"""Character traits (D-032): the Plan panel's Characters. See coderain/cast.py.

GET lists everyone who can be given strengths, weaknesses, a personality type and goals, with what they have now
(and, for reference, their live `wants` and `motivation`, which the memory fold keeps and this does not touch).
PUT sets or clears some of one character's four fields; a value over its limit or a field that does not exist is a
400 and a character that does not exist is a 404, with nothing written.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from coderain.cast import FIELDS, LIMITS, CastError, roster, set_traits

from .core import _engine, _exclusive

router = APIRouter()


def _payload(eng) -> dict:
    return {"fields": list(FIELDS), "limits": dict(LIMITS), "characters": roster(eng.store)}


@router.get("/api/saves/{slug}/cast")
def cast_view(slug: str):
    return _payload(_engine(slug))


@router.put("/api/saves/{slug}/cast/{key}")
def cast_set(slug: str, key: str, body: dict):
    eng = _engine(slug)
    try:
        with _exclusive():
            row = set_traits(eng.store, key, body)
    except CastError as e:
        raise HTTPException(404 if e.missing else 400, str(e))
    return row
