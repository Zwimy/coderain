"""First-run readiness probe (2026-07-21).

UX1: the app booted straight into an empty library that promised success, then
failed on the very first turn with an unreadable message. Nothing told a new
user that a model was needed at all. /api/ready is the gate the first-run
chooser hangs off. It must never spend tokens and never wrongly report ready.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
HOME = tempfile.mkdtemp(prefix="coderain-ready-")
os.environ["CODERAIN_HOME"] = HOME

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402

client = TestClient(server.app)


def _reload(raw):
    """Point the running server at a hand-built config."""
    from coderain import config as cfg_mod
    cfg_mod.save_yaml(raw, Path(HOME) / "config.yaml")
    server._reload_config()


def test_local_without_ollama_is_not_ready():
    # ready() probes the FIXED OLLAMA_TAGS url, not the profile's base_url, so a
    # dead base_url here proved nothing: on a machine where Ollama happens to be
    # running this asserted against the real daemon and failed. Stub the probe so
    # the case ("Ollama is not up") is actually the case under test.
    _reload({"active_profile": "local",
             "profiles": {"local": {"base_url": "http://127.0.0.1:1/v1",
                                    "model": "qwen3:4b",
                                    "api_key_env": "OLLAMA_API_KEY"}}})
    real_get = server.httpx.get

    def dead_get(*a, **k):
        raise server.httpx.ConnectError("connection refused")

    server.httpx.get = dead_get
    try:
        r = client.get("/api/ready").json()
    finally:
        server.httpx.get = real_get
    assert r["ok"] is False, r
    assert r["reason"] == "no_ollama", r
    assert r["detail"], "no human-readable detail"
    print("local + no Ollama -> not ready, reason no_ollama")


def test_hosted_without_key_is_not_ready():
    _reload({"active_profile": "hosted",
             "profiles": {"hosted": {"base_url": "https://api.example.com/v1",
                                     "model": "some-model",
                                     "api_key_env": server.HOSTED_KEY_ENV}}})
    os.environ.pop(server.HOSTED_KEY_ENV, None)
    env = Path(HOME) / ".env"
    if env.exists():
        env.unlink()
    r = client.get("/api/ready").json()
    assert r["ok"] is False and r["reason"] == "no_key", r
    print("hosted + no key -> not ready, reason no_key")


def test_hosted_with_key_and_model_is_ready():
    from coderain import config as cfg_mod
    cfg_mod.write_env({server.HOSTED_KEY_ENV: "sk-test-not-a-real-key"})
    _reload({"active_profile": "hosted",
             "profiles": {"hosted": {"base_url": "https://api.example.com/v1",
                                     "model": "some-model",
                                     "api_key_env": server.HOSTED_KEY_ENV}}})
    r = client.get("/api/ready").json()
    assert r["ok"] is True, r
    assert r["mode"] == "hosted" and r["model"] == "some-model", r
    print("hosted + key + model -> ready (no tokens spent)")


def test_incomplete_profile_falls_back_instead_of_killing_the_server():
    """A hand-edited config with an incomplete profile used to raise SystemExit
    out of build_profile — fatal at boot AND inside request handlers. It must now
    degrade to the shipped defaults and still answer honestly."""
    _reload({"active_profile": "hosted",
             "profiles": {"hosted": {"base_url": "", "model": "",
                                     "api_key_env": server.HOSTED_KEY_ENV}}})
    # The fallback lands on the LOCAL default profile, so this probes Ollama too:
    # stub it out or a machine with Ollama up reports ready and hides the case.
    real_get = server.httpx.get

    def dead_get(*a, **k):
        raise server.httpx.ConnectError("connection refused")

    server.httpx.get = dead_get
    try:
        r = client.get("/api/ready").json()       # must not 500 / not exit
    finally:
        server.httpx.get = real_get
    assert r["ok"] is False, r
    assert r["reason"] in ("no_model", "no_key", "no_ollama"), r
    assert client.get("/api/saves").status_code == 200, "server unusable"
    print(f"incomplete profile -> fell back safely (reason {r['reason']})")


class _Resp:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self._body


TIMEOUTS = []                                     # the timeout each stubbed probe was given


def _serve(bodies):
    """Stub the probe: answer per URL from `bodies`, remember every URL asked, refuse anything else."""
    asked = []

    def fake_get(url, **k):
        asked.append(url)
        TIMEOUTS.append((url, k.get("timeout")))
        if url not in bodies:
            raise server.httpx.ConnectError(f"nothing listens at {url}")
        return _Resp(bodies[url])

    real = server.httpx.get
    server.httpx.get = fake_get
    return asked, lambda: setattr(server.httpx, "get", real)


def _local(base_url, model="qwen3:4b"):
    _reload({"active_profile": "local",
             "profiles": {"local": {"base_url": base_url, "model": model, "api_key_env": "OLLAMA_API_KEY"}}})


OLLAMA_URL = "http://localhost:11434/api/tags"


def test_embedding_models_are_never_the_storyteller():
    """The first-run picker listed nomic-embed-text beside the chat models. (When nothing names a model the probe also used
    the first name in the list, which could be an embedding model: it takes the first chat model now.)"""
    from srv.settings import is_embedding
    for n in ("nomic-embed-text:latest", "mxbai-embed-large", "bge-m3:567m", "all-minilm:l6", "text-embedding-3-small",
              "snowflake-arctic-embed2", "hf.co/x/Some-Embedding-GGUF:Q8_0"):
        assert is_embedding(n), n
    for n in ("llama3.1:8b", "gemma3:4b", "qwen3:4b", "deepseek-r1:8b", "hf.co/mradermacher/Qwen3.5-9B-heretic-GGUF:Q4_K_M",
              "", None):
        assert not is_embedding(n), n
    _local("http://localhost:11434/v1", model="llama3.1:8b")
    asked, undo = _serve({OLLAMA_URL: {"models": [{"name": "nomic-embed-text:latest", "size": 3e8},
                                                  {"name": "llama3.1:8b", "size": 4.9e9}]}})
    try:
        r = client.get("/api/ready").json()
        listed = client.get("/api/models/local").json()
    finally:
        undo()
    assert r["ok"] is True and r["model"] == "llama3.1:8b", r
    assert {m["name"]: m["embedding"] for m in listed["installed"]} == {"nomic-embed-text:latest": True, "llama3.1:8b": False}
    # nothing names a model (the config loader normally fills one in, so set it empty directly): the probe's own default
    # must be the first CHAT model, not the first name in the list
    server.core._cfg.raw["profiles"]["local"]["model"] = ""
    asked, undo = _serve({OLLAMA_URL: {"models": [{"name": "nomic-embed-text:latest", "size": 3e8},
                                                  {"name": "llama3.1:8b", "size": 4.9e9}]}})
    try:
        unnamed = client.get("/api/ready").json()
    finally:
        undo()
    assert unnamed["ok"] is True and unnamed["model"] == "llama3.1:8b", ("an embedding model became the default", unnamed)
    asked, undo = _serve({OLLAMA_URL: {"models": [{"name": "nomic-embed-text:latest", "size": 3e8}]}})
    try:
        only = client.get("/api/ready").json()
    finally:
        undo()
    assert only["ok"] is False and only["reason"] == "no_chat_models" and "embedding" in only["detail"], only
    print("an embedding model is flagged, never the default, and a server with only embeddings is not ready")


def test_the_profiles_own_address_is_probed():
    """The probe and the model list asked a fixed http://localhost:11434, so a user on LM Studio, llama.cpp or an Ollama
    on another machine was told Ollama was not running, however well their server worked."""
    lm = "http://127.0.0.1:1234/v1/models"
    _local("http://127.0.0.1:1234/v1", model="qwen2.5-7b-instruct")
    asked, undo = _serve({lm: {"data": [{"id": "qwen2.5-7b-instruct"}, {"id": "text-embedding-nomic-embed-text-v1.5"}]}})
    try:
        r = client.get("/api/ready").json()
        listed = client.get("/api/models/local").json()
    finally:
        undo()
    assert r["ok"] is True and r["model"] == "qwen2.5-7b-instruct" and r["server"] == "Your model server", r
    assert asked and set(asked) == {lm}, ("an OpenAI-compatible server was asked something else", asked)
    assert listed["server"] == "Your model server" and not listed["error"], listed
    assert [m["name"] for m in listed["installed"] if not m["embedding"]] == ["qwen2.5-7b-instruct"]
    # an Ollama on another machine: still Ollama's own API, at that host
    _local("http://192.168.1.5:11434/v1", model="gemma3:4b")
    remote = "http://192.168.1.5:11434/api/tags"
    asked, undo = _serve({remote: {"models": [{"name": "gemma3:4b", "size": 3.3e9}]}})
    try:
        r = client.get("/api/ready").json()
    finally:
        undo()
    assert r["ok"] is True and r["server"] == "Ollama" and asked == [remote], (r, asked)
    # the default profile still asks the local Ollama
    _local("http://localhost:11434/v1", model="gemma3:4b")
    asked, undo = _serve({OLLAMA_URL: {"models": [{"name": "gemma3:4b", "size": 3.3e9}]}})
    try:
        client.get("/api/ready")
    finally:
        undo()
    assert asked == [OLLAMA_URL], asked
    # a closed port takes about 2.25 s per address to refuse on Windows and "localhost" is tried as ::1 and then 127.0.0.1, so
    # a server on this machine gets one second to connect and one elsewhere keeps three
    got = {u: t for u, t in TIMEOUTS}
    assert got[OLLAMA_URL].connect == 1.0 and got[OLLAMA_URL].read == 3.0, got
    assert got["http://192.168.1.5:11434/api/tags"].connect == 3.0, got
    assert got["http://127.0.0.1:1234/v1/models"].connect == 1.0, got
    # an unreachable server names itself in the message instead of blaming Ollama
    _local("http://127.0.0.1:1234/v1")
    asked, undo = _serve({})
    try:
        r = client.get("/api/ready").json()
        listed = client.get("/api/models/local").json()
    finally:
        undo()
    assert r["ok"] is False and "Your model server" in r["detail"] and "Ollama" not in r["detail"], r
    assert "Your model server" in listed["error"], listed
    print("the local profile's own address is asked; an unreachable server names itself, not Ollama")


def _hosted(base, model="some-model"):
    _reload({"active_profile": "hosted",
             "profiles": {"hosted": {"base_url": base, "model": model, "api_key_env": server.HOSTED_KEY_ENV}}})


def test_a_keyless_server_on_this_network_passes_the_gate():
    """LM Studio and llama.cpp take no key. Set up as an OpenAI-compatible profile with a loopback or LAN address and no key,
    the gate said "No API key saved yet" and held the user at the first-run screen until they typed a made-up key. A key is
    still demanded for anything that is not on this machine or network, and the match is on the whole host name."""
    from coderain import config as cfg_mod
    from coderain.llm import LLM, is_lan
    os.environ.pop(server.HOSTED_KEY_ENV, None)
    env = Path(HOME) / ".env"
    if env.exists():
        env.unlink()
    here = ("http://127.0.0.1:1234/v1", "http://localhost:1234/v1", "http://192.168.1.20:8080/v1", "http://10.0.0.7:5000/v1",
            "http://172.16.4.2/v1", "http://172.31.255.1/v1", "http://[::1]:1234/v1", "http://gpu-box.local:1234/v1",
            "localhost:1234/v1", "http://169.254.10.1/v1", "http://LOCALHOST./v1")
    elsewhere = ("https://api.example.com/v1", "https://openrouter.ai/api/v1", "https://localhost.example.com/v1",
                 "http://192.168.1.20.example.com/v1", "http://8.8.8.8/v1", "http://172.32.0.1/v1", "http://11.0.0.1/v1",
                 "http://notlocal/v1", "", "http://")
    for base in here:
        assert is_lan(base), base
        _hosted(base)
        r = client.get("/api/ready").json()
        assert r["ok"] is True and r["mode"] == "hosted" and r.get("keyless") is True, (base, r)
    for base in elsewhere:
        assert not is_lan(base), base
        _hosted(base or "https://x.invalid/v1")
        if base:
            r = client.get("/api/ready").json()
            assert r["ok"] is False and r["reason"] == "no_key", (base, r)
    # with a key saved nothing changes, and it is not reported as keyless
    cfg_mod.write_env({server.HOSTED_KEY_ENV: "sk-test-not-a-real-key"})
    _hosted("http://127.0.0.1:1234/v1")
    r = client.get("/api/ready").json()
    assert r["ok"] is True and "keyless" not in r, r
    # and the client really can be built with no key at all (it sends a placeholder)
    os.environ.pop(server.HOSTED_KEY_ENV, None)
    prof = cfg_mod.build_profile({"profiles": {"hosted": {"base_url": "http://127.0.0.1:1234/v1", "model": "m",
                                                          "api_key_env": server.HOSTED_KEY_ENV}}}, "hosted")
    assert prof.api_key == "not-needed", prof
    assert LLM(prof, {}).client.api_key == "not-needed"
    print("a keyless server on this machine or network passes the gate; a provider still needs its key")


def test_the_connection_test_asks_the_model_list_and_never_echoes_the_key():
    """A new user with a hosted key could not tell a wrong key from a down server until the first turn failed with an unreadable
    message. The test asks GET <base>/models (no tokens), keeps /api/ready off the network, and never sends the key back."""
    import json as _json
    from coderain import config as cfg_mod
    TYPED, SAVED = "sk-typed-secret-123", "sk-saved-secret-456"
    base = "https://api.example.com/v1"
    cfg_mod.write_env({server.HOSTED_KEY_ENV: SAVED})
    _hosted(base)
    calls = []

    class Resp:
        def __init__(self, code, body=None):
            self.status_code, self._b = code, body

        def json(self):
            if self._b is None:
                raise ValueError("not json")
            return self._b

    def run(answer, body=None):
        calls.clear()

        def fake(url, **k):
            calls.append((url, k))
            if isinstance(answer, Exception):
                raise answer
            return answer
        real = server.httpx.get
        server.httpx.get = fake
        try:
            res = client.post("/api/connection/test", json=body if body is not None else {})
        finally:
            server.httpx.get = real
        assert res.status_code == 200, res.text
        assert TYPED not in res.text and SAVED not in res.text, ("the key came back", res.text)
        return res.json()

    listing = Resp(200, {"data": [{"id": "some-model"}, {"id": "other"}]})
    r = run(listing)
    assert r["ok"] is True and r["reason"] == "connected" and r["model_listed"] is True, r
    assert calls[0][0] == base + "/models", calls
    assert calls[0][1]["headers"] == {"Authorization": f"Bearer {SAVED}"}, ("the saved key was not used", calls)
    r = run(listing, {"api_key": TYPED, "model": "some-model"})
    assert calls[0][1]["headers"] == {"Authorization": f"Bearer {TYPED}"}, ("a typed key must win over the saved one", calls)
    r = run(listing, {"model": "no-such-model"})
    assert r["ok"] is True and r["reason"] == "model_not_listed" and r["model_listed"] is False, r
    r = run(Resp(200, {"data": []}))
    assert r["ok"] is True and r["model_listed"] is None, r
    r = run(Resp(200))                                     # an answer that is not JSON still means the server answered
    assert r["ok"] is True, r
    r = run(listing, {"base_url": "https://other.example.org/v1/"})
    assert calls[0][0] == "https://other.example.org/v1/models", ("a typed base URL was not used", calls)
    for code, reason in ((401, "rejected"), (403, "rejected"), (404, "no_model_list"), (302, "redirect"), (500, "error"),
                         (429, "error")):
        r = run(Resp(code))
        assert r["ok"] is False and r["reason"] == reason, (code, r)
    r = run(server.httpx.ConnectError("refused"))
    assert r["ok"] is False and r["reason"] == "unreachable" and "api.example.com" in r["detail"], r
    r = run(server.httpx.ReadTimeout("slow"))
    assert r["ok"] is False and r["reason"] == "unreachable", r
    # no key and a public host: nothing is sent at all
    os.environ.pop(server.HOSTED_KEY_ENV, None)
    (Path(HOME) / ".env").unlink()
    r = run(listing)
    assert r["ok"] is False and r["reason"] == "no_key" and not calls, (r, calls)
    # a server on this network needs no key: the request goes out with no Authorization header
    r = run(listing, {"base_url": "http://192.168.1.20:1234/v1"})
    assert r["ok"] is True and calls[0][1]["headers"] == {}, (r, calls)
    r = run(listing, {"base_url": "  ", "model": "  "})   # blank fields fall back to the saved profile: a public host, no key
    assert r["ok"] is False and r["reason"] == "no_key" and not calls, ("blank fields hid the saved base URL", r, calls)
    cfg_mod.write_env({server.HOSTED_KEY_ENV: SAVED})
    r = run(listing, {"base_url": "  ", "model": "  "})
    assert r["ok"] is True and calls[0][0] == base + "/models", ("blank fields did not fall back to the saved base URL", r, calls)
    assert r["reason"] == "connected" and r["model_listed"] is True, ("the saved model was not used", r)
    os.environ.pop(server.HOSTED_KEY_ENV, None)
    (Path(HOME) / ".env").unlink()
    _reload({"active_profile": "hosted", "profiles": {"hosted": {"base_url": "", "model": "m",
                                                                  "api_key_env": server.HOSTED_KEY_ENV}}})
    r = run(listing, {"api_key": TYPED})
    assert r["ok"] is False and r["reason"] in ("no_base", "no_key", "unreachable") and not calls, (r, calls)
    # /api/ready never asks the provider, with or without a key
    cfg_mod.write_env({server.HOSTED_KEY_ENV: SAVED})
    _hosted(base)
    calls.clear()
    real = server.httpx.get
    server.httpx.get = lambda url, **k: calls.append(url) or Resp(200)
    try:
        ready_now = client.get("/api/ready").json()
    finally:
        server.httpx.get = real
    assert ready_now["ok"] is True and not calls, ("readiness reached the provider", calls)
    print("the connection test reads the model list, prefers the typed key, never echoes it, and /api/ready stays off the network")


for fn in (test_local_without_ollama_is_not_ready,
           test_hosted_without_key_is_not_ready,
           test_hosted_with_key_and_model_is_ready,
           test_incomplete_profile_falls_back_instead_of_killing_the_server,
           test_embedding_models_are_never_the_storyteller,
           test_the_profiles_own_address_is_probed,
           test_a_keyless_server_on_this_network_passes_the_gate,
           test_the_connection_test_asks_the_model_list_and_never_echoes_the_key):
    fn()
shutil.rmtree(HOME, ignore_errors=True)
print("\nREADY PROBE TESTS PASSED")
