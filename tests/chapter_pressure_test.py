"""The story drifted away from the chapter plan.

The plan reached the writer only as "Story structure (chapter plan)" inside the
system prompt: one section among a dozen and, on a large context, thousands of
tokens from where generation starts. Naming a goal that far away does not steer
anything, and the story wandered.

The engine already had the answer for this. _lore_directive is appended AFTER
the player's action because "it binds hardest on the next tokens", and the
author's note's `tail` placement works for the same reason. The active chapter
now rides there too. It costs no extra model call: the plan is already on disk.

 1) the chapter directive is the LAST message the model reads
 2) it names the active chapter and its goal
 3) it carries the anti-drift instruction, not just the goal
 4) it names the next chapter as somewhere NOT to jump to
 5) no outline, or the feature off, means no directive at all
 6) the system-prompt plan section is still there (this adds, not replaces)
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-chappress-"))
os.environ["CODERAIN_HOME"] = str(WORK)

from coderain.config import load_config              # noqa: E402
from coderain.engine import Engine                    # noqa: E402
from coderain.memory import Library                   # noqa: E402
from coderain.planner import ChapterPlanner           # noqa: E402

lib = Library(WORK / "lib")

ROWS = [
    {"title": "The Handoff", "goal": "receive the box", "status": "done"},
    {"title": "The River Road", "goal": "avoid the highway and reach the ford",
     "status": "active"},
    {"title": "The Bridge", "goal": "cross unseen", "status": "planned"},
]


class Cap:
    """Captures exactly what the model is handed."""
    gen = {"max_tokens": 2000}

    def __init__(self):
        self.msgs = None

    def stream(self, messages, **k):
        self.msgs = messages
        yield "The road bends north."


def _run(name, rows=ROWS, outline_on=True):
    store = lib.store(lib.create_story(name, "A courier crosses a kingdom."))
    for _ in range(4):
        store.append_turn("player", "go")
        store.append_turn("narrator", "Rain.")
    cfg = load_config()
    cfg.generation["trinity_brain"] = False
    cfg.generation["chapter_outline"] = outline_on
    if rows:
        ChapterPlanner(cfg, store, None).replace_all(rows)
    eng = Engine(cfg, store)
    cap = Cap()
    eng.llm = cap
    list(eng.turn("I keep walking."))
    return cap.msgs


def test_directive_is_last():
    msgs = _run("last")
    assert msgs[-1]["role"] == "system", [m["role"] for m in msgs[-3:]]
    assert "THIS CHAPTER" in msgs[-1]["content"], msgs[-1]["content"][:120]
    # and it sits AFTER the player's action, not before it
    assert msgs[-2]["role"] == "user" and "keep walking" in msgs[-2]["content"]
    print("1. the chapter directive is the last message, after the action")


def test_names_chapter_and_goal():
    body = _run("names")[-1]["content"]
    assert "The River Road" in body, body
    assert "avoid the highway and reach the ford" in body, body
    assert "The Handoff" not in body, "a completed chapter must not steer"
    print("2. names the ACTIVE chapter and its goal, not a finished one")


def test_carries_the_anti_drift_rule():
    """§3 the part that does the work. Naming a goal is not steering; telling
    the model to check whether recent turns advanced it is."""
    body = _run("drift")[-1]["content"]
    assert "have not advanced it, advance it now" in body, body
    assert "Do not resolve it in a single turn" in body, body
    print("3. carries the advance-it-now and do-not-rush rules")


def test_names_the_next_chapter_as_off_limits():
    body = _run("next")[-1]["content"]
    assert "The Bridge" in body and "do not skip ahead" in body.lower(), body
    print("4. names the next chapter as somewhere not to jump to")


def test_absent_when_nothing_to_steer():
    no_plan = _run("noplan", rows=None)
    assert "THIS CHAPTER" not in no_plan[-1]["content"], no_plan[-1]["content"][:120]
    off = _run("off", outline_on=False)
    assert "THIS CHAPTER" not in off[-1]["content"], off[-1]["content"][:120]
    print("5. no outline / feature off -> no directive")


def test_system_section_still_present():
    """§6 this ADDS a binding restatement; it does not remove the fuller plan
    from the system prompt, which carries the later chapters."""
    msgs = _run("both")
    assert "Story structure (chapter plan)" in msgs[0]["content"]
    print("6. the system-prompt plan section is still there")


try:
    for fn in (test_directive_is_last,
               test_names_chapter_and_goal,
               test_carries_the_anti_drift_rule,
               test_names_the_next_chapter_as_off_limits,
               test_absent_when_nothing_to_steer,
               test_system_section_still_present):
        fn()
finally:
    shutil.rmtree(WORK, ignore_errors=True)
print("\nCHAPTER PRESSURE TESTS PASSED")
