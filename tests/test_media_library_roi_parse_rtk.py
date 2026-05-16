"""RTK checks for ROI parsing in media library load flow."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_media_tab_parses_string_roi_from_json_columnar_table():
    txt = _read("app_tabs/media_tab.py")
    assert "def _parse_roi_table(roi_table) -> list[dict]:" in txt
    assert "def _coords_from_any(v) -> list[float]:" in txt
    assert 'txt.replace(",", " ").replace(";", " ").split()' in txt
    assert 'coords = coords_list[i] if i < len(coords_list) else []' in txt
    assert "x, y, w, h = _coords_from_any(coords)" in txt


def test_media_tab_load_uses_best_json_candidate_for_roi_data():
    txt = _read("app_tabs/media_tab.py")
    assert "def _json_candidates_for_folder() -> list[Path]:" in txt
    assert '_add(_base() / "results" / f"results_{folder}.json")' in txt
    assert '_add(Path("_temp") / f"results_{folder}.json")' not in txt
    assert "def _extract_roi_info(doc: dict) -> tuple[list[dict], int, int]:" in txt
    assert "if (n_ocr > best_n_ocr) or (n_ocr == best_n_ocr and n_all > best_n_all):" in txt
    assert "st.session_state[\"mat_selected_key\"] = best_path" in txt


def test_media_tab_load_handles_recordresult_and_roi_table_raw_fallbacks():
    txt = _read("app_tabs/media_tab.py")
    assert 'rr = doc.get("recordresult")' in txt
    assert 'ocr = rr.get("OCR")' in txt
    assert 'roi_src = ocr.get("roi_table")' in txt
    assert 'roi_src = ocr.get("roi_table_raw")' in txt


def test_media_tab_applies_loaded_rois_after_video_load_reset():
    txt = _read("app_tabs/media_tab.py")
    assert "_pending_rois: list[dict] = []" in txt
    assert "_apply_video() resets rois/t_start/t_end" in txt
    assert "if _pending_rois:" in txt
    assert "st.session_state.rois = _pending_rois" in txt


def test_media_tab_loads_track_calibration_from_trkCalSlim():
    txt = _read("app_tabs/media_tab.py")
    assert "trk = ocr.get(\"trkCalSlim\") if isinstance(ocr.get(\"trkCalSlim\"), dict) else {}" in txt
    assert "st.session_state.ref_track_pts = _pending_ref_pts" in txt
    assert "st.session_state.minimap_pts = _pending_minimap_pts" in txt
    assert "st.session_state.moving_pt_color_range = _pending_color_range" in txt
