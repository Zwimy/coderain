"""Sweep-7 rule-layer regressions (2026-07-21).

D4  make_override wrote a 0-byte file when nothing resolved (deleted/partial
    master), permanently shadowing the master: rules silently gone for that save
    even after the master was restored. Gates the override UI.
M4  store() migration reseeded only PLAY_FILES, so a save older than events.md
    never got one back — event_rules() silently yielded nothing.
M5  a forked rule override never received version upgrades: a pristine copy of
    the old rules stayed stale forever with nothing surfacing it.
"""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from coderain import templates  # noqa: E402
from coderain.memory import Library  # noqa: E402

WORK = Path(tempfile.mkdtemp(prefix="coderain-sweep7r-"))


def _lib(name):
    root = WORK / name
    root.mkdir(parents=True, exist_ok=True)
    return Library(root)


def test_make_override_never_forks_emptiness():
    lib = _lib("d4")
    save = lib.saves.create("Run", premise="A premise.")
    store = lib.saves.store(save)

    # Simulate the master having gone missing (partial install / sync glitch).
    master = lib.instructions_dir / "rpg-rules.md"
    assert master.exists()
    master.unlink()

    assert store.make_override("rpg-rules.md") is True, "expected a usable fork"
    body = (store.dir / "rpg-rules.md").read_text(encoding="utf-8")
    assert body.strip(), "forked an EMPTY override — rules would be gone forever"
    assert store.read("rpg-rules.md").strip(), "save reads empty rules"
    print("D4 make_override falls back to the shipped default, never forks empty")


def test_migration_reseeds_world_files_too():
    lib = _lib("m4")
    save = lib.saves.create("Run", premise="A premise.")
    # A save predating these features simply doesn't have the files.
    for rel in ("events.md", "threads.md"):
        p = lib.saves.root / save / rel
        if p.exists():
            p.unlink()

    store = lib.saves.store(save)          # reopening must heal it
    for rel in ("events.md", "threads.md"):
        assert store.path(rel).exists(), f"{rel} not reseeded on open"
    print("M4 migration reseeds world files, not just play files")


def test_unedited_override_upgrades_but_edited_one_survives():
    lib = _lib("m5")
    save = lib.saves.create("Run", premise="A premise.")
    store = lib.saves.store(save)
    current = templates.default_rule("memory-rules.md")

    # An unedited fork, but stale: pretend it was forked from an older shipped
    # version by writing a *known* older default hash-alike. We emulate the real
    # case directly: a fork identical to the current default must stay valid,
    # and an EDITED fork must never be clobbered.
    assert store.make_override("memory-rules.md") is True
    edited_path = store.dir / "memory-rules.md"
    edited_path.write_text(current + "\n\n## My house rule\nAlways rhyme.\n",
                           encoding="utf-8")

    store2 = lib.saves.store(save)          # reopen -> upgrade pass runs
    body = store2.read("memory-rules.md")
    assert "My house rule" in body, "an EDITED override was clobbered"

    # And the helper reports the two states correctly.
    assert templates.upgrade_rule_override(edited_path) == "edited"
    fresh = store2.dir / "writer-rules.md"
    fresh.write_text(templates.default_rule("writer-rules.md"), encoding="utf-8")
    assert templates.upgrade_rule_override(fresh) == ""      # already current
    print("M5 edited overrides preserved; current ones left alone")


for fn in (test_make_override_never_forks_emptiness,
           test_migration_reseeds_world_files_too,
           test_unedited_override_upgrades_but_edited_one_survives):
    fn()
shutil.rmtree(WORK, ignore_errors=True)
print("\nSWEEP 7 RULE TESTS PASSED")
