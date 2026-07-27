"""The scenario builder: the reusable world a save is created from."""
from __future__ import annotations

import json
from fastapi import APIRouter
from fastapi import HTTPException
from fastapi.responses import FileResponse
from coderain.generator import _split_premise_body
from coderain.generator import _write_premise_md

from .core import _engines
from .core import _exclusive
from .core import _guard_slug
from .core import lib
from .pieces import _BASE_PIECE_FILES
from .pieces import _declare_custom_type
from .pieces import _entry_dict
from .pieces import _entry_from_dict
from .pieces import _piece_files
from .pieces import _scen_store

router = APIRouter()


@router.post("/api/scenarios")
def create_scenario(body: dict):
    """Create a world — a builder shell (empty premise is fine; the builder
    fills it) or a complete manual one with premise + introduction."""
    title = str(body.get("title", "")).strip() or "Untitled World"
    premise = str(body.get("premise", "")).strip()
    slug = lib.scenarios.create(
        title, premise,
        world=str(body.get("world", "")).strip(),
        description=str(body.get("description", "")).strip() or premise[:140],
        introduction=str(body.get("introduction", "")).strip())
    return {"slug": slug}


@router.get("/api/scenarios/{slug}/full")
def scenario_full(slug: str):
    store = _scen_store(slug)
    meta = json.loads((lib.scenarios.dir(slug) / "scenario.json")
                      .read_text(encoding="utf-8"))
    world = "\n".join(ln for ln in store.read("world-bible.md").splitlines()
                      if not ln.startswith("# ")).strip()
    files = _piece_files(store)
    return {
        "slug": slug,
        "title": meta.get("title", slug),
        "description": meta.get("description", ""),
        "premise": _split_premise_body(store.read("premise.md")),
        "introduction": store.opening_override(),
        "world": world,
        "pieces": {rel: [_entry_dict(e) for e in store.entries(rel)]
                   for rel in files},
    }


@router.put("/api/scenarios/{slug}/main")
def scenario_main(slug: str, body: dict):
    store = _scen_store(slug)
    premise = str(body.get("premise", "")).strip()
    intro = str(body.get("introduction", "")).strip()
    _write_premise_md(store, premise, intro)
    world = str(body.get("world", "")).strip()
    store.write("world-bible.md", "# World bible\n\n"
                + (world + "\n" if world else ""))
    lib.scenarios.update_meta(
        slug, title=str(body.get("title", "")).strip(),
        description=str(body.get("description", "")).strip())
    return {"ok": True}


@router.put("/api/scenarios/{slug}/pieces/{rel}")
def scenario_piece_put(slug: str, rel: str, body: dict):
    store = _scen_store(slug)
    if rel not in _piece_files(store):
        raise HTTPException(400, f"not a lore file of this world: {rel}")
    entry = _entry_from_dict(body.get("entry") or {})
    store.upsert_entry(rel, entry)
    old = str(body.get("old_slug", "")).strip()
    if old and old != entry.slug:
        store.remove_entry(rel, old)          # slug rename cleans the old one
    return {"ok": True, "slug": entry.slug}


@router.delete("/api/scenarios/{slug}/pieces/{rel}/{pslug}")
def scenario_piece_delete(slug: str, rel: str, pslug: str):
    store = _scen_store(slug)
    if rel not in _piece_files(store):
        raise HTTPException(400, f"not a lore file of this world: {rel}")
    if not store.remove_entry(rel, pslug):
        raise HTTPException(404, f"no such piece: {pslug}")
    return {"ok": True}


@router.post("/api/scenarios/{slug}/types")
def scenario_add_type(slug: str, body: dict):
    """Declare a custom lore type on a scenario (scenario.json custom_files)."""
    return {"file": _declare_custom_type(slug, str(body.get("name", "")))}


@router.delete("/api/scenarios/{slug}/types/{fname}")
def scenario_delete_type(slug: str, fname: str):
    """Remove a CUSTOM lore type: the declaration AND the file (its pieces go
    with it — the UI confirms first). Built-ins are never deletable."""
    _guard_slug(slug)
    if fname in _BASE_PIECE_FILES or not fname.endswith(".md") \
            or "/" in fname or "\\" in fname:
        raise HTTPException(400, f"'{fname}' is not a removable lore type")
    scen_dir = lib.scenarios.dir(slug)
    meta_path = scen_dir / "scenario.json"
    if not meta_path.exists():
        raise HTTPException(404, f"no such scenario: {slug}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    declared = meta.get("custom_files") or []
    if fname not in declared:
        raise HTTPException(404, f"'{fname}' is not declared on this world")
    meta["custom_files"] = [f for f in declared if f != fname]
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    try:
        (scen_dir / fname).unlink()
    except FileNotFoundError:
        pass
    return {"ok": True}


@router.get("/api/scenarios/{slug}/pieces/{rel}/export")
def scenario_section_export(slug: str, rel: str):
    """Download one section of a world as its raw Markdown file."""
    store = _scen_store(slug)
    if rel not in _piece_files(store):
        raise HTTPException(400, f"not a lore file of this world: {rel}")
    path = lib.scenarios.dir(slug) / rel
    if not path.exists():
        raise HTTPException(404, f"{rel} has no content yet")
    return FileResponse(path, filename=f"{slug}-{rel}",
                        media_type="text/markdown")


@router.get("/api/scenarios/{slug}/playable")
def scenario_playable(slug: str):
    """The world's playable characters (`playable: true` in characters.md) —
    what the new-story dialog offers as 'Play as'."""
    store = _scen_store(slug)
    out = [{"slug": e.slug, "title": e.title,
            "blurb": e.body.strip().splitlines()[0][:120]
            if e.body.strip() else ""}
           for e in store.entries("characters.md")
           if str(e.attrs.get("playable", "")).strip().lower()
           in ("true", "yes", "1", "on")]
    return {"playable": out}


@router.delete("/api/scenarios/{slug}")
def delete_scenario(slug: str):
    _guard_slug(slug)
    # Under the turn lock: this rmtree's a directory that live MemoryStores hold
    # as scenario_dir (rule inheritance + lore types resolve through it), so
    # deleting mid-turn pulled the floor out from under a running generation.
    with _exclusive():
        if not lib.scenarios.delete(slug):
            raise HTTPException(404, f"no such scenario: {slug}")
        _engines.clear()          # drop cached engines bound to the dead world
    return {"ok": True}
