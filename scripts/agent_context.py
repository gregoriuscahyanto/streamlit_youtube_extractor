"""Print a compact repository map for agent runs.

The output is intentionally small: it points to durable sources of truth without
forcing future agents to spend context on large implementation files.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

KEY_DOCS = [
    "AGENTS.md",
    "ARCHITECTURE.md",
    "docs/CONTEXT.md",
    "docs/PRODUCT.md",
    "docs/QUALITY.md",
    "docs/RELIABILITY.md",
    "docs/SECURITY.md",
    "docs/STATE_KEYS.md",
    "docs/DECISIONS.md",
]

APP_AREAS = [
    ("Shell/navigation/session defaults", "app.py"),
    ("Cloud connection", "app_tabs/setup_tab.py"),
    ("Local/cloud sync", "app_tabs/sync_tab.py"),
    ("MAT selection/status", "app_tabs/mat_selection_tab.py"),
    ("ROI editing", "app_tabs/roi_setup_tab.py"),
    ("Track calibration/analysis", "app_tabs/track_analysis_tab.py"),
    ("Audio RPM analysis", "app_tabs/audio_tab.py"),
    ("MAT/JSON backend helpers", "backend.py"),
]

TEST_COMMANDS = [
    "python scripts/harness_lint.py",
    "python scripts/agent_context.py",
    "python scripts/run_tests_rtk.py",
    "python -m py_compile app.py app_tabs/setup_tab.py app_tabs/sync_tab.py app_tabs/mat_selection_tab.py app_tabs/roi_setup_tab.py app_tabs/track_analysis_tab.py app_tabs/audio_tab.py",
]


def _status(rel: str) -> str:
    path = ROOT / rel
    if not path.exists():
        return "missing"
    if path.is_dir():
        return "dir"
    return f"{path.stat().st_size} bytes"


def main() -> int:
    print("streamlit_youtube_extractor agent context")
    print()
    print("Key docs:")
    for rel in KEY_DOCS:
        print(f"- {rel} ({_status(rel)})")
    print()
    print("Application areas:")
    for label, rel in APP_AREAS:
        print(f"- {label}: {rel} ({_status(rel)})")
    print()
    print("Preferred checks:")
    for cmd in TEST_COMMANDS:
        print(f"- {cmd}")
    print()
    print("Do not read by default: logs/, results/, r2_mount/, .venv/, *.mat, generated JSON outputs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
