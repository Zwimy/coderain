"""Memory summaries made after the reply, beside the next turn (D-077).

 1) the three moves (next_step, ask, apply_step) write what the inline fold writes
 2) a step is refused, and nothing written, when the turns it summarized changed or another fold got there first;
    turns added after them do not matter
 3) a chapter changed while the model answered is not advanced by that answer
 4) an arc edited by hand while the model answered is kept
 5) while a summary is overdue, the history window keeps every turn it has not covered; otherwise it is unchanged
 6) the reply is handed over while the summary is still being asked for; the next turn runs; undo works; an edit of the
    story's memory waits; the summary lands afterwards and its events come with the next reply
 7) a turn edited under a pending summary drops it, says so, and writes nothing
 8) a turn that arrives while a summary is being written waits for it instead of being refused
 9) a background summary that crashes is said in the health log and frees the story
10) with the setting off, the fold runs inside the reply as before; the switch is stored only as a real true
"""
import contextlib
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
WORK = Path(tempfile.mkdtemp(prefix="cr-bgfold-"))
os.environ["CODERAIN_HOME"] = str(WORK)

from fastapi.testclient import TestClient            # noqa: E402

import server                                         # noqa: E402
from coderain.config import load_config               # noqa: E402
from coderain.engine import Engine                    # noqa: E402
from coderain.memory import Entry, Library            # noqa: E402
from coderain.summarizer import Summarizer            # noqa: E402
from srv import core                                  # noqa: E402

lib = Library(WORK / "unit")


class StubLLM:
    """Writes one line of prose; answers a fold with a summary, after `gate` is set."""
    gen = {"max_tokens": 2000}

    def __init__(self):
        self.gate = threading.Event()
        self.gate.set()
        self.asked = threading.Event()
        self.prompts = []
        self.scene = 0

    def as_stage(self, name):
        return contextlib.nullcontext()

    def stream(self, messages, **kw):
        self.prompts.append(messages)
        yield "The keeper lifts the lamp and says the tide is early tonight."

    def complete(self, messages, **kw):
        system = str(messages[0].get("content", ""))
        if "Fold the TURNS" in system:
            self.asked.set()
            assert self.gate.wait(60), "the test never opened the gate"
            self.scene += 1
            return json.dumps({"scene_summary": f"Summary number {self.scene}.", "timeline": "the tide came early"})
        if "arc" in system.lower():
            return json.dumps({"arc": "The courier reached the lamp house."})
        return "".join(self.stream(messages))


def _store(name, pairs=6):
    store = lib.store(lib.create_story(name, "A courier."))
    for i in range(pairs):
        store.append_turn("player", f"I walk to step {i}.")
        store.append_turn("narrator", f"The stairs creak at step {i}.")
    return store


def _summarizer(store, llm=None, planner=None):
    cfg = load_config()
    cfg.memory.update({"medium_fold_after": 6, "medium_fold_size": 4, "long_fold_after": 1, "long_fold_size": 2})
    return Summarizer(cfg, store, llm or StubLLM(), planner=planner)


def _files(store):
    return {rel: store.read(rel) for rel in ("memory/scenes.md", "memory/timeline.md", "memory/arc.md", ".fold_state.json")}


# ---------- 1: the same result ----------
def test_three_moves_match_the_inline_fold():
    a, b = _store("inline", 10), _store("moves", 10)
    inline = _summarizer(a).maybe_fold()
    s = _summarizer(b)
    moved, snapped = [], False
    while s.due():
        moved += s.prepare(snapped)
        snapped = True
        step = s.next_step()
        moved += s.apply_step(step, s.ask(step))
    assert inline == moved, (inline, moved)
    fa, fb = _files(a), _files(b)
    assert fa == fb, {k: (fa[k], fb[k]) for k in fa if fa[k] != fb[k]}
    assert any("updated arc" in e for e in moved), moved
    print(f"1. step by step gives the same files and events as the inline fold ({len(moved)} events)")


