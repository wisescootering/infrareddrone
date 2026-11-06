#!/usr/bin/env bash
# End-to-end check of the command line tools: --help of each entry script, then
# the alignment of the sample pair of the repository (RawTherapee, SJCam converter,
# alignment, ExifTool). Needs rawtherapee-cli and exiftool.
#
#   tests/cli_smoke.sh [samples folder]          (default: samples/ of the repository)
#
# In Docker:
#   docker run --rm -v "$PWD/samples:/samples:ro" irdrone tests/cli_smoke.sh /samples
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SAMPLES="${1:-$ROOT/samples}"
PYTHON="${PYTHON:-python}"
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}" MPLBACKEND="${MPLBACKEND:-Agg}"

cd "$ROOT"
for script in run.py run_after_preprocessing.py automatic_registration.py \
              synchronization/synchro_by_aruco.py; do
    "$PYTHON" "$script" --help > /dev/null
    echo "OK  $script --help"
done

# Work on a copy: the alignment writes a .exif cache next to the images.
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
mkdir "$work/in" "$work/out"
cp "$SAMPLES/_visible.DNG" "$SAMPLES/_nir.RAW" "$work/in/"
if ! "$PYTHON" automatic_registration.py --images "$work/in/_visible.DNG" "$work/in/_nir.RAW" \
        --outdir "$work/out" > "$work/log.txt" 2>&1; then
    cat "$work/log.txt"
    echo "FAIL alignment of the sample pair" >&2
    exit 1
fi
for name in VIS__visible.jpg NIR__visible_global.jpg VIR__visible_global.jpg \
            NDVI__visible_global.jpg _visible_motion_model.json; do
    if [ ! -s "$work/out/$name" ]; then
        cat "$work/log.txt"
        echo "FAIL missing output $name" >&2
        exit 1
    fi
done
echo "OK  alignment of the sample pair"
