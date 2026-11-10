# -*- coding: utf-8 -*-
"""Archives of a manual redo (automatic_registration.py --redo).

Before the redo, the outputs of the point are moved to
``VIS_N_align_traces_manual/original`` (the .exif sidecar is copied: it is an
input); after a failed redo they are put back. Kept free of heavy imports: the
wizard restores a point itself when the redo process was killed.
"""

import json
import os
import shutil
import time
from pathlib import Path

ALIGNED_TRACES = ("vir", "nir", "ndvi")
# In the trace folder while a redo runs: a redo that never removed it was
# interrupted (process or computer killed), its point is restored on the next
# review or redo.
REDO_MARKER = "REDO_IN_PROGRESS.json"


def _manual_redo_result_names(vis_pth):
    image_number = Path(vis_pth).stem.removeprefix("VIS_")
    names = [
        f"VIS_{image_number}.jpg",
        f"VIS_{image_number}_motion_model.npy",
        f"VIS_{image_number}_motion_model.json",
    ]
    for trace in ALIGNED_TRACES:
        names.extend(
            f"{trace.upper()}_{image_number}_{mode}.jpg"
            for mode in ("local", "global")
        )
    names.extend(
        f"IRD_{image_number}_{band}.tif"
        for band in range(1, 5)
    )
    names.append(f"IRD_{image_number}_1.exif")
    return names


def _archive_destination(source, archive_dir):
    destination = archive_dir / source.name
    index = 1
    while destination.exists():
        destination = archive_dir / f"{source.stem}_{index}{source.suffix}"
        index += 1
    return destination


def _move_to_archive(source, archive_dir):
    source = Path(source)
    destination = _archive_destination(source, archive_dir)
    shutil.move(str(source), str(destination))
    return destination


def _copy_to_archive(source, archive_dir):
    source = Path(source)
    destination = _archive_destination(source, archive_dir)
    shutil.copy2(source, destination)
    return destination


def _archived_versions(archive_dir, name):
    """Archived copies of ``name``, oldest first (``name``, ``stem_1``, ...)."""
    name = Path(name)
    versions = []
    candidate = Path(archive_dir) / name.name
    index = 1
    while candidate.is_file():
        versions.append(candidate)
        candidate = Path(archive_dir) / f"{name.stem}_{index}{name.suffix}"
        index += 1
    return versions


def restore_manual_redo_originals(
    vis_pth, out_dir, multispectral_folder, original_dir, since=None
):
    """After a failed redo (an error, or the process killed, e.g. out of
    memory): the point goes back to its state before the redo. Every
    deliverable is replaced by its last archived version, also one the redo
    did write (it may be cut short); with ``since`` (redo start time), a file
    written by the redo with no archived version is removed. The .exif
    sidecar is never removed. Returns the restored paths."""
    out_dir = Path(out_dir)
    original_dir = Path(original_dir)
    restored = []
    for name in _manual_redo_result_names(vis_pth):
        if name.startswith("IRD_"):
            if multispectral_folder is None:
                continue
            target = Path(multispectral_folder) / name
        else:
            target = out_dir / name
        is_sidecar = name.endswith(".exif")
        versions = _archived_versions(original_dir, name)
        if is_sidecar:
            # Never rewritten by a redo: put back only if missing.
            if not target.is_file() and versions:
                shutil.copy2(versions[0], target)
                restored.append(target)
            continue
        if versions:
            shutil.copy2(versions[-1], target)
            restored.append(target)
        elif since is not None and target.is_file() and target.stat().st_mtime >= since - 1.0:
            target.unlink()
    (original_dir.parent / REDO_MARKER).unlink(missing_ok=True)
    return restored


def _redo_alive(pid) -> bool:
    """A redo process ``pid`` still runs (not a recycled pid)."""
    try:
        import psutil
        if not isinstance(pid, int) or pid == os.getpid() or not psutil.pid_exists(pid):
            return False
        return any("automatic_registration" in part for part in psutil.Process(pid).cmdline())
    except Exception:
        return False


def recover_interrupted_redo(debug_dir):
    """Restore the point of a redo interrupted in ``debug_dir`` (its marker is
    there, its process gone). Returns the restored paths ([] if nothing to do)."""
    debug_dir = Path(debug_dir)
    marker = debug_dir / REDO_MARKER
    if not marker.is_file():
        return []
    try:
        info = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        info = None
    if not isinstance(info, dict) or not isinstance(info.get("vis"), str) \
            or not isinstance(info.get("out_dir"), str):
        marker.unlink(missing_ok=True)      # unreadable: nothing reliable to restore from
        return []
    if _redo_alive(info.get("pid")):
        return []
    started = info.get("started")
    return restore_manual_redo_originals(
        info["vis"], info["out_dir"], info.get("multispectral_folder"),
        debug_dir / "original",
        since=float(started) if isinstance(started, (int, float)) else None,
    )


