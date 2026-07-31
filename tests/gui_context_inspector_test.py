"""Desktop parity phase 3: the context inspector.

"What the model sees" answers "why did the story forget X" with "X is not in the
prompt, and here is what crowded it out". It existed only as an HTTP route with
its report built INLINE in srv/saves.py, so the desktop app — the build that
ships as a binary to people who will never open a browser devtools panel — could
not show it at all.

The report now lives in coderain.inspect and the route is transport only.

 1) the report names real assembled sections, not a guess
 2) the HTTP route returns exactly what the shared function returns
 3) health lines reach the report (invariant 2's visible half)
 4) the dialog renders every section and the billed totals
 5) a broken engine shows a message instead of taking the window down
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-guictx-"))
os.environ["CODERAIN_HOME"] = str(WORK)

from coderain.config import load_config          # noqa: E402
from coderain.engine import Engine               # noqa: E402
from coderain.inspect import context_report      # noqa: E402
from coderain.memory import Library              # noqa: E402

lib = Library(WORK / "lib")
slug = lib.create_story("CTX", "A courier crossing a frozen kingdom.")
store = lib.store(slug)
store.append_turn("player", "look")
store.append_turn("narrator", "Ice, and a shuttered lighthouse.")
store.write("world-bible.md", "# World bible\n\nWinter never ends here.\n")
store.log_degraded("fold", "scene 1 produced no summary")

cfg = load_config()
cfg.generation["trinity_brain"] = False


def test_report_names_real_sections():
    d = context_report(Engine(cfg, store), cfg)
    titles = [s["title"] for s in d["sections"]]
    assert "World" in titles, titles
    assert d["total_chars"] > 0 and d["approx_tokens"] > 0
    assert d["history_msgs"] >= 1, d["history_msgs"]
    # sorted biggest-first is what makes the panel useful at a glance
    chars = [s["chars"] for s in d["sections"]]
    assert chars == sorted(chars, reverse=True), chars
    print("1. sections are real and sorted biggest-first:", titles[:4])


def test_route_and_shared_function_agree():
    """§2 the whole point of extracting it: one report, two front ends."""
    import srv.core as core
    # Point the HTTP layer at THIS library. srv.core builds its own Library at
    # import time; without this the route 404s on a save that plainly exists,
    # and the assertion below would never run.
    core.lib = lib
    core._cfg = cfg
    from srv.saves import inspect_context
    core._engines.clear()
    via_route = inspect_context(slug)
    via_lib = context_report(Engine(cfg, store), cfg)
    assert via_route["sections"] == via_lib["sections"], "sections diverged"
    assert via_route["budget_tokens"] == via_lib["budget_tokens"]
    assert via_route["brain"] == via_lib["brain"]
    print("2. HTTP route and coderain.inspect return the same report")


def test_health_reaches_the_report():
    d = context_report(Engine(cfg, store), cfg)
    reasons = " ".join(h.get("reason", "") for h in d["health"])
    assert "produced no summary" in reasons, d["health"]
    print("3. quiet fallbacks surface in the report")


# ---- the dialog -------------------------------------------------------

import gui as gui_mod                              # noqa: E402
import tkinter as tk                               # noqa: E402

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


def test_dialog_renders_the_report():
    dlg = app._context_dialog()
    body = dlg.ctx_text.get("1.0", "end")
    for s in dlg.ctx_report["sections"]:
        assert s["title"][:30] in body, s["title"]
    assert "Billed so far" in body
    assert "produced no summary" in body, "health not rendered"
    dlg.destroy()
    print("4. dialog renders every section, health, and billed totals")


def test_broken_engine_does_not_kill_the_window():
    """§5 an inspector must never be the thing that breaks the app."""
    shown = {}
    real = gui_mod.messagebox.showinfo
    gui_mod.messagebox.showinfo = lambda t, m, *a, **k: shown.update(msg=m)
    saved = app.engine
    app.engine = object()                 # no _messages, no store
    try:
        assert app._context_dialog() is None
        assert "Couldn't inspect" in shown.get("msg", ""), shown
    finally:
        app.engine = saved
        gui_mod.messagebox.showinfo = real
    assert app.winfo_exists()
    print("5. a broken engine shows a message, window survives")


for fn in (test_report_names_real_sections,
           test_route_and_shared_function_agree,
           test_health_reaches_the_report,
           test_dialog_renders_the_report,
           test_broken_engine_does_not_kill_the_window):
    fn()

app.destroy()
shutil.rmtree(WORK, ignore_errors=True)
print("\nGUI CONTEXT INSPECTOR TESTS PASSED")
