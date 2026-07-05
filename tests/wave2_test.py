"""Wave 2: lorebook activation + structured episodes + hidden lore + custom types.

Covers: lore attribute parsing; budgeted assemble (pinned/critical always in,
trigger-attr activation, weight ranking under a tight budget, links one-liners);
hidden entries (Secrets section, no leaks); episode metadata + facts emission
(and the metadata-less fallback); recall_entity/recall_quest; related-scene
neighbor retrieval; custom lore files (declare, seed, activate, scenario copy);
the reveal delta end-to-end incl. undo re-hide; stat-list validation.
"""
import os, sys, shutil, tempfile, json
sys.path.insert(0, r"F:\Seven\StoryEngine")
from coderain import validator as V
from coderain.config import load_config
from coderain.engine import Engine
from coderain.memory import Entry, Library, MemoryStore
from coderain.summarizer import Summarizer

root = os.path.join(tempfile.gettempdir(), "se_wave2")
if os.path.exists(root): shutil.rmtree(root)
lib = Library(root)
store = lib.store(lib.create_story("Veil", "A masked court, full of secrets."))

# ---- 1) lore attribute parsing ----
store.upsert_entry("characters.md", Entry(
    "Mara", "mara", aliases=["the spymaster"], importance=4,
    attrs={"weight": "important", "triggers": "whisper network, ciphers",
           "links": "the-veil"}))
store.upsert_entry("factions.md", Entry(
    "The Veil", "the-veil", importance=3, attrs={"pinned": "true"}))
store.upsert_entry("characters.md", Entry(
    "The Patron", "the-patron", importance=5,
    attrs={"hidden": "true", "weight": "critical"},
    body="Secretly the player's own father."))
store.upsert_entry("items.md", Entry(
    "Dust Mote", "dust-mote", importance=1, attrs={"weight": "minor"},
    body="An utterly forgettable speck. " * 40))
m = next(e for e in store.entries("characters.md") if e.slug == "mara")
assert m.weight() == "important" and m.weight_factor() == 1.5
assert m.links() == ["the-veil"]
assert "ciphers" in m.triggers() and "whisper network" in m.triggers()
p = next(e for e in store.entries("characters.md") if e.slug == "the-patron")
assert p.hidden() and p.weight() == "critical"
assert next(e for e in store.entries("factions.md")
            if e.slug == "the-veil").pinned()
print("1) lore attributes parse (weight/pinned/hidden/triggers/links)")

# ---- 2) assemble: pinned always in; trigger attr activates; hidden -> Secrets ----
msgs = store.assemble([], "I study the ciphers by candlelight.")
sysmsg = msgs[0]["content"]
assert "Mara" in sysmsg, "triggers: attr keyword failed to activate the entry"
assert "The Veil" in sysmsg, "pinned entry missing despite no mention"
assert "Secrets you know" in sysmsg and "own father" in sysmsg
# hidden entry appears ONLY in the Secrets section
normal = sysmsg.split("Secrets you know")[0]
assert "the-patron" not in normal
print("2) assemble: trigger activation + pinned always-in + Secrets framing")

# ---- 3) weight ranking under a tight budget: minor drops first ----
msgs = store.assemble([], "the dust mote and the ciphers", budget_tokens=220)
sysmsg = msgs[0]["content"]
assert "Mara" in sysmsg, "important entry should survive the tight budget"
assert "utterly forgettable" not in sysmsg, "minor entry should be cut first"
print("3) tight budget cuts minor lore before important lore")

# ---- 4) links surface as one-liners when their owner activates ----
store.upsert_entry("factions.md", Entry(
    "The Veil", "the-veil", importance=3,
    attrs={"status": "watching the court"}))          # unpin so it must ride links
msgs = store.assemble([], "I ask about the whisper network.")
sysmsg = msgs[0]["content"]
assert "Mara" in sysmsg
assert "watching the court" in sysmsg, "linked piece should surface as one-liner"
print("4) links: activated entry pulls its linked piece")

# ---- 5) episode metadata + facts (and metadata-less fallback) ----
class FoldStub:
    def __init__(self, payload): self.payload = payload
    def complete(self, messages, **k): return json.dumps(self.payload)

class Cfg:
    memory = {}
    generation = {}

sumr = Summarizer(Cfg(), store, FoldStub({
    "scene_summary": "You bargain with [[char:mara]] over the ciphers.",
    "timeline": "bargained with [[char:mara]]",
    "characters": ["Mara"], "locations": ["Masked Court"],
    "quests": ["the-cipher-debt"],
    "state_changes": ["quests.the-cipher-debt -> active"],
    "facts": ["The court is ruled by the Masked Regent.",
              "The court is ruled by the Masked Regent."],   # dupe -> once
}))
for i in range(4):
    store.append_turn("player" if i % 2 == 0 else "narrator", f"turn {i + 1}")
