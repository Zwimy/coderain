"""Coderain web server (Phase 6) — the MAIN app UI.

FastAPI + a static SPA (webapp/). One process, local-first:

    .venv\\Scripts\\python.exe server.py          # http://127.0.0.1:8377

The Tkinter app (gui.py) remains as the retro easter egg; everything new lands
here first. Endpoints are thin wrappers over the same Engine/Library the CLI
and GUI use — no engine logic lives in this file.
"""
from __future__ import annotations

import contextlib
import copy
import io
import json
import queue
import shutil
import tempfile
import threading
import uuid
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from coderain import models as models_mod
from coderain import features
from coderain.config import (load_config, read_env, save_yaml,
                                write_env)
from coderain import templates
from coderain.engine import Engine
from coderain.generator import (PIECE_KINDS, ScenarioSpec,
                                   _split_premise_body, _write_premise_md,
                                   assist_field, complete_scenario)
from coderain.llm import LLM
from coderain.memory import (Entry, Library, MemoryStore, _safe_zip_member,
                             safe_output_regex)
from coderain.profiles import (STAT_NAMES, CharacterProfiles,
                                  PieceLibrary, apply_character,
                                  apply_playable_entry, character_from_entry,
                                  entry_from_character)

# Data (saves/scenarios/config/.env) lives in the user's home dir — the repo
# root in dev, %LOCALAPPDATA%\Coderain in the frozen desktop build (see
# config._home_dir). Assets (webapp/) always come from the install/bundle dir.
from coderain.config import ROOT as DATA_ROOT  # noqa: E402
ROOT = DATA_ROOT
ASSETS = Path(__file__).resolve().parent
OLLAMA_TAGS = "http://localhost:11434/api/tags"
HOSTED_KEY_ENV = "HOSTED_API_KEY"

app = FastAPI(title="Coderain")
lib = Library(ROOT)
lib.scenarios.ensure_default()   # seed the bundled world on a fresh install (web mode)
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


# ---------- library ----------
@app.get("/api/saves")
def list_saves():
    return {"saves": lib.saves.list(), "scenarios": lib.scenarios.list(),
            "characters": characters.list()}


@app.post("/api/saves")
def create_save(body: dict):
    title = str(body.get("title", "")).strip() or "Untitled"
    scenario = str(body.get("scenario", "")).strip()
    mode = body.get("mode") if body.get("mode") in ("simple", "rpg") \
        else "simple"
    premise = str(body.get("premise", "")).strip()
    start_time = body.get("start_time") if isinstance(
        body.get("start_time"), dict) else None
    slug = lib.saves.create(title, scenario, mode=mode, premise=premise,
                            rpg_cfg=_cfg.rpg, start_time=start_time)
    cid = str(body.get("character", "")).strip()
    if cid:
        char = characters.get(cid)
        if char:
            apply_character(lib.saves.store(slug), char)
    # Play as one of the WORLD's playable characters (piece slug): the files
    # were just copied from the scenario, so resolve it in the save itself.
    pslug = str(body.get("playable", "")).strip()
    if pslug:
        store = lib.saves.store(slug)
        entry = next((e for e in store.entries("characters.md")
                      if e.slug == pslug), None)
        if entry is not None:
            apply_playable_entry(store, entry)
    # Create-your-own player character: an inline name/description writes the
    # save's player.md, so a brand-new world (whose generated cast is all NPCs)
    # still lets you BE someone specific.
    pname = str(body.get("player_name", "")).strip()
    pdesc = str(body.get("player_desc", "")).strip()
    if pname or pdesc:
        store = lib.saves.store(slug)
        store.upsert_entry("player.md", Entry(
            title=pname or "You", slug="player", importance=5,
            body=pdesc or ""))
    return {"slug": slug}


@app.get("/api/saves/{slug}")
def get_save(slug: str):
    return _save_payload(slug)


@app.delete("/api/saves/{slug}")
def delete_save(slug: str):
    _guard_slug(slug)
    with _exclusive():                       # don't rmtree files under a live turn
        _engines.pop(slug, None)
        if not lib.saves.delete(slug):
            raise HTTPException(404, f"no such save: {slug}")
    return {"ok": True}


@app.put("/api/saves/{slug}/mode")
def set_save_mode(slug: str, body: dict):
    """Switch a story between simple and rpg after creation. `mode` was fixed at
    creation, so a story started in simple could never gain mechanics (or lose
    them) without starting over or hand-editing meta.json."""
    mode = str(body.get("mode", "")).strip().lower()
    if mode not in ("simple", "rpg"):
        raise HTTPException(400, "mode must be 'simple' or 'rpg'")
    if mode == "rpg" and not features.enabled("rpg"):
        raise HTTPException(402, "RPG mechanics need Coderain Pro")
    _guard_slug(slug)
    with _exclusive():
        meta = lib.saves.meta(slug)
        if not meta:
            raise HTTPException(404, f"no such save: {slug}")
        meta["mode"] = mode
        lib.saves._write_meta(slug, meta)
        store = _save_store(slug)
        st = store.rpg_state()
        st["enabled"] = (mode == "rpg")
        store.set_rpg_state(st)
        _engines.pop(slug, None)             # rebuild with the new mode
    return {"ok": True, "mode": mode}


@app.post("/api/saves/{slug}/branch")
def branch_save(slug: str, body: dict):
    try:
        n = int(body.get("turn", 0))
    except (TypeError, ValueError):
        raise HTTPException(400, "turn must be a number")
    total = len(_engine(slug).store.turns())
    if not 1 <= n <= total:
        raise HTTPException(400, f"turn must be 1..{total}")
    with _exclusive():                       # copy a consistent transcript snapshot
        new_slug, warnings = lib.saves.branch(slug, n, _cfg.rpg)
    return {"slug": new_slug, "warnings": warnings}


# ---------- play ----------
def _reset_swipes(slug: str) -> None:
    eng = _engines.get(slug)
    if eng is not None:
        eng._swipes = None      # a genuine new/edited turn invalidates alternates


@app.post("/api/saves/{slug}/opening")
def opening(slug: str):
    _reset_swipes(slug)
    return _stream_generation(
        slug, lambda eng, notes: eng.opening(on_stage=notes.append))


@app.post("/api/saves/{slug}/turn")
def turn(slug: str, body: dict):
    text = str(body.get("text", "")).strip()
    if not text:
        raise HTTPException(400, "empty action")
    _reset_swipes(slug)
    return _stream_generation(
        slug, lambda eng, notes: eng.turn(text, on_stage=notes.append))


@app.put("/api/saves/{slug}/turns/{i}")
def edit_turn(slug: str, i: int, body: dict):
    """In-place message edit (ST-03)."""
    eng = _engine(slug)
    with _exclusive():                       # don't rewrite the transcript mid-turn
        if not eng.store.update_turn(i, str(body.get("text", ""))):
            raise HTTPException(400, f"no turn at index {i}")
        eng._swipes = None
    return {"ok": True}


@app.post("/api/saves/{slug}/impersonate")
def impersonate(slug: str):
    """Draft the player's next action (ST-04). Returns text; stores nothing."""
    eng = _engine(slug)
    with _exclusive():
        try:
            return {"text": eng.impersonate()}
        except HTTPException:
            raise
        except Exception as e:                      # noqa: BLE001
            # The SSE routes already turn this into a friendly frame; this one
            # used to hand the browser a bare 500 + a server traceback.
            raise HTTPException(502, _model_error_text(e))


@app.post("/api/saves/{slug}/swipe")
def swipe_browse(slug: str, body: dict):
    """Browse cached narrator alternates without generating (ST-02)."""
    eng = _engine(slug)
    direction = 1 if int(body.get("dir", 1)) >= 0 else -1
    with _exclusive():                       # rewrites the tail turn — not mid-gen
        out = eng.swipe_browse(direction)
    if out is None:
        raise HTTPException(400, "nothing to swipe")
    return out


@app.post("/api/saves/{slug}/swipe-gen")
def swipe_gen(slug: str):
    """Generate a NEW narrator alternate and select it (ST-02)."""
    return _stream_generation(
        slug, lambda eng, notes: eng.swipe_generate(on_stage=notes.append))


