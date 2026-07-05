"""Phase 5: derived vector index for semantic recall (optional module, toggle).

`index.db` (a per-save SQLite file) is DERIVED from the Markdown files and fully
rebuildable — never a second source of truth. Embeddings come from any OpenAI-
compatible embeddings endpoint (local Ollama `nomic-embed-text`, or a hosted model),
so recall stays pure BYO. Retrieval ranks candidates by

    semantic similarity  ×  importance  ×  reference-count  ×  recency-decay

so stale memories fade while warm, well-connected ones persist (the salience/decay
model from the roadmap). The module is inert unless `retrieval.enabled` is set and an
embeddings model is reachable; a failing embedder degrades to "no extra recall"
rather than breaking a turn.
"""
from __future__ import annotations

import array
import hashlib
import math
import sqlite3
from dataclasses import dataclass

from ..memory import INDEX_FILES, Entry, MemoryStore

# What gets embedded: the typed registries + the episodic scene summaries.
EMBED_SOURCES = INDEX_FILES + ["memory/scenes.md"]

DEFAULTS = {
    "embed_model": "nomic-embed-text",
    "top_k": 4,
    "half_life_turns": 40,      # a memory's recency weight halves every N turns untouched
    "min_similarity": 0.15,     # ignore weak semantic matches
    "weight_importance": 1.0,
    "weight_references": 1.0,
}


def cfg_get(cfg: dict | None, key: str):
    if cfg and cfg.get(key) is not None:
        return cfg[key]
    return DEFAULTS[key]


def _hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _pack(vec: list[float]) -> bytes:
    return array.array("f", vec).tobytes()


def _unpack(blob: bytes) -> array.array:
    a = array.array("f")
    a.frombytes(blob)
    return a


def _cosine(a, b) -> float:
    if len(a) != len(b):
        return 0.0
    dot = na = nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / math.sqrt(na * nb)


class Embedder:
    """Thin wrapper over an OpenAI-compatible embeddings endpoint. Reuses the same
    client (base_url / api_key) as the chat model, so it's provider-agnostic."""

    def __init__(self, client, model: str):
        self.client = client
        self.model = model

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        resp = self.client.embeddings.create(model=self.model, input=texts)
        # Preserve request order (some providers return an `index` field).
        data = sorted(resp.data, key=lambda d: getattr(d, "index", 0))
        return [list(d.embedding) for d in data]


@dataclass
class _Hit:
    slug: str
    rel: str
    score: float


