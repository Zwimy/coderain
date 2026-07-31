"""The rolling chapter plan (the book plan panel)."""
from __future__ import annotations

import contextlib

from fastapi import APIRouter
from fastapi import HTTPException

from coderain.planner import PlanError

from .core import _engine
from .core import _exclusive

router = APIRouter()


# ---------- chapter outline (the rolling book plan) ----------
def _outline_payload(eng) -> dict:
    return {"enabled": eng.planner.enabled(),
            "horizon": eng.planner.horizon,
            "chapters": eng.planner.as_dicts()}


@contextlib.contextmanager
def _as_http():
    """Translate the planner's refusals into HTTP. The RULES live on the planner
    (a done chapter is already part of the story, so it cannot be deleted or
    reordered) because they are the engine's, not the transport's — they used to
    be written inline here as HTTPException, which made them unreachable from the
    desktop app, so it could not edit an outline at all."""
    try:
        yield
    except PlanError as e:
        raise HTTPException(404 if "no such chapter" in str(e) else 400, str(e))


@router.get("/api/saves/{slug}/outline")
def get_outline(slug: str):
    return _outline_payload(_engine(slug))


@router.post("/api/saves/{slug}/outline/generate")
def generate_outline(slug: str):
    """(Re)seed the whole outline from the premise — the panel's 'Generate' /
    'Regenerate' button. One LLM call; replaces any existing plan."""
    eng = _engine(slug)
    if not eng.planner.enabled():
        raise HTTPException(400, "the chapter outline is turned off in Settings")
    with _exclusive():
        eng.planner.seed(force=True)
    return _outline_payload(eng)


@router.post("/api/saves/{slug}/outline/advance")
def advance_outline(slug: str):
    """Manually mark the active chapter done and roll the plan forward (the
    'Chapter done' button) — same path the auto fold-detection uses."""
    eng = _engine(slug)
    with _exclusive():
        events = eng.planner.complete_active()
    return {**_outline_payload(eng), "events": events}


@router.put("/api/saves/{slug}/outline/{idx}")
def edit_chapter(slug: str, idx: int, body: dict):
    """Edit a chapter's title and/or goal in place (positions unchanged)."""
    eng = _engine(slug)
    with _exclusive(), _as_http():
        eng.planner.edit(idx, body.get("title") if "title" in body else None,
                         body.get("goal") if "goal" in body else None)
    return _outline_payload(eng)


@router.post("/api/saves/{slug}/outline")
def add_chapter(slug: str, body: dict):
    """Insert a planned chapter. `after` is the 0-based index to insert behind
    (default: append to the end)."""
    eng = _engine(slug)
    with _exclusive(), _as_http():
        eng.planner.insert(body.get("after"),
                           str(body.get("title", "") or "New chapter"),
                           str(body.get("goal", "") or ""))
    return _outline_payload(eng)


@router.delete("/api/saves/{slug}/outline/{idx}")
def delete_chapter(slug: str, idx: int):
    """Delete a planned chapter. A done or active chapter can't be deleted (it's
    already part of the story) — advance instead."""
    eng = _engine(slug)
    with _exclusive(), _as_http():
        eng.planner.delete(idx)
    return _outline_payload(eng)


@router.post("/api/saves/{slug}/outline/{idx}/move")
def move_chapter(slug: str, idx: int, body: dict):
    """Reorder a planned chapter up (-1) or down (+1). Movement is confined to the
    planned tail — a done/active chapter can't be dragged out of story order."""
    eng = _engine(slug)
    with _exclusive(), _as_http():
        eng.planner.move(idx, body.get("dir", 0))
    return _outline_payload(eng)
