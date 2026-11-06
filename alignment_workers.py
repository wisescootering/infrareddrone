# -*- coding: utf-8 -*-
"""Number of Step 4 alignment worker processes.

Kept free of heavy imports so the GUI can show the automatic value.
"""

import os

import psutil

# Peak memory of one alignment worker (RAM + swap) measured on full-resolution
# DJI / SJCam pairs: about 5.5 GB. Rounded up to keep a margin for the system.
ALIGNMENT_WORKER_MEMORY_GB = 6.0
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
