"""RTK checks for compressed database selector in setup tab."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_setup_tab_has_compressed_db_dropdown_at_top():
    txt = _read("app_tabs/setup_tab.py")
    assert 'st.selectbox(' in txt
    assert '"Datenbank für komprimierte Dateien"' in txt
    assert '["Lokale Database (bevorzugt)", "R2 Database"]' in txt
    assert 'st.session_state.compressed_db_mode = new_mode' in txt


def test_app_has_compressed_storage_binding_helper():
    txt = _read("app.py")
    assert "def _sync_compressed_storage_binding():" in txt
    assert 'mode = str(st.session_state.get("compressed_db_mode") or "local")' in txt
    assert "if mode == \"local\":" in txt
    assert "st.session_state.r2_client = st.session_state.local_client" in txt
    assert "_sync_compressed_storage_binding()" in txt
