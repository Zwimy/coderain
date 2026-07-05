"""Rules-migration tests: an app update that changes a rule master must reach an
already-seeded instructions/ for UNEDITED masters, while never clobbering a user's
edits. Covers the pre-ship footgun from HANDOFF (stale rpg-rules after a rename).
"""
import os, sys, shutil, tempfile, json
sys.path.insert(0, r"F:\Seven\StoryEngine")
from pathlib import Path
from coderain import templates as T
from coderain.memory import Library

root = Path(tempfile.gettempdir()) / "se_rules_mig"
if root.exists(): shutil.rmtree(root)
inst = root / "instructions"

WR = "writer-rules.md"
DEFAULT = T._RULE_CONTENT[WR]

# 1) Fresh seed writes all masters + a ledger recording their current hashes.
out = T.seed_instructions(inst)
assert out == [], out
for r in T.RULE_FILES:
    assert (inst / r).exists(), r
ledger = json.loads((inst / T.RULES_LEDGER).read_text(encoding="utf-8"))
assert ledger["hashes"][WR] == T._sha(DEFAULT)
print("1) fresh seed writes masters + version ledger")

# 2) App update to an UNEDITED master propagates on next seed.
NEWTEXT = DEFAULT + "\n## New shipped section\n- added by an app update.\n"
orig = dict(T._RULE_CONTENT)
try:
    T._RULE_CONTENT[WR] = NEWTEXT               # simulate the code-side default change
    out = T.seed_instructions(inst)
    assert out == [], out
    assert (inst / WR).read_text(encoding="utf-8") == NEWTEXT, "unedited master was NOT upgraded"
    print("2) unedited master auto-upgrades when the shipped default changes")

    # 3) A USER-EDITED master is preserved, and reported as outdated.
    EDIT = "# My custom writer rules\n- keep it noir.\n"
    (inst / WR).write_text(EDIT, encoding="utf-8")
    T._RULE_CONTENT[WR] = NEWTEXT + "\n## Even newer\n"   # another update ships
    out = T.seed_instructions(inst)
    assert WR in out, ("user edit not reported outdated", out)
    assert (inst / WR).read_text(encoding="utf-8") == EDIT, "user edit was clobbered!"
    print("3) user-edited master preserved + flagged outdated")
finally:
    T._RULE_CONTENT.clear(); T._RULE_CONTENT.update(orig)

# 4) Legacy install (no ledger) holding a KNOWN prior default auto-upgrades; a
#    legacy install holding a user edit is preserved.
legacy = root / "legacy"; legacy.mkdir(parents=True)
OLD = "# Old shipped writer rules v0\n- the pre-rename default.\n"
orig = dict(T._RULE_CONTENT); orig_hashes = {k: set(v) for k, v in T._SHIPPED_RULE_HASHES.items()}
try:
    T._SHIPPED_RULE_HASHES[WR].add(T._sha(OLD))   # register OLD as a shipped default
    # (a) unedited old default, no ledger -> upgrade to current
    (legacy / WR).write_text(OLD, encoding="utf-8")
    for r in T.RULE_FILES:
        if r != WR: (legacy / r).write_text(T._RULE_CONTENT[r], encoding="utf-8")
    out = T.seed_instructions(legacy)
    assert (legacy / WR).read_text(encoding="utf-8") == T._RULE_CONTENT[WR], "legacy old-default not upgraded"
    assert WR not in out
    print("4a) legacy unedited old-default upgrades (no ledger needed)")

    # (b) unknown user edit, no ledger -> preserved + flagged
    legacy2 = root / "legacy2"; legacy2.mkdir()
    (legacy2 / WR).write_text("# hand-written, never shipped\n", encoding="utf-8")
    out = T.seed_instructions(legacy2)
    assert WR in out and (legacy2 / WR).read_text(encoding="utf-8").startswith("# hand-written")
    print("4b) legacy unknown edit preserved + flagged outdated")
finally:
    T._RULE_CONTENT.clear(); T._RULE_CONTENT.update(orig)
    T._SHIPPED_RULE_HASHES.clear(); T._SHIPPED_RULE_HASHES.update(orig_hashes)

# 5) Library exposes outdated_rules and a reset path; reset restores the default.
lib_root = root / "lib"
lib = Library(lib_root)
assert lib.outdated_rules == [], lib.outdated_rules
(lib.instructions_dir / WR).write_text("# drifted\n", encoding="utf-8")
lib2 = Library(lib_root)                              # re-open: migration runs again
assert WR in lib2.outdated_rules, lib2.outdated_rules
reset = lib2.reset_all_rules()
assert WR in reset
assert (lib2.instructions_dir / WR).read_text(encoding="utf-8") == T._RULE_CONTENT[WR]
assert lib2.outdated_rules == []
print("5) Library flags outdated rules; reset_all_rules restores shipped defaults")

# 6) Per-store reset_rule restores default at the effective layer; a save override is
#    reset in place (still an override), leaving the global master untouched.
slug = lib2.create_story("Mig", "a premise")
store = lib2.store(slug)
store.make_override(WR)
store.write(WR, "# save-local custom\n")
assert store.layer_of(WR) == "save"
assert store.reset_rule(WR)
assert store.read(WR) == T._RULE_CONTENT[WR]          # override content reset to default
assert store.layer_of(WR) == "save"                    # but STILL a save override
assert (lib2.instructions_dir / WR).read_text(encoding="utf-8") == T._RULE_CONTENT[WR]  # global intact
print("6) reset_rule restores default at the effective layer (override stays local)")

print("\nRULES-MIGRATION TESTS PASSED")
