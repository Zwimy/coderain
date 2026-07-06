"""Tier 4 — automation & play aids.

ST-31 persistent output regex: the stored narrator turn is scrubbed by the save's
rules (so the model's memory sees the cleaned text) while the live stream stays
raw and the client settles it via the 'done' event. (ST-30 quick actions are a
UI + state.json round-trip, verified in the preview.)
"""
import os, sys, shutil, tempfile
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from coderain.config import load_config
from coderain.engine import Engine
from coderain.memory import Library

root = os.path.join(tempfile.gettempdir(), "se_tier4")
if os.path.exists(root):
    shutil.rmtree(root)
lib = Library(root)


def _engine_with_rules(rules, chunk):
    store = lib.store(lib.saves.create("Rx", mode="simple", premise="."))
    ws = store.world_state(); ws["regex_rules"] = rules
    store.set_world_state(ws)
    cfg = load_config(); cfg.generation["trinity_brain"] = False
    eng = Engine(cfg, store)
    eng.llm = type("L", (), {"stream": lambda self, m, **k: iter([chunk])})()
    return store, eng


# ---- ST-31: persistent regex cleans the STORED text; stream stays raw ----
store, eng = _engine_with_rules(
    [{"find": "wry smile", "replace": "grin", "flags": "i"}],
    "He gave a Wry Smile.")
streamed = "".join(eng.turn("look"))
assert streamed == "He gave a Wry Smile.", f"live stream must be raw; got {streamed!r}"
assert store.turns()[-1]["text"] == "He gave a grin.", \
    f"stored turn must be regex-cleaned; got {store.turns()[-1]['text']!r}"
print("1) ST-31 regex: stored text cleaned (model memory), live stream stays raw")

# ---- ST-31: a broken rule is skipped, never crashes the turn ----
store2, eng2 = _engine_with_rules(
    [{"find": "[unclosed(", "replace": "x"},
     {"find": "shadows", "replace": "gloom"}],
    "The shadows deepen.")
"".join(eng2.turn("wait"))
assert store2.turns()[-1]["text"] == "The gloom deepen.", "bad rule skipped, good rule applied"
print("2) ST-31 regex: an invalid pattern is skipped (good rules still apply)")

# ---- ST-31: no rules = untouched; multiple rules chain in order ----
store3, eng3 = _engine_with_rules([], "Plain narration.")
"".join(eng3.turn("go"))
assert store3.turns()[-1]["text"] == "Plain narration.", "no rules -> unchanged"
store4, eng4 = _engine_with_rules(
    [{"find": "cat", "replace": "dog"}, {"find": "dog", "replace": "fox"}],
    "The cat sat.")
"".join(eng4.turn("go"))
assert store4.turns()[-1]["text"] == "The fox sat.", "rules chain in order (cat->dog->fox)"
print("3) ST-31 regex: no-rules no-op; rules chain in declared order")

print("\nALL TIER-4 CHECKS PASSED")
