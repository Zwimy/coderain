"""Retry keeps what it replaces (D-057).

What broke: a retry deleted the last exchange first and regenerated second. A model error, the Stop button or an empty reply
ended the regeneration early and left the story one exchange shorter, with the player's own action gone too (and swipe-generate
did the same). The rollback is not one change (transcript, world state, ledger, reveals, folds, and the engine's single undo
snapshot), so the exchange is protected by a checkpoint of the whole save, copied back when no narration comes back.

Asserts:
 1) a good retry in a story with no mechanics keeps the replaced text as a variant: the tail is the new text, `_swipes` holds both,
    and going back puts the old text in the transcript; the checkpoint copy is gone afterwards;
 2) a model error puts the save back BYTE FOR BYTE, the error still reaches the caller, and the engine's undo record is back
    (an Undo afterwards still rolls the exchange's mechanics back);
 3) an empty reply puts the save back and says so (RetryRestored) instead of ending as a silent shorter story;
 4) Stop mid-stream (the stream is closed) puts the save back;
 5) the health log and the usage log are NOT rolled back (a failed attempt stays visible, and its tokens were spent), and a file
    the failed attempt created is removed;
 6) a story with mechanics keeps no variant (a variant carries prose only) but is still put back on failure;
 7) an orphan player action (the previous turn failed) comes back with its narration, and is put back when it fails again;
 8) swipe-generate is protected the same way (Stop used to destroy the exchange);
 9) the opening can be retried and is put back when it fails;
10) `.snapshots` is neither copied nor touched;
11) `took_hold` is the whole decision: a narrator tail needs the same length, an orphan player tail one more.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
HOME = tempfile.mkdtemp(prefix="cr-retry-")
os.environ["CODERAIN_HOME"] = HOME

from coderain import retry as retry_mod                    # noqa: E402
from coderain.config import load_config                    # noqa: E402
from coderain.engine import Engine                         # noqa: E402
from coderain.memory import Library                        # noqa: E402

lib = Library(os.path.join(HOME, "lib"))
cfg = load_config()
cfg.generation["trinity_brain"] = False
cfg.generation["chapter_outline"] = False           # nothing but the Writer may call the model
_n = [0]
COPIES = []                                          # every checkpoint directory a test run made
_take = retry_mod.Checkpoint.take.__func__


def _recording_take(cls, *a, **k):
    ck = _take(cls, *a, **k)
    COPIES.append(ck.copy)
    return ck


retry_mod.Checkpoint.take = classmethod(_recording_take)


class Stub:
    """The Writer. Each reply is a string (one chunk), a list of chunks, an Exception to raise, or a callable run first."""
    model = "stub-model"

    def __init__(self, *replies):
        self.replies = list(replies)

    def complete(self, messages, **k):
        return ""

    def stream(self, messages, **k):
        r = self.replies.pop(0) if self.replies else "A default new reply."
        if callable(r):
            r = r()
        if isinstance(r, BaseException):
            raise r
        yield from ([r] if isinstance(r, str) else r)


def make(first="OLD narration of the door.", rpg=False, player="I open the door."):
    _n[0] += 1
    store = lib.store(lib.create_story(f"Retry {_n[0]}", "A courier crosses a frozen kingdom."))
    if rpg:
        st = store.rpg_state()
        st["enabled"] = True
        store.set_rpg_state(st)
    eng = Engine(cfg, store)
    eng.llm = Stub(first)
    "".join(eng.turn(player))
    assert [t["role"] for t in store.turns()] == ["player", "narrator"], store.turns()
    return eng, store


def tree(store):
    """Every file of the save as bytes, minus the two logs that are never rolled back and the snapshots."""
    root = store.dir
    out = {}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        if p.is_file() and rel not in retry_mod.LEAVE_ALONE and not rel.startswith(".snapshots"):
            out[rel] = p.read_bytes()
    return out


def roles(store):
    return [(t["role"], t["text"]) for t in store.turns()]


# ---- 1) a good retry keeps the old text as a variant -------------------------------------------------------------------
eng, store = make()
before_copies = len(COPIES)
eng.llm = Stub("NEW narration of the door.")
out = "".join(eng.retry_exchange())
assert "NEW" in out, out
assert roles(store) == [("player", "I open the door."), ("narrator", "NEW narration of the door.")], roles(store)
assert eng._swipes and eng._swipes["variants"] == ["OLD narration of the door.", "NEW narration of the door."], eng._swipes
assert eng._swipes["idx"] == 1, eng._swipes
back = eng.swipe_browse(-1)
assert back["text"] == "OLD narration of the door." and back["count"] == 2, back
assert store.turns()[-1]["text"] == "OLD narration of the door.", "going back did not put the old text in the transcript"
assert len(COPIES) == before_copies + 1 and not COPIES[-1].exists(), "the checkpoint copy was left behind after a good retry"
print("1) a good retry keeps the replaced text as a variant")

# ---- 2) a model error puts the save back, byte for byte ----------------------------------------------------------------
eng, store = make()
before, slots_before = tree(store), eng._pre_turn_rpg
assert slots_before is not None, "the turn left no undo snapshot, so the test would prove nothing"
eng.llm = Stub(ConnectionError("connection refused"))
try:
    list(eng.retry_exchange())
    raise AssertionError("the model error was swallowed")
except ConnectionError:
    pass
assert tree(store) == before, "a failed retry did not put the save back: " + str(
    [k for k in set(before) | set(tree(store)) if before.get(k) != tree(store).get(k)])
assert roles(store)[-1] == ("narrator", "OLD narration of the door."), roles(store)
assert eng._pre_turn_rpg == slots_before, "the engine's undo snapshot was not put back"
assert not COPIES[-1].exists(), "the checkpoint copy was left behind after a failed retry"
assert eng.undo_last() is True and store.turns() == [], "Undo after a failed retry did not roll the exchange back"
print("2) a model error puts the save back byte for byte, and Undo still works")

# ---- 3) an empty reply puts it back and says so -----------------------------------------------------------------------
eng, store = make()
before = tree(store)
eng.llm = Stub("")
try:
    list(eng.retry_exchange())
    raise AssertionError("an empty regeneration ended as if it had worked")
except retry_mod.RetryRestored as e:
    assert e.code == "restored" and "earlier version" in e.user_text, (e.code, e.user_text)
assert tree(store) == before, "an empty retry left the story shorter"
print("3) an empty reply puts the exchange back and says so")

# ---- 4) Stop (the stream is closed mid-way) ---------------------------------------------------------------------------
eng, store = make()
before = tree(store)
eng.llm = Stub(["First half of the new narration. ", "Second half."])
stream = eng.retry_exchange()
first = next(stream)
assert first, "the stub should have streamed a chunk before the stop"
stream.close()                                       # what the pump's `finally: it.close()` does after Stop
assert tree(store) == before, "Stop during a retry destroyed the exchange"
assert eng._swipes is None, eng._swipes
print("4) Stop mid-stream puts the exchange back")

# ---- 5) logs are not rolled back; a stray file of the failed attempt goes -----------------------------------------------
eng, store = make()
store.log_usage({"stage": "writer", "model": "m", "in": 7, "out": 3})                      # both logs exist BEFORE the retry,
store.log_degraded("earlier-stage", "an older degraded pass")                              # so a restore could overwrite them
before = tree(store)


def noisy_failure():
    store.log_usage({"stage": "writer", "model": "m", "in": 111, "out": 0})
    store.log_degraded("retry-test", "a degraded pass of the failed attempt")
    (store.dir / "stray-from-failed-attempt.md").write_text("junk", encoding="utf-8")
    (store.dir / "memory" / "stray-dir").mkdir(exist_ok=True)
    (store.dir / "memory" / "stray-dir" / "x.md").write_text("junk", encoding="utf-8")
    return ConnectionError("down")


eng.llm = Stub(noisy_failure)
try:
    list(eng.retry_exchange())
except ConnectionError:
    pass
assert tree(store) == before, "the save was not put back"
assert not (store.dir / "stray-from-failed-attempt.md").exists(), "a file the failed attempt created survived"
assert not (store.dir / "memory" / "stray-dir").exists(), "a directory the failed attempt created survived"
assert any(r.get("stage") == "retry-test" for r in store.health()), "the failed attempt's health line was rolled back"
assert any(r.get("in") == 111 for r in store.usage(limit=50)), "the spend of the failed attempt was rolled back"
assert any(r.get("in") == 7 for r in store.usage(limit=50)), "the usage log lost its older rows"
assert any(r.get("stage") == "earlier-stage" for r in store.health()), "the health log lost its older rows"
print("5) the health and usage logs keep what the failed attempt wrote; a stray file does not survive")

# ---- 6) a story with mechanics: no variant, still put back on failure --------------------------------------------------
eng, store = make(rpg=True)
eng.llm = Stub("NEW narration with mechanics.")
"".join(eng.retry_exchange())
assert roles(store) == [("player", "I open the door."), ("narrator", "NEW narration with mechanics.")], (
    "the retry of a story's first exchange dropped the player's action (regenerate took an empty transcript for an opening)",
    roles(store))
assert eng._swipes is None, ("mechanics make a variant unsafe: it carries prose only", eng._swipes)
before = tree(store)
eng.llm = Stub(ConnectionError("down"))
try:
    list(eng.retry_exchange())
except ConnectionError:
    pass
assert tree(store) == before, "a failed retry in a story with mechanics was not put back"
print("6) with mechanics there is no variant, and a failure still puts the save back")

# ---- 7) an orphan player action ---------------------------------------------------------------------------------------
eng, store = make()
store.append_turn("player", "I wait by the gate.")            # the previous turn produced nothing and left this behind
assert store.turns()[-1]["role"] == "player"
before = tree(store)
eng.llm = Stub(ConnectionError("down"))
try:
    list(eng.retry_exchange())
except ConnectionError:
    pass
assert tree(store) == before and roles(store)[-1] == ("player", "I wait by the gate."), roles(store)
eng.llm = Stub("The gate swings open at last.")
"".join(eng.retry_exchange())
assert roles(store)[-2:] == [("player", "I wait by the gate."), ("narrator", "The gate swings open at last.")], roles(store)
assert eng._swipes is None, eng._swipes
print("7) an orphan player action is put back on failure and answered on success")

# ---- 8) swipe-generate is protected too ------------------------------------------------------------------------------
eng, store = make()
before = tree(store)
eng.llm = Stub(["Half a new version. ", "The rest."])
stream = eng.swipe_exchange()
next(stream)
stream.close()                                                # Stop
assert tree(store) == before and eng._swipes is None, "Stop during a swipe destroyed the exchange"
eng.llm = Stub(ConnectionError("down"))
try:
    list(eng.swipe_exchange())
except ConnectionError:
    pass
assert tree(store) == before, "a failed swipe-generate did not put the exchange back"
eng.llm = Stub("A second version of the door.")
"".join(eng.swipe_exchange())
assert eng._swipes["variants"] == ["OLD narration of the door.", "A second version of the door."], eng._swipes
print("8) swipe-generate: Stop and failure put the exchange back, success adds a variant")

# ---- 9) the opening ------------------------------------------------------------------------------------------------------
_n[0] += 1
store = lib.store(lib.create_story(f"Retry {_n[0]}", "A courier crosses a frozen kingdom."))
eng = Engine(cfg, store)
eng.llm = Stub("OLD opening line.")
"".join(eng.opening())
assert roles(store) == [("narrator", "OLD opening line.")], roles(store)
before = tree(store)
eng.llm = Stub(ConnectionError("down"))
try:
    list(eng.retry_exchange())
except ConnectionError:
    pass
assert tree(store) == before, "a failed retry of the opening lost the opening"
eng.llm = Stub("A better opening line.")
"".join(eng.retry_exchange())
assert roles(store) == [("narrator", "A better opening line.")], roles(store)
print("9) the opening can be retried and is put back when it fails")

# ---- 10) .snapshots is neither copied nor touched ---------------------------------------------------------------------
eng, store = make()
snap = store.dir / ".snapshots" / "2026-01-01T00-00-00"
snap.mkdir(parents=True)
(snap / "keep.md").write_text("an old snapshot", encoding="utf-8")
eng.llm = Stub(ConnectionError("down"))
copy_dirs = []
_orig = retry_mod.Checkpoint.restore_files


def _spy(self):
    copy_dirs.append(self.copy)
    assert not (self.copy / ".snapshots").exists(), "snapshots were copied into the checkpoint"
    return _orig(self)


retry_mod.Checkpoint.restore_files = _spy
try:
    list(eng.retry_exchange())
except ConnectionError:
    pass
finally:
    retry_mod.Checkpoint.restore_files = _orig
assert copy_dirs, "restore never ran"
assert (snap / "keep.md").read_text(encoding="utf-8") == "an old snapshot", "the snapshots were disturbed"
print("10) .snapshots is neither copied nor touched")

# ---- 11) took_hold is the whole decision ------------------------------------------------------------------------------
ck = retry_mod.Checkpoint(Path("."), Path("."), turns=4, tail_role="narrator")
N, P = {"role": "narrator"}, {"role": "player"}
assert ck.took_hold([P, N, P, N]) is True
assert ck.took_hold([P, N]) is False, "an exchange that came back shorter was accepted"
assert ck.took_hold([P, N, P]) is False, "a player action with no narration was accepted"
assert ck.took_hold([P, N, P, N, N]) is False, "an exchange that came back longer was accepted"
assert ck.took_hold([]) is False
same_len = retry_mod.Checkpoint(Path("."), Path("."), turns=3, tail_role="narrator")
assert same_len.took_hold([P, N, N]) is True and same_len.took_hold([N, N, P]) is False, (
    "the right length with a player action at the end was accepted")
orphan = retry_mod.Checkpoint(Path("."), Path("."), turns=3, tail_role="player")
assert orphan.took_hold([P, N, P, N]) is True and orphan.took_hold([P, N, P]) is False
assert orphan.took_hold([N, P, P, P]) is False, "the right length with a player action at the end was accepted"
print("11) took_hold: same length for a narrator tail, one more for an orphan player action")

for d in COPIES:
    shutil.rmtree(d, ignore_errors=True)
shutil.rmtree(HOME, ignore_errors=True)
print("\nRETRY KEEPS TESTS PASSED")
