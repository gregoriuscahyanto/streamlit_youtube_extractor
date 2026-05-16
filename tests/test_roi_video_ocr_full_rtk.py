"""RTK checks for full video OCR evaluation when ROI data is already present."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_app_has_full_video_ocr_runner():
    txt = _read("app.py")
    assert "def _run_video_ocr_fullvideo_framewise_now(" in txt
    assert "video_path_override: str = \"\"" in txt
    assert "target_fps_str: str = \"2\"" in txt
    assert "_roi_ocr_probe_indices()" in txt
    assert "rois_active = list(rois_override if isinstance(rois_override, list)" in txt
    assert "capture_folder = str(capture_folder_override or \"\").strip()" in txt
    assert "vp_ovr = str(video_path_override or \"\").strip()" in txt
    assert "video_path = _find_local_fullfps_video(capture_folder)" in txt
    assert "find_tesseract_cmd()" in txt
    assert "_find_local_fullfps_video(" in txt
    assert "cap.read()" in txt
    assert '"table"' in txt and '"cleaned"' in txt
    assert 'def _save_ocr_progress(partial: bool) -> tuple[bool, str]:' in txt
    assert '_save_fields_to_local_json({"ocr": ocr_doc_local}, cf_local, base_rr=rr_doc_local)' in txt
    assert 'progress_cb(done_native, frame_count, t_s, dict(live_snapshot))' in txt
    assert 'frame_step = max(1, int(round(fps / target_fps)))' in txt
    assert 'for _ in range(max(0, frame_step - 1)):' in txt
    assert '"track_minimap_x"' in txt
    assert '"track_xy_x"' in txt
    assert '"track_pct"' in txt
    assert "H_fallback" in txt
    assert "cv2.findHomography" in txt


def test_video_ocr_full_tab_has_run_button_and_roi_guard():
    txt = _read("app_tabs/video_ocr_tab.py")
    assert '"Video OCR (voll, frame-by-frame) starten"' in txt
    assert '"OCR stoppen"' in txt
    assert "_run_video_ocr_fullvideo_framewise_now(" in txt
    assert "if not ocr_rois:" in txt
    assert "if capture_folder and full_video is None:" in txt
    assert "video_ocr_full_running" in txt
    assert "Live-Progress (OCR-Werte je Update" in txt
    assert "pd.DataFrame(live_rows)" in txt
    assert "video_ocr_full_stop_event" in txt
    assert "video_ocr_full_stop_requested" in txt
    assert "disabled=(not can_run) or running or stop_requested" in txt
    assert "OCR-Stop angefordert" in txt
    assert "rois_snapshot = [dict(r) for r in list(st.session_state.get(\"rois\") or []) if isinstance(r, dict)]" in txt
    assert "capture_folder_override=capture_folder_snapshot" in txt
    assert "video_path_override=full_video_snapshot" in txt
    assert "target_fps_str=target_fps_snapshot" in txt
