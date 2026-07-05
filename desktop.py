"""Coderain desktop — the web app in its own native window.

    .venv\\Scripts\\python.exe desktop.py           # dev run
    Coderain.exe                                  # frozen build

Starts the FastAPI server (server.py's `app`) on a free localhost port in a
background thread, then opens a chromeless native window on it (pywebview →
Edge WebView2 on Windows). Closing the window exits the app.

User data lives in %LOCALAPPDATA%\\Coderain when frozen (see
config._home_dir); CODERAIN_HOME overrides. CODERAIN_PORT pins the port
(handy for debugging a running instance).
"""
from __future__ import annotations

import io
import os
import socket
import sys
import threading
import time
import urllib.request


def _fix_std_streams() -> None:
    """A --windowed frozen build has no console: sys.stdout/stderr are None,
    which crashes uvicorn's logging setup and any stray print(). Give them a
    throwaway sink so the whole stack behaves as if a console existed."""
    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is None:
            setattr(sys, name, io.StringIO())


def _free_port() -> int:
    pinned = os.environ.get("CODERAIN_PORT", "").strip()
    if pinned.isdigit():
        return int(pinned)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> None:
    _fix_std_streams()
    port = _free_port()
    url = f"http://127.0.0.1:{port}"

    # Import late: server.py seeds the data dir + loads config on import.
    import uvicorn
    import server as server_mod

    # log_config=None: skip uvicorn's dictConfig entirely — in a windowed build
    # its default 'default'/'access' formatters attach to sys.stdout and blow up
    # (the isatty-on-None crash). We don't need request logs in the desktop app.
    cfg = uvicorn.Config(server_mod.app, host="127.0.0.1", port=port,
                         log_config=None, access_log=False)
    srv = uvicorn.Server(cfg)
    threading.Thread(target=srv.run, daemon=True).start()

    # Wait for readiness (a few seconds covers a cold first run that seeds
    # instructions/ and default config).
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url + "/api/settings", timeout=1):
                break
        except Exception:  # noqa: BLE001 — still booting
            time.sleep(0.2)

    import webview
    webview.create_window("Coderain", url, width=1280, height=860,
                          min_size=(900, 600), background_color="#03060a")
    webview.start()          # blocks until the window closes
    srv.should_exit = True   # stop uvicorn cleanly, then exit


if __name__ == "__main__":
    main()