# ---------- 2: outdated steps ----------
def test_outdated_steps_are_refused():
    store = _store("outdated")
    s = _summarizer(store)
    step = s.next_step()
    before = _files(store)
    assert store.update_turn(1, "The stairs are gone.")
    assert s.apply_step(step, {"scene_summary": "Old."}) is None
    assert _files(store) == before, "nothing may be written"

    store = lib.store(lib.create_story("raced", "A courier."))
    for _ in range(8):                       # the same exchange over and over, so only the fold pointer can tell the chunks apart
        store.append_turn("player", "go")
        store.append_turn("narrator", "They walk on.")
    s = _summarizer(store)
    first, second = s.next_step(), s.next_step()
    assert s.apply_step(first, {"scene_summary": "Mine."}) is not None
    after = _files(store)
    assert s.apply_step(second, {"scene_summary": "Theirs."}) is None, "another fold got there first"
    assert _files(store) == after

    store = _store("appended")
    s = _summarizer(store)
    step = s.next_step()
    store.append_turn("player", "I keep climbing.")
    assert s.apply_step(step, {"scene_summary": "Still good."}) is not None
    assert "Still good." in store.read("memory/scenes.md") and store.state()["folded_turns"] == 4

    store = _store("shortened")
    s = _summarizer(store)
    step = s.next_step()
    store.drop_last_turns(len(store.turns()) - 3)
    assert s.apply_step(step, {"scene_summary": "Gone."}) is None
    print("2. changed, already folded and cut-off turns refuse the step; turns added after them do not")


# ---------- 3 and 4: the plan and the arc ----------
class _Planner:
    def __init__(self):
        self.slug, self.done = "chapter-1", []
        self.llm = None

    def active(self):
        return Entry("One", self.slug)

    def active_fold_hint(self):
        return f"ACTIVE CHAPTER (set chapter_goal_met=true ONLY if it landed): {self.slug}"

    def needs_seed(self):
        return False

    def ensure_seeded(self):
        return []

    def complete_active(self):
        self.done.append(self.slug)
        return ["chapter done"]


def test_a_changed_chapter_is_not_advanced():
    met = {"scene_summary": "They met.", "chapter_goal_met": True}
    planner = _Planner()
    s = _summarizer(_store("same-chapter"), planner=planner)
    s.apply_step(s.next_step(), dict(met))
    assert planner.done == ["chapter-1"], planner.done
    planner = _Planner()
    s = _summarizer(_store("new-chapter"), planner=planner)
    step = s.next_step()
    planner.slug = "chapter-2"                 # the plan moved on while the model answered
    assert s.apply_step(step, dict(met)) is not None, "the summary itself is still good"
    assert planner.done == [], planner.done
    print("3. 'the goal landed' is applied to the chapter the model was shown, and to no other")


def test_a_hand_edited_arc_is_kept():
    store = _store("arc-edit", 10)
    s = _summarizer(store)
    while True:
        step = s.next_step()
        if step["kind"] == "arc":
            break
        s.apply_step(step, s.ask(step))
    store.write("memory/arc.md", "# Arc synopsis (long-term)\n\nWritten by hand.\n")
    assert s.apply_step(step, {"arc": "From the model."}) is None
    assert "Written by hand." in store.read("memory/arc.md")
    step = s.next_step()                       # made again from the hand-written arc
    first = store.entries("memory/scenes.md")[0]
    first.body = "Corrected by hand."
    store.upsert_entry("memory/scenes.md", first)
    assert s.apply_step(step, {"arc": "From the model."}) is None, "a scene it summarized changed"
    assert int(store.state().get("folded_scenes", 0)) == 0
    print("4. an arc, or a scene in it, edited while the model answered stops that arc fold")


