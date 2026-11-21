# -*- coding: utf-8 -*-
"""IRDrone installation self-tests: is this computer able to process a mission?

    python selftests.py            (irdrone_diagnostic.bat / .sh run them too)

Each check runs one link of the processing chain on data bundled with IRDrone
(samples/_visible.DNG of the DJI drone, samples/_nir.RAW of the SJCam M20, a
visible / near infrared pair, a synthetic ArUco target), the same way the
wizard does, in a temporary folder whose name holds accents (Windows code
pages). Nothing in the working folder or in a mission is modified.

A check gives one status:

* ok       : works;
* warning  : works, but something may go wrong later (little free space...);
* failed   : this link is broken: the steps using it will fail;
* skipped  : not run, because a check it needs failed (the cause is there).

and, when it is not ok, a plain sentence on what is wrong and how to fix it.
From the wizard: first page, "Check the installation" (also ⚙ options).
"""
import datetime
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
for _path in (ROOT, ROOT / "irdrone_wizard"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

SAMPLES = ROOT / "samples"
SAMPLE_DNG = SAMPLES / "_visible.DNG"            # DJI Mavic Air 2 (FC3170)
SAMPLE_RAW = SAMPLES / "_nir.RAW"                # SJCam M20
# SJCam names hold the date: Step 1 writes it in the DNG
SAMPLE_RAW_NAME = "2022_0125_130446_023.RAW"
SAMPLE_RAW_DATE = "2022:01:25 13:04:46"
SAMPLE_PAIR = (SAMPLES / "20210906123134_PL4_DIST_raw_NON_LINEAR_REF.jpg",
               SAMPLES / "20210906123134_PL4_DIST_raw_NON_LINEAR_IR_registered_semi_auto.jpg")
FIXED_IDS = (5, 22, 16, 13)
MOBILE_ID = 0
MIN_FREE_GB = 20            # a mission of 300 pairs needs about 15 GB
TOOL_TIMEOUT = 60

OK, WARNING, FAILED, SKIPPED = "ok", "warning", "failed", "skipped"
ICONS = {OK: "✔", WARNING: "⚠", FAILED: "✖", SKIPPED: "–"}
LABELS = {OK: "OK", WARNING: "WARNING", FAILED: "FAILED", SKIPPED: "SKIPPED"}

TEARING_MAX = 4.0     # see _tearing
REINSTALL = ("Install IRDrone again: Windows bat_helpers\\install.bat, Linux / macOS ./setup.sh "
             "(they install the packages of requirements.txt in the Python used by the wizard).")
# Python modules the wizard imports: (module, pip package, what needs it, required)
MODULES = (
    ("numpy", "numpy", "everything", True),
    ("scipy", "scipy", "Step 3 time alignment, Step 4", True),
    ("cv2", "opencv-contrib-python", "image reading, ArUco markers, alignment", True),
    ("PyQt6.QtWidgets", "PyQt6", "the wizard windows", True),
    ("matplotlib", "matplotlib", "Step 3 plots, Step 4", True),
    ("skimage", "scikit-image", "Step 4 alignment", True),
    ("numba", "numba", "Step 4 alignment (speed)", True),
    ("imageio", "imageio", "images", True),
    ("pandas", "pandas", "Step 2 flight analysis", True),
    ("openpyxl", "openpyxl", "Step 2 spreadsheets", True),
    ("piexif", "piexif", "EXIF of the output images", True),
    ("exifread", "exifread", "EXIF of the images", True),
    ("PIL", "Pillow", "images", True),
    ("psutil", "psutil", "free space, processors", True),
    ("rasterio", "rasterio", "Step 5 / 6 maps", True),
    ("geopy", "geopy", "place names", True),
    ("requests", "requests", "maps and place names", True),
    ("qrcode", "qrcode", "Step 6 QR codes", True),
    ("rawpy", "rawpy", "raw image previews", False),
    ("osgeo.gdal", "GDAL", "Step 6 contour lines (optional)", False),
)


class CheckError(Exception):
    """A check that failed with a known cause: ``fix`` says what to do."""

    def __init__(self, detail, fix="", data=None):
        super().__init__(detail)
        self.detail, self.fix, self.data = detail, fix, data or {}


class Skip(Exception):
    """A check that cannot run (a check it needs failed)."""


class Context:
    """What the checks share: the temporary accented folder, results, log."""

    def __init__(self, work: Path, log=print):
        self.work = work
        self.log = log
        self.results = {}
        self.files = {}         # name -> Path of a file made by a check (DNG converted...)

    def need(self, *names):
        for name in names:
            result = self.results.get(name)
            if result is None or result["status"] in (FAILED, SKIPPED):
                title = TITLES.get(name, name)
                raise Skip(f"needs \"{title}\", which did not pass")


def _run(cmd, timeout=TOOL_TIMEOUT, env=None):
    """(return code, output) of an external program; (None, error) if it could not start."""
    try:
        result = subprocess.run([str(c) for c in cmd], capture_output=True, timeout=timeout,
                                encoding="utf-8", errors="replace", env=env)
        return result.returncode, ((result.stdout or "") + (result.stderr or "")).strip()
    except subprocess.TimeoutExpired:
        return None, f"no answer after {timeout} s"
    except OSError as error:
        return None, f"{type(error).__name__}: {error}"


def _first_lines(text, n=3):
    return "\n".join((text or "").splitlines()[:n])


def _image_summary(image):
    import numpy as np
    return {"shape": list(image.shape), "dtype": str(image.dtype), "min": float(np.min(image)),
            "max": float(np.max(image)), "mean": round(float(np.mean(image)), 4),
            "std": round(float(np.std(image)), 4)}


def _check_not_flat(image, name, low, high, fix):
    """A developed image that is not black, white or uniform."""
    summary = _image_summary(image)
    if summary["std"] <= (high - low) * 0.01:
        raise CheckError(f"{name} is uniform (mean {summary['mean']}, std {summary['std']}): "
                         "the image was not developed correctly.", fix, summary)
    if not (low + (high - low) * 0.02 < summary["mean"] < high - (high - low) * 0.02):
        raise CheckError(f"{name} is {'black' if summary['mean'] < (low + high) / 2 else 'white'} "
                         f"(mean {summary['mean']}).", fix, summary)
    return summary


def _tearing(image):
    """Mean row-to-row over column-to-column variation: about 1 on a photograph, far more when the rows are
    shifted sideways by bands (a DNG misread by RawTherapee 5.13 gives 40)."""
    import numpy as np
    gray = np.asarray(image, dtype=np.float32)
    if gray.ndim == 3:
        gray = gray.mean(axis=2)
    across = float(np.abs(np.diff(gray, axis=1)).mean())
    return float(np.abs(np.diff(gray, axis=0)).mean()) / max(across, 1e-6)


def _rawtherapee_version():
    import config
    try:
        out = subprocess.run([config.RAWTHERAPEEPATH, "-v"], capture_output=True, text=True, timeout=60).stdout
        import re
        found = re.search(r"version\s+([0-9][0-9.]*)", out)
        return found.group(1) if found else "?"
    except (OSError, subprocess.SubprocessError):
        return "?"


def _check_not_torn(image, name, fix):
    """The developed image is a photograph, not rows shifted sideways by bands."""
    ratio = _tearing(image)
    if ratio > TEARING_MAX:
        raise CheckError(f"{name} is torn into horizontal bands shifted sideways (row / column variation {ratio:.0f} "
                         f"instead of about 1): RawTherapee {_rawtherapee_version()} misreads this DNG.",
                         "Install RawTherapee 5.10 (5.8 also works): the SJCam DNG is developed correctly by them "
                         "and torn by RawTherapee 5.13. " + fix, {"tearing": round(ratio, 1)})
    return round(ratio, 2)


# ---------------------------------------------------------------------------
#  Python
# ---------------------------------------------------------------------------
def check_python(ctx):
    version = sys.version_info
    data = {"version": sys.version.split()[0], "executable": sys.executable,
            "bits": 64 if sys.maxsize > 2 ** 32 else 32, "platform": platform.platform()}
    detail = f"Python {data['version']} ({data['bits']} bits) {sys.executable}"
    if data["bits"] == 32:
        raise CheckError(detail + ": a 32 bits Python cannot hold the images in memory.",
                         "Install a 64 bits Python 3.10 or newer, then IRDrone again. " + REINSTALL, data)
    if version < (3, 9):
        raise CheckError(detail + ": too old.", "Install Python 3.10 or newer, then IRDrone again. " + REINSTALL, data)
    return OK, detail, "", data


def check_packages(ctx):
    import importlib
    from importlib import metadata
    missing, optional, versions = [], [], {}
    for module, package, used_by, required in MODULES:
        try:
            imported = importlib.import_module(module)
            try:
                versions[package] = metadata.version(package)
            except metadata.PackageNotFoundError:
                versions[package] = getattr(imported, "__version__", "?")
        except Exception as error:        # ImportError, DLL load failed (Windows)...
            entry = f"{package} ({used_by}): {type(error).__name__}: {_first_lines(str(error), 1)}"
            (missing if required else optional).append(entry)
            ctx.log(f"    cannot import {module}: {error}")
    data = {"versions": versions, "missing": missing, "optional_missing": optional}
    if missing:
        raise CheckError("Python packages missing or broken:\n" + "\n".join(f"  {m}" for m in missing),
                         "Install them in the Python of the wizard (" + sys.executable + "): "
                         f"\"{sys.executable}\" -m pip install -r requirements.txt — or " + REINSTALL, data)
    detail = f"{len(versions)} packages imported"
    if optional:
        detail += " (optional, not installed: " + ", ".join(m.split(" (")[0] for m in optional) + ")"
    return OK, detail, "", data


def check_opencv(ctx):
    from importlib import metadata
    import cv2
    packages = []
    for name in ("opencv-python", "opencv-contrib-python", "opencv-python-headless", "opencv-contrib-python-headless"):
        try:
            packages.append(f"{name} {metadata.version(name)}")
        except metadata.PackageNotFoundError:
            pass
    data = {"version": cv2.__version__, "file": getattr(cv2, "__file__", None), "packages": packages}
    fix = (f"\"{sys.executable}\" -m pip uninstall -y opencv-python opencv-python-headless "
           f"opencv-contrib-python-headless opencv-contrib-python, then \"{sys.executable}\" -m pip install "
           "opencv-contrib-python")
    if not hasattr(cv2, "aruco"):
        raise CheckError(f"OpenCV {cv2.__version__} has no ArUco module (opencv-python instead of "
                         "opencv-contrib-python): Step 3 cannot find the synchronisation target.", fix, data)
    if len(packages) > 1:
        return WARNING, (f"OpenCV {cv2.__version__}, but several OpenCV packages are installed "
                         f"({', '.join(packages)}): they overwrite each other's files."), fix, data
    return OK, f"OpenCV {cv2.__version__} with ArUco ({', '.join(packages) or 'built from source'})", "", data


# ---------------------------------------------------------------------------
#  External tools
# ---------------------------------------------------------------------------
def _tool(variable):
    import config
    for label, tool_variable, path, found, need, hint in config._TOOLS:
        if tool_variable == variable:
            return label, str(path), found, need, hint
    raise KeyError(variable)


def _tool_fix(variable):
    label, path, found, need, hint = _tool(variable)
    return (f"Install {label} from {hint}, or set the environment variable {variable} to the full path of "
            f"the program (Windows: System > Advanced system settings > Environment variables), "
            "then restart the wizard.")


def _check_tool(ctx, variable, args, expect=None):
    label, path, found, need, hint = _tool(variable)
    data = {"path": path, "found": bool(found), "from_environment": variable in os.environ, "need": need}
    if not found:
        source = f"environment variable {variable}" if variable in os.environ else "searched"
        raise CheckError(f"{label} not found ({source}: {path}). It is {need}.", _tool_fix(variable), data)
    code, out = _run([path] + list(args))
    data["output"] = _first_lines(out, 5)
    data["return_code"] = code
    if code is None or not out or (code != 0 and not expect) or (expect and expect not in out):
        raise CheckError(f"{label} found at {path} but does not run: {_first_lines(out, 2) or 'no output'}",
                         f"Install {label} again (another version, or the 64 bits one): {hint}.", data)
    version = _first_lines(out, 1).replace("Version:", "").strip()
    data["version"] = version
    return OK, f"{version if label.split()[0] in version else label + ' ' + version} ({path})", "", data


def check_exiftool(ctx):
    status, detail, fix, data = _check_tool(ctx, "EXIFTOOLPATH", ["-ver"])
    if "." not in data["version"]:
        raise CheckError(f"ExifTool answered \"{data['version']}\" instead of its version.",
                         _tool_fix("EXIFTOOLPATH"), data)
    return status, f"ExifTool {data['version']} ({data['path']})", fix, data


def check_rawtherapee(ctx):
    status, detail, fix, data = _check_tool(ctx, "RAWTHERAPEEPATH", ["-v"], expect="RawTherapee")
    return status, detail, fix, data


def check_sjcam_converter(ctx):
    status, detail, fix, data = _check_tool(ctx, "SJCONVERTERPATH", ["-v"])
    return status, detail, fix, data


# ---------------------------------------------------------------------------
#  Folders
# ---------------------------------------------------------------------------
def check_working_folder(ctx):
    import config
    folder = Path(config.OUTPUT_FOLDER_NAME)
    data = {"path": str(folder), "source": getattr(config, "WORKING_DIR_SOURCE", None)}
    fix = "Choose another working folder: ⚙ options on the first page of the wizard."
    if not folder.is_dir():
        return WARNING, f"The working folder {folder} does not exist yet (it is created with the first mission).", \
            "Nothing to do, or choose another one (⚙ options).", data
    probe = folder / f".irdrone_write_test_{os.getpid()}"
    try:
        probe.write_text("IRDrone", encoding="utf-8")
        probe.unlink()
    except OSError as error:
        raise CheckError(f"Cannot write in the working folder {folder}: {error}", fix, data)
    free_gb = shutil.disk_usage(folder).free / 1e9
    data["free_gb"] = round(free_gb, 1)
    detail = f"{folder}: writable, {free_gb:.0f} GB free"
    if free_gb < MIN_FREE_GB:
        return WARNING, detail + " (a mission needs 10 to 20 GB).", \
            "Free some space, or choose a working folder on another disk (⚙ options).", data
    return OK, detail, "", data


def check_accented_folder(ctx):
    """Image written / read and EXIF read by ExifTool in a folder named with accents."""
    import numpy as np
    import config
    import image_io
    image = (np.arange(24 * 16 * 3) % 255).astype(np.uint8).reshape(24, 16, 3)
    path = ctx.work / "VIS_0001_é.jpg"
    data = {"folder": str(ctx.work)}
    fix = ("Use a working folder and mission names without accents (é, è, ç...) or special characters, "
           "and send a diagnostic report.")
    if not image_io.imwrite(path, image):
        raise CheckError(f"Cannot write an image in {ctx.work}.", fix, data)
    read = image_io.imread(path)
    if read is None or read.shape != image.shape:
        raise CheckError(f"Cannot read back an image in {ctx.work}.", fix, data)
    if config._EXIFTOOL_FOUND:
        import exiftool_reader
        try:
            metadata = exiftool_reader.read_exiftool_json(config.EXIFTOOLPATH, path)
        except Exception as error:
            raise CheckError(f"ExifTool cannot read an image in a folder with accents: {error}", fix, data)
        if metadata.get("FileName") != path.name:
            raise CheckError(f"ExifTool read the name \"{metadata.get('FileName')}\" instead of \"{path.name}\" "
                             "(code page).", fix, data)
        return OK, "Image and EXIF read / written in a folder named with accents", "", data
    return OK, "Image read / written in a folder named with accents (ExifTool not tested: not found)", "", data


def check_tiff(ctx):
    """16 bits TIFF written and read again as Step 4 reads RawTherapee TIFFs."""
    import numpy as np
    import image_io
    from irdrone.process import load_tif
    rng = np.random.default_rng(0)
    image = rng.integers(0, 65535, (40, 56, 3), dtype=np.uint16)
    path = ctx.work / "TIFF 16 bits é.tif"
    fix = "Install OpenCV again (its TIFF support is broken): " + REINSTALL
    if not image_io.imwrite(path, image):
        raise CheckError("OpenCV cannot write a 16 bits TIFF.", fix)
    read = load_tif(path)                     # RGB, float32 in [0, 1]
    expected = image[..., ::-1].astype(np.float32) / 65535.
    error = float(np.abs(read - expected).max())
    data = {"shape": list(read.shape), "dtype": str(read.dtype), "max_error": error}
    if read.shape != expected.shape or error > 1e-4:
        raise CheckError(f"A 16 bits TIFF is read differently (shape {read.shape}, error {error:.2g}).", fix, data)
    return OK, "16 bits TIFF written and read back exactly (Step 4 developed images)", "", data


def check_processes(ctx):
    """Step 4 aligns the pairs in several processes."""
    from concurrent.futures import ProcessPoolExecutor
    started = time.perf_counter()
    try:
        with ProcessPoolExecutor(max_workers=2) as executor:
            pids = set(executor.map(_child_pid, range(4), timeout=120))
    except Exception as error:
        raise CheckError(f"Cannot start worker processes: {type(error).__name__}: {error}",
                         "Step 4 can run in a single process: send a diagnostic report. Antivirus software "
                         "sometimes blocks the Python processes started by the wizard.")
    pids.discard(os.getpid())
    data = {"workers": len(pids), "seconds": round(time.perf_counter() - started, 2), "cpu_count": os.cpu_count()}
    if not pids:
        raise CheckError("The worker processes did not run.", "Send a diagnostic report.", data)
    return OK, f"{len(pids)} worker processes started in {data['seconds']} s ({os.cpu_count()} processors)", "", data


def _child_pid(_):
    return os.getpid()


# ---------------------------------------------------------------------------
#  ArUco (Step 3)
# ---------------------------------------------------------------------------
def synthetic_target(size=60, angle=30.0, frame_angle=0.0):
    """Grey image of the synchronisation target: fixed markers 5, 22, 16, 13
    around the rotating marker 0 (DICT_4X4_50), turned by ``angle`` degrees;
    the whole target turned by ``frame_angle`` (drone yaw)."""
    import cv2
    import numpy as np
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    generate = getattr(cv2.aruco, "generateImageMarker", None) or getattr(cv2.aruco, "drawMarker")

    def marker(marker_id):
        m = generate(dictionary, marker_id, size)
        pad = size // 6
        return cv2.resize(cv2.copyMakeBorder(m, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=255), (size, size))

    canvas = np.full((size * 6, size * 6), 190, np.uint8)
    for marker_id, (x, y) in zip(FIXED_IDS, ((2.5, 0.5), (4.5, 2.5), (2.5, 4.5), (0.5, 2.5))):
        x0, y0 = int(x * size), int(y * size)
        canvas[y0:y0 + size, x0:x0 + size] = marker(marker_id)
    rotation = cv2.getRotationMatrix2D((size / 2, size / 2), angle, 1.0)
    mobile = cv2.warpAffine(marker(MOBILE_ID), rotation, (size, size), borderValue=190)
    c0 = int(2.5 * size)
    canvas[c0:c0 + size, c0:c0 + size] = mobile
    if frame_angle:
        big = cv2.copyMakeBorder(canvas, size, size, size, size, cv2.BORDER_CONSTANT, value=190)
        center = (big.shape[1] / 2, big.shape[0] / 2)
        canvas = cv2.warpAffine(big, cv2.getRotationMatrix2D(center, frame_angle, 1.0), big.shape[::-1],
                                flags=cv2.INTER_CUBIC, borderValue=190)
    return cv2.cvtColor(canvas, cv2.COLOR_GRAY2BGR)


def marker_ids(image):
    """Sorted ArUco ids found by the detection Step 3 uses."""
    import IRD_Interactive_ArUco as Aru
    data = Aru.detect_aruco_marker(image, Aru.get_aruco_dict("DICT_4X4_50"), verbose=False)
    return sorted({int(entry[0]) for entry in data})


def _angle(ctx, image, name):
    import contextlib
    import io
    import IRD_Interactive_ArUco as Aru
    with contextlib.redirect_stdout(io.StringIO()):
        result, _, _ = Aru.detect_mobile_marker_absolute(
            image_cv=image, img_path=ctx.work / f"{name}.jpg", arucoDict=Aru.get_aruco_dict("DICT_4X4_50"),
            fixed_ids=list(FIXED_IDS), mobile_id=MOBILE_ID, verbose=False)
    return result


def _wrap(angle):
    return (angle + 180.) % 360. - 180.


def check_aruco(ctx):
    """The five markers of a perfect target are found, the rotation of the
    mobile marker is measured, and does not depend on the drone yaw."""
    fix = ("OpenCV does not detect the markers of a perfect target: install opencv-contrib-python again. "
           + REINSTALL)
    found = marker_ids(synthetic_target())
    expected = sorted((MOBILE_ID,) + FIXED_IDS)
    data = {"found": found, "expected": expected}
    if found != expected:
        raise CheckError(f"ArUco markers found {found} instead of {expected} on a perfect synthetic target.",
                         fix, data)
    reference = _angle(ctx, synthetic_target(size=80, angle=0), "angle_0")
    errors = {}
    for turn in (30, 75, 160):
        result = _angle(ctx, synthetic_target(size=80, angle=turn), f"angle_{turn}")
        if result is None or result.get("angle_abs") is None:
            raise CheckError(f"The angle of the mobile marker is not measured (marker turned by {turn}°).", fix, data)
        errors[turn] = abs(_wrap(float(reference["angle_abs"]) - float(result["angle_abs"]) - turn))
    yawed = _angle(ctx, synthetic_target(size=80, angle=30, frame_angle=25), "yaw_25")
    straight = _angle(ctx, synthetic_target(size=80, angle=30), "yaw_0")
    yaw_error = abs(_wrap(float(yawed["angle_abs"]) - float(straight["angle_abs"]))) if yawed and straight else None
    data.update({"angle_errors_deg": errors, "yaw_invariance_error_deg": yaw_error})
    worst = max(errors.values())
    if worst > 3:
        raise CheckError(f"Mobile marker angle measured with an error of {worst:.1f}° (more than 3°).", fix, data)
    if yaw_error is None or yaw_error > 3:
        raise CheckError(f"The absolute angle changes with the drone yaw (error {yaw_error}°).", fix, data)
    return OK, (f"5 markers found; rotation measured within {worst:.1f}°; drone yaw of 25° changes the "
                f"absolute angle by {yaw_error:.1f}°"), "", data


# ---------------------------------------------------------------------------
#  DJI DNG (visible)
# ---------------------------------------------------------------------------
def _copy_sample(ctx, source, folder, name):
    if not source.is_file():
        raise CheckError(f"Sample image missing: {source}.",
                         "Download IRDrone again (the samples folder is incomplete).")
    target = ctx.work / folder / name
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.is_file():
        shutil.copyfile(source, target)
    return target


def _exif(path):
    import config
    import exiftool_reader
    return exiftool_reader.read_exiftool_json(config.EXIFTOOLPATH, path)


def check_dng_exif(ctx):
    """ExifTool reads the date, camera, gimbal and GPS of a DJI DNG (Step 1 / 2)."""
    ctx.need("exiftool")
    dng = _copy_sample(ctx, SAMPLE_DNG, "VIS", "DJI_0001.DNG")
    metadata = _exif(dng)
    wanted = ("DateTimeOriginal", "Model", "GimbalYawDegree", "GPSLatitude", "GPSLongitude", "ImageWidth")
    data = {key: metadata.get(key) for key in wanted}
    missing = [key for key in wanted if metadata.get(key) in (None, "")]
    if missing:
        raise CheckError(f"ExifTool does not read {', '.join(missing)} in a DJI DNG.",
                         "Install a recent ExifTool (12 or newer): " + _tool("EXIFTOOLPATH")[4], data)
    return OK, (f"DJI {data['Model']} DNG: date {data['DateTimeOriginal']}, gimbal yaw {data['GimbalYawDegree']}, "
                f"GPS read"), "", data


def _rawtherapee_fix():
    return ("RawTherapee does not develop the images: install RawTherapee 5.8 or newer again "
            f"({_tool('RAWTHERAPEEPATH')[4]}) and check RAWTHERAPEEPATH.")


def _develop_for_aruco(ctx, dng, name):
    """The development of Step 3 (Aruco_Detection.pp3, JPEG)."""
    import IRD_Interactive_ArUco as Aru
    started = time.perf_counter()
    try:
        image, out_file = Aru.load_dng_for_aruco(str(dng), ctx.work)
    except Exception as error:
        raise CheckError(f"RawTherapee failed on {name}: {error}", _rawtherapee_fix())
    if image is None:
        raise CheckError(f"RawTherapee did not write the developed {name} (JPEG for Step 3).", _rawtherapee_fix())
    summary = _check_not_flat(image, f"The developed {name}", 0, 255, _rawtherapee_fix())
    summary["tearing"] = _check_not_torn(image, f"The developed {name}", _rawtherapee_fix())
    summary["seconds"] = round(time.perf_counter() - started, 1)
    return summary


def _develop_linear(ctx, dng, name, template):
    """The development of Step 4 (linear 16 bits TIFF)."""
    from irdrone.process import load_dng
    started = time.perf_counter()
    try:
        image, out_file = load_dng(str(dng), template=template)
    except Exception as error:
        raise CheckError(f"RawTherapee failed on {name} ({template}): {error}", _rawtherapee_fix())
    summary = _check_not_flat(image, f"The developed {name} ({template})", 0., 1., _rawtherapee_fix())
    summary["tearing"] = _check_not_torn(image, f"The developed {name} ({template})", _rawtherapee_fix())
    summary["seconds"] = round(time.perf_counter() - started, 1)
    summary["tiff"] = Path(out_file).name
    return summary


def check_dng_step3(ctx):
    ctx.need("rawtherapee")
    dng = _copy_sample(ctx, SAMPLE_DNG, "VIS", "DJI_0001.DNG")
    data = _develop_for_aruco(ctx, dng, "DJI DNG")
    return OK, f"DJI DNG developed for Step 3 in {data['seconds']} s: {data['shape'][1]}×{data['shape'][0]}, " \
               f"mean {data['mean']:.0f}/255", "", data


def check_dng_step4(ctx):
    ctx.need("rawtherapee", "tiff")
    dng = _copy_sample(ctx, SAMPLE_DNG, "VIS4", "DJI_0001.DNG")
    data = _develop_linear(ctx, dng, "DJI DNG", "DJI_neutral.pp3")
    return OK, f"DJI DNG developed for Step 4 in {data['seconds']} s: linear TIFF {data['shape'][1]}×" \
               f"{data['shape'][0]}, mean {data['mean']:.3f}", "", data


# ---------------------------------------------------------------------------
#  SJCam RAW (near infrared)
# ---------------------------------------------------------------------------
def check_sjcam_raw(ctx):
    """SJCam .RAW converted to DNG as in Step 1, its date written by ExifTool."""
    ctx.need("sjcam_converter", "exiftool")
    import config
    from irdrone.convert_raw_to_dng import _convert_single_raw
    raw = _copy_sample(ctx, SAMPLE_RAW, "RAW", SAMPLE_RAW_NAME)
    out = ctx.work / "NIR"
    out.mkdir(exist_ok=True)
    started = time.perf_counter()
    fix = (f"The SJCam converter fails: install it again ({_tool('SJCONVERTERPATH')[4]}); on Windows it needs the "
           "Microsoft Visual C++ Redistributable (x64).")
    try:
        dng = Path(_convert_single_raw(str(raw), config.SJCONVERTERPATH, str(out), "0", False, config.EXIFTOOLPATH))
    except subprocess.CalledProcessError as error:
        raise CheckError(f"The SJCam converter stopped with the code {error.returncode}.", fix)
    if not dng.is_file() or dng.stat().st_size < 1_000_000:
        raise CheckError(f"The SJCam converter did not write the DNG ({dng.name}).", fix)
    seconds = round(time.perf_counter() - started, 1)
    metadata = _exif(dng)
    data = {"dng": dng.name, "size": dng.stat().st_size, "seconds": seconds,
            "DateTimeOriginal": metadata.get("DateTimeOriginal"), "Model": metadata.get("Model")}
    if metadata.get("DateTimeOriginal") != SAMPLE_RAW_DATE:
        raise CheckError(f"The date of the converted DNG is {metadata.get('DateTimeOriginal')!r} instead of "
                         f"{SAMPLE_RAW_DATE!r} (taken from the RAW name by ExifTool): Step 2 / 3 will place the "
                         "infrared images wrongly in time.",
                         "Install a recent ExifTool: " + _tool("EXIFTOOLPATH")[4], data)
    ctx.files["sjcam_dng"] = dng
    return OK, f"SJCam .RAW converted to {dng.name} in {seconds} s, date {data['DateTimeOriginal']} written", "", data


def check_sjcam_step3(ctx):
    ctx.need("rawtherapee", "sjcam_raw")
    data = _develop_for_aruco(ctx, ctx.files["sjcam_dng"], "SJCam DNG")
    return OK, f"SJCam DNG developed for Step 3 in {data['seconds']} s: {data['shape'][1]}×{data['shape'][0]}, " \
               f"mean {data['mean']:.0f}/255", "", data


def check_sjcam_step4(ctx):
    ctx.need("rawtherapee", "sjcam_raw", "tiff")
    data = _develop_linear(ctx, ctx.files["sjcam_dng"], "SJCam DNG", "SJCAM.pp3")
    return OK, f"SJCam DNG developed for Step 4 in {data['seconds']} s: linear TIFF {data['shape'][1]}×" \
               f"{data['shape'][0]}, mean {data['mean']:.3f}", "", data


# ---------------------------------------------------------------------------
#  Alignment (Step 4)
# ---------------------------------------------------------------------------
def check_alignment(ctx):
    """The pyramid alignment of Step 4 (gradient energies, NTG) finds a known
    shift between a visible and a near infrared image of the same scene."""
    import cv2
    import numpy as np
    import image_io
    from registration.constants import LAPLACIAN_ENERGIES, NTG
    from registration.rigid import pyramidal_search
    vis, nir = (image_io.imread(path) for path in SAMPLE_PAIR)
    if vis is None or nir is None:
        raise CheckError("Sample visible / infrared pair missing.", "Download IRDrone again (samples folder).")
    scale = 1000. / vis.shape[1]
    vis, nir = (cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA).astype(np.float32) / 255.
                for img in (vis, nir))
    h, w = vis.shape[:2]
    shift = np.float32([12., -8.])
    moved = cv2.warpAffine(nir, np.float32([[1, 0, shift[0]], [0, 1, shift[1]]]), (w, h),
                           borderMode=cv2.BORDER_REFLECT)
    options = dict(debug=False, mode=LAPLACIAN_ENERGIES, dist=NTG, iterative_scheme=[(8, 2, 4, 8), (8, 2, 5), (2, 3, 5)],
                   affinity=False, sigma_ref=5., sigma_mov=3.)
    started = time.perf_counter()
    reference = pyramidal_search(vis, nir, **options)
    shifted = pyramidal_search(vis, moved, **options)
    seconds = round(time.perf_counter() - started, 2)
    points = np.float32([[x, y] for x in np.linspace(.25 * w, .75 * w, 3)
                         for y in np.linspace(.25 * h, .75 * h, 3)]).reshape(-1, 1, 2)
    # A point of the infrared image is at p + shift in the moved one: both models send it to the same place
    error = float(np.abs(cv2.perspectiveTransform(points + shift, shifted.model)
                         - cv2.perspectiveTransform(points, reference.model)).max())
    data = {"shift_px": shift.tolist(), "error_px": round(error, 3), "seconds": seconds, "width": w}
    if not np.isfinite(error) or error > 1.5:
        raise CheckError(f"The alignment finds the shift of ({shift[0]:.0f}, {shift[1]:.0f}) pixels with an error of "
                         f"{error:.1f} pixels (more than 1.5).",
                         "Install the Python packages again (numpy, scipy, opencv-contrib-python, numba). " + REINSTALL,
                         data)
    return OK, f"Visible / infrared alignment finds a shift of (12, -8) pixels within {error:.2f} pixel " \
               f"({seconds} s)", "", data


