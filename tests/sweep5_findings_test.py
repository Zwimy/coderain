"""Fifth-sweep findings: the two paths that lose a turn, and one missed bound.

Asserts:
 1) a Continue that applies mechanics but writes no prose is rolled back whole,
    so its envelope cannot collide with the previous turn's ledger record;
 2) a swipe-gen that produces nothing does not graft the PREVIOUS exchange's
    narration on as a variant of the swiped turn;
 3) one oversized `with` in a relationships list cannot evict the real ones.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
HOME = tempfile.mkdtemp(prefix="cr-sw5-")
os.environ["CODERAIN_HOME"] = HOME

from coderain.config import load_config  # noqa: E402
from coderain.engine import Engine  # noqa: E402
from coderain.memory import Library, _read_event_log  # noqa: E402
from coderain.summarizer import Summarizer  # noqa: E402

lib = Library(os.path.join(HOME, "lib"))
cfg = load_config()
cfg.generation["trinity_brain"] = False


def _story(name):
    return lib.store(lib.create_story(name, "A courier crosses a frozen kingdom."))


def _llm(*chunks):
    return type("L", (), {"stream": lambda self, m, **k: iter(chunks),
                          "complete": lambda self, m, **k: "".join(chunks)})()


# ---- 1) a prose-less Continue is rolled back whole -----------------------
s1 = _story("Continue")
e1 = Engine(cfg, s1)
s1.append_turn("player", "I sell the horse")
s1.append_turn("narrator", "You pocket the coin.")
e1._pre_turn_rpg = e1._snapshot_rpg()
e1.apply_envelope({"v": 1, "deltas": {"flag_set": {"sold_horse": True}}}, False)
log_before = len(_read_event_log(s1))
flags_before = dict(s1.world_state().get("flags") or {})
assert flags_before.get("sold_horse") is True, s1.world_state()

# A Continue whose only output is a sidecar: mechanics, no prose.
e1.llm = _llm('```rpg\n{"v":1,"deltas":{"flag_set":{"met_smith":true}}}\n```')
assert "".join(e1.continue_story()).strip() == ""
assert len(s1.turns()) == 2, s1.turns()
assert (s1.world_state().get("flags") or {}) == flags_before, (
    "a Continue that wrote nothing kept its deltas; its ledger record then "
    "collides with the previous turn's and the next undo truncates both")
assert len(_read_event_log(s1)) == log_before, _read_event_log(s1)

# and the undo that used to expose the split now behaves
assert e1.undo_last()
state_flags = s1.world_state().get("flags") or {}
logged = [r for r in _read_event_log(s1) if (r.get("env") or {}).get("deltas")]
assert bool(state_flags.get("sold_horse")) == bool(logged), (
    f"state has {state_flags} but the ledger has {len(logged)} delta record(s) "
    "— a branch would rebuild a different save than the one it came from")
print("1) a Continue that writes no prose is rolled back whole")

# ---- 2) a failed swipe-gen grafts nothing ------------------------------
s2 = _story("Swipe")
e2 = Engine(cfg, s2)
s2.append_turn("player", "I greet the guard")
s2.append_turn("narrator", "PREV he nods.")
s2.append_turn("player", "I ask about the pass")
s2.append_turn("narrator", "SWIPED he points north.")
assert e2._ensure_swipes() is not None
e2.llm = _llm("")                       # the regeneration produces nothing
list(e2.swipe_generate())
# The exchange is gone (that is what a swipe does before regenerating, and the
# regeneration failed), so there is nothing left to swipe.
assert e2._swipes is None, (
    f"swipe state survived the exchange it describes: {e2._swipes}")
# Browsing now re-seeds from the turn that is actually there, which is the
# correct fresh state for it — the point is that it cannot reach back into the
# deleted exchange's text.
e2.swipe_browse(-1)
tail = [t["text"] for t in s2.turns()]
# The decisive check: browsing must never write one exchange's prose over
# another exchange's turn in transcript.md (invariant 7).
assert tail == ["I greet the guard", "PREV he nods."], (
    f"browse rewrote a turn with text from a different exchange: {tail}")
print("2) a swipe-gen that produced nothing adds no variant")

# ---- 3) one huge `with` cannot evict the real relationships ------------
s3 = _story("Rel")
sm3 = Summarizer(cfg, s3, _llm(""))
sm3._apply_promotions({"promotions": [{
    "kind": "character", "slug": "mara", "title": "Mara", "detail": "A spy.",
    "relationships": [{"with": "x" * 3000, "note": "ally"},
                      {"with": "smith", "note": "owes a debt"}]}]})
rel = s3.entries("characters.md")[0].attrs.get("relationships", "")
assert "smith" in rel, (
    f"the real relationship was pushed out by one oversized value: {rel[:120]}")
assert len(rel) <= 800, len(rel)
print("3) an oversized relationship value cannot evict the real ones")

shutil.rmtree(HOME, ignore_errors=True)
print("\nSWEEP 5 FINDINGS: ALL CLOSED")
