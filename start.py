"""Coderain — single start-up.

The one file to launch everything. Double-click `Coderain.bat`, or run:

    py start.py            # desktop GUI (default)
    py start.py --cli      # terminal / text mode

It self-heals the two things that usually trip a fresh checkout on Windows:
  1. re-launches itself under the project's `.venv` interpreter if you started it
     with a different Python (so the deps are always there), and
  2. checks the core deps are importable and prints a clear install hint if not.

The Tcl/Tk path fix for the GUI lives in `gui.py` (`_ensure_tcl`, runs on import).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
_REEXEC_FLAG = "STORYENGINE_REEXEC"


def _venv_python(cli: bool) -> Path | None:
    """The project venv interpreter, if present. Console app -> python.exe (needs a
    console); GUI -> pythonw.exe (no console window when double-clicked)."""
    scripts = ROOT / ".venv" / "Scripts"
    if not scripts.is_dir():                       # POSIX venvs put it in bin/
        scripts = ROOT / ".venv" / "bin"
    if not scripts.is_dir():
        return None
    for name in (("python.exe", "python") if cli else ("pythonw.exe", "python")):
        cand = scripts / name
        if cand.exists():
            return cand
    return None


def _reexec_in_venv(cli: bool) -> None:
    """If a venv exists and we're not already running under it, relaunch there once."""
    if os.environ.get(_REEXEC_FLAG):
        return
    venv_py = _venv_python(cli)
    if venv_py is None:
        return
    try:
        same = Path(sys.executable).resolve() == venv_py.resolve()
    except OSError:
        same = False
    if same:
        return
    env = {**os.environ, _REEXEC_FLAG: "1"}
    sys.exit(subprocess.call([str(venv_py), str(ROOT / "start.py"), *sys.argv[1:]],
                             env=env))


def _check_deps(cli: bool) -> None:
    missing = []
    for mod in ("openai", "yaml", "dotenv"):
        try:
            __import__(mod)
        except ImportError:
            missing.append("pyyaml" if mod == "yaml"
                           else "python-dotenv" if mod == "dotenv" else mod)
    if not missing:
        return
    msg = ("Coderain is missing dependencies: " + ", ".join(missing)
           + f"\n\nInstall them, e.g.:\n    {sys.executable} -m pip install "
           + " ".join(missing))
    if cli:
        sys.exit(msg)
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Coderain — missing dependencies", msg)
    except Exception:  # noqa: BLE001 — no Tk either; fall back to stderr
        sys.exit(msg)
    sys.exit(1)


def main() -> None:
    cli = any(a in ("--cli", "-c", "--text") for a in sys.argv[1:])
    _reexec_in_venv(cli)
    sys.path.insert(0, str(ROOT))
    _check_deps(cli)
    if cli:
        from play import main as run_cli
        run_cli()
    else:
        import gui                                  # _ensure_tcl() runs on import
        gui.App().mainloop()


if __name__ == "__main__":
    main()