class VectorIndex:
    """Manages a save's derived `index.db`. Rebuilt incrementally from the Markdown
    (only changed entries are re-embedded); deleting the file simply forces a full
    rebuild on the next sync."""

    def __init__(self, store: MemoryStore, embedder: Embedder):
        self.store = store
        self.embedder = embedder
        self.db_path = store.path("index.db")

    def _connect(self) -> sqlite3.Connection:
        # timeout + WAL so the GUI worker thread's writes don't hit "database is
        # locked" against a concurrent read (Memory-tab save, overlapping turn).
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS vec("
            "slug TEXT PRIMARY KEY, rel TEXT, hash TEXT, importance INTEGER, "
            "ref_count INTEGER, last_turn INTEGER, vec BLOB)")
        return conn

    # --- source of truth: the Markdown entries ---
    def _gather(self) -> list[dict]:
        idx = self.store.index()
        refs = idx.ref_counts
        model = self.embedder.model
        items: list[dict] = []
        seen: set[str] = set()

        def add(slug: str, rel: str, e: Entry) -> None:
            if slug in seen:
                return
            text = " ".join(x for x in [e.title, " ".join(e.aliases),
                                        e.attrs.get("status", ""), e.body] if x).strip()
            if not text:                       # nothing to embed — skip (M6)
                return
            seen.add(slug)
            items.append({
                "slug": slug, "rel": rel, "text": text,
                # model is part of the hash: switching embed models invalidates every
                # row and forces a clean re-embed (no silent dim-mismatch — M3).
                "hash": _hash(model + "\x00" + text),
                "importance": e.importance, "ref_count": int(refs.get(slug, 0))})

        # Per-save sources: the built-in registries plus any custom lore files
        # this save declares (Wave 2) — MemoryIndex already spans both.
        sources = set(self.store.index_files()) | set(EMBED_SOURCES)
        for slug, (rel, e) in idx.entries.items():
            if rel in sources:
                add(slug, rel, e)
        # Scene summaries live in memory/scenes.md, which MemoryIndex does NOT index
        # (INDEX_FILES only), so add them explicitly — they're the aging episodic
        # memory the decay/salience model is meant to resurface (H1).
        for e in self.store.entries("memory/scenes.md"):
            add(e.slug, "memory/scenes.md", e)
        return items

    def sync(self, now_turn: int) -> int:
        """Bring index.db in line with the Markdown. Returns how many entries were
        (re)embedded this call (0 when nothing changed)."""
        conn = self._connect()
        try:
            existing = {row[0]: row[1] for row in
                        conn.execute("SELECT slug, hash FROM vec")}
            items = self._gather()
            live = {it["slug"] for it in items}
            to_embed = []
            for it in items:
                if existing.get(it["slug"]) != it["hash"]:
                    to_embed.append(it)
                else:
                    # cheap metadata refresh without re-embedding
                    conn.execute("UPDATE vec SET importance=?, ref_count=? WHERE slug=?",
                                 (it["importance"], it["ref_count"], it["slug"]))
            if to_embed:
                vecs = self.embedder.embed([it["text"] for it in to_embed])
                if len(vecs) != len(to_embed):
                    # Provider returned an inconsistent batch — don't half-write the
                    # index (zip would silently truncate). Leave it unchanged (no
                    # commit) and retry next turn.
                    return 0
                for it, v in zip(to_embed, vecs):
                    conn.execute(
                        "INSERT OR REPLACE INTO vec"
                        "(slug, rel, hash, importance, ref_count, last_turn, vec) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (it["slug"], it["rel"], it["hash"], it["importance"],
                         it["ref_count"], now_turn, _pack(v)))
            stale = [s for s in existing if s not in live]
            for s in stale:
                conn.execute("DELETE FROM vec WHERE slug=?", (s,))
            conn.commit()
            return len(to_embed)
        finally:
            conn.close()

    def search(self, query: str, k: int, exclude: set[str], now_turn: int,
               cfg: dict | None = None) -> list[_Hit]:
        """Return up to k salient entries semantically related to `query`, excluding
        slugs already in context. Salience = similarity × importance × ref-count ×
        recency-decay."""
        half_life = max(1, int(cfg_get(cfg, "half_life_turns")))
        min_sim = float(cfg_get(cfg, "min_similarity"))
        w_imp = float(cfg_get(cfg, "weight_importance"))
        w_ref = float(cfg_get(cfg, "weight_references"))
        try:
            qv = self.embedder.embed([query])[0]
        except Exception:  # noqa: BLE001 — no embeddings endpoint -> no extra recall
            return []
        conn = self._connect()
        try:
            rows = conn.execute("SELECT slug, rel, importance, ref_count, last_turn, "
                                "vec FROM vec").fetchall()
        finally:
            conn.close()
        hits: list[_Hit] = []
        for slug, rel, importance, ref_count, last_turn, blob in rows:
            if slug in exclude:
                continue
            sim = _cosine(qv, _unpack(blob))
            if sim < min_sim:
                continue
            imp_w = 0.5 + 0.5 * (max(1, min(5, importance)) / 5) * w_imp
            ref_w = 1.0 + w_ref * math.log1p(max(0, ref_count))
            decay = 0.5 ** (max(0, now_turn - last_turn) / half_life)
            hits.append(_Hit(slug, rel, sim * imp_w * ref_w * decay))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:k]


class Retriever:
    """Callable passed into MemoryStore.assemble(): given the turn's context text and
    the slugs already injected, returns extra Entry objects to recall. Syncs the index
    first (cheap when nothing changed) and degrades to [] on any failure."""

    def __init__(self, store: MemoryStore, index: VectorIndex, cfg: dict | None):
        self.store = store
        self.index = index
        self.cfg = cfg or {}
        self.top_k = int(cfg_get(self.cfg, "top_k"))

    def __call__(self, query: str, exclude: set[str]) -> list[Entry]:
        try:
            now = len(self.store.turns())
            self.index.sync(now)
            hits = self.index.search(query, self.top_k, exclude, now, self.cfg)
            # Resolve slugs to Entry objects, including scene summaries (which aren't
            # in MemoryIndex) so a scene hit isn't silently dropped.
            resolved = {slug: e for slug, (_, e) in self.store.index().entries.items()}
            for e in self.store.entries("memory/scenes.md"):
                resolved.setdefault(e.slug, e)
            return [resolved[h.slug] for h in hits if h.slug in resolved]
        except Exception:  # noqa: BLE001 — recall is best-effort, never a turn-breaker
            return []


def build_retriever(store: MemoryStore, client, cfg: dict | None) -> Retriever | None:
    """Construct a Retriever if retrieval is enabled; else None (recall stays off)."""
    cfg = cfg or {}
    if not cfg.get("enabled"):
        return None
    embedder = Embedder(client, str(cfg_get(cfg, "embed_model")))
    return Retriever(store, VectorIndex(store, embedder), cfg)
