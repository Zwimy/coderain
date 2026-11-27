"""A run of run_tests.py must leave nothing behind in the temp folder.

What broke. The suites make temp folders (homes, copies of the repo, the soak runs they start) and do not remove them, and the
runner made one more for itself. Every full run left a few hundred behind; more than 8,000 (1.9 GB) had piled up. The runner
now gives the whole run one temp folder, hands it to every suite and every process a suite starts, and removes it at the end.

 1) after a full run, the temp folder is empty: what the suite made, what a process it started made, and a read-only file
 2) the suite and its child saw TEMP and CODERAIN_HOME inside the run's own folder, so a run is still hermetic
 3) a failing suite leaves nothing behind either, and the run still fails
 4) a suite run on its own through run_one gets the same: nothing left behind
 5) something that cannot be removed (a file still held open, on Windows) is reported, not raised, and the rest is removed
"""
import io
import os
import shutil
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-runtemp-"))

import run_tests                                              # noqa: E402

SYSTEM = WORK / "system-temp"                                 # stands in for the machine's temp folder
FAKE = WORK / "fake-repo"

SUITE = '''
import os, stat, subprocess, sys, tempfile
mine = tempfile.mkdtemp(prefix="made-by-suite-")
child = subprocess.run([sys.executable, "-c", "import tempfile; print(tempfile.mkdtemp(prefix='made-by-child-'))"],
                       capture_output=True, text=True, check=True).stdout.strip()
locked = os.path.join(mine, "read-only.txt")
open(locked, "w").close()
os.chmod(locked, stat.S_IREAD)
print("SEEN|" + "|".join([mine, child, os.environ["CODERAIN_HOME"]]))
sys.exit(EXIT)
'''


def in_sandbox(fn):
    """Run `fn` with SYSTEM as the temp folder, for this process and for what it starts."""
    SYSTEM.mkdir(exist_ok=True)
    keep_env = {k: os.environ.get(k) for k in ("TEMP", "TMP", "TMPDIR")}
    keep_dir = tempfile.tempdir
    for k in keep_env:
        os.environ[k] = str(SYSTEM)
    tempfile.tempdir = str(SYSTEM)
    try:
        return fn()
    finally:
        tempfile.tempdir = keep_dir
        for k, v in keep_env.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def fake_suite(exit_code: int) -> Path:
    shutil.rmtree(FAKE, ignore_errors=True)
    (FAKE / "tests").mkdir(parents=True)
    path = FAKE / "tests" / "a_test.py"
    path.write_text(SUITE.replace("EXIT", str(exit_code)), encoding="utf-8")
    return path


def capture(fn):
    buf = io.StringIO()
    with redirect_stdout(buf):
        result = fn()
    return result, buf.getvalue()


def seen(echoed: str) -> list[Path]:
    line = next(ln for ln in echoed.splitlines() if ln.startswith("SEEN|"))
    return [Path(p) for p in line.split("|")[1:]]


def whole_run(exit_code: int):
    fake_suite(exit_code)
    keep = run_tests.ROOT
    run_tests.ROOT = FAKE
    try:
        return capture(lambda: in_sandbox(run_tests.main))
    finally:
        run_tests.ROOT = keep


def check_places(echoed: str):
    paths = seen(echoed)
    tops = {p.relative_to(SYSTEM).parts[0] for p in paths}            # raises when one landed outside the sandbox
    assert len(tops) == 1 and next(iter(tops)).startswith("coderain-tests-"), tops
    assert all(len(p.relative_to(SYSTEM).parts) >= 2 for p in paths), paths


def test_a_run_leaves_nothing():
    code, echoed = whole_run(0)
    assert code == 0 and "ALL SUITES PASSED" in echoed, echoed
    assert list(SYSTEM.iterdir()) == [], [p.name for p in SYSTEM.iterdir()]
    assert "Could not remove" not in echoed, echoed
    check_places(echoed)
    print("1-2. nothing is left after a run (suite, child and read-only file), and TEMP and the home were inside the run's folder")


def test_a_failing_run_leaves_nothing():
    code, echoed = whole_run(3)
    assert code == 1 and "FAILED: a_test.py" in echoed, echoed
    assert list(SYSTEM.iterdir()) == [], [p.name for p in SYSTEM.iterdir()]
    print("3. a failing suite leaves nothing behind either, and the run still fails")


def test_one_suite_on_its_own():
    path = fake_suite(0)
    (rc, timed, _skips), echoed = capture(lambda: in_sandbox(lambda: run_tests.run_one(path, 60)))
    assert rc == 0 and not timed, echoed
    assert list(SYSTEM.iterdir()) == [], [p.name for p in SYSTEM.iterdir()]
    check_places(echoed)
    print("4. a suite run through run_one on its own gets a temp folder of its own, removed afterwards")


def test_what_will_not_go_is_reported():
    keep = run_tests.remove_run_dir
    run_tests.remove_run_dir = lambda run_dir: (keep(run_dir), False)[1]
    try:
        code, echoed = whole_run(0)
    finally:
        run_tests.remove_run_dir = keep
    assert code == 0 and "Could not remove all of" in echoed, echoed
    if os.name != "nt":                                       # elsewhere an open file can be deleted, so nothing is held
        print("5. a run that cannot remove everything says so")
        return
    run_dir = WORK / "held"
    (run_dir / "sub").mkdir(parents=True)
    (run_dir / "sub" / "gone.txt").write_text("x", encoding="utf-8")
    held = open(run_dir / "held.txt", "w", encoding="utf-8")
    try:
        assert run_tests.remove_run_dir(run_dir) is False
        assert (run_dir / "held.txt").exists() and not (run_dir / "sub").exists(), "the rest was not removed"
    finally:
        held.close()
    assert run_tests.remove_run_dir(run_dir) is True and not run_dir.exists()
    print("5. a file still held open is reported, not raised, the rest is removed, and the run says so")


for fn in (test_a_run_leaves_nothing, test_a_failing_run_leaves_nothing, test_one_suite_on_its_own,
           test_what_will_not_go_is_reported):
    fn()
shutil.rmtree(WORK, ignore_errors=True)
print("\nRUN TESTS TEMP TESTS PASSED")
