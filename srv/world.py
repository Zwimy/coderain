"""A save's OWN copy of the world files, editable mid-play.

They diverge from the scenario as the story evolves. The engine reads the
Markdown fresh each turn, so an edit here goes live immediately."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi import HTTPException
from fastapi.responses import FileResponse
from coderain.generator import _split_premise_body
from coderain.generator import _write_premise_md
from coderain.profiles import entry_from_character

from .core import _clean_quick_actions
from .core import _clean_regex_rules
from .core import _exclusive
from .core import characters
from .core import lib
from .core import pieces_lib
from .pieces import _declare_type_in
from .pieces import _delete_type_in
from .pieces import _entry_dict
from .pieces import _entry_from_dict
from .pieces import _kind_to_rel
from .pieces import _piece_files
from .pieces import _save_store

router = APIRouter()


@router.get("/api/saves/{slug}/world/full")
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


@router.get("/api/saves/{slug}/authors-note")
def get_authors_note(slug: str):
    store = _save_store(slug)
    an = store.world_state().get("authors_note")
    an = an if isinstance(an, dict) else {}
    depth = an.get("depth") if an.get("depth") in ("system", "tail") else "system"
    try:
        every = max(1, int(an.get("every", 1)))
    except (TypeError, ValueError):
        every = 1
    return {"content": store.custom_instructions(), "depth": depth, "every": every}


@router.put("/api/saves/{slug}/authors-note")
def put_authors_note(slug: str, body: dict):
    """ST-21: the per-save author's note — content + placement (depth/frequency)."""
    store = _save_store(slug)
    content = str(body.get("content", "") or "")
    depth = body.get("depth") if body.get("depth") in ("system", "tail") else "system"
    try:
        every = max(1, int(body.get("every", 1)))
    except (TypeError, ValueError):
        every = 1
    with _exclusive():                           # don't race a live turn's state write
        # custom_instructions() reads the body BELOW the first `---`; keep whatever
        # header sits above it (the template's, or the user's own) instead of nuking it.
        existing = store.read("custom-instructions.md")
        head = existing.split("---", 1)[0] if "---" in existing \
            else "# Custom instructions (this save)\n\n"
        store.write("custom-instructions.md", head + "---\n" + content)
        state = store.world_state()
        state["authors_note"] = {"depth": depth, "every": every}
        store.set_world_state(state)
    return {"ok": True}


@router.get("/api/saves/{slug}/aids")
def get_aids(slug: str):
    ws = _save_store(slug).world_state()
    return {"quick_actions": _clean_quick_actions(ws.get("quick_actions")),
            "regex_rules": _clean_regex_rules(ws.get("regex_rules"))}


@router.put("/api/saves/{slug}/aids")
def put_aids(slug: str, body: dict):
    """ST-30 per-save quick actions + ST-31 persistent output regex rules."""
    store = _save_store(slug)
    qa = _clean_quick_actions(body.get("quick_actions"))
    rules = _clean_regex_rules(body.get("regex_rules"))
    with _exclusive():                           # don't race a live turn's state write
        state = store.world_state()
        state["quick_actions"] = qa
        state["regex_rules"] = rules
        store.set_world_state(state)
    return {"ok": True}


@router.put("/api/saves/{slug}/world/main")
def save_world_main(slug: str, body: dict):
    store = _save_store(slug)
    premise = str(body.get("premise", "")).strip()
    world = str(body.get("world", "")).strip()
    title = str(body.get("title", "")).strip()
    with _exclusive():                           # don't race a live turn's state write
        # Preserve the opening unless the caller sends one: a live save's intro is
        # already in the transcript, and the builder hides that field for saves.
        intro = str(body.get("introduction", store.opening_override())).strip()
        _write_premise_md(store, premise, intro)
        store.write("world-bible.md", "# World bible\n\n"
                    + (world + "\n" if world else ""))
        if title:
            lib.saves.rename(slug, title)
    return {"ok": True}


@router.put("/api/saves/{slug}/world/pieces/{rel}")
def save_world_piece_put(slug: str, rel: str, body: dict):
    store = _save_store(slug)
    if rel not in _piece_files(store):
        raise HTTPException(400, f"not a lore file of this save: {rel}")
    entry = _entry_from_dict(body.get("entry") or {})
    old = str(body.get("old_slug", "")).strip()
    with _exclusive():                           # don't race a live turn's state write
        store.upsert_entry(rel, entry)
        if old and old != entry.slug:
            store.remove_entry(rel, old)
    return {"ok": True, "slug": entry.slug}


@router.delete("/api/saves/{slug}/world/pieces/{rel}/{pslug}")
def save_world_piece_delete(slug: str, rel: str, pslug: str):
    store = _save_store(slug)
    if rel not in _piece_files(store):
        raise HTTPException(400, f"not a lore file of this save: {rel}")
    with _exclusive():                           # don't race a live turn's state write
        if not store.remove_entry(rel, pslug):
            raise HTTPException(404, f"no such piece: {pslug}")
    return {"ok": True}


@router.post("/api/saves/{slug}/world/types")
def save_world_add_type(slug: str, body: dict):
    _save_store(slug)                          # 404 guard
    with _exclusive():                           # meta.json write vs. a live turn
        return {"file": _declare_type_in(lib.saves.dir(slug), "meta.json",
                                         str(body.get("name", "")))}


@router.delete("/api/saves/{slug}/world/types/{fname}")
def save_world_delete_type(slug: str, fname: str):
    _save_store(slug)
    with _exclusive():                           # meta.json write vs. a live turn
        return _delete_type_in(lib.saves.dir(slug), "meta.json", fname)


@router.get("/api/saves/{slug}/world/pieces/{rel}/export")
def save_world_section_export(slug: str, rel: str):
    store = _save_store(slug)
    if rel not in _piece_files(store):
        raise HTTPException(400, f"not a lore file of this save: {rel}")
    path = lib.saves.dir(slug) / rel
    if not path.exists():
        raise HTTPException(404, f"{rel} has no content yet")
    return FileResponse(path, filename=f"{slug}-{rel}",
                        media_type="text/markdown")


@router.post("/api/saves/{slug}/world/from-library")
def save_world_insert_character(slug: str, body: dict):
    char = characters.get(str(body.get("id", "")).strip())
    if char is None:
        raise HTTPException(404, "no such character")
    store = _save_store(slug)
    entry = entry_from_character(char)
    with _exclusive():                           # don't race a live turn's state write
        store.upsert_entry("characters.md", entry)
    return {"ok": True, "slug": entry.slug}


@router.post("/api/saves/{slug}/world/from-piece-library")
def save_world_insert_piece(slug: str, body: dict):
    rec = pieces_lib.get(str(body.get("id", "")).strip())
    if rec is None:
        raise HTTPException(404, "no such library piece")
    entry = pieces_lib.entry(rec["id"])
    rel = _kind_to_rel(rec.get("type", ""))
    store = _save_store(slug)
    with _exclusive():                           # don't race a live turn's state write
        if rel not in _piece_files(store):
            _declare_type_in(lib.saves.dir(slug), "meta.json", rel.removesuffix(".md"))
            store = _save_store(slug)
        store.upsert_entry(rel, entry)
    return {"ok": True, "rel": rel, "slug": entry.slug}
