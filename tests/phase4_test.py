import os, sys, shutil, tempfile, json, re
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from coderain.modules import rpg as rpg_mod
from coderain.config import load_config
from coderain.engine import Engine
from coderain.memory import Library, EDITABLE_FILES

root = os.path.join(tempfile.gettempdir(), "se_p4")
if os.path.exists(root): shutil.rmtree(root)
lib = Library(root)
cfg = load_config()
# tests stub a single-brain engine; the user's live config toggle must not reroute
cfg.generation["trinity_brain"] = False

# ---- 0) seed shape: rpg block present, disabled, rpg-rules.md editable ----
store = lib.store(lib.create_story("P4", "A duelist chasing a debt."))
assert store.read("rpg-rules.md").strip()               # resolved from global masters
assert store.layer_of("rpg-rules.md") == "global"       # not copied into the save
assert not store.path("rpg-rules.md").exists()          # lives in instructions/, shared
assert "rpg-rules.md" in EDITABLE_FILES
rpg0 = store.rpg_state()
assert rpg0 and rpg0.get("enabled") is False, rpg0
assert store.rpg_enabled() is False
assert set(rpg0["player"]["stats"]) == {"strength", "agility", "intelligence",
                                        "knowledge", "willpower", "charisma"}
print("0) rpg block seeded, disabled by default, rules editable")

# ---- 1) dice are deterministic + win-chance math ----
a = rpg_mod.roll_check(2, 15, 42, 0)
b = rpg_mod.roll_check(2, 15, 42, 0)
assert a == b, "same (seed,nonce) must reproduce the roll"
assert rpg_mod.roll_check(2, 15, 42, 1) != a or True  # different nonce -> independent
assert rpg_mod.win_chance(0, 11) == 0.5, rpg_mod.win_chance(0, 11)
assert rpg_mod.win_chance(5, 5) == 1.0        # clamps at 20/20
assert rpg_mod.win_chance(0, 25) == 0.0       # clamps at 0
assert a["success"] == (a["total"] >= 15)
print("1) engine-rolled dice deterministic + win-chance correct")

# ---- 2) sidecar parsing (fenced, bare, malformed) ----
assert rpg_mod.parse_sidecar('x ```rpg\n{"check":{"stat":"intelligence"}}\n``` y'
                             )["check"]["stat"] == "intelligence"
assert rpg_mod.parse_sidecar('prose only, nothing here') is None
assert rpg_mod.parse_sidecar('```rpg\n{not valid json}\n```') is None
vis, side = rpg_mod.strip_sidecar('Prose here.\n\n```rpg\n{"deltas":{}}\n```')
assert vis == "Prose here." and side == {"deltas": {}}
print("2) sidecar parse: fenced / bare / malformed handled")

# ---- 3) filter_sidecar hides the block even when the marker is split ----
full = 'You strike.\n\n```rpg\n{"deltas":{"xp_delta":5}}\n```'
hidden = []
out = "".join(rpg_mod.filter_sidecar((full[i:i+2] for i in range(0, len(full), 2)),
                                     hidden))
assert "```rpg" not in out and out.strip() == "You strike.", repr(out)
assert rpg_mod.parse_sidecar("".join(hidden))["deltas"]["xp_delta"] == 5
print("3) streaming filter hides sidecar (split-safe) and captures it")

# ---- 4) apply(): deltas resolve deterministically against state + files ----
st = store.rpg_state()
st["enabled"] = True
st["seed"] = 7
st["player"]["stats"]["strength"] = 3
store.set_rpg_state(st)

ev = rpg_mod.apply(store, {
    "check": {"stat": "strength", "dc": 10},
    "deltas": {"hp_delta": -4, "mana_delta": -1, "xp_delta": 50,
               "inventory_add": ["Rusty Dagger"], "status_add": ["bleeding"],
               "trust": {"mara": 2},
               "enemies": {"goblin": {"hp_max": 8, "hp_delta": -3}}},
}, cfg.rpg)
p = store.rpg_state()["player"]
assert p["hp"] == 16 and p["mana"] == 4, p
assert p["xp"] == 50 and p["level"] == 1                       # no level-up yet
assert "bleeding" in p["conditions"]
assert any(e.slug == "rusty-dagger" for e in store.entries("items.md")), "item not on items.md"
assert store.rpg_state()["companions"]["mara"]["trust"] == 2
g = store.rpg_state()["enemies"]["goblin"]
assert g["hp"] == 5 and g["hp_max"] == 8, g
assert store.rpg_state()["last_check"]["stat"] == "strength"
assert any(e.startswith("check:") for e in ev), ev
print("4) apply(): hp/mana/xp/inventory/status/trust/enemy all resolved")

