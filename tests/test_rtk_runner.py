import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_run_tests_rtk_executes_target_suite():
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run_tests_rtk.py"), "tests/test_harness_contract.py", "-q"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    assert "passed" in combined.lower()