@app.post("/api/saves/{slug}/cancel")
def cancel_generation(slug: str):
    """Stop the in-flight turn. Sets the cooperative flag the stream pump checks
    between chunks; the turn then unwinds and its player action is cleaned up.
    (A non-streaming planner stage finishes first — cancel lands at the next
    chunk boundary.)"""
    _cancel.set()
    return {"ok": True}


@app.post("/api/saves/{slug}/undo")
def undo(slug: str):
    eng = _engine(slug)
    with _exclusive():
        ok = eng.undo_last()
        eng._swipes = None
    return {"ok": ok, "turns": len(eng.store.turns()),
            "sheet": _sheet_lines(eng)}


@app.post("/api/saves/{slug}/retry")
def retry(slug: str):
    eng = _engine(slug)
    turns = eng.store.turns()
    if not (turns and turns[-1]["role"] in ("narrator", "player")):
        raise HTTPException(400, "nothing to retry yet")

    def run(e, notes):
        # The destructive rollback runs UNDER the generation lock (inside the
        # stream) so it can't truncate the transcript of an in-flight turn.
        t = e.store.turns()
        if t and t[-1]["role"] == "narrator" and len(t) >= 2:
            last_player = t[-2]["text"]
            e.store.drop_last_turns(2)
        elif t and t[-1]["role"] == "player":
            last_player = t[-1]["text"]
            e.store.drop_last_turns(1)
        else:
            return iter(())               # nothing to retry (raced away)
        e.restore_pre_turn_rpg()
        e._swipes = None
        return e.turn(last_player, on_stage=notes.append)

    return _stream_generation(slug, run)


@app.post("/api/saves/{slug}/continue")
def continue_story(slug: str):
    """Extend the prose with no player action (the 'Continue' button)."""
    _reset_swipes(slug)
    return _stream_generation(
        slug, lambda eng, notes: eng.continue_story(on_stage=notes.append))


@app.post("/api/saves/{slug}/talk")
def talk(slug: str, body: dict):
    name = str(body.get("name", "")).strip()
    text = str(body.get("text", "")).strip()
    if not name or not text:
        raise HTTPException(400, "need a companion name and a message")
    return _stream_generation(
        slug, lambda eng, notes: eng.companion_chat(name, text))


# ---------- scenarios (FictionLab shape: name + premise + introduction) ----
_BASE_PIECE_FILES = ["characters.md", "locations.md", "items.md",
                     "factions.md", "threads.md", "events.md"]


def _scen_store(slug: str) -> MemoryStore:
    _guard_slug(slug)
    scen_dir = lib.scenarios.dir(slug)
    if not (scen_dir / "scenario.json").exists():
        raise HTTPException(404, f"no such scenario: {slug}")
    # scenario_dir = itself so custom lore types (scenario.json) resolve
    return MemoryStore(scen_dir, None, scen_dir)


def _piece_files(store: MemoryStore) -> list[str]:
    return _BASE_PIECE_FILES + [f for f in store.custom_files()
                                if f not in _BASE_PIECE_FILES]


def _entry_dict(e: Entry) -> dict:
    return {"title": e.title, "slug": e.slug, "aliases": e.aliases,
            "importance": e.importance, "attrs": e.attrs, "body": e.body}


def _entry_from_dict(d: dict) -> Entry:
    from coderain.templates import slugify
    title = str(d.get("title", "")).strip()
    slug = slugify(str(d.get("slug", "")).strip() or title)
    if not title or not slug:
        raise HTTPException(400, "a piece needs at least a title")
    try:
        imp = max(1, min(5, int(d.get("importance", 3))))
    except (TypeError, ValueError):
        imp = 3
    raw_attrs = d.get("attrs")
    attrs = {str(k): str(v) for k, v in raw_attrs.items()
             if str(v).strip()} if isinstance(raw_attrs, dict) else {}
    raw_aliases = d.get("aliases")
    aliases = [str(a).strip() for a in raw_aliases
               if str(a).strip()] if isinstance(raw_aliases, list) else []
    return Entry(title=title, slug=slug, aliases=aliases, importance=imp,
                 attrs=attrs, body=str(d.get("body", "")).strip())


def _scenario_context(store: MemoryStore) -> str:
    """What the per-field AI assists see: the premise (and tone lives in it)."""
    return _split_premise_body(store.read("premise.md"))


@app.post("/api/scenarios")
def create_scenario(body: dict):
    """Create a world — a builder shell (empty premise is fine; the builder
    fills it) or a complete manual one with premise + introduction."""
    title = str(body.get("title", "")).strip() or "Untitled World"
    premise = str(body.get("premise", "")).strip()
    slug = lib.scenarios.create(
        title, premise,
        world=str(body.get("world", "")).strip(),
        description=str(body.get("description", "")).strip() or premise[:140],
        introduction=str(body.get("introduction", "")).strip())
    return {"slug": slug}


@app.get("/api/scenarios/{slug}/full")
def scenario_full(slug: str):
    store = _scen_store(slug)
    meta = json.loads((lib.scenarios.dir(slug) / "scenario.json")
                      .read_text(encoding="utf-8"))
    world = "\n".join(ln for ln in store.read("world-bible.md").splitlines()
                      if not ln.startswith("# ")).strip()
    files = _piece_files(store)
    return {
        "slug": slug,
        "title": meta.get("title", slug),
        "description": meta.get("description", ""),
        "premise": _split_premise_body(store.read("premise.md")),
        "introduction": store.opening_override(),
        "world": world,
        "pieces": {rel: [_entry_dict(e) for e in store.entries(rel)]
                   for rel in files},
    }


@app.put("/api/scenarios/{slug}/main")
def scenario_main(slug: str, body: dict):
    store = _scen_store(slug)
    premise = str(body.get("premise", "")).strip()
    intro = str(body.get("introduction", "")).strip()
    _write_premise_md(store, premise, intro)
    world = str(body.get("world", "")).strip()
    store.write("world-bible.md", "# World bible\n\n"
                + (world + "\n" if world else ""))
    lib.scenarios.update_meta(
        slug, title=str(body.get("title", "")).strip(),
        description=str(body.get("description", "")).strip())
    return {"ok": True}


@app.put("/api/scenarios/{slug}/pieces/{rel}")
def scenario_piece_put(slug: str, rel: str, body: dict):
    store = _scen_store(slug)
    if rel not in _piece_files(store):
        raise HTTPException(400, f"not a lore file of this world: {rel}")
    entry = _entry_from_dict(body.get("entry") or {})
    store.upsert_entry(rel, entry)
    old = str(body.get("old_slug", "")).strip()
    if old and old != entry.slug:
        store.remove_entry(rel, old)          # slug rename cleans the old one
    return {"ok": True, "slug": entry.slug}


@app.delete("/api/scenarios/{slug}/pieces/{rel}/{pslug}")
def scenario_piece_delete(slug: str, rel: str, pslug: str):
    store = _scen_store(slug)
    if rel not in _piece_files(store):
        raise HTTPException(400, f"not a lore file of this world: {rel}")
    if not store.remove_entry(rel, pslug):
        raise HTTPException(404, f"no such piece: {pslug}")
    return {"ok": True}


