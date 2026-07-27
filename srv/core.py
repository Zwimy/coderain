"""Shared app state and the helpers every router leans on.

`app`, the Library/profile singletons, the single generation lock, the
engine cache, and the SSE pump live here. `_cfg` is REBOUND whenever
settings change, so routers must read it as `core._cfg`, never bind it
at import time."""
from __future__ import annotations

import contextlib
import json
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from fastapi.responses import StreamingResponse
from coderain import features
from coderain import templates
from coderain.config import ROOT as DATA_ROOT
from coderain.config import load_config
from coderain.engine import Engine
from coderain.memory import Library
from coderain.memory import MemoryStore
from coderain.memory import safe_output_regex
from coderain.profiles import CharacterProfiles
from coderain.profiles import PieceLibrary

# Data (saves/scenarios/config/.env) lives in the user's home dir — the
# repo root in dev, %LOCALAPPDATA%\Coderain in the frozen desktop build
# (see config._home_dir). Assets (webapp/) come from the bundle dir.
ROOT = DATA_ROOT

OLLAMA_TAGS = "http://localhost:11434/api/tags"

HOSTED_KEY_ENV = "HOSTED_API_KEY"

app = FastAPI(title="Coderain")

lib = Library(ROOT)
# seed the bundled world on a fresh install
lib.scenarios.ensure_default()

characters = CharacterProfiles(ROOT)

pieces_lib = PieceLibrary(ROOT)

_cfg = load_config()

_engines: dict[str, Engine] = {}

# The local GPU (and most single-key plans) can't run turns in parallel —
# one generation at a time, app-wide.
_gen_lock = threading.Lock()

# Cooperative cancel for the Stop button. Only one generation runs at a time
# (the lock), so a single flag is enough. The stream pump checks it between
# chunks/stages and bails; closing the inner generator then runs turn()'s
# cleanup, so a stopped turn leaves no orphan behind.
_cancel = threading.Event()

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@app.middleware("http")
async def _same_origin_only(request, call_next):
    """Refuse mutating requests that came from another site's page.

    We bind to localhost, but that is NOT a security boundary: a browser tab on
    any website can POST here. CORS does not help, because a *simple* request is
    sent without a preflight — and both `multipart/form-data` uploads and POSTs
    with no body are simple. Without this guard, any page you visit while
    Coderain runs could rewrite instructions/writer-rules.md (the system prompt
    every story inherits), wipe turns via /undo, or loop /opening to burn hosted
    API credits. Requests with no Origin/Referer (curl, the desktop shell, the
    test client) are allowed — only a *foreign* origin is rejected.
    """
    if request.method not in _SAFE_METHODS:
        source = request.headers.get("origin") or request.headers.get("referer") or ""
        if source:
            try:
                origin_host = urlsplit(source).netloc.lower()
            except ValueError:
                origin_host = "invalid"
            if origin_host != (request.headers.get("host") or "").lower():
                return JSONResponse(
                    {"detail": "cross-origin request refused"}, status_code=403)
    return await call_next(request)


def _guard_slug(slug: str) -> str:
    """Reject a slug that isn't a clean id (a real slug equals slugify(slug)) — a
    boundary guard against path traversal on any endpoint that maps slug -> disk."""
    if not slug or slug != templates.slugify(slug):
        raise HTTPException(400, "invalid id")
    return slug

_MODEL_ERROR_TEXT = {
    "connection": "Can't reach the model. If you're running it locally, start "
                  "Ollama first; if you're using an API, check the base URL in "
                  "Settings.",
    "auth": "The API key was rejected. Re-enter it in Settings.",
    "timeout": "The model took too long to answer. Try again, or choose a "
               "smaller/faster model.",
    "context": "This story is longer than the model's context window. Lower the "
               "context budget in Settings, or branch to a shorter history.",
    "rate_limit": "The provider is rate-limiting this key. Wait a moment, then "
                  "retry.",
    "busy": "A turn is already generating — wait for it to finish.",
    "unknown": "The model call failed.",
}


def _model_error_kind(exc: BaseException) -> str:
    """Classify a generation failure so the UI can say something actionable
    instead of showing a raw SDK string like 'Connection error.'"""
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    if "connect" in name or "connect" in text or "refused" in text:
        return "connection"
    if "auth" in name or "401" in text or "unauthorized" in text \
            or "api key" in text or "invalid_api_key" in text:
        return "auth"
    if "timeout" in name or "timed out" in text:
        return "timeout"
    if "429" in text or "rate limit" in text or "ratelimit" in name:
        return "rate_limit"
    if "context" in text and ("length" in text or "window" in text
                              or "token" in text):
        return "context"
    return "unknown"


def _model_error_text(exc: BaseException) -> str:
    """A plain-language message. Never the raw exception: it can carry absolute
    filesystem paths, and 'Connection error.' tells a new user nothing."""
    return _MODEL_ERROR_TEXT[_model_error_kind(exc)]


@contextlib.contextmanager
def _exclusive():
    """Run a save-mutating (non-streaming) op under the single generation lock,
    failing fast with 409 rather than blocking if a turn is in flight — so an
    edit/undo/delete never races a generation nor hangs on a stuck stream."""
    if not _gen_lock.acquire(blocking=False):
        raise HTTPException(409, "a turn is generating — try again in a moment")
    try:
        yield
    finally:
        _gen_lock.release()


