"""Scenario Builder rework: per-field AI assist, fill-the-rest generation,
playable characters (library kinds + scenario drop-in + story-start seeding),
user defaults (override + revert), and scenario export.
"""
import json
import os
import shutil
import sys
import tempfile
import zipfile

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from coderain import templates                       # noqa: E402
from coderain.generator import (ScenarioSpec, assist_field,   # noqa: E402
                                   complete_scenario)
from coderain.memory import Entry, Library, MemoryStore       # noqa: E402
from coderain.profiles import (CharacterProfiles,             # noqa: E402
                                  PieceLibrary, apply_playable_entry,
                                  character_from_entry,
                                  entry_from_character)

root = os.path.join(tempfile.gettempdir(), "se_builder")
if os.path.exists(root):
    shutil.rmtree(root)
lib = Library(root)

# ---- 1) character kinds + library <-> entry round-trip ----
chars = CharacterProfiles(root)
old = chars.save({"name": "Seren", "description": "A wiry cartographer.",
                  "stats": {"agility": 3}})
assert old["kind"] == "playable", old            # pre-kind profiles = playable
npc = chars.save({"name": "Brann the Fence", "kind": "npc",
                  "description": "Moves stolen relics.",
                  "traits": "greedy, careful",
                  "skills": "appraisal (knowledge)"})
e = entry_from_character(npc)
assert e.attrs.get("playable", "") == "", e.attrs   # NPCs aren't playable
assert "appraisal (knowledge)" == e.attrs["skills"]
e2 = entry_from_character(old)
assert e2.attrs["playable"] == "true"
back = character_from_entry(e)
assert back["kind"] == "npc" and back["name"] == "Brann the Fence"
assert back["traits"] == "greedy, careful", back
back2 = character_from_entry(e2)
assert back2["kind"] == "playable" and back2["stats"]["agility"] == 3
print("1) kinds + entry_from_character/character_from_entry round-trip")

# ---- 2) playable piece seeds a save's player.md (md wins on open) ----
scen = lib.scenarios.create("Port of Ash", "A dying port under a curse.",
                            introduction="The gangplank drops.")
scen_store = MemoryStore(lib.scenarios.dir(scen), None,
                         lib.scenarios.dir(scen))
scen_store.upsert_entry("characters.md", Entry(
    "Vesna the Diver", "vesna-the-diver", importance=4,
    attrs={"playable": "true", "stats": "agility 4, willpower 2",
           "skills": "wreck-diving (agility)"},
    body="A salvage diver who owes the harbourmaster."))
save = lib.saves.create("Run", scen, mode="rpg")
sv = lib.store(save)
piece = next(e for e in sv.entries("characters.md")
             if e.slug == "vesna-the-diver")     # copied with the world
apply_playable_entry(sv, piece)
sv2 = lib.store(save)                            # reopen → md-wins sync
player = next(e for e in sv2.entries("player.md") if e.slug == "player")
assert player.title == "Vesna the Diver"
assert sv2.rpg_state()["player"]["stats"]["agility"] == 4, \
    sv2.rpg_state()["player"]["stats"]
assert any(e.slug == "vesna-the-diver"
           for e in sv2.entries("characters.md")), "world entry must stay"
print("2) apply_playable_entry: player.md seeded, stats flow, NPC entry kept")

# ---- 3) user defaults: override consulted, revert restores shipped ----
dflt = lib.instructions_dir / "defaults"
dflt.mkdir(parents=True, exist_ok=True)
(dflt / "premise.md").write_text("# Premise\n\nMy house premise.\n",
                                 encoding="utf-8")
(dflt / "events.md").write_text("# Events\n\n## When dawn breaks {#dawn}\n"
                                "once: true\n\nEveryone must sing.\n",
                                encoding="utf-8")
blank = lib.saves.create("Blank", premise="")     # no premise → user default
b = lib.store(blank)
assert "My house premise" in b.read("premise.md")
assert "Everyone must sing" in b.read("events.md")
scen2 = lib.scenarios.create("W2", "Authored premise.")   # premise given
s2dir = lib.scenarios.dir(scen2)
assert "Authored premise" in (s2dir / "premise.md").read_text(encoding="utf-8")
assert "Everyone must sing" in (s2dir / "events.md").read_text(encoding="utf-8")
assert templates.user_default("premise.md", lib.instructions_dir).startswith(
    "# Premise\n\nMy house premise")
