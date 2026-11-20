#!/usr/bin/env bash
# IRDrone diagnostic report (Linux / macOS): ./irdrone_diagnostic.sh [MISSION_FOLDER]
# Same as irdrone_diagnostic.bat on Windows; the zip is written in the working folder.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${IRDRONE_PYTHON:-}"
if [ -z "$PYTHON" ] && [ -x "$ROOT/.venv/bin/python" ]; then PYTHON="$ROOT/.venv/bin/python"; fi
PYTHON="${PYTHON:-python3}"
cd "$ROOT"
exec "$PYTHON" "$ROOT/diagnostic.py" "$@"
