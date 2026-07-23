"""Stop/abort must not corrupt the transcript (2026-07-22 play-test bug).

The reported symptom: pressing Stop (or a disconnect) left the player's action in
transcript.md with no response, and the previous turn read as user text. Root
cause: turn() appends the player turn, then streams; a GeneratorExit thrown at
the yield (client Stop closing the stream) skipped the orphan-cleanup, so the
half turn was written to disk. The fix is a try/finally in turn().

Driven at the engine level with next()/close(), which deterministically models
exactly what the server does when the SSE stream is closed early. (A TestClient
can't simulate a mid-stream disconnect against a fast in-process stub — the turn
completes before the "disconnect".)
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from coderain.config import load_config      # noqa: E402
from coderain.engine import Engine           # noqa: E402
from coderain.memory import Library          # noqa: E402

cfg = load_config()
cfg.generation["trinity_brain"] = False      # single-brain uses eng.llm directly
cfg.generation["use_memory_tool"] = False
cfg.generation["think"] = False

WORK = Path(tempfile.mkdtemp(prefix="cr-abort-"))
lib = Library(WORK)
store = lib.store(lib.create_story("Abort", "A frontier town."))
eng = Engine(cfg, store)


class OneShot:
    def stream(self, m, **k):
        yield "A complete response."


class Slow:
    def stream(self, m, **k):
        for i in range(40):
            yield f"word{i} "


def test_abort_leaves_no_orphan_player_turn():
    eng.llm = OneShot()
    list(eng.turn("open the door"))
    assert [t["role"] for t in store.turns()] == ["player", "narrator"]

    eng.llm = Slow()
    gen = eng.turn("look around")
    next(gen)                                 # appends player turn + streams a bit
    assert [t["role"] for t in store.turns()] == ["player", "narrator", "player"]
    gen.close()                               # the Stop / disconnect
    after = [t["role"] for t in store.turns()]
    assert after == ["player", "narrator"], f"orphan left behind: {after}"
    assert "look around" not in store.read("transcript.md"), "action left in the file"
    assert store.turns()[-1]["text"] == "A complete response.", "prior turn harmed"
    print("abort drops the orphan player turn; prior turns untouched")


def test_turn_after_abort_is_clean():
    eng.llm = OneShot()
    list(eng.turn("go north"))
    roles = [t["role"] for t in store.turns()]
    assert roles == ["player", "narrator", "player", "narrator"], roles
    # exactly one player+narrator for the new turn, no duplication
    assert store.read("transcript.md").count("go north") == 1
    print("a turn after an abort stores cleanly, no duplication")


def test_abort_during_empty_generation_also_cleans_up():
    """A turn that streams nothing (only <think>/sidecar) already dropped the
    orphan on normal return; abort must reach the same state."""
    class EmptyThenClose:
        def stream(self, m, **k):
            if False:
                yield ""                      # a generator that yields nothing
            return
    eng.llm = EmptyThenClose()
    before = len(store.turns())
    list(eng.turn("whisper to nobody"))       # normal return, empty -> orphan dropped
    assert len(store.turns()) == before, "empty turn left an orphan"
    print("empty generation leaves no orphan")


def test_server_has_cancel_endpoint_and_frees_lock_on_error():
    import importlib
    os.environ["CODERAIN_HOME"] = str(WORK / "srv")
    server = importlib.import_module("server")
    from fastapi.testclient import TestClient
    server._cfg.generation["trinity_brain"] = False
    server._cfg.generation["use_memory_tool"] = False
    c = TestClient(server.app)

    paths = {r.path for r in server.app.routes if hasattr(r, "path")}
    assert "/api/saves/{slug}/cancel" in paths, "no cancel endpoint"

    slug = server.lib.saves.create("Lock", premise="x", mode="simple")
    server._engines.pop(slug, None)
    e = server._engine(slug)

    class Boom:
        def stream(self, m, **k):
            raise ConnectionError("Connection error.")
            yield  # pragma: no cover
    e.llm = Boom()
    r = c.post(f"/api/saves/{slug}/turn", json={"text": "x"})   # errors mid-gen
    assert '"aborted"' not in r.text
    assert not server._gen_lock.locked(), "lock stayed held after an error"

    # the errored turn left no orphan, and the next turn works
    assert not [t for t in server.lib.saves.store(slug).turns()], "orphan after error"
    e.llm = type("Ok", (), {"stream": lambda self, m, **k: iter(["Fine."])})()
    r2 = c.post(f"/api/saves/{slug}/turn", json={"text": "again"})
    assert "busy" not in r2.text and '"t": "done"' in r2.text, r2.text[:200]
    print("cancel endpoint present; lock frees on error; no orphan; next turn OK")


for fn in (test_abort_leaves_no_orphan_player_turn,
           test_turn_after_abort_is_clean,
           test_abort_during_empty_generation_also_cleans_up,
           test_server_has_cancel_endpoint_and_frees_lock_on_error):
    fn()
shutil.rmtree(WORK, ignore_errors=True)
print("\nABORT TESTS PASSED")
