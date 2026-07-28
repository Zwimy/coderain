"""Tenth-sweep findings.

Two lessons in this round. First: `Entry.__post_init__` cannot guard an attrs
dict that a producer fills in AFTER construction, and generator.py does exactly
that — so the guard written for that producer was bypassed by that producer.
Sanitising moved to render(), the one place attrs become `key: value` lines.

Second: bounding a value and MATCHING it are different jobs. The `location`
delta was slugified for safety, and resolve_location matches on slug OR title OR
alias — so the safety step made two of the three matches impossible, and the
place the player was standing in stopped reaching the prompt.

Asserts:
 1) a location named exactly as the rules instruct resolves and activates;
 2) a multi-word alias resolves;
 3) punctuation-only is still refused;
 4) attrs set after construction still render as one line;
 5) a comma in a granted ability does not become two abilities on reopen.

The six SPA findings are browser behaviours (a latched busy flag, a destructive
Try-again, a silent retry rollback, a cross-story Suggest, an unguarded delete);
tests/webapp_smoke_test.py is where those live.
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
HOME = tempfile.mkdtemp(prefix="cr-sw10-")
os.environ["CODERAIN_HOME"] = HOME

from coderain import validator as V  # noqa: E402
from coderain.config import load_config  # noqa: E402
from coderain.memory import Entry, Library  # noqa: E402

lib = Library(os.path.join(HOME, "lib"))
cfg = load_config()


def _story(name):
    return lib.store(lib.create_story(name, "A courier crosses a frozen kingdom."))


# ---- 1) the exact name of an established place --------------------------
s1 = _story("Place")
s1.upsert_entry("locations.md", Entry(
    "The Static Quarter", "static-quarter", aliases=["the quarter"],
    body="Dead screens and wet concrete."))
clean, rejected = V.validate(
    {"v": 1, "deltas": {"location": "The Static Quarter"}}, s1)
assert not rejected, rejected
V.apply_world(s1, clean)
loc = s1.world_state()["player"]["location"]
assert loc == "The Static Quarter", (
    f"stored {loc!r}: slugifying the delta made resolve_location's title and "
    "alias matches impossible, so every prompt read a slug and the entry was "
    "never force-activated")
sysmsg = s1.assemble([], "I look around.")[0]["content"]
assert "Current location: The Static Quarter" in sysmsg, sysmsg[:400]
assert "Dead screens and wet concrete." in sysmsg, (
    "the place the player is standing in never reached the prompt")
print("1) a location named as the rules instruct resolves and activates")

# ---- 2) a multi-word alias ---------------------------------------------
clean, _rej = V.validate({"v": 1, "deltas": {"location": "the quarter"}}, s1)
V.apply_world(s1, clean)
assert s1.world_state()["player"]["location"] == "The Static Quarter", (
    "a multi-word alias resolved to nothing; apply_world's own comment "
    "promises 'the tavern' resolves to 'Blackwood Tavern'")
print("2) a multi-word alias resolves to the canonical name")

# ---- 3) punctuation-only is still refused ------------------------------
clean, rejected = V.validate({"v": 1, "deltas": {"location": "!!!"}}, s1)
assert not (clean.get("deltas") or {}).get("location"), clean
assert rejected, "junk must still be rejected, not stored as a place name"
print("3) a punctuation-only location is still refused")

# ---- 4) attrs set AFTER construction ------------------------------------
s4 = _story("Attrs")
e4 = Entry("Mira", "mira", body="A ranger.")
e4.attrs["wants"] = "To find her brother\nbefore the pass closes"
e4.attrs["motivation"] = "guilt over the fire"
s4.upsert_entry("characters.md", e4)
got = s4.entries("characters.md")[0]
assert got.attrs.get("motivation") == "guilt over the fire", (
    f"the newline swallowed every attr after it: {got.attrs}")
assert got.attrs.get("wants", "").startswith("To find her brother before"), (
    got.attrs.get("wants"))
print("4) attrs filled in after construction still render as one line")

# ---- 5) a comma in a granted ability ------------------------------------
s5 = _story("Grant")
rpg = s5.rpg_state()
rpg["enabled"], rpg["pending_grant"] = True, 1
s5.set_rpg_state(rpg)
clean, _rej = V.validate(
    {"v": 1, "deltas": {"ability_add": ["Blade of the Sun, Herald of Dawn"]}}, s5)
got = (clean.get("deltas") or {}).get("ability_add") or []
assert got and "," not in got[0], (
    f"a comma survives into the `abilities:` attr line, which _sync_player_stats "
    f"re-splits on the next open: one grant becomes two, permanently: {got}")
print("5) a comma in a granted ability cannot split it into two")

shutil.rmtree(HOME, ignore_errors=True)
print("\nSWEEP 10 FINDINGS: ALL CLOSED")
