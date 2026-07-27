"""User defaults: the rule files and skeletons a new story inherits."""
from __future__ import annotations

import zipfile
from fastapi import APIRouter
from fastapi import HTTPException
from fastapi.responses import FileResponse
from coderain import templates
from coderain.profiles import STAT_NAMES

from .core import _EXPORT_DIR
from .core import _exclusive
from .core import characters
from .core import lib

router = APIRouter()


# ---------- user defaults (Library section) ----------
def _default_kind(name: str) -> str:
    return "rule" if name in templates.RULE_FILES else "skeleton"


def _defaultable(name: str) -> None:
    if name not in list(templates.RULE_FILES) + templates.USER_DEFAULTABLE:
        raise HTTPException(404, f"not a user-defaultable file: {name}")


@router.get("/api/defaults")
def list_defaults():
    out = []
    for name in list(templates.RULE_FILES) + templates.USER_DEFAULTABLE:
        kind = _default_kind(name)
        if kind == "rule":
            p = lib.instructions_dir / name
            customized = p.exists() and \
                p.read_text(encoding="utf-8") != templates.default_rule(name)
        else:
            customized = (lib.instructions_dir / "defaults" / name).exists()
        out.append({"name": name, "kind": kind, "customized": customized})
    return {"defaults": out}


@router.get("/api/defaults/{name}")
def get_default(name: str):
    _defaultable(name)
    if _default_kind(name) == "rule":
        p = lib.instructions_dir / name
        text = p.read_text(encoding="utf-8") if p.exists() \
            else templates.default_rule(name)
    else:
        text = templates.user_default(name, lib.instructions_dir)
    return {"name": name, "text": text}


@router.put("/api/defaults/{name}")
def put_default(name: str, body: dict):
    _defaultable(name)
    text = str(body.get("text", ""))
    # Under the turn lock: the engine re-reads the rule files EVERY turn, so a
    # save landing mid-generation could hand it a half-written rule file.
    with _exclusive():
        if _default_kind(name) == "rule":
            (lib.instructions_dir / name).write_text(text, encoding="utf-8")
            lib.outdated_rules = templates.seed_instructions(lib.instructions_dir)
        else:
            d = lib.instructions_dir / "defaults"
            d.mkdir(parents=True, exist_ok=True)
            (d / name).write_text(text, encoding="utf-8")
    return {"ok": True}


@router.post("/api/defaults/{name}/revert")
def revert_default(name: str):
    _defaultable(name)
    with _exclusive():                      # same live-rule race as put_default
        if _default_kind(name) == "rule":
            (lib.instructions_dir / name).write_text(
                templates.default_rule(name), encoding="utf-8")
            lib.outdated_rules = templates.seed_instructions(lib.instructions_dir)
        else:
            try:
                (lib.instructions_dir / "defaults" / name).unlink()
            except FileNotFoundError:
                pass
    return get_default(name)


@router.get("/api/defaults-export")
def export_defaults():
    import zipfile
    _EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    dest = _EXPORT_DIR / "user-defaults.zip"
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(lib.instructions_dir.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(lib.instructions_dir).as_posix())
    return FileResponse(dest, filename="user-defaults.zip",
                        media_type="application/zip")


# ---------- characters ----------
@router.get("/api/characters")
def list_characters():
    return {"characters": characters.list(), "stats": STAT_NAMES}


@router.post("/api/characters")
def save_character(body: dict):
    return characters.save(body if isinstance(body, dict) else {})


@router.delete("/api/characters/{cid}")
def delete_character(cid: str):
    if not characters.delete(cid):
        raise HTTPException(404, "no such character")
    return {"ok": True}
