"""Entry/piece/custom-type helpers shared by the scenario builder and
the in-play world editor.

A scenario and a save hold the same shape of Markdown (characters.md,
locations.md, ...), so both editors run through these."""
from __future__ import annotations

import json
from pathlib import Path
from fastapi import HTTPException
from coderain import templates
from coderain.generator import PIECE_KINDS
from coderain.generator import _split_premise_body
from coderain.memory import Entry
from coderain.memory import MemoryStore

from .core import _guard_slug
from .core import lib

# ---------- scenarios (FictionLab shape: name + premise + introduction) ----
_BASE_PIECE_FILES = ["characters.md", "locations.md", "items.md",
                     "factions.md", "threads.md", "events.md"]


def _scen_store(slug: str) -> MemoryStore:
    _guard_slug(slug)
    scen_dir = lib.scenarios.dir(slug)
    if not (scen_dir / "scenario.json").exists():
        raise HTTPException(404, f"no such scenario: {slug}")
    # scenario_dir = itself so custom lore types (scenario.json) resolve
    return MemoryStore(scen_dir, None, scen_dir)


def _piece_files(store: MemoryStore) -> list[str]:
    return _BASE_PIECE_FILES + [f for f in store.custom_files()
                                if f not in _BASE_PIECE_FILES]


def _entry_dict(e: Entry) -> dict:
    return {"title": e.title, "slug": e.slug, "aliases": e.aliases,
            "importance": e.importance, "attrs": e.attrs, "body": e.body}


def _entry_from_dict(d: dict) -> Entry:
    from coderain.templates import slugify
    title = str(d.get("title", "")).strip()
    slug = slugify(str(d.get("slug", "")).strip() or title)
    if not title or not slug:
        raise HTTPException(400, "a piece needs at least a title")
    try:
        imp = max(1, min(5, int(d.get("importance", 3))))
    except (TypeError, ValueError):
        imp = 3
    raw_attrs = d.get("attrs")
    attrs = {str(k): str(v) for k, v in raw_attrs.items()
             if str(v).strip()} if isinstance(raw_attrs, dict) else {}
    raw_aliases = d.get("aliases")
    aliases = [str(a).strip() for a in raw_aliases
               if str(a).strip()] if isinstance(raw_aliases, list) else []
    return Entry(title=title, slug=slug, aliases=aliases, importance=imp,
                 attrs=attrs, body=str(d.get("body", "")).strip())


def _scenario_context(store: MemoryStore) -> str:
    """What the per-field AI assists see: the premise (and tone lives in it)."""
    return _split_premise_body(store.read("premise.md"))


def _declare_custom_type(slug: str, name: str) -> str:
    """Declare (and seed) a custom lore type on a scenario. Returns the
    filename; raises HTTPException on bad names / missing scenario."""
    _guard_slug(slug)
    import re as _re
    base = str(name).strip().removesuffix(".md")
    if not _re.search(r"[A-Za-z0-9]", base):
        raise HTTPException(400, f"not a usable lore file name: {name!r}")
    from coderain.memory import _RESERVED_MD
    fname = templates.slugify(base) + ".md"
    if fname in _RESERVED_MD or fname in _BASE_PIECE_FILES:
        raise HTTPException(400, f"'{fname}' is a built-in file")
    scen_dir = lib.scenarios.dir(slug)
    meta_path = scen_dir / "scenario.json"
    if not meta_path.exists():
        raise HTTPException(404, f"no such scenario: {slug}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    declared = meta.setdefault("custom_files", [])
    if fname not in declared:
        declared.append(fname)
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    f = scen_dir / fname
    if not f.exists():
        label = fname.removesuffix(".md").replace("-", " ").title()
        f.write_text(f"# {label}\n\n{label} — custom lore registry.\n",
                     encoding="utf-8")
    return fname


# ---------- per-save world editing (same builder UI, live save files) --------
# A save owns its OWN copies of the world files (they diverge from the scenario
# as the story evolves). These mirror the scenario builder endpoints but read
# and write the loaded save, so the player can edit characters/locations/etc.
# mid-play. The engine reads the Markdown fresh each turn, so edits go live.
def _save_store(slug: str) -> MemoryStore:
    _guard_slug(slug)
    try:
        return lib.saves.store(slug)
    except FileNotFoundError:
        raise HTTPException(404, f"no such save: {slug}")


def _declare_type_in(base_dir: Path, meta_name: str, name: str) -> str:
    """Declare (+seed) a custom lore type by writing its file and adding it to
    the target's `custom_files` (scenario.json OR a save's meta.json)."""
    import re as _re
    base = str(name).strip().removesuffix(".md")
    if not _re.search(r"[A-Za-z0-9]", base):
        raise HTTPException(400, f"not a usable lore file name: {name!r}")
    from coderain.memory import _RESERVED_MD
    fname = templates.slugify(base) + ".md"
    if fname in _RESERVED_MD or fname in _BASE_PIECE_FILES:
        raise HTTPException(400, f"'{fname}' is a built-in file")
    meta_path = base_dir / meta_name
    if not meta_path.exists():
        raise HTTPException(404, "no such target")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    declared = meta.setdefault("custom_files", [])
    # Clear the delete tombstone, or custom_files() keeps filtering the type
    # back out: the re-add returned 200, wrote the file and declared the name,
    # and the engine ignored it forever — never indexed, never activated, and
    # 400 from every /world/pieces route. MemoryStore.add_custom_file already
    # does this; the route the SPA actually calls did not.
    tomb = [f for f in (meta.get("removed_files") or []) if f != fname]
    changed = tomb != (meta.get("removed_files") or [])
    if changed:
        meta["removed_files"] = tomb
    if fname not in declared:
        declared.append(fname)
        changed = True
    if changed:
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    f = base_dir / fname
    if not f.exists():
        label = fname.removesuffix(".md").replace("-", " ").title()
        f.write_text(f"# {label}\n\n{label} — custom lore registry.\n",
                     encoding="utf-8")
    return fname


def _delete_type_in(base_dir: Path, meta_name: str, fname: str) -> dict:
    if fname in _BASE_PIECE_FILES or not fname.endswith(".md") \
            or "/" in fname or "\\" in fname:
        raise HTTPException(400, f"'{fname}' is not a removable lore type")
    meta_path = base_dir / meta_name
    if not meta_path.exists():
        raise HTTPException(404, "no such target")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    declared = meta.get("custom_files") or []
    if fname not in declared and not (base_dir / fname).exists():
        raise HTTPException(404, f"'{fname}' is not declared here")
    meta["custom_files"] = [f for f in declared if f != fname]
    # Tombstone. A save reads its scenario's custom_files LIVE, and
    # SaveLibrary.store() re-materializes every name custom_files() returns — so
    # removing the name from this meta alone put the type straight back on the
    # next open, as an empty stub over the registry the player had filled in.
    # The delete has to be recorded, not just un-declared.
    meta["removed_files"] = [f for f in (meta.get("removed_files") or [])
                             if f != fname] + [fname]
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    try:
        (base_dir / fname).unlink()
    except FileNotFoundError:
        pass
    return {"ok": True}


# ---------- generic piece library (locations/items/factions/…) ----------
def _kind_to_rel(kind: str) -> str:
    info = PIECE_KINDS.get(kind)
    return info[3] if info else templates.slugify(kind) + ".md"

_REL_TO_KIND = {info[3]: kind for kind, info in PIECE_KINDS.items()}


def _rel_to_kind(rel: str) -> str:
    return _REL_TO_KIND.get(rel, rel.removesuffix(".md"))
