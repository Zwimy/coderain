import os, sys, shutil, tempfile, json
sys.path.insert(0, r"F:\Seven\StoryEngine")
from coderain.memory import Library, Entry
from coderain.summarizer import Summarizer

root = os.path.join(tempfile.gettempdir(), "se_p3s")
if os.path.exists(root): shutil.rmtree(root)
lib = Library(root)
store = lib.store(lib.create_story("P3S", "premise"))

# A-H1: snapshot backs up state.json (clock is recoverable on undo)
store.set_world_state({"time": {"day": 5, "phase": "night"}})
snap = store.snapshot()
assert (snap / "state.json").exists(), "state.json not in snapshot"
assert json.loads((snap / "state.json").read_text())["time"]["day"] == 5
print("A-H1) snapshot includes state.json")

# A-H2: rewrite makes managed keys authoritative; non-managed preserved
store.write("characters.md",
    "# Characters\n\n## Kael {#kael}\nimportance: 3\nstatus: ally\n"
    "when: Day 1\nrelationships: mara: friend\nfaction: ash-guard\n\nOld body.\n")
store.merge_entry("characters.md",
    Entry("Kael", "kael", importance=4, attrs={"status": "enemy"},
          body="New body, betrayal revealed."), rewrite=True)
k = {e.slug: e for e in store.entries("characters.md")}["kael"]
assert k.body == "New body, betrayal revealed.", k.body
assert k.attrs.get("status") == "enemy"                 # updated
assert "relationships" not in k.attrs, k.attrs          # dropped (not re-emitted)
assert "when" not in k.attrs, k.attrs                   # dropped
assert k.attrs.get("faction") == "ash-guard"           # non-managed, preserved
print("A-H2) rewrite: managed keys authoritative, custom attr preserved")

# B-H1: valid-but-wrong-shape state.json degrades instead of crashing
for bad in ['{"time":"evening"}', "[]", '"hi"', "not json at all", "42"]:
    store.write("state.json", bad)
    _ = store.clock_str()             # must not raise
    _ = store.assemble([], "go")      # must not raise
store.write("state.json", '{"time":"evening"}')
# Wave 1 lazy migration SELF-HEALS a non-dict time block to the default clock
# (previously it degraded to an empty clock string).
assert store.clock_str() == "Day 1", repr(store.clock_str())
print("B-H1) wrong-shape state.json self-heals, no crash")

# A-M1 + A-L2: note-only time persists; day:true is rejected
class Cfg:
    memory = {}; generation = {}
store.set_world_state({"time": {"day": 2, "phase": "dawn", "note": ""}})
sm = Summarizer(Cfg(), store, None)
ev = sm._apply_time({"time": {"note": "the storm breaks"}})
assert ev and store.world_state()["time"]["note"] == "the storm breaks", ev
assert store.world_state()["time"]["day"] == 2  # unchanged
ev2 = sm._apply_time({"time": {"day": True}})   # bool must not set the day
assert store.world_state()["time"]["day"] == 2 and ev2 == [], ev2
print("A-M1/L2) note-only persists; day:true rejected")

print("\nPHASE 3 SWEEP-FIX TESTS PASSED")
