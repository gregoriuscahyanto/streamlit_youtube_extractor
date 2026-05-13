"""RTK check for pinned dependency versions in requirements."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_requirements_pin_pyarrow_19_0_1():
    txt = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "pyarrow==19.0.1" in txt
