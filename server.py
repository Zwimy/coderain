"""Coderain web server (Phase 6) — the MAIN app UI.

FastAPI + a static SPA (webapp/). One process, local-first:

    .venv\\Scripts\\python.exe server.py          # http://127.0.0.1:8377

The Tkinter app (gui.py) remains as the retro easter egg; everything new lands
here first. Endpoints are thin wrappers over the same Engine/Library the CLI
and GUI use — no engine logic lives here.

This file is the assembly point. The endpoints themselves live in srv/, one
module per domain; srv/core.py holds the app object and the state they share.
Names are re-exported below so `server.lib`, `server._engine` and friends keep
working for the tests and for anything that imports this module.
"""
from __future__ import annotations

from pathlib import Path

import httpx                       # noqa: F401 — tests stub server.httpx.get
import uvicorn
from fastapi import HTTPException  # noqa: F401 — re-exported
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from srv import (authoring, core, defaults, files, outline, play, saves,
                 scenarios, settings, transfer, world)
# Re-exports, so `server.lib` and friends keep resolving. Everything here is
# read-only from this module's point of view — the routers own the writes.
from srv.core import (HOSTED_KEY_ENV, OLLAMA_TAGS, ROOT, _cancel,  # noqa: F401
                      _clean_quick_actions, _clean_regex_rules, _engine,
                      _engines, _EXPORT_DIR, _exclusive, _gen_lock,
                      _guard_slug, _model_error_kind, _model_error_text,
                      _reload_config, _save_payload, _sheet_lines, _sse,
                      app, characters, lib, pieces_lib)
from srv.pieces import _entry_from_dict, _save_store, _scen_store  # noqa: F401

# Assets (webapp/) always come from the install/bundle dir — deliberately
# anchored on THIS file, which sits at the root both in the repo and in the
# frozen build. Save data lives elsewhere (srv.core.ROOT).
ASSETS = Path(__file__).resolve().parent

for _mod in (saves, outline, play, scenarios, world, authoring, transfer,
             defaults, files, settings):
    app.include_router(_mod.router)


def __getattr__(name):
    """`_cfg` is REBOUND every time settings change (srv.core._reload_config),
    so it can't be a plain re-export — that would freeze the boot-time config.
    PEP 562 lets `server._cfg` stay a live read of the real one."""
    if name == "_cfg":
        return core._cfg
    raise AttributeError(f"module 'server' has no attribute {name!r}")


# ---------- static SPA ----------
class _FreshFiles(StaticFiles):
    """Serve the SPA with revalidate-always caching.

    Everything here comes off localhost, so there is no bandwidth to save by
    caching, and a stale asset is a real bug: unzip a new release over an old
    install and the browser will happily keep running the previous app.js
    against the new API. The failure looks like nothing in particular.

    `no-cache` still allows a conditional request, so an unchanged file costs a
    304 and no body. ES module imports (`./util.js`) resolve without the entry
    file's query string, so a ?v= stamp would only bust the entry point — this
    covers the whole graph.
    """

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
        return resp


@app.get("/")
def index():
    return FileResponse(ASSETS / "webapp" / "index.html",
                        headers={"Cache-Control": "no-cache, must-revalidate"})


app.mount("/", _FreshFiles(directory=ASSETS / "webapp"), name="webapp")


if __name__ == "__main__":
    import os
    _port = int((os.environ.get("CODERAIN_PORT") or "8377").strip() or "8377")
    uvicorn.run(app, host="127.0.0.1", port=_port)