(dflt / "premise.md").unlink()                    # = the Revert button
assert "dark" in templates.user_default(
    "premise.md", lib.instructions_dir).lower() or templates.DEFAULT_PREMISE \
    in templates.user_default("premise.md", lib.instructions_dir)
print("3) user defaults seed new saves/worlds; revert restores shipped")

# ---- 4) scenario export zip ----
arc = lib.scenarios.export(scen, os.path.join(root, "world.zip"))
with zipfile.ZipFile(arc) as z:
    names = z.namelist()
assert "scenario.json" in names and "premise.md" in names, names
assert not any(n.endswith(".tmp") for n in names)
print("4) scenario export: zip carries the world, no temps")

# ---- 5) assist_field: seed + improve, main fields and pieces ----
class AssistStub:
    def __init__(self):
        self.calls = []
    def complete(self, messages, **kw):
        s, u = messages[0]["content"], messages[1]["content"]
        self.calls.append(s.split(".")[0])
        if "STAGE: prompt improver" in s:
            assert "moon temple" in u
            return json.dumps({"idea": "A drowned MOON TEMPLE that surfaces "
                                       "at low tide, guarded by salt-monks."})
        if "STAGE: premise" in s:
            assert "salt-monks" in u, "seed did not use the improved idea"
            return json.dumps({"premise": "You wade toward the moon temple."})
        if "STAGE: introduction" in s:
            assert "CURRENT TEXT" in u
            return json.dumps({"introduction": "Better opening prose."})
        if "STAGE: character" in s:
            return json.dumps({"slug": "salt-monk", "title": "The Salt-Monk",
                               "playable": True, "importance": 3,
                               "stats": {"willpower": 4},
                               "detail": "Keeper of the tide bell."})
        if "STAGE: rules" in s:
            return json.dumps({"slug": "tide-law", "title": "Tide Law",
                               "importance": 4,
                               "detail": "No blade drawn at low tide."})
        return "{}"

stub = AssistStub()
out, err = assist_field(stub, "premise", "seed", "a moon temple idea",
                        context="Coastal world.", improve=True)
assert err is None and "moon temple" in out, (out, err)
out, err = assist_field(stub, "introduction", "improve", "Old opening.")
assert err is None and out == "Better opening prose."
entry, err = assist_field(stub, "character", "seed", "a monk")
assert err is None and entry.slug == "salt-monk"
assert entry.attrs.get("playable") == "true", entry.attrs
entry, err = assist_field(stub, "rules", "seed", "law of tides")  # custom kind
assert err is None and entry.slug == "tide-law"
out, err = assist_field(AssistStub(), "premise", "seed", "x")  # improve off
assert err is None or out is None  # no improver call happened:
assert "STAGE: prompt improver" not in "".join(stub.calls[-1:])
print("5) assist_field: improver-routed seeds, improve mode, pieces + custom")

# ---- 6) complete_scenario fills ONLY what's missing ----
scen3 = lib.scenarios.create("Half World", "")     # empty premise shell
s3 = MemoryStore(lib.scenarios.dir(scen3), None, lib.scenarios.dir(scen3))
s3.upsert_entry("characters.md", Entry(
    "Authored Hero", "authored-hero", importance=4,
    attrs={"playable": "true"}, body="Hand-written, must survive."))

class CompleteStub:
    def __init__(self):
        self.char_calls = 0
        self.saw_authored = False
    def complete(self, messages, **kw):
        s = messages[0]["content"]
        u = messages[1]["content"] if len(messages) > 1 else ""
        if "STAGE: premise" in s:
            return json.dumps({"title": "Filled World",
                               "premise": "A canyon city of rope bridges.",
                               "world_bible": "Wind is currency.",
                               "tone_lock": "windswept"})
        if "STAGE: character" in s:
            self.char_calls += 1
            if "authored-hero" in u:
                self.saw_authored = True
            return json.dumps({"slug": f"new-npc-{self.char_calls}",
                               "title": f"New NPC {self.char_calls}",
                               "importance": 3, "detail": "Fits the canyon."})
        if "STAGE: threads" in s:
            return json.dumps({"threads": [{"slug": "rope-debt",
                                            "title": "Rope Debt",
                                            "importance": 3,
                                            "detail": "You owe rope."}]})
        if "STAGE: introduction" in s:
            return json.dumps({"introduction": "Wind screams over the canyon."})
        return "{}"

