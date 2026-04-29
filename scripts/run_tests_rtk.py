"""Run pytest through RTK by default, with a safe fallback.

Usage:
  python scripts/run_tests_rtk.py
  python scripts/run_tests_rtk.py tests/test_harness_contract.py -q
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RTK_LOCAL = ROOT / "tools" / "rtk" / "rtk.exe"
PYTHON_VENV = ROOT / ".venv" / "Scripts" / "python.exe"


def _build_pytest_cmd(args: list[str]) -> str:
    if PYTHON_VENV.exists():
        py = str(PYTHON_VENV)
    else:
        py = sys.executable
    parts = [py, "-m", "pytest", *args]
    return subprocess.list2cmdline(parts)


def _find_rtk() -> str | None:
    if RTK_LOCAL.exists():
        return str(RTK_LOCAL)
    return shutil.which("rtk")


def main() -> int:
    args = sys.argv[1:]
    pytest_cmd = _build_pytest_cmd(args)
    rtk = _find_rtk()

    if rtk:
        wrapped = [rtk, "test", pytest_cmd]
        print(f"[run-tests] via RTK: {wrapped[0]} test <pytest>", flush=True)
        return subprocess.call(wrapped, cwd=str(ROOT))

    fallback = subprocess.list2cmdline([str(PYTHON_VENV if PYTHON_VENV.exists() else Path(sys.executable)), "-m", "pytest", *args])
    print("[run-tests] RTK not found, fallback to pytest.", flush=True)
    return subprocess.call(fallback, cwd=str(ROOT), shell=True)


if __name__ == "__main__":
    raise SystemExit(main())

