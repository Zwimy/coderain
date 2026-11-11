"""One turn through the Scribe: read the prose, validate, commit.

    prose -> Scribe (model) -> claims -> validate (code) -> ledger records

The roster handed to the Scribe is the story's known characters, those named in
the prose first. It is only there so the model uses the right names; the Scribe is
NOT shown canon's current values, because a model told "her hair is raven" will
tend to confirm it. Comparing a claim with canon is code's job.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from canon.scribe import Extraction, Scribe
from canon.state import Canon
from canon.store import Store
from canon.validate import Decision, Who, commit, validate


@dataclass
class TurnReport:
    turn: int
    extraction: Extraction
    decisions: list[Decision]
    committed: list

    def counts(self) -> dict:
        c = Counter(d.status for d in self.decisions)
        c["claims"] = len(self.extraction.claims)
        c["rejected_shape"] = len(self.extraction.rejects)
        return dict(c)


def roster_for(canon: Canon, prose: str, limit: int = 40) -> list[dict]:
    low = prose.lower()

    def named(e) -> bool:
        return any(re.search(r"\b" + re.escape(n.lower()) + r"\b", low)
                   for n in [e["name"], *e["aliases"]])

    ents = list(canon.entities.values())
    ents.sort(key=lambda e: (not named(e), e["created_id"]))
    return [{"name": e["name"], "aliases": e["aliases"]} for e in ents[:limit]]


def process_turn(store: Store, turn: int, prose: str, scribe: Scribe, *,
                 record_contradictions: bool = False, min_confidence: str = "medium",
                 create_unknown: bool = True, world_time: int | None = None,
                 roster_limit: int = 40, who: Who | None = None,
                 refused: dict | None = None) -> TurnReport:
    ext = scribe.extract(prose, roster_for(store.canon, prose, roster_limit))
    decisions = validate(
        store.canon, ext.claims, prose, turn=turn, next_id=len(store.ledger) + 1,
        min_confidence=min_confidence, create_unknown=create_unknown,
        world_time=world_time, who=who, refused=refused)
    written = commit(store, decisions, record_contradictions=record_contradictions)
    return TurnReport(turn, ext, decisions, written)
