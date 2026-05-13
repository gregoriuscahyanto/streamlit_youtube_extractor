"""RTK checks for pyarrow-safe fallback paths in tabs."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_app_exposes_pyarrow_presence_flag():
    txt = _read("app.py")
    assert 'HAS_PYARROW = importlib.util.find_spec("pyarrow") is not None' in txt
    assert "DeltaGenerator.dataframe = _delta_dataframe_no_pyarrow" in txt
    assert "st.dataframe = _st_dataframe_no_pyarrow" in txt


def test_sync_tab_has_dataframe_fallback_without_pyarrow():
    txt = _read("app_tabs/sync_tab.py")
    assert 'has_pyarrow = bool(globals().get("HAS_PYARROW", False))' in txt
    assert "if has_pyarrow:" in txt
    assert "table_slot.dataframe(" in txt


def test_roi_tab_has_readonly_fallback_without_pyarrow():
    txt = _read("app_tabs/roi_setup_tab.py")
    assert 'has_pyarrow = bool(globals().get("HAS_PYARROW", False))' in txt
    assert "if has_pyarrow:" in txt
    assert "ROI-Tabelle ist nur lesbar." in txt