# ---------- 5: the history window ----------
def test_history_keeps_unsummarized_turns():
    store = _store("window", 8)                # 16 turns, none folded
    cfg = load_config()
    cfg.memory.update({"short_term_turns": 8, "medium_fold_after": 6, "medium_fold_size": 4, "history_block": 4})
    off = Engine(cfg, store)
    assert len(off.history_window()) <= 8
    cfg.memory["background_folds"] = True
    on = Engine(cfg, store)
    window = on.history_window()
    assert window == store.turns(), f"all 16 unsummarized turns, got {len(window)}"

    def fold_pointer(n):
        state = store.state()
        state["folded_turns"] = n
        store.write_state(state)

    fold_pointer(7)                            # overdue from turn 8; the cache layout's block cut must not pass it
    assert on.history_window() == store.turns()[7:], len(on.history_window())
    assert on.history_window(drop_last=True) == store.turns()[7:-1]
    fold_pointer(12)                           # 4 left: nothing overdue
    assert on.history_window() == off.history_window(), "nothing overdue: the window is as it was"
    cfg.memory["medium_fold_after"] = 20       # a fold that is not due yet, with turns older than the window: unchanged too
    later = Engine(cfg, store)
    fold_pointer(0)
    assert later.history_window() == off.history_window(), len(later.history_window())
    print("5. an overdue summary keeps every unsummarized turn in the history; otherwise nothing changes")


# ---------- the server ----------
client = TestClient(server.app)


def _frames(resp):
    assert resp.status_code == 200, resp.text
    return [json.loads(line[6:]) for line in resp.text.splitlines() if line.startswith("data: ")]


def _done(frames):
    done = [f for f in frames if f["t"] == "done"]
    assert done, frames
    return done[0]


def _wait_idle(seconds=30):
    end = time.monotonic() + seconds
    while core._fold_busy.is_set():
        assert time.monotonic() < end, "the background fold never finished"
        time.sleep(0.02)


def _setup(title, background=True, pairs=3):
    core._cfg.memory.update({"background_folds": background, "short_term_turns": 6, "medium_fold_after": 6,
                             "medium_fold_size": 4, "long_fold_after": 8})
    core._cfg.generation.update({"trinity_brain": False, "chapter_outline": False, "use_memory_tool": False, "lore_check": False})
    core._engines.clear()
    r = client.post("/api/saves", json={"title": title, "mode": "simple", "premise": "A ferry town."})
    slug = r.json()["slug"]
    eng = core._engine(slug)
    stub = StubLLM()
    eng.llm = stub
    for i in range(pairs):
        eng.store.append_turn("player", f"I walk to step {i}.")
        eng.store.append_turn("narrator", f"The stairs creak at step {i}.")
    return slug, eng, stub


def _turn(slug, text):
    return _frames(client.post(f"/api/saves/{slug}/turn", json={"text": text}))


def test_reply_first_summary_after():
    slug, eng, stub = _setup("Background")
    stub.gate.clear()
    try:
        done = _done(_turn(slug, "I knock on the door."))          # returns while the fold waits at the gate
        assert any("in the background" in e for e in done["events"]), done["events"]
        assert stub.asked.wait(10), "the summary was never asked for"
        assert core._fold_busy.is_set() and "Summary number" not in eng.store.read("memory/scenes.md")
        done = _done(_turn(slug, "I wait on the step."))           # the next turn runs meanwhile
        assert not any("in the background" in e for e in done["events"]), "one fold at a time"
        sent = json.dumps(stub.prompts[-1])
        assert "I walk to step 0." in sent, "a turn not yet summarized must still be in the prompt"
        r = client.post(f"/api/saves/{slug}/web/connect", json={"from": "a", "to": "b", "note": "x"})
        assert r.status_code == 409 and "memory summary" in r.text, (r.status_code, r.text)
        turns = len(eng.store.turns())
        r = client.post(f"/api/saves/{slug}/undo")
        assert r.status_code == 200 and r.json()["ok"] and len(eng.store.turns()) == turns - 2, r.text
    finally:
        stub.gate.set()
    _wait_idle()
    assert "Summary number 1." in eng.store.read("memory/scenes.md")
    done = _done(_turn(slug, "I open it."))
    assert any(e.startswith("memory: folded scene 1") for e in done["events"]), done["events"]
    _wait_idle()
    print("6. the reply came first; a turn and an undo ran meanwhile, a memory edit waited, the summary landed after")


