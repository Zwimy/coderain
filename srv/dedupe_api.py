"""Duplicates: entries that are one character, place or item written under two slugs or two names, the merge and its undo (D-030, D-038, D-065).

`python -m coderain.dedupe` finds and merges them, and the app had no way to. A story played through a small local model collects second and
third entries for one person ("Dame Vesper", "Vesper", "Vesper Ann-Marie"), and each is a separate character to the memory, the card and the
Writer. This is that tool over HTTP, with the same rules and one addition: a restore, because a merge rewrites a registry file that a fold
wrote, a fold is one-way, and the only safe way to offer a merge is one that can be taken back.

GET  /api/saves/{slug}/duplicates           what could be merged: entries with the same whole name (safe to merge for the author's
                                            confirmation) and entries that MAY be one character (the author's call), plus the backups
POST /api/saves/{slug}/duplicates/merge     {"rel", "keep", "drop": [slugs]} merges exactly those; {"auto": true} merges the same-name groups.
                                            Backs up every registry it will change first. A refused merge writes nothing (400).
POST /api/saves/{slug}/duplicates/restore   {"backup": "<stamp>"} puts that backup's registries back, after backing up what is there now
                                            (so a restore can be restored too)

A merge takes a lock like every other save-changing call (409 while a turn is generating). It changes the registries only: the canon ledger
under <save>/canon/ is derived and keeps the old entities until it is rebuilt, which the response says (`canon`).
"""
from __future__ import annotations

import re
import shutil
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException

from coderain.dedupe import BACKUP_DIR, apply_merges, explicit_group, plan_for_store, similar_names, _player_names
from coderain.memory import ENTITY_FILES

from .core import _engine, _exclusive

router = APIRouter()
_STAMP = re.compile(r"^\d{8}-\d{6}(-\d+)?$")           # what apply_merges names a backup; anything else is not ours to open


def _backups(store) -> list[str]:
    root = Path(store.dir) / BACKUP_DIR
    if not root.is_dir():
        return []
    return sorted((d.name for d in root.iterdir() if d.is_dir() and _STAMP.match(d.name)), reverse=True)


def _view(store) -> dict:
    titles = {rel: {e.slug: e.title for e in store.entries(rel)} for rel in ENTITY_FILES}
    same = [{"rel": g.rel, "keep": {"slug": g.keep, "title": titles[g.rel].get(g.keep, g.keep)},
             "drop": [{"slug": s, "title": titles[g.rel].get(s, s)} for s in g.drop], "why": g.why}
            for g in plan_for_store(store)]
    regs = {rel: store.entries(rel) for rel in sorted(ENTITY_FILES)}
    possible = []
    for rel, es in similar_names(regs, skip_names=_player_names(store)):
        keep = max(es, key=lambda e: (len(e.body), len(e.title)))
        possible.append({"rel": rel, "keep": keep.slug,
                         "entries": [{"slug": e.slug, "title": e.title, "chars": len(e.body)} for e in es]})
    return {"same_name": same, "possible": possible, "backups": _backups(store),
            "canon": (Path(store.dir) / "canon").exists()}


@router.get("/api/saves/{slug}/duplicates")
def duplicates_view(slug: str):
    return _view(_engine(slug).store)


@router.post("/api/saves/{slug}/duplicates/merge")
def duplicates_merge(slug: str, body: dict):
    store = _engine(slug).store
    if body.get("auto") is True:
        groups = plan_for_store(store)
        if not groups:
            raise HTTPException(400, "there is nothing with the same name to merge")
    else:
        keep, drop, rel = body.get("keep"), body.get("drop"), body.get("rel", "characters.md")
        if not isinstance(keep, str) or not isinstance(drop, list) or not all(isinstance(x, str) for x in drop) or not isinstance(rel, str):
            raise HTTPException(400, "give rel, keep (a slug) and drop (a list of slugs), or auto: true")
        try:
            groups = [explicit_group(store, keep, drop, rel)]
        except ValueError as e:
            raise HTTPException(400, str(e))
    with _exclusive():
        result = apply_merges(store, groups)
    return {"result": result, **_view(store)}


@router.post("/api/saves/{slug}/duplicates/restore")
def duplicates_restore(slug: str, body: dict):
    store = _engine(slug).store
    stamp = body.get("backup")
    if not isinstance(stamp, str) or not _STAMP.match(stamp):
        raise HTTPException(400, "backup must be one of the stamps listed")
    src = Path(store.dir) / BACKUP_DIR / stamp
    if not src.is_dir():
        raise HTTPException(404, f"no such backup: {stamp}")
    files = [p for p in sorted(src.iterdir()) if p.is_file() and p.name in ENTITY_FILES]
    if not files:
        raise HTTPException(400, "that backup holds no registry to put back")
    with _exclusive():
        # back up what is there NOW first, so the restore itself can be undone
        now = time.strftime("%Y%m%d-%H%M%S")
        before = Path(store.dir) / BACKUP_DIR / now
        for n in range(2, 1000):
            if not before.exists():
                break
            before = Path(store.dir) / BACKUP_DIR / f"{now}-{n}"
        before.mkdir(parents=True, exist_ok=False)
        for p in files:
            if (Path(store.dir) / p.name).exists():
                shutil.copy2(Path(store.dir) / p.name, before / p.name)
            shutil.copy2(p, Path(store.dir) / p.name)
    return {"restored": [p.name for p in files], "backed_up_as": before.name, **_view(store)}