# ---------------------------------------------------------------------------
#  Suite
# ---------------------------------------------------------------------------
CHECKS = (
    ("python", "Python", check_python),
    ("packages", "Python packages", check_packages),
    ("opencv", "OpenCV and ArUco", check_opencv),
    ("exiftool", "ExifTool", check_exiftool),
    ("rawtherapee", "RawTherapee", check_rawtherapee),
    ("sjcam_converter", "SJCam RAW converter", check_sjcam_converter),
    ("working_folder", "Working folder", check_working_folder),
    ("accented_folder", "Folder with accents", check_accented_folder),
    ("tiff", "16 bits TIFF", check_tiff),
    ("processes", "Worker processes (Step 4)", check_processes),
    ("aruco", "ArUco target (Step 3)", check_aruco),
    ("dng_exif", "DJI DNG metadata (Steps 1, 2)", check_dng_exif),
    ("dng_step3", "DJI DNG development (Step 3)", check_dng_step3),
    ("dng_step4", "DJI DNG development (Step 4)", check_dng_step4),
    ("sjcam_raw", "SJCam RAW to DNG (Step 1)", check_sjcam_raw),
    ("sjcam_step3", "SJCam DNG development (Step 3)", check_sjcam_step3),
    ("sjcam_step4", "SJCam DNG development (Step 4)", check_sjcam_step4),
    ("alignment", "Visible / infrared alignment (Step 4)", check_alignment),
)
TITLES = {name: title for name, title, _ in CHECKS}
QUICK = ("python", "packages", "opencv", "exiftool", "rawtherapee", "sjcam_converter", "working_folder",
         "accented_folder", "tiff", "aruco")


