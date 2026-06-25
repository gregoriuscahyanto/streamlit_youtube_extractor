"""RTK checks for Watchdog tab and YouTube watchdog automation runtime."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_watchdog_runtime_state_and_loop_exist():
    txt = _read("app_tabs/youtube_tab.py")
    assert "from core.watchdog_state import _YT_WATCHDOG, _YT_WATCHDOG_LOCK" in txt
    state_txt = _read("core/watchdog_state.py")
    assert '"tasks": {' in state_txt
    assert '"mat_json": True' in state_txt
    assert '"download": True' in state_txt
    assert '"ocr": True' in state_txt
    assert '"sync_lite": True' not in state_txt
    assert "def watchdog_snapshot() -> dict:" in txt
    assert 'def _wd_loop(stop_event, cfg: dict) -> None:' in txt
    assert 'def _wd_process_once(cfg: dict, stop_event=None) -> bool:' in txt


def test_watchdog_tab_dashboard_controls_exist():
    txt = _read("app_tabs/watchdog_tab.py")
    assert '"Konvertierung MAT -> JSON"' in txt or '"Konvertierung MAT â†’ JSON"' in txt or '"Konvertierung MAT → JSON"' in txt
    assert '"YouTube Download"' in txt
    assert '"OCR Auswertung"' in txt
    assert '"Watchdog-Intervall (Sek.)"' in txt
    assert '"Watchdog starten"' in txt
    assert '"Watchdog stoppen"' in txt
    assert '"Watchdog-Log (letzte 15 Einträge)"' in txt or '"Watchdog-Log"' in txt
    assert 'st.session_state.yt_watchdog_task_mat_json' in txt
    assert 'st.session_state.yt_watchdog_task_download' in txt
    assert 'st.session_state.yt_watchdog_task_ocr' in txt
    assert 'yt_watchdog_task_sync_lite' not in txt
    assert 'st.session_state.yt_watchdog_cmd = "start"' in txt
    assert 'st.session_state.yt_watchdog_cmd = "stop"' in txt


def test_watchdog_tab_is_registered_in_app_tabs():
    txt = _read("app.py")
    assert "watchdog_tab" in txt
    assert '"Watchdog"' in txt
    assert "watchdog_tab.render(globals())" in txt


def test_watchdog_runs_download_and_ocr_pipeline_without_lite_dependencies():
    txt = _read("app_tabs/youtube_tab.py")
    assert "def _wd_convert_one_mat_to_json(" in txt
    assert "_download_one(" in txt
    assert "_wd_run_ocr(" in txt
    assert "_wd_ocr_pending(" in txt
    assert "task_mat_json" in txt
    assert "task_download" in txt
    assert "task_ocr" in txt
    assert 'st.session_state.setdefault("yt_watchdog_task_mat_json", False)' in txt
    assert 'st.session_state.setdefault("yt_watchdog_task_download", False)' in txt
    assert 'st.session_state.setdefault("yt_watchdog_task_ocr", True)' in txt
    assert "_wd_lite_missing(" not in txt
    assert "_postprocess_lite_assets(" not in txt
    assert "task_sync_lite" not in txt
    assert 'yt_watchdog_task_sync_lite' not in txt
    assert 'st.session_state.setdefault("yt_watchdog_cmd", "")' in txt
    assert '_wd_cmd == "start"' in txt
    assert '_wd_cmd == "stop"' in txt


def test_watchdog_ocr_allows_private_results_without_youtube_url():
    """Private/local captures have no youtube_link; OCR must still be reachable."""
    txt = _read("app_tabs/youtube_tab.py")
    loop = txt[txt.index("        for row in rows_now:"):txt.index("        # ── Nachkorrektur")]

    assert 'if not link:\n                continue' not in loop
    assert "if task_download and link:" in loop
    assert "if task_ocr and need_ocr and folder not in ocr_skip_now:" in loop
    assert loop.index("if task_download and link:") < loop.index("if task_ocr and need_ocr and folder not in ocr_skip_now:")
