"""Canon: what the memory holds about each character, and the author's corrections to it (D-028).

Three routes. GET shows what canon holds (the same view the Writer's card is built from, with the corrections
already applied), the corrections file and anything in it that could not be applied. PUT replaces the file, which
is Markdown in the save and the source of truth, so a hand edit and the app are the same thing. POST adds one
correction, the call a button next to a wrong value would make. The reader applies a change on its next pass; the
card honours it from the very next turn, because it applies the corrections itself.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from canon.corrections import FILE, MAX_FILE, MAX_VALUE, MAX_WHO, SLOTS, add_line, describe, slot_word

from .core import _engine

router = APIRouter()


def _view(eng) -> dict:
    sh = eng.canon_shadow
    if sh is None:
        # Without the shadow nothing reads the story, but the file can still be written and checked;
        # it takes effect when canon.shadow is turned on.
        return {"shadow": False, "inject": "off", "values": [], "unread": None, "card": "",
                **describe(eng.store.read(FILE) or "")}
    return sh.view(eng.store.turns())


def _save(eng, text: str) -> dict:
    eng.store.write(FILE, text)
    if eng.canon_shadow is not None:
        eng.canon_shadow.kick()                 # never raises, never waits
    return _view(eng)


@router.get("/api/saves/{slug}/canon")
def canon_view(slug: str):
    return _view(_engine(slug))


@router.put("/api/saves/{slug}/canon/corrections")
def canon_put(slug: str, body: dict):
    text = body.get("text")
    if not isinstance(text, str):
        raise HTTPException(400, "text must be a string")
    if len(text) > MAX_FILE:
        raise HTTPException(400, f"corrections.md is limited to {MAX_FILE} characters")
    return _save(_engine(slug), text)


@router.post("/api/saves/{slug}/canon/corrections")
def canon_add(slug: str, body: dict):
    who = " ".join(str(body.get("who", "")).split())
    value = " ".join(str(body.get("value", "")).split())
    slot, op = slot_word(str(body.get("slot", ""))), body.get("op")
    if not who or len(who) > MAX_WHO:
        raise HTTPException(400, "who must name a character")
    if slot is None:
        raise HTTPException(400, f"slot must be one of {', '.join(SLOTS)}")
    if op not in ("set", "wrong"):
        raise HTTPException(400, "op must be 'set' or 'wrong'")
    if not value or len(value) > MAX_VALUE:
        raise HTTPException(400, f"value must be 1 to {MAX_VALUE} characters")
    if ":" in who or "=" in who:
        raise HTTPException(400, "a name cannot contain ':' or '='")
    if " -- " in value:
        raise HTTPException(400, "a value cannot contain ' -- ' (it starts a note in the file)")
    eng = _engine(slug)
    text = add_line(eng.store.read(FILE) or "", who, slot, op, value)
    if len(text) > MAX_FILE:
        raise HTTPException(400, f"corrections.md is limited to {MAX_FILE} characters")
    return _save(eng, text)
