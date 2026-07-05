"""Coderain — one launcher.

The single command to run everything. Double-click `Coderain.bat` (Windows) or
`run.sh` (macOS/Linux), or run:

    python start.py               # web app — starts the server, opens your browser
    python start.py --no-browser  # ... start the server but don't open a browser
    python start.py --port 8399   # ... on a specific port (default 8377)
    python start.py --cli         # terminal / text mode
    python start.py --gui         # the retro Win2000 Tkinter UI (an easter egg)

First run self-heals a fresh checkout: if there's no `.venv` it creates one,
installs `requirements.txt` into it, and relaunches itself there. So after a
`git clone`, `python start.py` is the ONLY step — no manual venv, no pip.

If a `.venv` already exists but is missing a dependency (the classic
`ModuleNotFoundError: httpx`), it's installed automatically instead of crashing.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REQ = ROOT / "requirements.txt"
_REEXEC_FLAG = "CODERAIN_REEXEC"

# import name -> pip name. The deps the web app (default mode) needs; the CLI/GUI
# need a subset, but the venv gets the full set anyway, so we check them all.
_CORE_MODS = {
    "openai": "openai", "yaml": "pyyaml", "dotenv": "python-dotenv",
    "fastapi": "fastapi", "uvicorn": "uvicorn", "httpx": "httpx",
}


# ---------- venv discovery / bootstrap ----------
def _venv_python() -> Path | None:
    """The project venv interpreter, if the venv exists."""
    scripts = ROOT / ".venv" / "Scripts"          # Windows
    if not scripts.is_dir():
        scripts = ROOT / ".venv" / "bin"          # POSIX
    if not scripts.is_dir():
        return None
    for name in ("python.exe", "python"):
        cand = scripts / name
        if cand.exists():
            return cand
    return None


def _running_under(py: Path) -> bool:
    try:
        return Path(sys.executable).resolve() == py.resolve()
    except OSError:
        return False


def _pip_install(py: Path) -> None:
    print("Coderain: installing dependencies (first run, ~30s)...", flush=True)
    subprocess.check_call([str(py), "-m", "pip", "install", "-q", "-r", str(REQ)])


def _missing(mods: dict[str, str]) -> list[str]:
    out = []
    for mod, pip_name in mods.items():
        try:
            __import__(mod)
        except ImportError:
            out.append(pip_name)
    return out


def _bootstrap_and_reexec() -> None:
    """First run: make a .venv, install deps, and relaunch under it — exactly once.
    Already-under-venv or repeat runs fall straight through."""
    if os.environ.get(_REEXEC_FLAG):
        return                                    # this is the relaunched child
    venv_py = _venv_python()
    if venv_py is None:                           # fresh checkout: no venv yet
        print("Coderain: creating a virtual environment (.venv)...", flush=True)
        try:
            subprocess.check_call(
                [sys.executable, "-m", "venv", str(ROOT / ".venv")])
            venv_py = _venv_python()
            if venv_py is not None:
                _pip_install(venv_py)
        except (subprocess.CalledProcessError, OSError) as e:
            print(f"Coderain: automatic setup failed ({e}). Falling back to the "
                  "current Python.", flush=True)
            return                                # _ensure_deps() gives a hint
    if venv_py is None or _running_under(venv_py):
        return
    env = {**os.environ, _REEXEC_FLAG: "1"}
    sys.exit(subprocess.call([str(venv_py), str(ROOT / "start.py"), *sys.argv[1:]],
                             env=env))


def _ensure_deps() -> None:
    """Belt-and-braces after bootstrap: if imports still fail (a venv that predates
    a new dep — e.g. an old venv without httpx), install once, then re-check."""
    if not _missing(_CORE_MODS):
        return
    try:
        _pip_install(Path(sys.executable))
    except (subprocess.CalledProcessError, OSError):
        pass
    still = _missing(_CORE_MODS)
    if still:
        sys.exit("Coderain is missing dependencies: " + ", ".join(still)
                 + f"\n\nInstall them:\n    {sys.executable} -m pip install -r "
                 + str(REQ))


# ---------- run the web app ----------
def _run_web(open_browser: bool, port: int) -> None:
    url = f"http://127.0.0.1:{port}"
    import uvicorn
    import server as server_mod                   # import seeds data dir + config

    if open_browser:                              # server binds in <1s post-import
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    print(f"\n  Coderain is running  ->  {url}"
          "\n  (leave this window open; press Ctrl+C or close it to stop)\n",
          flush=True)
    uvicorn.run(server_mod.app, host="127.0.0.1", port=port)


# ---------- entry ----------
def main() -> None:
    args = sys.argv[1:]
    mode = ("cli" if any(a in ("--cli", "-c", "--text") for a in args)
            else "gui" if "--gui" in args
            else "web")
    open_browser = "--no-browser" not in args
    port = _arg_port(args)

    _bootstrap_and_reexec()                       # may relaunch under .venv and exit
    sys.path.insert(0, str(ROOT))
    _ensure_deps()

    if mode == "cli":
        from play import main as run_cli
        run_cli()
    elif mode == "gui":
        import gui                                 # _ensure_tcl() runs on import
        gui.App().mainloop()
    else:
        _run_web(open_browser, port)


def _arg_port(args: list[str]) -> int:
    """Port from `--port N`/`--port=N`, else $CODERAIN_PORT, else the default."""
    for i, a in enumerate(args):
        if a == "--port" and i + 1 < len(args) and args[i + 1].isdigit():
            return int(args[i + 1])
        if a.startswith("--port=") and a[7:].isdigit():
            return int(a[7:])
    return int((os.environ.get("CODERAIN_PORT") or "8377").strip() or "8377")


if __name__ == "__main__":
    main()
