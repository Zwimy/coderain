"""Save lifecycle: list, create, open, delete, mode, branch, and the
context inspector."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi import HTTPException
from coderain import features
from coderain.inspect import context_report, usage_report
from coderain.memory import Entry
from coderain.profiles import apply_character
from coderain.profiles import apply_playable_entry

from . import core
from .core import _engine
from .core import _engines
from .core import _exclusive
from .core import _guard_slug
from .core import _save_payload
from .core import characters
from .core import lib
from .pieces import _save_store

router = APIRouter()


# ---------- library ----------
@router.get("/api/saves")
def list_saves():
    return {"saves": lib.saves.list(), "scenarios": lib.scenarios.list(),
            "characters": characters.list()}


@router.post("/api/saves")
def create_save(body: dict):
    title = str(body.get("title", "")).strip() or "Untitled"
    scenario = str(body.get("scenario", "")).strip()
    mode = body.get("mode") if body.get("mode") in ("simple", "rpg") \
        else "simple"
    premise = str(body.get("premise", "")).strip()
    start_time = body.get("start_time") if isinstance(
        body.get("start_time"), dict) else None
    slug = lib.saves.create(title, scenario, mode=mode, premise=premise,
                            rpg_cfg=core._cfg.rpg, start_time=start_time)
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


@router.get("/api/saves/{slug}")
def get_save(slug: str):
    return _save_payload(slug)


@router.delete("/api/saves/{slug}")
def delete_save(slug: str):
    _guard_slug(slug)
    with _exclusive():                       # don't rmtree files under a live turn
        _engines.pop(slug, None)
        if not lib.saves.delete(slug):
            raise HTTPException(404, f"no such save: {slug}")
    return {"ok": True}


@router.put("/api/saves/{slug}/mode")
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


@router.post("/api/saves/{slug}/branch")
def branch_save(slug: str, body: dict):
    try:
        n = int(body.get("turn", 0))
    except (TypeError, ValueError):
        raise HTTPException(400, "turn must be a number")
    total = len(_engine(slug).store.turns())
    if not 1 <= n <= total:
        raise HTTPException(400, f"turn must be 1..{total}")
    with _exclusive():                       # copy a consistent transcript snapshot
        new_slug, warnings = lib.saves.branch(slug, n, core._cfg.rpg)
    return {"slug": new_slug, "warnings": warnings}


# ---------- context inspector ----------
@router.get("/api/saves/{slug}/context")
def inspect_context(slug: str):
    """What the model ACTUALLY receives this turn, section by section.

    Assembles the real payload (no model call, no tokens spent) and reports every
    section with its size, so "the story forgot X" can be answered with "X is not
    in the prompt, here is why" instead of guesswork. Three real bugs this month
    were found with a throwaway version of this; it belongs in the app."""
    # The report itself lives in coderain.inspect so the desktop UI can show the
    # same thing. This route is now transport only.
    return context_report(_engine(slug), core._cfg)


def _usage_payload(store) -> dict:
    return usage_report(store, core._cfg)


@router.get("/api/saves/{slug}/usage")
def save_usage(slug: str):
    """The token ledger on its own, with the recent per-call rows."""
    store = _engine(slug).store
    return {**_usage_payload(store), "recent": store.usage(limit=60)}


# ---------- folded scenes (review the memory a fold just wrote) ----------
def _scene_dict(e) -> dict:
    return {"slug": e.slug, "title": e.title, "summary": e.body,
            "turns": e.attrs.get("turns", ""), "when": e.attrs.get("when", ""),
            "characters": e.attrs.get("characters", ""),
            "locations": e.attrs.get("locations", "")}


@router.get("/api/saves/{slug}/scenes")
def list_scenes(slug: str, limit: int = 3):
    """The most recent folded scenes, newest first.

    A fold rewrites ten turns into a paragraph and then the raw turns stop being
    sent. If that paragraph dropped something, the story starts contradicting
    itself many turns later and the cause is long out of view. This is how the
    player sees what a fold actually wrote, while it still means something."""
    store = _engine(slug).store
    scenes = store.entries("memory/scenes.md")
    return {"scenes": [_scene_dict(e) for e in reversed(scenes[-max(1, limit):])]}


@router.put("/api/saves/{slug}/scenes/{sslug}")
def edit_scene(slug: str, sslug: str, body: dict):
    """Rewrite one folded scene's summary by hand."""
    summary = str(body.get("summary", "")).strip()
    if not summary:
        raise HTTPException(400, "a scene summary can't be empty")
    with _exclusive():
        store = _engine(slug).store
        entry = next((e for e in store.entries("memory/scenes.md")
                      if e.slug == sslug), None)
        if entry is None:
            raise HTTPException(404, f"no such scene: {sslug}")
        entry.body = summary
        store.upsert_entry("memory/scenes.md", entry)
        return {"ok": True, "scene": _scene_dict(entry)}


@router.post("/api/saves/{slug}/scenes/{sslug}/redo")
def redo_scene(slug: str, sslug: str):
    """Re-summarise a scene from its original turns. Costs one model call."""
    with _exclusive():
        eng = _engine(slug)
        try:
            res = eng.summarizer.refold_scene(sslug)
        except Exception as e:  # noqa: BLE001 — a bad redo must not 500 the app
            raise HTTPException(502, core._model_error_text(e))
        if not res.get("ok"):
            raise HTTPException(400, res.get("error", "the redo failed"))
        return res