def _engine(slug: str) -> Engine:
    _guard_slug(slug)
    if slug not in _engines:
        try:
            store = lib.saves.store(slug)
        except FileNotFoundError:
            raise HTTPException(404, f"no such save: {slug}")
        _engines[slug] = Engine(_cfg, store)
    return _engines[slug]


def _reload_config() -> None:
    global _cfg
    try:
        new = load_config()               # a bad persisted config must not kill
    except SystemExit as e:               # the running server — keep the last good
        raise HTTPException(400, f"config not applied: {e}")
    _cfg = new
    _engines.clear()          # engines rebuild lazily against the new config


def _sse(obj: dict) -> str:
    return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"


def _quick_actions_for(store: MemoryStore) -> list[str]:
    """ST-30: the global quick actions (config) followed by this save's own, deduped."""
    merged = _clean_quick_actions(_cfg.raw.get("quick_actions"))
    for a in _clean_quick_actions(store.world_state().get("quick_actions")):
        if a not in merged:
            merged.append(a)
    return merged


def _save_payload(slug: str) -> dict:
    eng = _engine(slug)
    store = eng.store
    turns = store.turns()
    return {
        "slug": slug,
        "title": store.title,
        "mode": store.mode(),
        "rpg": store.rpg_enabled(),
        "turns": turns,
        "sheet": _sheet_lines(eng),
        "companions": eng.companions(),
        "clock": store.clock_str(),
        "quick_actions": _quick_actions_for(store),
    }


def _sheet_lines(eng: Engine) -> list[str]:
    store = eng.store
    if not store.rpg_enabled():
        return []
    try:
        rpg_mod = features.module("rpg")
        if rpg_mod is None:
            return []
        text = rpg_mod.render_sheet_lines(store.rpg_state(),
                                          store.world_state())
        return text.splitlines() if isinstance(text, str) else list(text)
    except Exception:  # noqa: BLE001 — the sheet must never kill a request
        return []


def _stream_generation(slug: str, run):
    """Shared SSE pump: `run(eng, notes)` returns the prose iterator. Stage
    notes are flushed between chunks so the UI shows pipeline progress live."""
    eng = _engine(slug)

    def gen():
        if not _gen_lock.acquire(blocking=False):
            yield _sse({"t": "error", "code": "busy",
                        "text": _MODEL_ERROR_TEXT["busy"]})
            return
        _cancel.clear()
        it = None
        try:
            notes: list[str] = []
            it = run(eng, notes)
            for piece in it:
                if _cancel.is_set():
                    # Stop pressed: bail before folding. The finally closes `it`,
                    # which runs turn()'s cleanup so no orphan turn is left.
                    yield _sse({"t": "error", "code": "aborted",
                                "text": "Stopped."})
                    return
                while notes:
                    yield _sse({"t": "stage", "text": notes.pop(0)})
                if piece:
                    yield _sse({"t": "chunk", "text": piece})
            while notes:
                yield _sse({"t": "stage", "text": notes.pop(0)})
            events = eng.maybe_fold()
            # ST-31: hand back the final STORED narrator text so the client can
            # settle the streamed (raw) turn onto the regex-cleaned version.
            tail = eng.store.turns()
            final = tail[-1]["text"] if tail and tail[-1]["role"] == "narrator" else None
            yield _sse({"t": "done", "events": events,
                        "sheet": _sheet_lines(eng),
                        "clock": eng.store.clock_str(),
                        "turns": len(eng.store.turns()),
                        "text": final})
        except Exception as e:  # noqa: BLE001 — surface, never hang the stream
            # Classified + plain-language: the raw exception can leak absolute
            # paths, and 'Connection error.' is meaningless to a new user.
            yield _sse({"t": "error", "code": _model_error_kind(e),
                        "text": _model_error_text(e)})
        finally:
            # Deterministically run the inner generator's cleanup (drop an orphan
            # player turn) rather than waiting for GC, then always free the lock.
            if it is not None:
                it.close()
            _gen_lock.release()
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


# ---------- Tier 4 play aids: quick actions (ST-30) + regex rules (ST-31) ----------
def _clean_quick_actions(raw) -> list[str]:
    if isinstance(raw, str):
        raw = raw.split("\n")
    if not isinstance(raw, list):
        return []
    return [s.strip() for s in raw if isinstance(s, str) and s.strip()][:20]


def _clean_regex_rules(raw) -> list[dict]:
    out = []
    if not isinstance(raw, list):
        return out
    for r in raw:
        if not isinstance(r, dict):
            continue
        find = r.get("find")
        # a non-string or ReDoS-prone pattern is dropped on save (import re-checks
        # at exec time too, since import bypasses this cleaning layer).
        if not isinstance(find, str) or not safe_output_regex(find):
            continue
        out.append({"find": find, "replace": str(r.get("replace", ""))[:1000],
                    "flags": "".join(c for c in str(r.get("flags", "")).lower()
                                     if c in "ims")})
        if len(out) >= 30:
            break
    return out

# ---------- exports ----------
_EXPORT_DIR = Path(tempfile.gettempdir()) / "coderain-exports"