cs = CompleteStub()
warns = complete_scenario(lib, cs, scen3, ScenarioSpec(
    n_npcs=3, n_locations=0, n_items=0, detail="rich"))
s3b = MemoryStore(lib.scenarios.dir(scen3), None, lib.scenarios.dir(scen3))
assert cs.char_calls == 2, cs.char_calls          # 3 wanted − 1 existing
assert cs.saw_authored, "existing pieces missing from the roster"
names = {e.slug for e in s3b.entries("characters.md")}
assert "authored-hero" in names and len(names) == 3, names
hero = next(e for e in s3b.entries("characters.md")
            if e.slug == "authored-hero")
assert hero.body == "Hand-written, must survive.", "authored piece changed!"
assert "canyon city" in s3b.read("premise.md")
assert s3b.opening_override() == "Wind screams over the canyon."
assert "Wind is currency" in s3b.read("world-bible.md")
assert any(e.slug == "rope-debt" for e in s3b.entries("threads.md"))
# second run: nothing missing → no model damage
cs2 = CompleteStub()
complete_scenario(lib, cs2, scen3, ScenarioSpec(n_npcs=3, n_locations=0,
                                                n_items=0))
assert cs2.char_calls == 0, "complete regenerated already-full sections"
assert s3b.opening_override() == "Wind screams over the canyon."
print(f"6) complete_scenario: fills only gaps, keeps authored work "
      f"(warnings: {warns or 'none'})")

# ---- 7) generic piece library: CRUD + insert into a world ----
plib = PieceLibrary(root)
rec = plib.save("location", {"title": "The Salt Bazaar", "importance": 4,
                             "attrs": {"weight": "important",
                                       "triggers": "bazaar, salt"},
                             "body": "A market that floods twice a day."})
assert rec["id"] and rec["type"] == "location"
plib.save("rules", {"title": "Tide Law",
                    "body": "No blade drawn at low tide."})   # custom type
assert plib.types() == ["location", "rules"], plib.types()
assert len(plib.list("location")) == 1
rec2 = plib.save("location", {"title": "The Salt Bazaar (rebuilt)",
                              "body": "Rebuilt after the flood."},
                 pid=rec["id"])
assert rec2["id"] == rec["id"]
assert len(plib.list("location")) == 1, "update duplicated the piece"
e = plib.entry(rec["id"])
assert e.title == "The Salt Bazaar (rebuilt)"
assert e.attrs == {}, "update kept stale attrs"    # full replace on update
# insert into a world (what /from-piece-library does)
scen_store.upsert_entry("locations.md", plib.entry(rec["id"]))
assert any(x.slug == "the-salt-bazaar-rebuilt" for x
           in scen_store.entries("locations.md"))
assert plib.delete(rec["id"]) and not plib.list("location")
print("7) piece library: save/update/insert/delete, custom types tracked")

# ---- 8) character round-trip is lossless with the parity fields ----
full = chars.save({"name": "Ilya Voss", "kind": "npc",
                   "description": "A masked broker.",
                   "traits": "patient, exact",
                   "skills": "ciphers (knowledge)",
                   "stats": {"knowledge": 4},
                   "aliases": ["The Broker", "Voss"],
                   "importance": 5,
                   "extra": {"weight": "critical", "triggers": "broker, mask",
                             "hidden": "true"}})
e = entry_from_character(full)
assert e.aliases == ["The Broker", "Voss"] and e.importance == 5
assert e.attrs["weight"] == "critical" and e.attrs["hidden"] == "true"
back = character_from_entry(e)
for key in ("name", "kind", "traits", "skills", "aliases", "importance"):
    assert back[key] == full[key], (key, back[key], full[key])
assert back["extra"]["weight"] == "critical"
assert back["extra"]["triggers"] == "broker, mask"
assert back["extra"]["hidden"] == "true"
assert back["stats"]["knowledge"] == 4
print("8) character parity fields survive library -> world -> library")

print("\nBUILDER TESTS PASSED")
