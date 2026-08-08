"""The Lore-keeper failed on invalid JSON with no retry and no diagnosis.

Reported from a live 744-turn save: seven "lore-keeper | no valid JSON in
output" entries in ~100 turns, plus a scene fold lost outright.

The lore-keeper was the ONE JSON stage that did not go through emit_json_ex. It
called complete_with_tools and then extract_json by hand, so it got:

  no token floor      every other JSON stage floors at JSON_MIN_TOKENS
  no retry            emit_json_ex retries once with a corrective nudge
  no escalation       a starved reply was never re-asked with more room
  no diagnosis        "no valid JSON in output", with no tail to explain it

emit_json_ex takes any object exposing .complete(), so _ToolJSONClient adapts
the tool-calling stage into it without giving up tool use.

 1) the adapter forwards tools and returns the model's text
 2) it exposes .gen, so emit_json_ex applies the token floor
 3) a malformed first reply is RETRIED and can succeed
 4) a starved reply escalates the budget on the retry
 5) the failure reason reaches health.jsonl, not just the symptom
 6) a working lore-keeper still produces its directive
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-lorejson-"))
os.environ["CODERAIN_HOME"] = str(WORK)

from coderain.config import load_config                    # noqa: E402
from coderain.engine import Engine, _ToolJSONClient         # noqa: E402
from coderain.llm import JSON_MIN_TOKENS, emit_json_ex      # noqa: E402
from coderain.memory import Library                         # noqa: E402

GOOD = json.dumps({"vetted_facts": ["Aspen owes Jinx a favour"], "patches": []})

lib = Library(WORK / "lib")


class FakeLLM:
    """Records every tool-call and budget, replies from a script."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.gen = {"max_tokens": 700}
        self.budgets, self.tools_seen = [], []

    def complete_with_tools(self, messages, tools, dispatch, **kw):
        self.budgets.append(kw.get("max_tokens"))
        self.tools_seen.append(len(tools))
        return self.replies.pop(0) if self.replies else ""

    def as_stage(self, name):
        import contextlib
        return contextlib.nullcontext()


def test_adapter_forwards_tools():
    f = FakeLLM([GOOD])
    c = _ToolJSONClient(f, [{"a": 1}, {"b": 2}], lambda *a: None)
    assert c.complete([{"role": "user", "content": "x"}]) == GOOD
    assert f.tools_seen == [2], f.tools_seen
    print("1. adapter forwards the tool list and returns the reply")


def test_adapter_exposes_gen():
    """§2 emit_json_ex only applies the token floor to a client with .gen."""
    f = FakeLLM([GOOD])
    c = _ToolJSONClient(f, [], lambda *a: None)
    assert c.gen == f.gen
    emit_json_ex(c, "sys", "payload")
    assert f.budgets[0] == JSON_MIN_TOKENS, f.budgets
    print(f"2. token floor applied: {f.budgets[0]}")


def test_malformed_is_retried():
    f = FakeLLM(["I think the answer is probably fine.", GOOD])
    obj, err = emit_json_ex(_ToolJSONClient(f, [], lambda *a: None),
                            "sys", "payload")
    assert err is None and obj["vetted_facts"], (obj, err)
    assert len(f.budgets) == 2, f.budgets
    print("3. a malformed first reply is retried and recovers")


def test_starved_reply_escalates():
    f = FakeLLM(['{"vetted_facts": ["cut off', GOOD])
    obj, _ = emit_json_ex(_ToolJSONClient(f, [], lambda *a: None),
                          "sys", "payload")
    assert obj is not None
    assert f.budgets[1] > f.budgets[0], f.budgets
    print(f"4. truncated reply escalated the budget: {f.budgets}")


def _engine_with(replies):
    store = lib.store(lib.create_story(f"L{len(replies)}", "A courier."))
    store.append_turn("player", "look")
    store.append_turn("narrator", "Rain.")
    cfg = load_config()
    cfg.generation["trinity_brain"] = False
    cfg.generation["lore_check"] = True
    eng = Engine(cfg, store)
    eng.llm = FakeLLM(replies)
    return eng, store


def test_reason_reaches_health():
    """§5 the diagnosis. 'no valid JSON' cannot tell you whether to raise the
    budget or fix the prompt; the reason can."""
    eng, store = _engine_with(["not json", "still not json"])
    out = eng._lore_check([{"role": "system", "content": "ctx"},
                           {"role": "user", "content": "act"}], None)
    assert out == "", out
    health = store.read("memory/health.jsonl")
    assert "no usable JSON" in health, health
    assert "tail" in health or "empty" in health, health
    print("5. the failure REASON is logged, not just the symptom")


def test_working_lore_keeper_still_works():
    eng, _ = _engine_with([GOOD])
    out = eng._lore_check([{"role": "system", "content": "ctx"},
                           {"role": "user", "content": "act"}], None)
    assert "CONTINUITY CHECK" in out and "Aspen owes Jinx" in out, out
    print("6. a valid reply still produces the continuity directive")


try:
    for fn in (test_adapter_forwards_tools,
               test_adapter_exposes_gen,
               test_malformed_is_retried,
               test_starved_reply_escalates,
               test_reason_reaches_health,
               test_working_lore_keeper_still_works):
        fn()
finally:
    shutil.rmtree(WORK, ignore_errors=True)
print("\nLORE-KEEPER JSON TESTS PASSED")
