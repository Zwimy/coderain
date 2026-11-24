"""The reply-length options of the play soak (D-070): what the experiment varies reaches the model's budget, and the defaults change nothing.

A 1,000-turn soak showed replies growing past 1,000 words and repeating themselves, and the engine's own length control capped nothing:
`config.prose_tokens` adds 3,000 tokens of reasoning headroom to every prose call, so the soak's `max_tokens: 700` meant 3,700. To find out
whether a real cap or the existing "short" setting stops the growth, the soak gained `--response-length`, `--max-tokens` and
`--no-reasoning-headroom`. A test that does not check these reach the Writer would let the experiment compare three identical runs:

 1) the default config text has exactly the lines it always had (max_tokens 700, response_length medium), and the options change exactly
    those two lines
 2) the budget the Writer really has (`prose_cap_tokens` in the summary): medium 700 + 3,000 headroom = 3,700; short 1,200 + 3,000;
    long 4,096 + 3,000; and with the headroom dropped, medium 700 (or the value given), short 1,200, long 4,096
 3) the headroom is dropped for that run only: the engine's constant is still 3,000 in a fresh process
 4) a bad option is refused before anything runs (an unknown length, a budget under 64 tokens) and 64 is accepted
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from soak.play import _config                                    # noqa: E402


def run(*args):
    out = Path(tempfile.mkdtemp(prefix="cr-replycap-"))
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, "-m", "soak", "play", "--stub", "--turns", "2", "--out", str(out), *args], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", env=env, cwd=ROOT, timeout=300)
    text = (r.stdout or "") + (r.stderr or "")
    summary = None
    if (out / "summary.json").exists():
        summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    return r.returncode, text, summary


def test_config_lines():
    base = _config("m", 4, 5000, "off", False)
    assert "  max_tokens: 700\n  think: false\n" in base and "  response_length: medium\n  ai_acts_as_player: false\n" in base, base[:600]
    assert base == _config("m", 4, 5000, "off", False, response_length="medium", max_tokens=700), "the defaults are not the old text"
    changed = _config("m", 4, 5000, "off", False, response_length="short", max_tokens=450)
    assert "  max_tokens: 450\n  think: false\n" in changed and "  response_length: short\n  ai_acts_as_player: false\n" in changed
    assert changed.replace("max_tokens: 450", "max_tokens: 700").replace("response_length: short", "response_length: medium") == base, \
        "an option changed something else in the config"
    print("1. the default config is the old text; the options change exactly max_tokens and response_length")


def test_the_budget_the_writer_has():
    cases = [(("--response-length", "medium"), 3700), (("--response-length", "short"), 4200), (("--response-length", "long"), 7096),
             (("--response-length", "medium", "--max-tokens", "450"), 3450),
             (("--response-length", "medium", "--no-reasoning-headroom"), 700),
             (("--response-length", "medium", "--max-tokens", "450", "--no-reasoning-headroom"), 450),
             (("--response-length", "short", "--no-reasoning-headroom"), 1200),
             (("--response-length", "long", "--no-reasoning-headroom"), 4096), ((), 3700)]
    for args, want in cases:
        code, text, s = run(*args)
        assert code == 0 and s is not None, (args, text[-300:])
        assert s["prose_cap_tokens"] == want, (args, s["prose_cap_tokens"], want)
    code, text, s = run("--response-length", "short")
    assert s["response_length"] == "short"
    code, text, s = run()
    assert s["response_length"] == "medium"
    print("2. the Writer's real budget follows the options: medium 3,700, short 4,200, long 7,096 with the headroom; 700 / 1,200 / 4,096 without")


def test_headroom_is_for_that_run_only():
    code, text, s = run("--no-reasoning-headroom")
    assert s["prose_cap_tokens"] == 700
    out = subprocess.run([sys.executable, "-c", "import coderain.config as c; print(c.REASONING_HEADROOM)"], capture_output=True, text=True,
                         cwd=ROOT, env=dict(os.environ, CODERAIN_HOME=tempfile.mkdtemp(prefix="cr-replycap-home-")), timeout=120)
    assert out.stdout.strip() == "3000", (out.stdout, out.stderr[-200:])
    print("3. the headroom is dropped for that run only; the engine's constant is still 3,000")


def test_bad_options():
    code, text, s = run("--response-length", "huge")
    assert code != 0 and s is None
    code, text, s = run("--max-tokens", "63")
    assert code != 0 and "at least 64" in text and s is None, (code, text[-200:])
    code, text, s = run("--max-tokens", "64", "--no-reasoning-headroom")
    assert code == 0 and s["prose_cap_tokens"] == 256, (code, s and s["prose_cap_tokens"])     # reply_tokens floors a medium budget at 256
    print("4. an unknown length and a budget under 64 are refused before anything runs; 64 is accepted (the engine floors it at 256)")


test_config_lines()
test_the_budget_the_writer_has()
test_headroom_is_for_that_run_only()
test_bad_options()
print("\nSOAK REPLY CAP TESTS PASSED")