events = sumr._fold_scene(store.turns()[:2], 1, 1)
sc = next(e for e in store.entries("memory/scenes.md") if e.slug == "scene-1")
assert sc.attrs.get("characters") == "mara"
assert sc.attrs.get("locations") == "masked-court"
assert sc.attrs.get("quests") == "the-cipher-debt"
assert "->" in sc.attrs.get("state_changes", "")
assert sc.attrs.get("day"), "day stamp missing"
assert store.facts() == ["The court is ruled by the Masked Regent."]
assert any("fact" in e for e in events)
# metadata-less emission still folds (never blocks)
sumr2 = Summarizer(Cfg(), store, FoldStub({"scene_summary": "Bare.",
                                           "timeline": "bare"}))
sumr2._fold_scene(store.turns()[2:4], 2, 3)
sc2 = next(e for e in store.entries("memory/scenes.md") if e.slug == "scene-2")
assert "characters" not in sc2.attrs and sc2.body == "Bare."
print("5) episode metadata + deduped facts; metadata-less fold still lands")

# ---- 6) recall_entity / recall_quest ----
out = store.recall_entity("Mara")
assert "Mara" in out and "[T1-2]" in out
out = store.recall_quest("the-cipher-debt")
assert "[T1-2]" in out
st = store.world_state(); st["quests"]["the-cipher-debt"] = "active"
store.set_world_state(st)
assert "active" in store.recall_quest("the-cipher-debt")
assert "No entity" in store.recall_entity("nobody-ever")
print("6) recall_entity/recall_quest resolve entries + episode pointers")

# ---- 7) related past scenes: episode about a present entity + neighbors ----
for n in range(3, 9):
    sumr2._fold_scene(store.turns()[:2], n, n * 2 - 1)   # filler scenes 3..8
msgs = store.assemble([], "I return to Mara.", scenes_tail=2)
sysmsg = msgs[0]["content"]
assert "Related past scenes" in sysmsg and "scene-1" in sysmsg
print("7) related past scenes injected for entities now present")

# ---- 8) custom lore files: declare, seed, activate, index ----
name = store.add_custom_file("Races", "Species of the veil.")
assert name == "races.md" and store.path("races.md").exists()
assert "races.md" in store.gated_registries()
store.upsert_entry("races.md", Entry("Duskborn", "duskborn", importance=3,
                                     body="Night-sighted folk of the under-court."))
msgs = store.assemble([], "A duskborn crosses the hall.")
assert "Night-sighted" in msgs[0]["content"]
assert store.index().resolve("duskborn") is not None
# scenario-declared custom file copies into a save on open
scen = lib.scenarios.create("Custom World", "A premise.", "")
scen_json = lib.scenarios.dir(scen) / "scenario.json"
scen_meta = json.loads(scen_json.read_text(encoding="utf-8"))
scen_meta["custom_files"] = ["rules.md"]
scen_json.write_text(json.dumps(scen_meta), encoding="utf-8")
(lib.scenarios.dir(scen) / "rules.md").write_text("# Rules\n\n## No Iron  {#no-iron}\nimportance: 4\n\nIron is forbidden at court.\n", encoding="utf-8")
save2 = lib.saves.create("Custom Run", scenario_slug=scen)
store2 = lib.store(save2)
assert "rules.md" in store2.custom_files()
assert any(e.slug == "no-iron" for e in store2.entries("rules.md"))
print("8) custom lore files: save-declared + scenario-declared both work")

# ---- 9) reveal: validator legality + engine apply + undo re-hide ----
cfg = load_config()
cfg.generation["trinity_brain"] = False

class Prose:
    def stream(self, messages, **k):
        yield "A mask slips."

eng = Engine(cfg, store)
eng.llm = Prose()
_c, rej = V.validate({"deltas": {"reveal": ["nobody", "mara", "the-patron"]}},
                     store)
reasons = {r["delta"]: r["reason"] for r in rej}
assert "no such lore entry" in reasons["reveal:nobody"]
assert "not hidden" in reasons["reveal:mara"]
"".join(eng.turn("I confront the patron."))
events = eng.apply_envelope({"v": 1, "deltas": {"reveal": ["the-patron"]}},
                            rpg_on=False)
assert any("revealed: The Patron" in e for e in events), events
assert not next(e for e in store.entries("characters.md")
                if e.slug == "the-patron").hidden()
assert any(e.slug == "revealed-the-patron"
           for e in store.entries("canon-events.md"))
assert eng.undo_last()
assert next(e for e in store.entries("characters.md")
            if e.slug == "the-patron").hidden(), "undo must re-hide"
assert not any(e.slug == "revealed-the-patron"
               for e in store.entries("canon-events.md"))
print("9) reveal: legality, apply, canon event, undo re-hides")

# ---- 10) stat-list validation ----
stats = ["strength", "agility", "willpower"]
_c, rej = V.validate({"check": {"stat": "default", "dc": 12}}, store, stats=stats)
assert rej and "unknown stat" in rej[0]["reason"]
c, rej = V.validate({"check": {"stat": "Agility", "dc": 12}}, store, stats=stats)
assert not rej and c["check"]["stat"] == "Agility"
print("10) made-up check stats rejected; real ones pass")

print("\nWAVE 2 TESTS PASSED")
