"""RTK checks for JSON-only read paths across MAT Selection, ROI Setup and Audio."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_app_uses_json_only_summary_for_remote_results():
    txt = _read("app.py")
    blk = txt[txt.index("def _compute_mat_summary_remote("):txt.index("def _compute_folder_only_summary(", txt.index("def _compute_mat_summary_remote("))]
    assert "JSON sidecar only (no MAT read)" in blk
    assert "JSON-Download:" in blk
    assert "JSON-Parse:" in blk
    assert "summarize_mat_file(" not in blk
    assert "_summarize_record_result_mat(" not in blk


def test_app_loads_selected_result_from_json_sidecar_not_mat():
    txt = _read("app.py")
    blk = txt[txt.index("def _load_mat_from_r2("):txt.index("def _apply_centerline_to_session(", txt.index("def _load_mat_from_r2("))]
    assert "JSON-only loader for MAT-selection entries" in blk
    assert "_r2_download_json_doc(_r2_json_sidecar_key(remote_key))" in blk
    assert "_recordresult_json_to_cfg(" in blk
    assert "config_from_mat_file(" not in blk
    assert "_extract_rois_from_recordresult_mat(" not in blk


def test_roi_setup_download_section_is_json_only():
    txt = _read("app_tabs/roi_setup_tab.py")
    assert "JSON (JSON-only)" in txt
    assert "JSON herunterladen" in txt
    assert "MAT herunterladen" not in txt
