"""Wave 4: event instructions, opening override, response controls, branching.

Covers: event rules reach the Director ONLY (never the Writer); event_fired
legality (unknown/consumed rejected), once-rules consumed + undo un-consumes;
consumed rules leave the block; '## Opening' used verbatim (no model call);
length knob + custom-instructions style directives; branch: transcript
truncation, state replay to the fork point, fold/timeline filtering, snapshot
restore vs no-snapshot warning, original untouched. (Editor tab is covered in
gui_editor_test.py.)
"""
import os, sys, shutil, tempfile, json
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from coderain import validator as V
from coderain.config import load_config
from coderain.engine import Engine
from coderain.memory import Entry, Library

root = os.path.join(tempfile.gettempdir(), "se_wave4")
if os.path.exists(root): shutil.rmtree(root)
lib = Library(root)
save = lib.saves.create("Vault", mode="rpg", premise="A heist on a sealed vault.")
store = lib.store(save)
st = store.rpg_state(); st["seed"] = 3
store.set_rpg_state(st)
store.upsert_entry("events.md", Entry(
    "When the vault door opens", "vault-alarm", importance=4,
    attrs={"once": "true"},
    body="A silent alarm summons the wardens within three turns."))

cfg = load_config()
cfg.generation["trinity_brain"] = True
cfg.raw["trinity"] = {}
eng = Engine(cfg, store)

# ---- 1) event rules: Director sees them, Writer never does ----
class EventStub:
    def complete(self, messages, **k):
        assert any("SCENARIO EVENT RULES" in m["content"] for m in messages), \
            "director missing event rules"
        assert any("vault-alarm" in m["content"] for m in messages)
        return json.dumps({"beat_plan": "The door creaks open.",
                           "envelope": {"v": 1,
                                        "deltas": {"event_fired": ["vault-alarm"]}}})

    def stream(self, messages, **k):
        # The writer may see rpg-rules (which DOCUMENTS event_fired), but the
        # actual rule content must never reach it.
        joined = " ".join(m["content"] for m in messages)
        assert "vault-alarm" not in joined and "silent alarm" not in joined, \
            "event rule content leaked to the writer!"
        yield "The vault exhales stale air."

stub = EventStub()
eng.llm = stub
eng.trinity.director_llm = stub
eng.trinity.writer_llm = stub
out = "".join(eng.turn("open the vault door"))
assert out == "The vault exhales stale air."
rule = next(e for e in store.entries("events.md") if e.slug == "vault-alarm")
assert rule.attrs.get("consumed") == "true", "once-rule not consumed"
assert store.event_rules() == [], "consumed rule still active"
assert "vault-alarm" not in store.event_rules_block()
print("1) event rules: director-only injection; once-rule fired + consumed")

# ---- 2) undo un-consumes ----
assert eng.undo_last()
rule = next(e for e in store.entries("events.md") if e.slug == "vault-alarm")
assert rule.attrs.get("consumed") == "false"
assert len(store.event_rules()) == 1
print("2) undo un-consumes the fired rule")

# ---- 3) event_fired legality ----
_c, rej = V.validate({"deltas": {"event_fired": ["no-such-rule"]}}, store)
assert rej and "no such event rule" in rej[0]["reason"]
store.mark_event_consumed("vault-alarm")
_c, rej = V.validate({"deltas": {"event_fired": ["vault-alarm"]}}, store)
assert rej and "already consumed" in rej[0]["reason"]
store.mark_event_consumed("vault-alarm", False)
print("3) event_fired: unknown + already-consumed rejected")

# ---- 4) opening override: verbatim, no model call ----
save2 = lib.saves.create("Greeted", mode="simple", premise="A doorstep mystery.")
store2 = lib.store(save2)
store2.write("premise.md", store2.read("premise.md")
             + "\n## Opening\n\nYou wake to three knocks. The door is already "
               "open.\n")
cfg2 = load_config()
cfg2.generation["trinity_brain"] = False
eng2 = Engine(cfg2, store2)

class NeverLLM:
    def stream(self, messages, **k):
        raise AssertionError("model called despite an authored opening")

