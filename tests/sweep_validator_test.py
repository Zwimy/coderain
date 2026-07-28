"""Validator + sidecar defects found in the 2026-07-28 bug sweep.

The validator is the only component that is pure code and never an LLM. It is
the last thing between a hallucinated envelope and a corrupted save, so each of
these is pinned separately.

Asserts:
 1) `enemies` is validated like every other delta (it was the one forwarded raw,
    and a bare `Infinity` escaped as OverflowError mid-apply);
 2) scene_break is a real boolean test, so the STRING "false" can't lift the cap;
 3) list and string lengths are bounded, not just magnitudes;
 4) a repaired alias discarded in favour of a real key is reported;
 5) the ```rpg fence is matched case-insensitively;
 6) a second undo does not truncate the event log it can no longer roll back.
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
HOME = tempfile.mkdtemp(prefix="cr-swv-")
os.environ["CODERAIN_HOME"] = HOME

from coderain import sidecar as sc  # noqa: E402
from coderain import validator as V  # noqa: E402
from coderain.config import load_config  # noqa: E402
from coderain.engine import Engine  # noqa: E402
from coderain.memory import Library, _read_event_log  # noqa: E402

lib = Library(os.path.join(HOME, "lib"))


def _story(name):
    return lib.store(lib.create_story(name, "A tollkeeper counts what crosses "
                                            "the bridge at night."))


store = _story("Valid")

# ---- 1) enemies is validated, not forwarded ----------------------------
env = {"v": 1, "deltas": {"enemies": {"goblin": {"hp_max": 10,
                                                 "hp_delta": float("inf")}}}}
clean, rejected = V.validate(env, store)
assert "hp_delta" not in clean["deltas"].get("enemies", {}).get("goblin", {}), clean
assert any("hp_delta" in r["delta"] for r in rejected), rejected
# json.loads really does accept the bare token, which is how it got in
assert json.loads('{"x": Infinity}')["x"] == float("inf")
# a good spec still passes through, clamped
ok, _ = V.validate({"v": 1, "deltas": {"enemies": {"Goblin": {"hp_max": 999999,
                                                              "hp_delta": -3}}}}, store)
assert ok["deltas"]["enemies"]["Goblin"] == {"hp_max": V.NUM_CAP, "hp_delta": -3}, ok
bad, rej2 = V.validate({"v": 1, "deltas": {"enemies": ["not", "a", "dict"]}}, store)
assert "enemies" not in bad.get("deltas", {}) and rej2
print("1) enemies: non-finite rejected, magnitudes clamped, shape enforced")

# ---- 2) scene_break is a real boolean ----------------------------------
for falsey in ("false", "no", "0", "", "off"):
    clean, _ = V.validate({"v": 1, "scene_break": falsey,
                           "deltas": {"time_advance": {"days": 30}}}, store)
    assert not clean.get("scene_break"), f"{falsey!r} read as true"
    assert clean["deltas"]["time_advance"]["days"] == V.DAY_CAP, \
        f"{falsey!r} lifted the day cap to {clean['deltas']['time_advance']}"
for truthy in (True, "true", "YES", "1", "on"):
    clean, _ = V.validate({"v": 1, "scene_break": truthy,
                           "deltas": {"time_advance": {"days": 30}}}, store)
    assert clean.get("scene_break") is True, f"{truthy!r} read as false"
    assert clean["deltas"]["time_advance"]["days"] == V.DAY_CAP_SCENE_BREAK
print("2) scene_break: only real truthy values lift the day cap")

# ---- 3) cardinality and text length are bounded ------------------------
big = {"v": 1, "deltas": {
    "inventory_add": [f"item-{i}" for i in range(500)],
    "status_add": [f"cond-{i}" for i in range(500)],
    "flag_set": {f"f{i}": True for i in range(500)},
    "time_advance": {"days": 1, "phase": "x" * 200_000},
}}
clean, rejected = V.validate(big, store)
d = clean["deltas"]
assert len(d["inventory_add"]) <= V.LIST_CAP, len(d["inventory_add"])
assert len(d["status_add"]) <= V.LIST_CAP, len(d["status_add"])
assert len(d["flag_set"]) <= V.LIST_CAP, len(d["flag_set"])
assert len(d["time_advance"]["phase"]) <= V.STR_CAP, len(d["time_advance"]["phase"])
assert rejected, "over-long lists must be reported, not silently trimmed"
print(f"3) lists capped at {V.LIST_CAP}, free text at {V.STR_CAP} chars")

# ---- 4) a discarded alias repair is reported ---------------------------
clean, rejected = V.validate({"v": 1, "deltas": {"hp_delta": -1, "hp": 500}}, store)
assert clean["deltas"]["hp_delta"] == -1, clean
assert any(r["delta"] == "hp_delta" for r in rejected), \
    "the discarded shorthand was dropped in silence"
print("4) an alias losing to an explicit key is reported, not dropped silently")

# ---- 5) the fence is case-insensitive ----------------------------------
for fence in ("```rpg", "```RPG", "```Rpg"):
    text = f'He draws the blade.\n\n{fence}\n{{"v":1,"deltas":{{"hp_delta":-3}}}}\n```'
    got = sc.parse_sidecar(text)
    assert got and got["deltas"]["hp_delta"] == -3, f"{fence}: {got}"
    visible, side = sc.strip_sidecar(text)
    assert visible == "He draws the blade.", f"{fence} leaked: {visible!r}"
    assert side is not None
    hidden = []
    out = "".join(sc.filter_sidecar(iter([text]), hidden))
    assert out.strip() == "He draws the blade.", f"{fence} streamed: {out!r}"
    assert hidden, f"{fence} diverted nothing"
print("3 fence spellings parse, strip and stream identically")
print("5) ```RPG no longer leaks the envelope or drops its deltas")

# ---- 6) a second undo leaves the ledger consistent ---------------------
cfg = load_config()
cfg.generation["trinity_brain"] = False
s2 = _story("Undo")
eng = Engine(cfg, s2)
ws = s2.world_state()
ws["player"]["gold"] = 0
s2.set_world_state(ws)
for i in range(3):
    s2.append_turn("player", f"act {i}")
    s2.append_turn("narrator", f"result {i}")
    eng._pre_turn_rpg = eng._snapshot_rpg()
    eng.apply_envelope({"v": 1, "deltas": {"gold_delta": 10,
                                           "flag_set": {f"f{i}": True}}}, False)
gold_before = s2.world_state()["player"]["gold"]
assert eng.undo_last()
after1 = (s2.world_state()["player"]["gold"], len(_read_event_log(s2)))
assert eng.undo_last()                       # nothing left to roll back
after2 = (s2.world_state()["player"]["gold"], len(_read_event_log(s2)))
assert after2[0] == after1[0], "state changed on an unrollbackable undo"
assert after2[1] == after1[1], (
    f"the second undo deleted a log record whose deltas are still applied "
    f"({after1[1]} -> {after2[1]}); the save and the replay ledger now disagree")
print(f"6) second undo keeps state and ledger in step (gold {gold_before} -> "
      f"{after2[0]}, {after2[1]} records)")

shutil.rmtree(HOME, ignore_errors=True)
print("\nVALIDATOR SWEEP TESTS PASSED")
