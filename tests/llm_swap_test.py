"""Swapping the engine's LLM has to swap ALL of it.

`Engine.__init__` builds one LLM and hands the same object to the planner and
the summarizer. `engine.llm = stub` then rebound only the engine's own name, so
those two kept the REAL client — and nothing said so.

Found by profiling a test that was merely "slow": sweep_fold_test.py spent 342
of its 349 seconds inside httpcore. It stubbed `e.llm` and `e.summarizer.llm`,
folded, and every fold that seeded a chapter outline reached the planner's live
client and made real network calls. The suite was not hermetic, it depended on a
provider being up, and it blew the 300s per-suite budget once that provider got
slower.

 1) setting engine.llm reaches the planner and the summarizer
 2) a fold on a stubbed engine makes NO call the test did not provide
 3) the getter still returns what was set (a property that lies is worse)
 4) construction order is safe: the setter runs before planner/summarizer exist
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-llmswap-"))
os.environ["CODERAIN_HOME"] = str(WORK)

from coderain.config import load_config          # noqa: E402
from coderain.engine import Engine                # noqa: E402
from coderain.memory import Library               # noqa: E402

lib = Library(WORK / "lib")


class Tripwire:
    """Answers folds, and records every call so an unstubbed path is visible."""

    def __init__(self):
        self.calls = 0

    def complete(self, messages, **kw):
        self.calls += 1
        return '{"scene_summary": "The courier walked on.", "timeline": "walked"}'

    def stream(self, messages, **kw):
        return iter([self.complete(messages, **kw)])


def _engine(name, **gen):
    store = lib.store(lib.create_story(
        name, "A courier crosses a frozen kingdom carrying a sealed box."))
    cfg = load_config()
    cfg.memory.update({"medium_fold_after": 4, "medium_fold_size": 2})
    cfg.generation.update(gen)
    return Engine(cfg, store), store


def test_setter_reaches_both_holders():
    eng, _ = _engine("swap")
    real = eng.llm
    stub = Tripwire()
    eng.llm = stub
    assert eng.planner.llm is stub, "planner kept the old client"
    assert eng.summarizer.llm is stub, "summarizer kept the old client"
    assert eng.planner.llm is not real and eng.summarizer.llm is not real
    print("1. engine.llm = stub reaches the planner and the summarizer")


def test_a_fold_makes_no_unstubbed_call():
    """§2 the assertion that would have caught the original bug. Chapter
    planning is ON, so the fold WILL want the planner — and the planner must be
    reaching the stub, not a socket."""
    eng, store = _engine("hermetic", chapter_outline=True)
    stub = Tripwire()
    eng.llm = stub
    assert eng.cfg.generation.get("chapter_outline") is True
    for i in range(1, 11):
        store.append_turn("player" if i % 2 else "narrator", f"TURN-{i}")
    eng.maybe_fold()
    assert stub.calls > 0, "the fold made no call at all; the test proves nothing"
    # Every call the fold made went through the stub. If the planner still held a
    # real client this would have gone to the network instead, which is exactly
    # what it did before: an outline seeded per fold, one live call per chapter.
    assert eng.planner.llm is stub
    print(f"2. a fold on a stubbed engine made {stub.calls} calls, all stubbed")


def test_getter_returns_what_was_set():
    eng, _ = _engine("getter")
    stub = Tripwire()
    eng.llm = stub
    assert eng.llm is stub, eng.llm
    print("3. the getter returns what was set")


def test_construction_order_is_safe():
    """§4 the setter runs inside __init__, BEFORE self.planner exists. It has to
    tolerate that rather than raising AttributeError on every Engine built."""
    eng, _ = _engine("ctor")
    assert eng.llm is not None
    assert eng.planner.llm is eng.llm, "init did not leave the two agreeing"
    assert eng.summarizer.llm is eng.llm
    print("4. construction order is safe and leaves everything agreeing")


try:
    for fn in (test_setter_reaches_both_holders,
               test_a_fold_makes_no_unstubbed_call,
               test_getter_returns_what_was_set,
               test_construction_order_is_safe):
        fn()
finally:
    shutil.rmtree(WORK, ignore_errors=True)
print("\nLLM SWAP TESTS PASSED")
