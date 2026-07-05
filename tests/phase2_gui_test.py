import os, sys, shutil, tempfile
sys.path.insert(0, r"F:\Seven\StoryEngine")
import gui
from coderain.memory import Library
from coderain.config import load_config, save_yaml

# config round-trip for use_memory_tool (temp file, real config untouched)
cfg = load_config()
raw = cfg.raw
raw["generation"]["use_memory_tool"] = True
tmp_yaml = os.path.join(tempfile.gettempdir(), "se_cfg.yaml")
save_yaml(raw, tmp_yaml)
reloaded = load_config(tmp_yaml)
assert reloaded.generation["use_memory_tool"] is True
print("config round-trip: use_memory_tool persisted OK")

# GUI runtime smoke against a temp saves dir
root = os.path.join(tempfile.gettempdir(), "se_p2_gui")
if os.path.exists(root): shutil.rmtree(root)
lib = Library(root)
slug = lib.create_story("GuiP2", "A test premise.")
lib.store(slug).append_turn("narrator", "Rain hammers the shutters.")  # no model call

app = gui.App(root=root)
app.update_idletasks(); app.update()
assert hasattr(app, "tool_var"), "memory-tool checkbox missing"
for f in gui.EDITABLE_FILES:
    app.mem_file_var.set(f); app._load_mem_file(); app.update()
# memory-tool checkbox toggles
app.tool_var.set(True); app.update()
assert app.tool_var.get() is True
# memory-file save works when NOT generating (guard doesn't block normal saves)
assert not app.generating
app.mem_file_var.set("world-bible.md"); app._load_mem_file()
app.mem_edit.insert("end", "\nThe moon is red.\n"); app._save_mem_file()
assert "The moon is red." in app.store.read("world-bible.md")
print("opened:", app.story_var.get(), "| tool toggles + mem save OK")
app.destroy()
print("PHASE 2 GUI SMOKE PASSED")
