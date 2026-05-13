"""Regression for startup rendering: all tab modules are rendered via st.tabs."""

from pathlib import Path


def test_startup_uses_native_tabs_and_renders_all_modules():
    # Ensure startup uses Streamlit tabs and executes every tab renderer.
    src = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")

    assert "_tabs = st.tabs(_tab_labels)" in src
    assert "_render_main_navigation(_tab_labels)" not in src
    assert "segmented_control(" not in src
    assert 'with _tabs[0]:' in src
    assert 'with _tabs[1]:' in src
    assert 'with _tabs[2]:' in src
    assert 'with _tabs[3]:' in src
    assert 'with _tabs[4]:' in src
    assert "setup_tab.render(globals())" in src
    assert "sync_tab.render(globals())" in src
    assert "mat_selection_tab.render(globals())" in src
    assert "roi_setup_tab.render(globals())" in src
    assert "audio_tab.render(globals())" in src


def test_tab_renderers_define_startup_placeholders_without_dynamic_empty_slots():
    repo = Path(__file__).resolve().parents[1]
    roi_src = (repo / "app_tabs" / "roi_setup_tab.py").read_text(encoding="utf-8")
    mat_src = (repo / "app_tabs" / "mat_selection_tab.py").read_text(encoding="utf-8")
    sync_src = (repo / "app_tabs" / "sync_tab.py").read_text(encoding="utf-8")
    aud_src = (repo / "app_tabs" / "audio_tab.py").read_text(encoding="utf-8")

    assert "Kein Video geladen. Alle Komponenten sind vorbereitet" in roi_src
    assert 'key="roi_ph_start"' in roi_src
    assert 'key="roi_ph_end"' in roi_src
    assert 'key="roi_ph_pos"' in roi_src
    assert 'key="roi_ph_add"' in roi_src
    assert 'key="roi_ph_del"' in roi_src
    assert 'key="roi_ph_save"' in roi_src
    assert "2 · Track Analysis" in roi_src
    assert "3 · Vergleich / Ergebnisse" in roi_src
    assert 'key="roi_ph_track_load"' in roi_src
    assert 'key="roi_ph_track_reset"' in roi_src
    assert 'key="roi_ph_track_undo"' in roi_src
    assert 'key="roi_ph_hist_clear"' in roi_src
    assert "Frame aktuell nicht verfuegbar. Platzhalter wird angezeigt" in roi_src

    assert "Noch keine MAT analysiert." in mat_src
    assert "pd.DataFrame(" in mat_src
    assert "column_config=MAT_OVERVIEW_COLCFG" in mat_src
    assert "Auto-Analyse deaktiviert" in mat_src
    assert "if connected and mat_targets and st.session_state.mat_auto_updated_prefix != st.session_state.r2_prefix and not running:" not in mat_src
    assert "_mat_update_worker" in mat_src
    assert 'key="mat_stop_tab"' in mat_src
    assert '"Stop"' in mat_src
    assert "mat_request_rerun = False" in mat_src
    assert "if mat_request_rerun and st.session_state.get(\"mat_update_running\"):" in mat_src
    assert "if st.session_state.mat_update_running:\n            st.rerun()" not in mat_src
    assert "_mat_update_executor().submit(" in mat_src
    assert "mat_update_event_queue = queue.Queue()" in mat_src
    assert "mat_update_stop_event = threading.Event()" in mat_src

    assert "overall_progress_slot = st.container()" in sync_src
    assert "stage_slot = st.container()" in sync_src
    assert "table_slot = st.container()" in sync_src
    assert "st.empty()" not in sync_src

    assert "Analyse-Ergebnis (Platzhalter)" in aud_src
    assert 'key="aud_debug_zip_ph"' in aud_src
    assert 'key="aud_save_to_mat_ph"' in aud_src
