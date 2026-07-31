"""Desktop parity phase 5: user defaults.

The templates every NEW world and story is seeded from. The logic was inline in
srv/defaults.py, so a user who only opens the desktop build could not change the
templates their stories are built from.

The two kinds behave differently and that difference is the whole risk:
  RULE     lives in instructions/, re-read EVERY turn, "customized" = text
           differs from shipped, revert REWRITES it with the shipped text.
  SKELETON lives in instructions/defaults/, read only when seeding a new story,
           "customized" = the file EXISTS, revert DELETES it.

 1) both kinds are listed, tagged with their kind
 2) a rule: write marks it customized, revert restores the shipped text
 3) a skeleton: write creates the file, revert deletes it
 4) a non-defaultable name is refused by DefaultError, not silently written
 5) the HTTP route and the shared function agree
 6) the dialog lists, edits and reverts through the same functions
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-guidef-"))
os.environ["CODERAIN_HOME"] = str(WORK)

from coderain import defaults as cr_defaults          # noqa: E402
from coderain import templates                         # noqa: E402
from coderain.memory import Library                    # noqa: E402

lib = Library(WORK / "lib")
RULE = list(templates.RULE_FILES)[0]
SKEL = list(templates.USER_DEFAULTABLE)[0]


def test_lists_both_kinds():
    rows = cr_defaults.list_defaults(lib)
    by = {r["name"]: r for r in rows}
    assert by[RULE]["kind"] == "rule", by[RULE]
    assert by[SKEL]["kind"] == "skeleton", by[SKEL]
    assert len(rows) == len(cr_defaults.defaultable_names())
    print(f"1. {len(rows)} defaults listed; {RULE}=rule, {SKEL}=skeleton")


def test_rule_write_and_revert():
    shipped = templates.default_rule(RULE)
    cr_defaults.write_default(lib, RULE, shipped + "\n\nMY EXTRA RULE.\n")
    row = {r["name"]: r for r in cr_defaults.list_defaults(lib)}[RULE]
    assert row["customized"] is True, row
    assert "MY EXTRA RULE." in cr_defaults.read_default(lib, RULE)
    cr_defaults.revert_default(lib, RULE)
    assert cr_defaults.read_default(lib, RULE) == shipped
    row = {r["name"]: r for r in cr_defaults.list_defaults(lib)}[RULE]
    assert row["customized"] is False, row
    print("2. rule: customized on write, shipped text back on revert")


def test_skeleton_write_and_revert():
    """§3 the asymmetry: a skeleton is customized by EXISTING, and reverting
    deletes it rather than rewriting it."""
    path = lib.instructions_dir / "defaults" / SKEL
    cr_defaults.write_default(lib, SKEL, "my skeleton body")
    assert path.exists(), path
    assert cr_defaults.read_default(lib, SKEL) == "my skeleton body"
    assert {r["name"]: r for r in cr_defaults.list_defaults(lib)}[SKEL]["customized"]
    cr_defaults.revert_default(lib, SKEL)
    assert not path.exists(), "revert must DELETE a skeleton override"
    cr_defaults.revert_default(lib, SKEL)          # twice is not an error
    print("3. skeleton: created on write, deleted on revert, idempotent")


def test_unknown_name_refused():
    for bad in ("../../etc/passwd", "not-a-real-file.md", ""):
        try:
            cr_defaults.write_default(lib, bad, "x")
            raise AssertionError(f"{bad!r} was writable")
        except cr_defaults.DefaultError:
            pass
    print("4. non-defaultable names refused by DefaultError")


def test_route_agrees_with_shared_function():
    import srv.core as core
    core.lib = lib
    import srv.defaults as routes
    routes.lib = lib
    assert routes.list_defaults()["defaults"] == cr_defaults.list_defaults(lib)
    assert routes.get_default(RULE)["text"] == cr_defaults.read_default(lib, RULE)
    print("5. HTTP route and coderain.defaults agree")


import gui as gui_mod                                  # noqa: E402
import tkinter as tk                                   # noqa: E402

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


def test_dialog_edits_and_reverts():
    dlg = app._defaults_dialog()
    names = [i["name"] for i in dlg.def_items]
    assert RULE in names and SKEL in names, names
    i = names.index(RULE)
    dlg.def_list.selection_clear(0, "end")
    dlg.def_list.selection_set(i)
    dlg.def_load()                    # selection_set does not fire the event
    dlg.def_text.insert("end", "\nDESKTOP EDIT\n")
    for w in dlg.winfo_children():
        for b in w.winfo_children():
            if isinstance(b, tk.Button) and b.cget("text") == "Save":
                b.invoke()
    assert "DESKTOP EDIT" in cr_defaults.read_default(lib, RULE)
    assert dlg.def_list.get(i).startswith("*"), dlg.def_list.get(i)
    for w in dlg.winfo_children():
        for b in w.winfo_children():
            if isinstance(b, tk.Button) and b.cget("text") == "Revert":
                b.invoke()
    assert "DESKTOP EDIT" not in cr_defaults.read_default(lib, RULE)
    assert not dlg.def_list.get(i).startswith("*"), dlg.def_list.get(i)
    dlg.destroy()
    print("6. dialog edits, marks customized, and reverts")


for fn in (test_lists_both_kinds,
           test_rule_write_and_revert,
           test_skeleton_write_and_revert,
           test_unknown_name_refused,
           test_route_agrees_with_shared_function,
           test_dialog_edits_and_reverts):
    fn()

app.destroy()
shutil.rmtree(WORK, ignore_errors=True)
print("\nGUI DEFAULTS TESTS PASSED")