def run_check(ctx, name, title, function):
    ctx.log(f"[{title}]")
    started = time.perf_counter()
    result = {"name": name, "title": title}
    try:
        status, detail, fix, data = function(ctx)
        result.update(status=status, detail=detail, fix=fix, data=data)
    except Skip as skip:
        result.update(status=SKIPPED, detail=f"Not run: {skip}.", fix="", data={})
    except CheckError as error:
        result.update(status=FAILED, detail=error.detail, fix=error.fix, data=error.data)
    except Exception as error:
        result.update(status=FAILED, detail=f"Unexpected error: {type(error).__name__}: {error}",
                      fix="Send a diagnostic report (button below) to the IRDrone developers.",
                      data={"traceback": traceback.format_exc()})
    result["seconds"] = round(time.perf_counter() - started, 2)
    result["ok"] = result["status"] in (OK, WARNING)
    ctx.results[name] = result
    ctx.log(f"  {LABELS[result['status']]}: {result['detail']}")
    if result["fix"]:
        ctx.log(f"  How to fix: {result['fix']}")
    if result["data"].get("traceback"):
        ctx.log(result["data"]["traceback"])
    return result


def run_checks(names=None, log=print, on_result=lambda result: None, should_stop=lambda: False):
    """Run the checks (all, or ``names``) in a temporary folder; returns
    {name: result}, result = {status, title, detail, fix, data, seconds, ok}."""
    work = Path(tempfile.mkdtemp(prefix="irdrone_selftests_")) / "Démo Florine é"
    work.mkdir(parents=True)
    ctx = Context(work, log)
    try:
        for name, title, function in CHECKS:
            if names is not None and name not in names:
                continue
            if should_stop():
                break
            on_result(run_check(ctx, name, title, function))
    finally:
        shutil.rmtree(work.parent, ignore_errors=True)
    return ctx.results


