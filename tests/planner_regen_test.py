"""Chapter planning: keep history, plan one at a time, and know the story.

Four things were wrong with how the outline was generated.

  1. `seed(force=True)` deleted EVERY chapter, completed ones included, and
     replanned from the premise. The record of what the story had actually been
     about was thrown away, and the new plan could not be coherent with its own
     history. (Also D-008: it deleted before validating the reply.)
  2. There was no way to redo a single chapter. It was the whole outline or
     nothing.
  3. Seeding saw only the premise, the world and the arc. Not its own chapters,
     not one scene of what was played.
  4. Seeding asked for all N chapters in ONE reply, so no chapter was built on
     the one before it, and a single malformed element cost the whole batch.

 1) force keeps done and active chapters, clears only planned
 2) seeding plans ONE chapter per call, not a batch
 3) every generation payload carries the story so far, not just the premise
 4) a single chapter can be regenerated in place, keeping position and status
 5) regenerating a COMPLETED chapter is refused
 6) a rewrite sees which slot it is filling, and its neighbours
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-planregen-"))
os.environ["CODERAIN_HOME"] = str(WORK)

from coderain.config import load_config                     # noqa: E402
from coderain.memory import Library                          # noqa: E402
from coderain.planner import ChapterPlanner, PlanError       # noqa: E402

lib = Library(WORK / "lib")


class Stub:
    """One chapter per call; keeps every payload so we can inspect context."""

    def __init__(self):
        self.payloads, self.systems, self.calls = [], [], 0

    def complete(self, messages, **k):
        self.calls += 1
        self.systems.append(messages[0]["content"])
        self.payloads.append(messages[-1]["content"])
        return json.dumps({"title": f"Gen {self.calls}",
                           "goal": f"goal {self.calls}"})


def _planner(name, horizon=4, seed_rows=None, arc="", scene=""):
    store = lib.store(lib.create_story(
        name, "A courier crosses a frozen kingdom carrying a sealed box."))
    if arc:
        store.write("memory/arc.md", "# Arc\n\n" + arc)
    if scene:
        store.write("memory/scenes.md",
                    "# Scenes\n\n## Scene 1 {#scene-1}\nimportance: 3\n\n" + scene)
    cfg = load_config()
    cfg.generation["chapter_outline"] = True
    cfg.generation["chapter_horizon"] = horizon
    stub = Stub()
    p = ChapterPlanner(cfg, store, stub)
    if seed_rows:
        p.replace_all(seed_rows)
    return p, stub, store


DONE_ACTIVE_PLANNED = [
    {"title": "The Handoff", "goal": "receive the box", "status": "done"},
    {"title": "The River Road", "goal": "avoid the highway", "status": "active"},
    {"title": "The Bridge", "goal": "cross unseen", "status": "planned"},
]


def test_force_keeps_history():
    p, stub, _ = _planner("force", horizon=3, seed_rows=DONE_ACTIVE_PLANNED)
    p.seed(force=True)
    rows = p.as_dicts()
    titles = [r["title"] for r in rows]
    assert "The Handoff" in titles, titles
    assert "The River Road" in titles, titles
    assert "The Bridge" not in titles, titles      # the only planned one, cleared
    assert rows[0]["status"] == "done" and rows[1]["status"] == "active", rows
    print("1. force kept done + active, cleared only planned:", titles)


def test_seeding_is_one_call_per_chapter():
    p, stub, _ = _planner("onebyone", horizon=4)
    p.ensure_seeded()
    assert len(p.chapters()) == 4, [c.title for c in p.chapters()]
    assert stub.calls == 4, stub.calls          # not 1 batch call
    print(f"2. {len(p.chapters())} chapters from {stub.calls} calls, one each")


def test_payload_carries_the_story():
    """§3 the coherence fix: a plan made mid-story must see the story."""
    p, stub, _ = _planner("context", horizon=2,
                          seed_rows=DONE_ACTIVE_PLANNED,
                          arc="The courier lost the box at the ford.",
                          scene="They crossed the ice and were followed.")
    p.seed(force=True)
    payload = stub.payloads[-1]
    assert "PREMISE:" in payload, payload[:200]
    assert "CHAPTERS SO FAR:" in payload
    assert "The Handoff" in payload, "completed chapters missing from context"
    assert "lost the box at the ford" in payload, "arc missing from context"
    assert "crossed the ice" in payload, "played scenes missing from context"
    print("3. payload carries premise + chapters + arc + played scenes")


def test_regenerate_one_in_place():
    p, stub, _ = _planner("one", horizon=3, seed_rows=DONE_ACTIVE_PLANNED)
    before = p.as_dicts()
    events = p.regenerate_chapter(2)
    after = p.as_dicts()
    assert len(after) == len(before), (before, after)
    assert after[2]["title"] == "Gen 1", after[2]
    assert after[2]["status"] == "planned", after[2]
    # neighbours untouched
    assert after[0]["title"] == before[0]["title"], after
    assert after[1]["title"] == before[1]["title"], after
    assert stub.calls == 1, stub.calls
    assert events and "rewritten" in events[0], events
    print("4. one chapter rewritten in place, neighbours and status intact")


def test_completed_chapter_refused():
    p, _, _ = _planner("refuse", horizon=3, seed_rows=DONE_ACTIVE_PLANNED)
    try:
        p.regenerate_chapter(0)
        raise AssertionError("a done chapter was regenerated")
    except PlanError as e:
        assert "already part of the story" in str(e), e
    try:
        p.regenerate_chapter(99)
        raise AssertionError("out-of-range index allowed")
    except PlanError:
        pass
    print("5. a completed chapter is refused; bad index refused")


def test_rewrite_marks_its_slot():
    """§6 without the marker the model cannot tell WHICH chapter to replace, and
    would rewrite the outline instead of one slot."""
    p, stub, _ = _planner("slot", horizon=3, seed_rows=DONE_ACTIVE_PLANNED)
    p.regenerate_chapter(2)
    payload, system = stub.payloads[-1], stub.systems[-1]
    assert "REWRITE THIS ONE" in payload, payload[-300:]
    assert payload.count("REWRITE THIS ONE") == 1, "more than one slot marked"
    assert "The River Road" in payload, "neighbour missing"
    assert "only one you may change" in system, system[:200]
    print("6. exactly one slot marked, neighbours present, instruction scoped")


try:
    for fn in (test_force_keeps_history,
               test_seeding_is_one_call_per_chapter,
               test_payload_carries_the_story,
               test_regenerate_one_in_place,
               test_completed_chapter_refused,
               test_rewrite_marks_its_slot):
        fn()
finally:
    shutil.rmtree(WORK, ignore_errors=True)
print("\nPLANNER REGEN TESTS PASSED")
