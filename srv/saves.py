"""Save lifecycle: list, create, open, delete, mode, branch, and the
context inspector."""
from __future__ import annotations

import re
from fastapi import APIRouter
from fastapi import HTTPException
from coderain import features
from coderain.config import context_budget
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
    eng = _engine(slug)
    store = eng.store
    hist = store.recent_turns(eng.short_term)
    msgs = eng._messages(hist, "(preview of the next turn)")
    sys_txt = msgs[0]["content"]
    # Split on the section headings assemble() writes; entry headings carry a
    # {#slug} and belong to the section above them, so they are not split points.
    parts = re.split(r"(?m)^## (?![^\n]*\{#)(.+)$", sys_txt)
    preamble, sections = parts[0], []
    for i in range(1, len(parts) - 1, 2):
        body = parts[i + 1]
        sections.append({
            "title": parts[i].strip(),
            "chars": len(body.strip()),
            "entries": len(re.findall(r"(?m)^## [^\n]*\{#", body)),
        })
    hist_chars = sum(len(m["content"]) for m in msgs[1:])
    total = len(sys_txt) + hist_chars
    budget = context_budget(core._cfg)
    return {
        "model": core._cfg.profile.model,
        "brain": "quad" if eng.trinity else "single",
        "lore_check": {"on": bool(core._cfg.generation.get("lore_check")),
                       "every": int(core._cfg.generation.get("lore_check_every", 1)),
                       "due_next_turn": eng.lore_due()},
        "budget_tokens": budget,
        "rules_chars": len(preamble.strip()),
        "history_msgs": len(msgs) - 1,
        "history_chars": hist_chars,
        "system_chars": len(sys_txt),
        "total_chars": total,
        "approx_tokens": total // 4,
        "budget_used_pct": round(len(sys_txt) / max(1, budget * 4) * 100),
        "sections": sorted(sections, key=lambda s: -s["chars"]),
        "semantic_recall": "on" if eng.retriever is not None else "off",
        # Anything that silently fell back. Degrading is fine; degrading
        # invisibly is what costs continuity with nothing to show for it.
        "health": store.health(limit=8),
        # The provider's OWN token counts, not the /4 estimate above. Everything
        # else on this payload is what we think we sent; this is what was billed.
        "usage": _usage_payload(store),
    }


def _usage_payload(store) -> dict:
    """Lifetime tokens for this story, plus the most recent turn, per stage."""
    tot = store.usage_total()
    recent = store.usage(limit=40)
    last_turn = recent[0].get("turn") if recent else None
    return {
        "total_in": int(tot.get("in", 0)),
        "total_out": int(tot.get("out", 0)),
        "cached": int(tot.get("cached", 0)),
        "calls": int(tot.get("calls", 0)),
        "by_stage": tot.get("by_stage", {}),
        "last_turn": store.usage_for_turn(last_turn) if last_turn is not None
        else {"in": 0, "out": 0, "calls": 0},
        "price_in": float(core._cfg.raw.get("price_in", 0) or 0),
        "price_out": float(core._cfg.raw.get("price_out", 0) or 0),
    }


@router.get("/api/saves/{slug}/usage")
def save_usage(slug: str):
    """The token ledger on its own, with the recent per-call rows."""
    store = _engine(slug).store
    return {**_usage_payload(store), "recent": store.usage(limit=60)}
