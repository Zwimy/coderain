"""Run all Coderain test suites (offline; no model/network needed).

    py run_tests.py            # or: .venv\\Scripts\\python.exe run_tests.py

Each file in tests/ is a standalone script that exercises the memory/engine
internals with fake LLMs and asserts. They persist the regression coverage for
every bug found in the phase bug-sweeps.
"""
from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"
PY = PY if PY.exists() else Path(sys.executable)


# One temp folder holds a whole run, and it is removed when the run ends. Every suite, and every process a suite starts, gets it
# as TEMP/TMP/TMPDIR, so the temp folders they make land inside it. Suites do not clean up after themselves: each run left a few
# hundred folders behind in the system temp folder, and more than 8,000 (1.9 GB) had piled up on one machine.
def make_run_dir() -> Path:
    return Path(tempfile.mkdtemp(prefix="coderain-tests-"))


def child_env(run_dir: Path) -> dict:
    # Point every test at a throwaway data dir. Tests read load_config(), and the
    # real config.yaml is the USER's live settings (e.g. use_memory_tool on) — a
    # stub LLM then hits a code path it doesn't implement and the suite fails on the
    # user's machine even though a fresh clone (default config) is green. A temp home
    # gives every run the same default config and also keeps tests from touching real
    # saves. (Tests that need their own home set CODERAIN_HOME themselves.)
    home = run_dir / "home"
    home.mkdir(exist_ok=True)
    # Force UTF-8 for every child so a test that prints a non-ASCII glyph (→, …)
    # doesn't die on a Windows cp1252 console — keeps the suite green on any OS.
    return {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1",
            "CODERAIN_HOME": str(home), "TEMP": str(run_dir), "TMP": str(run_dir), "TMPDIR": str(run_dir)}


def remove_run_dir(run_dir: Path) -> bool:
    """Remove the run's temp folder, read-only files included. False when something in it would not go (a process a suite left
    running still holds a file); the rest is removed all the same."""
    def make_writable_and_retry(func, path, _error):
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except OSError:
            pass                # still held: the caller says what is left

    # `onerror` was renamed in 3.12; both pass the handler the failed call and the path.
    handler = {"onexc" if sys.version_info >= (3, 12) else "onerror": make_writable_and_retry}
    shutil.rmtree(run_dir, **handler)
    return not os.path.exists(run_dir)


# A suite whose optional dependency is missing (playwright, node) says so on a line starting SKIP or SKIPPED and
# exits 0. That is the right behaviour for a dev-only dependency, but a bare "ALL SUITES PASSED" then hid that the
# check never ran. The summary now lists every skip.
SKIP_LINE = re.compile(r"^\s*SKIP(?:PED)?\b[:\s]")


# Per-suite wall clock. There was NO timeout: subprocess.run without one blocks
# forever, so a single hung suite hung the whole run silently and indefinitely,
# with the last printed line the only clue. The GUI suites are the realistic way
# to get there — gui.py has ~30 blocking modal calls (messagebox/simpledialog/
# filedialog), only two suites stub them, and a modal raised by an app that has
# been withdrawn is INVISIBLE: it waits for a click nobody can make.
#
# 300s is ~10x the slowest honest suite (webapp_smoke_test boots uvicorn and a
# headless Chromium). Anything past that is stuck, not slow.
SUITE_TIMEOUT_S = 300


def ensure_utf8_stdout() -> None:
    """The children write UTF-8 (PYTHONIOENCODING above) and this now echoes them, so a cp1252 console or a redirect
    to a file would crash on the first arrow or accent a test prints. Replace, never raise, on what cannot be shown."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def run_one(path: Path, timeout: float = SUITE_TIMEOUT_S, env: dict | None = None) -> tuple[int, bool, list[str]]:
    """Run one suite, echoing its output as it arrives. Returns (exit code, timed out, its SKIP lines). Without `env` it gets a
    temp folder of its own, removed afterwards."""
    if env is None:
        own = make_run_dir()
        try:
            return run_one(path, timeout, child_env(own))
        finally:
            remove_run_dir(own)
    proc = subprocess.Popen([str(PY), str(path)], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", bufsize=1)
    timed_out: list[int] = []
    timer = threading.Timer(timeout, lambda: (timed_out.append(1), proc.kill()))
    timer.start()
    skips: list[str] = []
    try:
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            if SKIP_LINE.match(line):
                skips.append(line.strip())
    finally:
        timer.cancel()
    return proc.wait(), bool(timed_out), skips


def main() -> int:
    ensure_utf8_stdout()
    run_dir = make_run_dir()
    try:                                            # an interrupted run cleans up too
        return run_all(child_env(run_dir))
    finally:
        if not remove_run_dir(run_dir):
            print(f"\nCould not remove all of {run_dir}: something a suite started may still hold a file there.")


def run_all(env: dict) -> int:
    tests = sorted((ROOT / "tests").glob("*.py"))
    failed, stuck, skipped = [], [], []
    for t in tests:
        print(f"=== {t.name} ===", flush=True)      # flush: a crash mid-run must
        rc, timed_out, skips = run_one(t, env=env)  # still leave the name behind
        if timed_out:
            print(f"!!! {t.name} exceeded {SUITE_TIMEOUT_S}s and was killed "
                  f"(a blocking dialog or an infinite loop)", flush=True)
            stuck.append(t.name)
            continue
        if rc:
            failed.append(t.name)
        elif skips:
            skipped.append((t.name, skips[0]))
    bad = failed + [f"{s} (TIMEOUT)" for s in stuck]
    print("\n" + ("ALL SUITES PASSED" if not bad
                  else "FAILED: " + ", ".join(bad)))
    if skipped:
        print(f"\nSKIPPED, so NOT checked here ({len(skipped)}):")
        for name, why in skipped:
            print(f"  {name}: {why}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
