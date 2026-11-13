"""run_tests.py must say what it did not run.

What broke. A suite whose optional dependency is missing (the browser suite without playwright, the piece-editor suite
without node) prints a SKIP line and exits 0, which is right for a dev-only dependency, but then "ALL SUITES PASSED"
hid that the check never ran: on a machine without playwright every browser claim was "green" and unchecked.

 1) run_one echoes a suite's output and returns its exit code, whether it timed out, and its SKIP lines
 2) SKIP and SKIPPED lines are found (with a colon or a space after, indented too); a line that merely mentions the
    word is not
 3) a failing suite returns its code, and a suite over its time limit is killed and reported as timed out
 4) the summary at the end of a real run lists every skipped suite (read from the runner's source)
"""
import io
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.mkdtemp(prefix="cr-runner-"))

import run_tests                                              # noqa: E402


def script(name, body):
    p = WORK / name
    p.write_text(body, encoding="utf-8")
    return p


def run(p, timeout=60):
    buf = io.StringIO()
    with redirect_stdout(buf):
        res = run_tests.run_one(p, timeout)
    return res, buf.getvalue()


def test_skip_lines_are_found():
    (rc, timed, skips), echoed = run(script("a.py", 'print("start")\nprint("SKIPPED: playwright is not installed.")\n'
                                                    'print("  SKIP: node is missing")\nprint("done")\n'))
    assert rc == 0 and not timed
    assert skips == ["SKIPPED: playwright is not installed.", "SKIP: node is missing"], skips
    assert "start" in echoed and "done" in echoed and "playwright" in echoed, "the output was not echoed"
    (rc, timed, skips), _ = run(script("b.py", 'print("a test that does not skip")\nprint("we SKIP nothing; SKIPPED: not at the start")\n'))
    assert skips == [], skips
    print("1-2. a suite's output is echoed and its SKIP lines are found; a line that only mentions the word is not")


def test_failure_and_timeout():
    (rc, timed, _s), _ = run(script("c.py", "import sys\nprint('about to fail')\nsys.exit(3)\n"))
    assert rc == 3 and not timed
    (rc, timed, _s), echoed = run(script("d.py", "import time\nprint('hanging', flush=True)\ntime.sleep(60)\n"), timeout=2)
    assert timed and rc != 0 and "hanging" in echoed, (rc, timed)
    print("3. a failing suite returns its code; a suite over its time limit is killed and reported as timed out")


def test_a_narrow_console_does_not_crash_the_echo():
    """The first version of run_one crashed the whole run with a UnicodeEncodeError the moment a suite printed an
    arrow while stdout was a cp1252 console or file (the full suite found it, the unit cases did not)."""
    raw = io.BytesIO()
    narrow = io.TextIOWrapper(raw, encoding="cp1252", errors="strict", write_through=True)
    old, sys.stdout = sys.stdout, narrow
    try:
        run_tests.ensure_utf8_stdout()
        (rc, timed, skips), _ = (run_one_to_current_stdout(script("e.py", "print('before \\u2192 after \\u00e9')\n")), "")
    finally:
        sys.stdout = old
    assert rc == 0 and not timed
    assert "before" in raw.getvalue().decode("utf-8"), raw.getvalue()
    print("3b. a cp1252 console or file no longer crashes the echo of a suite that prints an arrow or an accent")


def run_one_to_current_stdout(p):
    return run_tests.run_one(p, 60)


def test_summary_is_printed():
    src = (ROOT / "run_tests.py").read_text(encoding="utf-8")
    assert "SKIPPED, so NOT checked here" in src and "skipped.append((t.name, skips[0]))" in src
    assert "elif skips:" in src, "a skipping suite is not collected"
    assert "def main() -> int:\n    ensure_utf8_stdout()\n" in src, "main() does not make stdout UTF-8 before echoing"
    print("4. the end-of-run summary lists the skipped suites")


for fn in (test_skip_lines_are_found, test_failure_and_timeout, test_a_narrow_console_does_not_crash_the_echo,
           test_summary_is_printed):
    fn()
print("\nRUN TESTS SKIP TESTS PASSED")