def summary(results):
    counts = {status: sum(1 for r in results.values() if r["status"] == status)
              for status in (OK, WARNING, FAILED, SKIPPED)}
    if counts[FAILED]:
        verdict = f"{counts[FAILED]} check(s) FAILED: the steps using them will not work. See \"How to fix\"."
    elif counts[WARNING]:
        verdict = f"Installation usable, {counts[WARNING]} warning(s)."
    else:
        verdict = "Installation OK: every check passed."
    return verdict, counts


def text(results, title="IRDrone installation self-tests"):
    """Plain text, for the console, the session log and the diagnostic report."""
    try:
        from version import __version__
    except ImportError:
        __version__ = "?"
    verdict, counts = summary(results)
    lines = [title, "=" * len(title),
             f"IRDrone {__version__}, {datetime.datetime.now().isoformat(timespec='seconds')}, "
             f"{platform.platform()}, Python {sys.version.split()[0]}", "", verdict, ""]
    for result in results.values():
        lines.append(f"[{LABELS[result['status']]:<7}] {result['title']} ({result['seconds']} s)")
        lines += [f"           {line}" for line in result["detail"].splitlines()]
        if result["fix"]:
            lines.append(f"           How to fix: {result['fix']}")
    return "\n".join(lines) + "\n"


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="IRDrone installation self-tests.")
    parser.add_argument("--quick", action="store_true", help="no image development, no alignment")
    parser.add_argument("--json", help="also write the results in this JSON file")
    args = parser.parse_args(argv)
    results = run_checks(QUICK if args.quick else None)
    print()
    print(text(results))
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return 1 if any(r["status"] == FAILED for r in results.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
