"""Desktop parity phase 2: author's note (ST-21) and play aids (ST-30/31).

The web play view has both; the Tkinter app had neither, so a desktop-only user
could not set standing guidance or a quick action at all.

The risk in adding them is not "does the widget appear" — it is the two paths
DRIFTING. The bounds (20 actions, 30 rules, ReDoS refusal) lived in srv/core.py,
and the header-preserving note write lived inline in srv/world.py, so a desktop
copy would have been a second implementation of both. They are now shared
(coderain.aids, MemoryStore.set_custom_instructions) and these assertions pin
that the GUI gets the SAME verdicts as the HTTP layer.

 1) the note round-trips, and keeps the header above the `---`
 2) placement (depth/every) reaches world_state
 3) quick actions are stored, trimmed, and capped at 20
 4) a ReDoS-prone rule is refused by the dialog, exactly as the route refuses it
 5) a safe rule is stored with its flags filtered to ims
 6) srv and coderain.aids are the SAME function, not two copies
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-guistory-"))
os.environ["CODERAIN_HOME"] = str(WORK)

from coderain.aids import clean_quick_actions, clean_regex_rules   # noqa: E402
from coderain.memory import Library                                # noqa: E402

lib = Library(WORK / "lib")
slug = lib.create_story("SM", "A courier in the rain.")
store = lib.store(slug)
store.append_turn("player", "look")
store.append_turn("narrator", "Rain on the cobbles.")

import gui as gui_mod                                              # noqa: E402
import tkinter as tk                                               # noqa: E402

try:
    _p = tk.Tk()
    _p.destroy()
except tk.TclError as e:
    print("SKIP: no display available ->", e)
    shutil.rmtree(WORK, ignore_errors=True)
    sys.exit(0)

app = gui_mod.App()
app.withdraw()
app.lib = lib
app._open_story(slug)


def _click(dlg, label):
    """Press the button with this text, wherever it sits in the dialog."""
    stack = [dlg]
    while stack:
        w = stack.pop()
        stack.extend(w.winfo_children())
        if isinstance(w, tk.Button) and w.cget("text") == label:
            w.invoke()
            return True
    raise AssertionError(f"no {label!r} button")


# No widget-tree search helper on purpose: an earlier version of this suite
# picked entries out of the tree by index and got them in traversal order, so
# the "find" pattern landed in the flags box and §5 asserted against garbage.
# The dialogs expose named handles instead.


def test_note_round_trips_and_keeps_its_header():
    store.write("custom-instructions.md",
                "# Custom instructions (this save)\n\nkeep me\n---\nold note")
    dlg = app._authors_note_dialog()
    txt = dlg.note_text
    assert txt.get("1.0", "end").strip() == "old note"
    txt.delete("1.0", "end")
    txt.insert("1.0", "Terse. No adverbs.")
    _click(dlg, "Save")
    raw = store.read("custom-instructions.md")
    assert store.custom_instructions() == "Terse. No adverbs.", raw
    assert "keep me" in raw, raw          # header above --- survived
    print("1. note round-trips and preserves the header above the ---")


def test_placement_reaches_world_state():
    dlg = app._authors_note_dialog()
    dlg.note_depth.set("tail")
    dlg.note_every.delete(0, "end")
    dlg.note_every.insert(0, "3")
    _click(dlg, "Save")
    an = store.world_state()["authors_note"]
    assert an == {"depth": "tail", "every": 3}, an
    print("2. placement (depth/every) stored:", an)


def test_quick_actions_stored_and_capped():
    dlg = app._play_aids_dialog()
    qa = dlg.aids_quick
    qa.delete("1.0", "end")
    qa.insert("1.0", "\n".join(["  look around  ", "", "listen"]
                               + [f"a{i}" for i in range(30)]))
    _click(dlg, "Save")
    got = store.world_state()["quick_actions"]
    assert got[0] == "look around" and got[1] == "listen", got[:3]
    assert len(got) == 20, len(got)
    print("3. quick actions trimmed, blanks dropped, capped at 20")


def test_redos_rule_is_refused():
    """§4 the dialog must apply the ENGINE's safety verdict, not its own."""
    evil = "(a+)+$"
    assert clean_regex_rules([{"find": evil, "replace": "x"}]) == [], \
        "setup: expected this pattern to be refused by the shared cleaner"
    dlg = app._play_aids_dialog()
    dlg.aids_fields["find"].insert(0, evil)
    gui_mod.messagebox.showinfo = lambda *a, **k: None   # swallow the popup
    _click(dlg, "Add")
    assert dlg.aids_list.size() == 0, dlg.aids_list.get(0, "end")
    dlg.destroy()
    print("4. ReDoS-prone rule refused by the dialog, as the route refuses it")


def test_safe_rule_is_stored_with_filtered_flags():
    dlg = app._play_aids_dialog()
    dlg.aids_fields["find"].insert(0, "colour")
    dlg.aids_fields["replace"].insert(0, "color")
    dlg.aids_fields["flags"].insert(0, "iXm")   # X is not a legal flag
    _click(dlg, "Add")
    _click(dlg, "Save")
    rules = store.world_state()["regex_rules"]
    assert rules == [{"find": "colour", "replace": "color", "flags": "im"}], rules
    print("5. safe rule stored, flags filtered to ims:", rules)


def test_gui_and_http_share_one_implementation():
    """§6 the whole point. Two copies of a bounds rule is how this repo ended up
    with a greedy JSON scanner beside a correct one."""
    from srv import core
    assert core._clean_quick_actions is clean_quick_actions
    assert core._clean_regex_rules is clean_regex_rules
    assert hasattr(store, "set_custom_instructions")
    print("6. srv re-exports the shared cleaners; no second copy exists")


for fn in (test_note_round_trips_and_keeps_its_header,
           test_placement_reaches_world_state,
           test_quick_actions_stored_and_capped,
           test_redos_rule_is_refused,
           test_safe_rule_is_stored_with_filtered_flags,
           test_gui_and_http_share_one_implementation):
    fn()

app.destroy()
shutil.rmtree(WORK, ignore_errors=True)
print("\nGUI STORY MENU TESTS PASSED")
