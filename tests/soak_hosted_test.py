"""The play soak on a hosted free model (D-068): the limits are enforced by code, not by promise.

`python -m soak play --provider openrouter` lets the soak use a hosted `:free` OpenRouter model. A key given for a free test must not be
able to spend, must not leak, and must not hammer a free pool, so each of these is a way it could quietly fail:

 1) a model that does not end in `:free` is refused (and `--allow-paid` is the only way round it), as is no model at all
 2) the key is read from the environment by NAME: with it unset the run refuses and names the variable, and a refusal message, the run's
    summary and its output never contain the key's value (a canary stands in for it)
 3) the Pacer spaces requests by the interval, counts every attempt and says how many are left (a fake clock, no real waiting)
 4) the SDK patch retries a busy pool (429), a provider fault (5xx) and a dropped connection with the waits, and does NOT retry a bad
    request, a bad key or a missing model (400 to 404); it gives up after the last wait and raises; every attempt counts; undo puts the SDK back
 5) the local config is byte for byte what it was (the default path of every earlier run), and the hosted config names the variable and
    the OpenRouter address, never a key and never localhost
 6) from the command line: a non-free model, a missing key and a missing model are refused before anything runs, and an offline hosted run
    with the budget one request short of a turn plays nothing and says why, with exactly a turn's worth it plays them all
 7) a request that fails for good (retries spent, a bad key, a daily cap) marks the pacer failed with a few words and no provider text; a
    daily cap is not retried; a request that worked after retries leaves it clean; and a run whose provider fails stops AT that turn and does
    not record it (an error message written into the story as narration would corrupt every row after it)
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from openai.resources.chat.completions import Completions    # noqa: E402
from soak import hosted                                         # noqa: E402
from soak.play import _config                                   # noqa: E402

CANARY = "sk-or-v1-CANARY0000000000000000000000000000000000"


def refused(fn, *a, **k):
    try:
        fn(*a, **k)
    except SystemExit as e:
        return str(e)
    raise AssertionError("expected a refusal")


def test_model_guard():
    assert "':free'" in refused(hosted.check_model, "openai/gpt-4o")
    assert "':free'" in refused(hosted.check_model, "google/gemma-4-31b-it")
    assert "':free'" in refused(hosted.check_model, "anything:freebie")          # only the exact suffix counts
    assert "needs --model" in refused(hosted.check_model, None)
    assert "needs --model" in refused(hosted.check_model, "")
    hosted.check_model("google/gemma-4-31b-it:free")
    hosted.check_model("openai/gpt-4o", allow_paid=True)
    print("1. a model that does not end in :free is refused, allow-paid is the only way round, no model is refused")


def test_key_by_name():
    saved = os.environ.pop(hosted.KEY_ENV, None)
    try:
        msg = refused(hosted.require_key)
        assert hosted.KEY_ENV in msg and "not set" in msg
        os.environ[hosted.KEY_ENV] = "   "
        assert "not set" in refused(hosted.require_key), "a blank key was accepted"
        os.environ[hosted.KEY_ENV] = CANARY
        hosted.require_key()
        for text in (refused(hosted.check_model, "openai/gpt-4o"), refused(hosted.check_model, None)):
            assert CANARY not in text
    finally:
        os.environ.pop(hosted.KEY_ENV, None)
        if saved is not None:
            os.environ[hosted.KEY_ENV] = saved
    print("2. the key is read by name, a blank or missing one is refused naming the variable, and no message holds its value")


class Clock:
    def __init__(self):
        self.t = 100.0
        self.slept = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(round(s, 3))
        self.t += s


def test_pacer():
    c = Clock()
    p = hosted.Pacer(interval=3.2, max_requests=5, clock=c.now, sleep=c.sleep)
    p.before_request()
    assert c.slept == [] and p.count == 1 and p.left() == 4, "the first request waited"
    p.before_request()
    assert c.slept == [3.2], c.slept                                  # straight after: waits the whole interval
    c.t += 1.0
    p.before_request()
    assert c.slept == [3.2, 2.2], c.slept                             # 1 s have passed: waits the rest
    c.t += 10.0
    p.before_request()
    assert c.slept == [3.2, 2.2], "waited although the interval had passed"
    assert p.count == 4 and p.left() == 1
    p.before_request()
    assert p.left() == 0
    print("3. the pacer waits the rest of the interval, never more, counts every request and says how many are left")


class Busy(Exception):
    def __init__(self, status):
        super().__init__(f"status {status}")
        self.status_code = status


class APIConnectionError(Exception):
    """Named as the SDK's is: a dropped connection carries no status."""


