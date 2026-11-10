"""The ledger: the only truth.

Every change to what the story has established is one line in an append-only
file. State is a projection of it (state.py); summaries and indexes are caches
that can be rebuilt from it. That makes a bad extraction recoverable, which a
fold that rewrites a paragraph in place is not.

Four properties this module owns:

  * Append-only. The one sanctioned way to shorten it is truncate(), which is
    what undo and branching are.
  * Hash-chained. Each line carries sha256(previous hash + this record), so a
    truncated, reordered or hand-edited ledger is detected on open instead of
    silently producing a different story. This is the structural answer to a
    snapshot that no longer matches its ledger.
  * Bounded. Everything that reaches the ledger came from a model, so every value
    has a length and cardinality bound. A value over the bound is REJECTED, not
    truncated: a clipped fact is a wrong fact with a confident look.
  * Crash-safe. A torn final line (a write cut short) is dropped and reported in
    `recovered`; corruption anywhere else raises.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

# Who said it, lowest to highest. Used to settle clashes (state.py).
AUTHORITY = {"inferred": 1, "narration": 2, "scenario": 3, "author": 4}

STATE_KINDS = frozenset({"state_set", "item_moved", "location_changed",
                         "relationship_set", "knowledge_gained"})
OVERRIDE_KINDS = frozenset({"retcon", "author_edit"})
KINDS = frozenset({"entity_created", "fact_established", "state_cleared"}
                  | STATE_KINDS | OVERRIDE_KINDS)

MAX_ID, MAX_SLOT = 64, 64
MAX_NAME, MAX_ITEM, MAX_VALUE = 120, 120, 400
MAX_LIST, MAX_SPAN, MAX_ALIASES = 16, 400, 16

_ID_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
_SLOT_RE = re.compile(r"[a-z0-9][a-z0-9_.-]{0,63}\Z")


class LedgerError(ValueError):
    """A record the ledger refuses."""


class LedgerCorrupt(RuntimeError):
    """The ledger file does not match its own hash chain."""


def slot_class(slot: str) -> str:
    """'state' for mutable slots, 'identity' for everything else.

    The layer is a property of the slot NAME, decided before any value arrives.
    Identity ("eyes: green") and state ("wearing: grey coat, wet") therefore can
    never share a slot, and no model decides which one a fact is.
    """
    return "state" if slot.startswith("state.") else "identity"


@dataclass(frozen=True)
class Record:
    id: int
    turn: int                      # transaction time: when the ledger learned it
    kind: str
    entity: str
    slot: str
    value: str | tuple[str, ...] | None
    authority: str
    world_time: int | None = None  # valid time: when it became true in the story
    source_turn: int | None = None
    span: str = ""
    aliases: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {"id": self.id, "turn": self.turn, "kind": self.kind,
                "entity": self.entity, "slot": self.slot,
                "value": list(self.value) if isinstance(self.value, tuple)
                else self.value,
                "authority": self.authority, "world_time": self.world_time,
                "source_turn": self.source_turn, "span": self.span,
                "aliases": list(self.aliases)}

    @staticmethod
    def from_dict(d: dict) -> "Record":
        v = d.get("value")
        return Record(
            id=d["id"], turn=d["turn"], kind=d["kind"], entity=d["entity"],
            slot=d["slot"], value=tuple(v) if isinstance(v, list) else v,
            authority=d["authority"], world_time=d.get("world_time"),
            source_turn=d.get("source_turn"), span=d.get("span", ""),
            aliases=tuple(d.get("aliases", ())))


def _line(value, limit: int, what: str, *, required: bool = True) -> str:
    """One bounded line of text: whitespace collapsed, over-limit REJECTED."""
    if not isinstance(value, str):
        raise LedgerError(f"{what} must be text, got {type(value).__name__}")
    out = " ".join(value.split())
    if required and not out:
        raise LedgerError(f"{what} is empty")
    if len(out) > limit:
        raise LedgerError(f"{what} is {len(out)} characters; the limit is {limit}")
    return out


def _int(value, what: str, *, optional: bool = False) -> int | None:
    if value is None and optional:
        return None
    # bool is an int subclass; True as a turn number is a bug, not a turn.
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LedgerError(f"{what} must be a non-negative integer")
    return value


def make_record(rid: int, **f) -> Record:
    """Validate raw fields into a Record, or raise LedgerError."""
    kind = f.get("kind")
    if kind not in KINDS:
        raise LedgerError(f"unknown kind {kind!r}")
    authority = f.get("authority")
    if authority not in AUTHORITY:
        raise LedgerError(f"unknown authority {authority!r}")
    entity = f.get("entity")
    if not isinstance(entity, str) or not _ID_RE.match(entity):
        raise LedgerError(f"entity id {entity!r} must match [a-z0-9][a-z0-9_-]*")
    turn = _int(f.get("turn"), "turn")
    world = _int(f.get("world_time"), "world_time", optional=True)
    src = _int(f.get("source_turn"), "source_turn", optional=True)
    span = _line(f.get("span", ""), MAX_SPAN, "span", required=False)

    if kind == "entity_created":
        name = _line(f.get("value"), MAX_NAME, "entity name")
        etype = f.get("slot") or ""
        if not isinstance(etype, str) or not _SLOT_RE.match(etype):
            raise LedgerError("entity_created needs a type in `slot` "
                              "(character, location, item, ...)")
        raw = f.get("aliases") or ()
        if isinstance(raw, str) or len(raw) > MAX_ALIASES:
            raise LedgerError(f"aliases must be a list of at most {MAX_ALIASES}")
        aliases = tuple(dict.fromkeys(_line(a, MAX_NAME, "alias") for a in raw))
        return Record(rid, turn, kind, entity, etype, name, authority, world,
                      src, span, aliases)

    slot = f.get("slot")
    if not isinstance(slot, str) or not _SLOT_RE.match(slot):
        raise LedgerError(f"slot {slot!r} must match [a-z0-9][a-z0-9_.-]*")
    cls = slot_class(slot)
    # The layer rule: kind and slot must agree, except for the explicit
    # overrides, which exist precisely to cross it.
    if kind == "fact_established" and cls == "state":
        raise LedgerError("fact_established targets identity; "
                          f"{slot!r} is a state slot (use state_set)")
    if (kind in STATE_KINDS or kind == "state_cleared") and cls != "state":
        raise LedgerError(f"{kind} targets state; {slot!r} is an identity slot "
                          "(use fact_established, retcon or author_edit)")
    if kind == "author_edit" and authority != "author":
        raise LedgerError("author_edit must carry authority 'author'")
    if kind == "retcon" and authority not in ("author", "scenario"):
        raise LedgerError("retcon needs authority 'author' or 'scenario'")

    if kind == "state_cleared":
        if f.get("value") is not None:
            raise LedgerError("state_cleared takes no value")
        value = None
    else:
        raw = f.get("value")
        if isinstance(raw, (list, tuple)):
            if not raw or len(raw) > MAX_LIST:
                raise LedgerError(f"a list value needs 1 to {MAX_LIST} items")
            value = tuple(_line(x, MAX_ITEM, "list item") for x in raw)
        else:
            value = _line(raw, MAX_VALUE, "value")
    return Record(rid, turn, kind, entity, slot, value, authority, world, src,
                  span)


def canonical(obj) -> str:
    """The one JSON form used for hashing and for the file. Same input, same
    bytes, on every machine."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def chain(prev: str, record_dict: dict) -> str:
    return hashlib.sha256(
        (prev + "\n" + canonical(record_dict)).encode("utf-8")).hexdigest()


