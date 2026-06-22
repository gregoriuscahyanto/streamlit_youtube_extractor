"""RTK checks for denser OCR live progress updates and persistent track minimap columns."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_full_video_ocr_progress_updates_are_dense():
    txt = _read("app.py")
    assert 'video_ocr_live_progress_step_frames' in txt
    assert 'processed <= 3 or processed % progress_step == 0 or done_native >= total_native' in txt


def test_full_video_ocr_track_columns_are_always_present_in_live_snapshot():
    txt = _read("app.py")
    assert 'for _k in ("track_minimap_x", "track_minimap_y", "track_xy_x", "track_xy_y", "track_pct"):' in txt
    assert 'clean_row[_k] = np.nan' in txt
    assert 'live_snapshot[_k] = np.nan' in txt
    assert 'clean_row["track_minimap_found"] = 0' in txt
    assert 'live_snapshot["track_minimap_found"] = 0' in txt
    assert 'clean_row["track_minimap_found"] = 1' in txt
    assert 'live_snapshot["track_minimap_found"] = 1' in txt
