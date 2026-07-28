"""Raw memory and rule files for a save — the repair hatch.

When a fold goes wrong, this is how a player fixes it by hand."""
from __future__ import annotations

import json
from fastapi import APIRouter
from fastapi import HTTPException

from .core import _exclusive
from .pieces import _save_store

router = APIRouter()


# ---------- models + settings ----------
# ---------- raw memory / rule files for a save (repair hatch) ----------
@router.get("/api/saves/{slug}/files")
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


@router.get("/api/saves/{slug}/files/{rel:path}")
def read_save_file(slug: str, rel: str):
    store = _save_store(slug)
    from coderain.memory import EDITABLE_FILES, RULE_FILES
    if rel not in EDITABLE_FILES:
        raise HTTPException(404, "not an editable file")
    return {"rel": rel, "text": store.read(rel), "layer": store.layer_of(rel),
            "is_rule": rel in RULE_FILES}


@router.put("/api/saves/{slug}/files/{rel:path}")
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
        before = len(store.turns()) if rel == "transcript.md" else 0
        store.write(rel, text)
        # A hand edit to the transcript or the world state invalidates whatever
        # the live engine is holding ABOUT that exchange. Only PUT /turns/{i}
        # cleared it, so after deleting the last exchange in "Transcript (raw)"
        # a ◄ wrote the deleted exchange's prose over a different exchange's
        # turn (invariant 7), and after editing state.json an Undo silently
        # discarded the edit by writing the pre-turn snapshot back over it.
        if rel in ("transcript.md", "state.json"):
            _forget_exchange(slug)
        # ONLY when the edit actually shortened the transcript. A hand edit
        # that does reaches undo's problem exactly: ledger records past the new
        # end that no branch point can reach while state.json keeps their
        # deltas (invariant 3), and a fold pointer claiming turns that are gone
        # (invariant 6). But running the reconciliation on EVERY write was
        # lossy and irreversible: re-stamping a record's turn index cannot be
        # undone, so cutting an exchange and pasting it straight back left two
        # envelopes sharing one index forever, and a later branch replayed
        # deltas from turns after its own branch point. A byte-identical
        # rewrite must be a no-op.
        if rel == "transcript.md" and len(store.turns()) < before:
            # Snapshot first. trim_folds_to_transcript DELETES any scene whose
            # range reaches past the new end — cutting one exchange can drop a
            # fold covering five turns that still exist. branch() gets away
            # with the same call because it restores memory files from a
            # pre-fold snapshot first; this writer restores nothing, so the
            # snapshot is the only way back.
            store.snapshot(keep=8, reason="transcript-edit")
            store.clamp_event_log_to_transcript()
            store.trim_folds_to_transcript()
    return {"ok": True, "layer": store.layer_of(rel)}


def _forget_exchange(slug: str) -> None:
    """Drop the cached engine's per-exchange undo/swipe state for `slug`.

    Best-effort: no live engine (or a build without the play router) simply
    means there is nothing cached to invalidate."""
    try:
        from .core import _engines
    except ImportError:                  # pragma: no cover - trimmed build
        return
    eng = _engines.get(slug)
    if eng is None:
        return
    eng._swipes = None
    eng._pre_turn_rpg = None
    eng._pre_turn_log = None
    eng._pre_turn_reveals = []
    eng._pre_turn_canon = []
    eng._pre_turn_events = []


@router.post("/api/saves/{slug}/rules/{rel}/override")
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


@router.delete("/api/saves/{slug}/rules/{rel}/override")
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
