"""Regressions for the pre-Phase-6 bug sweep (Phase 5 vector + RPG-retry findings)."""
import os, sys, re, shutil, tempfile, hashlib
sys.path.insert(0, r"F:\Seven\StoryEngine")
from coderain.memory import Library
from coderain.config import load_config
from coderain.engine import Engine
from coderain.modules import vector as vec


class FakeEmbedder:
    DIM = 64

    def __init__(self, model="fake-embed-v1"):
        self.calls = 0
        self.model = model

    def embed(self, texts):
        self.calls += 1
        out = []
        for t in texts:
            v = [0.0] * self.DIM
            for tok in re.findall(r"[a-z0-9]+", t.lower()):
                v[int(hashlib.md5(tok.encode()).hexdigest(), 16) % self.DIM] += 1.0
            out.append(v)
        return out


root = os.path.join(tempfile.gettempdir(), "se_pre6")
if os.path.exists(root): shutil.rmtree(root)
lib = Library(root)
store = lib.store(lib.create_story("Pre6", "A premise."))
store.write("locations.md",
    "# Locations\n\n## Keep {#keep}\nimportance: 3\n\nA cold stone keep on the moor.\n")
store.write("memory/scenes.md",
    "# Scene summaries\n\n## Scene 1 {#scene-1}\nwhen: Day 1\n\n"
    "The caravan was ambushed at Redgorge pass by masked raiders.\n")

# ---- H1/H2: scene summaries are embedded AND resolvable through the retriever ----
vi = vec.VectorIndex(store, FakeEmbedder())
vi.sync(10)
hits = vi.search("an ambush at the pass by masked raiders", 5, set(), 10)
assert any(h.slug == "scene-1" for h in hits), [h.slug for h in hits]
ret = vec.Retriever(store, vec.VectorIndex(store, FakeEmbedder()), {"top_k": 5})
recalled = ret("the caravan ambush at redgorge pass", set())
assert any(e.slug == "scene-1" for e in recalled), [e.slug for e in recalled]
print("H1/H2) scene summaries are embedded and recalled")

# ---- M1: an embedder that returns the wrong count aborts the sync (no half-write) --
class ShortEmb:
    model = "short"
    def embed(self, texts):
        return [[1.0] * 4]                     # always 1 vector regardless of input
store2 = lib.store(lib.create_story("Pre6b", "Another premise."))
store2.write("characters.md", "# Characters\n\n## Aldo {#aldo}\nimportance: 3\n\n"
             "A wary sellsword.\n\n## Bex {#bex}\nimportance: 2\n\nA quick thief.\n")
vi_bad = vec.VectorIndex(store2, ShortEmb())
assert vi_bad.sync(1) == 0                     # >1 entries in, 1 vec back -> aborted
assert vi_bad.search("anything", 5, set(), 1) == []   # nothing was written
print("M1) count-mismatch batch aborts the sync cleanly")

# ---- M3: changing the embed model re-embeds everything (model is part of the hash) -
vA = vec.VectorIndex(store, FakeEmbedder(model="model-A"))
nA = vA.sync(20)
assert vA.sync(21) == 0                         # unchanged -> no re-embed
vB = vec.VectorIndex(store, FakeEmbedder(model="model-B"))
assert vB.sync(22) == nA and nA > 0            # model switch -> full re-embed
print("M3) switching embed model forces a clean re-embed")

# ---- stale-slug deletion: removing an entry from Markdown drops its index row ------
assert any(h.slug == "keep" for h in vB.search("a cold stone keep", 5, set(), 22))
store.write("locations.md", "# Locations\n")   # delete the Keep entry
vB.sync(23)
assert all(h.slug != "keep" for h in vB.search("a cold stone keep", 5, set(), 23))
print("stale) deleted Markdown entry is purged from the index")

# ---- RPG /retry must not stack mechanics: rollback restores the pre-turn sheet -----
cfg = load_config()
# tests stub a single-brain engine; the user's live config toggle must not reroute
cfg.generation["trinity_brain"] = False
store3 = lib.store(lib.create_story("Pre6c", "A duel premise."))
st = store3.rpg_state(); st["enabled"] = True; st["seed"] = 9
store3.set_rpg_state(st)
engine = Engine(cfg, store3)

NAR = "You lunge and take a hit.\n\n```rpg\n{\"deltas\":{\"hp_delta\":-5}}\n```"
class FakeLLM:
    def stream(self, messages, **kw):
        for i in range(0, len(NAR), 5):
            yield NAR[i:i+5]
    def complete(self, *a, **k):
        return ""
engine.llm = FakeLLM()

hp0 = store3.rpg_state()["player"]["hp"]
"".join(engine.turn("attack")); engine.maybe_fold()
assert store3.rpg_state()["player"]["hp"] == hp0 - 5, store3.rpg_state()["player"]
# simulate a retry: roll back, then re-run the same action
engine.restore_pre_turn_rpg()
assert store3.rpg_state()["player"]["hp"] == hp0                 # deltas undone
store3.drop_last_turns(2)
"".join(engine.turn("attack")); engine.maybe_fold()
assert store3.rpg_state()["player"]["hp"] == hp0 - 5, "retry double-applied mechanics"
print("retry) mechanics roll back on retry (no double-apply)")

# ---- the global rpg-rules master carries the new attributes (not the old set) -----
assert "Strength" in store3.read("rpg-rules.md")
assert "combat, magic, stealth, social" not in store3.read("rpg-rules.md")
print("rules) global rpg-rules master uses the renamed attributes")

print("\nPRE-PHASE-6 SWEEP-FIX TESTS PASSED")