def run_with(script, waits=(1, 2, 3), pacer=None):
    """Install the patch over a fake SDK call that follows `script` (exceptions are raised, anything else returned)."""
    saved = Completions.create
    calls = []

    def fake(self, *a, **kw):
        step = script[min(len(calls), len(script) - 1)]
        calls.append(1)
        if isinstance(step, BaseException):
            raise step
        return step
    Completions.create = fake
    c = Clock()
    pacer = pacer or hosted.Pacer(interval=0.0, max_requests=100, clock=c.now, sleep=c.sleep)
    undo = hosted.install(pacer, waits=waits, sleep=c.sleep)
    try:
        try:
            result = ("returned", Completions.create(None))
        except Exception as e:  # noqa: BLE001
            result = ("raised", e)
    finally:
        undo()
        restored = Completions.create is fake
        Completions.create = saved
    return result, len(calls), pacer.count, [s for s in c.slept if s], restored


def test_retry():
    res, calls, counted, slept, restored = run_with([Busy(429), Busy(429), "ok"])
    assert res == ("returned", "ok") and calls == 3 and counted == 3 and slept == [1, 2], (res, calls, counted, slept)
    assert restored, "undo did not put the SDK back"
    res, calls, counted, slept, _ = run_with([Busy(503), "ok"])
    assert res == ("returned", "ok") and calls == 2 and slept == [1], "a provider fault was not retried"
    res, calls, counted, slept, _ = run_with([APIConnectionError("reset"), "ok"])
    assert res == ("returned", "ok") and calls == 2, "a dropped connection was not retried"
    for status in (400, 401, 402, 403, 404):
        res, calls, counted, slept, _ = run_with([Busy(status), "ok"])
        assert res[0] == "raised" and calls == 1 and counted == 1 and slept == [], (status, res, calls)
    res, calls, counted, slept, _ = run_with([ValueError("a bug of ours"), "ok"])
    assert res[0] == "raised" and calls == 1, "an error that is not the provider's was retried"
    res, calls, counted, slept, _ = run_with([Busy(429)])                    # always busy
    assert res[0] == "raised" and isinstance(res[1], Busy), res
    assert calls == 4 and counted == 4 and slept == [1, 2, 3], (calls, counted, slept)       # three waits, four attempts, then it gives up
    # the default patience: a shared free pool was measured refusing every request for more than four minutes (Particle-1, and the first
    # version of the waits, 255 s in all, ended a real run at turn 34)
    assert sum(hosted.RETRY_WAITS) >= 600, f"the retry patience is only {sum(hosted.RETRY_WAITS)} s"
    print("4. busy, fault and dropped connection are retried with the waits; 400 to 404 and our own errors are not; it gives up and raises; undo restores")


def test_config():
    local = _config("m", 4, 5000, "off", False)
    assert local.startswith("active_profile: local\nprofiles:\n  local:\n    base_url: http://localhost:11434/v1\n    model: m\n"
                            "    api_key_env: OLLAMA_API_KEY\n    context_tokens: 16384\ngeneration:\n"), local[:200]
    assert local == _config("m", 4, 5000, "off", False, provider="ollama")
    cloud = _config("google/gemma-4-31b-it:free", 4, 5000, "card", False, provider="openrouter")
    assert "base_url: https://openrouter.ai/api/v1" in cloud and "api_key_env: OPENROUTER_API_KEY" in cloud, cloud[:250]
    assert "model: google/gemma-4-31b-it:free" in cloud and "active_profile: hosted" in cloud
    assert "localhost" not in cloud and "OLLAMA" not in cloud, "the hosted config still points at the local server"
    assert "model: google/gemma-4-31b-it:free\n" in cloud.split("canon:")[1], "the canon reader is not the hosted model"
    assert cloud.count("generation:") == 1 and "short_term_turns: 4" in cloud
    print("5. the local config is unchanged byte for byte; the hosted one names the variable and OpenRouter, never a key or localhost")


