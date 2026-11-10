# -*- coding: utf-8 -*-
"""Number of Step 4 alignment worker processes.

Kept free of heavy imports so the GUI can show the automatic value.
"""

import os

import psutil

# Peak memory of one alignment worker (RAM + swap) measured on full-resolution
# DJI / SJCam pairs: about 5.5 GB. Rounded up to keep a margin for the system.
ALIGNMENT_WORKER_MEMORY_GB = 6.0
# A manual redo (wizard review) writes every diagnostic image at full
# resolution on top of that: estimated, with a margin. Running more redos than
# the RAM holds gets them killed by the system, mid-write.
REDO_WORKER_MEMORY_GB = 8.0
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
