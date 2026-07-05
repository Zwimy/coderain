"""Feature 4: staged scenario auto-generator (fast + rich modes, loud failures).

Stubbed LLMs return canned JSON per stage (detected by the "STAGE:" marker in the
system prompt). Covers: fast batched mode; rich per-entity mode (each call sees the
roster of already-created entities); premise failure ABORTS with no scenario; a
zero-entity stage retries once and reports a shortfall warning; player.md untouched;
FictionLab shape — generated INTRODUCTION lands as `## Opening` (the save's first
message) and the opt-in prompt improver rewrites the brief before generation.
"""
import os, sys, shutil, tempfile, json
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from coderain import templates
from coderain.generator import (GenerationError, ScenarioSpec,
                                   generate_scenario)
from coderain.memory import Library, MemoryStore

root = os.path.join(tempfile.gettempdir(), "se_gen")
if os.path.exists(root): shutil.rmtree(root)
lib = Library(root)

def char(i):
    return {"slug": f"npc-{i}", "title": f"NPC {i}", "aliases": [f"n{i}"],
            "importance": 3, "status": "wary",
            "visual": f"Weathered face {i}.", "mentality": "Cautious, tests you.",
            "voice": 'Clipped. e.g. "State your name."',
            "skills": [{"name": "blade", "stat": "strength"}],
            "stats": {"strength": 3, "agility": 2},
            "relationships": [{"with": "npc-0", "note": "rival"}],
            "detail": f"History and agenda of NPC {i}."}

def loc(i):
    return {"slug": f"loc-{i}", "title": f"Loc {i}", "importance": 3,
            "detail": f"A place {i}."}

def item(i):
    return {"slug": f"item-{i}", "title": f"Item {i}", "importance": 2,
            "detail": f"A thing {i}."}

PREMISE = {"title": "Ashfall Reach", "premise": "You arrive at a dying port.",
           "world_bible": "Salt, smugglers, a drowned god.",
           "tone_lock": "grim maritime noir",
           "factions": [{"slug": "dockers", "title": "The Dockers", "importance": 3,
                         "detail": "A smugglers' union."}]}
THREADS = {"threads": [{"slug": "the-debt", "title": "The Debt", "importance": 4,
                        "detail": "You owe the harbourmaster."}],
           "canon_events": [{"slug": "the-drowning", "title": "The Drowning",
                             "importance": 5, "detail": "A ship sank with the crew."}]}
INTRO = {"introduction": "Salt spray needles your face as the gangplank drops. "
                         "The harbourmaster is already walking toward you."}

N_NPC, N_LOC, N_ITEM = 3, 2, 2

class FastStub:
    def complete(self, messages, **kw):
        s = messages[0]["content"]
        if "STAGE: premise" in s:    return json.dumps(PREMISE)
        if "STAGE: characters" in s: return json.dumps({"characters": [char(i) for i in range(N_NPC)]})
        if "STAGE: locations" in s:  return json.dumps({"locations": [loc(i) for i in range(N_LOC)]})
        if "STAGE: items" in s:      return json.dumps({"items": [item(i) for i in range(N_ITEM)]})
        if "STAGE: threads" in s:    return json.dumps(THREADS)
        if "STAGE: introduction" in s: return json.dumps(INTRO)
        return "{}"

spec = ScenarioSpec(type="pirate adventure", tone="grim", premise="a dying port",
                    n_npcs=N_NPC, n_locations=N_LOC, n_items=N_ITEM, detail="fast")
slug = generate_scenario(lib, FastStub(), spec)

# ---- 1) fast mode: created + counts + facets + stats attr ----
assert lib.scenarios.exists(slug)
store = MemoryStore(lib.scenarios.dir(slug))
chars_md = store.entries("characters.md")
assert len(chars_md) == N_NPC and len(store.entries("locations.md")) == N_LOC \
    and len(store.entries("items.md")) == N_ITEM
for e in chars_md:
    assert "**Visual:**" in e.body and "**Voice:**" in e.body, e.body
    assert e.attrs.get("skills") == "blade (strength)"
    assert e.attrs.get("stats") == "strength 3, agility 2", e.attrs
    assert "History and agenda" in e.body          # detail paragraph kept
assert any(e.slug == "dockers" for e in store.entries("factions.md"))
assert any(e.slug == "the-debt" for e in store.entries("threads.md"))
assert generate_scenario.last_warnings == [], generate_scenario.last_warnings
print("1) fast mode: counts + facets + stats + no warnings")

# ---- 2) player.md untouched ----
player_md = (lib.scenarios.dir(slug) / "player.md").read_text(encoding="utf-8")
assert player_md == templates.FILE_SKELETONS["player.md"]
print("2) player.md untouched")

