"""Wave 3: RPG Campaign layer — inventory/gold, quest log, level-up grants,
companions + side-chat, story modes + beats.

Covers: gold overspend rejection + apply; inventory qty mirror + equip legality;
quest state machine + canon-on-completion + undo; npc_state; level-up banks a
grant, grant applies to state AND player.md, gated when nothing pending;
abilities feed skill_mod; sheet lines; simple mode skips the Logic Agent;
beats structure + beat_advance; companion side-chat stays out of the
transcript and surfaces as a digest; generator rarity attr.
"""
import os, sys, shutil, tempfile, json
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from coderain.modules import rpg as rpg_mod
from coderain import validator as V
from coderain.config import load_config
from coderain.engine import Engine
from coderain.generator import _entry_from
from coderain.memory import Entry, Library

root = os.path.join(tempfile.gettempdir(), "se_wave3")
if os.path.exists(root): shutil.rmtree(root)
lib = Library(root)
save = lib.saves.create("Campaign", mode="rpg", premise="A gritty border war.")
store = lib.store(save)
assert store.mode() == "rpg" and store.rpg_enabled()
st = store.rpg_state(); st["seed"] = 7
store.set_rpg_state(st)

cfg = load_config()
cfg.generation["trinity_brain"] = False

class Prose:
    def stream(self, messages, **k):
        yield "The border smolders."

eng = Engine(cfg, store)
eng.llm = Prose()

# ---- 1) gold: overspend rejected; earn + spend applies ----
_c, rej = V.validate({"deltas": {"gold_delta": -5}}, store)
assert rej and "not enough gold" in rej[0]["reason"]
"".join(eng.turn("loot the toll chest"))
ev = eng.apply_envelope({"v": 1, "deltas": {"gold_delta": 30}}, rpg_on=True)
assert any("gold: +30 → 30" in e for e in ev), ev
ev = eng.apply_envelope({"v": 1, "deltas": {"gold_delta": -12}}, rpg_on=True)
assert store.world_state()["player"]["gold"] == 18
print("1) gold: overspend rejected, earn/spend applied")

# ---- 2) inventory mirror: qty, equip legality, remove-to-zero ----
_c, rej = V.validate({"deltas": {"inventory_equip": ["iron-sword"]}}, store)
assert rej and "not held" in rej[0]["reason"]
eng.apply_envelope({"v": 1, "deltas": {
    "inventory_add": [{"slug": "iron-sword", "qty": 1}, "torch", "torch"]}},
    rpg_on=True)
inv = store.rpg_state()["inventory"]
assert inv["iron-sword"]["qty"] == 1 and inv["torch"]["qty"] == 2
ev = eng.apply_envelope({"v": 1, "deltas": {"inventory_equip": ["iron-sword"]}},
                        rpg_on=True)
assert store.rpg_state()["inventory"]["iron-sword"]["equipped"]
assert any(e.slug == "iron-sword" for e in store.entries("items.md"))
eng.apply_envelope({"v": 1, "deltas": {
    "inventory_remove": [{"slug": "torch", "qty": 2}]}}, rpg_on=True)
assert "torch" not in store.rpg_state()["inventory"]
assert not any(e.slug == "torch" for e in store.entries("items.md"))
print("2) inventory mirror: qty tracked, equip gated on holding, zero removes")

# ---- 3) quest log: machine + canon on completion + undo ----
store.upsert_entry("threads.md", Entry(
    "The Missing Courier", "missing-courier", importance=4,
    attrs={"type": "quest", "objectives": "find the courier; recover the satchel"}))
_c, rej = V.validate({"deltas": {"quest_update": {"missing-courier": "completed"}}},
                     store)
assert rej and "illegal transition" in rej[0]["reason"]
_c, rej = V.validate({"deltas": {"quest_update": {"ghost-quest": "active"}}}, store)
assert rej and "no such thread" in rej[0]["reason"]
eng.apply_envelope({"v": 1, "deltas": {"quest_update": {"missing-courier": "active"}}},
                   rpg_on=True)
assert store.world_state()["quests"]["missing-courier"] == "active"
"".join(eng.turn("bring the courier home"))
ev = eng.apply_envelope({"v": 1, "deltas": {
    "quest_update": {"missing-courier": "completed"}}}, rpg_on=True)
assert any("quest completed" in e for e in ev), ev
assert any(e.slug == "quest-missing-courier-completed"
           for e in store.entries("canon-events.md"))
assert eng.undo_last()
assert store.world_state()["quests"]["missing-courier"] == "active"
assert not any(e.slug == "quest-missing-courier-completed"
               for e in store.entries("canon-events.md"))
print("3) quest machine enforced; completion = canon event; undo reverts both")

# ---- 4) level-up banks a grant; grant applies to state + player.md; gated ----
_c, rej = V.validate({"deltas": {"ability_add": ["Riposte (agility)"]}}, store)
assert rej and "no level-up grant pending" in rej[0]["reason"]
ev = eng.apply_envelope({"v": 1, "deltas": {"xp_delta": 100}}, rpg_on=True)
assert store.rpg_state()["pending_grant"] == 1
assert any("ability or title pending" in e for e in ev)
_c, rej = V.validate({"deltas": {"ability_add": ["A"], "title_add": ["B"]}}, store)
assert rej and "only 1 grant" in str(rej)
ev = eng.apply_envelope({"v": 1, "deltas": {"ability_add": ["Riposte (agility)"]}},
                        rpg_on=True)
