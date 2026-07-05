"""GUI fix-pass smoke (no model calls): pinned sheet panel, generating note,
retry/undo transcript marks, dialog placement helper, scrollable settings.

Builds the real App against a temp library with an existing save (so opening
generation never fires) and drives the widgets directly.
"""
import os, sys, shutil, tempfile
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from coderain.memory import Library

root = os.path.join(tempfile.gettempdir(), "se_guipanel")
if os.path.exists(root): shutil.rmtree(root)
lib = Library(root)
slug = lib.create_story("GP", "A courier in the rain.")
store = lib.store(slug)
store.append_turn("player", "look around")
store.append_turn("narrator", "Rain. Cobbles. A door you don't remember.")
st = store.rpg_state(); st["enabled"] = True; store.set_rpg_state(st)

import tkinter as tk
import gui as gui_mod

app = gui_mod.App(root=root)
app.update()

# ---- 1) transcript rendered, engine built, no generation running ----
assert app.slug == slug and not app.generating
assert "Cobbles" in app.chat.get("1.0", "end")
print("1) app opened the save; transcript rendered")

# ---- 2) sheet = pinned panel (not a Toplevel), one value per line ----
assert not app.sheet_visible
app._show_sheet()
app.update()
assert app.sheet_visible and app.sheet_panel.winfo_manager() == "pack"
# The panel must actually get real width next to the expanding chat column
# (pack order pitfall: an expand=True sibling could squeeze it to nothing).
assert app.sheet_panel.winfo_width() > 80, app.sheet_panel.winfo_width()
sheet = app._sheet_text.get("1.0", "end")
assert "HP" in sheet and "— Stats —" in sheet and "Strength" in sheet, sheet
assert sheet.count("\n") >= 8            # vertical layout, one stat per line
app._show_sheet()                        # toggle off
app.update()
assert not app.sheet_visible and app.sheet_panel.winfo_manager() == ""
print("2) sheet toggles as a pinned side panel with per-line stats")

# ---- 3) generating note appears, animates, clears ----
app.generating = True
app._note_show("generating")
app.update()
assert app.chat.tag_ranges("gen_note"), "note not shown"
app._animate_note()
assert "generating." in app.chat.get("1.0", "end")
app._note_clear()
app.generating = False
assert not app.chat.tag_ranges("gen_note")
assert "generating." not in app.chat.get("1.0", "end")
print("3) generating note shows/animates/clears")

# ---- 4) retry marks: old response text removed from the widget ----
app._set_mark("turn_start")
app._append("\n> attack\n\n", "player")
app._set_mark("resp_start")
app._append("You swing and miss badly.", "narration")
assert "miss badly" in app.chat.get("1.0", "end")
assert app._clear_from_mark("resp_start")
assert "miss badly" not in app.chat.get("1.0", "end")
assert "> attack" in app.chat.get("1.0", "end")     # player line stays for retry
assert app._clear_from_mark("turn_start")
assert "> attack" not in app.chat.get("1.0", "end")  # undo removes the exchange
print("4) retry/undo marks strip superseded text; stale marks refused")

# stale marks after a story switch are refused (no wrong-page deletion)
app._marks_slug = "other-slug"
assert app._clear_from_mark("turn_start") is False

# ---- 5) dialog placement helper clamps to screen ----
dlg = tk.Toplevel(app)
tk.Label(dlg, text="x" * 40).pack()
app._place_dialog(dlg)
app.update()
geo = dlg.geometry()          # "WxH+X+Y" — X/Y must be non-negative ints
xy = geo.split("+")[1:]
assert len(xy) == 2 and all(int(v) >= 0 for v in xy), geo
dlg.destroy()
print("5) _place_dialog positions at pointer, clamped on-screen")

# ---- 6) settings tab is scrollable (canvas present) ----
canvases = [w for w in app.tab_settings.winfo_children()
            if isinstance(w, tk.Canvas)]
assert canvases, "settings not wrapped in a scrollable canvas"
print("6) settings wrapped in a scrollable canvas")

app.destroy()
print("\nGUI PANEL/UX TESTS PASSED")
