"""Chapters stopped being distinct from each other.

Planning one chapter per call (v0.6.0) hands the model the whole outline so each
chapter can build on the last. It also hands it the easiest possible answer:
paraphrase a neighbour. Seen live, three chapters into a real story:

  1. [active]  The Polychrome's Crucible: confront the Inner Circle ...
  2. [planned] The Trial of the Blood Pact: survive a test fight against an
               Inner Circle enforcer and uncover the contract's hidden COMPULSION
  3. [planned] The Dragon's Compulsion: uncover the contract's hidden TRAP ...
               setting the stage for the enforcer's brutal trial

Two failures. Chapter 3 is the same beat as chapter 2, and chapter 3 is written
as the lead-in to chapter 2 — a prequel to something that already comes first.

The second one is a positioning bug, not a taste problem: the payload listed the
chapters unnumbered with no marker, so nothing said WHICH slot was being written.
The model picked a gap it liked.

 1) the restatement check catches the live pair
 2) it does NOT fire on chapters that merely share a setting
 3) the append payload numbers the rows and marks the empty slot at the END
 4) a rewrite marks its own row and adds no end slot
 5) a restating reply is rejected and retried, naming the offending phrase
 6) a second restatement is kept (an outline beats a hole) but logged
 7) both instructions carry the distinctness rules
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-chdistinct-"))
os.environ["CODERAIN_HOME"] = str(WORK)

from coderain.config import load_config                              # noqa: E402
from coderain.memory import Library                                   # noqa: E402
from coderain.planner import (NEXT_INSTRUCTION, SLOT_INSTRUCTION,     # noqa: E402
                              ChapterPlanner, _restates)

lib = Library(WORK / "lib")

# The live goals, verbatim.
CH2 = ("Survive a savage test fight against an Inner Circle enforcer and uncover "
       "the contract's hidden compulsion that nearly enslaves you.")
CH3 = ("Uncover the contract's hidden trap while navigating the Golden Dragons' "
       "politics, setting the stage for the enforcer's brutal trial.")

ROWS = [
    {"title": "The Polychrome's Crucible", "status": "active",
     "goal": "Confront the Inner Circle summoned by your Polychrome exposure."},
    {"title": "The Trial of the Blood Pact", "goal": CH2, "status": "planned"},
]


class Stub:
    """Replies from a queue; keeps every payload it was handed."""

    def __init__(self, replies):
        self.replies, self.payloads, self.calls = list(replies), [], 0

    def complete(self, messages, **k):
        self.calls += 1
        self.payloads.append(messages[-1]["content"])
        r = self.replies.pop(0) if self.replies else {"title": "Fallback",
                                                      "goal": "something else"}
        return json.dumps(r)


def _planner(name, replies=(), rows=ROWS, horizon=3):
    store = lib.store(lib.create_story(
        name, "A rogue bound by a blood contract to the Golden Dragons."))
    cfg = load_config()
    cfg.generation["chapter_outline"] = True
    cfg.generation["chapter_horizon"] = horizon
    stub = Stub(replies)
    p = ChapterPlanner(cfg, store, stub)
    if rows:
        p.replace_all([dict(r) for r in rows])
    return p, stub, store


def test_catches_the_live_pair():
    hit = _restates(CH3, [CH2])
    assert hit == "uncover contract hidden", repr(hit)
    print("1. the live pair is caught on:", repr(hit))


def test_does_not_fire_on_a_shared_setting():
    """§2 the check has to survive a story that legitimately keeps saying
    'dragon'. Adjacency is what carries the meaning: the same words in the same
    ORDER is a restatement, the same words scattered is just the same setting."""
    same_world = [
        ("Cross the frozen river before the patrol reaches the ford.",
         "Bargain with the ferryman for passage across the river at dawn."),
        ("The dragon guards the gate against all comers.",
         "The gate opens, and behind it waits the dragon."),
        ("Escape the Golden Dragons' compound before dawn.",
         "Return to the Golden Dragons with proof of the betrayal."),
    ]
    for a, b in same_world:
        assert not _restates(a, [b]), (a, b, _restates(a, [b]))
    assert not _restates("", [CH2])          # nothing to compare
    assert not _restates("Run.", [CH2])      # too short for a trigram
    print(f"2. {len(same_world)} same-setting pairs and 2 degenerate cases pass")


def test_append_payload_numbers_and_marks_the_end():
    """§3 the positioning fix. Without this the model had no way to know it was
    writing the LAST chapter, and wrote a lead-in to one above it."""
    p, _, _ = _planner("append")
    payload = p._plan_payload(mark=len(p.chapters()))
    assert "1. [active] The Polychrome's Crucible:" in payload, payload[:400]
    assert "2. [planned] The Trial of the Blood Pact:" in payload, payload[:400]
    assert "3. <<< WRITE THIS ONE" in payload, payload[:400]
    assert "cannot lead into anything listed above" in payload, payload[:400]
    assert "REWRITE THIS ONE" not in payload
    print("3. append payload numbers the rows and marks the end slot")


def test_rewrite_payload_marks_its_own_row():
    p, _, _ = _planner("rewrite")
    payload = p._plan_payload(mark=1)
    assert "2. [planned] The Trial of the Blood Pact:" in payload
    line = next(l for l in payload.splitlines() if l.startswith("2. "))
    assert line.endswith("<<< REWRITE THIS ONE"), line
    assert "WRITE THIS ONE — the new last" not in payload, "added a phantom slot"
    print("4. a rewrite marks its own row and adds no end slot")


def test_restatement_is_rejected_and_retried():
    """§5 the retry has to TELL the model what was wrong. Re-asking the same
    question gets the same answer."""
    p, stub, _ = _planner("retry", replies=[
        {"title": "The Dragon's Compulsion", "goal": CH3},        # restates CH2
        {"title": "The Ledger", "goal": "Steal the pact ledger from the vault."},
    ])
    made = p._generate_next()
    assert stub.calls == 2, stub.calls
    assert made.title == "The Ledger", made.title
    nudge = stub.payloads[1]
    assert "REJECTED" in nudge, nudge[-400:]
    assert "uncover contract hidden" in nudge, nudge[-400:]
    assert CH3 in nudge, "the retry did not quote the rejected goal"
    print("5. a restatement is rejected, quoted back, and retried")


def test_second_restatement_is_kept_but_logged():
    """§6 invariant 2: degrade, never silently. A weak chapter still beats a
    hole in the outline, but it has to show up in the Context panel."""
    p, stub, store = _planner("twice", replies=[
        {"title": "A", "goal": CH3},
        {"title": "B", "goal": CH3},
    ])
    made = p._generate_next()
    assert made is not None and stub.calls == 2, (made, stub.calls)
    health = (store.dir / "memory" / "health.jsonl").read_text(encoding="utf-8")
    assert "chapter-plan" in health, health
    assert "uncover contract hidden" in health, health
    print("6. a second restatement is kept and written to health.jsonl")


def test_both_instructions_carry_the_rules():
    """§7 one path enforcing distinctness while another does not is how the
    outline ended up mixed in the first place."""
    for name, text in (("NEXT", NEXT_INSTRUCTION), ("SLOT", SLOT_INSTRUCTION)):
        assert "opens a question no other chapter opens" in text, name
        assert "may only set up chapters AFTER it" in text, name
        assert "Never restate another chapter's goal" in text, name
    assert "empty slot at the END" in NEXT_INSTRUCTION
    assert "REWRITE THIS ONE" in SLOT_INSTRUCTION
    print("7. both instructions carry the same distinctness rules")


try:
    for fn in (test_catches_the_live_pair,
               test_does_not_fire_on_a_shared_setting,
               test_append_payload_numbers_and_marks_the_end,
               test_rewrite_payload_marks_its_own_row,
               test_restatement_is_rejected_and_retried,
               test_second_restatement_is_kept_but_logged,
               test_both_instructions_carry_the_rules):
        fn()
finally:
    shutil.rmtree(WORK, ignore_errors=True)
print("\nCHAPTER DISTINCTNESS TESTS PASSED")
