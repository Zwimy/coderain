"""Import and export: saves, scenarios, character cards, defaults.

Every upload path is hostile input — see _guard_zip_bomb and _stash_upload."""
from __future__ import annotations

import io
import shutil
import uuid
import zipfile
from pathlib import Path
from fastapi import APIRouter
from fastapi import File
from fastapi import HTTPException
from fastapi import UploadFile
from fastapi.responses import FileResponse
from coderain import templates
from coderain.memory import Entry
from coderain.memory import _safe_zip_member

from .core import _EXPORT_DIR
from .core import _exclusive
from .core import _guard_slug
from .core import characters
from .core import lib
from .pieces import _declare_type_in
from .pieces import _scen_store

router = APIRouter()


@router.get("/api/saves/{slug}/export")
def export_save(slug: str):
    _guard_slug(slug)
    _EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        path = lib.saves.export(slug, _EXPORT_DIR / f"save-{slug}.zip")
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    return FileResponse(path, filename=f"save-{slug}.zip",
                        media_type="application/zip")

# Upload ceilings. Without these a tiny archive can write gigabytes: a 204 KB
# zip expanding to 200 MB was reproducible before this guard.
_MAX_UPLOAD_BYTES = 64 * 1024 * 1024        # compressed, per upload

_MAX_UNPACKED_BYTES = 256 * 1024 * 1024     # total decompressed, per archive

_MAX_COMPRESS_RATIO = 200                   # decompressed / compressed


def _guard_zip_bomb(packed_size: int, infos) -> None:
    """Reject an archive whose declared contents dwarf its compressed size."""
    unpacked = sum(max(0, getattr(i, "file_size", 0)) for i in infos)
    if unpacked > _MAX_UNPACKED_BYTES or unpacked > packed_size * _MAX_COMPRESS_RATIO:
        raise HTTPException(413, "archive expands too much (possible zip bomb)")


def _stash_upload(file: UploadFile) -> Path:
    """Persist a multipart upload to a temp .zip so the library import_ helpers
    (which take a path) can read it. The file keeps its original name inside a
    unique dir so the import's derived slug reads well (the 'save-'/'world-'
    export prefix is stripped). Caller removes the dir's parent.

    Streams in chunks with a hard ceiling, then refuses zip bombs, so an import
    can never fill the disk."""
    name = (file.filename or "").strip()
    if not name.lower().endswith(".zip"):
        raise HTTPException(400, "expected a .zip export")
    stem = Path(name).stem
    for pfx in ("save-", "world-", "user-"):
        if stem.startswith(pfx):
            stem = stem[len(pfx):]
    stem = "".join(c for c in stem if c.isalnum() or c in "-_ ") or "import"
    holder = _EXPORT_DIR / f"in-{uuid.uuid4().hex}"
    holder.mkdir(parents=True, exist_ok=True)
    dest = holder / f"{stem}.zip"
    try:
        total = 0
        with dest.open("wb") as out:
            while True:
                chunk = file.file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_UPLOAD_BYTES:
                    raise HTTPException(413, "upload too large (max 64 MB)")
                out.write(chunk)
        try:
            with zipfile.ZipFile(dest) as zf:
                _guard_zip_bomb(total, zf.infolist())
        except zipfile.BadZipFile:
            raise HTTPException(400, "not a valid .zip export")
    except BaseException:
        shutil.rmtree(holder, ignore_errors=True)   # caller never sees the path
        raise
    return dest


@router.post("/api/saves-import")
def import_save(file: UploadFile = File(...)):
    path = _stash_upload(file)
    try:
        slug = lib.saves.import_(path)
    except (ValueError, zipfile.BadZipFile) as e:
        raise HTTPException(400, str(e))
    finally:
        shutil.rmtree(path.parent, ignore_errors=True)
    return {"ok": True, "slug": slug}


