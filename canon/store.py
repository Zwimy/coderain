"""Ledger + projection + a snapshot that is only ever a cache.

The ledger is the truth. The snapshot exists so opening a long story does not
replay thousands of records, and it is trusted only when it provably matches the
ledger. Three ways it can fail to, each handled the same way (rebuild, never
guess): the snapshot is missing, the ledger no longer reaches the snapshot's
record or has a different history there (an undo, a branch, an edit), or the
snapshot's own contents do not match their digest. This is the failure that
docs/DECISIONS.md D-006 records in the current engine, where a pre-fold snapshot
could outlive the timeline it described and a fork inherited stale state.

A snapshot OLDER than the ledger is normal and cheap: the records after it are
replayed on top.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from canon.ledger import Ledger, Record, canonical
from canon.state import Canon, project

SNAPSHOT = "canon.snapshot.json"
LEDGER = "ledger.jsonl"


class Store:
    def __init__(self, directory: str | Path):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.ledger = Ledger(self.dir / LEDGER)
        self.canon: Canon
        self.opened_from = ""        # "snapshot", "snapshot+replay" or "rebuild"
        self._open()

    # --- opening -----------------------------------------------------------
    def _open(self) -> None:
        snap = self._read_snapshot()
        if snap is None:
            self.canon, self.opened_from = project(self.ledger.records), "rebuild"
            return
        canon, last_id = snap
        tail = self.ledger.records[last_id:]
        for rec in tail:
            canon.apply(rec)
        self.canon = canon
        self.opened_from = "snapshot+replay" if tail else "snapshot"

    def _read_snapshot(self) -> tuple[Canon, int] | None:
        path = self.dir / SNAPSHOT
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            last_id, head = data["last_id"], data["head"]
            canon = Canon.from_dict(data["canon"])
        except (OSError, ValueError, KeyError, TypeError):
            return None                              # missing or unreadable
        if not isinstance(last_id, int) or not 0 <= last_id <= len(self.ledger):
            return None                              # ledger no longer reaches it
        if self.ledger.hash_at(last_id) != head:
            return None                              # same length, other history
        if canon.last_id != last_id or canon.digest() != data.get("digest"):
            return None                              # contents altered
        return canon, last_id

    # --- writing -----------------------------------------------------------
    def append(self, **fields) -> Record:
        rec = self.ledger.append(**fields)
        self.canon.apply(rec)
        return rec

    def undo_to(self, turn: int) -> int:
        """Forget everything recorded after `turn`. Truncating the ledger and
        re-deriving is the whole operation; there is no separate rollback path
        that could disagree with it."""
        removed = self.ledger.truncate(turn)
        if removed:
            self.canon = project(self.ledger.records)
            self._drop_snapshot_if_stale()
        return removed

    def _drop_snapshot_if_stale(self) -> None:
        if self._read_snapshot() is None:
            try:
                (self.dir / SNAPSHOT).unlink()
            except FileNotFoundError:
                pass

    def rebuild(self) -> None:
        """Throw the projection away and derive it again from the ledger."""
        self.canon = project(self.ledger.records)
        self.opened_from = "rebuild"

    def save_snapshot(self) -> None:
        payload = {"last_id": self.canon.last_id, "head": self.ledger.head,
                   "digest": self.canon.digest(), "canon": self.canon.as_dict()}
        tmp = self.dir / (SNAPSHOT + ".tmp")
        tmp.write_text(canonical(payload), encoding="utf-8", newline="")
        os.replace(tmp, self.dir / SNAPSHOT)