def _declare_custom_type(slug: str, name: str) -> str:
    """Declare (and seed) a custom lore type on a scenario. Returns the
    filename; raises HTTPException on bad names / missing scenario."""
    _guard_slug(slug)
    import re as _re
    base = str(name).strip().removesuffix(".md")
    if not _re.search(r"[A-Za-z0-9]", base):
        raise HTTPException(400, f"not a usable lore file name: {name!r}")
    from coderain.memory import _RESERVED_MD
    fname = templates.slugify(base) + ".md"
    if fname in _RESERVED_MD or fname in _BASE_PIECE_FILES:
        raise HTTPException(400, f"'{fname}' is a built-in file")
    scen_dir = lib.scenarios.dir(slug)
    meta_path = scen_dir / "scenario.json"
    if not meta_path.exists():
        raise HTTPException(404, f"no such scenario: {slug}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    declared = meta.setdefault("custom_files", [])
    if fname not in declared:
        declared.append(fname)
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    f = scen_dir / fname
    if not f.exists():
        label = fname.removesuffix(".md").replace("-", " ").title()
        f.write_text(f"# {label}\n\n{label} — custom lore registry.\n",
                     encoding="utf-8")
    return fname


@app.post("/api/scenarios/{slug}/types")
def scenario_add_type(slug: str, body: dict):
    """Declare a custom lore type on a scenario (scenario.json custom_files)."""
    return {"file": _declare_custom_type(slug, str(body.get("name", "")))}


@app.delete("/api/scenarios/{slug}/types/{fname}")
def scenario_delete_type(slug: str, fname: str):
    """Remove a CUSTOM lore type: the declaration AND the file (its pieces go
    with it — the UI confirms first). Built-ins are never deletable."""
    _guard_slug(slug)
    if fname in _BASE_PIECE_FILES or not fname.endswith(".md") \
            or "/" in fname or "\\" in fname:
        raise HTTPException(400, f"'{fname}' is not a removable lore type")
    scen_dir = lib.scenarios.dir(slug)
    meta_path = scen_dir / "scenario.json"
    if not meta_path.exists():
        raise HTTPException(404, f"no such scenario: {slug}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    declared = meta.get("custom_files") or []
    if fname not in declared:
        raise HTTPException(404, f"'{fname}' is not declared on this world")
    meta["custom_files"] = [f for f in declared if f != fname]
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    try:
        (scen_dir / fname).unlink()
    except FileNotFoundError:
        pass
    return {"ok": True}


@app.get("/api/scenarios/{slug}/pieces/{rel}/export")
def scenario_section_export(slug: str, rel: str):
    """Download one section of a world as its raw Markdown file."""
    store = _scen_store(slug)
    if rel not in _piece_files(store):
        raise HTTPException(400, f"not a lore file of this world: {rel}")
    path = lib.scenarios.dir(slug) / rel
    if not path.exists():
        raise HTTPException(404, f"{rel} has no content yet")
    return FileResponse(path, filename=f"{slug}-{rel}",
                        media_type="text/markdown")


# ---------- per-save world editing (same builder UI, live save files) --------
# A save owns its OWN copies of the world files (they diverge from the scenario
# as the story evolves). These mirror the scenario builder endpoints but read
# and write the loaded save, so the player can edit characters/locations/etc.
# mid-play. The engine reads the Markdown fresh each turn, so edits go live.
def _save_store(slug: str) -> MemoryStore:
    _guard_slug(slug)
    try:
        return lib.saves.store(slug)
    except FileNotFoundError:
        raise HTTPException(404, f"no such save: {slug}")


def _declare_type_in(base_dir: Path, meta_name: str, name: str) -> str:
    """Declare (+seed) a custom lore type by writing its file and adding it to
    the target's `custom_files` (scenario.json OR a save's meta.json)."""
    import re as _re
    base = str(name).strip().removesuffix(".md")
    if not _re.search(r"[A-Za-z0-9]", base):
        raise HTTPException(400, f"not a usable lore file name: {name!r}")
    from coderain.memory import _RESERVED_MD
    fname = templates.slugify(base) + ".md"
    if fname in _RESERVED_MD or fname in _BASE_PIECE_FILES:
        raise HTTPException(400, f"'{fname}' is a built-in file")
    meta_path = base_dir / meta_name
    if not meta_path.exists():
        raise HTTPException(404, "no such target")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    declared = meta.setdefault("custom_files", [])
    if fname not in declared:
        declared.append(fname)
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    f = base_dir / fname
    if not f.exists():
        label = fname.removesuffix(".md").replace("-", " ").title()
        f.write_text(f"# {label}\n\n{label} — custom lore registry.\n",
                     encoding="utf-8")
    return fname


def _delete_type_in(base_dir: Path, meta_name: str, fname: str) -> dict:
    if fname in _BASE_PIECE_FILES or not fname.endswith(".md") \
            or "/" in fname or "\\" in fname:
        raise HTTPException(400, f"'{fname}' is not a removable lore type")
    meta_path = base_dir / meta_name
    if not meta_path.exists():
        raise HTTPException(404, "no such target")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    declared = meta.get("custom_files") or []
    if fname not in declared:
        raise HTTPException(404, f"'{fname}' is not declared here")
    meta["custom_files"] = [f for f in declared if f != fname]
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    try:
        (base_dir / fname).unlink()
    except FileNotFoundError:
        pass
    return {"ok": True}


@app.get("/api/saves/{slug}/world/full")
def save_world_full(slug: str):
    store = _save_store(slug)
    meta = lib.saves.meta(slug)
    world = "\n".join(ln for ln in store.read("world-bible.md").splitlines()
                      if not ln.startswith("# ")).strip()
    files = _piece_files(store)
    return {
        "slug": slug,
        "title": meta.get("title", slug),
        "description": "",
        "premise": _split_premise_body(store.read("premise.md")),
        "introduction": store.opening_override(),
        "world": world,
        "pieces": {rel: [_entry_dict(e) for e in store.entries(rel)]
                   for rel in files},
    }


@app.get("/api/saves/{slug}/authors-note")
def get_authors_note(slug: str):
    store = _save_store(slug)
    an = store.world_state().get("authors_note")
    an = an if isinstance(an, dict) else {}
    depth = an.get("depth") if an.get("depth") in ("system", "tail") else "system"
    try:
        every = max(1, int(an.get("every", 1)))
    except (TypeError, ValueError):
        every = 1
    return {"content": store.custom_instructions(), "depth": depth, "every": every}


@app.put("/api/saves/{slug}/authors-note")
def put_authors_note(slug: str, body: dict):
    """ST-21: the per-save author's note — content + placement (depth/frequency)."""
    store = _save_store(slug)
    content = str(body.get("content", "") or "")
    depth = body.get("depth") if body.get("depth") in ("system", "tail") else "system"
    try:
        every = max(1, int(body.get("every", 1)))
    except (TypeError, ValueError):
        every = 1
    with _exclusive():                           # don't race a live turn's state write
        # custom_instructions() reads the body BELOW the first `---`; keep whatever
        # header sits above it (the template's, or the user's own) instead of nuking it.
        existing = store.read("custom-instructions.md")
        head = existing.split("---", 1)[0] if "---" in existing \
            else "# Custom instructions (this save)\n\n"
        store.write("custom-instructions.md", head + "---\n" + content)
        state = store.world_state()
        state["authors_note"] = {"depth": depth, "every": every}
        store.set_world_state(state)
    return {"ok": True}


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


@app.get("/api/saves/{slug}/aids")
def get_aids(slug: str):
    ws = _save_store(slug).world_state()
    return {"quick_actions": _clean_quick_actions(ws.get("quick_actions")),
            "regex_rules": _clean_regex_rules(ws.get("regex_rules"))}


@app.put("/api/saves/{slug}/aids")
def put_aids(slug: str, body: dict):
    """ST-30 per-save quick actions + ST-31 persistent output regex rules."""
    store = _save_store(slug)
    qa = _clean_quick_actions(body.get("quick_actions"))
    rules = _clean_regex_rules(body.get("regex_rules"))
    with _exclusive():                           # don't race a live turn's state write
        state = store.world_state()
        state["quick_actions"] = qa
        state["regex_rules"] = rules
        store.set_world_state(state)
    return {"ok": True}


@app.put("/api/saves/{slug}/world/main")
def save_world_main(slug: str, body: dict):
    store = _save_store(slug)
    premise = str(body.get("premise", "")).strip()
    world = str(body.get("world", "")).strip()
    title = str(body.get("title", "")).strip()
    with _exclusive():                           # don't race a live turn's state write
        # Preserve the opening unless the caller sends one: a live save's intro is
        # already in the transcript, and the builder hides that field for saves.
        intro = str(body.get("introduction", store.opening_override())).strip()
        _write_premise_md(store, premise, intro)
        store.write("world-bible.md", "# World bible\n\n"
                    + (world + "\n" if world else ""))
        if title:
            lib.saves.rename(slug, title)
    return {"ok": True}


@app.put("/api/saves/{slug}/world/pieces/{rel}")
def save_world_piece_put(slug: str, rel: str, body: dict):
    store = _save_store(slug)
    if rel not in _piece_files(store):
        raise HTTPException(400, f"not a lore file of this save: {rel}")
    entry = _entry_from_dict(body.get("entry") or {})
    old = str(body.get("old_slug", "")).strip()
    with _exclusive():                           # don't race a live turn's state write
        store.upsert_entry(rel, entry)
        if old and old != entry.slug:
            store.remove_entry(rel, old)
    return {"ok": True, "slug": entry.slug}


@app.delete("/api/saves/{slug}/world/pieces/{rel}/{pslug}")
def save_world_piece_delete(slug: str, rel: str, pslug: str):
    store = _save_store(slug)
    if rel not in _piece_files(store):
        raise HTTPException(400, f"not a lore file of this save: {rel}")
    with _exclusive():                           # don't race a live turn's state write
        if not store.remove_entry(rel, pslug):
            raise HTTPException(404, f"no such piece: {pslug}")
    return {"ok": True}


@app.post("/api/saves/{slug}/world/types")
def save_world_add_type(slug: str, body: dict):
    _save_store(slug)                          # 404 guard
    with _exclusive():                           # meta.json write vs. a live turn
        return {"file": _declare_type_in(lib.saves.dir(slug), "meta.json",
                                         str(body.get("name", "")))}


@app.delete("/api/saves/{slug}/world/types/{fname}")
def save_world_delete_type(slug: str, fname: str):
    _save_store(slug)
    with _exclusive():                           # meta.json write vs. a live turn
        return _delete_type_in(lib.saves.dir(slug), "meta.json", fname)


@app.get("/api/saves/{slug}/world/pieces/{rel}/export")
def save_world_section_export(slug: str, rel: str):
    store = _save_store(slug)
    if rel not in _piece_files(store):
        raise HTTPException(400, f"not a lore file of this save: {rel}")
    path = lib.saves.dir(slug) / rel
    if not path.exists():
        raise HTTPException(404, f"{rel} has no content yet")
    return FileResponse(path, filename=f"{slug}-{rel}",
                        media_type="text/markdown")


@app.post("/api/saves/{slug}/world/from-library")
def save_world_insert_character(slug: str, body: dict):
    char = characters.get(str(body.get("id", "")).strip())
    if char is None:
        raise HTTPException(404, "no such character")
    store = _save_store(slug)
    entry = entry_from_character(char)
    with _exclusive():                           # don't race a live turn's state write
        store.upsert_entry("characters.md", entry)
    return {"ok": True, "slug": entry.slug}


@app.post("/api/saves/{slug}/world/from-piece-library")
def save_world_insert_piece(slug: str, body: dict):
    rec = pieces_lib.get(str(body.get("id", "")).strip())
    if rec is None:
        raise HTTPException(404, "no such library piece")
    entry = pieces_lib.entry(rec["id"])
    rel = _kind_to_rel(rec.get("type", ""))
    store = _save_store(slug)
    with _exclusive():                           # don't race a live turn's state write
        if rel not in _piece_files(store):
            _declare_type_in(lib.saves.dir(slug), "meta.json", rel.removesuffix(".md"))
            store = _save_store(slug)
        store.upsert_entry(rel, entry)
    return {"ok": True, "rel": rel, "slug": entry.slug}


@app.get("/api/scenarios/{slug}/playable")
def scenario_playable(slug: str):
    """The world's playable characters (`playable: true` in characters.md) —
    what the new-story dialog offers as 'Play as'."""
    store = _scen_store(slug)
    out = [{"slug": e.slug, "title": e.title,
            "blurb": e.body.strip().splitlines()[0][:120]
            if e.body.strip() else ""}
           for e in store.entries("characters.md")
           if str(e.attrs.get("playable", "")).strip().lower()
           in ("true", "yes", "1", "on")]
    return {"playable": out}


@app.post("/api/assist")
def assist(body: dict):
    """Per-field AI assist for the builder: seed a section from a one-line
    idea, or improve existing content. Piece kinds return a full entry."""
    kind = str(body.get("kind", "")).strip().lower()
    mode = str(body.get("mode", "seed")).strip().lower()
    text = str(body.get("text", ""))
    improve = bool(body.get("improve", False))
    context = ""
    scen = str(body.get("scenario", "")).strip()
    if scen and lib.scenarios.exists(scen):
        context = _scenario_context(_scen_store(scen))
    elif scen and templates.slugify(scen) == scen and lib.saves.exists(scen):
        # The story editor (#edit/<save>) sends a SAVE slug here. That used to
        # miss every branch above and run the assist context-blind.
        context = _scenario_context(_save_store(scen))
    if not _gen_lock.acquire(blocking=False):
        raise HTTPException(409, "another generation is running")
    try:
        llm = LLM(_cfg.profile, _cfg.generation)
        result, err = assist_field(llm, kind, mode, text, context=context,
                                   improve=improve)
    except Exception as e:                          # noqa: BLE001
        raise HTTPException(502, _model_error_text(e))   # not a bare 500
    finally:
        _gen_lock.release()
    if err:
        raise HTTPException(502, err)
    if isinstance(result, Entry):
        return {"entry": _entry_dict(result)}
    return {"text": result}


@app.post("/api/scenarios/{slug}/complete")
def scenario_complete(slug: str, body: dict):
    """'Generate the rest with AI' (SSE): fill only what's missing, keep
    everything the user wrote."""
    _guard_slug(slug)                            # every sibling scenario endpoint guards
    def _n(key, default=5):
        try:
            return max(0, min(20, int(body.get(key, default))))
        except (TypeError, ValueError):
            return default
    spec = ScenarioSpec(
        type=str(body.get("type", "")).strip(),
        tone=str(body.get("tone", "")).strip(),
        premise=str(body.get("premise", "")).strip(),
        n_npcs=_n("n_npcs"), n_locations=_n("n_locations"),
        n_items=_n("n_items"),
        detail="fast" if body.get("detail") == "fast" else "rich",
        improve=bool(body.get("improve", False)))

    def gen():
        if not _gen_lock.acquire(blocking=False):
            yield _sse({"t": "error", "text": "another generation is running"})
            return
        try:
            q: queue.Queue = queue.Queue()
            result: dict = {}

            def worker():
                try:
                    llm = LLM(_cfg.profile, _cfg.generation)
                    result["warnings"] = complete_scenario(
                        lib, llm, slug, spec, on_stage=lambda s: q.put(s))
                except Exception as e:  # noqa: BLE001
                    result["error"] = str(e)
                q.put(None)

            threading.Thread(target=worker, daemon=True).start()
            while True:
                msg = q.get()
                if msg is None:
                    break
                yield _sse({"t": "stage", "text": msg})
            if "error" in result:
                yield _sse({"t": "error", "text": result["error"]})
            else:
                yield _sse({"t": "done", "slug": slug,
                            "events": result.get("warnings", [])})
        finally:
            _gen_lock.release()
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@app.delete("/api/scenarios/{slug}")
def delete_scenario(slug: str):
    _guard_slug(slug)
    # Under the turn lock: this rmtree's a directory that live MemoryStores hold
    # as scenario_dir (rule inheritance + lore types resolve through it), so
    # deleting mid-turn pulled the floor out from under a running generation.
    with _exclusive():
        if not lib.scenarios.delete(slug):
            raise HTTPException(404, f"no such scenario: {slug}")
        _engines.clear()          # drop cached engines bound to the dead world
    return {"ok": True}


@app.post("/api/scenarios/{slug}/from-library")
def scenario_insert_character(slug: str, body: dict):
    """Drop a saved library character into a world as a characters.md piece
    (playable sheets land with `playable: true`)."""
    char = characters.get(str(body.get("id", "")).strip())
    if char is None:
        raise HTTPException(404, "no such character")
    store = _scen_store(slug)
    entry = entry_from_character(char)
    store.upsert_entry("characters.md", entry)
    return {"ok": True, "slug": entry.slug}


@app.post("/api/characters/from-entry")
def character_save_entry(body: dict):
    """Save a scenario piece back into the character library."""
    entry = _entry_from_dict(body.get("entry") or {})
    return characters.save(character_from_entry(entry))


# ---------- generic piece library (locations/items/factions/…) ----------
def _kind_to_rel(kind: str) -> str:
    info = PIECE_KINDS.get(kind)
    return info[3] if info else templates.slugify(kind) + ".md"


@app.get("/api/library")
def list_library(type: str = ""):
    return {"pieces": pieces_lib.list(type), "types": pieces_lib.types()}


@app.post("/api/library")
def save_library_piece(body: dict):
    try:
        return pieces_lib.save(str(body.get("type", "")),
                               body.get("entry") or {},
                               pid=str(body.get("id", "")).strip())
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e))


