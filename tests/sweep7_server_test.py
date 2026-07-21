"""Sweep-7 server-robustness regressions (2026-07-21).

D5  put_settings mutated the LIVE config before validating, so a rejected save
    (400) left the running process reporting values that were never written to
    disk and silently reverted on restart.
D8  save_yaml/write_env wrote in place (a torn write bricked startup) and
    load_config raised SystemExit on a malformed file - fatal inside a request
    handler, killing the whole server instead of returning an error.
W7  impersonate/assist handed the browser a bare 500 + a server traceback when
    the model was unreachable, while the SSE routes handled it gracefully.
W9  SSE errors echoed str(e), which can carry absolute filesystem paths.
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
HOME = tempfile.mkdtemp(prefix="coderain-srv-")
os.environ["CODERAIN_HOME"] = HOME

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
from coderain import config as cfg_mod  # noqa: E402

client = TestClient(server.app)


def test_rejected_settings_save_does_not_half_apply():
    before = server._cfg.generation.get("temperature", 0.9)
    r = client.put("/api/settings", json={
        "mode": "hosted",
        "generation": {"temperature": 1.5},
        "hosted": {"model": "", "base_url": ""},      # invalid -> 400
    })
    assert r.status_code == 400, r.status_code
    after = server._cfg.generation.get("temperature", 0.9)
    assert after == before, f"live config half-applied: {before} -> {after}"
    assert client.get("/api/settings").json()["generation"]["temperature"] == before
    print("D5 a rejected settings save leaves the live config untouched")


def test_config_writes_are_atomic_and_malformed_config_is_not_fatal():
    p = Path(HOME) / "config.yaml"
    cfg_mod.save_yaml({"active_profile": "local",
                       "profiles": {"local": {"base_url": "x", "model": "m"}}}, p)
    assert not list(p.parent.glob("config.yaml.*.tmp")), "temp file left behind"

    p.write_text("]]] not : valid : yaml [[[", encoding="utf-8")
    c = cfg_mod.load_config(p)          # must NOT raise SystemExit
    assert c.profile.model, "no usable fallback profile"

    p.write_text("active_profile: ghost\nprofiles: {}\n", encoding="utf-8")
    c = cfg_mod.load_config(p)          # unknown active_profile, no profiles
    assert c.profile.model, "unknown active_profile was fatal"
    print("D8 atomic writes; a malformed config falls back instead of exiting")


def test_model_errors_are_classified_and_sanitized():
    kind = server._model_error_kind
    assert kind(ConnectionError("Connection error.")) == "connection"
    assert kind(Exception("401 Unauthorized: invalid api key")) == "auth"
    assert kind(TimeoutError("request timed out")) == "timeout"
    assert kind(Exception("429 rate limit exceeded")) == "rate_limit"
    assert kind(Exception("maximum context length is 4096 tokens")) == "context"

    leaky = FileNotFoundError(r"C:\Users\Someone\secret\path\model.gguf")
    msg = server._model_error_text(leaky)
    assert "C:\\Users" not in msg and "secret" not in msg, msg
    assert msg, "empty error text"
    print("W7/W9 model errors classified; raw paths never surface")


def test_impersonate_returns_502_not_500_when_model_is_down():
    slug = server.lib.saves.create("Err Run", premise="A premise.")

    class Boom:
        def impersonate(self):
            raise ConnectionError("Connection error.")
    server._engines[slug] = Boom()
    r = client.post(f"/api/saves/{slug}/impersonate")
    assert r.status_code == 502, f"expected 502, got {r.status_code}"
    assert "Ollama" in r.json()["detail"] or "base URL" in r.json()["detail"]
    server._engines.pop(slug, None)
    print("W7 impersonate -> 502 with an actionable message")


for fn in (test_rejected_settings_save_does_not_half_apply,
           test_config_writes_are_atomic_and_malformed_config_is_not_fatal,
           test_model_errors_are_classified_and_sanitized,
           test_impersonate_returns_502_not_500_when_model_is_down):
    fn()
shutil.rmtree(HOME, ignore_errors=True)
print("\nSWEEP 7 SERVER TESTS PASSED")