def cli(*args, key=CANARY, cwd=ROOT):
    env = dict(os.environ)
    env.pop(hosted.KEY_ENV, None)
    if key is not None:
        env[hosted.KEY_ENV] = key
    env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run([sys.executable, "-m", "soak", "play", *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=env, cwd=cwd, timeout=300)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def test_command_line():
    out = Path(tempfile.mkdtemp(prefix="cr-hosted-"))
    code, text = cli("--out", str(out / "a"), "--provider", "openrouter", "--model", "openai/gpt-4o", "--turns", "1")
    assert code != 0 and "not a ':free' model" in text and CANARY not in text, (code, text[-300:])
    code, text = cli("--out", str(out / "b"), "--provider", "openrouter", "--model", "x/y:free", "--turns", "1", key=None)
    assert code != 0 and "OPENROUTER_API_KEY" in text and "not set" in text, (code, text[-300:])
    code, text = cli("--out", str(out / "c"), "--provider", "openrouter", "--turns", "1")
    assert code != 0 and "needs --model" in text and CANARY not in text, (code, text[-300:])
    assert not (out / "a" / "turns.jsonl").exists() and not (out / "b" / "turns.jsonl").exists(), "a refused run still wrote rows"
    # an offline hosted run (stub writer, so no request is made): the budget is checked before each turn
    code, text = cli("--out", str(out / "short"), "--stub", "--provider", "openrouter", "--model", "x/y:free",
                     "--turns", str(6), "--max-requests", str(hosted.MIN_TURN_REQUESTS - 1))
    assert code == 0, text[-300:]
    s = json.loads((out / "short" / "summary.json").read_text(encoding="utf-8"))
    assert s["turns"] == 0 and s["stopped"] == "request budget spent after 0 turns" and s["requests"] == 0 and s["provider"] == "openrouter", s
    code, text = cli("--out", str(out / "enough"), "--stub", "--provider", "openrouter", "--model", "x/y:free",
                     "--turns", str(6), "--max-requests", str(hosted.MIN_TURN_REQUESTS))
    assert code == 0, text[-300:]
    s = json.loads((out / "enough" / "summary.json").read_text(encoding="utf-8"))
    assert s["turns"] == 6 and s["stopped"] is None and s["provider"] == "openrouter", s
    for path in out.rglob("*"):
        if path.is_file():
            assert CANARY not in path.read_text(encoding="utf-8", errors="replace"), f"the key reached {path}"
    assert CANARY not in text
    code, text = cli("--out", str(out / "local"), "--stub", "--turns", "3")
    s = json.loads((out / "local" / "summary.json").read_text(encoding="utf-8"))
    assert code == 0 and s["provider"] == "ollama" and s["requests"] is None and s["stopped"] is None, s
    print("6. from the command line: a non-free model, no key and no model are refused before anything runs; the budget is checked before each turn; "
          "the key is in no output")


class Capped(Exception):
    def __init__(self):
        super().__init__("rate limit")
        self.status_code = 429
        self.body = {"message": "Rate limit exceeded: free-models-per-day. Add credits to unlock more"}


def test_failed_for_good():
    p = hosted.Pacer(interval=0.0, max_requests=100)
    res, calls, counted, slept, _ = run_with([Busy(429)], pacer=p)                              # busy through every retry
    assert res[0] == "raised" and p.failed and p.last_error == "status 429", (p.failed, p.last_error)
    p = hosted.Pacer(interval=0.0, max_requests=100)
    res, calls, counted, slept, _ = run_with([Capped(), "ok"], pacer=p)                         # a daily cap: one try, no waiting
    assert res[0] == "raised" and calls == 1 and slept == [] and p.failed and p.last_error == "status 429", (res, calls, slept)
    p = hosted.Pacer(interval=0.0, max_requests=100)
    res, calls, counted, slept, _ = run_with([Busy(401), "ok"], pacer=p)
    assert p.failed and p.last_error == "status 401"
    p = hosted.Pacer(interval=0.0, max_requests=100)
    res, calls, counted, slept, _ = run_with([ValueError("sk-or-v1-NOT-A-KEY in a message"), "ok"], pacer=p)
    assert p.failed and p.last_error == "ValueError" and "sk-or" not in p.last_error, "the exception's own text must not be kept"
    p = hosted.Pacer(interval=0.0, max_requests=100)
    res, calls, counted, slept, _ = run_with([Busy(429), Busy(503), "ok"], pacer=p)           # worked after retries: clean
    assert res == ("returned", "ok") and not p.failed and p.last_error is None
    p = hosted.Pacer(interval=0.0, max_requests=100)
    assert not p.failed and p.last_error is None
    print("7a. a request that fails for good marks the pacer failed with the status or the exception's name only; a daily cap is one try")


DRIVER = """
import os, sys
from soak import hosted
import soak.play as sp
MODE = os.environ["FAIL_MODE"]
state = {"streams": 0, "failed": False}
class Flaky(hosted.Pacer):
    # the pacer's verdict is whatever the driver says: the provider failed for good, or it did not
    def left(self):
        return 100
    @property
    def failed(self):
        return state["failed"]
    @failed.setter
    def failed(self, v):
        pass
    @property
    def last_error(self):
        return "status 429"
    @last_error.setter
    def last_error(self, v):
        pass
hosted.Pacer = Flaky
real = sp.StubWriter.stream
def stream(self, messages, **k):
    state["streams"] += 1
    if state["streams"] == 4:                      # the Writer's call of the fourth turn
        if MODE == "signal":
            state["failed"] = True                 # the engine turned the error into text; the pacer knows the provider failed
        elif MODE == "raise":
            state["failed"] = True
            raise RuntimeError("provider down")    # the engine raised it; the pacer knows the provider failed
        elif MODE == "bug":
            raise RuntimeError("a bug of ours")    # raised, but the provider did not fail
    return real(self, messages, **k)
sp.StubWriter.stream = stream
from soak.__main__ import main
sys.exit(main(sys.argv[1:]))
"""


def drive(mode):
    out = Path(tempfile.mkdtemp(prefix=f"cr-hosted-{mode}-"))
    env = dict(os.environ, **{hosted.KEY_ENV: CANARY, "PYTHONIOENCODING": "utf-8", "FAIL_MODE": mode})
    r = subprocess.run([sys.executable, "-c", DRIVER, "play", "--out", str(out), "--stub", "--provider", "openrouter", "--model", "x/y:free",
                        "--turns", "10"], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, cwd=ROOT, timeout=300)
    return r.returncode, (r.stdout or "") + (r.stderr or ""), out


def test_run_stops_at_the_failed_turn():
    want = "the provider failed at turn 4 (status 429); that turn is not recorded"
    # the provider failed for good, shown as error text in the story (signal) or as an exception out of the engine's turn (raise: this is
    # what a real run did, and the first version of this test missed it because it only simulated the first)
    for mode in ("signal", "raise"):
        code, text, out = drive(mode)
        assert code == 0, (mode, text[-400:])
        s = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        assert s["turns"] == 3, f"{mode}: the failed turn was recorded or the run went on: {s['turns']}"
        assert s["stopped"] == want, (mode, s["stopped"])
        rows = [json.loads(x) for x in (out / "turns.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
        assert [x["i"] for x in rows] == [1, 2, 3], (mode, [x["i"] for x in rows])
    # a bug of ours is NOT the provider's failure: it must stop the run loudly, not be swallowed into a tidy summary
    code, text, out = drive("bug")
    assert code != 0 and "a bug of ours" in text, (code, text[-300:])
    assert not (out / "summary.json").exists(), "a bug was turned into a normal-looking summary"
    print("7b. a provider that fails for good (as text or as an exception) stops the run at that turn, unrecorded, with a summary and a reason; "
          "a bug of ours still stops it loudly")

test_model_guard()
test_key_by_name()
test_pacer()
test_retry()
test_config()
test_command_line()
test_failed_for_good()
test_run_stops_at_the_failed_turn()
print("\nSOAK HOSTED TESTS PASSED")
