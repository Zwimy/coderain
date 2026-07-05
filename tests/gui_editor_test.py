"""Wave 4 Editor tab smoke (no model calls): the piece editor round-trips
entries through the real Entry machinery — form save == hand-edited Markdown.
"""
import os, sys, shutil, tempfile
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from coderain.memory import Library

root = os.path.join(tempfile.gettempdir(), "se_guieditor")
if os.path.exists(root): shutil.rmtree(root)
lib = Library(root)
slug = lib.create_story("ED", "A quiet harbor town.")
store = lib.store(slug)
store.append_turn("player", "look")
store.append_turn("narrator", "Gulls. Salt. A shuttered lighthouse.")

import gui as gui_mod

app = gui_mod.App(root=root)
app.update()

# ---- 1) editor tab built; registries listed ----
files = list(app.ed_file_box["values"])
assert "characters.md" in files and "events.md" in files, files
print("1) editor lists the save's registries")

# ---- 2) create a piece through the form ----
app.ed_file_var.set("characters.md")
app._ed_load_list()
app._ed_new()
f = app.ed_fields
f["title"].insert(0, "Keeper Ansel")
f["aliases"].insert(0, "the keeper")
f["importance"].delete(0, "end"); f["importance"].insert(0, "4")
f["weight"].set("important")
f["hidden"].set(True)
f["triggers"].insert(0, "lighthouse")
f["stats"].insert(0, "willpower 3")
app.ed_body.insert("1.0", "He has not lit the lamp in nine years.")
app._ed_save()
e = next(e for e in store.entries("characters.md") if e.slug == "keeper-ansel")
assert e.aliases == ["the keeper"] and e.importance == 4
assert e.weight() == "important" and e.hidden()
assert "lighthouse" in e.triggers() and e.stats() == {"willpower": 3}
assert "nine years" in e.body
print("2) form save lands as a normal md entry (attrs + body intact)")

# ---- 3) round-trip: load into the form, edit, re-save ----
app._ed_load_list()
titles = [app.ed_list.get(i) for i in range(app.ed_list.size())]
idx = next(i for i, t in enumerate(titles) if "Keeper Ansel" in t)
assert "[hidden]" in titles[idx]
app.ed_list.selection_set(idx)
app._ed_load_entry()
assert app.ed_fields["title"].get() == "Keeper Ansel"
assert app.ed_fields["hidden"].get() is True
app.ed_fields["hidden"].set(False)
app.ed_fields["status"].insert(0, "seen at the quay")
app._ed_save()
e = next(e for e in store.entries("characters.md") if e.slug == "keeper-ansel")
assert not e.hidden() and e.attrs.get("status") == "seen at the quay"
print("3) round-trip edit preserves and updates attributes")

# ---- 4) add a custom lore type from the editor ----
app._ed_add_type_direct = getattr(app, "_ed_add_type", None)
rel = store.add_custom_file("Legends")
app._ed_load_files()
assert "legends.md" in list(app.ed_file_box["values"])
print("4) custom lore type appears in the editor")

# ---- 5) delete via the machinery ----
app.ed_file_var.set("characters.md")
app._ed_load_list()
store.remove_entry("characters.md", "keeper-ansel")
app._ed_load_list()
titles = [app.ed_list.get(i) for i in range(app.ed_list.size())]
assert not any("Keeper Ansel" in t for t in titles)
print("5) deletion reflected in the list")

app.destroy()
print("\nGUI EDITOR TESTS PASSED")
