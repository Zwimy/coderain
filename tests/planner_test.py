"""Chapter planner — the rolling book-style outline (2026-07-23 'a planner that
plans 3-4 chapters ahead ... each chapter completed creates a new one nested after,
but I don't want one more brain').

The planner is NOT a per-turn brain: it seeds once and extends once per completed
chapter, on the summarizer's occasional LLM. Asserts:
 1) seed produces `horizon` chapters, chapter 1 active, the rest planned;
 2) the active chapter steers context (store.outline_block), horizon chapters ahead;
 3) when a fold reports chapter_goal_met, the active chapter is marked done, the
    next activates, and ONE fresh chapter is appended (horizon maintained);
 4) disabled / no-premise / LLM failure all degrade gracefully (no crash, no plan).
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
HOME = tempfile.mkdtemp(prefix="cr-planner-")
os.environ["CODERAIN_HOME"] = HOME

from coderain.config import load_config  # noqa: E402
from coderain.memory import Library  # noqa: E402
from coderain.planner import ChapterPlanner  # noqa: E402

lib = Library(os.path.join(HOME, "lib"))


def _status(c):
    return (c.attrs.get("status", "planned") or "planned").strip().lower()


class SeedStub:
    """Emits `horizon` chapters on the seed call, then one chapter per extend call."""
    def __init__(self, horizon):
        self.horizon = horizon
        self.extend_calls = 0

    def complete(self, messages, **k):
        sys_txt = messages[0]["content"]
        if "extending" in sys_txt:            # NEXT_INSTRUCTION (vs seed)
            self.extend_calls += 1
            n = self.extend_calls
            return json.dumps({"title": f"Added Chapter {n}",
                               "goal": f"escalate, step {n}"})
        # seed
        return json.dumps({"chapters": [
            {"title": f"Chapter {i}", "goal": f"goal {i}"}
            for i in range(1, self.horizon + 1)]})


# ---- 1) seed --------------------------------------------------------------
cfg = load_config()
cfg.generation["chapter_outline"] = True
cfg.generation["chapter_horizon"] = 4
store = lib.store(lib.create_story(
    "Book", "A cartographer chases a rumor of a city that moves between valleys."))
stub = SeedStub(horizon=4)
planner = ChapterPlanner(cfg, store, stub)

ev = planner.ensure_seeded()
chapters = planner.chapters()
assert len(chapters) == 4, [c.title for c in chapters]
assert _status(chapters[0]) == "active", _status(chapters[0])
assert all(_status(c) == "planned" for c in chapters[1:]), \
    [(_status(c)) for c in chapters]
assert planner.active().slug == "ch-1"
# idempotent — a second ensure_seeded does nothing
assert planner.ensure_seeded() == []
assert len(planner.chapters()) == 4
print("1) seed -> 4 chapters, ch-1 active, rest planned; idempotent")

# ---- 2) steering block ----------------------------------------------------
block = store.outline_block()
assert "Chapter 1:" in block and "Chapter 1" in block, block
assert "goal 1" in block, block
assert "Later chapters" in block and "Chapter 2" in block, block
print("2) outline_block steers toward the active chapter, names upcoming ones")

# ---- 3) roll forward on completion ----------------------------------------
ev = planner.complete_active()
chapters = planner.chapters()
# ch-1 done, ch-2 active, and ONE new chapter appended (horizon 4 maintained: the
# non-done count stays 4 -> ch2,ch3,ch4 + the newly added one).
assert _status(chapters[0]) == "done", _status(chapters[0])
assert planner.active().slug == "ch-2", planner.active().slug
non_done = [c for c in chapters if _status(c) != "done"]
assert len(non_done) == 4, [(c.title, _status(c)) for c in chapters]
assert stub.extend_calls == 1, stub.extend_calls           # exactly one new chapter
assert chapters[-1].title == "Added Chapter 1", chapters[-1].title
assert any("chapter done" in e.lower() for e in ev), ev
print("3) completion: ch-1 done, ch-2 active, one fresh chapter appended (horizon held)")

# a full sweep to the end still terminates and keeps exactly one active
for _ in range(12):
    planner.complete_active()
act = [c for c in planner.chapters() if _status(c) == "active"]
assert len(act) == 1, [(_status(c)) for c in planner.chapters()]
print("   repeated completion keeps exactly one active; never loops away")

# ---- 4) graceful degradation ----------------------------------------------
# disabled
cfg_off = load_config()
cfg_off.generation["chapter_outline"] = False
store_off = lib.store(lib.create_story("Off", "A premise long enough to be real."))
p_off = ChapterPlanner(cfg_off, store_off, SeedStub(4))
assert p_off.ensure_seeded() == [] and p_off.chapters() == []
assert store_off.outline_block() == ""

# no premise (too short)
store_np = lib.store(lib.create_story("NP", "x"))
p_np = ChapterPlanner(cfg, store_np, SeedStub(4))
assert p_np.ensure_seeded() == [] and p_np.chapters() == []

# LLM failure (bad JSON) -> no plan, no crash
class BadStub:
    def complete(self, messages, **k):
        return "not json at all"

store_bad = lib.store(lib.create_story("Bad", "A premise long enough to be real."))
p_bad = ChapterPlanner(cfg, store_bad, BadStub())
assert p_bad.seed() == [] and p_bad.chapters() == []
print("4) disabled / no-premise / bad-LLM all degrade to no plan, no crash")

shutil.rmtree(HOME, ignore_errors=True)
print("\nPLANNER TESTS PASSED")
