"""Real token counts, per turn and per stage (2026-07-28).

The provider tells us exactly what every call cost. llm.py used to skip those
frames — the comment even named them ("usage/keep-alive frames arrive with empty
choices") — and the app estimated tokens from character counts instead.

Asserts:
 1) the usage frame is captured off the stream and recorded through on_usage;
 2) a provider that rejects stream_options degrades once, silently, and the
    generation still completes;
 3) the store keeps a per-stage ledger, bounded, with lifetime totals that
    survive the trimming;
 4) stages are labelled through a helper that tolerates a stub client;
 5) the API reports it and Settings round-trips the price.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
HOME = tempfile.mkdtemp(prefix="cr-usage-")
os.environ["CODERAIN_HOME"] = HOME

from coderain import llm as llm_mod  # noqa: E402
from coderain.config import load_config  # noqa: E402
from coderain.memory import Library  # noqa: E402

lib = Library(os.path.join(HOME, "lib"))
store = lib.store(lib.create_story("Ledger", "A cartographer sells maps of "
                                             "places that do not exist yet."))


class _Usage:
    def __init__(self, i, o):
        self.prompt_tokens, self.completion_tokens = i, o
        self.prompt_tokens_details = None


class _Chunk:
    def __init__(self, text=None, usage=None):
        self.usage = usage
        if text is None:
            self.choices = []                    # the usage frame carries none
        else:
            self.choices = [type("C", (), {"delta": type("D", (), {
                "content": text})()})()]


class _Completions:
    """A provider that answers with two text frames then a usage frame."""

    def __init__(self, reject_stream_options=False):
        self.reject = reject_stream_options
        self.saw_stream_options = []

    def create(self, **kw):
        self.saw_stream_options.append("stream_options" in kw)
        if self.reject and "stream_options" in kw:
            err = Exception("unknown field: stream_options")
            err.status_code = 400
            raise err
        return iter([_Chunk("Rain "), _Chunk("falls."), _Chunk(None, _Usage(120, 34))])


def _client(reject=False):
    comp = _Completions(reject)
    client = type("Cl", (), {})()
    client.chat = type("Ch", (), {})()
    client.chat.completions = comp
    return client, comp


cfg = load_config()

# ---- 1) the usage frame is captured ------------------------------------
llm = llm_mod.LLM(cfg.profile, cfg.generation)
llm.client, comp = _client()
seen = []
llm.on_usage = seen.append
text = "".join(llm.stream([{"role": "user", "content": "go"}]))
assert text == "Rain falls.", text
assert llm.last_usage == {"stage": "writer", "model": cfg.profile.model,
                          "in": 120, "out": 34}, llm.last_usage
assert seen and seen[0]["in"] == 120, seen
assert comp.saw_stream_options == [True], "we must ASK for usage"
print("1) usage captured off the stream and handed to on_usage")

# ---- 2) a provider that rejects the option still works ------------------
llm2 = llm_mod.LLM(cfg.profile, cfg.generation)
llm2.client, comp2 = _client(reject=True)
got = []
llm2.on_usage = got.append
assert "".join(llm2.stream([{"role": "user", "content": "go"}])) == "Rain falls."
assert comp2.saw_stream_options == [True, False], \
    f"expected ask-then-retry, got {comp2.saw_stream_options}"
assert "".join(llm2.stream([{"role": "user", "content": "again"}])) == "Rain falls."
assert comp2.saw_stream_options == [True, False, False], \
    "it must STOP asking after one rejection, not retry every turn"
print("2) a provider without stream_options degrades once and keeps generating")

# ---- 3) the ledger ------------------------------------------------------
for i in range(3):
    store.log_usage({"stage": "writer", "model": "m", "in": 100, "out": 20})
store.log_usage({"stage": "fold", "model": "m", "in": 900, "out": 80})
store.log_usage({"stage": "director", "model": "m", "in": 50, "out": 10})
tot = store.usage_total()
assert tot["in"] == 3 * 100 + 900 + 50 and tot["out"] == 3 * 20 + 80 + 10, tot
assert tot["by_stage"]["writer"]["calls"] == 3, tot["by_stage"]
assert tot["by_stage"]["fold"]["in"] == 900, tot["by_stage"]
assert len(store.usage()) == 5 and store.usage()[0]["stage"] == "director", \
    "usage() must be newest-first"
# bounded, but the lifetime sum must survive the trim
for i in range(520):
    store.log_usage({"stage": "spam", "model": "m", "in": 1, "out": 1})
rows = (Path(store.dir) / "memory" / "usage.jsonl").read_text(
    encoding="utf-8").splitlines()
assert len(rows) <= 500, f"ledger is unbounded: {len(rows)}"
assert store.usage_total()["in"] == 3 * 100 + 900 + 50 + 520, \
    "trimming the ledger lost the lifetime total"
# a store whose folder is gone must not raise
gone = lib.store(lib.create_story("Gone", "x"))
shutil.rmtree(gone.dir, ignore_errors=True)
gone.log_usage({"stage": "x", "model": "m", "in": 1, "out": 1})   # must not raise
print("3) per-stage ledger, bounded, totals survive the trim, never raises")

# ---- 4) stage labelling tolerates a stub --------------------------------
class _Stub:                       # what the trinity/summarizer tests inject
    pass


with llm_mod.stage(_Stub(), "director"):
    pass                           # must not raise
with llm_mod.stage(llm, "fold"):
    assert llm.stage == "fold"
assert llm.stage == "writer", "as_stage must restore the previous label"
print("4) stage() labels a real client and no-ops on a stub")

# ---- 5) API + settings round-trip ---------------------------------------
import server  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

c = TestClient(server.app)
slug = c.post("/api/saves", json={
    "title": "Spend", "mode": "simple",
    "premise": "A tollkeeper counts what crosses the bridge."}).json()["slug"]
st = c.get(f"/api/saves/{slug}").json()
server._engine(slug).store.log_usage(
    {"stage": "writer", "model": "m", "in": 2000, "out": 300})
u = c.get(f"/api/saves/{slug}/usage").json()
assert u["total_in"] == 2000 and u["total_out"] == 300, u
assert u["by_stage"]["writer"]["calls"] == 1, u
ctx = c.get(f"/api/saves/{slug}/context").json()
assert ctx["usage"]["total_in"] == 2000, "the inspector must carry real usage"
r = c.put("/api/settings", json={"price_in": 0.27, "price_out": 1.1})
assert r.status_code == 200, r.text
back = c.get("/api/settings").json()
assert back["price_in"] == 0.27 and back["price_out"] == 1.1, back
assert c.get(f"/api/saves/{slug}/usage").json()["price_in"] == 0.27
print(f"5) /usage + inspector report real tokens; price round-trips "
      f"({st['title']} -> {u['total_in']} in)")

shutil.rmtree(HOME, ignore_errors=True)
print("\nUSAGE LEDGER TESTS PASSED")
