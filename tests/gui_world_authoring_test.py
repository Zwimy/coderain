"""Desktop parity phase 6: world authoring and the character depth fields.

Two gaps left after phases 1-5.

WORLD AUTHORING. The Editor tab could only ever reach the current SAVE. Scenario
pieces were built in srv/pieces.py, so a desktop author could fix a character in
the story they were playing but not in the world it came from — and every new
save from that world kept the flaw. events.md was unreachable entirely.

CHARACTER DEPTH. wants / motivation / traits / playable were in the web piece
editor and not here. wants and motivation are LIVE (the fold rewrites them as
the fiction moves), so a desktop user could see them in context but never set
the starting values.

 1) ScenarioLibrary.store/piece_files exist and include events.md
 2) the HTTP layer uses them (no second copy)
 3) the scope picker lists this story plus every world
 4) editing in world scope writes to the SCENARIO, not the save
 5) an event rule (events.md) is authorable, `once` included
 6) wants / motivation / traits / playable round-trip
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-guiworld-"))
os.environ["CODERAIN_HOME"] = str(WORK)

from coderain.memory import SCENARIO_PIECE_FILES, Library    # noqa: E402

lib = Library(WORK / "lib")
scen = lib.scenarios.create("Frostfall", "A courier crosses a frozen kingdom.",
                            "Winter never ends here.")
slug = lib.create_story("WA", "A courier in the rain.")
store = lib.store(slug)
store.append_turn("player", "look")
store.append_turn("narrator", "Rain on the cobbles.")


def test_scenario_store_api():
    assert "events.md" in SCENARIO_PIECE_FILES, SCENARIO_PIECE_FILES
    st = lib.scenarios.store(scen)
    assert st is not None
    files = lib.scenarios.piece_files(scen)
    assert "events.md" in files and "characters.md" in files, files
    try:
        lib.scenarios.store("no-such-world")
        raise AssertionError("a missing scenario must raise")
    except FileNotFoundError:
        pass
    print("1. ScenarioLibrary.store/piece_files work;", len(files), "files")


def test_http_layer_shares_them():
    import srv.core as core
    core.lib = lib
    import srv.pieces as pieces
    pieces.lib = lib
    assert pieces._BASE_PIECE_FILES is SCENARIO_PIECE_FILES
    assert pieces._scen_store(scen).dir == lib.scenarios.store(scen).dir
    print("2. srv/pieces.py uses the shared store and list")


import gui as gui_mod                                        # noqa: E402
import tkinter as tk                                         # noqa: E402

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
app._ed_load_scopes()
WORLD = next(k for k in app._ed_scenarios if "Frostfall" in k)


def test_scope_picker_lists_worlds():
    values = list(app.ed_scope_box.cget("values"))
    assert values[0] == gui_mod.App._ED_THIS_STORY, values
    assert WORLD in values, values
    assert app._ed_store().dir == store.dir      # defaults to this story
    print("3. scope picker:", values)


def _set(key, value):
    w = app.ed_fields[key]
    if isinstance(w, tk.BooleanVar):
        w.set(bool(value))
    else:
        w.delete(0, "end")
        w.insert(0, str(value))


def test_world_scope_writes_to_the_scenario():
    app.ed_scope_var.set(WORLD)
    app._ed_scope_changed()
    assert app._ed_in_scenario()
    assert app._ed_store().dir == lib.scenarios.store(scen).dir
    app.ed_file_var.set("characters.md")
    _set("title", "Grimbold")
    _set("slug", "grimbold")
    app.ed_body.delete("1.0", "end")
    app.ed_body.insert("1.0", "The innkeeper at the Blackwood Tavern.")
    app._ed_save()
    in_world = [e.slug for e in lib.scenarios.store(scen).entries("characters.md")]
    in_save = [e.slug for e in store.entries("characters.md")]
    assert in_world == ["grimbold"], in_world
    assert in_save == [], f"the SAVE was written instead of the world: {in_save}"
    print("4. world-scope edit landed in the scenario, not the save")


def test_event_rule_is_authorable():
    assert "events.md" in app._ed_registries(), app._ed_registries()
    app.ed_file_var.set("events.md")
    app._ed_current = None
    _set("title", "Chest trap")
    _set("slug", "chest-trap")
    _set("triggers", "chest, lid")
    _set("once", True)
    app.ed_body.delete("1.0", "end")
    app.ed_body.insert("1.0", "The lid is wired to a needle.")
    app._ed_save()
    ev = lib.scenarios.store(scen).entries("events.md")
    assert [e.slug for e in ev] == ["chest-trap"], [e.slug for e in ev]
    assert ev[0].attrs.get("once") == "true", ev[0].attrs
    print("5. event rule authored in the world, once=true")


def test_character_depth_fields():
    app.ed_file_var.set("characters.md")
    app._ed_current = None
    _set("title", "Aria")
    _set("slug", "aria")
    _set("wants", "reach the manor before dawn")
    _set("motivation", "her sister's debt is owed there")
    _set("traits", "wary, quick")
    _set("playable", True)
    app.ed_body.delete("1.0", "end")
    app.ed_body.insert("1.0", "A night courier.")
    app._ed_save()
    e = next(x for x in lib.scenarios.store(scen).entries("characters.md")
             if x.slug == "aria")
    assert e.attrs["wants"] == "reach the manor before dawn", e.attrs
    assert e.attrs["motivation"] == "her sister's debt is owed there", e.attrs
    assert e.attrs["traits"] == "wary, quick", e.attrs
    assert e.attrs["playable"] == "true", e.attrs
    # and back out again — the form must repopulate them
    app._ed_load_list()
    for i, s in enumerate(app.ed_list.get(0, "end")):
        if "aria" in str(s):
            app.ed_list.selection_clear(0, "end")
            app.ed_list.selection_set(i)
            break
    app._ed_load_entry()
    assert app.ed_fields["wants"].get() == "reach the manor before dawn"
    assert app.ed_fields["playable"].get() is True
    print("6. wants / motivation / traits / playable round-trip")


for fn in (test_scenario_store_api,
           test_http_layer_shares_them,
           test_scope_picker_lists_worlds,
           test_world_scope_writes_to_the_scenario,
           test_event_rule_is_authorable,
           test_character_depth_fields):
    fn()

app.destroy()
shutil.rmtree(WORK, ignore_errors=True)
print("\nGUI WORLD AUTHORING TESTS PASSED")
