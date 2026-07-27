"""AI assist for the builder, scenario completion, and the piece
library (saved characters and world pieces, reusable across scenarios)."""
from __future__ import annotations

import queue
import threading
from fastapi import APIRouter
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from coderain import templates
from coderain.generator import ScenarioSpec
from coderain.generator import assist_field
from coderain.generator import complete_scenario
from coderain.llm import LLM
from coderain.memory import Entry
from coderain.profiles import character_from_entry
from coderain.profiles import entry_from_character

from . import core
from .core import _gen_lock
from .core import _guard_slug
from .core import _model_error_text
from .core import _sse
from .core import characters
from .core import lib
from .core import pieces_lib
from .pieces import _declare_custom_type
from .pieces import _entry_dict
from .pieces import _entry_from_dict
from .pieces import _kind_to_rel
from .pieces import _piece_files
from .pieces import _rel_to_kind
from .pieces import _save_store
from .pieces import _scen_store
from .pieces import _scenario_context

router = APIRouter()


@router.post("/api/assist")
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
        llm = LLM(core._cfg.profile, core._cfg.generation)
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


@router.post("/api/scenarios/{slug}/complete")
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
                    llm = LLM(core._cfg.profile, core._cfg.generation)
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
                # Everything the AI just made also becomes a reusable library
                # piece (the play-test ask: "add everything to pieces as well").
                added = _mirror_scenario_to_library(slug)
                warns = list(result.get("warnings", []))
                if added["characters"] or added["pieces"]:
                    warns.append(f"added {added['characters']} characters + "
                                 f"{added['pieces']} pieces to your library")
                yield _sse({"t": "done", "slug": slug, "events": warns})
        finally:
            _gen_lock.release()
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@router.post("/api/scenarios/{slug}/from-library")
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


@router.post("/api/characters/from-entry")
def character_save_entry(body: dict):
    """Save a scenario piece back into the character library."""
    entry = _entry_from_dict(body.get("entry") or {})
    return characters.save(character_from_entry(entry))


def _mirror_scenario_to_library(slug: str) -> dict:
    """Copy a world's pieces into the reusable Pieces library so a whole world's
    cast/lore becomes reusable in one step. Idempotent: dedupes generic pieces by
    (type, slug) and characters by name, so re-running (or auto-mirror on each
    generation) never duplicates."""
    store = _scen_store(slug)
    added = {"characters": 0, "pieces": 0}
    have_pieces = {(p.get("type"), (p.get("entry") or {}).get("slug"))
                   for p in pieces_lib.list()}
    have_chars = {str(c.get("name", "")).strip().lower()
                  for c in characters.list()}
    for rel in _piece_files(store):
        kind = _rel_to_kind(rel)
        for e in store.entries(rel):
            if rel == "characters.md":
                nm = e.title.strip().lower()
                if not nm or nm in have_chars:
                    continue
                characters.save(character_from_entry(e))
                have_chars.add(nm)
                added["characters"] += 1
            else:
                key = (kind, e.slug)
                if key in have_pieces:
                    continue
                pieces_lib.save(kind, {
                    "title": e.title, "slug": e.slug, "aliases": e.aliases,
                    "importance": e.importance, "attrs": e.attrs, "body": e.body})
                have_pieces.add(key)
                added["pieces"] += 1
    return added


@router.post("/api/scenarios/{slug}/to-library")
def scenario_to_library(slug: str):
    """Add every piece in this world to the reusable Pieces library."""
    _guard_slug(slug)
    return {"ok": True, "added": _mirror_scenario_to_library(slug)}


@router.get("/api/library")
def list_library(type: str = ""):
    return {"pieces": pieces_lib.list(type), "types": pieces_lib.types()}


@router.post("/api/library")
def save_library_piece(body: dict):
    try:
        return pieces_lib.save(str(body.get("type", "")),
                               body.get("entry") or {},
                               pid=str(body.get("id", "")).strip())
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e))


@router.delete("/api/library/{pid}")
def delete_library_piece(pid: str):
    if not pieces_lib.delete(pid):
        raise HTTPException(404, "no such library piece")
    return {"ok": True}


@router.post("/api/scenarios/{slug}/from-piece-library")
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
