# -*- coding: utf-8 -*-
"""Number of Step 4 alignment worker processes.

Kept free of heavy imports so the GUI can show the automatic value.
"""

import os

import psutil

# Peak memory of one alignment worker measured on full-resolution DJI / SJCam
# pairs: about 2.3 GB for Python (images in float32), or 1.8 GB for RawTherapee
# while it converts an image for a worker that then holds about 0.6 GB.
# Rounded up to keep a margin for the system.
ALIGNMENT_WORKER_MEMORY_GB = 3.0
# A manual redo (wizard review) is one alignment in its own process (2.4 GB
# measured); with the "Debug" log detail it also writes every diagnostic image
# at full resolution (4.4 GB measured). Running more redos than the RAM holds
# gets them killed by the system, mid-write.
REDO_WORKER_MEMORY_GB = 3.0
REDO_DIAGNOSTICS_WORKER_MEMORY_GB = 5.0
# concurrent.futures.ProcessPoolExecutor refuses more than 61 workers on Windows.
MAX_WORKERS = 61 if os.name == "nt" else 1024


def clamp_workers(value: int) -> int:
    """Keep a requested worker count within what the platform supports."""
    return max(1, min(int(value), MAX_WORKERS))


def available_alignment_workers(
    memory_per_worker_gb: float = ALIGNMENT_WORKER_MEMORY_GB,
) -> int:
    """Physical CPU cores, limited by the available RAM; never less than one."""
    cores = psutil.cpu_count(logical=False) or 1
    available_gb = psutil.virtual_memory().available / 2**30
    memory_limit = int(available_gb // memory_per_worker_gb)
    return clamp_workers(min(cores, memory_limit))


def threads_per_worker(worker_count: int) -> int:
    """Threads each of ``worker_count`` alignment workers may use for its image
    operations (OpenCV): the physical cores shared between the workers."""
    cores = psutil.cpu_count(logical=False) or 1
    return max(1, cores // max(1, int(worker_count)))


def rawtherapee_threads_per_worker(worker_count: int) -> int:
    """Threads of a RawTherapee conversion started by one of ``worker_count``
    alignment workers: its share of the cores, at least 2 (a conversion is a
    short part of an alignment: with 2 threads it takes hardly more CPU than
    with 1 and half the time; measured best on 4 cores with 3 workers)."""
    cores = psutil.cpu_count(logical=False) or 1
    return min(cores, max(2, threads_per_worker(worker_count)))


def memory_fitting_workers(requested: int, memory_per_worker_gb: float) -> int:
    """``requested`` lowered to what the available RAM holds (never less than
    one); ``memory_per_worker_gb`` <= 0: no memory limit."""
    requested = clamp_workers(requested)
    if memory_per_worker_gb <= 0:
        return requested
    available_gb = psutil.virtual_memory().available / 2**30
    return clamp_workers(min(requested, int(available_gb // memory_per_worker_gb)))


def worker_count_report(
    worker_count: int,
    memory_per_worker_gb: float = ALIGNMENT_WORKER_MEMORY_GB,
) -> list:
    """Lines for the Step 4 log: workers used, what the computer allows, advice.

    Each worker needs about ``memory_per_worker_gb``: more workers than the
    available RAM allows make the computer swap, and a run can get slower.
    """
    cores = psutil.cpu_count(logical=False) or 1
    available_gb = psutil.virtual_memory().available / 2**30
    fitting = max(1, int(available_gb // memory_per_worker_gb))
    best = clamp_workers(min(cores, fitting))
    lines = [
        f"Alignment workers: {worker_count} "
        f"({cores} physical cores, {available_gb:.1f} GB RAM available, "
        f"about {memory_per_worker_gb:g} GB per worker: {best} recommended)."
    ]
    if worker_count > fitting:
        lines.append(
            f"WARNING: {worker_count} workers need about "
            f"{worker_count * memory_per_worker_gb:g} GB of RAM: the computer may "
            "swap and the run be slower. Lower the number of workers in the "
            "Step 4 settings (gear button) or close other programs."
        )
    elif worker_count < best:
        lines.append(
            f"Up to {best} workers would fit on this computer: "
            "the number of workers can be raised in the Step 4 settings (gear button)."
        )
    return lines
