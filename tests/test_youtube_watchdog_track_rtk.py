"""RTK checks: watchdog OCR also evaluates track_minimap position."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_watchdog_ocr_extracts_track_cfg_and_writes_track_columns():
    txt = _read("app_tabs/youtube_tab.py")
    assert "def _wd_extract_track_cfg(doc: dict) -> dict:" in txt
    assert 'trk = ocr.get("trkCalSlim")' in txt
    assert '"track_minimap_x", "track_minimap_y", "track_xy_x", "track_xy_y", "track_pct"' in txt
    assert 'raw_cols.setdefault(_k, [])' in txt
    assert 'clean_cols.setdefault(_k, [])' in txt
    assert '_detect_moving_point = globals().get("detect_moving_point")' in txt
    assert '_compare_minimap = globals().get("compare_minimap_to_reference")' in txt
    assert 'cv2.findHomography' in txt


def test_watchdog_ocr_no_longer_skips_track_only_cases():
    txt = _read("app_tabs/youtube_tab.py")
    assert 'if not rois and (not has_track):' in txt
    assert 'if not rois and (not track_roi):' in txt
    assert 'return False, "keine OCR-ROIs/track_minimap"' in txt


def test_watchdog_ocr_reruns_when_expected_columns_are_missing():
    txt = _read("app_tabs/youtube_tab.py")
    assert "def _wd_expected_ocr_columns(doc: dict) -> tuple[list[str], list[str]]:" in txt
    assert "miss_tbl = [k for k in exp_cols if k not in table]" in txt
    assert "miss_cln = [k for k in exp_cols if k not in cleaned]" in txt
    assert 'return True, f"fehlende Spalten ({miss_info})"' in txt
    assert "_miss_tbl = [k for k in exp_cols if k not in existing_table]" in txt
    assert "_miss_cln = [k for k in exp_cols if k not in existing_cleaned]" in txt
    assert "fehlende Spalten erkannt -> kompletter Rebuild" in txt
