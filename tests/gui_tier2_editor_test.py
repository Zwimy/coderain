"""The desktop editor could not author Tier-2 activation gates.

gui.py's _ED_ATTRS listed 13 attributes. The engine has honoured nine more
since ST-12 (triggers_all, triggers_not, chance, group, delay, sticky,
cooldown, semantic, recurse — see tier2_test.py) and the web builder authors
every one of them, so a desktop-only user could not reach a shipped feature at
all.

 1) every Tier-2 gate has a widget in the editor form
 2) a gate typed into the form reaches disk as a real Entry attribute
 3) the Entry accessors read back exactly what the form wrote
 4) loading a piece populates the gate widgets from disk
 5) an empty gate writes NO attribute (it must not add noise to every entry)
 6) a piece with gates survives an edit that does not touch them
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-guitier2-"))
os.environ["CODERAIN_HOME"] = str(WORK)

from coderain.memory import Library                     # noqa: E402

lib = Library(WORK / "lib")
slug = lib.create_story("T2", "A courier in the rain.")
store = lib.store(slug)
# Seed a turn BEFORE opening: _open_story fires the opening generation on an
# empty transcript, which sets App.generating, and _ed_save refuses to write
# while a turn is in flight. Same reason gui_panel_test.py seeds one.
store.append_turn("player", "look")
store.append_turn("narrator", "Rain on the cobbles. A shuttered lighthouse.")

# gui FIRST: its _ensure_tcl() points Tk at the base install's tcl/ directory,
# which a venv's auto-locator gets wrong. Probing Tk before this import fails
# with "can't find init.tcl" and would have self-skipped this whole suite for a
# reason that has nothing to do with having a display.
import gui as gui_mod                                   # noqa: E402
import tkinter as tk                                    # noqa: E402

try:
    _probe = tk.Tk()
    _probe.destroy()
except tk.TclError as e:                                # genuinely headless CI
    print("SKIP: no display available ->", e)
    shutil.rmtree(WORK, ignore_errors=True)
    sys.exit(0)

GATES = ["triggers_all", "triggers_not", "chance", "group",
         "delay", "sticky", "cooldown", "semantic", "recurse"]

app = gui_mod.App()
app.withdraw()
app.lib = lib
app._open_story(slug)
f = app.ed_fields


def test_every_gate_has_a_widget():
    missing = [g for g in GATES if g not in f]
    assert not missing, missing
    assert all(g in gui_mod.App._ED_ATTRS for g in GATES)
    print("1. all nine Tier-2 gates present in the form and managed")


def _set(key, value):
    w = f[key]
    if isinstance(w, tk.BooleanVar):
        w.set(bool(value))
    else:
        w.delete(0, "end")
        w.insert(0, str(value))


def test_gates_round_trip_to_disk():
    app.ed_file_var.set("characters.md")
    _set("title", "Thorne")
    _set("slug", "thorne")
    _set("triggers", "thorne, fixer")
    _set("triggers_all", "harbor, night")
    _set("triggers_not", "daylight")
    _set("chance", "50")
    _set("group", "fixers")
    _set("delay", "3")
    _set("sticky", "2")
    _set("cooldown", "4")
    _set("semantic", True)
    _set("recurse", True)
    app.ed_body.delete("1.0", "end")
    app.ed_body.insert("1.0", "A fixer with a buried past.")
    app._ed_save()

    e = next(x for x in store.entries("characters.md") if x.slug == "thorne")
    assert e.attrs["triggers_all"] == "harbor, night", e.attrs
    assert e.attrs["triggers_not"] == "daylight", e.attrs
    assert e.attrs["chance"] == "50", e.attrs
    assert e.attrs["group"] == "fixers", e.attrs
    assert e.attrs["semantic"] == "true" and e.attrs["recurse"] == "true", e.attrs
    print("2. gates written to disk as Entry attributes")


def test_entry_accessors_agree():
    """§3 the form is only useful if the ENGINE reads what it wrote."""
    e = next(x for x in store.entries("characters.md") if x.slug == "thorne")
    assert e.triggers_all() == ["harbor", "night"], e.triggers_all()
    assert e.triggers_not() == ["daylight"], e.triggers_not()
    assert e.chance() == 50, e.chance()
    assert e.group() == "fixers", e.group()
    assert e.delay() == 3 and e.sticky() == 2, (e.delay(), e.sticky())
    print("3. Entry accessors read back exactly what the form wrote")


def test_loading_populates_the_gates():
    app._ed_load_list()
    for i, s in enumerate(app.ed_list.get(0, "end")):
        if "thorne" in str(s):
            app.ed_list.selection_clear(0, "end")
            app.ed_list.selection_set(i)
            break
    app._ed_load_entry()
    assert f["triggers_all"].get() == "harbor, night", f["triggers_all"].get()
    assert f["chance"].get() == "50", f["chance"].get()
    assert f["semantic"].get() is True
    print("4. loading a piece repopulates the gate widgets")


def test_empty_gate_writes_nothing():
    """§5 the overcorrection guard: a blank field must not stamp an empty
    attribute onto every entry. Those render into the prompt."""
    _set("title", "Plain")
    _set("slug", "plain")
    for g in GATES:
        _set(g, False if isinstance(f[g], tk.BooleanVar) else "")
    app.ed_body.delete("1.0", "end")
    app.ed_body.insert("1.0", "Nothing special.")
    app._ed_current = None
    app._ed_save()
    e = next(x for x in store.entries("characters.md") if x.slug == "plain")
    present = [g for g in GATES if g in e.attrs]
    assert not present, present
    print("5. blank gates write no attributes at all")


def test_gates_survive_an_unrelated_edit():
    """§6 a fold or a body tweak must not silently drop the gates."""
    e = next(x for x in store.entries("characters.md") if x.slug == "thorne")
    before = {g: e.attrs.get(g) for g in GATES if g in e.attrs}
    assert before, "setup failed: thorne has no gates"
    app._ed_load_list()
    for i, s in enumerate(app.ed_list.get(0, "end")):
        if "thorne" in str(s):
            app.ed_list.selection_clear(0, "end")
            app.ed_list.selection_set(i)
            break
    app._ed_load_entry()
    app.ed_body.delete("1.0", "end")
    app.ed_body.insert("1.0", "A fixer with a buried past. Now limping.")
    app._ed_save()
    after_e = next(x for x in store.entries("characters.md") if x.slug == "thorne")
    after = {g: after_e.attrs.get(g) for g in GATES if g in after_e.attrs}
    assert after == before, (before, after)
    print("6. gates survive an edit that does not touch them")


for fn in (test_every_gate_has_a_widget,
           test_gates_round_trip_to_disk,
           test_entry_accessors_agree,
           test_loading_populates_the_gates,
           test_empty_gate_writes_nothing,
           test_gates_survive_an_unrelated_edit):
    fn()

app.destroy()
shutil.rmtree(WORK, ignore_errors=True)
print("\nGUI TIER-2 EDITOR TESTS PASSED")