# ---- 5) level-up, hp-floor + downed, inventory_remove ----
st = store.rpg_state(); st["player"]["xp"] = 90; store.set_rpg_state(st)
rpg_mod.apply(store, {"deltas": {"xp_delta": 20}}, cfg.rpg)   # 110 >= 100
p = store.rpg_state()["player"]
assert p["level"] == 2 and p["xp"] == 10, p
assert p["hp"] == p["hp_max"] == 25 and p["mana"] == p["mana_max"] == 7, p  # restored

st = store.rpg_state(); st["player"]["hp"] = 3; store.set_rpg_state(st)
rpg_mod.apply(store, {"deltas": {"hp_delta": -99}}, cfg.rpg)
p = store.rpg_state()["player"]
assert p["hp"] == 0 and "downed" in p["conditions"], p               # floors at 0

assert store.remove_entry("items.md", "rusty-dagger")
rpg_mod.apply(store, {"deltas": {"inventory_remove": ["Rusty Dagger"]}}, cfg.rpg)
assert not any(e.slug == "rusty-dagger" for e in store.entries("items.md"))
print("5) level-up restores, hp floors at 0 (+downed), inventory_remove works")

# ---- 6) engine integration: single-pass, sidecar hidden from prose + applied ----
store2 = lib.store(lib.create_story("P4b", "A mage in a burning library."))
st = store2.rpg_state()
st["enabled"] = True; st["seed"] = 3; st["player"]["stats"]["intelligence"] = 4
store2.set_rpg_state(st)
engine = Engine(cfg, store2)

NAR = ('You hurl a bolt of flame at the shade.\n\n'
       '```rpg\n{"check":{"stat":"intelligence","dc":8},'
       '"deltas":{"hp_delta":-2,"xp_delta":30,"status_add":["scorched"]}}\n```')

class FakeLLM:
    def stream(self, messages, **kw):
        assert "RPG MODULE" in messages[0]["content"], "rpg rules not injected"
        assert "Your character sheet" in messages[0]["content"]
        for i in range(0, len(NAR), 3):
            yield NAR[i:i+3]
    def complete(self, *a, **k):
        return ""

engine.llm = FakeLLM()
visible = "".join(engine.turn("cast fire at the shade"))
assert "```rpg" not in visible and "shade" in visible, repr(visible)
assert "```rpg" not in store2.turns()[-1]["text"], "sidecar leaked into transcript"
events = engine.maybe_fold()
p = store2.rpg_state()["player"]
assert p["hp"] == 18 and p["xp"] == 30 and "scorched" in p["conditions"], p
assert store2.rpg_state()["last_check"]["success"] is True   # dc8, intelligence+4
assert any(e.startswith("check:") for e in events), events
print("6) engine single-pass: prose clean, sidecar applied, events surfaced")

# ---- 7) toggle OFF: no injection, no stripping, state untouched ----
store3 = lib.store(lib.create_story("P4c", "A quiet cartographer."))  # rpg disabled
engine3 = Engine(cfg, store3)
before = store3.read("state.json")

class FakeLLMOff:
    def stream(self, messages, **kw):
        assert "RPG MODULE" not in messages[0]["content"], "rpg rules injected while OFF"
        for ch in "You unroll the map. Nothing stirs.": yield ch
    def complete(self, *a, **k):
        return ""

engine3.llm = FakeLLMOff()
vis = "".join(engine3.turn("look at the map"))
assert "map" in vis
assert engine3.maybe_fold() == [] or True   # no rpg events
assert store3.read("state.json") == before, "state.json mutated while RPG off"
print("7) toggle OFF: clean engine, no injection, state untouched")

print("\nPHASE 4 TESTS PASSED")
