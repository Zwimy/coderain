"""Coderain web server (Phase 6) — the MAIN app UI.

FastAPI + a static SPA (webapp/). One process, local-first:

    .venv\\Scripts\\python.exe server.py          # http://127.0.0.1:8377

The Tkinter app (gui.py) remains as the retro easter egg; everything new lands
here first. Endpoints are thin wrappers over the same Engine/Library the CLI
and GUI use — no engine logic lives in this file.
"""
from __future__ import annotations

import json
import queue
import shutil
import tempfile
import threading
import uuid
import zipfile
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from coderain import models as models_mod
from coderain import features
from coderain.config import (load_config, read_env, save_yaml,
                                write_env)
from coderain import templates
from coderain.engine import Engine
from coderain.generator import (PIECE_KINDS, ScenarioSpec,
                                   _split_premise_body, _write_premise_md,
                                   assist_field, complete_scenario,
                                   generate_scenario)
from coderain.llm import LLM
from coderain.memory import Entry, Library, MemoryStore
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
characters = CharacterProfiles(ROOT)
pieces_lib = PieceLibrary(ROOT)

_cfg = load_config()
_engines: dict[str, Engine] = {}
# The local GPU (and most single-key plans) can't run turns in parallel —
# one generation at a time, app-wide.
_gen_lock = threading.Lock()


def _engine(slug: str) -> Engine:
    if slug not in _engines:
        try:
            store = lib.saves.store(slug)
        except FileNotFoundError:
            raise HTTPException(404, f"no such save: {slug}")
        _engines[slug] = Engine(_cfg, store)
    return _engines[slug]


def _reload_config() -> None:
    global _cfg
    _cfg = load_config()
    _engines.clear()          # engines rebuild lazily against the new config


def _sse(obj: dict) -> str:
    return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"


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
            yield _sse({"t": "error", "text": "another turn is running"})
            return
        try:
            notes: list[str] = []
            it = run(eng, notes)
            for piece in it:
                while notes:
                    yield _sse({"t": "stage", "text": notes.pop(0)})
                if piece:
                    yield _sse({"t": "chunk", "text": piece})
            while notes:
                yield _sse({"t": "stage", "text": notes.pop(0)})
            events = eng.maybe_fold()
            yield _sse({"t": "done", "events": events,
                        "sheet": _sheet_lines(eng),
                        "clock": eng.store.clock_str(),
                        "turns": len(eng.store.turns())})
        except Exception as e:  # noqa: BLE001 — surface, never hang the stream
            yield _sse({"t": "error", "text": str(e)})
        finally:
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
    return {"slug": slug}


@app.get("/api/saves/{slug}")
def get_save(slug: str):
    return _save_payload(slug)


@app.delete("/api/saves/{slug}")
def delete_save(slug: str):
    _engines.pop(slug, None)
    if not lib.saves.delete(slug):
        raise HTTPException(404, f"no such save: {slug}")
    return {"ok": True}


@app.post("/api/saves/{slug}/branch")
def branch_save(slug: str, body: dict):
    try:
        n = int(body.get("turn", 0))
    except (TypeError, ValueError):
        raise HTTPException(400, "turn must be a number")
    total = len(_engine(slug).store.turns())
    if not 1 <= n <= total:
        raise HTTPException(400, f"turn must be 1..{total}")
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
    if not eng.store.update_turn(i, str(body.get("text", ""))):
        raise HTTPException(400, f"no turn at index {i}")
    eng._swipes = None
    return {"ok": True}


@app.post("/api/saves/{slug}/impersonate")
def impersonate(slug: str):
    """Draft the player's next action (ST-04). Returns text; stores nothing."""
    eng = _engine(slug)
    with _gen_lock:
        return {"text": eng.impersonate()}


@app.post("/api/saves/{slug}/swipe")
def swipe_browse(slug: str, body: dict):
    """Browse cached narrator alternates without generating (ST-02)."""
    eng = _engine(slug)
    direction = 1 if int(body.get("dir", 1)) >= 0 else -1
    out = eng.swipe_browse(direction)
    if out is None:
        raise HTTPException(400, "nothing to swipe")
    return out


@app.post("/api/saves/{slug}/swipe-gen")
def swipe_gen(slug: str):
    """Generate a NEW narrator alternate and select it (ST-02)."""
    return _stream_generation(
        slug, lambda eng, notes: eng.swipe_generate(on_stage=notes.append))


@app.post("/api/saves/{slug}/undo")
def undo(slug: str):
    eng = _engine(slug)
    with _gen_lock:
        ok = eng.undo_last()
    eng._swipes = None
    return {"ok": ok, "turns": len(eng.store.turns()),
            "sheet": _sheet_lines(eng)}


@app.post("/api/saves/{slug}/retry")
def retry(slug: str):
    eng = _engine(slug)
    store = eng.store
    turns = store.turns()
    if turns and turns[-1]["role"] == "narrator" and len(turns) >= 2:
        last_player = turns[-2]["text"]
        store.drop_last_turns(2)
    elif turns and turns[-1]["role"] == "player":
        last_player = turns[-1]["text"]
        store.drop_last_turns(1)
    else:
        raise HTTPException(400, "nothing to retry yet")
    eng.restore_pre_turn_rpg()
    eng._swipes = None
    return _stream_generation(
        slug, lambda e, notes: e.turn(last_player, on_stage=notes.append))


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
    attrs = {str(k): str(v) for k, v in (d.get("attrs") or {}).items()
             if str(v).strip()}
    aliases = [str(a).strip() for a in (d.get("aliases") or [])
               if str(a).strip()]
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


