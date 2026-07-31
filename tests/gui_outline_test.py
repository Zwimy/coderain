"""Desktop parity phase 4: the chapter plan.

The outline panel's rules were written INLINE in srv/outline.py and raised
HTTPException — so they were unreachable from any non-HTTP front end and the
desktop app could not edit an outline at all. They are the engine's rules, not
the transport's: a done or active chapter is already part of the story, so it
cannot be deleted or dragged out of story order.

They now live on ChapterPlanner and raise PlanError. srv/outline.py translates
that to 400/404; the desktop dialog shows it in the panel.

 1) planner.edit / insert / delete / move do the obvious thing
 2) delete refuses a done or active chapter, by PlanError not HTTPException
 3) move refuses to drag a chapter out of story order; an edge is a no-op
 4) the dialog lists chapters with their status
 5) editing through the dialog reaches disk
 6) a refusal shows in the panel instead of raising
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-guiplan-"))
os.environ["CODERAIN_HOME"] = str(WORK)

from coderain.config import load_config                    # noqa: E402
from coderain.engine import Engine                         # noqa: E402
from coderain.memory import Library                        # noqa: E402
from coderain.planner import ChapterPlanner, PlanError     # noqa: E402

lib = Library(WORK / "lib")
slug = lib.create_story("PLAN", "A courier crossing a frozen kingdom.")
store = lib.store(slug)
store.append_turn("player", "look")
store.append_turn("narrator", "Ice, and a shuttered lighthouse.")

cfg = load_config()
cfg.generation["chapter_outline"] = True
planner = ChapterPlanner(cfg, store, None)      # llm=None: no seeding here
planner.replace_all([
    {"title": "The Handoff", "goal": "receive the box", "status": "done"},
    {"title": "The River Road", "goal": "avoid the highway", "status": "active"},
    {"title": "The Bridge", "goal": "cross unseen", "status": "planned"},
    {"title": "The Manor", "goal": "deliver it", "status": "planned"},
])


def test_basic_edits():
    planner.edit(2, title="The Burned Bridge", goal="cross at night")
    rows = planner.as_dicts()
    assert rows[2]["title"] == "The Burned Bridge", rows[2]
    assert rows[2]["goal"] == "cross at night", rows[2]
    planner.insert(2, "Interlude", "rest")
    assert [r["title"] for r in planner.as_dicts()][3] == "Interlude"
    planner.delete(3)
    assert "Interlude" not in [r["title"] for r in planner.as_dicts()]
    planner.move(2, 1)
    assert [r["title"] for r in planner.as_dicts()][2] == "The Manor"
    # Put it back by moving the LOWER one up. Moving index 2 up here would drag a
    # planned chapter above the active one, which the rule correctly refuses —
    # the first draft of this line did exactly that and the engine caught it.
    planner.move(3, -1)
    print("1. edit / insert / delete / move behave")


def test_delete_protects_story_chapters():
    for idx, why in ((0, "done"), (1, "active")):
        try:
            planner.delete(idx)
            raise AssertionError(f"{why} chapter was deletable")
        except PlanError as e:
            assert "planned" in str(e), e
    print("2. done and active chapters refuse deletion, via PlanError")


def test_move_protects_story_order_and_edges():
    try:
        planner.move(1, 1)       # active chapter
        raise AssertionError("active chapter was reorderable")
    except PlanError:
        pass
    before = [r["title"] for r in planner.as_dicts()]
    planner.move(len(before) - 1, 1)          # bottom edge: no-op, not an error
    assert [r["title"] for r in planner.as_dicts()] == before
    try:
        planner.delete(99)
        raise AssertionError("out-of-range delete was allowed")
    except PlanError as e:
        assert "no such chapter" in str(e), e
    print("3. order protected; an edge move is a no-op; bad index refused")


import gui as gui_mod                                       # noqa: E402
import tkinter as tk                                        # noqa: E402

try:
    _p = tk.Tk()
    _p.destroy()
except tk.TclError as e:
    print("SKIP (dialog checks): no display ->", e)
    shutil.rmtree(WORK, ignore_errors=True)
    sys.exit(0)

app = gui_mod.App()
app.withdraw()
app.lib = lib
app._open_story(slug)


def test_dialog_lists_chapters_and_opens_on_the_active_one():
    """§4 also pins the opening selection. Defaulting to row 0 meant opening on
    a `done` chapter, whose form load() disables — so the panel greeted the user
    with a dead form and swallowed the first thing they typed."""
    dlg = app._outline_dialog()
    shown = list(dlg.plan_list.get(0, "end"))
    assert len(shown) == len(planner.as_dicts()), shown
    assert any("NOW" in s for s in shown), shown
    assert any("done" in s for s in shown), shown
    rows = app.engine.planner.as_dicts()
    active_i = next(n for n, r in enumerate(rows) if r["status"] == "active")
    assert dlg.plan_list.curselection() == (active_i,), dlg.plan_list.curselection()
    assert str(dlg.plan_title.cget("state")) == "normal", "form opened disabled"
    dlg.destroy()
    print("4. dialog lists every chapter and opens on the active one")


def test_dialog_edit_reaches_disk():
    dlg = app._outline_dialog()
    rows = app.engine.planner.as_dicts()
    i = next(n for n, r in enumerate(rows) if r["status"] == "planned")
    dlg.plan_list.selection_clear(0, "end")
    dlg.plan_list.selection_set(i)
    # selection_set does NOT fire <<ListboxSelect>>, so the form still holds the
    # previous row. A real click fires it; a test has to say so explicitly.
    dlg.plan_load()
    dlg.plan_title.delete(0, "end")
    dlg.plan_title.insert(0, "Renamed From The Desktop")
    dlg.plan_goal.delete("1.0", "end")
    dlg.plan_goal.insert("1.0", "a new goal")
    for w in dlg.winfo_children():
        for b in w.winfo_children():
            if isinstance(b, tk.Button) and b.cget("text") == "Save":
                b.invoke()
    after = app.engine.planner.as_dicts()
    got = after[i]
    assert got["title"] == "Renamed From The Desktop", (i, after)
    assert got["goal"] == "a new goal", (i, after)
    dlg.destroy()
    print("5. a dialog edit reaches disk")


def test_refusal_shows_in_the_panel():
    """§6 the desktop equivalent of a 400: the user must see why, and the
    window must survive."""
    dlg = app._outline_dialog()
    done_i = next(n for n, r in enumerate(app.engine.planner.as_dicts())
                  if r["status"] == "done")
    dlg.plan_list.selection_clear(0, "end")
    dlg.plan_list.selection_set(done_i)
    for w in dlg.winfo_children():
        for b in w.winfo_children():
            if isinstance(b, tk.Button) and b.cget("text") == "Delete":
                b.invoke()
    assert "planned" in dlg.plan_status.cget("text"), dlg.plan_status.cget("text")
    assert app.winfo_exists()
    dlg.destroy()
    print("6. a refusal is shown in the panel, not raised")


for fn in (test_basic_edits,
           test_delete_protects_story_chapters,
           test_move_protects_story_order_and_edges,
           test_dialog_lists_chapters_and_opens_on_the_active_one,
           test_dialog_edit_reaches_disk,
           test_refusal_shows_in_the_panel):
    fn()

app.destroy()
shutil.rmtree(WORK, ignore_errors=True)
print("\nGUI OUTLINE TESTS PASSED")
