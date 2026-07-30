"""A starved JSON stage must get a BIGGER budget on retry, not the same one.

Found by running real folds through qwen3:4b: scene 1 failed "JSON truncated
(unclosed brace)", scene 2 failed "model returned empty output", both at the
8192 JSON_MIN_TOKENS floor. A fold is one-way — its pointer advances whether or
not a summary came back — so each failure permanently compressed those turns to
"(scene summary unavailable)".

The retry could not have rescued either one. It re-sent at the SAME max_tokens
with the nudge "That was not valid JSON", so a reply that was cut off for lack
of room was cut off identically the second time. Reasoning length scales with
payload size, so raising the constant alone just moves the cliff.

 1) a truncated reply escalates max_tokens on the retry
 2) an empty reply escalates too (the other starvation shape)
 3) escalation stops at JSON_RETRY_CEILING
 4) a well-formed-but-wrong reply does NOT escalate — that model needs
    correcting, not more room
 5) the nudge tells a starved model to be brief, not that it was invalid
 6) a retry that then succeeds returns the object with no error
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-jsonret-"))
os.environ["CODERAIN_HOME"] = str(WORK)

from coderain.llm import (JSON_MIN_TOKENS, JSON_RETRY_CEILING,   # noqa: E402
                          emit_json_ex)


class Fake:
    """Minimal stand-in for LLM: records the budget of every call and replies
    from a scripted list. `gen` must exist for emit_json_ex to set max_tokens."""

    def __init__(self, replies, max_tokens=JSON_MIN_TOKENS):
        self.replies = list(replies)
        self.gen = {"max_tokens": max_tokens}
        self.budgets: list[int] = []
        self.prompts: list[str] = []

    def complete(self, messages, **kw):
        self.budgets.append(kw.get("max_tokens"))
        self.prompts.append(messages[-1]["content"])
        return self.replies.pop(0) if self.replies else ""


TRUNCATED = '{"scene_summary": "She crossed the ice and the'   # unclosed
GOOD = '{"scene_summary": "She crossed the ice."}'


def test_truncated_reply_escalates():
    f = Fake([TRUNCATED, TRUNCATED])
    obj, err = emit_json_ex(f, "sys", "payload")
    assert obj is None
    assert len(f.budgets) == 2, f.budgets
    assert f.budgets[1] > f.budgets[0], f.budgets
    assert f.budgets[1] == f.budgets[0] * 2, f.budgets
    print("1. truncated -> retry budget doubled:", f.budgets)


def test_empty_reply_escalates():
    f = Fake(["", ""])
    obj, err = emit_json_ex(f, "sys", "payload")
    assert obj is None and "empty" in err, err
    assert f.budgets[1] == f.budgets[0] * 2, f.budgets
    print("2. empty output -> retry budget doubled:", f.budgets)


def test_escalation_is_capped():
    f = Fake([TRUNCATED, TRUNCATED], max_tokens=JSON_RETRY_CEILING)
    emit_json_ex(f, "sys", "payload")
    assert f.budgets[1] <= JSON_RETRY_CEILING, f.budgets
    print("3. escalation capped at JSON_RETRY_CEILING:", f.budgets)


def test_valid_json_wrong_shape_does_not_escalate():
    """A parseable non-dict is the model being WRONG, not starved. Handing it a
    bigger budget would just buy a longer wrong answer."""
    f = Fake(["not json at all", "still not json"])
    emit_json_ex(f, "sys", "payload")
    assert f.budgets[1] == f.budgets[0], f.budgets
    print("4. malformed-but-complete -> budget unchanged:", f.budgets)


def test_nudge_matches_the_failure():
    f = Fake([TRUNCATED, TRUNCATED])
    emit_json_ex(f, "sys", "payload")
    assert "ran out of room" in f.prompts[1], f.prompts[1]
    g = Fake(["not json at all", "nope"])
    emit_json_ex(g, "sys", "payload")
    assert "not valid JSON" in g.prompts[1], g.prompts[1]
    print("5. starved gets 'be brief', wrong gets 'that was not valid JSON'")


def test_escalated_retry_can_succeed():
    f = Fake([TRUNCATED, GOOD])
    obj, err = emit_json_ex(f, "sys", "payload")
    assert err is None and obj == {"scene_summary": "She crossed the ice."}, (obj, err)
    assert f.budgets[1] == f.budgets[0] * 2, f.budgets
    print("6. escalated retry recovers the fold")


for fn in (test_truncated_reply_escalates,
           test_empty_reply_escalates,
           test_escalation_is_capped,
           test_valid_json_wrong_shape_does_not_escalate,
           test_nudge_matches_the_failure,
           test_escalated_retry_can_succeed):
    fn()
shutil.rmtree(WORK, ignore_errors=True)
print("\nJSON RETRY ESCALATION TESTS PASSED")
