"""RTK regression checks for stable placeholder widgets across tabs."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_setup_tab_has_local_db_widgets():
    txt = _read("app_tabs/setup_tab.py")
    assert "Lokale DB" in txt
    assert "Ordner waehlen (lokal)" in txt
    assert 'key="local_pick_btn"' in txt
    assert "Lokaler Basispfad:" in txt


def test_sync_tab_uses_single_stable_table_widget_key():
    txt = _read("app_tabs/sync_tab.py")
    assert txt.count('key="sync_single_table"') == 1
    assert "data_editor(" in txt


def test_mat_selection_tab_keeps_table_slot_for_empty_filter_result():
    txt = _read("app_tabs/mat_selection_tab.py")
    assert "filter_info_slot = st.empty()" in txt
    assert "table_slot.dataframe(" in txt
    assert "Keine Fälle passend zum aktuellen Filter." in txt


def test_audio_tab_has_no_media_placeholder_block():
    txt = _read("app_tabs/audio_tab.py")
    assert "if not _has_media_source():" in txt
    assert 'key="aud_ph_start"' in txt