@app.delete("/api/library/{pid}")
def delete_library_piece(pid: str):
    if not pieces_lib.delete(pid):
        raise HTTPException(404, "no such library piece")
    return {"ok": True}


@app.post("/api/scenarios/{slug}/from-piece-library")
def scenario_insert_piece(slug: str, body: dict):
    """Drop a library piece into a world — its type's registry file; a custom
    type the world doesn't have yet is declared on the fly."""
    rec = pieces_lib.get(str(body.get("id", "")).strip())
    if rec is None:
        raise HTTPException(404, "no such library piece")
    entry = pieces_lib.entry(rec["id"])
    rel = _kind_to_rel(rec.get("type", ""))
    store = _scen_store(slug)
    if rel not in _piece_files(store):
        _declare_custom_type(slug, rel.removesuffix(".md"))
        store = _scen_store(slug)          # re-read the declaration
    store.upsert_entry(rel, entry)
    return {"ok": True, "rel": rel, "slug": entry.slug}


# ---------- exports ----------
_EXPORT_DIR = Path(tempfile.gettempdir()) / "coderain-exports"


@app.get("/api/saves/{slug}/export")
def export_save(slug: str):
    _guard_slug(slug)
    _EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        path = lib.saves.export(slug, _EXPORT_DIR / f"save-{slug}.zip")
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    return FileResponse(path, filename=f"save-{slug}.zip",
                        media_type="application/zip")