@router.post("/api/cards-import")
def import_card(file: UploadFile = File(...)):
    """Import a SillyTavern/Tavern character card (PNG/JSON/charx) as a new World
    (ST-01): scenario→premise, first_mes→introduction, the character→a piece (+
    the reusable Pieces library), embedded lorebook→lore pieces."""
    from coderain import cards as cards_mod
    _MAX_UPLOAD = 32 * 1024 * 1024                        # 32 MB compressed ceiling
    raw = file.file.read(_MAX_UPLOAD + 1)
    if len(raw) > _MAX_UPLOAD:
        raise HTTPException(413, "card file too large (max 32 MB)")
    # .charx is a zip — the size cap above is compressed only, so a small file
    # could still expand to hundreds of MB. Check the declared unpacked size too.
    if zipfile.is_zipfile(io.BytesIO(raw)):
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            _guard_zip_bomb(len(raw), zf.infolist())
    try:
        card = cards_mod.parse_card(raw, file.filename or "")
    except ValueError as e:
        raise HTTPException(400, str(e))

    name = card["name"]
    sub = lambda t: cards_mod.substitute_macros(t, name)     # noqa: E731
    premise = sub(card["scenario"]) or sub(card["description"]) \
        or f"A story featuring {name}."
    intro = sub(card["first_mes"])
    desc_short = sub(card["description"])[:140]
    slug = lib.scenarios.create(name, premise, description=desc_short,
                                introduction=intro)
    store = _scen_store(slug)

    # The card's character → a characters.md piece (NPC).
    body = sub(card["description"])
    if card["personality"]:
        body += f"\n\n**Personality:** {sub(card['personality'])}"
    if card["mes_example"]:
        body += f"\n\n**Example dialogue:**\n{sub(card['mes_example'])}"
    store.upsert_entry("characters.md", Entry(
        title=name, slug=templates.slugify(name), aliases=[], importance=4,
        attrs={}, body=body.strip()))

    # Embedded lorebook → pieces in a declared custom 'lore' file.
    if card["lore"]:
        _declare_type_in(lib.scenarios.dir(slug), "scenario.json", "lore")
        store = _scen_store(slug)
        for e in card["lore"]:
            # Resolve {{char}}/{{user}} at import like every other card field, so
            # only intentional ST-20 macros survive to assemble time (no raw
            # {{char}} leak, and {{user}} matches the other fields).
            title = sub(e["title"])
            keys = [sub(k) for k in e["keys"]]
            store.upsert_entry("lore.md", Entry(
                title=title, slug=templates.slugify(title),
                aliases=keys, importance=3,
                attrs={"triggers": ", ".join(keys)} if keys else {},
                body=sub(e["content"])))

    # Also drop the character into the reusable Pieces library.
    try:
        characters.save({"name": name, "kind": "npc",
                         "description": sub(card["description"])})
    except Exception:  # noqa: BLE001 — library add is best-effort
        pass
    return {"ok": True, "slug": slug,
            "counts": {"lore": len(card["lore"]),
                       "greetings": len(card["alternate_greetings"])}}


@router.post("/api/scenarios-import")
def import_scenario(file: UploadFile = File(...)):
    path = _stash_upload(file)
    try:
        slug = lib.scenarios.import_(path)
    except (ValueError, zipfile.BadZipFile) as e:
        raise HTTPException(400, str(e))
    finally:
        shutil.rmtree(path.parent, ignore_errors=True)
    return {"ok": True, "slug": slug}


@router.post("/api/defaults-import")
def import_defaults(file: UploadFile = File(...)):
    """Restore a user-defaults.zip into the instructions dir (overwrites the
    files it contains; leaves others alone). Path-traversal guarded."""
    path = _stash_upload(file)
    try:
        # Under the turn lock: this rewrites instructions/*.md, which the engine
        # re-reads every turn — an import landing mid-generation would hand it a
        # torn rule file.
        with _exclusive(), zipfile.ZipFile(path) as z:
            for n in z.namelist():
                if not _safe_zip_member(lib.instructions_dir, n):  # traversal+absolute
                    continue
                target = lib.instructions_dir / n
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(n) as srcf, open(target, "wb") as outf:
                    shutil.copyfileobj(srcf, outf)
    except zipfile.BadZipFile as e:
        raise HTTPException(400, str(e))
    finally:
        shutil.rmtree(path.parent, ignore_errors=True)
    lib.outdated_rules = templates.seed_instructions(lib.instructions_dir)
    return {"ok": True}


@router.get("/api/scenarios/{slug}/export")
def export_scenario(slug: str):
    _guard_slug(slug)
    _EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        path = lib.scenarios.export(slug, _EXPORT_DIR / f"world-{slug}.zip")
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    return FileResponse(path, filename=f"world-{slug}.zip",
                        media_type="application/zip")
