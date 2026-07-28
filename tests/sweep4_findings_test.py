"""Fourth-sweep findings, including one regression the third fix pass created.

Finding 2 was introduced by the commit that fixed the arc fold's silent pointer
advance: holding the pointer on failure left the loop condition permanently
true, and maybe_fold runs after every turn. That is the fourth time a fix in
this repo has produced a new defect, which is why every sweep gets another.

Asserts:
 1) an exchange that stores nothing does not leave its pre-turn snapshot live
    for the NEXT undo to consume against a different exchange;
 2) a persistently failing arc fold does not re-run every turn (no model-call
    storm, no snapshot churn, no health-log flood);
 3) the fold's episode-index attrs are bounded, so an oversized one cannot push
    its own scene summary out of the context budget;
 4) JSON with an integer literal past Python's digit limit degrades to None
    instead of raising a bare ValueError out of the turn;
 5) the fold cannot write an unbounded absolute in-world day;
 6) a promotion's alias LIST is bounded, not just each alias.

The SPA race (the Welcome gate returning without the stale-hash check) is pinned
by tests/webapp_smoke_test.py §4, which failed 5 runs in 6 before the fix and
6 in 6 after. It is not repeated here.
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
HOME = tempfile.mkdtemp(prefix="cr-sw4f-")
os.environ["CODERAIN_HOME"] = HOME

from coderain import sidecar as sc  # noqa: E402
from coderain.config import load_config  # noqa: E402
from coderain.engine import Engine  # noqa: E402
from coderain.llm import extract_json  # noqa: E402
from coderain.memory import Entry, Library, _read_event_log  # noqa: E402
from coderain.summarizer import Summarizer  # noqa: E402

lib = Library(os.path.join(HOME, "lib"))
cfg = load_config()
cfg.generation["trinity_brain"] = False


def _story(name):
    return lib.store(lib.create_story(name, "A courier crosses a frozen kingdom."))


class _Stub:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def complete(self, messages, **kw):
        self.calls += 1
        return self.payload

    def stream(self, messages, **kw):
        self.calls += 1
        return iter([self.payload])


# ---- 1) an aborted turn leaves no snapshot behind ------------------------
s1 = _story("Aborted")
e1 = Engine(cfg, s1)
s1.append_turn("player", "I sell the horse")
s1.append_turn("narrator", "You pocket the coin.")
e1._pre_turn_rpg = e1._snapshot_rpg()
e1.apply_envelope({"v": 1, "deltas": {"gold_delta": 50}}, False)
gold = s1.world_state()["player"]["gold"]
assert gold >= 50, s1.world_state()
log_before = len(_read_event_log(s1))
assert log_before >= 1
# Now a turn that produces nothing at all — a model error, or the client's Stop.
e1.llm = type("Empty", (), {"stream": lambda self, m, **k: iter([""])})()
assert "".join(e1.turn("I look around")) == ""
assert [t["role"] for t in s1.turns()] == ["player", "narrator"], s1.turns()
# ...and only now, an undo of the exchange BEFORE it.
assert e1.undo_last()
assert s1.world_state()["player"]["gold"] == gold - 50, (
    "the undo restored a snapshot belonging to the aborted turn")
assert len(_read_event_log(s1)) == log_before - 1, (
    "the ledger and the state disagree by an envelope: state.json still has the "
    "gold the ledger no longer describes, so a branch rebuilds a different save")
print("1) an exchange that stores nothing leaves no snapshot for the next undo")

# ---- 2) a failing arc fold does not re-run every turn --------------------
s2 = _story("ArcStorm")
for i in range(1, 41):
    s2.append_turn("player" if i % 2 else "narrator", f"turn {i}")
for k in range(1, 9):
    s2.upsert_entry("memory/scenes.md", Entry(
        f"Scene {k}", f"scene-{k}", attrs={"turns": f"{k * 2 - 1}-{k * 2}"},
        body=f"Scene {k} happened."))
st = s2.state()
st["folded_turns"], st["folded_scenes"] = 40, 0
s2.write_state(st)
e2 = Engine(cfg, s2)
stub2 = _Stub("not json at all")
e2.summarizer.llm = stub2
e2.summarizer.long_after = 2
e2.summarizer.long_size = 4
e2.summarizer.medium_after = 10_000
e2.summarizer.maybe_fold()
after_first = stub2.calls        # emit_json retries once internally, so 2 per attempt
assert after_first > 0
for _turn in range(5):
    e2.summarizer.maybe_fold()
assert stub2.calls == after_first, (
    f"the failing arc fold was re-attempted across 5 more turns "
    f"({after_first} -> {stub2.calls} calls) — one attempt AND one full story "
    "snapshot each, which evicts every real restore point within a few turns")
assert s2.read("memory/health.jsonl").count("arc-fold") == 1, (
    "one health line per turn floods the 200-line log and evicts every other "
    "degradation record")
# a NEW scene is what re-arms it — the same cadence it had when it advanced
s2.upsert_entry("memory/scenes.md", Entry(
    "Scene 9", "scene-9", attrs={"turns": "17-18"}, body="Scene 9 happened."))
e2.summarizer.maybe_fold()
assert stub2.calls > after_first, (
    f"a new scene must re-arm the retry; calls stuck at {stub2.calls}")
print("2) a failing arc fold retries once per new scene, not once per turn")

# ---- 3) the fold's episode-index attrs are bounded ----------------------
s3 = _story("Attrs")
for i in range(1, 5):
    s3.append_turn("player" if i % 2 else "narrator", f"turn {i}")
sm3 = Summarizer(cfg, s3, _Stub(json.dumps({
    "scene_summary": "MARKER the courier reached the pass.",
    "state_changes": ["s" * 60_000],
    "characters": ["c" * 5_000] + [f"npc{i}" for i in range(500)]})))
sm3._fold_scene(s3.turns(), 1, 1)
sc3 = s3.entries("memory/scenes.md")[0]
for key in ("state_changes", "characters"):
    assert len(sc3.attrs.get(key, "")) <= 800, (key, len(sc3.attrs.get(key, "")))
# the point of the bound: Entry.render emits attrs BEFORE the body, so an
# oversized attr line pushed the scene's own summary past the budget cut.
sysmsg = s3.assemble([], "what happened at the pass?", budget_tokens=8000)[0]["content"]
assert "MARKER" in sysmsg, (
    "the scene summary was cut by its own metadata; the raw turns are folded "
    "away, so that summary can now never reach the model")
print("3) episode-index attrs are bounded and cannot bury their own summary")

# ---- 4) a huge integer literal degrades instead of raising --------------
big = '{"day": ' + "9" * 4400 + '}'
assert extract_json(big) is None, "must degrade, not raise"
assert sc.parse_sidecar("```rpg\n" + big + "\n```") is None
print("4) an over-long integer literal degrades to None (no bare ValueError)")

# ---- 5) the fold's absolute day is magnitude-bounded --------------------
s5 = _story("Day")
sm5 = Summarizer(cfg, s5, _Stub(""))
sm5._apply_time({"time": {"day": 10 ** 4000, "phase": "evening"}})
assert len(s5.clock_str()) < 100, (
    f"clock_str is {len(s5.clock_str())} chars — it renders into the Time "
    "section of EVERY prompt, and the monotonic guard makes it permanent")
print("5) the fold cannot write an unbounded in-world day")

# ---- 6) a promotion's alias LIST is bounded -----------------------------
s6 = _story("Aliases")
sm6 = Summarizer(cfg, s6, _Stub(""))
sm6._apply_promotions({"promotions": [{
    "kind": "character", "slug": "mara", "title": "Mara", "detail": "A spy.",
    "aliases": [f"alias{i} " + "y" * 180 for i in range(5000)]}]})
mara = s6.entries("characters.md")[0]
assert len(mara.aliases) <= 32, len(mara.aliases)
assert len(mara.render()) < 20_000, len(mara.render())
print("6) a promotion's alias list is bounded, not just each alias")

shutil.rmtree(HOME, ignore_errors=True)
print("\nSWEEP 4 FINDINGS: ALL CLOSED")
