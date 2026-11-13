"""A system message after the player's turn made llama3.1:8b start every reply with the word "assistant" (D-054).

What broke. The engine puts its per-turn directives (the chapter goal, the canon card, fate's note, the continuity pass) AFTER the
player's action, as system messages, because the end of the prompt binds hardest. Through a local Ollama, llama3.1:8b renders such
a message as the start of its OWN reply: the narration began with the literal line "assistant" and a blank line. Measured with a
raw client, 6 replies each: [system, user] 0 of 6, [system, user, system] 6 of 6, [system, user, system, system] 6 of 6, the same
words folded into the user turn 0 of 6; gemma3:4b was clean in all four shapes. A story with the default chapter outline hits it
from the first turn. The fix folds a trailing run of system messages into the last user turn, for a server on this machine only.

 1) fold_late_system: one or several trailing system messages are appended to the last user turn, in order, blank-line separated;
    after an assistant turn they become a user turn of their own; everything else (system messages before the player's turn or in
    the middle, a request that is only system messages, a user turn that is not text) is left alone; the input is not modified
 2) is_local: loopback hosts with or without a port are local, hosted providers and garbage are not
 3) needs_fold: a llama-family model on a server on this machine, and nothing else (gemma3:4b was clean AND looped more in a fate-on
    soak when its note rode in the user turn: 103 recurring 8-word runs against 9, 11 turns sharing an opening against 0)
 4) the client folds by that rule, and generation.fold_late_system true or false overrides it either way
 5) the folding applies to the streaming path and to the tool-calling path
"""
import copy
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["CODERAIN_HOME"] = tempfile.mkdtemp(prefix="cr-latesys-")

from coderain.config import Profile                              # noqa: E402
from coderain.llm import LLM, fold_late_system, is_local, needs_fold    # noqa: E402

S = lambda t: {"role": "system", "content": t}                   # noqa: E731
U = lambda t: {"role": "user", "content": t}                     # noqa: E731
A = lambda t: {"role": "assistant", "content": t}                # noqa: E731


def test_fold():
    msgs = [S("rules"), U("I step off the ferry."), S("# THIS CHAPTER\nreach the gate")]
    before = copy.deepcopy(msgs)
    got = fold_late_system(msgs)
    assert got == [S("rules"), U("I step off the ferry.\n\n# THIS CHAPTER\nreach the gate")], got
    assert msgs == before and got is not msgs, "the caller's list or messages were modified"
    got = fold_late_system([S("rules"), U("go"), S("card"), S("chapter"), S("steer")])
    assert got == [S("rules"), U("go\n\ncard\n\nchapter\n\nsteer")], got
    # a Continue: the last non-system message is the narrator's, so the notes become a user turn
    assert fold_late_system([S("rules"), U("go"), A("It rains."), S("chapter")]) == \
        [S("rules"), U("go"), A("It rains."), U("chapter")]
    # nothing late: returned as is (the same object)
    plain = [S("rules"), U("go")]
    assert fold_late_system(plain) is plain
    only = [S("a"), S("b")]
    assert fold_late_system(only) is only, "a request of system messages alone has no user turn to fold into"
    mid = [S("rules"), U("go"), S("aside"), A("It rains."), U("again")]
    assert fold_late_system(mid) is mid, "a system message in the middle is not 'late'"
    # empty notes are dropped; nothing to say means no change to the user turn
    assert fold_late_system([S("rules"), U("go"), S("  "), S("")]) == [S("rules"), U("go")]
    # a user turn that is not plain text is not edited: the notes get a turn of their own instead
    parts = {"role": "user", "content": [{"type": "text", "text": "go"}]}
    assert fold_late_system([S("rules"), parts, S("chapter")]) == [S("rules"), parts, U("chapter")]
    assert fold_late_system([]) == []
    print("1. trailing system messages join the last user turn in order; nothing else is touched or modified")


def test_is_local():
    for url in ("http://localhost:11434/v1", "http://127.0.0.1:8080/v1", "http://[::1]:11434/v1", "http://LOCALHOST/v1",
                "http://0.0.0.0:1234/v1"):
        assert is_local(url), url
    for url in ("https://openrouter.ai/api/v1", "https://api.openai.com/v1", "http://192.168.1.20:11434/v1",
                "http://localhost.example.com/v1", "", None, "not a url", "http://[bad"):
        assert not is_local(url), url
    print("2. loopback is local; a hosted provider, a LAN address and garbage are not")


