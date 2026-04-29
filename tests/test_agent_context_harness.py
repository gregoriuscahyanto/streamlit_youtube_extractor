import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_agent_context_script_is_compact_and_points_to_docs():
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "agent_context.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    out = proc.stdout
    assert "AGENTS.md" in out
    assert "ARCHITECTURE.md" in out
    assert "app_tabs/roi_setup_tab.py" in out
    assert "Do not read by default" in out
    assert len(out.splitlines()) < 80
