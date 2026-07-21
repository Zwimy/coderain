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
    _reload({"active_profile": "local",
             "profiles": {"local": {"base_url": "http://127.0.0.1:1/v1",
                                    "model": "qwen3:4b",
                                    "api_key_env": "OLLAMA_API_KEY"}}})
    r = client.get("/api/ready").json()
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
    r = client.get("/api/ready").json()          # must not 500 / not exit
    assert r["ok"] is False, r
    assert r["reason"] in ("no_model", "no_key", "no_ollama"), r
    assert client.get("/api/saves").status_code == 200, "server unusable"
    print(f"incomplete profile -> fell back safely (reason {r['reason']})")


for fn in (test_local_without_ollama_is_not_ready,
           test_hosted_without_key_is_not_ready,
           test_hosted_with_key_and_model_is_ready,
           test_incomplete_profile_falls_back_instead_of_killing_the_server):
    fn()
shutil.rmtree(HOME, ignore_errors=True)
print("\nREADY PROBE TESTS PASSED")
