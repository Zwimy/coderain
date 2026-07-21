"""Sweep-7 data-integrity regressions (2026-07-21).

D1  an imported save bound to ANY local world with a colliding slug (slugs are
    title-derived, so "Fantasy Adventure" collides), silently inheriting that
    stranger's rule overrides and lore-type declarations.
D2  scenario-declared custom lore types were read live from scenario.json and
    never copied into the save, so editing or deleting the world orphaned the
    save's populated registry: entries still on disk, invisible to recall,
    the writer, the indexer and the editor.
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from coderain.memory import Library  # noqa: E402

WORK = Path(tempfile.mkdtemp(prefix="coderain-sweep7-"))


def _lib(name):
    root = WORK / name
    root.mkdir(parents=True, exist_ok=True)
    return Library(root)


def _world_with_custom_type(lib, title="Elf World"):
    slug = lib.scenarios.create(title, "A premise about elves.")
    d = lib.scenarios.dir(slug)
    meta = json.loads((d / "scenario.json").read_text(encoding="utf-8"))
    meta["custom_files"] = ["races.md"]
    (d / "scenario.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    (d / "races.md").write_text(
        "# Races\n\n## Sylvan  {#sylvan}\nimportance: 4\n\nTall forest folk.\n",
        encoding="utf-8")
    return slug


# --- D2: custom lore types survive the world being edited or deleted --------
def test_custom_types_copied_into_save_at_creation():
    lib = _lib("d2")
    scen = _world_with_custom_type(lib)
    save = lib.saves.create("Run One", scenario_slug=scen)

    # copied at creation, not lazily on first open
    assert (lib.saves.root / save / "races.md").exists(), "races.md not copied in"
    meta = json.loads((lib.saves.root / save / "meta.json").read_text(encoding="utf-8"))
    assert "races.md" in meta.get("custom_files", []), meta
    print("D2 custom type copied + declared in save meta at creation")


def test_custom_types_survive_scenario_deletion():
    lib = _lib("d2b")
    scen = _world_with_custom_type(lib)
    save = lib.saves.create("Run Two", scenario_slug=scen)
    lib.scenarios.delete(scen)

    store = lib.saves.store(save)
    assert "races.md" in store.custom_files(), store.custom_files()
    assert "races.md" in store.index_files(), "custom type dropped from the index"
    entries = store.entries("races.md")
    assert [e.slug for e in entries] == ["sylvan"], entries
    print("D2 custom type still declared, indexed and readable after world delete")


# --- D1: an imported save must not bind to a same-slug stranger -------------
def test_import_unlinks_from_a_colliding_foreign_world():
    src = _lib("d1-src")
    scen = _world_with_custom_type(src, "Fantasy Adventure")
    save = src.saves.create("My Run", scenario_slug=scen)
    zip_path = src.saves.export(save, WORK / "save-my-run.zip")

    # A different machine that happens to have its own world of the same name.
    dst = _lib("d1-dst")
    other = dst.scenarios.create("Fantasy Adventure", "A completely different world.")
    assert other == scen, f"fixture needs a slug collision: {other} vs {scen}"
    # ...carrying a rule override the imported save must NOT inherit.
    (dst.scenarios.dir(other) / "writer-rules.md").write_text(
        "# EVIL OVERRIDE\nWrite everything in all caps.\n", encoding="utf-8")

    imported = dst.saves.import_(zip_path)
    meta = json.loads((dst.saves.root / imported / "meta.json").read_text(encoding="utf-8"))
    assert meta.get("scenario") == "", f"bound to a stranger's world: {meta}"
    assert meta.get("scenario_unlinked") == scen, meta

    store = dst.saves.store(imported)
    assert "EVIL OVERRIDE" not in store.read("writer-rules.md"), \
        "imported save read a stranger's rule override"
    assert store.layer_of("writer-rules.md") != "scenario", store.layer_of("writer-rules.md")
    print("D1 colliding import unlinked; stranger's rules NOT inherited")


def test_import_keeps_the_link_when_it_is_really_the_same_world():
    """The guard must not unlink a genuine round-trip."""
    lib = _lib("d1-same")
    scen = _world_with_custom_type(lib, "Round Trip World")
    save = lib.saves.create("Trip", scenario_slug=scen)
    zip_path = lib.saves.export(save, WORK / "save-trip.zip")

    imported = lib.saves.import_(zip_path)
    meta = json.loads((lib.saves.root / imported / "meta.json").read_text(encoding="utf-8"))
    assert meta.get("scenario") == scen, f"same-world import wrongly unlinked: {meta}"
    assert "scenario_unlinked" not in meta, meta
    print("D1 genuine same-world import keeps its link")


for fn in (test_custom_types_copied_into_save_at_creation,
           test_custom_types_survive_scenario_deletion,
           test_import_unlinks_from_a_colliding_foreign_world,
           test_import_keeps_the_link_when_it_is_really_the_same_world):
    fn()
shutil.rmtree(WORK, ignore_errors=True)
print("\nSWEEP 7 DATA TESTS PASSED")
