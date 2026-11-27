"""The model check run when switching models (soak/check.py, D-079).

What it protects. A check that cannot fail would pass every model, and one that cannot pass would fail every model; either way
the owner would pick a model on noise. So a good offline writer must pass every check, a bad one must fail every check, and the
comparison must only call a change worse or better when it is big enough to mean something.

 1) the good writer passes every check, every question had its facts in the prompt, and the report, the replies and the
    comparison are written; the temp home is removed and the repo's saves are never touched
 2) the bad writer fails every check, and the failing replies are quoted in the report with the app's own reason for the JSON jobs
 3) each scorer on its own: what it catches, and what it must not (a character's "You say..." is not your line, speech may say
    "I", a short spoken answer need not say "you")
 4) a change is worse or better only at a quarter of the replies and two replies; reports of another check version or with other
    settings are said to differ
 5) the report to compare with is the newest one of another model, else of the same model; other versions and broken files are
    skipped
 6) refused: a paid hosted model, no model at all, a bad --against, rounds below one
 7) a model that cannot be called stops the run with a message, and no report is written
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-check-"))
TEMPDIR = WORK / "temp"                               # the temp folder of the runs below, so what they leave is visible
TEMPDIR.mkdir()

from soak import check as ck                          # noqa: E402  (soak.check imports no coderain at the top)

ENV = dict(os.environ, PYTHONIOENCODING="utf-8", TEMP=str(TEMPDIR), TMP=str(TEMPDIR), TMPDIR=str(TEMPDIR))
ENV.pop("OPENROUTER_API_KEY", None)                   # nothing here may ever reach a hosted model, even with a fix broken


def run(*args):
    return subprocess.run([sys.executable, "-m", "soak", "check", *args], cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=240, env=ENV)


def report_in(folder: Path) -> dict:
    return json.loads((folder / "report.json").read_text(encoding="utf-8"))


def saves_state() -> list:
    saves = ROOT / "saves"
    return sorted((p.name, p.stat().st_mtime_ns) for p in saves.iterdir()) if saves.is_dir() else []


def test_good_and_bad():
    before = saves_state()
    r = run("--stub", "good", "--repeats", "2", "--out", str(WORK / "reports" / "1-good"))
    assert r.returncode == 0, r.stdout + r.stderr
    good = report_in(WORK / "reports" / "1-good")
    assert list(good["checks"]) == list(ck.CHECKS)
    short = {k: c for k, c in good["checks"].items() if not c["total"] or c["passed"] != c["total"]}
    assert not short, short
    sizes = {k: c["total"] for k, c in good["checks"].items()}
    assert sizes["keeps_quiet"] == 8 and sizes["ties"] == 4 and sizes["in_story"] == 42 and sizes["summary"] == 2, sizes
    replies = [json.loads(ln) for ln in (WORK / "reports" / "1-good" / "replies.jsonl").read_text(encoding="utf-8").splitlines()]
    asked = [x for x in replies if "facts_in_prompt" in x]
    assert len(asked) == 2 * len(ck.PROBE_CHECKS) and all(x["facts_in_prompt"] for x in asked), \
        [x["kind"] for x in asked if not x["facts_in_prompt"]]
    assert "Nothing earlier to compare with." in (WORK / "reports" / "1-good" / "report.md").read_text(encoding="utf-8")
    assert saves_state() == before, "the repo's saves changed"
    assert not list(TEMPDIR.glob("soakcheck-*")), "the temp home was left behind"
    print("1. the good writer passes every check, every question had its facts in the prompt, reports written, home removed")

    r = run("--stub", "bad", "--repeats", "2", "--out", str(WORK / "reports" / "2-bad"))
    assert r.returncode == 0, r.stdout + r.stderr
    bad = report_in(WORK / "reports" / "2-bad")
    passed = {k: c for k, c in bad["checks"].items() if not c["total"] or c["passed"]}
    assert not passed, passed
    md = (WORK / "reports" / "2-bad" / "report.md").read_text(encoding="utf-8")
    assert "Compared with **stub-good**" in md, "the newest report of another model was not picked"
    assert md.count("| worse |") == len(ck.CHECKS), md
    for key in ("summary", "chapter", "director"):
        assert bad["checks"][key]["examples"] and all(len(e) > 10 for e in bad["checks"][key]["examples"]), \
            (key, bad["checks"][key]["examples"])
    assert "usable first chapter" in bad["checks"]["chapter"]["examples"][0], bad["checks"]["chapter"]["examples"]
    assert "north beacon" in " ".join(bad["checks"]["keeps_quiet"]["examples"])
    print("2. the bad writer fails every check; the report quotes the failures and the app's own reason for the JSON jobs")


def test_scorers():
    q1, q2 = chr(0x201C), chr(0x201D)
    # your words
    assert not ck.keeps_your_words('"Hand it over," you say.')
    assert not ck.keeps_your_words(f"{q1}Where is it?{q2} you ask.")
    assert not ck.keeps_your_words('You say quietly, "I know."')
    assert not ck.keeps_your_words("You decide to leave at once.")
    assert not ck.keeps_your_words("'Hand it over,' you whisper.")
    assert ck.keeps_your_words('He frowns. "You say that now," he mutters.'), "a character's own line was taken for yours"
    assert ck.keeps_your_words('You ask Hollis about the key. "I have it," he says.'), "restating your action is not a line"
    # in the story
    assert not ck.stays_in_story("I cannot continue with this scene.")
    assert not ck.stays_in_story("As an AI, the narrator will stop here.")
    assert not ck.stays_in_story('"Sorry," he says. Would you like me to continue?')
    assert ck.stays_in_story('"I cannot help you," the smuggler says, and you step back.'), "speech was taken for a refusal"
    # speaks to you
    assert not ck.speaks_to_you("I walk to the door and wait.")
    assert not ck.speaks_to_you("The rain soaks my coat as you wait.")
    assert not ck.speaks_to_you("The traveller walks to the door. " * 8), "a long third-person reply passed"
    assert ck.speaks_to_you('"Hollis Wren," he says.'), "a short spoken answer need not say you"
    assert ck.speaks_to_you(f"You wait. {q1}I know my way,{q2} she says."), "speech may say I"
    assert ck.speaks_to_you("You wait. 'I know my way,' she says."), "single-quoted speech may say I"
    # prompt text, endings, lengths
    for leak in ("## Notes\nYou wait.", "NARRATOR: you wait", "Facts in play, from the story's own files", "<think>x</think>",
                 "```rpg", "[[character:bram]] nods", "LENGTH: keep it short"):
        assert not ck.no_prompt_text(leak), leak
    assert ck.no_prompt_text("You wait at the counter: nothing happens. He says the word narrator out loud.")
    assert ck.finishes("You wait.") and ck.finishes(f"{q1}Go{q2}") and ck.finishes("*She nods.*")
    assert not ck.finishes("You wait and") and not ck.finishes("")
    assert ck.short_enough("word " * ck.SHORT_WORDS) and not ck.short_enough("word " * (ck.SHORT_WORDS + 1))
    assert not ck.short_enough("a.\n\nb.\n\nc.\n\nd.") and not ck.short_enough("  ")
    assert ck.long_enough("word " * ck.LONG_WORDS) and ck.long_enough("a.\n\nb.\n\nc.\n\nd.")
    assert not ck.long_enough("word " * (ck.LONG_WORDS - 1))
    print("3. each scorer catches what it should and leaves alone what it should")


def made(model, scores, when="2026-01-01 00:00:00", version=ck.PACK_VERSION, settings=None):
    checks = {k: {"label": ck.CHECKS[k], "passed": p, "total": t, "examples": []} for k, (p, t) in scores.items()}
    return {"pack_version": version, "model": model, "when": when, "repeats": 1, "settings": settings or {"think": False},
            "checks": checks, "speed": {"replies": 1, "median_secs": 1.0, "median_words": 1}}


def change(before, now):
    rows = ck.compare(made("a", {"ties": before}), made("b", {"ties": now}))
    return rows[0]["change"] if rows else None


def test_compare():
    assert change((4, 4), (2, 4)) == "worse" and change((2, 4), (4, 4)) == "better"
    assert change((4, 4), (3, 4)) == "about the same", "one reply is chance"
    assert change((1, 1), (0, 1)) == "about the same", "all of one reply is still one reply"
    assert change((42, 42), (32, 42)) == "about the same", "ten of 42 is under a quarter"
    assert change((42, 42), (31, 42)) == "worse"
    assert change((8, 8), (6, 8)) == "worse" and change((6, 8), (8, 8)) == "better", "exactly a quarter and two replies counts"
    assert change((2, 4), (4, 8)) == "about the same", "the same share over more replies"
    assert change((0, 0), (2, 4)) is None and not ck.compare(made("a", {}), made("b", {"ties": (1, 2)}))
    old = made("a", {"ties": (4, 4)}, version=0, settings={"think": True})
    notes = ck.notes_for(old, made("b", {"ties": (4, 4)}))
    assert len(notes) == 2 and "different versions" in notes[0] and "think" in notes[1], notes
    assert not ck.notes_for(made("a", {}), made("b", {}))
    md = ck.to_markdown(made("b", {"ties": (2, 4)}), made("a", {"ties": (4, 4)}))
    assert "**Worse than before:** Answers who is tied to whom" in md, md
    md = ck.to_markdown(made("b", {"ties": (4, 4)}), made("a", {"ties": (4, 4)}))
    assert "**Worse than before:** nothing by a clear margin." in md, md
    print("4. worse or better only at a quarter of the replies and two replies; version and settings differences are said")


def test_previous():
    root = WORK / "previous"
    def put(name, report):
        (root / name).mkdir(parents=True)
        (root / name / "report.json").write_text(json.dumps(report) if isinstance(report, dict) else report, encoding="utf-8")
    put("z-old-other", made("other", {}, when="2026-01-01 10:00:00"))
    put("a-new-other", made("other", {}, when="2026-01-03 10:00:00"))
    put("b-same", made("mine", {}, when="2026-01-04 10:00:00"))
    put("c-old-version", made("third", {}, when="2026-01-05 10:00:00", version=0))
    put("d-broken", "not json")
    got = ck.previous_report(root, "mine")
    assert got["model"] == "other" and got["when"] == "2026-01-03 10:00:00", got
    assert ck.previous_report(root, "other")["model"] == "mine"
    assert ck.previous_report(root, "mine", skip=root / "a-new-other")["when"] == "2026-01-01 10:00:00"
    only = WORK / "only-same"
    (only / "x").mkdir(parents=True)
    (only / "x" / "report.json").write_text(json.dumps(made("mine", {})), encoding="utf-8")
    assert ck.previous_report(only, "mine")["model"] == "mine"
    assert ck.previous_report(WORK / "nothing-here", "mine") is None
    assert ck.read_report(root / "b-same")["model"] == "mine" and ck.read_report(root / "d-broken") is None
    print("5. compares with the newest report of another model, else the same model; other versions and broken files skipped")


def test_refusals():
    r = run("--provider", "openrouter", "--model", "some/model", "--out", str(WORK / "no"))
    assert r.returncode != 0 and ":free" in r.stdout + r.stderr, r.stdout + r.stderr
    r = run("--out", str(WORK / "no"))
    assert r.returncode != 0 and "--model" in r.stdout + r.stderr, r.stdout + r.stderr
    r = run("--stub", "good", "--against", str(WORK / "nothing.json"), "--out", str(WORK / "no"))
    assert r.returncode != 0 and "not a report" in r.stdout + r.stderr, r.stdout + r.stderr
    r = run("--stub", "good", "--repeats", "0", "--out", str(WORK / "no"))
    assert r.returncode != 0 and "at least 1" in r.stderr, r.stderr
    assert not (WORK / "no").exists()
    print("6. a paid hosted model, no model, a bad --against and zero rounds are refused, nothing written")


DOWN = '''
import sys
sys.argv = ["soak", "check", "--stub", "good", "--repeats", "1", "--out", sys.argv[1], "--against", "none"]
from soak import check as ck
def boom(self, messages, **k):
    raise ConnectionError("the model server went away")
    yield ""
ck.StubModel.stream = boom
from soak.__main__ import main
sys.exit(main())
'''


def test_a_model_that_cannot_be_called():
    out = WORK / "down"
    r = subprocess.run([sys.executable, "-c", DOWN, str(out)], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=240, env=ENV)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "could not be called" in r.stdout and "the model server went away" in r.stdout, r.stdout + r.stderr
    assert not (out / "report.json").exists(), "a report of failed calls was written"
    assert not list(TEMPDIR.glob("soakcheck-*")), "the temp home was left behind"
    print("7. a model that cannot be called stops the run with the reason, and no report is written")


for fn in (test_good_and_bad, test_scorers, test_compare, test_previous, test_refusals, test_a_model_that_cannot_be_called):
    fn()
print("\nSOAK CHECK TESTS PASSED")
