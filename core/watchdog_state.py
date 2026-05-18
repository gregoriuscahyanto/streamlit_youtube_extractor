"""Persistent watchdog state — intentionally NOT in the importlib.reload list.

app.py reloads all app_tabs modules on every Streamlit rerun. Any module-level
dict defined inside youtube_tab.py would therefore be reset on every rerun,
causing the watchdog thread to disappear. Keeping the state here prevents that.
"""
from __future__ import annotations

import threading
from collections import deque, OrderedDict

_YT_WATCHDOG_LOCK = threading.Lock()
_YT_WATCHDOG: dict = {
    "running": False,
    "thread": None,
    "stop_event": None,
    "interval_sec": 10,
    "last_tick": "",
    "current": "",
    "logs": deque(maxlen=200),  # bounded — no manual slicing needed
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

# Per-path write locks — LRU-capped at 500 entries to prevent unbounded growth.
_PATH_LOCKS: "OrderedDict[str, threading.Lock]" = OrderedDict()
_PATH_LOCKS_REGISTRY_LOCK = threading.Lock()
_PATH_LOCKS_MAX = 500


def get_path_lock(path: str) -> threading.Lock:
    """Return the shared Lock for a given file path (LRU-capped dict)."""
    with _PATH_LOCKS_REGISTRY_LOCK:
        if path in _PATH_LOCKS:
            _PATH_LOCKS.move_to_end(path)  # mark as recently used
            return _PATH_LOCKS[path]
        lock = threading.Lock()
        _PATH_LOCKS[path] = lock
        if len(_PATH_LOCKS) > _PATH_LOCKS_MAX:
            _PATH_LOCKS.popitem(last=False)  # evict oldest
        return lock


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