# Upload ceilings. Without these a tiny archive can write gigabytes: a 204 KB
# zip expanding to 200 MB was reproducible before this guard.
_MAX_UPLOAD_BYTES = 64 * 1024 * 1024        # compressed, per upload
_MAX_UNPACKED_BYTES = 256 * 1024 * 1024     # total decompressed, per archive
_MAX_COMPRESS_RATIO = 200                   # decompressed / compressed


def _guard_zip_bomb(packed_size: int, infos) -> None:
    """Reject an archive whose declared contents dwarf its compressed size."""
    unpacked = sum(max(0, getattr(i, "file_size", 0)) for i in infos)
    if unpacked > _MAX_UNPACKED_BYTES or unpacked > packed_size * _MAX_COMPRESS_RATIO:
        raise HTTPException(413, "archive expands too much (possible zip bomb)")


def _stash_upload(file: UploadFile) -> Path:
    """Persist a multipart upload to a temp .zip so the library import_ helpers
    (which take a path) can read it. The file keeps its original name inside a
    unique dir so the import's derived slug reads well (the 'save-'/'world-'
    export prefix is stripped). Caller removes the dir's parent.

    Streams in chunks with a hard ceiling, then refuses zip bombs, so an import
    can never fill the disk."""
    name = (file.filename or "").strip()
    if not name.lower().endswith(".zip"):
        raise HTTPException(400, "expected a .zip export")
    stem = Path(name).stem
    for pfx in ("save-", "world-", "user-"):
        if stem.startswith(pfx):
            stem = stem[len(pfx):]
    stem = "".join(c for c in stem if c.isalnum() or c in "-_ ") or "import"
    holder = _EXPORT_DIR / f"in-{uuid.uuid4().hex}"
    holder.mkdir(parents=True, exist_ok=True)
    dest = holder / f"{stem}.zip"
    try:
        total = 0
        with dest.open("wb") as out:
            while True:
                chunk = file.file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_UPLOAD_BYTES:
                    raise HTTPException(413, "upload too large (max 64 MB)")
                out.write(chunk)
        try:
            with zipfile.ZipFile(dest) as zf:
                _guard_zip_bomb(total, zf.infolist())
        except zipfile.BadZipFile:
            raise HTTPException(400, "not a valid .zip export")
    except BaseException:
        shutil.rmtree(holder, ignore_errors=True)   # caller never sees the path
        raise
    return dest


@app.post("/api/saves-import")
def import_save(file: UploadFile = File(...)):
    path = _stash_upload(file)
    try:
        slug = lib.saves.import_(path)
    except (ValueError, zipfile.BadZipFile) as e:
        raise HTTPException(400, str(e))
    finally:
        shutil.rmtree(path.parent, ignore_errors=True)
    return {"ok": True, "slug": slug}


@app.post("/api/cards-import")
def import_card(file: UploadFile = File(...)):
    """Import a SillyTavern/Tavern character card (PNG/JSON/charx) as a new World
    (ST-01): scenario→premise, first_mes→introduction, the character→a piece (+
    the reusable Pieces library), embedded lorebook→lore pieces."""
    from coderain import cards as cards_mod
    _MAX_UPLOAD = 32 * 1024 * 1024                        # 32 MB compressed ceiling
    raw = file.file.read(_MAX_UPLOAD + 1)
    if len(raw) > _MAX_UPLOAD:
        raise HTTPException(413, "card file too large (max 32 MB)")
    # .charx is a zip — the size cap above is compressed only, so a small file
    # could still expand to hundreds of MB. Check the declared unpacked size too.
    if zipfile.is_zipfile(io.BytesIO(raw)):
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            _guard_zip_bomb(len(raw), zf.infolist())
    try:
        card = cards_mod.parse_card(raw, file.filename or "")
    except ValueError as e:
        raise HTTPException(400, str(e))

    name = card["name"]
    sub = lambda t: cards_mod.substitute_macros(t, name)     # noqa: E731
    premise = sub(card["scenario"]) or sub(card["description"]) \
        or f"A story featuring {name}."
    intro = sub(card["first_mes"])
    desc_short = sub(card["description"])[:140]
    slug = lib.scenarios.create(name, premise, description=desc_short,
                                introduction=intro)
    store = _scen_store(slug)

    # The card's character → a characters.md piece (NPC).
    body = sub(card["description"])
    if card["personality"]:
        body += f"\n\n**Personality:** {sub(card['personality'])}"
    if card["mes_example"]:
        body += f"\n\n**Example dialogue:**\n{sub(card['mes_example'])}"
    store.upsert_entry("characters.md", Entry(
        title=name, slug=templates.slugify(name), aliases=[], importance=4,
        attrs={}, body=body.strip()))

    # Embedded lorebook → pieces in a declared custom 'lore' file.
    if card["lore"]:
        _declare_type_in(lib.scenarios.dir(slug), "scenario.json", "lore")
        store = _scen_store(slug)
        for e in card["lore"]:
            # Resolve {{char}}/{{user}} at import like every other card field, so
            # only intentional ST-20 macros survive to assemble time (no raw
            # {{char}} leak, and {{user}} matches the other fields).
            title = sub(e["title"])
            keys = [sub(k) for k in e["keys"]]
            store.upsert_entry("lore.md", Entry(
                title=title, slug=templates.slugify(title),
                aliases=keys, importance=3,
                attrs={"triggers": ", ".join(keys)} if keys else {},
                body=sub(e["content"])))

    # Also drop the character into the reusable Pieces library.
    try:
        characters.save({"name": name, "kind": "npc",
                         "description": sub(card["description"])})
    except Exception:  # noqa: BLE001 — library add is best-effort
        pass
    return {"ok": True, "slug": slug,
            "counts": {"lore": len(card["lore"]),
                       "greetings": len(card["alternate_greetings"])}}


