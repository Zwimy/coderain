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


def _serve(bodies):
    """Stub the probe: answer per URL from `bodies`, remember every URL asked, refuse anything else."""
    asked = []

    def fake_get(url, **k):
        asked.append(url)
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


for fn in (test_local_without_ollama_is_not_ready,
           test_hosted_without_key_is_not_ready,
           test_hosted_with_key_and_model_is_ready,
           test_incomplete_profile_falls_back_instead_of_killing_the_server,
           test_embedding_models_are_never_the_storyteller,
           test_the_profiles_own_address_is_probed):
    fn()
shutil.rmtree(HOME, ignore_errors=True)
print("\nREADY PROBE TESTS PASSED")
