#!/usr/bin/env bash
# Launch the IRDrone wizard (irdrone_wizard/IRD_Interactive_Main.py) on Linux / macOS.
# Windows: use irdrone_wizard.bat instead.
#
# Python is searched in this order:
#   1. IRDRONE_PYTHON            path to a python executable (set it to force one)
#   2. .venv/bin/python next to this file
#   3. the conda environment IRDRONE_CONDA_ENV (default py39_clean) in
#      ~/miniforge3, ~/miniconda3, ~/anaconda3 or ~/mambaforge
#   4. python3 found on the PATH
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAIN_SCRIPT="$ROOT/irdrone_wizard/IRD_Interactive_Main.py"
CONDA_ENV_NAME="${IRDRONE_CONDA_ENV:-py39_clean}"

if [ ! -f "$MAIN_SCRIPT" ]; then
    echo "ERROR: IRD_Interactive_Main.py was not found at $MAIN_SCRIPT" >&2
    exit 1
fi

PYTHON=""
if [ -n "${IRDRONE_PYTHON:-}" ]; then
    PYTHON="$IRDRONE_PYTHON"
elif [ -x "$ROOT/.venv/bin/python" ]; then
    PYTHON="$ROOT/.venv/bin/python"
else
    for conda_root in "$HOME/miniforge3" "$HOME/miniconda3" "$HOME/anaconda3" "$HOME/mambaforge"; do
        if [ -x "$conda_root/envs/$CONDA_ENV_NAME/bin/python" ]; then
            PYTHON="$conda_root/envs/$CONDA_ENV_NAME/bin/python"
            # Same effect as "conda activate" for the tools the wizard calls.
            export PATH="$conda_root/envs/$CONDA_ENV_NAME/bin:$PATH"
            break
        fi
    done
fi
if [ -z "$PYTHON" ] && command -v python3 >/dev/null 2>&1; then
    PYTHON="python3"
    echo "WARNING: no .venv or conda environment '$CONDA_ENV_NAME' found, using python3 from the PATH." >&2
fi
if [ -z "$PYTHON" ]; then
    echo "ERROR: no Python environment found for IRDrone." >&2
    echo "Create $ROOT/.venv or the conda environment '$CONDA_ENV_NAME'," >&2
    echo "or set IRDRONE_PYTHON to the python executable to use." >&2
    exit 1
fi

cd "$ROOT" || exit 1
"$PYTHON" "$MAIN_SCRIPT" "$@"
status=$?
if [ "$status" -ne 0 ]; then
    echo "IRDrone exited with code $status." >&2
fi
exit "$status"