@app.post("/api/scenarios-import")
def import_scenario(file: UploadFile = File(...)):
    path = _stash_upload(file)
    try:
        slug = lib.scenarios.import_(path)
    except (ValueError, zipfile.BadZipFile) as e:
        raise HTTPException(400, str(e))
    finally:
        shutil.rmtree(path.parent, ignore_errors=True)
    return {"ok": True, "slug": slug}


@app.post("/api/defaults-import")
def import_defaults(file: UploadFile = File(...)):
    """Restore a user-defaults.zip into the instructions dir (overwrites the
    files it contains; leaves others alone). Path-traversal guarded."""
    path = _stash_upload(file)
    try:
        # Under the turn lock: this rewrites instructions/*.md, which the engine
        # re-reads every turn — an import landing mid-generation would hand it a
        # torn rule file.
        with _exclusive(), zipfile.ZipFile(path) as z:
            for n in z.namelist():
                if not _safe_zip_member(lib.instructions_dir, n):  # traversal+absolute
                    continue
                target = lib.instructions_dir / n
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(n) as srcf, open(target, "wb") as outf:
                    shutil.copyfileobj(srcf, outf)
    except zipfile.BadZipFile as e:
        raise HTTPException(400, str(e))
    finally:
        shutil.rmtree(path.parent, ignore_errors=True)
    lib.outdated_rules = templates.seed_instructions(lib.instructions_dir)
    return {"ok": True}


@app.get("/api/scenarios/{slug}/export")
def export_scenario(slug: str):
    _guard_slug(slug)
    _EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        path = lib.scenarios.export(slug, _EXPORT_DIR / f"world-{slug}.zip")
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    return FileResponse(path, filename=f"world-{slug}.zip",
                        media_type="application/zip")


# ---------- user defaults (Library section) ----------
def _default_kind(name: str) -> str:
    return "rule" if name in templates.RULE_FILES else "skeleton"


def _defaultable(name: str) -> None:
    if name not in list(templates.RULE_FILES) + templates.USER_DEFAULTABLE:
        raise HTTPException(404, f"not a user-defaultable file: {name}")


@app.get("/api/defaults")
def list_defaults():
    out = []
    for name in list(templates.RULE_FILES) + templates.USER_DEFAULTABLE:
        kind = _default_kind(name)
        if kind == "rule":
            p = lib.instructions_dir / name
            customized = p.exists() and \
                p.read_text(encoding="utf-8") != templates.default_rule(name)
        else:
            customized = (lib.instructions_dir / "defaults" / name).exists()
        out.append({"name": name, "kind": kind, "customized": customized})
    return {"defaults": out}


@app.get("/api/defaults/{name}")
def get_default(name: str):
    _defaultable(name)
    if _default_kind(name) == "rule":
        p = lib.instructions_dir / name
        text = p.read_text(encoding="utf-8") if p.exists() \
            else templates.default_rule(name)
    else:
        text = templates.user_default(name, lib.instructions_dir)
    return {"name": name, "text": text}


@app.put("/api/defaults/{name}")
def put_default(name: str, body: dict):
    _defaultable(name)
    text = str(body.get("text", ""))
    # Under the turn lock: the engine re-reads the rule files EVERY turn, so a
    # save landing mid-generation could hand it a half-written rule file.
    with _exclusive():
        if _default_kind(name) == "rule":
            (lib.instructions_dir / name).write_text(text, encoding="utf-8")
            lib.outdated_rules = templates.seed_instructions(lib.instructions_dir)
        else:
            d = lib.instructions_dir / "defaults"
            d.mkdir(parents=True, exist_ok=True)
            (d / name).write_text(text, encoding="utf-8")
    return {"ok": True}


@app.post("/api/defaults/{name}/revert")
def revert_default(name: str):
    _defaultable(name)
    with _exclusive():                      # same live-rule race as put_default
        if _default_kind(name) == "rule":
            (lib.instructions_dir / name).write_text(
                templates.default_rule(name), encoding="utf-8")
            lib.outdated_rules = templates.seed_instructions(lib.instructions_dir)
        else:
            try:
                (lib.instructions_dir / "defaults" / name).unlink()
            except FileNotFoundError:
                pass
    return get_default(name)


@app.get("/api/defaults-export")
def export_defaults():
    import zipfile
    _EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    dest = _EXPORT_DIR / "user-defaults.zip"
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(lib.instructions_dir.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(lib.instructions_dir).as_posix())
    return FileResponse(dest, filename="user-defaults.zip",
                        media_type="application/zip")


# ---------- characters ----------
@app.get("/api/characters")
def list_characters():
    return {"characters": characters.list(), "stats": STAT_NAMES}


@app.post("/api/characters")
def save_character(body: dict):
    return characters.save(body if isinstance(body, dict) else {})


@app.delete("/api/characters/{cid}")
def delete_character(cid: str):
    if not characters.delete(cid):
        raise HTTPException(404, "no such character")
    return {"ok": True}


# ---------- models + settings ----------
# ---------- raw memory / rule files for a save (repair hatch) ----------
@app.get("/api/saves/{slug}/files")
def list_save_files(slug: str):
    """Every file a player may need to inspect or repair, with the layer each one
    currently resolves from. Without this a bad fold — a wrong scene summary, a
    false "fact" — was permanent: the engine re-reads these every turn and the
    builder only reaches the world pieces."""
    store = _save_store(slug)
    from coderain.memory import EDITABLE_FILES, RULE_FILES
    out = []
    for rel in EDITABLE_FILES:
        out.append({
            "rel": rel,
            "is_rule": rel in RULE_FILES,
            "layer": store.layer_of(rel),
            "exists": store.path(rel).exists(),
            "bytes": store.path(rel).stat().st_size
            if store.path(rel).exists() else 0,
        })
    return {"files": out}


@app.get("/api/saves/{slug}/files/{rel:path}")
def read_save_file(slug: str, rel: str):
    store = _save_store(slug)
    from coderain.memory import EDITABLE_FILES, RULE_FILES
    if rel not in EDITABLE_FILES:
        raise HTTPException(404, "not an editable file")
    return {"rel": rel, "text": store.read(rel), "layer": store.layer_of(rel),
            "is_rule": rel in RULE_FILES}


@app.put("/api/saves/{slug}/files/{rel:path}")
def write_save_file(slug: str, rel: str, body: dict):
    store = _save_store(slug)
    from coderain.memory import EDITABLE_FILES
    if rel not in EDITABLE_FILES:
        raise HTTPException(404, "not an editable file")
    text = str(body.get("text", ""))
    if rel.endswith(".json"):            # never persist story-breaking JSON
        try:
            json.loads(text)
        except json.JSONDecodeError as e:
            raise HTTPException(400, f"not valid JSON: {e}")
    with _exclusive():                   # the engine re-reads these every turn
        store.write(rel, text)
    return {"ok": True, "layer": store.layer_of(rel)}


@app.post("/api/saves/{slug}/rules/{rel}/override")
def make_rule_override(slug: str, rel: str):
    """Fork a save-local copy of a rule so edits affect ONLY this story. Without
    this, editing the rules in Settings changed them globally for every story at
    once — tuning one story's prose silently rewrote them all."""
    store = _save_store(slug)
    from coderain.memory import RULE_FILES
    if rel not in RULE_FILES:
        raise HTTPException(404, "not a rule file")
    with _exclusive():
        made = store.make_override(rel)
    if not made:
        raise HTTPException(400, "this story already has its own copy")
    return {"ok": True, "layer": store.layer_of(rel)}


@app.delete("/api/saves/{slug}/rules/{rel}/override")
def drop_rule_override(slug: str, rel: str):
    """Revert to the inherited (scenario/global) rule."""
    store = _save_store(slug)
    from coderain.memory import RULE_FILES
    if rel not in RULE_FILES:
        raise HTTPException(404, "not a rule file")
    with _exclusive():
        dropped = store.remove_override(rel)
    if not dropped:
        raise HTTPException(400, "this story has no copy of its own")
    return {"ok": True, "layer": store.layer_of(rel)}


