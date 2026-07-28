"""Sixth-sweep findings, from two auditors run in parallel.

Two of these are corrections to bounds added in sweep 4 — clamping an absolute
day, and slicing a joined attr line — which fixed the size problem and created a
correctness one. A bound that silently mangles is not obviously better than no
bound, and both were caught only because the next sweep attacked the last one's
fixes.

Asserts:
 1) a swipe cancelled MID-STREAM cannot leave swipe state pointing at the
    exchange it deleted (the cleanup is in a finally, not after the yield);
 2) the ledger truncation on undo is by COUNT, so a record surviving a second
    consecutive undo cannot be deleted by a later, unrelated one;
 3) an opening that writes no prose is rolled back whole;
 4) retrying the opening regenerates an OPENING, and keeps an authored greeting;
 5) companion_chat streams every chunk, and survives an empty stream;
 6) rolled-back deltas do not appear in the UI event list;
 7) a fold-created slug is bounded to exactly what the validator will look up;
 8) a chapter title containing a newline cannot collide two chapters onto one
    slug;
 9) an out-of-range fold day is REJECTED, not clamped, so it cannot pin the
    clock and freeze every later fold;
10) a joined attr line is cut at an item boundary, never mid-token, and says
    what it dropped.
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
HOME = tempfile.mkdtemp(prefix="cr-sw6-")
os.environ["CODERAIN_HOME"] = HOME

from coderain import validator as V  # noqa: E402
from coderain.config import load_config  # noqa: E402
from coderain.engine import Engine  # noqa: E402
from coderain.memory import Entry, Library, _read_event_log  # noqa: E402
from coderain.planner import ChapterPlanner  # noqa: E402
from coderain.summarizer import Summarizer  # noqa: E402

lib = Library(os.path.join(HOME, "lib"))
cfg = load_config()
cfg.generation["trinity_brain"] = False


def _story(name, premise="A courier crosses a frozen kingdom."):
    return lib.store(lib.create_story(name, premise))


def _llm(*chunks):
    return type("L", (), {"stream": lambda self, m, **k: iter(chunks),
                          "complete": lambda self, m, **k: "".join(chunks)})()


class _Stub:
    def __init__(self, payload):
        self.payload = payload

    def complete(self, m, **k):
        return self.payload

    def stream(self, m, **k):
        return iter([self.payload])


# ---- 1) a swipe cancelled mid-stream ------------------------------------
s1 = _story("SwipeStop")
e1 = Engine(cfg, s1)
for role, text in (("player", "I greet the guard"), ("narrator", "PREV he nods."),
                   ("player", "I ask about the pass"),
                   ("narrator", "SWIPED he points north.")):
    s1.append_turn(role, text)
assert e1._ensure_swipes() is not None
e1.llm = _llm("half a sentence", " and the rest")
it = e1.swipe_generate()
next(it)
it.close()          # exactly what srv/core.py's `finally: it.close()` does
assert e1._swipes is None, (
    f"swipe state outlived the exchange it describes: {e1._swipes}")
e1.swipe_browse(-1)
assert [t["text"] for t in s1.turns()] == ["I greet the guard", "PREV he nods."], (
    f"browse wrote one exchange's prose over another's turn: {s1.turns()}")
print("1) a swipe cancelled mid-stream leaves no stale swipe state")

# ---- 2) undo truncates the ledger by count, not by turn number ----------
s2 = _story("Undo")
e2 = Engine(cfg, s2)


def _sidecar_turn(eng, store, player, flag):
    eng.llm = _llm(f'```rpg\n{{"v":1,"deltas":{{"flag_set":{{"{flag}":true}}}}}}\n```')
    list(eng.turn(player))


s2.append_turn("player", "start")
s2.append_turn("narrator", "The road bends.")
_sidecar_turn(e2, s2, "A", "sold_horse")
_sidecar_turn(e2, s2, "B", "bought_cloak")
assert e2.undo_last()
assert e2.undo_last()          # D-002: no snapshot left, so no truncation
_sidecar_turn(e2, s2, "C", "met_smith")
assert e2.undo_last()
flags = {k for k, v in (s2.world_state().get("flags") or {}).items() if v}
logged = set()
for rec in _read_event_log(s2):
    logged |= set((rec.get("env") or {}).get("deltas", {}).get("flag_set", {}))
assert flags <= logged, (
    f"state has flags {flags - logged} that no ledger record describes — a "
    "branch rebuilds a different save than the one it came from")
print("2) undo truncates the ledger by count, so an old record survives")

# ---- 3) a prose-less opening is rolled back whole -----------------------
s3 = _story("Opening")
e3 = Engine(cfg, s3)
e3.llm = _llm('```rpg\n{"v":1,"deltas":{"flag_set":{"met_smith":true}}}\n```')
assert "".join(e3.opening()).strip() == ""
assert s3.turns() == [], s3.turns()
assert not (s3.world_state().get("flags") or {}), (
    "an opening that wrote nothing kept its deltas, logged at turn 0 where the "
    "record collides with genesis, survives every truncation, and is filtered "
    "out of every branch")
assert [r for r in _read_event_log(s3) if (r.get("env") or {}).get("deltas")] == []
print("3) an opening that writes no prose is rolled back whole")

# ---- 4) retrying the opening regenerates an opening --------------------
s4 = _story("Retry", "A tale.\n\n## Opening\nAUTHORED GREETING: snow on the gate.")
e4 = Engine(cfg, s4)
e4.llm = _llm("model prose, not the greeting")
list(e4.opening())
assert s4.turns()[-1]["text"].startswith("AUTHORED GREETING"), s4.turns()
ok, player_input = e4.rollback_for_retry()
assert ok and player_input is None
list(e4.regenerate(player_input))
assert s4.turns()[-1]["text"].startswith("AUTHORED GREETING"), (
    f"retrying the opening went through continue_story, which never consults "
    f"opening_override(): {s4.turns()}")
print("4) retrying the opening regenerates an opening, greeting intact")

# ---- 5) companion_chat streams every chunk -----------------------------
s5 = _story("Talk")
s5.upsert_entry("characters.md", Entry("Mara", "mara", importance=4,
                                       attrs={"companion": "true"},
                                       body="A spymaster."))
e5 = Engine(cfg, s5)
e5.llm = _llm("Keep ", "your ", "hood ", "up.")
assert "".join(e5.companion_chat("Mara", "what now?")) == "Keep your hood up.", (
    "only the last chunk reached the client")
e5.llm = _llm()
assert "".join(e5.companion_chat("Mara", "and now?")) == ""   # no UnboundLocalError
print("5) companion_chat streams every chunk and survives an empty stream")

# ---- 6) rolled-back deltas leave the UI event list ---------------------
s6 = _story("Events")
e6 = Engine(cfg, s6)
s6.append_turn("player", "I sell the horse")
s6.append_turn("narrator", "You pocket the coin.")
e6.llm = _llm('```rpg\n{"v":1,"deltas":{"flag_set":{"met_smith":true},'
              '"location":"gate"}}\n```')
list(e6.continue_story())
events = e6.maybe_fold()
assert not [ev for ev in events if "met_smith" in ev or "gate" in ev], (
    f"the done frame credits mechanics that were rolled back: {events}")
print("6) rolled-back deltas do not reach the event bar")

# ---- 7) a fold slug matches what the validator will look up ------------
s7 = _story("Slug")
long_slug = "the-sealed-vault-beneath-the-winter-palace-" + "x" * 200
sm7 = Summarizer(cfg, s7, _Stub(""))
sm7._apply_promotions({"new_threads": [
    {"slug": long_slug, "title": "The Vault", "detail": "Still sealed."}]})
on_disk = [e.slug for e in s7.entries("threads.md")]
assert on_disk, "the thread was not written at all"
clean, rejected = V.validate(
    {"v": 1, "deltas": {"quest_update": {long_slug: "active"}}}, s7)
assert (clean.get("deltas") or {}).get("quest_update"), (
    f"the validator cannot address a thread the fold just wrote: on disk "
    f"{on_disk[0][:60]}..., rejected {rejected}")
print("7) a fold-written slug is addressable by every delta channel")

# ---- 8) a chapter title with a newline cannot collide two chapters -----
s8 = _story("Outline")
s8.write("premise.md", "A courier crosses a frozen kingdom carrying a box.")
cfg8 = load_config()
cfg8.generation["chapter_plan"] = True
cfg8.generation["chapter_horizon"] = 3
p8 = ChapterPlanner(cfg8, s8, _Stub(json.dumps({"chapters": [
    {"title": "The Road\nNorth", "goal": "Reach the pass."},
    {"title": "The Road\nSouth", "goal": "Turn back."},
    {"title": "The Pass", "goal": "Cross."}]})))
p8.seed()
slugs = [c.slug for c in p8.chapters()]
assert slugs == ["ch-1", "ch-2", "ch-3"], (
    f"a newline in the title broke the entry header: {slugs}")
for c in p8.chapters():
    assert c.attrs.get("status"), f"attrs fell into the body: {c.slug} {c.attrs}"
    assert "{#ch-" not in c.body, f"the anchor leaked into the goal: {c.body!r}"
print("8) a newline in a chapter title cannot collide two chapters")

# ---- 9) an out-of-range fold day is rejected, not clamped -------------
s9 = _story("Clock")
st = s9.world_state()
st["time"] = {"day": 3, "phase": "morning"}
s9.set_world_state(st)
sm9 = Summarizer(cfg, s9, _Stub(""))
sm9._apply_time({"time": {"day": 10 ** 9, "phase": "evening"}})
assert s9.world_state()["time"]["day"] == 3, (
    f"clamping pinned the clock at {s9.world_state()['time']['day']}, and the "
    "monotonic guard makes that permanent")
assert "fold-time" in s9.read("memory/health.jsonl"), "and it was silent"
# the decisive half: a later truthful fold must still work
sm9._apply_time({"time": {"day": 4, "phase": "dawn", "note": "cold"}})
assert s9.world_state()["time"]["phase"] == "dawn", s9.world_state()["time"]
print("9) an out-of-range fold day is rejected and the clock keeps working")

# ---- 10) joined attr lines cut at item boundaries ---------------------
s10 = _story("Index")
for i in range(1, 5):
    s10.append_turn("player" if i % 2 else "narrator", f"turn {i}")
names = [f"captain-marlow-of-the-red-harbour-{i:02d}" for i in range(30)]
sm10 = Summarizer(cfg, s10, _Stub(json.dumps({
    "scene_summary": "They argued on the quay.", "characters": names})))
sm10._fold_scene(s10.turns(), 1, 1)
idx = s10.entries("memory/scenes.md")[0].attrs.get("characters", "")
for part in idx.split(", "):
    assert part in names, f"a mid-token cut left the phantom key {part!r}"
assert "fold" in s10.read("memory/health.jsonl"), "the dropped names were silent"
print("10) a joined attr line is cut between items, and says what it dropped")

shutil.rmtree(HOME, ignore_errors=True)
print("\nSWEEP 6 FINDINGS: ALL CLOSED")
