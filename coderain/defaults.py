"""User defaults: the rule files and skeletons every NEW world and story inherits.

Two kinds, which behave differently and are easy to confuse:

- a RULE file lives directly in `instructions/` and the engine re-reads it EVERY
  turn, so it is "customized" when its text differs from the shipped one, and
  reverting rewrites it with the shipped text.
- a SKELETON lives in `instructions/defaults/` and is only read when seeding a
  new story, so it is "customized" merely by existing, and reverting deletes it.

This lived inline in srv/defaults.py, which meant the desktop app could not show
or edit any of it — a user who only ever opens the desktop build could not change
the templates their stories are built from.
"""
from __future__ import annotations

from . import templates


class DefaultError(ValueError):
    """A defaults operation the engine refuses (an unknown or non-defaultable
    name). Transport-agnostic: the HTTP layer makes it a 404, the desktop UI
    shows it in the dialog."""


def defaultable_names() -> list[str]:
    """Every file a user may override, rules first."""
    return list(templates.RULE_FILES) + list(templates.USER_DEFAULTABLE)


def default_kind(name: str) -> str:
    return "rule" if name in templates.RULE_FILES else "skeleton"


def _check(name: str) -> str:
    if name not in defaultable_names():
        raise DefaultError(f"not a user-defaultable file: {name}")
    return default_kind(name)


def list_defaults(lib) -> list[dict]:
    """Every defaultable file with whether the user has changed it."""
    out = []
    for name in defaultable_names():
        kind = default_kind(name)
        if kind == "rule":
            p = lib.instructions_dir / name
            customized = (p.exists() and p.read_text(encoding="utf-8")
                          != templates.default_rule(name))
        else:
            customized = (lib.instructions_dir / "defaults" / name).exists()
        out.append({"name": name, "kind": kind, "customized": customized})
    return out


def read_default(lib, name: str) -> str:
    """The user's version if there is one, else the shipped text."""
    if _check(name) == "rule":
        p = lib.instructions_dir / name
        return p.read_text(encoding="utf-8") if p.exists() \
            else templates.default_rule(name)
    return templates.user_default(name, lib.instructions_dir)


def write_default(lib, name: str, text: str) -> None:
    """Save a user override.

    Callers that can race a live turn must hold the turn lock: the engine
    re-reads the rule files every turn, so a save landing mid-generation could
    hand it a half-written rule file.
    """
    if _check(name) == "rule":
        (lib.instructions_dir / name).write_text(str(text), encoding="utf-8")
        lib.outdated_rules = templates.seed_instructions(lib.instructions_dir)
        return
    d = lib.instructions_dir / "defaults"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(str(text), encoding="utf-8")


def revert_default(lib, name: str) -> str:
    """Drop the user override and return whatever the file now reads as."""
    if _check(name) == "rule":
        (lib.instructions_dir / name).write_text(
            templates.default_rule(name), encoding="utf-8")
        lib.outdated_rules = templates.seed_instructions(lib.instructions_dir)
    else:
        try:
            (lib.instructions_dir / "defaults" / name).unlink()
        except FileNotFoundError:
            pass          # already shipped-default; reverting twice is not an error
    return read_default(lib, name)