# ---- 3) rich mode: one call per entity, each sees the growing roster ----
class RichStub:
    def __init__(self):
        self.char_calls = 0
        self.saw_roster = False
    def complete(self, messages, **kw):
        s = messages[0]["content"]
        u = messages[1]["content"] if len(messages) > 1 else ""
        if "STAGE: premise" in s:
            return json.dumps(PREMISE)
        if "STAGE: characters" in s:
            i = self.char_calls
            self.char_calls += 1
            if i > 0 and "npc-0" in u:      # later calls see earlier entities
                self.saw_roster = True
            return json.dumps(char(i))       # ONE object per call in rich mode
        if "STAGE: locations" in s:
            assert "npc-0" in u, "locations must see the cast roster"
            return json.dumps(loc(0))
        if "STAGE: items" in s:
            return json.dumps(item(0))
        if "STAGE: threads" in s:
            return json.dumps(THREADS)
        if "STAGE: introduction" in s:
            return json.dumps(INTRO)
        return "{}"

rich = RichStub()
slug2 = generate_scenario(lib, rich, ScenarioSpec(
    type="x", n_npcs=2, n_locations=1, n_items=1, detail="rich"))
st2 = MemoryStore(lib.scenarios.dir(slug2))
assert rich.char_calls == 2, rich.char_calls          # one call per NPC
assert rich.saw_roster, "rich calls did not receive the roster"
assert len(st2.entries("characters.md")) == 2
print("3) rich mode: per-entity calls, roster chained through")

# ---- 4) premise failure ABORTS, creates nothing ----
class DeadStub:
    def complete(self, messages, **kw):
        return "I refuse to answer with JSON."
before = {s["slug"] for s in lib.scenarios.list()}
try:
    generate_scenario(lib, DeadStub(), ScenarioSpec(type="void"))
    raise AssertionError("premise failure did not raise")
except GenerationError as e:
    assert "no scenario was created" in str(e).lower() or "Premise" in str(e)
assert {s["slug"] for s in lib.scenarios.list()} == before, "junk scenario created"
print("4) premise failure aborts cleanly")

# ---- 5) zero-entity stage: one corrective retry, then a shortfall warning ----
class FlakyStub:
    def __init__(self): self.char_tries = 0
    def complete(self, messages, **kw):
        s = messages[0]["content"]
        if "STAGE: premise" in s: return json.dumps(PREMISE)
        if "STAGE: characters" in s:
            self.char_tries += 1
            return "not json"                # every character attempt fails
        if "STAGE: locations" in s: return json.dumps({"locations": [loc(0)]})
        if "STAGE: items" in s: return json.dumps({"items": [item(0)]})
        if "STAGE: threads" in s: return json.dumps(THREADS)
        if "STAGE: introduction" in s: return json.dumps(INTRO)
        return "{}"

fl = FlakyStub()
slug3 = generate_scenario(lib, fl, ScenarioSpec(
    type="y", n_npcs=1, n_locations=1, n_items=1, detail="fast"))
assert any("characters" in w for w in generate_scenario.last_warnings), \
    generate_scenario.last_warnings
assert fl.char_tries >= 2, "no corrective retry happened"   # emit retry + batch retry
assert len(MemoryStore(lib.scenarios.dir(slug3)).entries("locations.md")) == 1
print("5) zero-entity stage retried once + shortfall warning surfaced")

# ---- 6) a save created FROM the generated scenario carries the entities ----
save_slug = lib.saves.create("Playthrough", slug)
sv = lib.store(save_slug)
assert len(sv.entries("characters.md")) == N_NPC, "save missed generated characters"
assert len(sv.entries("locations.md")) == N_LOC
assert any(e.slug == "the-debt" for e in sv.entries("threads.md"))
assert "dying port" in sv.read("premise.md")
print("6) new save picks up all generated files")

# ---- 7) introduction = ## Opening = the save's verbatim first message ----
scen_premise = (lib.scenarios.dir(slug) / "premise.md").read_text(encoding="utf-8")
assert "## Opening" in scen_premise and "gangplank drops" in scen_premise
assert sv.opening_override() == INTRO["introduction"], sv.opening_override()
print("7) generated introduction is the scenario's ## Opening (first message)")

# ---- 8) opt-in prompt improver rewrites the brief before generation ----
class ImproveStub(FastStub):
    def __init__(self):
        self.improved = 0
        self.premise_brief = ""
    def complete(self, messages, **kw):
        s = messages[0]["content"]
        if "STAGE: prompt improver" in s:
            self.improved += 1
            assert "vague boat idea" in messages[1]["content"]
            return json.dumps({"type": "maritime heist",
                               "tone": "salt-bitten noir",
                               "premise": "A cursed lighthouse blinks a code "
                                          "only debtors can read."})
        if "STAGE: premise" in s:
            self.premise_brief = messages[1]["content"]
        return super().complete(messages, **kw)

imp = ImproveStub()
slug4 = generate_scenario(lib, imp, ScenarioSpec(
    type="boat thing", premise="vague boat idea", detail="fast",
    n_npcs=0, n_locations=0, n_items=0, improve=True))
assert imp.improved == 1, "improver stage did not run"
assert "cursed lighthouse" in imp.premise_brief, \
    "premise stage did not receive the improved brief"
imp2 = ImproveStub()
generate_scenario(lib, imp2, ScenarioSpec(
    type="boat thing", premise="vague boat idea", detail="fast",
    n_npcs=0, n_locations=0, n_items=0, improve=False))
assert imp2.improved == 0, "improver ran without opt-in"
print("8) prompt improver: opt-in only, improved brief feeds generation")

print("\nGENERATOR TESTS PASSED")
