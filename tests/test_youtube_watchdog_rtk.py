"""RTK checks for Watchdog tab and YouTube watchdog automation runtime."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_watchdog_runtime_state_and_loop_exist():
    txt = _read("app_tabs/youtube_tab.py")
    assert "_YT_WATCHDOG_LOCK = threading.Lock()" in txt
    assert "_YT_WATCHDOG = {" in txt
    assert '"tasks": {' in txt
    assert '"mat_json": True' in txt
    assert '"download": True' in txt
    assert '"sync_lite": True' in txt
    assert '"ocr": True' in txt
    assert "def watchdog_snapshot() -> dict:" in txt
    assert 'def _wd_loop(stop_event, cfg: dict) -> None:' in txt
    assert 'def _wd_process_once(cfg: dict) -> bool:' in txt


def test_watchdog_tab_dashboard_controls_exist():
    txt = _read("app_tabs/watchdog_tab.py")
    assert '"Konvertierung MAT -> JSON"' in txt
    assert '"YouTube Download"' in txt
    assert '"Sync Voll <-> Lite"' in txt
    assert '"OCR Auswertung"' in txt
    assert '"Watchdog-Intervall (Sek.)"' in txt
    assert '"Watchdog starten"' in txt
    assert '"Watchdog stoppen"' in txt
    assert '"Watchdog-Log"' in txt
    assert 'fragment_fn = getattr(st, "fragment", None) or getattr(st, "experimental_fragment", None)' in txt
    assert "run_every = 0.4 if bool(_yt.watchdog_snapshot().get(\"running\")) else None" in txt
    assert 'st.session_state.yt_watchdog_task_mat_json' in txt
    assert 'st.session_state.yt_watchdog_task_download' in txt
    assert 'st.session_state.yt_watchdog_task_sync_lite' in txt
    assert 'st.session_state.yt_watchdog_task_ocr' in txt
    assert 'st.session_state.yt_watchdog_cmd = "start"' in txt
    assert 'st.session_state.yt_watchdog_cmd = "stop"' in txt


def test_watchdog_tab_is_registered_in_app_tabs():
    txt = _read("app.py")
    assert "watchdog_tab" in txt
    assert '"Watchdog"' in txt
    assert "watchdog_tab.render(globals())" in txt


def test_watchdog_runs_download_lite_and_ocr_pipeline():
    txt = _read("app_tabs/youtube_tab.py")
    assert "def _wd_convert_one_mat_to_json(" in txt
    assert "def _wd_sync_one_folder_lite(" in txt
    assert "_download_one(" in txt
    assert "_postprocess_lite_assets(" in txt
    assert "_wd_run_ocr(" in txt
    assert "_wd_ocr_pending(" in txt
    assert "task_mat_json" in txt
    assert "task_download" in txt
    assert "task_sync_lite" in txt
    assert "task_ocr" in txt
    assert 'st.session_state.setdefault("yt_watchdog_task_mat_json", True)' in txt
    assert 'st.session_state.setdefault("yt_watchdog_task_download", True)' in txt
    assert 'st.session_state.setdefault("yt_watchdog_task_sync_lite", True)' in txt
    assert 'st.session_state.setdefault("yt_watchdog_task_ocr", True)' in txt
    assert 'st.session_state.setdefault("yt_watchdog_cmd", "")' in txt
    assert '_wd_cmd == "start"' in txt
    assert '_wd_cmd == "stop"' in txt
