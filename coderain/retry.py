"""Retry keeps what it replaces (D-057).

A retry deleted the last exchange FIRST and regenerated second, so whatever ended the regeneration early (a model error, the
Stop button, an empty reply) left the story one exchange shorter, with the player's own action gone too. Rolling the exchange
back is not one change: it trims the transcript, resets the world state, drops ledger records, un-reveals things and trims
folds (invariants 3 and 6), and the engine holds ONE undo snapshot that the rollback consumes. Putting the text back alone would
leave all of that out of step with the story.

So the whole save is copied before the rollback, and copied back when the regeneration does not put a narrator turn in the
exchange's place. A copy is crude and it cannot be wrong: the save is byte for byte what it was. Two files are never rolled
back: the health log (a failed attempt must stay visible, invariant 2) and the usage log (the tokens were spent).
"""
from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

# Never copied: snapshots are large and belong to the fold machinery, not to one exchange.
SKIP_TOP = (".snapshots",)
# Never rolled back: what a failed attempt wrote here is true whatever happened to the story.
LEAVE_ALONE = ("memory/health.jsonl", "memory/usage.jsonl")


class RetryRestored(Exception):
    """The regeneration produced no narration, so the earlier exchange was put back. Carries its own reader-facing wording
    (`user_text`) and error code for the stream, which would otherwise call it "The model call failed."."""
    code = "restored"
    user_text = "The model gave back nothing, so your earlier version is still here."


@dataclass
class Checkpoint:
    root: Path                      # the save directory
    copy: Path                      # where the copy lives
    turns: int                      # transcript length before the retry
    tail_role: str                  # "narrator", or "player" for an orphan action left by a failed turn
    slots: dict = field(default_factory=dict)   # the engine's in-memory undo state, deep-copied by the caller

    @classmethod
    def take(cls, root: Path, turns: int, tail_role: str, slots: dict) -> "Checkpoint":
        dest = Path(tempfile.mkdtemp(prefix="coderain-retry-"))
        shutil.copytree(root, dest, ignore=shutil.ignore_patterns(*SKIP_TOP), dirs_exist_ok=True)
        return cls(Path(root), dest, turns, tail_role, slots)

    def took_hold(self, turns: list[dict]) -> bool:
        """Did the regeneration put a narrator turn where the exchange was? A narrator tail comes back as the same length (the
        exchange, or a Continue, or the opening); an orphan player action comes back with its narration, one longer."""
        want = self.turns if self.tail_role == "narrator" else self.turns + 1
        return bool(turns) and turns[-1]["role"] == "narrator" and len(turns) == want

    def restore_files(self) -> None:
        """Copy the checkpoint over the save. The save is whole again after the first step, so a failure part way through
        never leaves less than the checkpoint's own files; what the attempt ADDED is removed last."""
        kept = {rel: (self.root / rel).read_bytes() for rel in LEAVE_ALONE if (self.root / rel).is_file()}
        shutil.copytree(self.copy, self.root, dirs_exist_ok=True)
        for p in sorted(self.root.rglob("*"), key=lambda q: len(q.parts), reverse=True):
            rel = p.relative_to(self.root)
            if rel.parts[0] in SKIP_TOP or rel.as_posix() in LEAVE_ALONE or (self.copy / rel).exists():
                continue
            try:
                p.unlink() if p.is_file() else p.rmdir()
            except OSError:
                pass                      # a directory that still holds something that must stay: leave it
        for rel, data in kept.items():
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.root / rel).write_bytes(data)

    def discard(self) -> None:
        shutil.rmtree(self.copy, ignore_errors=True)
