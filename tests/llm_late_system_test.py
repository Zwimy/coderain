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
 3) the client folds for a local profile and not for a hosted one; generation.fold_late_system true or false overrides either way
 4) the folding applies to the streaming path and to the tool-calling path
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
from coderain.llm import LLM, fold_late_system, is_local         # noqa: E402

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


def llm(url, **gen):
    out = LLM(Profile(name="t", base_url=url, model="m", api_key="k", context_tokens=8192), {"max_tokens": 50, **gen})
    out.client = Fake()
    return out


LATE = [S("rules"), U("go"), S("chapter")]
FOLDED = [S("rules"), U("go\n\nchapter")]


def test_client():
    local = llm("http://localhost:11434/v1")
    assert local.fold_late is True
    assert local.complete(LATE) == "ok" and local.client.sent == [FOLDED], local.client.sent
    hosted = llm("https://openrouter.ai/api/v1")
    assert hosted.fold_late is False
    hosted.complete(LATE)
    assert hosted.client.sent == [LATE], "a hosted provider was sent a changed request"
    off = llm("http://localhost:11434/v1", fold_late_system=False)
    off.complete(LATE)
    assert off.client.sent == [LATE], "the override to keep did not hold"
    on = llm("https://openrouter.ai/api/v1", fold_late_system=True)
    on.complete(LATE)
    assert on.client.sent == [FOLDED], "the override to fold did not hold"
    odd = llm("http://localhost:11434/v1", fold_late_system="yes")
    assert odd.fold_late is True, "a value that is not a real boolean must fall back to the default for this host"
    assert llm("https://openrouter.ai/api/v1", fold_late_system="yes").fold_late is False
    print("3. a local profile folds, a hosted one does not, and generation.fold_late_system overrides either way")


def test_tools_path():
    local = llm("http://localhost:11434/v1")
    assert local.complete_with_tools(LATE, tools=[], dispatch=lambda n, a: "") == "done"
    assert local.client.sent == [FOLDED], local.client.sent
    hosted = llm("https://openrouter.ai/api/v1")
    hosted.complete_with_tools(LATE, tools=[], dispatch=lambda n, a: "")
    assert hosted.client.sent == [LATE]
    print("4. the tool-calling path folds too")


for fn in (test_fold, test_is_local, test_client, test_tools_path):
    fn()
print("\nLLM LATE SYSTEM TESTS PASSED")
