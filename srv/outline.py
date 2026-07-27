"""The rolling chapter plan (the book plan panel)."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi import HTTPException

from .core import _engine
from .core import _exclusive

router = APIRouter()


# ---------- chapter outline (the rolling book plan) ----------
def _outline_payload(eng) -> dict:
    return {"enabled": eng.planner.enabled(),
            "horizon": eng.planner.horizon,
            "chapters": eng.planner.as_dicts()}


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
    rows = eng.planner.as_dicts()
    if not 0 <= idx < len(rows):
        raise HTTPException(404, "no such chapter")
    if "title" in body:
        rows[idx]["title"] = str(body.get("title", "")).strip() or rows[idx]["title"]
    if "goal" in body:
        rows[idx]["goal"] = str(body.get("goal", "")).strip()
    with _exclusive():
        eng.planner.replace_all(rows)
    return _outline_payload(eng)


@router.post("/api/saves/{slug}/outline")
def add_chapter(slug: str, body: dict):
    """Insert a planned chapter. `after` is the 0-based index to insert behind
    (default: append to the end)."""
    eng = _engine(slug)
    rows = eng.planner.as_dicts()
    new = {"title": str(body.get("title", "")).strip() or "New chapter",
           "goal": str(body.get("goal", "")).strip(), "status": "planned"}
    after = body.get("after")
    pos = len(rows)
    if isinstance(after, int) and 0 <= after < len(rows):
        pos = after + 1
    rows.insert(pos, new)
    with _exclusive():
        eng.planner.replace_all(rows)
    return _outline_payload(eng)


@router.delete("/api/saves/{slug}/outline/{idx}")
def delete_chapter(slug: str, idx: int):
    """Delete a planned chapter. A done or active chapter can't be deleted (it's
    already part of the story) — advance instead."""
    eng = _engine(slug)
    rows = eng.planner.as_dicts()
    if not 0 <= idx < len(rows):
        raise HTTPException(404, "no such chapter")
    if rows[idx]["status"] in ("done", "active"):
        raise HTTPException(400, "only a planned chapter can be deleted")
    rows.pop(idx)
    with _exclusive():
        eng.planner.replace_all(rows)
    return _outline_payload(eng)


@router.post("/api/saves/{slug}/outline/{idx}/move")
def move_chapter(slug: str, idx: int, body: dict):
    """Reorder a planned chapter up (-1) or down (+1). Movement is confined to the
    planned tail — a done/active chapter can't be dragged out of story order."""
    eng = _engine(slug)
    rows = eng.planner.as_dicts()
    if not 0 <= idx < len(rows):
        raise HTTPException(404, "no such chapter")
    try:
        direction = int(body.get("dir", 0))
    except (TypeError, ValueError):
        raise HTTPException(400, "dir must be -1 or 1")
    j = idx + (1 if direction > 0 else -1)
    if not 0 <= j < len(rows):
        return _outline_payload(eng)                 # already at an edge — no-op
    if rows[idx]["status"] != "planned" or rows[j]["status"] != "planned":
        raise HTTPException(400, "only planned chapters can be reordered")
    rows[idx], rows[j] = rows[j], rows[idx]
    with _exclusive():
        eng.planner.replace_all(rows)
    return _outline_payload(eng)
