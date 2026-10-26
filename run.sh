#!/usr/bin/env bash
# Start the chess coach on Linux. Runs scripts/setup.py until it finishes once.
# Arguments go to scripts/run.py, for example: ./run.sh --no-build
# Other Python for setup: PYTHON=python3.12 ./run.sh
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -f .venv/.setup-done ]; then
    "${PYTHON:-python3}" scripts/setup.py
fi
exec .venv/bin/python scripts/run.py "$@"
