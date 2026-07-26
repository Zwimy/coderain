"""Standalone lore-keeper + a hosted-save config bug (2026-07-26).

The continuity pass used to exist ONLY inside the quad pipeline, so verifying
continuity forced three calls per turn (Director + Lore-keeper + Writer). It never
actually needed the Director's plan: given the context and the action it can work
out what the prose must not contradict. So it now runs in single-brain too — two
calls with verification instead of three.

One switch drives both: `generation.lore_check`. It lives in `generation` (not the
`trinity` block) specifically so a hosted-mode settings save cannot delete it.

Asserts:
 1) single-brain + lore_check: the check runs and its facts reach the writer as a
    POST-history instruction (binding hardest on the next tokens);
 2) it is OFF by default (no silent extra call);
 3) a failing/garbage lore pass never breaks the turn;
 4) saving settings in HOSTED mode no longer wipes a configured lore-keeper.
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
HOME = tempfile.mkdtemp(prefix="cr-lore-")
os.environ["CODERAIN_HOME"] = HOME

from coderain.config import load_config  # noqa: E402
from coderain.engine import Engine  # noqa: E402
from coderain.memory import Library  # noqa: E402

lib = Library(os.path.join(HOME, "lib"))


def _story(name):
    return lib.store(lib.create_story(name, "A courier crosses a frozen kingdom."))


class LoreStub:
    """Single-brain writer + a lore-keeper that answers via the tool path."""
    def __init__(self, reply=None):
        self.tool_calls = 0
        self.writer_msgs = None
        self.reply = reply if reply is not None else json.dumps(
            {"vetted_facts": ["the seal on the box is unbroken"],
             "patches": ["she has never opened it"]})
        self.gen = {}

    def complete_with_tools(self, messages, tools, dispatch, **k):
        self.tool_calls += 1
        assert "LORE-KEEPER" in messages[0]["content"], messages[0]["content"][:80]
        return self.reply

    def stream(self, messages, **k):
        self.writer_msgs = messages
        yield "She keeps walking, the box under her arm."


# ---- 1) runs in single-brain, and binds AFTER the history ------------------
cfg = load_config()
cfg.generation["trinity_brain"] = False        # NO quad pipeline
cfg.generation["lore_check"] = True
store = _story("Solo")
eng = Engine(cfg, store)
assert eng.trinity is None, "quad should be off for this case"
stub = LoreStub()
eng.llm = stub
notes = []
out = "".join(eng.turn("keep walking north", on_stage=notes.append))

assert stub.tool_calls == 1, f"lore-keeper did not run standalone ({stub.tool_calls})"
msgs = stub.writer_msgs
assert msgs[-1]["role"] == "system", "continuity directive is not post-history"
last = msgs[-1]["content"]
assert "CONTINUITY CHECK" in last, last[:200]
assert "the seal on the box is unbroken" in last, last[:300]
assert "CORRECTIONS" in last and "never opened it" in last, last[:400]
assert out.startswith("She keeps walking"), out
assert any("Lore-keeper done" in n for n in notes), notes
print("1) single-brain + lore_check: one extra call, facts bind post-history")

# ---- 2) off by default -----------------------------------------------------
cfg2 = load_config()
cfg2.generation["trinity_brain"] = False
store2 = _story("Off")
eng2 = Engine(cfg2, store2)
stub2 = LoreStub()
eng2.llm = stub2
"".join(eng2.turn("walk on"))
assert stub2.tool_calls == 0, "lore-keeper ran while off (silent extra cost)"
print("2) off by default — no hidden extra call")

# ---- 3) a broken lore pass never breaks the turn ---------------------------
for bad in ("not json at all", None):
    cfg3 = load_config()
    cfg3.generation["trinity_brain"] = False
    cfg3.generation["lore_check"] = True
    store3 = _story(f"Bad{bad is None}")
    eng3 = Engine(cfg3, store3)

    class Broken(LoreStub):
        def complete_with_tools(self, *a, **k):
            self.tool_calls += 1
            if bad is None:
                raise RuntimeError("network died")
            return bad

    s3 = Broken()
    eng3.llm = s3
    got = "".join(eng3.turn("keep going"))
    assert got.startswith("She keeps walking"), f"turn broken by a bad lore pass: {got!r}"
    assert s3.writer_msgs[-1]["role"] != "system" or \
        "CONTINUITY CHECK" not in s3.writer_msgs[-1]["content"]
print("3) a failing lore pass degrades quietly; the turn still completes")

# ---- 4) a hosted settings save keeps the lore-keeper ------------------------
import server  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

c = TestClient(server.app)
server._cfg.raw["trinity"] = {"lorekeeper": {"llm_pass": True,
                                             "profile": "local",
                                             "model": "gemma3:4b"}}
r = c.put("/api/settings", json={
    "mode": "hosted",
    "hosted": {"model": "some-model", "base_url": "https://api.example/v1",
               "context_tokens": 131072},
    "generation": {"lore_check": True},
})
assert r.status_code == 200, r.text
tri = server._cfg.raw.get("trinity") or {}
assert tri.get("lorekeeper", {}).get("llm_pass") is True, \
    f"hosted save wiped the lore-keeper: {tri}"
assert "model" not in tri.get("lorekeeper", {}), \
    "the LOCAL model pin should still be dropped in hosted mode"
assert r.json()["generation"]["lore_check"] is True
print("4) a hosted save keeps the lore-keeper (only local model pins are dropped)")

shutil.rmtree(HOME, ignore_errors=True)
print("\nLORE-CHECK TESTS PASSED")
