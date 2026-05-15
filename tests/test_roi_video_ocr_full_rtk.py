"""RTK checks for full video OCR evaluation when ROI data is already present."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_app_has_full_video_ocr_runner():
    txt = _read("app.py")
    assert "def _run_video_ocr_full_now() -> tuple[bool, str, dict]:" in txt
    assert "def _run_video_ocr_fullvideo_framewise_now(progress_cb=None, stop_cb=None) -> tuple[bool, str, dict]:" in txt
    assert "_roi_ocr_probe_indices()" in txt
    assert "find_tesseract_cmd()" in txt
    assert "_find_local_fullfps_video(" in txt
    assert "cap.read()" in txt
    assert '"table"' in txt and '"cleaned"' in txt
    assert '_save_recordresult_fields_to_r2_mat(' in txt
    assert 'replace_fields={"ocr": ocr_doc}' in txt


def test_video_ocr_full_tab_has_run_button_and_roi_guard():
    txt = _read("app_tabs/video_ocr_tab.py")
    assert '"Video OCR (voll, frame-by-frame) starten"' in txt
    assert "_run_video_ocr_fullvideo_framewise_now(" in txt
    assert "if not ocr_rois:" in txt
    assert "if capture_folder and full_video is None:" in txt
    assert "video_ocr_full_running" in txt
