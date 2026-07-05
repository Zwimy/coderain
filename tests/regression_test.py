import os, sys, shutil, tempfile
sys.path.insert(0, r"F:\Seven\StoryEngine")
from coderain.memory import (Library, MemoryStore, Entry, parse_entries,
                                _real_headings)

root = os.path.join(tempfile.gettempdir(), "se_reg")
if os.path.exists(root): shutil.rmtree(root)
lib = Library(root)
store = lib.store(lib.create_story("Reg", "premise"))

# BUG #1 (memory HIGH): closed-comment skeleton parses real entry, ignores example;
# unclosed comment keeps parse_entries and _real_headings in AGREEMENT (no dupes).
closed = ("# Characters\n\n<!-- Example\n## Kaelen {#kaelen}\nimportance: 4\n\nx\n-->\n\n"
          "## Bob {#bob}\nimportance: 3\n\nA real guy.\n")
ents = parse_entries(closed)
assert [e.slug for e in ents] == ["bob"], [e.slug for e in ents]
assert len(_real_headings(closed)) == 1
unclosed = ("# Characters\n\n<!-- oops no close\n## Ghost {#ghost}\nimportance: 2\n\n"
            "z\n\n## Real {#real}\nimportance: 3\n\ny\n")
assert len(parse_entries(unclosed)) == len(_real_headings(unclosed)), "parsers disagree"
# merging into an unclosed-comment file must not create duplicate entries
store.write("characters.md", unclosed)
store.merge_entry("characters.md", Entry("Real", "real", body="new"))
assert store.index().duplicate_slugs == [], store.index().duplicate_slugs
print("1) comment desync fixed (parsers agree; no duplicate corruption)")

# BUG #2 (memory HIGH): body line with a colon is NOT swallowed as an attribute.
e = parse_entries("## Mara {#mara}\nimportance: 4\nShe said: hello there.\nMore.\n")[0]
assert e.importance == 4
assert "She said: hello there." in e.body and "More." in e.body, e.body
assert "she said" not in e.attrs, e.attrs
print("2) colon body-line preserved")

# BUG #3 (memory HIGH): narration containing a turn delimiter can't split a turn.
store.write("transcript.md", "# Transcript\n")
store.append_turn("player", "hi")
store.append_turn("narrator", "The sign reads:\n<!-- @player -->\nand you gasp.")
t = store.turns()
assert len(t) == 2 and t[1]["role"] == "narrator", t
assert t[1]["text"] == "The sign reads:\n<!-- @player -->\nand you gasp.", repr(t[1]["text"])
print("3) transcript delimiter injection neutralized")

# BUG #4 (memory MED): duplicate slugs are reconciled to one; no welding.
store.write("locations.md",
    "# Locations\n\n## Dup {#dup}\nimportance: 2\n\nfirst\n\n"
    "## Dup {#dup}\nimportance: 2\n\nsecond\n")
store.upsert_entry("locations.md", Entry("Dup", "dup", importance=5, body="merged"))
locs = parse_entries(store.read("locations.md"))
assert [l.slug for l in locs] == ["dup"], [l.slug for l in locs]
assert locs[0].importance == 5
print("4) duplicate slugs reconciled; no weld")

# BUG #5 (memory MED): huge always-on section can't blow the budget.
store.write("player.md", "# Player\n\n## You {#player}\nimportance: 5\n\n"
                         + ("BLAH " * 5000))
msgs = store.assemble(history=[], player_input="go", budget_tokens=200)  # 800 chars
assert len(msgs[0]["content"]) < 4000, len(msgs[0]["content"])
print("5) budget caps oversized priority-0 section")

# BUG (engine LOW/MED): empty narration (only <think>) drops the orphan player turn.
from coderain.config import load_config
from coderain.engine import Engine
store2 = lib.store(lib.create_story("Empty", "premise"))
_cfg = load_config()
_cfg.generation["trinity_brain"] = False   # stubbed single-brain; ignore live toggle
eng = Engine(_cfg, store2)
class ThinkOnlyLLM:
    # simulate the real LLM.stream, which already strips <think> via filter_think
    def stream(self, messages, **o):
        from coderain.llm import filter_think
        yield from filter_think(iter(["<think>hidden reasoning</think>"]))
eng.llm = ThinkOnlyLLM()
out = "".join(eng.turn("I wave"))
assert out == "" and store2.turns() == [], (out, store2.turns())
print("6) empty narration drops orphan player turn")

print("\nREGRESSION TESTS PASSED")