class Fake:
    """Stands in for the OpenAI client: remembers the messages it was sent."""

    def __init__(self):
        self.sent = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.sent.append(kw["messages"])
        if kw.get("stream"):
            return iter([SimpleNamespace(usage=None, choices=[SimpleNamespace(delta=SimpleNamespace(content="ok"))])])
        return SimpleNamespace(usage=None, choices=[SimpleNamespace(message=SimpleNamespace(content="done", tool_calls=None))])


def llm(url, model="llama3.1:8b", **gen):
    out = LLM(Profile(name="t", base_url=url, model=model, api_key="k", context_tokens=8192), {"max_tokens": 50, **gen})
    out.client = Fake()
    return out


LATE = [S("rules"), U("go"), S("chapter")]
FOLDED = [S("rules"), U("go\n\nchapter")]


def test_needs_fold():
    yes = [("http://localhost:11434/v1", "llama3.1:8b"), ("http://127.0.0.1:8080/v1", "hf.co/someone/Llama-3-8B-GGUF:Q4_K_M"),
           ("http://localhost:11434/v1", "dolphin-llama3:8b"), ("http://localhost:11434/v1", "LLAMA3.2")]
    no = [("http://localhost:11434/v1", "gemma3:4b"), ("http://localhost:11434/v1", "qwen3:4b"),
          ("http://localhost:11434/v1", "deepseek-r1:8b"), ("http://localhost:11434/v1", ""), ("http://localhost:11434/v1", None),
          ("https://openrouter.ai/api/v1", "meta-llama/llama-3.1-70b-instruct"),     # a hosted provider handles roles itself
          ("http://192.168.1.20:11434/v1", "llama3.1:8b")]
    for url, model in yes:
        assert needs_fold(url, model), (url, model)
    for url, model in no:
        assert not needs_fold(url, model), (url, model)
    print("3. only a llama-family model on a server on this machine folds by default")


def test_client():
    local = llm("http://localhost:11434/v1")
    assert local.fold_late is True
    assert local.complete(LATE) == "ok" and local.client.sent == [FOLDED], local.client.sent
    gemma = llm("http://localhost:11434/v1", model="gemma3:4b")
    assert gemma.fold_late is False
    gemma.complete(LATE)
    assert gemma.client.sent == [LATE], "a local model that does not need the fold was sent a changed request"
    hosted = llm("https://openrouter.ai/api/v1", model="meta-llama/llama-3.1-70b-instruct")
    assert hosted.fold_late is False
    hosted.complete(LATE)
    assert hosted.client.sent == [LATE], "a hosted provider was sent a changed request"
    off = llm("http://localhost:11434/v1", fold_late_system=False)
    off.complete(LATE)
    assert off.client.sent == [LATE], "the override to keep did not hold"
    on = llm("http://localhost:11434/v1", model="qwen3:4b", fold_late_system=True)
    on.complete(LATE)
    assert on.client.sent == [FOLDED], "the override to fold did not hold"
    odd = llm("http://localhost:11434/v1", fold_late_system="yes")
    assert odd.fold_late is True, "a value that is not a real boolean must fall back to the default for this model"
    assert llm("http://localhost:11434/v1", model="gemma3:4b", fold_late_system="yes").fold_late is False
    print("4. the client folds by that rule, and generation.fold_late_system overrides it either way")


def test_tools_path():
    local = llm("http://localhost:11434/v1")
    assert local.complete_with_tools(LATE, tools=[], dispatch=lambda n, a: "") == "done"
    assert local.client.sent == [FOLDED], local.client.sent
    gemma = llm("http://localhost:11434/v1", model="gemma3:4b")
    gemma.complete_with_tools(LATE, tools=[], dispatch=lambda n, a: "")
    assert gemma.client.sent == [LATE]
    print("5. the tool-calling path folds too, by the same rule")


for fn in (test_fold, test_is_local, test_needs_fold, test_client, test_tools_path):
    fn()
print("\nLLM LATE SYSTEM TESTS PASSED")
