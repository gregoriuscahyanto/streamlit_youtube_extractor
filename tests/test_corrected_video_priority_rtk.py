"""RTK checks for corrected GoPro video priority."""

from pathlib import Path


def test_find_local_video_prefers_gopro_corrected_file():
    txt = Path("app.py").read_text(encoding="utf-8")
    assert "def _find_local_fullfps_video(" in txt
    assert "_gopro_corrected_2fps" in txt
    assert "corrected_cands" in txt
    assert "return max(corrected_cands" in txt