eng2.llm = NeverLLM()
opening = "".join(eng2.opening())
assert opening.startswith("You wake to three knocks")
assert store2.turns()[-1]["text"] == opening
print("4) '## Opening' used verbatim — zero model calls")

# ---- 5) response controls: length knob + custom instructions ----
cfg3 = load_config()
cfg3.generation["trinity_brain"] = False
cfg3.generation["response_length"] = "short"
eng3 = Engine(cfg3, store2)
msgs = eng3._messages([], "hello")
assert "STYLE DIRECTIVES" in msgs[0]["content"]
assert "TIGHT" in msgs[0]["content"]
store2.write("custom-instructions.md",
             store2.read("custom-instructions.md") + "\nAlways address the "
             "player as 'Detective'.\n")
msgs = eng3._messages([], "hello")
assert "Detective" in msgs[0]["content"]
cfg3.generation["response_length"] = "medium"
eng3b = Engine(cfg3, store2)
msgs = eng3b._messages([], "hello")
assert "TIGHT" not in msgs[0]["content"]          # medium adds no length line
assert "Detective" in msgs[0]["content"]          # custom persists
print("5) length knob + per-save custom instructions in the system prompt")

# ---- 6) branching: snapshot restore + replay + filtering ----
save3 = lib.saves.create("Long Road", mode="rpg", premise="A long road east.")
store3 = lib.store(save3)
st3 = store3.rpg_state(); st3["seed"] = 5
store3.set_rpg_state(st3)
cfg4 = load_config()
cfg4.generation["trinity_brain"] = False
cfg4.memory["medium_fold_after"] = 4
cfg4.memory["medium_fold_size"] = 2

class RoadLLM:
    def __init__(self): self.n = 0
    def stream(self, messages, **k):
        self.n += 1
        yield f"Mile {self.n} passes."
    def complete(self, messages, **k):          # summarizer folds
        return json.dumps({"scene_summary": "Miles pass.",
                           "timeline": "the road east"})

eng4 = Engine(cfg4, store3)
eng4.llm = RoadLLM()
eng4.summarizer.llm = eng4.llm
for i in range(5):
    "".join(eng4.turn(f"walk mile {i + 1}"))
    eng4.apply_envelope({"v": 1, "deltas": {"gold_delta": 10}}, rpg_on=True)
    eng4.maybe_fold()
total = len(store3.turns())
assert total == 10 and store3.world_state()["player"]["gold"] == 50
assert (store3.dir / ".snapshots").exists(), "folds should have snapshotted"

new_slug, warns = lib.saves.branch(save3, 6, cfg4.rpg)
bstore = lib.store(new_slug)
assert bstore.title.startswith("(BRANCH)") and "@T6" in bstore.title
assert len(bstore.turns()) == 6
# state replayed to the fork: 3 completed exchanges -> 3 gold applications
assert bstore.world_state()["player"]["gold"] == 30, \
    bstore.world_state()["player"]["gold"]
# no scene/timeline entry may cover turns beyond 6
for sc in bstore.entries("memory/scenes.md"):
    rng = sc.attrs.get("turns", "0-0")
    assert int(rng.split("-")[1]) <= 6, rng
assert "[T7" not in bstore.read("memory/timeline.md")
# original untouched
assert len(store3.turns()) == 10
assert store3.world_state()["player"]["gold"] == 50
print(f"6) branch @T6: transcript 6 turns, gold 30, folds filtered "
      f"(warnings: {warns or 'none'})")

# ---- 7) branch past retention: loud warning, state still rebuilt ----
shutil.rmtree(store3.dir / ".snapshots")
new2, warns2 = lib.saves.branch(save3, 4, cfg4.rpg)
assert warns2 and "post-branch knowledge" in warns2[0]
b2 = lib.store(new2)
assert len(b2.turns()) == 4
assert b2.world_state()["player"]["gold"] == 20   # rebuilt from the full log
print("7) no snapshot: warned about memory bleed; state rebuilt from the log")

print("\nWAVE 4 TESTS PASSED")
