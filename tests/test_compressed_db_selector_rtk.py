"""RTK checks for compressed storage mode handling in setup tab."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_setup_tab_forces_local_compressed_mode_without_dropdown():
    txt = _read("app_tabs/setup_tab.py")
    assert "Datenbank für komprimierte Dateien" not in txt
    assert "setup_compressed_db_mode" not in txt
    assert 'st.session_state.compressed_db_mode = "local"' in txt


def test_app_has_compressed_storage_binding_helper():
    txt = _read("app.py")
    assert "def _sync_compressed_storage_binding():" in txt
    assert 'mode = str(st.session_state.get("compressed_db_mode") or "local")' in txt
    assert "if mode == \"local\":" in txt
    assert "st.session_state.r2_client = st.session_state.local_client" in txt
    assert "_sync_compressed_storage_binding()" in txt