@app.put("/api/saves/{slug}/world/main")
def save_world_main(slug: str, body: dict):
    store = _save_store(slug)
    premise = str(body.get("premise", "")).strip()
    # Preserve the opening unless the caller sends one: a live save's intro is
    # already in the transcript, and the builder hides that field for saves.
    intro = str(body.get("introduction", store.opening_override())).strip()
    _write_premise_md(store, premise, intro)
    world = str(body.get("world", "")).strip()
    store.write("world-bible.md", "# World bible\n\n"
                + (world + "\n" if world else ""))
    title = str(body.get("title", "")).strip()
    if title:
        lib.saves.rename(slug, title)
    return {"ok": True}


@app.put("/api/saves/{slug}/world/pieces/{rel}")
def save_world_piece_put(slug: str, rel: str, body: dict):
    store = _save_store(slug)
    if rel not in _piece_files(store):
        raise HTTPException(400, f"not a lore file of this save: {rel}")
    entry = _entry_from_dict(body.get("entry") or {})
    store.upsert_entry(rel, entry)
    old = str(body.get("old_slug", "")).strip()
    if old and old != entry.slug:
        store.remove_entry(rel, old)
    return {"ok": True, "slug": entry.slug}


@app.delete("/api/saves/{slug}/world/pieces/{rel}/{pslug}")
def save_world_piece_delete(slug: str, rel: str, pslug: str):
    store = _save_store(slug)
    if rel not in _piece_files(store):
        raise HTTPException(400, f"not a lore file of this save: {rel}")
    if not store.remove_entry(rel, pslug):
        raise HTTPException(404, f"no such piece: {pslug}")
    return {"ok": True}


@app.post("/api/saves/{slug}/world/types")
def save_world_add_type(slug: str, body: dict):
    _save_store(slug)                          # 404 guard
    return {"file": _declare_type_in(lib.saves.dir(slug), "meta.json",
                                     str(body.get("name", "")))}


@app.delete("/api/saves/{slug}/world/types/{fname}")
def save_world_delete_type(slug: str, fname: str):
    _save_store(slug)
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
    if not _gen_lock.acquire(blocking=False):
        raise HTTPException(409, "another generation is running")
    try:
        llm = LLM(_cfg.profile, _cfg.generation)
        result, err = assist_field(llm, kind, mode, text, context=context,
                                   improve=improve)
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
    if not lib.scenarios.delete(slug):
        raise HTTPException(404, f"no such scenario: {slug}")
    return {"ok": True}


@app.post("/api/scenarios/generate")
def generate_scenario_ep(body: dict):
    """AI world generation (SSE). Streams every stage note; `improve: true`
    runs the user's prompt through the detailer/improver first."""
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
                    result["slug"] = generate_scenario(
                        lib, llm, spec, on_stage=lambda s: q.put(s))
                    result["warnings"] = list(generate_scenario.last_warnings)
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
                scen = next((s for s in lib.scenarios.list()
                             if s["slug"] == result["slug"]), {})
                yield _sse({"t": "done", "slug": result["slug"],
                            "title": scen.get("title", result["slug"]),
                            "events": result.get("warnings", [])})
        finally:
            _gen_lock.release()
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


# ---------- library <-> scenario character exchange ----------
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
    _EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        path = lib.saves.export(slug, _EXPORT_DIR / f"save-{slug}.zip")
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    return FileResponse(path, filename=f"save-{slug}.zip",
                        media_type="application/zip")


def _stash_upload(file: UploadFile) -> Path:
    """Persist a multipart upload to a temp .zip so the library import_ helpers
    (which take a path) can read it. The file keeps its original name inside a
    unique dir so the import's derived slug reads well (the 'save-'/'world-'
    export prefix is stripped). Caller removes the dir's parent."""
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
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)
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
    raw = file.file.read()
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
            title = e["title"]
            store.upsert_entry("lore.md", Entry(
                title=title, slug=templates.slugify(title),
                aliases=e["keys"], importance=3,
                attrs={"triggers": ", ".join(e["keys"])} if e["keys"] else {},
                body=e["content"]))

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
        with zipfile.ZipFile(path) as z:
            for n in z.namelist():
                if n.endswith("/") or ".." in n.split("/"):
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
        },
    }


@app.put("/api/settings")
def put_settings(body: dict):
    raw = _cfg.raw
    mode = body.get("mode") if body.get("mode") in ("local", "hosted") \
        else "local"
    gen = body.get("generation") or {}
    raw.setdefault("generation", {})
    if gen.get("response_length") in ("short", "medium", "long"):
        raw["generation"]["response_length"] = gen["response_length"]
    if "trinity_brain" in gen:
        raw["generation"]["trinity_brain"] = bool(gen["trinity_brain"])

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


# ---------- static SPA ----------
@app.get("/")
def index():
    return FileResponse(ASSETS / "webapp" / "index.html")


app.mount("/", StaticFiles(directory=ASSETS / "webapp"), name="webapp")


if __name__ == "__main__":
    import os
    _port = int((os.environ.get("CODERAIN_PORT") or "8377").strip() or "8377")
    uvicorn.run(app, host="127.0.0.1", port=_port)
