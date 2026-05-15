"""RTK checks for audio_rpm processed columnar JSON sidecar output."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_normalizer_builds_processed_col_from_processed_rows():
    txt = _read("app.py")
    assert "processed_col" in txt
    assert "def _normalize_sidecar_json_payload(obj):" in txt
    assert "_build_columnar_from_row_list" in txt
    assert '_to_float(v) if not _is_missing(v) else float("nan")' in txt


def test_mat_to_json_tab_normalizes_output_after_conversion():
    txt = _read("app_tabs/mat_to_json_tab.py")
    assert "def _normalize_json_bytes(json_bytes: bytes) -> bytes:" in txt
    assert 'norm = globals().get("_normalize_sidecar_json_payload")' in txt
    assert "return True, _normalize_json_bytes(bytes(fixed))" in txt
    assert "return True, _normalize_json_bytes(fixed_fb)" in txt
    assert "return True, _normalize_json_bytes(fixed_data)" in txt