assert store.rpg_state()["pending_grant"] == 0
assert store.rpg_state()["player"]["abilities"] == ["Riposte (agility)"]
player_md = next(e for e in store.entries("player.md") if e.slug == "player")
assert player_md.attrs.get("abilities") == "Riposte (agility)"
assert rpg_mod.skill_mod(store, "player", "Riposte", cfg.rpg) == 2
print("4) grants: banked on level-up, gated, applied to state+md, feed skill_mod")

# ---- 5) sheet lines show the new layers ----
lines = rpg_mod.render_sheet_lines(store.rpg_state(), store.world_state())
assert "Gold   18" in lines and "iron-sword ×1  [E]" in lines
assert "— Abilities —" in lines and "Riposte (agility)" in lines
assert "— Quests —" in lines and "missing-courier" in lines
print("5) sheet: gold/inventory/abilities/quests rendered")

# ---- 6) companions: npc_state + side-chat out-of-band + digest ----
store.upsert_entry("characters.md", Entry(
    "Lyra", "lyra", importance=4, attrs={"companion": "true"},
    body="**Voice:** dry, clipped. e.g. \"Try not to die.\""))
eng.apply_envelope({"v": 1, "deltas": {"trust": {"lyra": 3},
                                       "npc_state": {"lyra": {"mood": "wary"}}}},
                   rpg_on=True)
c = store.rpg_state()["companions"]["lyra"]
assert c["trust"] == 3 and c["mood"] == "wary"
assert eng.companions() == ["lyra"]

class CompanionLLM:
    def stream(self, messages, **k):
        assert "You ARE Lyra" in messages[0]["content"]
        yield "Try not to die out there."

eng.llm = CompanionLLM()
turns_before = len(store.turns())
reply = "".join(eng.companion_chat("Lyra", "Any advice?"))
assert reply == "Try not to die out there."
assert len(store.turns()) == turns_before, "side-chat leaked into the transcript!"
assert "Try not to die" in store.read("memory/companion-chat.md")
eng.llm = Prose()
msgs = store.assemble([], "onward")
assert "Companion side-chat" in msgs[0]["content"]
print("6) companion: state applied; side-chat logged out-of-band; digest in context")

# ---- 7) beats: structure gates beat_advance; advance is monotonic + capped ----
_c, rej = V.validate({"deltas": {"beat_advance": True}}, store)
assert rej and "no beat structure" in rej[0]["reason"]
arc = store.read("memory/arc.md")
store.write("memory/arc.md", arc + "\n## Beats\n- Reach the border\n"
                                   "- Find the traitor\n- End the war\n")
assert store.beats() == ["Reach the border", "Find the traitor", "End the war"]
ev = eng.apply_envelope({"v": 1, "deltas": {"beat_advance": True}}, rpg_on=True)
assert store.world_state()["beat"] == 1 and any("beat → 2/3" in e for e in ev)
eng.apply_envelope({"v": 1, "deltas": {"beat_advance": 5}}, rpg_on=True)
assert store.world_state()["beat"] == 2, "beat must cap at the last one"
msgs = store.assemble([], "press on")
assert "Beat 3/3: End the war" in msgs[0]["content"]
print("7) beats: gated, monotonic, capped, steering line in context")

# ---- 8) simple mode: Logic Agent skipped in quad ----
save_s = lib.saves.create("Quiet Life", mode="simple", premise="A tea shop.")
store_s = lib.store(save_s)
assert store_s.mode() == "simple" and not store_s.rpg_enabled()
cfg_q = load_config()
cfg_q.generation["trinity_brain"] = True
cfg_q.raw["trinity"] = {}
eng_s = Engine(cfg_q, store_s)

class NoDirectorStub:
    def __init__(self): self.stages = []
    def complete(self, messages, **k):
        raise AssertionError("Logic Agent ran in simple mode")
    def stream(self, messages, **k):
        self.stages.append("writer")
        assert not any("DIRECTOR'S PLAN" in m["content"] for m in messages)
        yield "Steam curls from the kettle."

stub = NoDirectorStub()
eng_s.llm = stub
eng_s.trinity.director_llm = stub
eng_s.trinity.writer_llm = stub
out = "".join(eng_s.turn("open the shop"))
assert out == "Steam curls from the kettle." and stub.stages == ["writer"]
print("8) simple mode: one LLM call, no director, no directive")

# ---- 9) generator rarity attr ----
e = _entry_from({"slug": "moon-blade", "title": "Moon Blade",
                 "rarity": "Legendary", "detail": "A blade of moonlight."})
assert e.attrs.get("rarity") == "legendary"
assert _entry_from({"slug": "x", "title": "X", "rarity": "shiny",
                    "detail": "d"}).attrs.get("rarity") is None
print("9) generator emits validated rarity")

print("\nWAVE 3 TESTS PASSED")
