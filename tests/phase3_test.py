import os, sys, shutil, tempfile, json
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from coderain.memory import Library, Entry, EDITABLE_FILES
from coderain.summarizer import Summarizer

root = os.path.join(tempfile.gettempdir(), "se_p3")
if os.path.exists(root): shutil.rmtree(root)
lib = Library(root)
store = lib.store(lib.create_story("P3", "A hedge-witch with a debt."))

# 0) state.json seeded; clock reads default
assert store.path("state.json").exists()
assert store.clock_str() == "Day 1, morning", store.clock_str()
assert "state.json" in EDITABLE_FILES
# assemble injects the clock
msgs = store.assemble(history=[], player_input="look")
assert "Current in-world time: Day 1, morning" in msgs[0]["content"]
print("0) clock seeded + injected into context")

# pre-existing character to be REWRITTEN (not appended)
store.write("characters.md",
    "# Characters\n\n## Kaelen {#kaelen}\naliases: the knight\nimportance: 3\n"
    "status: wary\n\nOld identity text.\n")
for i in range(5):
    store.append_turn("player", f"I greet the knight ({i})")
    store.append_turn("narrator", f"Kaelen the knight nods ({i}).")

SCENE = json.dumps({
    "scene_summary": "You spoke with [[character:kaelen]] at dusk.",
    "time": {"day": 3, "phase": "evening"},
    "promotions": [{"kind": "character", "slug": "kaelen", "title": "Kaelen",
                    "aliases": ["Ser Kaelen"], "importance": 4, "status": "wounded",
                    "when": "Day 3, evening",
                    "relationships": [{"with": "you", "note": "owes a debt"}],
                    "detail": "Grim knight, now wounded after the duel."}],
    "new_threads": [], "resolved_threads": [],
})

class FakeLLM:
    def complete(self, messages):
        payload = messages[1]["content"]
        # rewrite-mode: the model must be shown existing entities
        assert "EXISTING ENTITIES" in payload, "existing context not provided"
        assert "kaelen" in payload.lower(), "relevant entity not shown"
        return SCENE

class Cfg:
    memory = {"medium_fold_after": 4, "medium_fold_size": 2,
              "long_fold_after": 99, "long_fold_size": 2}
    generation = {}

events = Summarizer(Cfg(), store, FakeLLM()).maybe_fold()

# 1) REWRITE not append: body replaced, aliases unioned, importance bumped
k = {e.slug: e for e in store.entries("characters.md")}["kaelen"]
assert k.body == "Grim knight, now wounded after the duel.", k.body
assert "Old identity text." not in k.body, "append instead of rewrite"
assert set(k.aliases) == {"the knight", "Ser Kaelen"}, k.aliases
assert k.importance == 4 and k.attrs.get("status") == "wounded"
print("1) rewrite-style promotion OK (body replaced, aliases unioned)")

# 2) relationships parsed + in graph
assert k.relationships() == [("you", "owes a debt")], k.relationships()
assert "kaelen" in store.index().relationships()
print("2) relationships recorded + graph OK")

# 3) in-world time advanced + stamped
assert store.clock_str() == "Day 3, evening", store.clock_str()
assert json.loads(store.read("state.json"))["time"]["day"] == 3
scenes = store.entries("memory/scenes.md")
assert scenes and scenes[0].attrs.get("when") == "Day 3, evening", scenes[0].attrs
# and the new clock now shows in assembled context
assert "Day 3, evening" in store.assemble([], "x")[0]["content"]
print("3) time advanced, scene stamped, clock in context")

print("\nevents:", [e for e in events if "time" in e or "promoted" in e][:3])
print("PHASE 3 TESTS PASSED")
