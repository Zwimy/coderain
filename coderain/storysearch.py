"""Search of the story's own words (D-075): the passages a long story has scrolled past, found again.

A fold keeps what a summary keeps; the exact line someone said forty turns ago is gone from the prompt unless something finds it. This index
holds every passage of the transcript in SQLite: full-text search (FTS5, ranked by BM25) finds them by their words, and when semantic recall
is on, an embedding of each passage finds them by meaning; the two ranked lists are merged by reciprocal rank fusion.

`search.db` is DERIVED from the transcript and rebuildable (invariant 7): it is synced to the turns by content before every search, so an
undo, a retry, a swipe, an edit or a branch cannot leave an old line behind, and deleting the file only costs a rebuild. Only turns before the
verbatim history window are searched, since the window is already in the prompt. A failure is logged once and the turn goes on without it.
"""
from __future__ import annotations

import array
import hashlib
import math
import re
import sqlite3

PASSAGE_CHARS = 500
TOP_K = 3
MAX_YOURS = 1                   # of TOP_K, the player's own earlier lines (see search)
MAX_CHARS = 1500                # the whole section
CANDIDATES = 40                 # per ranked list, before the two are merged
RRF_K = 60
_ZW = chr(0x200B)                # zero-width: keeps a copied `{{macro}}` in story text from being expanded
EMBED_PER_CALL = 64             # new passages embedded per turn, so a long story catches up over a few turns instead of stalling one
MAX_TERMS = 24

# Words a story search must not be about. Kept short: BM25 already weighs common words down; this stops them from counting as a match.
STOPWORDS = frozenset("""
a about after again all also am an and any are as at back be because been before being but by can could did do does doing down for from
get go going had has have having he her here hers herself him himself his how i if in into is it its itself just know like look me more
most my myself no nor not now of off on once only or other our ours out over own say says said see she should so some such than that the
their theirs them themselves then there these they this those through to too under until up upon very want was we were what when where
which while who whom why will with would you your yours yourself tell ask asks asked around toward towards still then thing things
""".split())

_SENTENCE = re.compile(r"(?<=[.!?…])[\"'”’)]*\s+")


def passages(text: str) -> list[str]:
    """The turn cut into passages of at most PASSAGE_CHARS: paragraphs are kept whole and short neighbours joined; a long paragraph is cut
    at sentence ends, and a sentence longer than a passage at a space."""
    pieces: list[str] = []
    for para in re.split(r"\n\s*\n", text or ""):
        para = " ".join(para.split())
        if not para:
            continue
        if len(para) <= PASSAGE_CHARS:
            pieces.append(para)
            continue
        for sentence in _SENTENCE.split(para):
            while len(sentence) > PASSAGE_CHARS:
                cut = sentence.rfind(" ", 0, PASSAGE_CHARS)
                cut = cut if cut > 0 else PASSAGE_CHARS
                pieces.append(sentence[:cut].strip())
                sentence = sentence[cut:].strip()
            if sentence:
                pieces.append(sentence)
    out: list[str] = []
    for piece in pieces:
        if out and len(out[-1]) + 1 + len(piece) <= PASSAGE_CHARS:
            out[-1] += " " + piece
        else:
            out.append(piece)
    return out


def query_terms(text: str) -> list[str]:
    """The words of `text` to search for: the first MAX_TERMS of those worth searching."""
    return _words(text)[:MAX_TERMS]


def _words(text: str) -> list[str]:
    """The words of `text` worth searching for, in order, each once."""
    words = re.findall(r"[^\W_]+(?:'[^\W_]+)?", (text or "").lower())
    out: list[str] = []
    for w in words:
        w = w.split("'")[0]
        if len(w) >= 3 and w not in STOPWORDS and w not in out:
            out.append(w)
    return out


def _stem(term: str) -> str:
    """A crude prefix, so that "carries" counts as found in "carried". Only used to count how many of the words a passage holds."""
    return term if len(term) <= 4 else term[:max(4, len(term) - 3)]


