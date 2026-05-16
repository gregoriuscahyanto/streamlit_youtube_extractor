"""RTK checks for watchdog-driven live OCR progress in Video OCR Full tab."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_video_ocr_tab_shows_watchdog_live_progress_and_values():
    txt = _read("app_tabs/video_ocr_tab.py")
    assert "def _watchdog_live_ocr_for_folder(folder: str, wd_cur: str)" in txt
    assert 'st.info(' in txt and 'Watchdog läuft automatisiert' in txt
    assert 'Watchdog OCR-Live:' in txt
    assert 'if wd_ocr_active and capture_folder:' in txt
    assert 'wd_prog, wd_rows, wd_json = _watchdog_live_ocr_for_folder(capture_folder, wd_current)' in txt
    assert 'live_rows = wd_rows if wd_rows else live_rows' in txt
    assert 'if running or _is_running() or wd_ocr_active:' in txt
    assert 'st.dataframe(pd.DataFrame(live_rows)' in txt
