#!/usr/bin/env bash
# Set up IRDrone on Linux / macOS in a virtual environment at .venv/
# (the one irdrone_wizard.sh picks up first).
# Windows: bat_helpers\install.bat does the same.
#
# Uses uv when it is installed (fast, can download the Python version itself),
# otherwise python3 -m venv + pip.
#
#   ./setup.sh                 create .venv, or update it if it exists
#   ./setup.sh --recreate      delete .venv and start again
#
# Environment variables:
#   IRDRONE_PYTHON_VERSION     Python version for uv (default 3.12)
#   PYTHON                     interpreter for the pip fallback (default python3)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$ROOT/.venv"
REQUIREMENTS="$ROOT/requirements.txt"
PYTHON_VERSION="${IRDRONE_PYTHON_VERSION:-3.12}"
PYTHON="${PYTHON:-python3}"

recreate=0
for arg in "$@"; do
    case "$arg" in
        --recreate) recreate=1 ;;
        -h|--help) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unknown option: $arg (see --help)" >&2; exit 2 ;;
    esac
done

if [ "$recreate" -eq 1 ] && [ -d "$VENV" ]; then
    echo "Removing $VENV"
    rm -rf "$VENV"
fi

if command -v uv >/dev/null 2>&1; then
    echo "Using uv ($(uv --version))"
    if [ ! -x "$VENV/bin/python" ]; then
        uv venv --python "$PYTHON_VERSION" "$VENV"
    fi
    uv pip install --python "$VENV/bin/python" -r "$REQUIREMENTS"
else
    echo "uv not found, using $PYTHON -m venv + pip"
    echo "(install uv for a faster setup: https://docs.astral.sh/uv/)"
    if ! command -v "$PYTHON" >/dev/null 2>&1; then
        echo "ERROR: $PYTHON was not found. Install Python 3 or uv." >&2
        exit 1
    fi
    if [ ! -x "$VENV/bin/python" ]; then
        if ! "$PYTHON" -m venv "$VENV"; then
            echo "ERROR: could not create the virtual environment." >&2
            echo "On Debian / Ubuntu: sudo apt install python3-venv" >&2
            exit 1
        fi
    fi
    "$VENV/bin/python" -m pip install --upgrade pip
    "$VENV/bin/python" -m pip install -r "$REQUIREMENTS"
fi

echo
echo "Checking the installation..."
"$VENV/bin/python" - <<'EOF'
import importlib
modules = ["numpy", "scipy", "matplotlib", "cv2", "skimage", "numba", "pandas",
           "openpyxl", "piexif", "exifread", "rawpy", "rasterio", "geopy",
           "requests", "psutil", "PyQt6.QtWidgets", "qrcode"]
missing = []
for name in modules:
    try:
        importlib.import_module(name)
    except Exception as error:
        missing.append(f"{name} ({error})")
try:
    import tkinter  # noqa: F401  (imported when the wizard starts)
except ImportError:
    missing.append("tkinter (On Debian / Ubuntu: sudo apt install python3-tk,"
                   " or install uv and run ./setup.sh --recreate)")
if missing:
    raise SystemExit("ERROR: could not import " + ", ".join(missing))
try:
    from osgeo import gdal  # noqa: F401
except ImportError:
    print("NOTE: GDAL is not installed: contour lines will be skipped.")
print("Python packages OK")
EOF

# External tools, looked up like config.py does: environment variable,
# usual location (bundled copy for the SJCam converter), then the PATH.
find_tool() {  # variable default name
    local value="${!1:-}"
    if [ -n "$value" ]; then [ -x "$value" ] && echo "$value"; return; fi
    if [ -x "$2" ]; then echo "$2"; return; fi
    command -v "$3" 2>/dev/null || true
}
if [ -z "$(find_tool EXIFTOOLPATH /usr/bin/exiftool exiftool)" ]; then
    echo "WARNING: exiftool not found (required)."
    echo "         On Debian / Ubuntu: sudo apt install libimage-exiftool-perl, or set EXIFTOOLPATH."
fi
if [ -z "$(find_tool RAWTHERAPEEPATH /usr/bin/rawtherapee-cli rawtherapee-cli)" ]; then
    echo "WARNING: rawtherapee-cli not found (needed for DNG images)."
    echo "         On Debian / Ubuntu: sudo apt install rawtherapee, or set RAWTHERAPEEPATH."
fi
sjcam_bundled="$ROOT/thirdparty/sjcam_raw2dng_linux/sjcam_raw2dng"
[ "$(uname -s)-$(uname -m)" = "Linux-x86_64" ] || sjcam_bundled=""
if [ -z "$(find_tool SJCONVERTERPATH "$sjcam_bundled" sjcam_raw2dng)" ]; then
    echo "WARNING: SJCam RAW converter not found (needed for SJCam .RAW images)."
    echo "         The bundled copy only runs on Linux x86-64: build it from"
    echo "         https://github.com/yanburman/sjcam_raw2dng and set SJCONVERTERPATH."
fi
if ! command -v docker >/dev/null 2>&1; then
    echo "NOTE: docker not found: ODM mapping (Step 5) needs it."
fi

echo
echo "Done. Launch the wizard with: ./irdrone_wizard.sh"
