"""Playing a turn: opening, turn, retry, continue, swipes, undo, talk.

Every generating endpoint streams through core._stream_generation."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi import HTTPException

from .core import _cancel
from .core import _engine
from .core import _engines
from .core import _exclusive
from .core import _model_error_text
from .core import _sheet_lines
from .core import _stream_generation

router = APIRouter()


# ---------- play ----------
def _reset_swipes(slug: str) -> None:
    eng = _engines.get(slug)
    if eng is not None:
        eng._swipes = None      # a genuine new/edited turn invalidates alternates


@router.post("/api/saves/{slug}/opening")
def opening(slug: str):
    _reset_swipes(slug)
    return _stream_generation(
        slug, lambda eng, notes: eng.opening(on_stage=notes.append))


@router.post("/api/saves/{slug}/turn")
def turn(slug: str, body: dict):
    text = str(body.get("text", "")).strip()
    if not text:
        raise HTTPException(400, "empty action")
    _reset_swipes(slug)
    return _stream_generation(
        slug, lambda eng, notes: eng.turn(text, on_stage=notes.append))


@router.put("/api/saves/{slug}/turns/{i}")
def edit_turn(slug: str, i: int, body: dict):
    """In-place message edit (ST-03)."""
    eng = _engine(slug)
    with _exclusive():                       # don't rewrite the transcript mid-turn
        if not eng.store.update_turn(i, str(body.get("text", ""))):
            raise HTTPException(400, f"no turn at index {i}")
        eng._swipes = None
    return {"ok": True}


@router.post("/api/saves/{slug}/impersonate")
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


@router.post("/api/saves/{slug}/swipe")
def swipe_browse(slug: str, body: dict):
    """Browse cached narrator alternates without generating (ST-02)."""
    eng = _engine(slug)
    direction = 1 if int(body.get("dir", 1)) >= 0 else -1
    with _exclusive():                       # rewrites the tail turn — not mid-gen
        out = eng.swipe_browse(direction)
    if out is None:
        raise HTTPException(400, "nothing to swipe")
    return out


@router.post("/api/saves/{slug}/swipe-gen")
def swipe_gen(slug: str):
    """Generate a NEW narrator alternate and select it (ST-02)."""
    return _stream_generation(
        slug, lambda eng, notes: eng.swipe_generate(on_stage=notes.append))


@router.post("/api/saves/{slug}/cancel")
def cancel_generation(slug: str):
    """Stop the in-flight turn. Sets the cooperative flag the stream pump checks
    between chunks; the turn then unwinds and its player action is cleaned up.
    (A non-streaming planner stage finishes first — cancel lands at the next
    chunk boundary.)"""
    _cancel.set()
    return {"ok": True}


@router.post("/api/saves/{slug}/undo")
def undo(slug: str):
    eng = _engine(slug)
    with _exclusive():
        ok = eng.undo_last()
        eng._swipes = None
    return {"ok": ok, "turns": len(eng.store.turns()),
            "sheet": _sheet_lines(eng)}


@router.post("/api/saves/{slug}/retry")
def retry(slug: str):
    eng = _engine(slug)
    turns = eng.store.turns()
    if not (turns and turns[-1]["role"] in ("narrator", "player")):
        raise HTTPException(400, "nothing to retry yet")

    def run(e, notes):
        # The destructive rollback runs UNDER the generation lock (inside the
        # stream) so it can't truncate the transcript of an in-flight turn.
        ok, last_player = e.rollback_for_retry()
        if not ok:
            return iter(())               # nothing to retry (raced away)
        return e.regenerate(last_player, on_stage=notes.append)

    return _stream_generation(slug, run)


@router.post("/api/saves/{slug}/continue")
def continue_story(slug: str):
    """Extend the prose with no player action (the 'Continue' button)."""
    _reset_swipes(slug)
    return _stream_generation(
        slug, lambda eng, notes: eng.continue_story(on_stage=notes.append))


@router.post("/api/saves/{slug}/talk")
def talk(slug: str, body: dict):
    name = str(body.get("name", "")).strip()
    text = str(body.get("text", "")).strip()
    if not name or not text:
        raise HTTPException(400, "need a companion name and a message")
    return _stream_generation(
        slug, lambda eng, notes: eng.companion_chat(name, text))