def matched(terms: list[str], text: str) -> int:
    low = text.lower()
    return sum(1 for t in terms if re.search(r"\b" + re.escape(_stem(t)), low))


def adds_something(action_words: list[str], passage: str) -> bool:
    """Does the passage hold a word worth searching for that the action does not, in any form? One that holds none tells the writer
    nothing beyond the action it is already reading: an earlier copy of the same question, most of all."""
    said = " ".join(action_words)
    return any(not matched([w], said) for w in _words(passage))


def _hash(*parts: str) -> str:
    return hashlib.sha1("\x00".join(parts).encode("utf-8")).hexdigest()


def _cosine(a, b) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class StorySearch:
    def __init__(self, store, embedder=None):
        self.store = store
        self.embedder = embedder                    # an object with .embed(texts) and .model, or None: keyword search only
        self.path = store.path("search.db")
        self._embed_failed = False

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE IF NOT EXISTS turn_seen(turn INTEGER PRIMARY KEY, hash TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS passage(id INTEGER PRIMARY KEY, turn INTEGER, role TEXT, text TEXT, hash TEXT)")
        conn.execute("CREATE INDEX IF NOT EXISTS passage_turn ON passage(turn)")
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS passage_fts USING fts5(text, tokenize='porter unicode61 remove_diacritics 2')")
        conn.execute("CREATE TABLE IF NOT EXISTS passage_vec(hash TEXT, model TEXT, vec BLOB, PRIMARY KEY(hash, model))")
        return conn

    def sync(self, conn: sqlite3.Connection) -> int:
        """Bring the passages in line with the transcript, turn by turn, by content. -> how many turns were (re)indexed."""
        turns = self.store.turns()
        seen = dict(conn.execute("SELECT turn, hash FROM turn_seen"))
        changed = 0
        for n, t in enumerate(turns, 1):
            h = _hash(t["role"], t["text"])
            if seen.get(n) == h:
                continue
            self._drop(conn, n)
            for part in passages(t["text"]):
                cur = conn.execute("INSERT INTO passage(turn, role, text, hash) VALUES (?,?,?,?)", (n, t["role"], part, _hash(part)))
                conn.execute("INSERT INTO passage_fts(rowid, text) VALUES (?,?)", (cur.lastrowid, part))
            conn.execute("INSERT OR REPLACE INTO turn_seen(turn, hash) VALUES (?,?)", (n, h))
            changed += 1
        for n in [n for n in seen if n > len(turns)]:
            self._drop(conn, n)
            conn.execute("DELETE FROM turn_seen WHERE turn=?", (n,))
            changed += 1
        if changed:
            conn.commit()
        return changed

    @staticmethod
    def _drop(conn, turn: int) -> None:
        ids = [r[0] for r in conn.execute("SELECT id FROM passage WHERE turn=?", (turn,))]
        for i in ids:
            conn.execute("DELETE FROM passage_fts WHERE rowid=?", (i,))
        conn.execute("DELETE FROM passage WHERE turn=?", (turn,))

    def _by_words(self, conn, terms: list[str], before: int) -> list[int]:
        if not terms:
            return []
        match = " OR ".join('"' + t.replace('"', "") + '"' for t in terms)
        rows = conn.execute(
            "SELECT p.id, p.text FROM passage_fts JOIN passage p ON p.id = passage_fts.rowid "
            "WHERE passage_fts MATCH ? AND p.turn <= ? ORDER BY bm25(passage_fts), p.turn DESC LIMIT ?",
            (match, before, CANDIDATES)).fetchall()
        # one shared word is noise ("the door"); two, or the only one asked for, is a lead
        need = 2 if len(terms) > 1 else 1
        return [i for i, text in rows if matched(terms, text) >= need]

    def _by_meaning(self, conn, query: str, before: int) -> list[int]:
        if self.embedder is None or self._embed_failed:
            return []
        model = self.embedder.model
        try:
            missing = conn.execute(
                "SELECT DISTINCT p.hash, p.text FROM passage p LEFT JOIN passage_vec v ON v.hash = p.hash AND v.model = ? "
                "WHERE p.turn <= ? AND v.hash IS NULL ORDER BY p.turn DESC LIMIT ?", (model, before, EMBED_PER_CALL)).fetchall()
            if missing:
                vecs = self.embedder.embed([text for _h, text in missing])
                if len(vecs) == len(missing):
                    for (h, _t), v in zip(missing, vecs):
                        conn.execute("INSERT OR REPLACE INTO passage_vec(hash, model, vec) VALUES (?,?,?)",
                                     (h, model, array.array("f", v).tobytes()))
                    conn.commit()
            query_vec = self.embedder.embed([query])[0]
        except Exception as e:  # noqa: BLE001 - recall by meaning is best-effort; keyword search still runs
            self._embed_failed = True
            self.store.log_degraded("story-search", f"search by meaning is off for this session: {type(e).__name__}: {e}")
            return []
        scored = []
        for i, blob in conn.execute("SELECT p.id, v.vec FROM passage p JOIN passage_vec v ON v.hash = p.hash AND v.model = ? "
                                    "WHERE p.turn <= ?", (model, before)):
            a = array.array("f")
            a.frombytes(blob)
            scored.append((_cosine(query_vec, a), i))
        scored.sort(reverse=True)
        return [i for score, i in scored[:CANDIDATES] if score > 0.3]

    def search(self, query: str, before: int, top_k: int = TOP_K) -> list[tuple[int, str, str]]:
        """Up to `top_k` (turn, role, passage) from the first `before` turns that match `query`, at most one per turn, in story order.

        A passage that adds no word to the query is left out, and at most MAX_YOURS are the player's own lines. An action shares its
        words with the player's earlier actions, which are short and so rank first by keyword: unfiltered, 136 of 153 quotes in two
        measured runs were the player's own lines (D-075). One of them still has room, since what the player told someone is theirs."""
        if before <= 0:
            return []
        conn = self._connect()
        try:
            self.sync(conn)
            fused: dict[int, float] = {}
            for ranked in (self._by_words(conn, query_terms(query), before), self._by_meaning(conn, query, before)):
                for rank, i in enumerate(ranked, 1):
                    fused[i] = fused.get(i, 0.0) + 1.0 / (RRF_K + rank)
            picked: dict[int, tuple[int, str, str]] = {}
            said, yours = _words(query), 0
            for i, _score in sorted(fused.items(), key=lambda kv: (-kv[1], -kv[0])):
                turn, role, text = conn.execute("SELECT turn, role, text FROM passage WHERE id=?", (i,)).fetchone()
                if turn in picked or not adds_something(said, text):
                    continue
                if role == "player":
                    if yours >= MAX_YOURS:
                        continue
                    yours += 1
                picked[turn] = (turn, role, text)
                if len(picked) >= top_k:
                    break
            return [picked[t] for t in sorted(picked)]
        finally:
            conn.close()

    def block(self, query: str, before: int, top_k: int = TOP_K, max_chars: int = MAX_CHARS) -> str:
        """The lines for the prompt, or "". Each passage is quoted with its turn number, the player's own lines marked as theirs. A failure
        is logged and the turn runs without the section (invariant 2)."""
        try:
            found = self.search(query, before, top_k)
        except Exception as e:  # noqa: BLE001 - search must never cost a turn
            self.store.log_degraded("story-search", f"no story search this turn: {type(e).__name__}: {e}")
            return ""
        lines: list[str] = []
        used = 0
        for turn, role, text in found:
            # story text goes into the prompt after nothing: a `{{macro}}` in it must stay text, not be rolled or expanded again
            line = f"[T{turn}{', the player' if role == 'player' else ''}] {text}".replace("{{", "{" + _ZW + "{")
            if used + len(line) > max_chars:
                break
            lines.append(line)
            used += len(line) + 1
        return "\n".join(lines)
