"""RTK regression check: MAT table stays visible during running updates."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_running_update_disables_filters_and_shows_visibility_note():
    txt = (ROOT / "app_tabs" / "mat_selection_tab.py").read_text(encoding="utf-8")
    assert "_update_all_mat_overview_rows(_targets, live_table=table_slot, progress_slot=progress_slot)" in txt
    assert "Live-Update aktiv: Ampeln werden zeilenweise aktualisiert" in txt
    assert "show_live_run = bool(running_now or has_active_future or has_pending_run)" in txt
    assert "Analysefortschritt:" in txt
    assert "phase_slot = st.empty()" in txt
    assert "update_clicked = c1.button(" in txt
    assert "stop_clicked = c2.button(" in txt
    assert "if update_clicked:" in txt
    assert "if stop_clicked:" in txt
    assert "disabled=is_running_now" in txt
    assert "Update läuft: Filter sind temporär pausiert" in txt
    assert "if is_running_now:" in txt
    assert "if (not st.session_state.get(\"mat_overview_rows\")) and st.session_state.get(\"mat_update_keys\"):" in txt
    assert "table_slot.dataframe(" in txt
    assert "Live-Status je Zeile sichtbar" in txt
    assert "Live-Update aktiv:" in txt
    assert "mat-selection-disabled" not in txt
    assert "overview_rows = list(st.session_state.get(\"mat_overview_rows\") or [])" in txt
    assert "if (not overview_rows) and show_live_run and st.session_state.get(\"mat_update_keys\"):" in txt
