"""SPEC-V2 bug-sweep regressions (multi-agent sweep after Wave 4).

Covers the sweep's HIGH/MED fixes: NaN/Infinity envelopes never raise;
magnitude caps; same-envelope add+equip; removals gated on actually holding
the item (authored definitions survive); duplicate grants don't burn
pending_grant; '## ' inside an entry body round-trips; hidden lore is masked
in every recall tool; threads.md is revealable; undo prunes the events log;
event-log records carry the narrator index in quad mode; branch never
double-applies (genesis record / incomplete-log guard); fold-state
reconciliation; word-boundary triggers; facts newline sanitization.
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from coderain.modules import rpg as rpg_mod                     # noqa: E402
from coderain import validator as V                     # noqa: E402
from coderain.config import load_config                 # noqa: E402
from coderain.engine import Engine                      # noqa: E402
from coderain.memory import (Entry, Library,            # noqa: E402
                                _reconcile_fold_state, trigger_hit)

root = os.path.join(tempfile.gettempdir(), "se_sweep2")
if os.path.exists(root):
    shutil.rmtree(root)
lib = Library(root)
save = lib.saves.create("Sweep", mode="rpg", premise="A test of everything.")
store = lib.store(save)
st = store.rpg_state()
st["seed"] = 7
store.set_rpg_state(st)

cfg = load_config()
cfg.generation["trinity_brain"] = False
eng = Engine(cfg, store)

# ---- 1) NaN/Infinity never raise; magnitude caps clamp ----
nan, inf = float("nan"), float("inf")
clean, rejected = V.validate(
    {"deltas": {"hp_delta": inf, "gold_delta": nan,
                "time_advance": {"days": inf}},
     "check": {"stat": "agility", "dc": nan}}, store)
assert "hp_delta" not in clean.get("deltas", {}), clean
reasons = " ".join(r["reason"] for r in rejected)
assert "integer" in reasons or "number" in reasons, rejected
clean, _ = V.validate({"deltas": {"xp_delta": 10**15, "gold_delta": 10**15}},
                      store)
assert clean["deltas"]["xp_delta"] == V.NUM_CAP, clean
assert clean["deltas"]["gold_delta"] == V.GOLD_CAP, clean
print("1) NaN/Infinity rejected without raising; huge numbers clamped")

# ---- 2) pick-up-and-equip in ONE envelope ----
clean, rejected = V.validate(
    {"deltas": {"inventory_add": [{"slug": "iron-sword", "qty": 1}],
                "inventory_equip": ["iron-sword"]}}, store)
assert clean["deltas"].get("inventory_equip") == ["iron-sword"], (clean, rejected)
events = rpg_mod.apply(store, clean, cfg.rpg)
assert any("equipped: iron-sword" in e for e in events), events
print("2) same-envelope add+equip validates and applies")

# ---- 3) removals gated on holding; authored definitions survive ----
store.upsert_entry("items.md", Entry(
    "The Debt-Contract", "debt-contract", importance=4,
    attrs={"rarity": "unique"}, body="A binding pact, sealed in wax."))
_, rejected = V.validate(
    {"deltas": {"inventory_remove": ["debt-contract"]}}, store)
assert any("not held" in r["reason"] for r in rejected), rejected
assert any(e.slug == "debt-contract" for e in store.entries("items.md"))
# held authored item dropped to qty 0: mirror empties, definition stays
rpg_state = store.rpg_state()
rpg_state.setdefault("inventory", {})["debt-contract"] = {
    "qty": 1, "equipped": False}
store.set_rpg_state(rpg_state)
clean, _ = V.validate({"deltas": {"inventory_remove": ["debt-contract"]}}, store)
rpg_mod.apply(store, clean, cfg.rpg)
assert "debt-contract" not in store.rpg_state().get("inventory", {})
assert any(e.slug == "debt-contract" for e in store.entries("items.md")), \
    "authored definition erased on drop"
print("3) not-held removal rejected; authored item survives being dropped")

# ---- 4) duplicate grant keeps pending_grant ----
rpg_state = store.rpg_state()
rpg_state["pending_grant"] = 2
rpg_state.setdefault("player", {})["abilities"] = ["Fireball"]
store.set_rpg_state(rpg_state)
events = rpg_mod.apply(store, {"deltas": {"ability_add": ["Fireball"]}}, cfg.rpg)
assert store.rpg_state()["pending_grant"] == 2, store.rpg_state()
assert any("already known" in e for e in events), events
events = rpg_mod.apply(store, {"deltas": {"ability_add": ["Ice Lance"]}}, cfg.rpg)
assert store.rpg_state()["pending_grant"] == 1
assert "Ice Lance" in store.rpg_state()["player"]["abilities"]
print("4) duplicate grant burns nothing; a real grant still consumes one")

# ---- 5) '## ' in a body round-trips without phantom entries ----
store.upsert_entry("characters.md", Entry(
    "Kaelen", "kaelen", importance=3,
    body="A knight.\n\n## Backstory\nHe fell at Ashford."))
chars = store.entries("characters.md")
kaelen = next(e for e in chars if e.slug == "kaelen")
assert not any(e.slug == "backstory" for e in chars), \
    "body sub-header became a phantom entry"
assert "Backstory" in kaelen.body and "Ashford" in kaelen.body, kaelen.body
print("5) markdown sub-header inside a body survives the round-trip")

# ---- 6) hidden lore masked in every recall tool ----
store.upsert_entry("characters.md", Entry(
    "Thorne", "thorne", importance=4, attrs={"hidden": "true"},
    body="SECRET: Thorne is the killer."))
for text in (store.lookup("thorne"), store.recall_entity("thorne")):
    assert "killer" not in text, text
    assert "SECRET" in text or "secret" in text.lower(), text
store.upsert_entry("threads.md", Entry(
    "The Betrayal", "the-betrayal", importance=4, attrs={"hidden": "true"},
    body="SECRET: the captain sold the gate key."))
assert "sold the gate key" not in store.recall_quest("the-betrayal")
print("6) lookup/recall_entity/recall_quest mask hidden lore")

# ---- 7) hidden threads are revealable ----
e = store.set_hidden("the-betrayal", False)
assert e is not None and e.slug == "the-betrayal", "thread not revealable"
store.set_hidden("the-betrayal", True)
clean, rejected = V.validate({"deltas": {"reveal": ["the-betrayal"]}}, store)
assert clean.get("deltas", {}).get("reveal") == ["the-betrayal"], rejected
print("7) threads.md joined the reveal path")

# ---- 8) events log: genesis record + narrator indexing + undo pruning ----
records = [json.loads(ln) for ln in
           store.read("memory/events.jsonl").splitlines()]
assert records and records[0]["turn"] == 0, "no genesis record on create"
# single-brain order: narration is stored first, THEN the sidecar applies
store.append_turn("player", "I search the room.")
store.append_turn("narrator", "You find five coins.")
eng._pre_turn_rpg = eng._snapshot_rpg()
eng.apply_envelope({"deltas": {"gold_delta": 5}}, True)
records = [json.loads(ln) for ln in
           store.read("memory/events.jsonl").splitlines()]
assert records[-1]["turn"] == 2, records[-1]      # narrator turn index
gold_before_undo = store.world_state()["player"]["gold"]
assert eng.undo_last()
records = [json.loads(ln) for ln in
           store.read("memory/events.jsonl").splitlines()]
assert all(r["turn"] <= 0 for r in records), \
    f"undone turn's record survived: {records}"
assert store.world_state()["player"]["gold"] == gold_before_undo - 5
print("8) genesis logged; records carry narrator index; undo prunes the log")

# ---- 9) quad log_turn: envelope applied pre-append still gets the right index ----
store.append_turn("player", "I haggle.")
eng._pre_turn_rpg = eng._snapshot_rpg()
eng.apply_envelope({"deltas": {"gold_delta": 3}}, True,
                   log_turn=len(store.turns()) + 1)
store.append_turn("narrator", "The merchant relents.")
records = [json.loads(ln) for ln in
           store.read("memory/events.jsonl").splitlines()]
assert records[-1]["turn"] == len(store.turns()), records[-1]
print("9) quad-style pre-append apply logs the narrator index")

# ---- 10) branch: complete log rebuilds; gold matches the fork point ----
store.append_turn("player", "I buy bread.")
store.append_turn("narrator", "One coin gone.")
eng._pre_turn_rpg = eng._snapshot_rpg()
eng.apply_envelope({"deltas": {"gold_delta": -1}}, True)
gold_now = store.world_state()["player"]["gold"]
b_slug, warns = lib.saves.branch(save, 2, cfg.rpg)
b_store = lib.store(b_slug)
assert len(b_store.turns()) == 2
assert b_store.world_state()["player"]["gold"] == 3, \
    (b_store.world_state()["player"], "expected only the T2 delta")
assert store.world_state()["player"]["gold"] == gold_now   # source untouched
print(f"10) branch @T2 rebuilt from the log: gold 3 (warnings: {warns or 'none'})")

# ---- 11) branch with an INCOMPLETE log warns and never double-applies ----
save2 = lib.saves.create("NoGenesis", mode="rpg", premise="Legacy save.")
s2 = lib.store(save2)
eng2 = Engine(cfg, s2)
for i in range(2):
    s2.append_turn("player", f"act {i}")
    s2.append_turn("narrator", f"done {i}")
    eng2._pre_turn_rpg = eng2._snapshot_rpg()
    eng2.apply_envelope({"deltas": {"gold_delta": 10}}, True)
assert s2.world_state()["player"]["gold"] == 20
# Simulate a legacy save whose log lost its early records: keep only the
# records past the first exchange (first surviving record is turn 4).
kept = [json.loads(ln) for ln in s2.read("memory/events.jsonl").splitlines()]
kept = [r for r in kept if r.get("turn", 0) > 2]
s2.write("memory/events.jsonl",
         "".join(json.dumps(r) + "\n" for r in kept))
b2, warns2 = lib.saves.branch(save2, 4, cfg.rpg)
assert any("event log" in w for w in warns2), warns2
assert lib.store(b2).world_state()["player"]["gold"] == 20, \
    "incomplete-log branch double-applied deltas"
print("11) incomplete log: loud warning, state kept, no double-apply")

# ---- 12) fold-state reconciliation ----
b2_store = lib.store(b2)
b2_store.write_state({"folded_turns": 12, "folded_scenes": 3})
_reconcile_fold_state(b2_store)               # no scenes remain on this save
assert b2_store.state()["folded_turns"] == 0, b2_store.state()
b2_store.upsert_entry("memory/scenes.md", Entry(
    "Scene 1", "scene-1", attrs={"turns": "1-4"}, body="Stuff happened."))
_reconcile_fold_state(b2_store)
assert b2_store.state()["folded_turns"] == 4
assert b2_store.state()["folded_scenes"] == 1
print("12) fold counter recomputed from the scenes actually present")

# ---- 13) word-boundary triggers + newline-safe facts ----
assert not trigger_hit("Ash", "the tide washed over the pier")
assert trigger_hit("Ash", "the road to ash was long")
assert not trigger_hit("Ana", "a banana split")
store.add_facts(["The moon is red.\n- Injected bullet"])
facts_text = store.read("memory/facts.md")
assert "Injected bullet" not in [ln[2:] for ln in facts_text.splitlines()
                                 if ln.startswith("- ")] or \
    "The moon is red. - Injected bullet" in facts_text
assert facts_text.count("The moon is red") == 1
store.add_facts(["The moon is red.\n- Injected bullet"])   # dedupe round-trip
assert facts_text == store.read("memory/facts.md")
print("13) triggers respect word boundaries; facts are newline-safe + deduped")

print("\nSWEEP-2 REGRESSION TESTS PASSED")
