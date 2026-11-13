"""The scripted player (python -m soak play, D-046): the same moves for the same seed, an offline writer, fate on/off.

Every comparison that needs a story played for many turns needs the same player making the same moves, and the driver
the consistency soaks used lived outside the repo. This pins the in-repo one with its offline writer, so nothing here
needs a model.

 1) a stub run plays N turns and writes one row per turn and a summary; a probe turn comes every probe-every turns and
    the offline writer states the sheet's colour, so each probe is scored held
 2) the same seed gives the same actions and prose; another seed does not
 3) fate off asks the model nothing; preview asks and records for every turn and steers nothing; on steers
 4) probe_verdict: held, drift and none
 5) it refuses what it must: a model host that is not this machine, the canon card with no model, and no turns
 6) the repo root is never the home (the run builds a temp one)
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-soakplay-"))
_n = [0]


def play(*extra, expect=0):
    _n[0] += 1
    out = WORK / f"run{_n[0]}"
    r = subprocess.run([sys.executable, "-m", "soak", "play", "--out", str(out), *extra], cwd=ROOT,
                       capture_output=True, text=True, timeout=240, encoding="utf-8", errors="replace")
    assert r.returncode == expect, (extra, r.returncode, r.stdout[-300:], r.stderr[-500:])
    if expect:
        return r
    rows = [json.loads(x) for x in (out / "turns.jsonl").read_text(encoding="utf-8").splitlines()]
    return rows, json.loads((out / "summary.json").read_text(encoding="utf-8")), out


def test_a_stub_run():
    rows, s, out = play("--stub", "--turns", "24")
    assert len(rows) == 24 and s["turns"] == 24 and s["stub"] is True and s["fate"] == "off"
    probes = [r for r in rows if r["kind"] == "probe"]
    assert [r["i"] for r in probes] == [8, 16, 24], [r["i"] for r in probes]
    assert all(r["verdict"] == "held" for r in probes), [r.get("verdict") for r in probes]
    assert s["probes"] == {"held": 3, "drift": 0, "none": 0} and s["health_rows"] == 0, s
    assert all(r["text"] and r["action"] and r["words"] > 3 for r in rows)
    assert s["fate_rows"] == 0 and s["model_calls"]["fate"] == 0 and s["model_calls"]["writer"] == 24
    assert (out / "turns.jsonl").exists() and (out / "summary.json").exists()
    print("1. a stub run plays 24 turns, writes a row each and a summary, and every probe is held")


def test_the_same_seed_gives_the_same_story():
    a, _sa, _ = play("--stub", "--turns", "14", "--seed", "11")
    b, _sb, _ = play("--stub", "--turns", "14", "--seed", "11")
    c, _sc, _ = play("--stub", "--turns", "14", "--seed", "12")
    key = lambda rows: [(r["action"], r["text"]) for r in rows]          # noqa: E731
    assert key(a) == key(b), "the same seed played differently"
    assert key(a) != key(c), "another seed played the same story"
    fa, _f1, _ = play("--stub", "--turns", "14", "--seed", "11", "--fate", "preview")
    fb, _f2, _ = play("--stub", "--turns", "14", "--seed", "11", "--fate", "preview")
    assert [r["fate"] for r in fa] == [r["fate"] for r in fb] and all(r["fate"] for r in fa),         "fate's rows differ between two runs of the same seed (a flaky stub made the first draft of this suite fail one run in several)"
    print("2. the same seed gives the same actions and prose; another seed does not")


def test_fate_modes():
    rows, s, _ = play("--stub", "--turns", "12", "--fate", "preview")
    assert s["fate"] == "preview" and s["fate_rows"] == 12 and s["health_rows"] == 0, s
    assert all(any("fate (preview) d20" in e for e in r["events"]) for r in rows), "a preview row has no event line"
    assert s["model_calls"]["steered"] == 0, "preview steered the Writer"
    rows, s, _ = play("--stub", "--turns", "12", "--fate", "on")
    steered = sum(1 for r in rows if r["fate"] and r["fate"]["text"])
    assert s["model_calls"]["steered"] == steered and steered > 0, (s["model_calls"], steered)
    assert all(any(e.startswith("fate d20") for e in r["events"]) for r in rows), "on with the die shown has no event line"
    assert not any(r["fate"]["text"] in " ".join(r["events"]) for r in rows if r["fate"] and r["fate"]["text"]), \
        "on showed the sentence"
    rows, s, _ = play("--stub", "--turns", "12", "--fate", "off")
    assert s["model_calls"]["fate"] == 0 and s["model_calls"]["steered"] == 0 and not any(r["fate"] for r in rows)
    print("3. fate off asks nothing, preview asks and records for every turn and steers nothing, on steers")


def test_probe_verdict():
    from soak.play import probe_verdict
    assert probe_verdict("Ottoline Pike meets your look. Ottoline's red hair catches the light.", "Ottoline Pike", "hair", "red") == "held"
    assert probe_verdict("Her crimson hair is tied back.", "Ottoline Pike", "hair", "red") == "held", "a colour of the same family is held"
    assert probe_verdict("Her black hair is tied back.", "Ottoline Pike", "hair", "red") == "drift"
    assert probe_verdict("Ottoline looks away and says nothing.", "Ottoline Pike", "hair", "red") == "none"
    assert probe_verdict("Her grey eyes narrow.", "Ottoline Pike", "hair", "red") == "none", "eyes are not hair"
    assert probe_verdict("Her grey eyes narrow.", "Ottoline Pike", "eyes", "grey") == "held"
    print("4. probe_verdict: held, drift, none")


def test_refusals():
    r = play("--model", "x", "--host", "http://10.0.0.5:11434", "--turns", "2", expect=1)
    assert "not this machine" in (r.stderr + r.stdout), r.stderr[-200:]
    r = play("--stub", "--canon", "card", "--turns", "2", expect=1)
    assert "needs --model" in (r.stderr + r.stdout), r.stderr[-200:]
    play("--stub", "--turns", "0", expect=2)
    print("5. a remote model host, the canon card with no model and zero turns are refused")


def test_never_the_repo_root():
    rows, s, out = play("--stub", "--turns", "3")
    before = sorted(p.name for p in (ROOT / "saves").iterdir()) if (ROOT / "saves").exists() else []
    play("--stub", "--turns", "3")
    after = sorted(p.name for p in (ROOT / "saves").iterdir()) if (ROOT / "saves").exists() else []
    assert before == after, "the player wrote into the repo's saves"
    src = (ROOT / "soak" / "play.py").read_text(encoding="utf-8")
    assert "assert_isolated()" in src and "isolated_home(\"soakplay-\")" in (ROOT / "soak" / "__main__.py").read_text(encoding="utf-8")
    print("6. the run builds a temp home and never touches the repo's saves")


for fn in (test_a_stub_run, test_the_same_seed_gives_the_same_story, test_fate_modes, test_probe_verdict, test_refusals,
           test_never_the_repo_root):
    fn()
print("\nSOAK PLAY TESTS PASSED")
