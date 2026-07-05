"""Player character profiles (Phase 6): reusable characters, picked per save.

A profile is app-level (characters.json at the library root), NOT part of any
save — the same character can start many scenarios. Applying one to a save
writes a normal player.md entry, so the established rule holds: Markdown is
the source of truth, and `_sync_player_stats` carries the baselines into
state.json on every open.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from .memory import Entry, MemoryStore

# The form's stat order (mirrors the default rpg stats list).
STAT_NAMES = ["strength", "agility", "intelligence", "knowledge",
              "willpower", "charisma"]


class CharacterProfiles:
    """CRUD over characters.json — [{id, name, description, traits, stats,
    skills, created}]."""

    def __init__(self, root: str | Path):
        self.path = Path(root) / "characters.json"

    def _read(self) -> list[dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return []
        return data if isinstance(data, list) else []

    def _write(self, chars: list[dict]) -> None:
        self.path.write_text(json.dumps(chars, indent=2, ensure_ascii=False),
                             encoding="utf-8")

    def list(self) -> list[dict]:
        return self._read()

    def get(self, cid: str) -> dict | None:
        return next((c for c in self._read() if c.get("id") == cid), None)

    def save(self, char: dict) -> dict:
        """Create (no/unknown id) or update (existing id) a character."""
        chars = self._read()
        clean = _clean_character(char)
        cid = str(char.get("id") or "").strip()
        cur = next((c for c in chars if c.get("id") == cid), None) if cid \
            else None
        if cur is None:
            clean["id"] = cid or uuid.uuid4().hex[:12]
            clean["created"] = time.time()
            chars.append(clean)
        else:
            clean["id"] = cid
            clean["created"] = cur.get("created", time.time())
            chars[chars.index(cur)] = clean
        self._write(chars)
        return clean

    def delete(self, cid: str) -> bool:
        chars = self._read()
        kept = [c for c in chars if c.get("id") != cid]
        if len(kept) == len(chars):
            return False
        self._write(kept)
        return True


def _clean_character(char: dict) -> dict:
    name = str(char.get("name", "")).strip() or "Unnamed"
    stats = char.get("stats") if isinstance(char.get("stats"), dict) else {}
    out_stats = {}
    for k in STAT_NAMES:
        try:
            out_stats[k] = max(-5, min(10, int(stats.get(k, 1))))
        except (TypeError, ValueError):
            out_stats[k] = 1
    kind = str(char.get("kind", "")).strip().lower()
    try:
        importance = max(1, min(5, int(char.get("importance", 4))))
    except (TypeError, ValueError):
        importance = 4
    extra = char.get("extra") if isinstance(char.get("extra"), dict) else {}
    return {
        "name": name,
        # playable sheet (drop in as the protagonist) vs reusable NPC;
        # profiles created before kinds existed count as playable.
        "kind": kind if kind in ("playable", "npc") else "playable",
        "description": str(char.get("description", "")).strip(),
        "traits": str(char.get("traits", "")).strip(),
        "skills": str(char.get("skills", "")).strip(),
        "stats": out_stats,
        "aliases": [str(a).strip() for a in (char.get("aliases") or [])
                    if str(a).strip()],
        "importance": importance,
        # any further entry attrs (weight/triggers/pinned/hidden/status…) —
        # kept verbatim so library -> world -> library round-trips lossless.
        "extra": {str(k): str(v) for k, v in extra.items()
                  if str(v).strip()},
    }


def apply_character(store: MemoryStore, char: dict) -> None:
    """Seed a save's player.md from a profile. Written as the regular `player`
    entry — md wins on open, so stats flow into the rpg block automatically."""
    clean = _clean_character(char)
    body = clean["description"] or f"{clean['name']}, the protagonist."
    if clean["traits"]:
        body += f"\n\nTraits: {clean['traits']}"
    attrs = {"stats": ", ".join(f"{k} {v}"
                                for k, v in clean["stats"].items())}
    if clean["skills"]:
        attrs["skills"] = clean["skills"]
    store.upsert_entry("player.md", Entry(
        title=clean["name"], slug="player", importance=5,
        attrs=attrs, body=body))


class PieceLibrary:
    """Reusable lore pieces of ANY type — locations, items, factions,
    threads, events, custom (library.json at the app root):
    ``[{id, type, entry, created}]`` where `entry` is the plain entry dict
    the web API trades in ({title, slug, aliases, importance, attrs, body}).
    Characters keep their own richer store (characters.json / play-as)."""

    def __init__(self, root: str | Path):
        self.path = Path(root) / "library.json"

    def _read(self) -> list[dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return []
        return data if isinstance(data, list) else []

    def _write(self, items: list[dict]) -> None:
        self.path.write_text(json.dumps(items, indent=2, ensure_ascii=False),
                             encoding="utf-8")

    def list(self, type_: str = "") -> list[dict]:
        items = self._read()
        if type_:
            items = [p for p in items if p.get("type") == type_]
        return items

    def get(self, pid: str) -> dict | None:
        return next((p for p in self._read() if p.get("id") == pid), None)

    def types(self) -> list[str]:
        return sorted({str(p.get("type", "")) for p in self._read()
                       if p.get("type")})

    def save(self, type_: str, entry: dict, pid: str = "") -> dict:
        """Create (no/unknown id) or update (existing id) a library piece."""
        from .templates import slugify
        type_ = slugify(str(type_ or "piece").removesuffix(".md"))
        title = str(entry.get("title", "")).strip()
        if not title:
            raise ValueError("a library piece needs a title")
        clean = {
            "title": title,
            "slug": slugify(str(entry.get("slug", "")).strip() or title),
            "aliases": [str(a).strip() for a in (entry.get("aliases") or [])
                        if str(a).strip()],
            "importance": max(1, min(5, int(entry.get("importance", 3) or 3))),
            "attrs": {str(k): str(v)
                      for k, v in (entry.get("attrs") or {}).items()
                      if str(v).strip()},
            "body": str(entry.get("body", "")).strip(),
        }
        items = self._read()
        cur = next((p for p in items if p.get("id") == pid), None) if pid \
            else None
        if cur is None:
            rec = {"id": pid or uuid.uuid4().hex[:12], "type": type_,
                   "entry": clean, "created": time.time()}
            items.append(rec)
        else:
            cur.update({"type": type_, "entry": clean})
            rec = cur
        self._write(items)
        return rec

    def delete(self, pid: str) -> bool:
        items = self._read()
        kept = [p for p in items if p.get("id") != pid]
        if len(kept) == len(items):
            return False
        self._write(kept)
        return True

    def entry(self, pid: str) -> Entry | None:
        rec = self.get(pid)
        if rec is None:
            return None
        d = rec.get("entry") or {}
        return Entry(title=d.get("title", ""), slug=d.get("slug", ""),
                     aliases=list(d.get("aliases") or []),
                     importance=int(d.get("importance", 3) or 3),
                     attrs=dict(d.get("attrs") or {}),
                     body=d.get("body", ""))


# Entry attrs the character shape manages explicitly — everything else rides
# in the profile's `extra` dict (lossless round-trip).
_CHAR_MANAGED_ATTRS = {"stats", "skills", "playable"}


def entry_from_character(char: dict) -> Entry:
    """A library character as a characters.md piece (for dropping it into a
    scenario). Playable sheets carry `playable: true` so the new-story dialog
    offers them for that world; NPCs land as plain cast."""
    from .templates import slugify
    clean = _clean_character(char)
    body = clean["description"] or f"{clean['name']}."
    if clean["traits"]:
        body += f"\n\nTraits: {clean['traits']}"
    attrs: dict[str, str] = dict(clean["extra"])
    attrs["stats"] = ", ".join(f"{k} {v}"
                               for k, v in clean["stats"].items())
    if clean["skills"]:
        attrs["skills"] = clean["skills"]
    if clean["kind"] == "playable":
        attrs["playable"] = "true"
    else:
        attrs.pop("playable", None)
    return Entry(title=clean["name"], slug=slugify(clean["name"]),
                 aliases=list(clean["aliases"]),
                 importance=clean["importance"], attrs=attrs, body=body)


def character_from_entry(e: Entry) -> dict:
    """The reverse: a scenario piece saved back into the library (id-less —
    CharacterProfiles.save assigns one)."""
    body = e.body.strip()
    traits = ""
    if "\nTraits: " in "\n" + body:
        body, _, traits = body.rpartition("\nTraits: ")
        body = body.strip()
    playable = str(e.attrs.get("playable", "")).strip().lower() in \
        ("true", "yes", "1", "on")
    return _clean_character({
        "name": e.title,
        "kind": "playable" if playable else "npc",
        "description": body,
        "traits": traits.strip(),
        "skills": e.attrs.get("skills", ""),
        "stats": e.stats(),
        "aliases": e.aliases,
        "importance": e.importance,
        "extra": {k: v for k, v in e.attrs.items()
                  if k not in _CHAR_MANAGED_ATTRS},
    })


def apply_playable_entry(store: MemoryStore, entry: Entry) -> None:
    """Start a story AS one of the scenario's playable characters: seed the
    save's player.md from that piece (same md-wins flow as apply_character).
    The characters.md entry stays — the world still knows who they are."""
    attrs: dict[str, str] = {}
    stats = entry.stats()
    if stats:
        attrs["stats"] = ", ".join(f"{k} {v}" for k, v in stats.items())
    if entry.attrs.get("skills", "").strip():
        attrs["skills"] = entry.attrs["skills"].strip()
    if entry.attrs.get("abilities", "").strip():
        attrs["abilities"] = entry.attrs["abilities"].strip()
    body = entry.body.strip() or f"{entry.title}, the protagonist."
    store.upsert_entry("player.md", Entry(
        title=entry.title, slug="player", importance=5,
        attrs=attrs, body=body))
