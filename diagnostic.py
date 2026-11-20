# -*- coding: utf-8 -*-
"""IRDrone diagnostic report: everything needed to understand a problem met
on another computer, in one zip file to send.

    python diagnostic.py [MISSION_FOLDER] [--output FOLDER] [--no-develop]

(irdrone_diagnostic.bat on Windows: drop a mission folder on it.) Also run
from the wizard: ⚙ options, "Create a diagnostic report…".

The report holds:

* installation: IRDrone version and commit, Python used, system, Windows code
  page (accented paths), Python packages, external tools (path, version),
  settings, working folder and free space;
* self-tests (selftests.py, "Check the installation" in the wizard): every
  link of the processing chain run on the bundled samples (DJI DNG, SJCam
  RAW, ArUco target, alignment, 16 bits TIFF, accented folder...), each with
  how to fix it when it fails;
* mission (optional): steps done, time lines, Step 2 windows, Step 3 offset and
  pairs, developed images older than their DNG; every synchronisation image
  is developed again with RawTherapee in a temporary folder (the mission is
  never modified) and the ArUco markers are searched on it and on the cached
  image Step 3 used; a few developed images are added to the zip;
* the last wizard session logs (session_log.py).

Nothing is sent anywhere: the zip is written next to the working folder (or in
--output) for the user to send.
"""
import argparse
import datetime
import json
import locale
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import traceback
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
for _path in (ROOT, ROOT / "irdrone_wizard"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

PACKAGES = ("numpy", "scipy", "opencv-contrib-python", "opencv-python", "opencv-python-headless",
            "opencv-contrib-python-headless", "PyQt6", "PyQt6-Qt6", "rawpy", "scikit-image", "matplotlib",
            "imageio", "numba", "pandas", "openpyxl", "piexif", "exifread", "rasterio", "geopy",
            "requests", "psutil", "qrcode", "GDAL")
from selftests import MOBILE_ID  # noqa: E402
SAMPLE_IMAGES = 3          # developed images added to the zip per band (first, middle, last)
TOOL_TIMEOUT = 30


def _run(cmd, timeout=TOOL_TIMEOUT):
    """(return code, first lines of the output) of an external program."""
    try:
        result = subprocess.run([str(c) for c in cmd], capture_output=True, timeout=timeout,
                                encoding="utf-8", errors="replace")
        text = (result.stdout or "") + (result.stderr or "")
        return result.returncode, "\n".join(text.strip().splitlines()[:3])
    except (OSError, subprocess.SubprocessError) as error:
        return None, f"{type(error).__name__}: {error}"


def _safe(function, *args, **kwargs):
    """Run one part of the report; an error is written in the report, never raised."""
    try:
        return function(*args, **kwargs)
    except Exception as error:
        return {"error": f"{type(error).__name__}: {error}", "traceback": traceback.format_exc()}


# ---------------------------------------------------------------------------
#  Installation
# ---------------------------------------------------------------------------
def _git_commit():
    head = ROOT / ".git" / "HEAD"
    if not head.is_file():
        return None
    code, out = _run(["git", "-C", ROOT, "log", "-1", "--format=%h %ad %s", "--date=short"])
    if code == 0:
        return out
    try:
        ref = head.read_text().strip()
        if ref.startswith("ref:"):
            return (ROOT / ".git" / ref.split(" ", 1)[1]).read_text().strip()[:10]
        return ref[:10]
    except OSError:
        return None


def _windows_code_page():
    if os.name != "nt":
        return None
    try:
        import ctypes
        return {"ansi": ctypes.windll.kernel32.GetACP(), "console_output": ctypes.windll.kernel32.GetConsoleOutputCP()}
    except Exception as error:
        return f"unknown ({error})"


def _package_versions():
    from importlib import metadata
    versions = {}
    for name in PACKAGES:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            pass
    return versions


def _opencv_info():
    import cv2
    info = {"version": cv2.__version__, "file": getattr(cv2, "__file__", None),
            "ArucoDetector": hasattr(cv2, "aruco") and hasattr(cv2.aruco, "ArucoDetector")}
    try:
        info["build_threads"] = cv2.getNumThreads()
    except Exception:
        pass
    return info


def _tool_versions():
    import config
    tools = {}
    for label, variable, path, found, *_ in config._TOOLS:
        entry = {"variable": variable, "path": str(path), "found": bool(found),
                 "from_environment": variable in os.environ}
        if found and Path(str(path)).is_file():
            stat = Path(str(path)).stat()
            entry["size"] = stat.st_size
            entry["modified"] = datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
            if variable == "EXIFTOOLPATH":
                entry["version"] = _run([path, "-ver"])[1]
            elif variable == "RAWTHERAPEEPATH":
                entry["version"] = (_run([path, "-v"])[1].splitlines() or [""])[0]
        tools[label] = entry
    return tools


def installation_report():
    import config
    try:
        from version import __version__
    except ImportError:
        __version__ = "unknown"
    working = Path(config.OUTPUT_FOLDER_NAME)
    free = None
    try:
        free = shutil.disk_usage(working).free
    except OSError:
        pass
    return {
        "irdrone_version": __version__,
        "commit": _safe(_git_commit),
        "irdrone_folder": str(ROOT),
        "python": {"version": sys.version, "executable": sys.executable, "prefix": sys.prefix},
        "system": {"platform": platform.platform(), "machine": platform.machine(),
                   "processor": platform.processor(), "cpu_count": os.cpu_count()},
        "encodings": {"preferred": locale.getpreferredencoding(False), "filesystem": sys.getfilesystemencoding(),
                      "stdout": getattr(sys.stdout, "encoding", None), "windows_code_page": _windows_code_page()},
        "packages": _safe(_package_versions),
        "opencv": _safe(_opencv_info),
        "tools": _safe(_tool_versions),
        "settings_file": str(config.SETTINGS_FILE),
        "settings": config.load_user_settings(),
        "working_folder": {"path": str(working), "source": config.WORKING_DIR_SOURCE, "exists": working.is_dir(),
                           "free_bytes": free},
        "environment": {k: v for k, v in os.environ.items()
                        if k.startswith(("IRDRONE", "OMP_", "QT_")) or k.endswith("PATH") and k != "PATH"},
    }


# ---------------------------------------------------------------------------
#  Self-tests (selftests.py: the same as "Check the installation" in the wizard)
# ---------------------------------------------------------------------------
from selftests import marker_ids, synthetic_target  # noqa: E402,F401  (used below and by the tests)


def selftest_aruco():
    import selftests
    return selftests.run_checks(["aruco"], log=lambda text: None)["aruco"]


def run_selftests(progress=lambda text: None, log=lambda text: None, quick=False):
    """Every check of selftests.py (``quick``: no image development): {name: result}."""
    import selftests

    def on_result(result):
        progress(f"Self-test {result['title']}: {selftests.LABELS[result['status']]}")
    return selftests.run_checks(selftests.QUICK if quick else None, log=log, on_result=on_result)


# ---------------------------------------------------------------------------
#  Mission
# ---------------------------------------------------------------------------
def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _image_stats(image):
    import numpy as np
    if image is None:
        return None
    return {"shape": list(image.shape), "min": int(np.min(image)), "max": int(np.max(image)),
            "mean": round(float(np.mean(image)), 1), "std": round(float(np.std(image)), 1)}


def mission_summary(mission: Path):
    import IRD_Interactive_progress as Progress
    aerial = mission / "AerialPhotography"
    summary = {"folder": str(mission), "exists": mission.is_dir(),
               "steps_done": sorted(_safe(Progress.done_steps, mission) or []) if mission.is_dir() else [],
               "mission_parameters": _read_json(mission / "FlightAnalytics" / "mission_parameters.json"),
               "flight_timeline": _read_json(mission / "FlightAnalytics" / "flight_timeline.json")}
    for band in ("VIS", "NIR"):
        folder = aerial / band
        if not folder.is_dir():
            summary[band] = None
            continue
        info = {"dng": len(list(folder.glob("*.dng"))) + len(list(folder.glob("*.DNG"))),
                "exif": len(list(folder.glob("*.exif")))}
        transfer = _read_json(folder / f"transfer_info_{band}_dng.json") or {}
        for key in ("tkoff", "sync", "fly"):
            section = transfer.get(key) or {}
            names = section.get("listCopiedImages") or []
            info[key] = {"idMin": section.get("idMin"), "idMax": section.get("idMax"), "count": len(names),
                         "first": names[0] if names else None, "last": names[-1] if names else None,
                         "missing": [n for n in names if not (folder / n).is_file()]}
        info["selected_by"] = transfer.get("selected_by")
        timeline = _read_json(folder / "time_line.json") or {}
        entries = timeline.get(band) or []
        info["time_line"] = {"images": len(entries),
                             "first": entries[0] if entries else None, "last": entries[-1] if entries else None}
        summary[band] = info
    points = _read_json(aerial / "shoot_points.json")
    if isinstance(points, dict):
        summary["step3"] = {"time_shift": points.get("time_shift"), "pairs": len(points.get("shoot_points", [])),
                            "created_at": points.get("created_at")}
    synchro = mission / "Synchro"
    summary["synchro_files"] = sorted(str(p.relative_to(synchro)) for p in synchro.rglob("*")
                                      if p.is_file())[:200] if synchro.is_dir() else []
    return summary


def sync_images_check(mission: Path, work: Path, samples: Path, develop=True, progress=lambda text: None):
    """Every synchronisation image: the markers found on the cached developed
    image Step 3 uses and on a new development (temporary folder)."""
    import IRD_Interactive_ArUco as Aru
    import image_io
    import cv2
    aerial = mission / "AerialPhotography"
    report = {}
    for band in ("VIS", "NIR"):
        try:
            _, _, _, names = Aru.read_transfer_info(aerial, band, "dng", key="sync")
        except Exception as error:
            report[band] = {"error": f"no synchronisation images: {error}"}
            continue
        names = list(names or [])
        rows = []
        keep = {0, len(names) // 2, len(names) - 1}
        for index, name in enumerate(names):
            progress(f"{band} {index + 1}/{len(names)}: {name}")
            dng = aerial / band / name
            row = {"image": name, "dng_exists": dng.is_file()}
            # Same path as Aru.cached_jpeg, which would create the folder in the mission
            cached = mission / "Synchro" / band / f"{dng.stem}_RawTherapee.jpg"
            if cached.is_file() and dng.is_file():
                row["cached_older_than_dng"] = cached.stat().st_mtime < dng.stat().st_mtime
                image = image_io.imread(cached, cv2.IMREAD_COLOR)
                row["cached"] = {"stats": _image_stats(image), "markers": marker_ids(image) if image is not None else None}
            if develop and dng.is_file():
                try:
                    image, out_file = Aru.load_dng_for_aruco(str(dng), work)
                except Exception as error:          # RawTherapee wrote nothing: in the report
                    row["developed"] = {"error": str(error), "markers": None}
                    rows.append(row)
                    continue
                row["developed"] = {"stats": _image_stats(image),
                                    "markers": marker_ids(image) if image is not None else None}
                if image is not None and index in keep:
                    scale = min(1.0, 1200.0 / max(image.shape[:2]))
                    small = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
                    image_io.imwrite(samples / f"{band}_{Path(name).stem}_developed.jpg", small,
                                     [cv2.IMWRITE_JPEG_QUALITY, 80])
            rows.append(row)

        def with_mobile(key):
            return sum(1 for r in rows if (r.get(key) or {}).get("markers") and MOBILE_ID in r[key]["markers"])

        report[band] = {"images": len(rows),
                        "cached_images": sum(1 for r in rows if r.get("cached")),
                        "with_mobile_marker_cached": with_mobile("cached"),
                        "with_mobile_marker_developed": with_mobile("developed") if develop else None,
                        "cached_older_than_dng": sum(1 for r in rows if r.get("cached_older_than_dng")),
                        "rows": rows}
    return report


# ---------------------------------------------------------------------------
#  Report
# ---------------------------------------------------------------------------
def _verdicts(report):
    """Plain sentences on what looks wrong (first thing read in report.txt)."""
    lines = []
    install = report.get("installation", {})
    packages = install.get("packages") or {}
    cv = [p for p in packages if p.startswith("opencv")]
    if len(cv) > 1:
        lines.append(f"Several OpenCV packages installed ({', '.join(cv)}): they overwrite each other, "
                     "keep opencv-contrib-python only.")
    for name, test in (report.get("selftests") or {}).items():
        if not isinstance(test, dict) or test.get("status") in (None, "ok", "skipped"):
            continue
        detail = " ".join(str(test.get("detail", "")).split())
        fix = f" How to fix: {test['fix']}" if test.get("fix") else ""
        lines.append(f"Self-test \"{test.get('title', name)}\" {str(test['status']).upper()}: {detail}{fix}")
    sync = report.get("sync_images") or {}
    for band, data in sync.items():
        if not isinstance(data, dict) or "images" not in data:
            if isinstance(data, dict) and data.get("error"):
                lines.append(f"{band}: {data['error']}")
            continue
        n = data["images"]
        if data.get("cached_older_than_dng"):
            lines.append(f"{band}: {data['cached_older_than_dng']}/{n} developed images in Synchro are older than "
                         "their DNG (Step 1 run again): Step 3 before version 1.6 used them anyway.")
        cached, developed = data.get("with_mobile_marker_cached"), data.get("with_mobile_marker_developed")
        if developed is not None:
            cache = (f"cached images used by Step 3: {cached}/{data.get('cached_images')}"
                     if data.get("cached_images") else "no cached image")
            lines.append(f"{band}: rotating marker found on {developed}/{n} images developed again ({cache}).")
            if data.get("cached_images") and cached < developed:
                lines.append(f"{band}: fewer markers on the cached images than on the images developed again: "
                             "the cache in Synchro is wrong (delete Synchro/{band}).".replace("{band}", band))
            if developed == 0 and n:
                lines.append(f"{band}: no marker on any image developed again: check the developed images "
                             "in the zip (black, white, wrong image?) and the RawTherapee version.")
    if not lines:
        lines.append("Nothing abnormal found.")
    return lines


def _text(report):
    out = ["IRDrone diagnostic report", "=" * 25, f"Created {report['created']}", ""]
    out += ["Summary", "-------"] + [f"* {line}" for line in report["verdicts"]] + [""]
    install = report.get("installation", {})
    out += ["Installation", "------------",
            f"IRDrone {install.get('irdrone_version')}  commit {install.get('commit')}",
            f"Python {((install.get('python') or {}).get('version') or '?').split()[0]}  "
            f"{(install.get('python') or {}).get('executable')}",
            f"System {(install.get('system') or {}).get('platform')}",
            f"Encodings {install.get('encodings')}",
            f"OpenCV {install.get('opencv')}", "Packages:"]
    out += [f"    {k} {v}" for k, v in (install.get("packages") or {}).items()]
    out += ["External tools:"]
    for label, tool in (install.get("tools") or {}).items():
        out.append(f"    {label}: {tool}")
    out += [f"Working folder {install.get('working_folder')}", f"Settings {install.get('settings')}", ""]
    tests = {k: v for k, v in (report.get("selftests") or {}).items() if isinstance(v, dict) and "status" in v}
    if tests:
        import selftests
        out += [selftests.text(tests, title="Self-tests")]
    if report.get("mission"):
        out += ["Mission", "-------", json.dumps(report["mission"], indent=2, ensure_ascii=False, default=str), ""]
    for band, data in (report.get("sync_images") or {}).items():
        out += [f"Synchronisation images {band}", "-" * 28]
        if not isinstance(data, dict) or "rows" not in data:
            out += [str(data), ""]
            continue
        for row in data["rows"]:
            cached = (row.get("cached") or {}).get("markers")
            developed = (row.get("developed") or {}).get("markers")
            stats = (row.get("developed") or row.get("cached") or {}).get("stats") or {}
            out.append(f"    {row['image']:<16} developed {developed}  cached {cached}"
                       f"{'  (cache older than DNG)' if row.get('cached_older_than_dng') else ''}"
                       f"  mean {stats.get('mean')} std {stats.get('std')}")
        out.append("")
    out += ["Files in the zip", "----------------", "report.txt (this file), report.json (everything), logs/, images/"]
    return "\n".join(out) + "\n"


def create_report(mission=None, output=None, develop=True, progress=lambda text: None, checks=None,
                  quick=False) -> Path:
    """Write irdrone_diagnostic_YYYYMMDD_HHMMSS.zip and return its path.
    ``checks``: results of selftests.run_checks already run (not run again)."""
    import config
    started = datetime.datetime.now()
    output = Path(output) if output else Path(config.OUTPUT_FOLDER_NAME)
    output.mkdir(parents=True, exist_ok=True)
    report = {"created": started.isoformat(timespec="seconds")}
    progress("Installation")
    report["installation"] = _safe(installation_report)
    progress("Self-tests")
    report["selftests"] = checks if checks else _safe(run_selftests, progress, quick=quick)
    work = Path(tempfile.mkdtemp(prefix="irdrone_diagnostic_"))
    try:
        samples = work / "images"
        samples.mkdir()
        if mission:
            mission = Path(mission)
            progress("Mission")
            report["mission"] = _safe(mission_summary, mission)
            report["sync_images"] = _safe(sync_images_check, mission, work / "develop", samples, develop, progress)
        report["verdicts"] = _verdicts(report)
        report["duration_s"] = round((datetime.datetime.now() - started).total_seconds(), 1)
        zip_path = output / started.strftime("irdrone_diagnostic_%Y%m%d_%H%M%S.zip")
        progress("Writing the zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("report.txt", _text(report))
            archive.writestr("report.json", json.dumps(report, indent=2, ensure_ascii=False, default=str))
            try:
                import session_log
                for log in session_log.recent_logs(3):
                    archive.write(log, f"logs/{log.name}")
            except Exception:
                pass
            if mission:
                for name in ("check_time_alignment.png", "check_time_before_alignment.png"):
                    path = Path(mission) / "Synchro" / name
                    if path.is_file():
                        archive.write(path, f"images/{name}")
            for path in sorted(samples.glob("*.jpg")):
                archive.write(path, f"images/{path.name}")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return zip_path


def main(argv=None):
    parser = argparse.ArgumentParser(description="IRDrone diagnostic report (zip to send).")
    parser.add_argument("mission", nargs="?", help="mission folder FLY-... (optional)")
    parser.add_argument("--output", help="folder of the zip (default: the working folder)")
    parser.add_argument("--no-develop", action="store_true",
                        help="do not develop the synchronisation images again (faster)")
    parser.add_argument("--quick", action="store_true",
                        help="self-tests without developing the sample images, no alignment (faster)")
    args = parser.parse_args(argv)
    if args.mission and not Path(args.mission).is_dir():
        parser.error(f"not a folder: {args.mission}")
    zip_path = create_report(args.mission, args.output, develop=not args.no_develop, quick=args.quick,
                             progress=lambda text: print(f"  {text}", flush=True))
    with zipfile.ZipFile(zip_path) as archive:
        text = archive.read("report.txt").decode("utf-8")
    print(text)
    print(f"Diagnostic report written: {zip_path}")
    print("Send this zip file to the IRDrone developers.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