class Ledger:
    """The file, its records, and its hash chain. Single writer."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.records: list[Record] = []
        self._hashes: list[str] = []
        self.recovered = 0          # torn final lines dropped on open
        self._load()

    # --- reading ----------------------------------------------------------
    def _load(self) -> None:
        if not self.path.exists():
            return
        raw = self.path.read_bytes()
        lines = raw.split(b"\n")
        torn = lines[-1] != b""          # no trailing newline: a cut-short write
        complete = lines[:-1]
        prev = ""
        for n, line in enumerate(complete, start=1):
            try:
                obj = json.loads(line.decode("utf-8"))
                rec, h = Record.from_dict(obj["r"]), obj["h"]
            except (ValueError, KeyError, TypeError) as exc:
                raise LedgerCorrupt(f"line {n} is not a ledger record: {exc}")
            if rec.id != n:
                raise LedgerCorrupt(f"line {n} carries id {rec.id}")
            if chain(prev, obj["r"]) != h:
                raise LedgerCorrupt(f"line {n} fails the hash chain")
            self.records.append(rec)
            self._hashes.append(h)
            prev = h
        if torn:
            self.recovered = 1
            self._rewrite()              # drop the partial line from the file

    def __len__(self) -> int:
        return len(self.records)

    @property
    def head(self) -> str:
        return self._hashes[-1] if self._hashes else ""

    def hash_at(self, record_id: int) -> str:
        """Chain hash after record `record_id` (0 = the empty ledger)."""
        return "" if record_id == 0 else self._hashes[record_id - 1]

    # --- writing ----------------------------------------------------------
    def append(self, **fields) -> Record:
        if self.records and fields.get("turn") is not None \
                and isinstance(fields["turn"], int) \
                and fields["turn"] < self.records[-1].turn:
            raise LedgerError(
                f"turn {fields['turn']} is before the last record "
                f"(turn {self.records[-1].turn}); the ledger never goes back")
        rec = make_record(len(self.records) + 1, **fields)
        d = rec.to_dict()
        h = chain(self.head, d)
        data = (canonical({"r": d, "h": h}) + "\n").encode("utf-8")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "ab") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        self.records.append(rec)
        self._hashes.append(h)
        return rec

    def truncate(self, after_turn: int) -> int:
        """Drop every record recorded after `after_turn`. Returns how many.

        This is undo and branching: the ledger's one sanctioned shortening. Turns
        never decrease, so what is dropped is always a suffix and the chain of the
        remaining prefix is unchanged.
        """
        keep = sum(1 for r in self.records if r.turn <= after_turn)
        removed = len(self.records) - keep
        if removed:
            del self.records[keep:]
            del self._hashes[keep:]
            self._rewrite()
        return removed

    def _rewrite(self) -> None:
        """Write the in-memory ledger to disk atomically."""
        lines = [canonical({"r": r.to_dict(), "h": h}) + "\n"
                 for r, h in zip(self.records, self._hashes)]
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text("".join(lines), encoding="utf-8", newline="")
        os.replace(tmp, self.path)
