#!/usr/bin/env sh
# Coderain — launch the web app (opens in your browser).
# First run creates a .venv and installs dependencies automatically.
#   ./run.sh            web app (default)
#   ./run.sh --cli      terminal / text mode
# start.py finds/creates the .venv and re-launches itself there.
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then
    exec python3 start.py "$@"
else
    exec python start.py "$@"
fi
