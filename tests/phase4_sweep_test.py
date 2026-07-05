"""Regressions for the pre-Phase-5 bug sweep — RPG module (agent A findings)."""
import os, sys, shutil, tempfile
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from coderain.modules import rpg as rpg_mod
from coderain.config import load_config
from coderain.engine import Engine
from coderain.memory import Library, Entry

root = os.path.join(tempfile.gettempdir(), "se_p4_sweep")
if os.path.exists(root): shutil.rmtree(root)
lib = Library(root)
cfg = load_config()
# tests stub a single-brain engine; the user's live config toggle must not reroute
cfg.generation["trinity_brain"] = False


def fresh(name, enable=True, seed=5):
    store = lib.store(lib.create_story(name, "sweep premise"))
    st = store.rpg_state(); st["enabled"] = enable; st["seed"] = seed
    store.set_rpg_state(st)
    return store


# H1 — xp_per_level <= 0 must NOT hang (per clamped to >=1; loop terminates).
store = fresh("h1")
rpg_mod.apply(store, {"deltas": {"xp_delta": 10}}, {"xp_per_level": 0})
p = store.rpg_state()["player"]
# with per=1: 10→L2(9)→L3(7)→L4(4)→L5(0); terminates deterministically.
assert p["level"] == 5 and p["xp"] == 0, p
rpg_mod.apply(fresh("h1b"), {"deltas": {"xp_delta": 3}}, {"xp_per_level": -5})  # negative too
print("H1) xp_per_level<=0 no longer infinite-loops")

# H2 — a sidecar-ONLY narrator turn (no prose) still applies mechanics and is kept.
store = fresh("h2", seed=3)
NAR_ONLY = '```rpg\n{"deltas":{"hp_delta":-5,"xp_delta":10}}\n```'
class FakeOnly:
    def stream(self, messages, **kw):
        for i in range(0, len(NAR_ONLY), 4):
            yield NAR_ONLY[i:i+4]
    def complete(self, *a, **k):
        return ""
eng = Engine(cfg, store)
eng.llm = FakeOnly()
visible = "".join(eng.turn("stab in the dark"))
assert visible.strip() == "", repr(visible)                 # nothing shown (all sidecar)
events = eng.maybe_fold()
assert store.rpg_state()["player"]["hp"] == 15, store.rpg_state()["player"]
assert any(e.startswith("hp:") for e in events), events
turns = store.turns()
assert turns and turns[-1]["role"] == "player" and "stab in the dark" in turns[-1]["text"]
print("H2) sidecar-only turn applies mechanics + keeps the player action")

# M1 — inventory_add must not clobber an authored item's status.
store = fresh("m1")
store.write("items.md", "# Items\n\n## Torch {#torch}\nimportance: 3\n"
            "status: lit, mounted (authored)\n\nAn authored torch.\n")
rpg_mod.apply(store, {"deltas": {"inventory_add": ["Torch"]}}, cfg.rpg)
torch = {e.slug: e for e in store.entries("items.md")}["torch"]
assert torch.attrs.get("status") == "lit, mounted (authored)", torch.attrs
print("M1) inventory_add preserves an authored item's attrs")

# M2 — 'downed' auto-clears when HP is restored above 0.
store = fresh("m2")
st = store.rpg_state(); st["player"]["hp"] = 3; store.set_rpg_state(st)
rpg_mod.apply(store, {"deltas": {"hp_delta": -99}}, cfg.rpg)
assert "downed" in store.rpg_state()["player"]["conditions"]
rpg_mod.apply(store, {"deltas": {"hp_delta": 8}}, cfg.rpg)
assert "downed" not in store.rpg_state()["player"]["conditions"]
print("M2) 'downed' clears symmetrically on heal")

# M3 — XP floors at 0 (a negative delta can't desync the sheet).
store = fresh("m3")
st = store.rpg_state(); st["player"]["xp"] = 5; store.set_rpg_state(st)
rpg_mod.apply(store, {"deltas": {"xp_delta": -50}}, cfg.rpg)
assert store.rpg_state()["player"]["xp"] == 0, store.rpg_state()["player"]
print("M3) XP floors at 0 on a negative delta")

# M4 — bare (unfenced/truncated) sidecar parses via brace balancing, not greedily.
got = rpg_mod.parse_sidecar('prose ```rpg\n{"deltas":{"hp_delta":-1}} then stray } junk')
assert got == {"deltas": {"hp_delta": -1}}, got
# nested braces inside a proper fence still parse whole
assert rpg_mod.parse_sidecar('```rpg\n{"deltas":{"x":1}}\n```') == {"deltas": {"x": 1}}
# L1 — when several fenced blocks appear, the LAST one wins.
assert rpg_mod.parse_sidecar('```rpg\n{"a":1}\n```\ntext\n```rpg\n{"b":2}\n```') == {"b": 2}
print("M4/L1) bare parse is brace-balanced; last fenced block wins")

print("\nPHASE 4 SWEEP-FIX TESTS PASSED")