def test_edit_under_a_pending_summary_drops_it():
    slug, eng, stub = _setup("Stale")
    stub.gate.clear()
    try:
        _done(_turn(slug, "I knock."))
        assert stub.asked.wait(10)
        r = client.put(f"/api/saves/{slug}/turns/1", json={"text": "The stairs collapse."})
        assert r.status_code == 200, r.text
    finally:
        stub.gate.set()
    _wait_idle()
    assert "Summary number" not in eng.store.read("memory/scenes.md"), "an outdated summary must not be written"
    assert int(eng.store.state().get("folded_turns", 0)) == 0
    assert any("changed while a background summary" in str(h.get("reason")) for h in eng.store.health()), eng.store.health()
    done = _done(_turn(slug, "I look around."))                   # still due: made again, from the new text
    assert any("in the background" in e for e in done["events"]), done["events"]
    _wait_idle()
    assert "Summary number" in eng.store.read("memory/scenes.md")
    print("7. a turn edited under a pending summary dropped it, said so, and it was made again later")


def test_a_turn_waits_for_a_summary_being_written():
    slug, eng, stub = _setup("Writing")
    writing, release = threading.Event(), threading.Event()
    apply = eng.summarizer.apply_step

    def slow_apply(step, answer):
        writing.set()
        assert release.wait(30)
        return apply(step, answer)

    eng.summarizer.apply_step = slow_apply
    _done(_turn(slug, "I knock."))
    assert writing.wait(10), "the fold never reached its write"
    threading.Timer(0.8, release.set).start()
    frames = _turn(slug, "I knock again.")
    assert any(f["t"] == "stage" and "memory summary" in f["text"] for f in frames), frames
    _done(frames)
    _wait_idle()
    print("8. a turn that met a summary being written waited for it, and said so")


def test_a_crash_frees_the_story():
    slug, eng, stub = _setup("Crash")

    def boom():
        raise RuntimeError("disk full")

    eng.summarizer.next_step = boom
    _done(_turn(slug, "I knock."))
    _wait_idle()
    assert any("background summary failed" in str(h.get("reason")) for h in eng.store.health())
    r = client.post(f"/api/saves/{slug}/undo")
    assert r.status_code == 200, r.text
    assert core._gen_lock.acquire(blocking=False), "the lock was left held"
    core._gen_lock.release()
    print("9. a crashed background summary is logged and leaves nothing locked")


def test_off_means_inline_and_only_true_is_on():
    slug, eng, stub = _setup("Inline", background=False)
    frames = _turn(slug, "I knock.")
    done = _done(frames)
    assert any(e.startswith("memory: folded scene 1") for e in done["events"]), done["events"]
    assert not core._fold_busy.is_set()
    cfg = load_config()
    for value in ("true", 1, "false"):
        cfg.memory["background_folds"] = value
        assert Engine(cfg, eng.store).background_folds is False, value
    for sent, stored in ((True, True), ("true", False)):
        r = client.put("/api/settings", json={"mode": "local", "memory": {"background_folds": sent}})
        assert r.status_code == 200, r.text
        assert core._cfg.memory.get("background_folds") is stored, (sent, core._cfg.memory.get("background_folds"))
        assert r.json()["memory"]["background_folds"] is stored
    print("10. off keeps the fold inside the reply; only a real true turns it on")


try:
    for fn in (test_three_moves_match_the_inline_fold, test_outdated_steps_are_refused, test_a_changed_chapter_is_not_advanced,
               test_a_hand_edited_arc_is_kept, test_history_keeps_unsummarized_turns, test_reply_first_summary_after,
               test_edit_under_a_pending_summary_drops_it, test_a_turn_waits_for_a_summary_being_written,
               test_a_crash_frees_the_story, test_off_means_inline_and_only_true_is_on):
        fn()
finally:
    shutil.rmtree(WORK, ignore_errors=True)
print("\nBACKGROUND FOLD TESTS PASSED")
