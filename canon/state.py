"""The projection: what the ledger says is true, and what used to be.

project(records) is a pure function of the ordered records. Same ledger, same
canon, on any machine, in any process. Everything a caller can ask (current
value, history, value as of a turn or a story time) is read off intervals that
the records opened and closed; nothing is ever deleted, so "what was her outfit
at turn 200" has an answer after she changed it.

Two kinds of slot, decided by the slot's name (ledger.slot_class), with
different rules for a second value:

  identity ("identity.hair")  FIRST WRITE WINS. The same value corroborates. A
      different value is a CONFLICT unless it comes from a strictly higher
      authority or an explicit retcon/author_edit. Narration drifting to a new
      hair colour is exactly the failure this exists to catch, so it is recorded
      as disputed instead of silently applied.

  state ("state.outfit")      LATEST WINS. A character changing clothes is the
      story working, so a later value closes the earlier interval and opens its
      own. Authority does not pin state: scenario and author set the STARTING
      state, and play has to be able to change it, so narration may supersede
      anything. Only `inferred` (a guess) cannot overwrite narrated state.

A conflict never changes canon and never raises. It is kept in `conflicts` so a
person can see what was disputed and decide.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Iterable

from canon.ledger import (AUTHORITY, OVERRIDE_KINDS, Record, canonical,
                          slot_class)


@dataclass
class Interval:
    value: str | list[str]
    cls: str
    kind: str
    authority: str
    start_id: int
    start_turn: int
    start_world: int | None
    source_turn: int | None
    span: str
    confirmations: int = 1
    end_id: int | None = None
    end_turn: int | None = None
    end_world: int | None = None
    # The turn this value was last RESTATED, None until it is (last_seen() then falls
    # back to when it was opened). The ledger keeps
    # every record, so this is a fact about when the story last said it, and what a
    # card does with an old value is decided where the card is made (scene.py).
    last_turn: int | None = None

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def _plain(value):
    return list(value) if isinstance(value, tuple) else value


class Canon:
    def __init__(self) -> None:
        self.entities: dict[str, dict] = {}
        self.slots: dict[str, dict[str, list[Interval]]] = {}
        self.conflicts: list[dict] = []
        self.last_id = 0

    # --- writing: one record at a time (replay is repeated apply) ----------
    def apply(self, rec: Record) -> None:
        self.last_id = rec.id
        if rec.kind == "entity_created":
            self._create(rec)
            return
        if rec.entity not in self.entities:
            self._conflict(rec, "unknown_entity", None)
            return
        iv = self._open(rec.entity, rec.slot)
        value = _plain(rec.value)

        if rec.kind in OVERRIDE_KINDS:
            # Explicit, so it crosses the identity rule on purpose.
            if value is None:                    # a retraction: close it, open nothing
                if iv is None:
                    self._conflict(rec, "nothing_to_clear", None)
                else:
                    self._close(iv, rec)
                return
            if iv is not None and iv.value == value:
                self._restated(iv, rec)
                return
            self._close(iv, rec)
            self._open_new(rec, value)
        elif rec.kind == "state_cleared":
            if iv is None:
                self._conflict(rec, "nothing_to_clear", None)
            elif not self._may_supersede_state(iv, rec):
                self._conflict(rec, "lower_authority", iv.value)
            else:
                self._close(iv, rec)
        elif slot_class(rec.slot) == "identity":
            if iv is None:
                self._open_new(rec, value)
            elif iv.value == value:
                self._restated(iv, rec)
            elif AUTHORITY[rec.authority] > AUTHORITY[iv.authority]:
                self._close(iv, rec)
                self._open_new(rec, value)
            else:
                self._conflict(rec, "identity_locked", iv.value)
        else:
            if iv is not None and iv.value == value:
                self._restated(iv, rec)
            elif iv is not None and not self._may_supersede_state(iv, rec):
                self._conflict(rec, "lower_authority", iv.value)
            else:
                self._close(iv, rec)
                self._open_new(rec, value)

    def _create(self, rec: Record) -> None:
        if rec.entity in self.entities:
            self._conflict(rec, "entity_exists", self.entities[rec.entity]["name"])
            return
        self.entities[rec.entity] = {
            "name": rec.value, "type": rec.slot, "aliases": list(rec.aliases),
            "created_id": rec.id, "created_turn": rec.turn}
        self.slots[rec.entity] = {}

    def _open(self, entity: str, slot: str) -> Interval | None:
        ivs = self.slots.get(entity, {}).get(slot)
        return ivs[-1] if ivs and ivs[-1].end_id is None else None

    @staticmethod
    def _may_supersede_state(iv: Interval, rec: Record) -> bool:
        # Narration (2) is the floor for changing state, whatever set it. Only a
        # guess (1) is held back from overwriting something narrated or authored.
        return AUTHORITY[rec.authority] >= min(AUTHORITY[iv.authority],
                                               AUTHORITY["narration"])

    @staticmethod
    def _restated(iv: Interval, rec: Record) -> None:
        iv.confirmations += 1
        iv.last_turn = rec.turn

    @staticmethod
    def _close(iv: Interval | None, rec: Record) -> None:
        if iv is not None:
            iv.end_id, iv.end_turn, iv.end_world = rec.id, rec.turn, rec.world_time

    def _open_new(self, rec: Record, value) -> None:
        self.slots[rec.entity].setdefault(rec.slot, []).append(Interval(
            value=value, cls=slot_class(rec.slot), kind=rec.kind,
            authority=rec.authority, start_id=rec.id, start_turn=rec.turn,
            start_world=rec.world_time, source_turn=rec.source_turn,
            span=rec.span))

    def _conflict(self, rec: Record, reason: str, existing) -> None:
        self.conflicts.append({
            "id": rec.id, "turn": rec.turn, "entity": rec.entity,
            "slot": rec.slot, "kind": rec.kind, "reason": reason,
            "proposed": _plain(rec.value), "existing": existing})

    # --- reading -----------------------------------------------------------
    def current(self, entity: str, slot: str):
        iv = self._open(entity, slot)
        return None if iv is None else iv.value

    def last_seen(self, entity: str, slot: str) -> int | None:
        """The turn the slot's current value was last stated, or None when it has none."""
        iv = self._open(entity, slot)
        if iv is None:
            return None
        return iv.start_turn if iv.last_turn is None else iv.last_turn

    def history(self, entity: str, slot: str) -> list[dict]:
        return [iv.as_dict() for iv in self.slots.get(entity, {}).get(slot, [])]

    def value_at_turn(self, entity: str, slot: str, turn: int):
        """What the ledger knew about this slot after recording `turn`
        (transaction time)."""
        hit = None
        for iv in self.slots.get(entity, {}).get(slot, []):
            if iv.start_turn <= turn and (iv.end_turn is None or turn < iv.end_turn):
                hit = iv
        return None if hit is None else hit.value

    def value_at_world_time(self, entity: str, slot: str, world_time: int):
        """What was true in the story at `world_time` (valid time). Intervals
        with no story time recorded are skipped, not guessed."""
        hit = None
        for iv in self.slots.get(entity, {}).get(slot, []):
            if iv.start_world is None or iv.start_world > world_time:
                continue
            if iv.end_world is None and iv.end_id is not None:
                # Closed, but the closing record carried no story time, so when
                # it ended is unknown. It is known true at its own start and
                # unknown after it.
                if world_time == iv.start_world:
                    hit = iv
                continue
            if iv.end_world is None or world_time < iv.end_world:
                hit = iv
        return None if hit is None else hit.value

    def resolve(self, name: str) -> str | None:
        """Entity id for a name, alias or id; None when unknown OR ambiguous. A
        wrong merge is worse than a duplicate, so ambiguity is never guessed."""
        key = " ".join(name.lower().split())
        found = {eid for eid, e in self.entities.items()
                 if key == eid or key == e["name"].lower()
                 or key in (a.lower() for a in e["aliases"])}
        return next(iter(found)) if len(found) == 1 else None

    # --- plain-data form: equality, snapshots ------------------------------
    def as_dict(self) -> dict:
        return {
            "last_id": self.last_id,
            "entities": {k: self.entities[k] for k in sorted(self.entities)},
            "slots": {e: {s: [iv.as_dict() for iv in ivs]
                          for s, ivs in sorted(slots.items())}
                      for e, slots in sorted(self.slots.items())},
            "conflicts": list(self.conflicts),
        }

    def digest(self) -> str:
        return hashlib.sha256(canonical(self.as_dict()).encode("utf-8")).hexdigest()

    @staticmethod
    def from_dict(d: dict) -> "Canon":
        c = Canon()
        c.last_id = d["last_id"]
        c.entities = {k: dict(v) for k, v in d["entities"].items()}
        c.slots = {e: {s: [Interval(**iv) for iv in ivs]
                       for s, ivs in slots.items()}
                   for e, slots in d["slots"].items()}
        c.conflicts = [dict(x) for x in d["conflicts"]]
        return c


def project(records: Iterable[Record]) -> Canon:
    """Canon as of the end of `records`. Pure and deterministic."""
    c = Canon()
    for rec in records:
        c.apply(rec)
    return c
