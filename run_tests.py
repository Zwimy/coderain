"""Run all Coderain test suites (offline; no model/network needed).

    py run_tests.py            # or: .venv\\Scripts\\python.exe run_tests.py

Each file in tests/ is a standalone script that exercises the memory/engine
internals with fake LLMs and asserts. They persist the regression coverage for
every bug found in the phase bug-sweeps.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"
PY = PY if PY.exists() else Path(sys.executable)

# Point every test at a throwaway data dir. Tests read load_config(), and the
# real config.yaml is the USER's live settings (e.g. use_memory_tool on) — a
# stub LLM then hits a code path it doesn't implement and the suite fails on the
# user's machine even though a fresh clone (default config) is green. A temp home
# gives every run the same default config and also keeps tests from touching real
# saves. (Tests that need their own home set CODERAIN_HOME themselves.)
_TEST_HOME = tempfile.mkdtemp(prefix="coderain-tests-")

# Force UTF-8 for every child so a test that prints a non-ASCII glyph (→, …)
# doesn't die on a Windows cp1252 console — keeps the suite green on any OS.
ENV = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
       "CODERAIN_HOME": _TEST_HOME}


def main() -> int:
    tests = sorted((ROOT / "tests").glob("*.py"))
    failed = []
    for t in tests:
        print(f"=== {t.name} ===")
        if subprocess.run([str(PY), str(t)], env=ENV).returncode:
            failed.append(t.name)
    print("\n" + ("ALL SUITES PASSED" if not failed
                  else "FAILED: " + ", ".join(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
