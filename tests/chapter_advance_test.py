"""Chapters did not advance automatically.

Reported live. The fold hands the active chapter to the model and reads
`chapter_goal_met` back to decide whether the chapter is finished. That check was
`obj.get("chapter_goal_met") is True` — a strict identity test against a real
JSON boolean. A model answering `"chapter_goal_met": "true"` (a string, which
small local models produce constantly) was ignored completely, and because
nothing was logged, the only symptom was a plan that never moved.

Every other model-supplied boolean in this engine goes through
memory._attr_true, which accepts "true"/"yes"/"1"/"on". This was the one place
that did not.

 1) a real JSON boolean still advances (the case that already worked)
 2) "true", "yes" and 1 now advance too
 3) false, "false" and "no" still do NOT advance
 4) an unusable value does not advance AND leaves a health line
 5) advancing marks the chapter done and activates the next
 6) a stray flag cannot advance anything when there is no outline
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-chapadv-"))
os.environ["CODERAIN_HOME"] = str(WORK)

from coderain.config import load_config            # noqa: E402
from coderain.memory import Library                # noqa: E402
from coderain.planner import ChapterPlanner        # noqa: E402
from coderain.summarizer import Summarizer         # noqa: E402


class Stub:
    """Fold LLM that reports whatever chapter_goal_met shape we are testing."""
    gen = {"max_tokens": 2000}

    def __init__(self, flag):
        self.flag = flag

    def complete(self, convo, **kw):
        return json.dumps({"scene_summary": "They crossed the ice.",
                           "timeline": "crossed", "promotions": [],
                           "chapter_goal_met": self.flag})


def _fold_with(flag, name, outline=True):
    lib = Library(WORK / f"lib-{name}")
    slug = lib.create_story("C", "A courier crosses a frozen kingdom.")
    store = lib.store(slug)
    for _ in range(8):
        store.append_turn("player", "go")
        store.append_turn("narrator", "They walk on.")
    cfg = load_config()
    cfg.generation["chapter_outline"] = True
    planner = ChapterPlanner(cfg, store, Stub(flag))
    if outline:
        planner.replace_all([
            {"title": "A", "goal": "cross the ice", "status": "active"},
            {"title": "B", "goal": "reach the manor", "status": "planned"},
        ])
    s = Summarizer(cfg, store, Stub(flag), planner=planner)
    s._fold_scene(store.turns()[:4], 1, 0)
    return planner, store


def _advanced(planner) -> bool:
    rows = planner.as_dicts()
    return bool(rows) and rows[0]["status"] == "done"


def test_real_boolean_still_advances():
    p, _ = _fold_with(True, "bool")
    assert _advanced(p), p.as_dicts()
    print("1. JSON true advances (the case that already worked)")


def test_truthy_strings_and_int_advance():
    """§2 the actual bug: these were all silently ignored."""
    for flag, name in ((("true"), "s_true"), ("yes", "s_yes"), (1, "i_1"),
                       ("ON", "s_on")):
        p, _ = _fold_with(flag, name)
        assert _advanced(p), (flag, p.as_dicts())
    print("2. 'true', 'yes', 1 and 'ON' now advance")


def test_falsey_values_do_not_advance():
    """§3 the overcorrection guard. Advancing is one-way, so a loose truthiness
    test that treated any non-empty string as true would be worse than the bug."""
    for flag, name in ((False, "f_bool"), ("false", "f_str"), ("no", "f_no"),
                       ("0", "f_zero"), (None, "f_none")):
        p, _ = _fold_with(flag, name)
        assert not _advanced(p), (flag, p.as_dicts())
    print("3. false, 'false', 'no', '0' and null all stay put")


def test_unusable_value_is_logged():
    p, store = _fold_with("maybe", "garbage")
    assert not _advanced(p), p.as_dicts()
    health = store.read("memory/health.jsonl")
    assert "chapter_goal_met" in health, health
    print("4. an unusable value refuses to advance, and says so in health")


def test_advance_marks_done_and_activates_next():
    p, _ = _fold_with(True, "roll")
    rows = p.as_dicts()
    assert rows[0]["status"] == "done", rows
    assert any(r["status"] == "active" for r in rows[1:]), rows
    print("5. advancing marks done and activates the next chapter")


def test_no_outline_cannot_be_advanced():
    """§6 the guard that was already right: with no chapter handed to the fold,
    a stray flag must do nothing."""
    p, _ = _fold_with(True, "noplan", outline=False)
    assert p.as_dicts() == [], p.as_dicts()
    print("6. a stray flag cannot advance an outline-less story")


for fn in (test_real_boolean_still_advances,
           test_truthy_strings_and_int_advance,
           test_falsey_values_do_not_advance,
           test_unusable_value_is_logged,
           test_advance_marks_done_and_activates_next,
           test_no_outline_cannot_be_advanced):
    fn()

shutil.rmtree(WORK, ignore_errors=True)
print("\nCHAPTER ADVANCE TESTS PASSED")
