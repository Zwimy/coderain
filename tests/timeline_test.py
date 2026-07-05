"""Feature 7: fold-aligned timeline + pointer-back recall.

Each fold appends one shorthand line tagged with its source-turn range; scene
entries carry a `turns:` attr; turns_range/recall_turns fetch the exact verbatim
turns; and folded ranges stay stable across a later retry/undo on the tail.
"""
import os, sys, shutil, tempfile, json, re
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from coderain.memory import Library
from coderain.summarizer import Summarizer

root = os.path.join(tempfile.gettempdir(), "se_timeline")
if os.path.exists(root): shutil.rmtree(root)
lib = Library(root)
store = lib.store(lib.create_story("TL", "A courier crossing a haunted moor."))

SCENE_JSON = json.dumps({
    "scene_summary": "You crossed the moor and met [[character:kaelen]].",
    "timeline": "Crossed the moor; met [[character:kaelen]] at the cairn.",
})

class FakeLLM:
    def complete(self, messages):
        return SCENE_JSON

class Cfg:
    memory = {"medium_fold_after": 4, "medium_fold_size": 2,
              "long_fold_after": 99, "long_fold_size": 2}
    generation = {}

# 10 turns -> folds of 2 at folded=0,2,4 (10-6=4 not >4) => ranges T1-2, T3-4, T5-6.
for i in range(5):
    store.append_turn("player", f"action {i}")
    store.append_turn("narrator", f"narration {i}")
events = Summarizer(Cfg(), store, FakeLLM()).maybe_fold()

# ---- 1) one timeline line per fold, with the right [Ta-b] tags ----
tl = store.read("memory/timeline.md")
tags = re.findall(r"\[T(\d+)-(\d+)\]", tl)
assert tags == [("1", "2"), ("3", "4"), ("5", "6")], tags
assert tl.count("\n- [T") == 3, tl
print("1) timeline: one tagged line per fold:", tags)

# ---- 2) scene entries carry a turns: attr matching the range ----
scenes = store.entries("memory/scenes.md")
assert [s.attrs.get("turns") for s in scenes] == ["1-2", "3-4", "5-6"], \
    [s.attrs.get("turns") for s in scenes]
print("2) scenes stamped with turns: attr")

# ---- 3) turns_range returns exactly those verbatim turns ----
r = store.turns_range(3, 4)
assert [t["text"] for t in r] == ["action 1", "narration 1"], r
assert store.turns_range(1, 2)[0]["text"] == "action 0"
assert store.turns_range(99, 100) == []          # out of range -> empty
print("3) turns_range returns exact verbatim turns")

# ---- 4) recall_turns resolves range / scene slug / keyword ----
by_range = store.recall_turns("T3-4")
assert "action 1" in by_range and "narration 1" in by_range, by_range
by_scene = store.recall_turns("scene-2")
assert "action 1" in by_scene, by_scene              # scene-2 == T3-4
by_kw = store.recall_turns("kaelen")                 # matches a timeline line
assert "PLAYER" in by_kw or "NARRATOR" in by_kw, by_kw
assert "No timeline entry" in store.recall_turns("zzz-nonexistent")
print("4) recall_turns: range / scene / keyword all resolve")

# ---- 5) folded ranges are stable across a retry/undo on the tail ----
before = store.recall_turns("T1-2")
store.drop_last_turns(2)          # undo the last (unfolded) exchange, turns 9-10
assert store.recall_turns("T1-2") == before, "folded pointer shifted after undo"
assert [t["text"] for t in store.turns_range(1, 2)] == ["action 0", "narration 0"]
print("5) folded pointers immutable across tail undo")

# ---- 6) migration: a save with no timeline.md gets one seeded on open ----
s2 = lib.store(lib.create_story("TL2", "premise"))
os.remove(s2.path("memory/timeline.md"))
reopened = lib.store("tl2")
assert reopened.path("memory/timeline.md").exists(), "timeline.md not re-seeded"
print("6) missing timeline.md re-seeded on open")

print("\nTIMELINE TESTS PASSED")
