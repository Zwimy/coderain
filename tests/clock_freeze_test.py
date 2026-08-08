"""The in-world clock froze permanently at "Day 2043".

Reported live on a 744-turn save. The fold is the one writer that sets `day`
ABSOLUTELY, and it was bounded only by DAY_CAP (10,000,000). The realistic
hallucination is not a 4000-digit number, it is a calendar YEAR — "day": 2043 —
which passes that ceiling easily.

Once accepted it is unrecoverable. `fold_day >= cur_day` fails for every real
story day afterwards, so the day never moves again; and because
`current_or_later` is then False, PHASE AND NOTE stop updating too. The whole
clock is stuck, which is exactly how it was reported: "this doesn't seem to
change at all anymore".

 1) a normal advance still works
 2) a year-shaped day is refused, and says so
 3) refusing the day still lets phase and note advance (the freeze is the bug)
 4) a legitimate long timeskip is still allowed
 5) an absurd magnitude is still refused (DAY_CAP is not replaced)
 6) the fold still cannot rewind the clock
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-clock-"))
os.environ["CODERAIN_HOME"] = str(WORK)

from coderain.config import load_config                     # noqa: E402
from coderain.memory import Library                          # noqa: E402
from coderain.summarizer import MAX_FOLD_DAY_JUMP, Summarizer  # noqa: E402

lib = Library(WORK / "lib")


def _fold_time(name, start_day, t_block):
    """Run _apply_time against a store whose clock starts at start_day."""
    store = lib.store(lib.create_story(name, "A courier."))
    ws = store.world_state()
    ws["time"] = {"day": start_day, "phase": "morning", "note": "start"}
    store.set_world_state(ws)
    s = Summarizer(load_config(), store, None, planner=None)
    s._apply_time({"time": t_block})
    tm = store.world_state().get("time") or {}
    health = store.read("memory/health.jsonl")
    return tm, health


def test_normal_advance():
    tm, _ = _fold_time("ok", 5, {"day": 6, "phase": "evening"})
    assert tm["day"] == 6 and tm["phase"] == "evening", tm
    print("1. a normal advance still moves the clock")


def test_year_shaped_day_is_refused():
    tm, health = _fold_time("year", 5, {"day": 2043, "phase": "deep night"})
    assert tm["day"] == 5, tm
    assert "looks like a year" in health, health
    print("2. day 2043 from day 5 refused, and logged")


def test_refusing_the_day_still_advances_phase_and_note():
    """§3 THE bug. Freezing the day also froze phase and note, so the whole
    display went dead rather than just the number."""
    tm, _ = _fold_time("phase", 5,
                       {"day": 2043, "phase": "deep night", "note": "after rain"})
    assert tm["day"] == 5, tm
    assert tm["phase"] == "deep night", tm
    assert tm["note"] == "after rain", tm
    print("3. day refused, but phase and note still advance")


def test_legitimate_timeskip_allowed():
    tm, _ = _fold_time("skip", 10, {"day": 10 + MAX_FOLD_DAY_JUMP})
    assert tm["day"] == 10 + MAX_FOLD_DAY_JUMP, tm
    print(f"4. a {MAX_FOLD_DAY_JUMP}-day timeskip is still allowed")


def test_absurd_magnitude_still_refused():
    tm, health = _fold_time("huge", 5, {"day": 10 ** 9})
    assert tm["day"] == 5, tm
    assert "out-of-range" in health, health
    print("5. DAY_CAP still refuses absurd magnitudes")


def test_fold_cannot_rewind():
    """§6 the guard that must survive: a fold summarizing OLDER turns must not
    drag the clock backwards."""
    tm, _ = _fold_time("back", 20, {"day": 3, "phase": "dawn"})
    assert tm["day"] == 20, tm
    assert tm["phase"] == "morning", tm      # phase held too, by design
    print("6. an older fold still cannot rewind the clock")


try:
    for fn in (test_normal_advance,
               test_year_shaped_day_is_refused,
               test_refusing_the_day_still_advances_phase_and_note,
               test_legitimate_timeskip_allowed,
               test_absurd_magnitude_still_refused,
               test_fold_cannot_rewind):
        fn()
finally:
    shutil.rmtree(WORK, ignore_errors=True)
print("\nCLOCK FREEZE TESTS PASSED")
