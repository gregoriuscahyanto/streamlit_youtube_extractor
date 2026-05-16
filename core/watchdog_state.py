"""Persistent watchdog state — intentionally NOT in the importlib.reload list.

app.py reloads all app_tabs modules on every Streamlit rerun. Any module-level
dict defined inside youtube_tab.py would therefore be reset on every rerun,
causing the watchdog thread to disappear. Keeping the state here prevents that.
"""
from __future__ import annotations

import threading

_YT_WATCHDOG_LOCK = threading.Lock()
_YT_WATCHDOG: dict = {
    "running": False,
    "thread": None,
    "stop_event": None,
    "interval_sec": 10,
    "last_tick": "",
    "current": "",
    "logs": [],
    "errors": 0,
    "downloads": 0,
    "ocr": 0,
    "mat_json": 0,
    "mat_json_skip": set(),
    "tasks": {
        "mat_json": True,
        "download": True,
        "ocr": True,
    },
}

# Cache for _rows_from_results_json: path -> (mtime, row_dict)
# Avoids re-reading large JSON files (with OCR tables) on every rerun.
_JSON_ROW_CACHE: dict[str, tuple[float, dict]] = {}

# Per-path write locks: str(path) -> threading.Lock()
# Watchdog acquires before writing; UI tries non-blocking and shows warning if locked.
_PATH_LOCKS: dict[str, threading.Lock] = {}
_PATH_LOCKS_REGISTRY_LOCK = threading.Lock()


def get_path_lock(path: str) -> threading.Lock:
    """Return the shared Lock for a given file path (created on first access)."""
    with _PATH_LOCKS_REGISTRY_LOCK:
        if path not in _PATH_LOCKS:
            _PATH_LOCKS[path] = threading.Lock()
        return _PATH_LOCKS[path]


def is_path_locked(path: str) -> bool:
    """Return True if the path is currently held by the watchdog."""
    with _PATH_LOCKS_REGISTRY_LOCK:
        lock = _PATH_LOCKS.get(path)
    if lock is None:
        return False
    acquired = lock.acquire(blocking=False)
    if acquired:
        lock.release()
        return False
    return True
