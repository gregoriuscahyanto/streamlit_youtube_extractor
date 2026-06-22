"""RTK checks for watchdog-driven live OCR progress in Video OCR Full tab."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_video_ocr_tab_shows_watchdog_live_progress_and_values():
    txt = _read("app_tabs/video_ocr_tab.py")
    assert "def _watchdog_live_ocr_for_folder(folder: str, wd_cur: str)" in txt
    assert 'st.info(' in txt and 'Watchdog läuft automatisiert' in txt
    assert 'elif wd_ocr_running:' in txt
    assert '_wd_live_folder_hint = str((wd_snap.get("ocr_live") or {}).get("folder") or "")' in txt
    assert 'if _wd_ocr:' in txt
    assert '_live = dict(_snap.get("ocr_live") or {})' in txt
    assert '_wd_rows = list(_live.get("rows") or [])' in txt
    assert '_df = pd.DataFrame(_rows)' in txt
