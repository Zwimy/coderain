"""Thinking was whatever the model felt like doing.

llm.py never sent a `reasoning` key, so a model's DEFAULT behaviour was what you
got and there was no way to change it from inside the app. filter_think strips
<think> only AFTER those tokens are generated and billed.

Measured on the live OpenRouter catalogue (2026-08-22): deepseek-v4-flash
defaults to "high" effort; ling-3.0-flash and qwen3.7-flash carry
"default_enabled": true. At ~2.2 billable calls per turn and ~2500 reasoning
tokens each, against 1540 measured output tokens, that is about a 4.5x
multiplier on output billing -- and it eats the OUTPUT budget before the JSON,
which is the failure JSON_MIN_TOKENS / JSON_RETRY_CEILING exist to survive.

 1) absent config sends NO reasoning key (the old behaviour, exactly)
 2) the shorthand forms normalise to the provider shape
 3) an unrecognised value is treated as unset, not as "on"
 4) the key rides in extra_body without clobbering repetition_penalty
 5) a provider that rejects `reasoning` degrades once, then stops sending it
 6) that rejection does NOT also disable usage accounting
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-reason-"))
os.environ["CODERAIN_HOME"] = str(WORK)

from coderain.config import Profile                      # noqa: E402
from coderain.llm import LLM, _reasoning_block, _without_reasoning  # noqa: E402

PROF = Profile(name="t", base_url="http://localhost:1/v1", model="m",
               api_key="k", context_tokens=32768)


def _llm(**gen):
    return LLM(PROF, {"max_tokens": 700, **gen})


def test_absent_sends_nothing():
    p = _llm()._params()
    assert "reasoning" not in (p.get("extra_body") or {}), p
    assert _reasoning_block(None) is None and _reasoning_block("") is None
    print("1. no config -> no reasoning key at all")


def test_shorthands_normalise():
    cases = {False: {"enabled": False}, "off": {"enabled": False},
             "none": {"enabled": False}, True: {"enabled": True},
             "high": {"effort": "high"}, "minimal": {"effort": "minimal"},
             "xhigh": {"effort": "xhigh"},
             frozenset(): None}
    for raw, want in cases.items():
        if isinstance(raw, frozenset):
            continue
        assert _reasoning_block(raw) == want, (raw, _reasoning_block(raw))
    assert _reasoning_block({"effort": "low"}) == {"effort": "low"}, "dict passthrough"
    print(f"2. {len(cases) - 1} shorthand forms normalise correctly")


def test_garbage_is_unset_not_on():
    """§3 the dangerous default. Treating an unrecognised value as `enabled:
    true` would switch thinking ON for models that default it off, which is the
    exact bill this feature exists to stop."""
    for bad in ("bogus", "verylow", "1", 7, []):
        assert _reasoning_block(bad) is None, bad
    print("3. an unrecognised value behaves as unset, never as 'on'")


def test_rides_in_extra_body_without_clobbering():
    p = _llm(reasoning="off", repetition_penalty=1.1)._params()
    eb = p.get("extra_body") or {}
    assert eb.get("reasoning") == {"enabled": False}, eb
    assert eb.get("repetition_penalty") == 1.1, eb
    print("4. reasoning and repetition_penalty coexist in extra_body")


class _Boom:
    """A provider that 400s on `reasoning` and succeeds without it."""

    def __init__(self):
        self.seen = []

    def create(self, **kw):
        self.seen.append(kw)
        if "reasoning" in (kw.get("extra_body") or {}):
            err = Exception("400 unknown field: reasoning")
            err.status_code = 400
            raise err
        return "OK"


def _wire(llm, fake):
    class _C:
        pass
    c, comp = _C(), _C()
    comp.completions = fake
    c.chat = comp
    llm.client = c
    return llm


def test_rejection_degrades_once():
    llm = _wire(_llm(reasoning="off"), None)
    fake = _Boom()
    _wire(llm, fake)
    out = llm._create_stream(model="m", messages=[], stream=True,
                             **llm._params())
    assert out == "OK", out
    assert llm._send_reasoning is False, "did not latch the rejection off"
    assert any("reasoning" in (k.get("extra_body") or {}) for k in fake.seen)
    assert "reasoning" not in (fake.seen[-1].get("extra_body") or {})
    # and the NEXT request must not carry it either
    assert "reasoning" not in (llm._params().get("extra_body") or {})
    print(f"5. rejected once ({len(fake.seen)} calls), then never sent again")


def test_rejection_keeps_usage_accounting():
    """§6 the two extensions ride the same call. Dropping both on one 400 would
    blind memory/usage.jsonl for a rejection that was never about usage."""
    llm = _llm(reasoning="off")
    _wire(llm, _Boom())
    llm._create_stream(model="m", messages=[], stream=True, **llm._params())
    assert llm._send_reasoning is False
    assert llm._ask_usage is True, "usage accounting was collateral damage"
    print("6. the reasoning rejection did not disable usage accounting")


def test_without_reasoning_helper():
    assert _without_reasoning({"a": 1}) == {"a": 1}
    assert "extra_body" not in _without_reasoning(
        {"extra_body": {"reasoning": {"enabled": False}}})
    kept = _without_reasoning({"extra_body": {"reasoning": {}, "repetition_penalty": 1.1}})
    assert kept["extra_body"] == {"repetition_penalty": 1.1}, kept


try:
    for fn in (test_absent_sends_nothing, test_shorthands_normalise,
               test_garbage_is_unset_not_on,
               test_rides_in_extra_body_without_clobbering,
               test_rejection_degrades_once,
               test_rejection_keeps_usage_accounting,
               test_without_reasoning_helper):
        fn()
finally:
    shutil.rmtree(WORK, ignore_errors=True)
print("\nREASONING PARAM TESTS PASSED")