def recover_interrupted_redos(out_dir) -> dict:
    """Every interrupted redo of the output folder restored:
    ``{trace folder name: restored paths}``."""
    recovered = {}
    for marker in sorted(Path(out_dir).glob(f"*_align_traces_manual/{REDO_MARKER}")):
        restored = recover_interrupted_redo(marker.parent)
        if not marker.exists():
            recovered[marker.parent.name] = restored
    return recovered


def prepare_manual_redo_archives(vis_pth, out_dir, multispectral_folder=None):
    """Preserve existing REDO outputs and clear stale diagnostics before rerunning."""
    vis_pth = Path(vis_pth)
    out_dir = Path(out_dir)
    debug_dir = out_dir / f"{vis_pth.stem}_align_traces_manual"
    tech_dir = debug_dir / "Tech"
    original_dir = debug_dir / "original"
    debug_dir.mkdir(parents=True, exist_ok=True)
    tech_dir.mkdir(exist_ok=True)
    original_dir.mkdir(exist_ok=True)
    # An earlier redo of this point interrupted: back to its state before,
    # or its cut-short files would be archived as the previous alignment.
    recover_interrupted_redo(debug_dir)

    for existing in debug_dir.iterdir():
        if existing not in (tech_dir, original_dir):
            _move_to_archive(existing, tech_dir)
    (debug_dir / REDO_MARKER).write_text(json.dumps({
        "vis": os.fspath(vis_pth),
        "out_dir": os.fspath(out_dir),
        "multispectral_folder": None if multispectral_folder is None else os.fspath(multispectral_folder),
        "started": time.time(),
        "pid": os.getpid(),
    }), encoding="utf-8")

    image_number = vis_pth.stem.removeprefix("VIS_")
    original_names = _manual_redo_result_names(vis_pth)
    original_names.remove(f"VIS_{image_number}_motion_model.npy")
    exif_name = f"IRD_{image_number}_1.exif"
    original_names.remove(exif_name)
    archived_exif = None
    if multispectral_folder is not None:
        # The sidecar is an input of the redo (georeferencing), not regenerated:
        # it stays in place, a copy is kept. A redo that died earlier may have
        # left it only in the archive: put it back.
        sidecar = Path(multispectral_folder) / exif_name
        if not sidecar.is_file():
            previous = _archived_versions(original_dir, exif_name)
            if previous:
                shutil.copy2(previous[0], sidecar)
        if sidecar.is_file():
            archived_exif = _copy_to_archive(sidecar, original_dir)
    for name in original_names:
        if name.startswith("IRD_"):
            if multispectral_folder is None:
                continue
            source_dir = Path(multispectral_folder)
        else:
            source_dir = out_dir
        source = source_dir / name
        if source.is_file():
            _move_to_archive(source, original_dir)

    motion_model = out_dir / f"VIS_{image_number}_motion_model.npy"
    if motion_model.is_file():
        _move_to_archive(motion_model, original_dir)
    return debug_dir, original_dir, archived_exif


def finalize_manual_redo_archives(
    vis_pth, out_dir, multispectral_folder, debug_dir, archived_exif
):
    """Copy the regenerated deliverables into the trace folder and file diagnostics."""
    vis_pth = Path(vis_pth)
    out_dir = Path(out_dir)
    debug_dir = Path(debug_dir)
    image_number = vis_pth.stem.removeprefix("VIS_")

    if archived_exif is not None and multispectral_folder is not None:
        sidecar = Path(multispectral_folder) / f"IRD_{image_number}_1.exif"
        shutil.copy2(archived_exif, sidecar)

    result_names = _manual_redo_result_names(vis_pth)
    result_paths = [
        (Path(multispectral_folder) if name.startswith("IRD_") else out_dir) / name
        for name in result_names
        if not name.startswith("IRD_") or multispectral_folder is not None
    ]

    archived_names = set(result_names)
    tech_dir = debug_dir / "Tech"
    try:
        for result in result_paths:
            if not result.is_file():
                raise FileNotFoundError(f"Expected REDO output was not created: {result}")
            shutil.copy2(result, debug_dir / result.name)
        (debug_dir / REDO_MARKER).unlink(missing_ok=True)     # the redo is complete
    finally:
        for item in debug_dir.iterdir():
            if item.name in ("Tech", "original", REDO_MARKER) or item.name in archived_names:
                continue
            _move_to_archive(item, tech_dir)