@app.get("/api/ready")
def ready():
    """Is there a model this install can actually talk to?

    The app used to boot straight into the library with no check at all, so a
    new user with no Ollama and no API key clicked New story -> Begin and got a
    blank page with an unreadable error. Nothing told them a model was needed.
    This is the gate the first-run chooser hangs off.

    Cheap and honest: for local we ask Ollama what it has installed (a model
    must actually be pulled, not just the daemon running); for hosted we check a
    key and a model are configured. No tokens are spent.
    """
    mode = "hosted" if _cfg.raw.get("active_profile") == "hosted" else "local"
    if mode == "hosted":
        prof = (_cfg.raw.get("profiles") or {}).get("hosted") or {}
        has_key = bool(read_env().get(HOSTED_KEY_ENV, "").strip())
        model = str(prof.get("model", "")).strip()
        base = str(prof.get("base_url", "")).strip()
        if not has_key:
            return {"ok": False, "mode": mode, "reason": "no_key",
                    "detail": "No API key saved yet."}
        if not model or not base:
            return {"ok": False, "mode": mode, "reason": "no_model",
                    "detail": "No hosted model chosen yet."}
        return {"ok": True, "mode": mode, "model": model}

    try:
        r = httpx.get(OLLAMA_TAGS, timeout=3)
        r.raise_for_status()
        names = [m.get("name", "") for m in r.json().get("models", [])]
    except Exception:                                   # noqa: BLE001
        return {"ok": False, "mode": mode, "reason": "no_ollama",
                "detail": "Ollama isn't running (or isn't installed)."}
    if not names:
        return {"ok": False, "mode": mode, "reason": "no_models",
                "detail": "Ollama is running but has no models pulled yet."}
    want = str((_cfg.raw.get("profiles") or {}).get("local", {})
               .get("model", "")).strip()
    # Ollama reports "qwen3:4b"; a config may say "qwen3" — match on the stem.
    if want and not any(n == want or n.split(":")[0] == want.split(":")[0]
                        for n in names):
        return {"ok": False, "mode": mode, "reason": "model_missing",
                "detail": f"The selected model ({want}) isn't installed.",
                "installed": names}
    return {"ok": True, "mode": mode, "model": want or names[0],
            "installed": names}


@app.get("/api/models/local")
def local_models():
    """Installed Ollama models for the local dropdowns (live from the daemon;
    static suggestions as a fallback when it's not running)."""
    installed: list[dict] = []
    error = ""
    try:
        r = httpx.get(OLLAMA_TAGS, timeout=3)
        r.raise_for_status()
        for m in r.json().get("models", []):
            size_gb = round((m.get("size", 0) or 0) / 1e9, 1)
            installed.append({"name": m.get("name", ""),
                              "size": f"{size_gb} GB"})
    except Exception as e:  # noqa: BLE001
        error = f"Ollama not reachable ({e.__class__.__name__})"
    return {"installed": installed, "error": error,
            "howto": models_mod.LOCAL_HOWTO,
            "suggestions": [{"name": n, "kind": kind, "size": size,
                             "note": note}
                            for n, kind, size, note
                            in models_mod.LOCAL_SUGGESTIONS]}


@app.get("/api/models/hosted")
def hosted_models():
    return {"presets": models_mod.HOSTED_PRESETS,
            "hints": models_mod.context_hint_lines(),
            "platforms": models_mod.platform_comparison_lines(),
            "howto": models_mod.HOSTED_HOWTO,
            "recommended_min": models_mod.RECOMMENDED_MIN_CONTEXT}


@app.get("/api/settings")
def get_settings():
    raw = _cfg.raw
    trinity = raw.get("trinity") or {}
    local = raw.get("profiles", {}).get("local", {})
    hosted = raw.get("profiles", {}).get("hosted", {})
    return {
        "mode": "hosted" if raw.get("active_profile") == "hosted" else "local",
        "local": {
            "director": (trinity.get("director") or {}).get("model")
            or local.get("model", ""),
            # No base-model fallback: the lore-keeper is OPT-IN, so an unset
            # stage must read back as "" (the dropdown's "(none)") — otherwise
            # the UI would imply a continuity pass that isn't actually running.
            "lorekeeper": (trinity.get("lorekeeper") or {}).get("model", ""),
            "writer": (trinity.get("writer") or {}).get("model")
            or local.get("model", ""),
            "context_tokens": local.get("context_tokens", 16384),
        },
        "hosted": {
            "model": hosted.get("model", ""),
            "base_url": hosted.get("base_url", ""),
            "context_tokens": hosted.get("context_tokens", 131072),
            "key_set": bool(read_env().get(HOSTED_KEY_ENV, "")),
        },
        "generation": {
            "response_length":
                _cfg.generation.get("response_length", "medium"),
            "trinity_brain": bool(_cfg.generation.get("trinity_brain", True)),
            "use_memory_tool": bool(_cfg.generation.get("use_memory_tool", False)),
            "ai_acts_as_player":
                bool(_cfg.generation.get("ai_acts_as_player", False)),
            "start_reply_with": _cfg.generation.get("start_reply_with", ""),
            "stop": _cfg.generation.get("stop", []),
            "temperature": _cfg.generation.get("temperature", 0.9),
            "top_p": _cfg.generation.get("top_p", 0.95),
            "max_tokens": _cfg.generation.get("max_tokens", 2500),
            "frequency_penalty": _cfg.generation.get("frequency_penalty"),
            "presence_penalty": _cfg.generation.get("presence_penalty"),
            "repetition_penalty": _cfg.generation.get("repetition_penalty"),
            "seed": _cfg.generation.get("seed"),
        },
        "quick_actions": _clean_quick_actions(_cfg.raw.get("quick_actions")),
        # Previously web-invisible: these existed in config.yaml and the legacy
        # Tk app but had no endpoint, so semantic recall was permanently OFF and
        # the memory depth/budget could not be tuned from the main UI at all.
        "memory": {
            "short_term_turns": _cfg.memory.get("short_term_turns", 12),
            "medium_fold_after": _cfg.memory.get("medium_fold_after", 12),
            "medium_fold_size": _cfg.memory.get("medium_fold_size", 5),
            "long_fold_after": _cfg.memory.get("long_fold_after", 8),
            "long_fold_size": _cfg.memory.get("long_fold_size", 4),
            "context_budget_tokens":
                _cfg.memory.get("context_budget_tokens", "auto"),
        },
        "retrieval": {
            "enabled": bool(_cfg.retrieval.get("enabled", False)),
            "embed_model": _cfg.retrieval.get("embed_model", "nomic-embed-text"),
            "top_k": _cfg.retrieval.get("top_k", 4),
            "half_life_turns": _cfg.retrieval.get("half_life_turns", 40),
            "min_similarity": _cfg.retrieval.get("min_similarity", 0.25),
            "available": features.enabled("vector"),
        },
    }


