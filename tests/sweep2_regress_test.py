"""Second-sweep findings, and the regressions the FIRST fix pass introduced.

Four of these were caused by the fixes for the first sweep. That is the point of
a second pass, and the reason each one is pinned here rather than trusted.

Asserts:
 1) undo after a Continue drops ONE turn (no player turn sits behind it);
 2) an unreadable scene range cannot rewind the fold pointer;
 3) find_marker survives a non-length-preserving lowercase (Turkish İ);
 4) an empty enemy spec still reaches rpg.apply (spawn at defaults);
 5) npc_state / trust / location / reveal are bounded like the rest;
 6) NaN and Infinity cannot be written into a flag;
 7) a promoted title or alias containing a newline cannot split the entry;
 8) a re-listed thread does not reopen a resolved one;
 9) packing stays MONOTONIC: a bigger budget never drops what a smaller kept.
"""
import json
import math
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
HOME = tempfile.mkdtemp(prefix="cr-sw2-")
os.environ["CODERAIN_HOME"] = HOME

from coderain import sidecar as sc  # noqa: E402
from coderain import validator as V  # noqa: E402
from coderain.config import load_config  # noqa: E402
from coderain.engine import Engine  # noqa: E402
from coderain.memory import (Entry, Library, _read_event_log,  # noqa: E402
                             _reconcile_fold_state)

lib = Library(os.path.join(HOME, "lib"))
cfg = load_config()
cfg.generation["trinity_brain"] = False


def _story(name):
    return lib.store(lib.create_story(name, "A courier crosses a frozen kingdom."))


class _Stub:
    def __init__(self, payload):
        self.payload = payload

    def complete(self, messages, **kw):
        return self.payload

    def stream(self, messages, **kw):
        return iter([self.payload])


# ---- 1) undo after a Continue -------------------------------------------
s1 = _story("Continue")
e1 = Engine(cfg, s1)
s1.append_turn("player", "I walk on")
s1.append_turn("narrator", "The road bends.")
e1._pre_turn_rpg = e1._snapshot_rpg()
e1.apply_envelope({"v": 1, "deltas": {"gold_delta": 10}}, False)
s1.append_turn("narrator", "A CONTINUE, no player turn.")   # continue_story
e1._pre_turn_rpg = e1._snapshot_rpg()
e1.apply_envelope({"v": 1, "deltas": {"gold_delta": 10}}, False)
gold_before, log_before = s1.world_state()["player"]["gold"], len(_read_event_log(s1))
assert e1.undo_last()
roles = [t["role"] for t in s1.turns()]
assert roles == ["player", "narrator"], (
    f"undo after a Continue dropped a turn it did not own: {roles}")
assert s1.world_state()["player"]["gold"] == gold_before - 10, s1.world_state()
assert len(_read_event_log(s1)) == log_before - 1, (
    "the ledger was truncated further than the state was rolled back")
print("1) undo after a Continue drops exactly the narration it owns")

# ---- 2) an unreadable range cannot rewind the pointer --------------------
s2 = _story("Rewind")
for i in range(1, 13):
    s2.append_turn("player" if i % 2 else "narrator", f"turn {i}")
for n in range(1, 5):
    s2.upsert_entry("memory/scenes.md", Entry(
        f"Scene {n}", f"scene-{n}", attrs={"turns": f"{n * 2 - 1}-{n * 2}"},
        body=f"Scene {n}."))
s2.write_state({**s2.state(), "folded_turns": 8})
# strip the ranges, as a pre-Wave-2 save or a hand-edit would
for e in s2.entries("memory/scenes.md"):
    e.attrs.pop("turns", None)
    s2.upsert_entry("memory/scenes.md", e)
_reconcile_fold_state(s2)
assert s2.state()["folded_turns"] == 8, (
    f"an unreadable range rewound the pointer to {s2.state()['folded_turns']}; "
    "the whole transcript would re-fold into duplicate scenes")
print("2) a scene with no readable range leaves the fold pointer alone")

# ---- 3) find_marker under a non-length-preserving lowercase --------------
assert len("İ".lower()) == 2, "precondition: İ folds to two code points"
text = ("İİİİİİİ she said.\n\n```RPG\n"
        '{"v":1,"deltas":{"hp_delta":-3}}\n```')
assert sc.find_marker(text) == text.index("```RPG"), sc.find_marker(text)
visible, side = sc.strip_sidecar(text)
assert "```" not in visible, f"the fence leaked into the prose: {visible!r}"
assert side and side["deltas"]["hp_delta"] == -3, side
hidden = []
out = "".join(sc.filter_sidecar(iter([text]), hidden))
assert "```" not in out, f"the fence was streamed to the reader: {out!r}"
assert sc.parse_sidecar("".join(hidden)) is not None, "the diverted text won't parse"
print("3) a dotted-capital-I before the fence no longer shifts the index")

