# -*- coding: utf-8 -*-
"""Copy of the console of each wizard session in a log file.

The wizard prints its messages (warnings of the steps, errors of the threads)
in the console window only: once closed, nothing was left to send when
something went wrong. ``start()`` copies stdout and stderr into
``<settings folder>/logs/irdrone_YYYYMMDD_HHMMSS.log`` (the console still
shows everything) and keeps the most recent logs only. The diagnostic report
(diagnostic.py) adds the last ones to its zip.

Kept free of heavy imports: started first thing by the wizard.
"""
import sys
import threading
import time
from pathlib import Path

KEEP_LOGS = 10
_started = None


def logs_folder() -> Path:
    import config
    return Path(config.SETTINGS_FILE).parent / "logs"


def recent_logs(count: int = 3):
    """The ``count`` most recent session logs, newest first."""
    folder = logs_folder()
    if not folder.is_dir():
        return []
    return sorted(folder.glob("irdrone_*.log"), reverse=True)[:count]


class _Tee:
    """Writes to the console stream and to the log file (one lock for both
    streams: the worker threads print too)."""

    def __init__(self, stream, log_file, lock):
        self.stream, self.log_file, self.lock = stream, log_file, lock

    def write(self, text):
        if self.stream is not None:
            try:
                self.stream.write(text)
            except (OSError, ValueError, UnicodeError):
                pass          # a console that cannot show a character never stops the wizard
        with self.lock:
            try:
                self.log_file.write(text)
                if "\n" in text:
                    self.log_file.flush()
            except (OSError, ValueError):
                pass
        return len(text)

    def flush(self):
        for target in (self.stream, self.log_file):
            try:
                if target is not None:
                    target.flush()
            except (OSError, ValueError):
                pass

    def isatty(self):
        return bool(self.stream is not None and getattr(self.stream, "isatty", lambda: False)())

    def __getattr__(self, name):
        return getattr(self.stream, name)


def start(folder: Path = None):
    """Start copying the console to a new log file; returns its path (None if
    the log cannot be written: the wizard runs anyway). Called once."""
    global _started
    if _started is not None:
        return _started
    try:
        folder = Path(folder) if folder else logs_folder()
        folder.mkdir(parents=True, exist_ok=True)
        old = sorted(folder.glob("irdrone_*.log"), reverse=True)[KEEP_LOGS - 1:]
        for path in old:
            try:
                path.unlink()
            except OSError:
                pass
        path = folder / time.strftime("irdrone_%Y%m%d_%H%M%S.log")
        log_file = open(path, "a", encoding="utf-8", errors="replace")
    except OSError:
        return None
    lock = threading.Lock()
    sys.stdout = _Tee(sys.stdout, log_file, lock)
    sys.stderr = _Tee(sys.stderr, log_file, lock)
    log_file.write(f"IRDrone session {time.strftime('%Y-%m-%d %H:%M:%S')}  Python {sys.version.split()[0]}  "
                   f"{sys.executable}\n")
    log_file.flush()
    _started = path
    return path