@app.put("/api/settings")
def put_settings(body: dict):
    # Build against a COPY: a later validation failure (e.g. hosted mode with no
    # model) used to abort with 400 after already mutating the live config, so
    # the running process reported a temperature/sampler that was never written
    # to disk and silently reverted on restart.
    raw = copy.deepcopy(_cfg.raw)
    mode = body.get("mode") if body.get("mode") in ("local", "hosted") \
        else "local"
    if "quick_actions" in body:                 # ST-30 global quick actions
        raw["quick_actions"] = _clean_quick_actions(body.get("quick_actions"))
    gen = body.get("generation") or {}
    raw.setdefault("generation", {})
    if gen.get("response_length") in ("short", "medium", "long"):
        raw["generation"]["response_length"] = gen["response_length"]
    if "trinity_brain" in gen:
        raw["generation"]["trinity_brain"] = bool(gen["trinity_brain"])
    if "use_memory_tool" in gen:
        raw["generation"]["use_memory_tool"] = bool(gen["use_memory_tool"])
    if "ai_acts_as_player" in gen:
        raw["generation"]["ai_acts_as_player"] = bool(gen["ai_acts_as_player"])

    # Memory depth / budget — was config-file-only, so a web user could not trade
    # history depth against context budget.
    mem = body.get("memory") or {}
    if mem:
        raw.setdefault("memory", {})
        for key, lo, hi in (("short_term_turns", 2, 200),
                            ("medium_fold_after", 2, 200),
                            ("medium_fold_size", 1, 100),
                            ("long_fold_after", 1, 200),
                            ("long_fold_size", 1, 100)):
            if key in mem and mem[key] not in (None, ""):
                try:
                    raw["memory"][key] = max(lo, min(hi, int(mem[key])))
                except (TypeError, ValueError):
                    pass
        if "context_budget_tokens" in mem:
            v = mem["context_budget_tokens"]
            if isinstance(v, str) and v.strip().lower() == "auto":
                raw["memory"]["context_budget_tokens"] = "auto"
            else:
                try:
                    raw["memory"]["context_budget_tokens"] = max(1000, int(v))
                except (TypeError, ValueError):
                    pass

    # Semantic recall (vector retrieval) — a headline memory feature that was
    # permanently off for anyone who never hand-edited config.yaml.
    ret = body.get("retrieval") or {}
    if ret:
        raw.setdefault("retrieval", {})
        if "enabled" in ret:
            raw["retrieval"]["enabled"] = bool(ret["enabled"])
        if str(ret.get("embed_model", "")).strip():
            raw["retrieval"]["embed_model"] = str(ret["embed_model"]).strip()
        for key, lo, hi, cast in (("top_k", 1, 20, int),
                                  ("half_life_turns", 1, 500, int),
                                  ("min_similarity", 0.0, 1.0, float)):
            if key in ret and ret[key] not in (None, ""):
                try:
                    raw["retrieval"][key] = max(lo, min(hi, cast(ret[key])))
                except (TypeError, ValueError):
                    pass
    # ST-22 persistent reply prefix (literal; every generated turn starts with it)
    if "start_reply_with" in gen:
        raw["generation"]["start_reply_with"] = str(gen["start_reply_with"] or "")[:300]
    # ST-24 custom stop sequences (accepts a list or newline-separated string)
    if "stop" in gen:
        stop = gen["stop"]
        if isinstance(stop, str):
            stop = stop.split("\n")
        raw["generation"]["stop"] = ([s.strip() for s in stop
                                      if isinstance(s, str) and s.strip()][:8]
                                     if isinstance(stop, list) else [])
    # ST-26 core samplers (always set; clamped to sane ranges)
    for key, lo, hi, cast in (("temperature", 0.0, 2.0, float),
                              ("top_p", 0.0, 1.0, float),
                              ("max_tokens", 1, 100000, int)):
        if key in gen and gen[key] not in (None, ""):
            try:
                raw["generation"][key] = max(lo, min(hi, cast(gen[key])))
            except (TypeError, ValueError):
                pass
    # ST-26 opt-in samplers: set within range, or clear (None/"") -> provider default
    for key, lo, hi, cast in (("frequency_penalty", -2.0, 2.0, float),
                              ("presence_penalty", -2.0, 2.0, float),
                              ("repetition_penalty", 0.0, 2.0, float),
                              ("seed", 0, 2**31 - 1, int)):
        if key in gen:
            if gen[key] in (None, ""):
                raw["generation"].pop(key, None)
            else:
                try:
                    raw["generation"][key] = max(lo, min(hi, cast(gen[key])))
                except (TypeError, ValueError):
                    pass

    if mode == "local":
        loc = body.get("local") or {}
        profile = raw.setdefault("profiles", {}).setdefault("local", {})
        profile.setdefault("base_url", "http://localhost:11434/v1")
        profile.setdefault("api_key_env", "OLLAMA_API_KEY")
        try:
            profile["context_tokens"] = max(
                models_mod.MIN_CONTEXT_TOKENS,
                int(loc.get("context_tokens",
                            profile.get("context_tokens", 16384))))
        except (TypeError, ValueError):
            pass
        director = str(loc.get("director", "")).strip()
        writer = str(loc.get("writer", "")).strip()
        keeper = str(loc.get("lorekeeper", "")).strip()
        if director:
            profile["model"] = director
        trinity = {}
        for stage, model in (("director", director), ("lorekeeper", keeper),
                             ("writer", writer)):
            if model:
                trinity[stage] = {"profile": "local", "model": model}
        # Choosing a lore-keeper model is what TURNS THE PASS ON — "(none)"
        # leaves the stage absent, so trinity.lore_llm_pass stays False.
        if keeper:
            trinity["lorekeeper"]["llm_pass"] = True
        if trinity:
            raw["trinity"] = trinity
        else:
            raw.pop("trinity", None)
        raw["active_profile"] = "local"
    else:
        ho = body.get("hosted") or {}
        model = str(ho.get("model", "")).strip()
        base_url = str(ho.get("base_url", "")).strip()
        if not model or not base_url:
            raise HTTPException(400, "hosted mode needs a model and base URL")
        try:
            ctx = max(models_mod.MIN_CONTEXT_TOKENS,
                      int(ho.get("context_tokens", 131072)))
        except (TypeError, ValueError):
            ctx = 131072
        raw.setdefault("profiles", {})["hosted"] = {
            "base_url": base_url, "model": model,
            "api_key_env": HOSTED_KEY_ENV, "context_tokens": ctx,
        }
        key = str(ho.get("api_key", "")).strip()
        if key:
            write_env({HOSTED_KEY_ENV: key})
        # One big dual-mode model serves every stage — drop the local pins.
        raw.pop("trinity", None)
        raw["active_profile"] = "hosted"

    save_yaml(raw)
    _reload_config()
    return get_settings()


# ---------- ST-25 connection profiles (named connection bundles) ----------
def _profiles_saved() -> dict:
    p = _cfg.raw.get("connection_profiles")
    return p if isinstance(p, dict) else {}


@app.get("/api/profiles")
def list_profiles():
    saved = _profiles_saved()
    active = _cfg.raw.get("active_profile_name", "")
    return {"profiles": sorted(saved.keys()),
            "active": active if active in saved else ""}   # never a dangling pointer


@app.post("/api/profiles")
def save_profile(body: dict):
    """Snapshot the CURRENT active connection under a name."""
    name = str(body.get("name", "")).strip()
    if not name or "/" in name or "\\" in name or len(name) > 60:
        raise HTTPException(400, "profile name must be 1-60 chars with no slashes")
    raw = _cfg.raw
    kind = raw.get("active_profile", "local")
    src = (raw.get("profiles") or {}).get(kind, {})
    # Never snapshot an empty connection: a profile without base_url/model would
    # persist a config that crashes load_config on the next boot.
    if not (src.get("base_url") and src.get("model")):
        raise HTTPException(400, "the active connection has no model/URL to save yet")
    saved = raw.setdefault("connection_profiles", {})
    saved[name] = {"kind": kind, **{k: src[k] for k in
                   ("base_url", "model", "api_key_env", "context_tokens")
                   if k in src}}
    raw["active_profile_name"] = name
    save_yaml(raw)
    _reload_config()
    return list_profiles()


@app.post("/api/profiles/activate")
def activate_profile(body: dict):
    name = str(body.get("name", "")).strip()
    saved = _profiles_saved().get(name)
    if not isinstance(saved, dict):
        raise HTTPException(404, f"no such profile: {name}")
    raw = _cfg.raw
    kind = saved.get("kind", "local")
    raw.setdefault("profiles", {})[kind] = {k: v for k, v in saved.items()
                                            if k != "kind"}
    raw["active_profile"] = kind
    raw["active_profile_name"] = name
    save_yaml(raw)
    _reload_config()
    return get_settings()


@app.delete("/api/profiles/{name}")
def delete_profile(name: str):
    raw = _cfg.raw
    if isinstance(raw.get("connection_profiles"), dict):
        raw["connection_profiles"].pop(name, None)
        if raw.get("active_profile_name") == name:
            raw["active_profile_name"] = ""
        save_yaml(raw)
        _reload_config()
    return list_profiles()


# ---------- static SPA ----------
@app.get("/")
def index():
    return FileResponse(ASSETS / "webapp" / "index.html")


app.mount("/", StaticFiles(directory=ASSETS / "webapp"), name="webapp")


if __name__ == "__main__":
    import os
    _port = int((os.environ.get("CODERAIN_PORT") or "8377").strip() or "8377")
    uvicorn.run(app, host="127.0.0.1", port=_port)
