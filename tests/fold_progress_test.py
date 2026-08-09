"""Turns appeared to hang after the prose had finished streaming.

Reported live. The fold runs AFTER the text has streamed, inside the same
request, and it is the most expensive call the engine makes — measured on a real
save at ~4,300 output tokens, firing on 1 turn in 7. It reported nothing while it
worked, so the reader watched finished text beside a dead UI.

Worse, nothing bounded how long one request could take: the OpenAI SDK defaults
are read=600s with max_retries=2, so a stalled call could hold the turn lock for
roughly THIRTY MINUTES before failing. That is not slow, it is indistinguishable
from hung.

 1) maybe_fold reports each scene fold through on_stage
 2) it reports the arc fold too
 3) no callback still works (the CLI and tests call it bare)
 4) notes arrive DURING the fold, not batched at the end
 5) a request timeout is set, and is generous enough for a real fold
 6) a junk timeout falls back instead of making every call fail instantly
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-foldprog-"))
os.environ["CODERAIN_HOME"] = str(WORK)

from coderain.config import load_config                  # noqa: E402
from coderain.llm import REQUEST_TIMEOUT_S, request_timeout   # noqa: E402
from coderain.memory import Library                       # noqa: E402
from coderain.summarizer import Summarizer                # noqa: E402

lib = Library(WORK / "lib")


class FoldLLM:
    """Returns a valid fold object; optionally blocks so timing is observable."""
    gen = {"max_tokens": 2000}

    def __init__(self, delay=0.0):
        self.delay = delay
        self.calls = 0

    def complete(self, convo, **kw):
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        return json.dumps({"scene_summary": "They crossed the ice.",
                           "timeline": "crossed", "promotions": [],
                           "arc": "The courier crossed a frozen kingdom."})

    def as_stage(self, name):
        import contextlib
        return contextlib.nullcontext()


def _store(name, turns=60):
    store = lib.store(lib.create_story(name, "A courier."))
    for _ in range(turns // 2):
        store.append_turn("player", "go")
        store.append_turn("narrator", "They walk on.")
    return store


def _summarizer(store, delay=0.0):
    cfg = load_config()
    cfg.memory["medium_fold_after"] = 6
    cfg.memory["medium_fold_size"] = 4
    cfg.memory["long_fold_after"] = 2
    cfg.memory["long_fold_size"] = 2
    return Summarizer(cfg, store, FoldLLM(delay), planner=None)


def test_scene_folds_are_reported():
    notes = []
    _summarizer(_store("scene")).maybe_fold(notes.append)
    scene_notes = [n for n in notes if "scene" in n.lower()]
    assert scene_notes, notes
    assert any("Folding memory" in n for n in scene_notes), notes
    print(f"1. {len(scene_notes)} scene fold(s) reported:", scene_notes[0])


def test_arc_fold_is_reported():
    notes = []
    _summarizer(_store("arc")).maybe_fold(notes.append)
    assert any("long-term arc" in n for n in notes), notes
    print("2. the arc fold is reported too")


def test_no_callback_still_works():
    """§3 the CLI and every test call this bare; a required callback would
    break them."""
    events = _summarizer(_store("bare")).maybe_fold()
    assert isinstance(events, list) and events, events
    print("3. maybe_fold() with no callback still folds")


def test_notes_arrive_during_the_fold():
    """§4 the whole point. Collecting notes and emitting them at the end would
    pass §1 while changing nothing the reader sees."""
    store = _store("timing")
    s = _summarizer(store, delay=0.4)
    seen, done = [], threading.Event()

    def on_stage(msg):
        seen.append(time.monotonic())

    def run():
        s.maybe_fold(on_stage)
        done.set()

    t0 = time.monotonic()
    threading.Thread(target=run, daemon=True).start()
    assert done.wait(60), "fold did not finish"
    total = time.monotonic() - t0
    assert seen, "no notes at all"
    first = seen[0] - t0
    # The first note must land well before the work finishes.
    assert first < total * 0.5, (first, total)
    print(f"4. first note at {first:.2f}s of a {total:.2f}s fold")


def test_request_timeout_is_set_and_generous():
    assert REQUEST_TIMEOUT_S >= 120, REQUEST_TIMEOUT_S
    assert request_timeout({}) == float(REQUEST_TIMEOUT_S)
    assert request_timeout({"request_timeout_s": 90}) == 90.0
    print(f"5. request timeout defaults to {REQUEST_TIMEOUT_S}s, overridable")


def test_bad_timeout_falls_back():
    """§6 a typo must not make every call fail instantly — that looks exactly
    like the model being unreachable."""
    assert request_timeout({"request_timeout_s": "nonsense"}) == float(REQUEST_TIMEOUT_S)
    assert request_timeout({"request_timeout_s": 0}) == 30.0        # floored
    assert request_timeout({"request_timeout_s": -5}) == 30.0
    assert request_timeout(None) == float(REQUEST_TIMEOUT_S)
    print("6. junk/tiny timeouts fall back or floor at 30s")


try:
    for fn in (test_scene_folds_are_reported,
               test_arc_fold_is_reported,
               test_no_callback_still_works,
               test_notes_arrive_during_the_fold,
               test_request_timeout_is_set_and_generous,
               test_bad_timeout_falls_back):
        fn()
finally:
    shutil.rmtree(WORK, ignore_errors=True)
print("\nFOLD PROGRESS TESTS PASSED")