# ---- 4) an empty enemy spec still spawns --------------------------------
store = _story("Enemies")
clean, rejected = V.validate({"v": 1, "deltas": {"enemies": {"goblin": {}}}}, store)
assert clean.get("deltas", {}).get("enemies", {}) == {"goblin": {}}, clean
print("4) an empty enemy spec survives validation (rpg.apply defaults it)")

# ---- 5) the remaining unbounded deltas ----------------------------------
big = {"v": 1, "deltas": {
    "npc_state": {f"npc-{i}": {"mood": "x" * 50_000} for i in range(500)},
    "trust": {f"c-{i}": 3 for i in range(500)},
    "location": "L" * 200_000,
    "reveal": [f"nope-{i}" for i in range(5000)],
}}
clean, rejected = V.validate(big, store)
d = clean.get("deltas", {})
assert len(d.get("npc_state", {})) <= V.LIST_CAP, len(d.get("npc_state", {}))
assert all(len(v.get("mood", "")) <= V.STR_CAP for v in d.get("npc_state", {}).values())
assert len(d.get("trust", {})) <= V.LIST_CAP, len(d.get("trust", {}))
assert len(d.get("location", "")) <= V.STR_CAP + 20, len(d.get("location", ""))
assert len(rejected) <= V.LIST_CAP * 4, (
    f"{len(rejected)} rejection records; rejection_text() is sent to the Director "
    "as the re-ask payload and would blow its context")
print(f"5) npc_state/trust/location/reveal bounded ({len(rejected)} rejects)")

# ---- 6) non-finite flags -------------------------------------------------
clean, rejected = V.validate(
    {"v": 1, "deltas": {"flag_set": {"a": float("nan"), "b": float("inf"),
                                     "ok": True}}}, store)
flags = clean.get("deltas", {}).get("flag_set", {})
assert "a" not in flags and "b" not in flags, flags
assert flags.get("ok") is True, flags
json.dumps(flags, allow_nan=False)          # must not raise
print("6) NaN/Infinity are refused, so state.json stays valid JSON")

# ---- 7) a newline in a promoted title or alias --------------------------
s7 = _story("Titles")
e7 = Engine(cfg, s7)
e7.llm = _Stub('{"scene_summary": "s", "timeline": "t", "promotions": ['
               '{"kind": "character", "slug": "keeper",'
               ' "title": "Alira, Keeper\\n(the Warden)",'
               ' "aliases": ["the pale one\\nthe Warden"],'
               ' "status": "waiting", "wants": "to cross",'
               ' "detail": "She keeps the bridge."}]}')
e7.summarizer.llm = e7.llm
e7.summarizer._apply_promotions(e7.summarizer._emit_json("x", "y"))
chars = s7.entries("characters.md")
assert len(chars) == 1, f"the entry split in two: {[c.slug for c in chars]}"
k = chars[0]
assert k.slug == "keeper", k.slug
assert k.attrs.get("wants") == "to cross", k.attrs
assert all("\n" not in a for a in k.aliases), k.aliases
print(f"7) a multiline title/alias keeps one entry with its attrs ({k.title!r})")

# ---- 8) a re-listed thread does not reopen -----------------------------
s8 = _story("Threads")
e8 = Engine(cfg, s8)
s8.upsert_entry("threads.md", Entry("Sealed Box", "sealed-box",
                                    attrs={"status": "resolved"},
                                    body="It was opened."))
e8.llm = _Stub('{"scene_summary": "s", "timeline": "t", "new_threads": ['
               '{"slug": "sealed-box", "title": "Sealed Box",'
               ' "detail": "Mentioned again."}]}')
e8.summarizer.llm = e8.llm
e8.summarizer._apply_promotions(e8.summarizer._emit_json("x", "y"))
box = next(e for e in s8.entries("threads.md") if e.slug == "sealed-box")
assert box.attrs.get("status") == "resolved", (
    f"a re-mention reopened a resolved thread: {box.attrs}")
print("8) re-listing a resolved thread does not reopen it")

# ---- 9) packing is monotonic in the budget -----------------------------
s9 = _story("Monotone")
s9.write("memory/arc.md", "# Arc synopsis (long-term)\n\n" + ("Arc detail. " * 330))
s9.write("world-bible.md", "# World\n\n" + ("Every stone is named. " * 545))
seen = {}
for tok in range(2000, 5200, 200):
    txt = s9.assemble(history=[], player_input="x", budget_tokens=tok)[0]["content"]
    seen[tok] = "## World" in txt
first_in = next((t for t, ok in sorted(seen.items()) if ok), None)
assert first_in is not None, "the world bible never appeared at any budget"
lost = [t for t, ok in sorted(seen.items()) if t > first_in and not ok]
assert not lost, (
    f"non-monotonic: World is present at {first_in} tokens but MISSING at {lost} "
    "— raising the budget silently deleted a section")
print(f"9) packing is monotonic (World enters at {first_in} tokens and stays)")

shutil.rmtree(HOME, ignore_errors=True)
print("\nSECOND-SWEEP REGRESSION TESTS PASSED")
