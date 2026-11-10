"""Isolation for the harness: never touch the real install.

CLAUDE.md records why this module exists. `saves/` and `.env` in the repo root
are live user data; a browser test once overwrote a real API key and it was not
recoverable. The rules the harness follows:

  * `coderain.config.ROOT` is resolved once, at import, from CODERAIN_HOME. So
    the home must be set BEFORE anything imports coderain, and the harness
    refuses to continue if the resolved home is the repo root.
  * A real save is only ever READ. It is copied into the isolated home and all
    probing happens on the copy. SaveLibrary.store() writes migration files into
    whatever it opens, which is exactly why the source must never be opened.
  * Before and after the copy the source is fingerprinted. If it changed in
    between (the app is running and wrote to it) the copy is rejected rather than
    measured, because a half-written copy would produce a false baseline.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parent.parent

# What a copy leaves behind. Snapshots are large and no probe reads them; the
# vector index is derived data and would tie a probe to a live embedder.
_SKIP_DIRS = {".snapshots"}
_SKIP_SUFFIXES = (".db", ".db-wal", ".db-shm", ".tmp")


class UnsafeHome(RuntimeError):
    """The harness was about to run against the real install."""


class SourceChanged(RuntimeError):
    """The source save changed while it was being copied."""


def isolated_home(prefix: str = "soak-") -> Path:
    """Create a temp CODERAIN_HOME and point the environment at it.

    Must run before coderain is imported. If it already was, the home it
    resolved cannot be changed, so say so instead of silently using it.
    """
    if "coderain.config" in sys.modules:
        raise UnsafeHome(
            "coderain was imported before the isolated home was set, so its "
            "home is already fixed; start the harness in a fresh process")
    home = Path(tempfile.mkdtemp(prefix=prefix))
    os.environ["CODERAIN_HOME"] = str(home)
    return home


def assert_isolated(root: Path | None = None) -> Path:
    """Refuse to continue unless coderain resolved a home that is not the repo.

    `root` exists so the guard itself can be tested; normally it is read from
    the live coderain.config.
    """
    if root is None:
        from coderain import config
        root = config.ROOT
    resolved = Path(root).resolve()
    if resolved == REPO_ROOT:
        raise UnsafeHome(
            f"coderain resolved its home to the repo root ({resolved}), which "
            "holds live saves and .env. Set CODERAIN_HOME to a temp dir first.")
    return resolved


def _skipped(path: Path, base: Path) -> bool:
    rel = path.relative_to(base)
    return (any(part in _SKIP_DIRS for part in rel.parts)
            or path.name.endswith(_SKIP_SUFFIXES))


def fingerprint(src: Path) -> dict[str, str]:
    """sha256 of every file a copy would include, keyed by relative posix path."""
    src = Path(src)
    out: dict[str, str] = {}
    for p in sorted(src.rglob("*")):
        if not p.is_file() or _skipped(p, src):
            continue
        out[p.relative_to(src).as_posix()] = hashlib.sha256(
            p.read_bytes()).hexdigest()
    return out


def _ignore(directory: str, names: list[str]) -> set[str]:
    return {n for n in names
            if n in _SKIP_DIRS or n.endswith(_SKIP_SUFFIXES)}


def copy_save(src: Path, home: Path, slug: str | None = None,
              rules_from: Path | None = None,
              _between: Callable[[], None] | None = None) -> str:
    """Copy a save into `home/saves/<slug>` and verify the source was untouched.

    `rules_from` optionally copies a global `instructions/` directory so the
    prompt carries the author's own writer rules rather than the shipped ones.
    `_between` is a test seam that runs after the copy and before the second
    fingerprint, to simulate the app writing mid-copy.
    """
    src, home = Path(src).resolve(), Path(home).resolve()
    if not (src / "meta.json").exists():
        raise ValueError(f"{src} is not a save (no meta.json)")
    if home == REPO_ROOT:
        raise UnsafeHome("refusing to copy a save into the repo root")
    if home == src or src in home.parents:
        raise UnsafeHome("the isolated home must not live inside the source save")
    slug = slug or src.name
    dst = home / "saves" / slug
    if dst.exists():
        raise FileExistsError(f"{dst} already exists")

    before = fingerprint(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst, ignore=_ignore)
    if rules_from is not None and Path(rules_from).is_dir():
        shutil.copytree(rules_from, home / "instructions", dirs_exist_ok=True)
    if _between is not None:
        _between()
    after = fingerprint(src)
    if before != after:
        changed = sorted(k for k in set(before) | set(after)
                         if before.get(k) != after.get(k))
        shutil.rmtree(dst, ignore_errors=True)
        raise SourceChanged(
            f"{len(changed)} file(s) changed while copying (is the app "
            f"running?): {', '.join(changed[:4])}")
    return slug
