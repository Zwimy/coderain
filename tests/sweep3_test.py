"""Round-3 fixes: adjustable start clock at save creation, world import round-trip,
continue-the-prose engine path, and the lore-keeper on/off settings mapping.
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, r"F:\Seven\StoryEngine")
from coderain import templates                       # noqa: E402
from coderain.memory import Entry, Library, MemoryStore  # noqa: E402

root = os.path.join(tempfile.gettempdir(), "se_sweep3")
if os.path.exists(root):
    shutil.rmtree(root)
lib = Library(root)


def _state(slug):
    return json.loads((lib.saves.root / slug / "state.json")
                      .read_text(encoding="utf-8"))


# ---- 1) default start is still Day 1 / morning ----
s0 = lib.saves.create("Plain Start", premise="A quiet village.")
t0 = _state(s0)["time"]
assert t0["day"] == 1 and t0["phase"] == "morning", t0
print("1) default clock unchanged (Day 1, morning)")

# ---- 2) a story can begin on any day/phase with a fictional calendar note ----
s1 = lib.saves.create("Late Start", premise="Mid-siege.", start_time={
    "day": 47, "phase": "dusk", "note": "3rd of Frostmoon, Year 812"})
t1 = _state(s1)["time"]
assert t1["day"] == 47, t1
assert t1["phase"] == "dusk", t1
assert t1["note"] == "3rd of Frostmoon, Year 812", t1
clock = lib.saves.store(s1).clock_str()
assert "Day 47" in clock and "dusk" in clock, clock
assert "Frostmoon" in clock, clock
print("2) custom start day/phase/calendar seed the clock and clock_str")

# ---- 3) garbage start_time degrades to defaults, never crashes ----
s2 = lib.saves.create("Bad Start", premise="x", start_time={
    "day": "not-a-number", "phase": 5, "note": None})
t2 = _state(s2)["time"]
assert t2["day"] == 1 and t2["phase"] == "morning", t2
print("3) malformed start_time falls back to defaults")

# ---- 4) world export -> import round-trip yields a playable copy ----
wslug = lib.scenarios.create("Salt Reach", premise="A drowned coast city.",
                             world="Tides rule everything here.")
dest = os.path.join(root, "world-export.zip")
lib.scenarios.export(wslug, dest)
new_slug = lib.scenarios.import_(dest)
assert new_slug != wslug, new_slug
assert lib.scenarios.exists(new_slug), new_slug
prem = (lib.scenarios.dir(new_slug) / "premise.md").read_text(encoding="utf-8")
assert "drowned coast" in prem, prem
# a save can be started from the imported world
sfrom = lib.saves.create("Play Import", scenario_slug=new_slug)
assert (lib.saves.root / sfrom / "premise.md").exists()
print("4) world export -> import -> new world -> playable save")

# ---- 5) importing a non-world zip is rejected cleanly ----
import zipfile                                          # noqa: E402
junk = os.path.join(root, "junk.zip")
with zipfile.ZipFile(junk, "w") as z:
    z.writestr("random.txt", "nope")
try:
    lib.scenarios.import_(junk)
    raise AssertionError("should have rejected a non-world zip")
except ValueError as e:
    assert "scenario.json" in str(e), e
print("5) import rejects an archive with no scenario.json")

# ---- 6) continue_story extends prose with no player turn appended ----
from coderain.config import load_config             # noqa: E402
from coderain.engine import Engine                  # noqa: E402


class _StreamStub:
    """Single-brain LLM double: streams a fixed line so a narrator turn stores."""
    def __init__(self): self.calls = 0
    def stream(self, *a, **k):
        self.calls += 1
        for w in ("Rain", " keeps", " falling."):
            yield w
    def complete(self, *a, **k):
        return "Rain keeps falling."


cfg = load_config()
cfg.generation["trinity_brain"] = False                # single-brain path
sc = lib.saves.create("Continue Me", premise="Standing in the rain.")
eng = Engine(cfg, lib.saves.store(sc))
eng.llm = _StreamStub()
eng.store.append_turn("narrator", "The rain drums on the tin roof.")
turns_before = eng.store.turns()
n_player_before = sum(1 for t in turns_before if t["role"] == "player")
out = "".join(eng.continue_story())
turns_after = eng.store.turns()
n_player_after = sum(1 for t in turns_after if t["role"] == "player")
assert n_player_after == n_player_before, "continue must not add a player turn"
assert turns_after[-1]["role"] == "narrator", turns_after[-1]
assert len(turns_after) == len(turns_before) + 1, (len(turns_before), len(turns_after))
assert "Rain" in out, out
print("6) continue_story appends only a narrator turn (no player line)")

# ---- 7) a save's world pieces are editable INDEPENDENTLY of the scenario ----
def _scen_store(sl):
    return MemoryStore(lib.scenarios.dir(sl), None, lib.scenarios.dir(sl))


wslug2 = lib.scenarios.create("Ember Hold", premise="A keep under siege.")
scen_store = _scen_store(wslug2)
scen_store.upsert_entry("characters.md", Entry(
    title="Captain Rode", slug="captain-rode", aliases=[], importance=4,
    attrs={}, body="Grizzled defender of the gate."))
save_from = lib.saves.create("Siege Run", scenario_slug=wslug2)
ss = lib.saves.store(save_from)
# the character copied into the save
assert any(e.slug == "captain-rode" for e in ss.entries("characters.md"))
# edit the SAVE's copy
ss.upsert_entry("characters.md", Entry(
    title="Captain Rode", slug="captain-rode", aliases=["Roro"], importance=5,
    attrs={"status": "wounded"}, body="Wounded, but still holding the gate."))
edited = next(e for e in ss.entries("characters.md") if e.slug == "captain-rode")
assert edited.attrs.get("status") == "wounded", edited.attrs
# the SCENARIO's original is untouched (divergence)
orig = next(e for e in _scen_store(wslug2).entries("characters.md")
            if e.slug == "captain-rode")
assert orig.attrs.get("status") != "wounded", orig.attrs
assert "Grizzled" in orig.body, orig.body
print("7) save world pieces edit independently of the scenario copy")

# ---- 8) ST-03 in-place turn edit ----
se = lib.saves.create("Edit Me", premise="A hush before the storm.")
st = lib.saves.store(se)
st.append_turn("player", "I wait.")
st.append_turn("narrator", "Thunder rolls in the distance.")
assert st.update_turn(1, "Thunder CRACKS overhead.") is True
assert st.turns()[1]["text"] == "Thunder CRACKS overhead.", st.turns()
assert st.turns()[0]["text"] == "I wait.", st.turns()   # sibling untouched
assert st.update_turn(9, "x") is False                  # out of range
print("8) update_turn edits one turn in place, guards range")

# ---- 9) ST-02 swipe browse cycles cached variants without a model call ----
cfg2 = load_config()
cfg2.generation["trinity_brain"] = False
sw = lib.saves.create("Swipe Me", premise="Rain on tin.")
eng2 = Engine(cfg2, lib.saves.store(sw))
eng2.store.append_turn("narrator", "Variant A.")
eng2._swipes = {"variants": ["Variant A.", "Variant B.", "Variant C."], "idx": 0}
out1 = eng2.swipe_browse(1)
assert out1 == {"text": "Variant B.", "idx": 1, "count": 3}, out1
assert eng2.store.turns()[-1]["text"] == "Variant B."   # transcript rewritten
out2 = eng2.swipe_browse(1)
assert out2["text"] == "Variant C." and out2["idx"] == 2
assert eng2.swipe_browse(1)["idx"] == 2                  # clamps at the end
assert eng2.swipe_browse(-1)["text"] == "Variant B."
print("9) swipe_browse cycles cached variants + rewrites the tail turn")

# ---- 10) ST-04 impersonate returns text and stores nothing ----
imp = lib.saves.create("Impersonate", premise="Standing at a locked door.")
eng3 = Engine(load_config(), lib.saves.store(imp))
eng3.trinity = None


class _ImpStub:
    def stream(self, *a, **k):
        for w in ("I", " try", " the", " handle."):
            yield w
eng3.llm = _ImpStub()
before = len(eng3.store.turns())
suggestion = eng3.impersonate()
assert "handle" in suggestion, suggestion
assert len(eng3.store.turns()) == before, "impersonate must not store a turn"
print("10) impersonate drafts player action, stores nothing")

print("\nSWEEP3 TESTS PASSED")
