"""The settings a hosted model needs (D-076): which OpenRouter providers may serve a request, Min-p, and strict JSON replies.

 1) Min-p goes in extra_body only when set, beside the repetition penalty, and a caller's own value wins
 2) the provider block goes to OpenRouter only, and a value that is not a mapping stops the request
 3) no fallback ever sends a request without the provider block
 4) a server that names Min-p or JSON mode in its refusal gets requests without it, once, said in the health log, usage kept
 5) a refusal that names neither: both are given up only if the request works without them
 6) a request that fails either way keeps them
 7) the memory tool's loop gets the same care, and never JSON mode beside tools
 8) strict JSON only for JSON calls whose prompt asks for JSON, only when switched on with a real true; fate asks too
 9) semantic recall embeds with the same provider block when it embeds at OpenRouter
10) Settings writes its part of the provider block, keeps the rest, and refuses a name that cannot be a provider
11) the engine writes a refused setting to the story's health log
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-hosted-"))
os.environ["CODERAIN_HOME"] = str(WORK)

from fastapi.testclient import TestClient                          # noqa: E402

import server                                                       # noqa: E402
from coderain import fate                                           # noqa: E402
from coderain.config import Config, Profile                         # noqa: E402
from coderain.llm import LLM, emit_json_ex, is_openrouter, json_overrides  # noqa: E402
from coderain.modules import vector as vector_mod                   # noqa: E402
from srv import core                                                # noqa: E402


def _llm(base="http://localhost:1/v1", **gen):
    return LLM(Profile(name="t", base_url=base, model="m", api_key="k", context_tokens=32768), {"max_tokens": 700, **gen})


OR = "https://openrouter.ai/api/v1"
PRIVATE = {"data_collection": "deny", "zdr": True}


class _Server:
    """A fake chat.completions: `refuse(kw)` returns the error text to answer with, or None to accept."""

    def __init__(self, refuse=lambda kw: None, status=400):
        self.refuse, self.status, self.seen = refuse, status, []

    def create(self, **kw):
        self.seen.append(kw)
        why = self.refuse(kw)
        if why:
            err = Exception(why)
            err.status_code = self.status
            raise err
        return "OK"


def _wire(llm, fake):
    class _C:
        pass
    client, chat = _C(), _C()
    chat.completions = fake
    client.chat = chat
    llm.client = client
    llm.notices = []
    llm.on_notice = llm.notices.append
    return llm


def _send(llm, **overrides):
    return llm._create_stream(model="m", messages=[], stream=True, **llm._params(**overrides))


def _eb(kw):
    return kw.get("extra_body") or {}


JSON_FORMAT = {"type": "json_object"}


# ---------- 1: min_p ----------
def test_min_p():
    assert "min_p" not in _eb(_llm()._params())
    eb = _eb(_llm(min_p=0.05, repetition_penalty=1.1)._params())
    assert eb == {"min_p": 0.05, "repetition_penalty": 1.1}, eb
    assert _eb(_llm(min_p=0.05)._params(extra_body={"min_p": 0.2}))["min_p"] == 0.2, "a caller's own value wins"
    assert _eb(_llm(min_p=0)._params())["min_p"] == 0, "zero is a value, not unset"
    print("1. Min-p only when set, beside the repetition penalty, a caller's own wins")


# ---------- 2: the provider block ----------
def test_provider_block_only_for_openrouter():
    for yes in (OR, "https://eu.openrouter.ai/api/v1", "https://OpenRouter.ai./api/v1"):
        assert is_openrouter(yes), yes
        assert _eb(_llm(yes, openrouter_provider=PRIVATE)._params())["provider"] == PRIVATE, yes
    for no in ("http://localhost:11434/v1", "https://openrouter.ai.example.com/v1", "https://notopenrouter.ai/v1",
               "https://api.deepseek.com/v1"):
        assert "provider" not in _eb(_llm(no, openrouter_provider=PRIVATE)._params()), no
    assert "provider" not in _eb(_llm(OR, openrouter_provider={})._params())
    for bad in ("zdr", ["zdr"], True):
        try:
            _llm(OR, openrouter_provider=bad)._params()
        except ValueError as e:
            assert "openrouter_provider" in str(e)
        else:
            raise AssertionError(f"{bad!r} must stop the request, not be dropped quietly")
        _llm(openrouter_provider=bad)._params()            # a local server never sends it, so it does not stop there
    print("2. the provider block goes to OpenRouter only; a value that is not a mapping stops the request there")


# ---------- 3: the privacy choice is never dropped ----------
def test_provider_is_never_dropped():
    llm = _wire(_llm(OR, openrouter_provider=PRIVATE, min_p=0.1, reasoning="off"),
                _Server(lambda kw: "400 unknown field in provider routing"))
    try:
        _send(llm, response_format=JSON_FORMAT)
    except Exception as e:
        assert "provider routing" in str(e)
    else:
        raise AssertionError("a server that refuses every request must fail it")
    fake = llm.client.chat.completions
    assert len(fake.seen) >= 2 and all(_eb(kw).get("provider") == PRIVATE for kw in fake.seen), fake.seen
    try:
        llm._create_plain(model="m", messages=[], **llm._params())
    except Exception:
        pass
    assert all(_eb(kw).get("provider") == PRIVATE for kw in fake.seen)
    assert llm._params()["extra_body"]["provider"] == PRIVATE
    print(f"3. {len(fake.seen)} refused tries, every one with the provider block")


# ---------- 4: a refusal that names the setting ----------
def test_named_refusal():
    for name, refuse, present in (
            ("min_p", lambda kw: "400 unrecognized request argument: min_p" if "min_p" in _eb(kw) else None,
             lambda kw: "min_p" in _eb(kw)),
            ("response_format", lambda kw: "400 response_format json_object is not supported by this model"
             if "response_format" in kw else None, lambda kw: "response_format" in kw)):
        llm = _wire(_llm(min_p=0.1), _Server(refuse))
        assert _send(llm, response_format=JSON_FORMAT) == "OK"
        fake = llm.client.chat.completions
        assert not present(fake.seen[-1]), name
        other = "response_format" if name == "min_p" else "min_p"
        assert ("response_format" in fake.seen[-1]) if other == "response_format" else ("min_p" in _eb(fake.seen[-1])), \
            f"only {name} is given up"
        assert llm._ask_usage is True, "usage accounting was collateral damage"
        assert len(fake.seen) == 2 and len(llm.notices) == 1, (len(fake.seen), llm.notices)
        _send(llm, response_format=JSON_FORMAT)
        assert not present(fake.seen[-1]) and len(fake.seen) == 3, "it must not be sent again"
    print("4. a setting the refusal names is dropped once, said once, and usage accounting stays on")


# ---------- 5: a refusal that names nothing ----------
def test_unnamed_refusal_that_works_bare():
    llm = _wire(_llm(min_p=0.1), _Server(lambda kw: "400 invalid request" if "response_format" in kw else None))
    assert _send(llm, response_format=JSON_FORMAT) == "OK"
    assert llm._send_json_format is False and llm._send_min_p is False, "both go: nothing said which"
    assert "response_format" not in llm._params(response_format=JSON_FORMAT) and "min_p" not in _eb(llm._params())
    assert any("only without" in n for n in llm.notices), llm.notices
    print("5. an unnamed refusal: both given up once the request works without them, and it is said")


# ---------- 6: a failure that is about something else ----------
def test_unrelated_failure_keeps_them():
    llm = _wire(_llm(min_p=0.1), _Server(lambda kw: "400 this model's maximum context length is 8192 tokens"))
    try:
        _send(llm, response_format=JSON_FORMAT)
    except Exception as e:
        assert "context length" in str(e)
    else:
        raise AssertionError("a request that fails either way must fail")
    assert llm._send_min_p and llm._send_json_format and not llm.notices, llm.notices
    llm = _wire(_llm(min_p=0.1), _Server(lambda kw: "401 invalid key", status=401))
    try:
        _send(llm)
    except Exception:
        pass
    assert len(llm.client.chat.completions.seen) == 1, "an auth failure is not retried"
    print("6. a failure about something else keeps both settings; an auth failure is not retried at all")


# ---------- 7: the tool loop ----------
def test_tool_loop():
    class _Msg:
        content, tool_calls = "done", None

    class _Resp:
        usage = None

        def __init__(self):
            self.choices = [type("C", (), {"message": _Msg()})()]

    class _Tools(_Server):
        def create(self, **kw):
            super().create(**kw)
            return _Resp()

    llm = _wire(_llm(OR, openrouter_provider=PRIVATE, min_p=0.1),
                _Tools(lambda kw: "400 min_p is not supported" if "min_p" in _eb(kw) else None))
    out = llm.complete_with_tools([{"role": "user", "content": "give JSON"}], [{"type": "function"}], lambda *a: "",
                                  response_format=JSON_FORMAT)
    fake = llm.client.chat.completions
    assert out == "done", out
    assert all("response_format" not in kw for kw in fake.seen), "JSON mode beside tools"
    assert all(_eb(kw).get("provider") == PRIVATE for kw in fake.seen)
    assert "min_p" not in _eb(fake.seen[-1]) and llm._send_min_p is False
    print("7. the memory tool's loop: no JSON mode, the provider block on every call, a refused Min-p dropped")


# ---------- 8: strict JSON ----------
class _Stub:
    def __init__(self, reply='{"a": 1}', **gen):
        self.gen, self.reply, self.calls = gen, reply, []

    def complete(self, messages, **kw):
        self.calls.append(kw)
        return self.reply


def test_json_mode():
    ask = [{"role": "user", "content": "Return ONLY a JSON object."}]
    assert json_overrides(_Stub(), ask) == {}
    assert json_overrides(_Stub(json_mode="false"), ask) == {}, "only a real true"
    assert json_overrides(_Stub(json_mode=True), [{"role": "user", "content": "Tell a story."}]) == {}, \
        "some providers require the prompt to ask for JSON"
    assert json_overrides(_Stub(json_mode=True), ask) == {"response_format": JSON_FORMAT}
    stub = _Stub(json_mode=True)
    obj, err = emit_json_ex(stub, "Reply with JSON.", "the payload")
    assert obj == {"a": 1} and stub.calls[0].get("response_format") == JSON_FORMAT, stub.calls
    off = _Stub()
    emit_json_ex(off, "Reply with JSON.", "the payload")
    assert "response_format" not in off.calls[0]
    fstub = _Stub('{"stakes": "none", "direction": "x"}', json_mode=True)
    fate._ask(fstub, [{"role": "system", "content": "Answer with JSON only."}])
    assert fstub.calls[0].get("response_format") == JSON_FORMAT, fstub.calls
    assert fstub.calls[0].get("max_tokens") == fate.FATE_TOKENS
    print("8. strict JSON only when switched on, only for a prompt asking for JSON; fate asks for it too")


# ---------- 9: embeddings ----------
class _Embeds:
    def __init__(self, base_url):
        self.base_url, self.seen = base_url, []
        self.embeddings = self

    def create(self, **kw):
        self.seen.append(kw)
        return type("R", (), {"data": [type("D", (), {"embedding": [1.0], "index": 0})() for _ in kw["input"]]})()


def test_embeddings():
    cfg = Config(profile=Profile(name="t", base_url=OR, model="m", api_key="k", context_tokens=32768),
                 generation={"openrouter_provider": PRIVATE}, memory={}, rpg={}, retrieval={}, raw={})
    store = core.lib.store(core.lib.saves.create("Embedding route", premise="A ferry town."))
    for base, want in ((OR, {"provider": PRIVATE}), ("http://localhost:11434/v1", None)):
        client = _Embeds(base)
        r = vector_mod.build_retriever(store, client, {"enabled": True, "embed_model": "e"}, cfg)
        r.index.embedder.embed(["a line"])
        assert client.seen[-1].get("extra_body") == want, (base, client.seen[-1])
        probe = _Embeds(base)
        assert vector_mod.probe_embedder(probe, {"embed_model": "e"}, cfg) == ""
        assert probe.seen[-1].get("extra_body") == want, "the check sends it the same way"
    print("9. semantic recall embeds with the provider block at OpenRouter, and without it elsewhere")


# ---------- 10: Settings ----------
def test_settings_api():
    c = TestClient(server.app)
    st = c.get("/api/settings").json()["generation"]
    assert st["openrouter_provider"] == {} and st["min_p"] is None and st["json_mode"] is False, st
    hosted = {"mode": "hosted", "hosted": {"model": "a/b", "base_url": OR}}

    def put(gen):
        return c.put("/api/settings", json={**hosted, "generation": gen})

    core._cfg.raw["generation"]["openrouter_provider"] = {"only": ["x"], "sort": "price", "zdr": True}
    r = put({"openrouter_provider": {"order": " deepinfra, together ,", "allow_fallbacks": False, "data_collection": "deny",
                                     "zdr": False, "require_parameters": True}, "min_p": "1.7", "json_mode": True})
    assert r.status_code == 200, r.text
    g = core._cfg.generation
    assert g["openrouter_provider"] == {"only": ["x"], "sort": "price", "order": ["deepinfra", "together"], "allow_fallbacks": False,
                                        "data_collection": "deny", "require_parameters": True}, g["openrouter_provider"]
    assert g["min_p"] == 1.0 and g["json_mode"] is True, g
    assert put({"openrouter_provider": {"order": "Deep Infra"}}).status_code == 400
    assert put({"openrouter_provider": {"order": "", "allow_fallbacks": False}}).status_code == 400
    assert core._cfg.generation["openrouter_provider"]["order"] == ["deepinfra", "together"], "a refused save changes nothing"
    before = dict(core._cfg.generation["openrouter_provider"])
    assert put({"min_p": "", "json_mode": "true"}).status_code == 200
    g = core._cfg.generation
    assert "min_p" not in g and "json_mode" not in g, "blank clears Min-p; only a real true turns JSON on"
    assert g.get("openrouter_provider") == before, "a save without the block (another provider on screen) keeps every choice"
    core._cfg.raw["generation"]["openrouter_provider"] = {"order": ["a"]}
    assert put({"openrouter_provider": {"order": "", "allow_fallbacks": True}}).status_code == 200
    assert "openrouter_provider" not in core._cfg.generation, "everything unchecked removes it"
    core._cfg.raw["generation"]["openrouter_provider"] = "zdr"
    assert put({"openrouter_provider": {"order": ""}}).status_code == 200
    assert core._cfg.generation.get("openrouter_provider") == "zdr", "a hand-written mistake is not quietly erased"
    assert c.get("/api/settings").json()["generation"]["openrouter_provider"] == {}
    print("10. Settings writes its part, keeps hand-written keys, refuses a bad name, and erases nothing quietly")


# ---------- 11: the health log ----------
def test_engine_logs_a_refusal():
    from coderain.engine import Engine
    slug = core.lib.saves.create("Hosted notice", premise="A ferry town.")
    store = core.lib.store(slug)
    eng = Engine(core._cfg, store)
    eng.llm.on_notice("min_p is off for this model: 400")
    health = store.health()
    assert any("min_p is off" in str(h.get("reason")) for h in health), health
    print("11. a refused setting is written to the story's health log")


try:
    for fn in (test_min_p, test_provider_block_only_for_openrouter, test_provider_is_never_dropped, test_named_refusal,
               test_unnamed_refusal_that_works_bare, test_unrelated_failure_keeps_them, test_tool_loop, test_json_mode,
               test_embeddings, test_settings_api, test_engine_logs_a_refusal):
        fn()
finally:
    shutil.rmtree(WORK, ignore_errors=True)
print("\nHOSTED SETTINGS TESTS PASSED")
