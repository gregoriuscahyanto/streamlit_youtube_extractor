"""RTK checks for manual Video OCR Full resume support."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_video_ocr_full_tab_exposes_resume_option():
    txt = _read("app_tabs/video_ocr_tab.py")
    assert 'st.session_state.setdefault("video_ocr_full_resume_enabled", True)' in txt
    assert 'resume_enabled = st.checkbox(' in txt
    assert 'key="video_ocr_full_resume_enabled"' in txt
    assert 'resume_enabled_snapshot = bool(resume_enabled)' in txt
    assert 'resume_enabled=resume_enabled_snapshot' in txt


def test_video_ocr_full_runner_can_resume_partial_json():
    txt = _read("app.py")
    assert 'resume_enabled: bool = True' in txt
    assert 'def _load_resume_rows() -> tuple[list[dict], list[dict], bool]:' in txt
    assert 'if not bool(_params.get("partial")):' in txt
    assert 'existing_mode = str(existing_ocr.get("fps_mode") or "").strip().lower()' in txt
    assert 'raw_rows, clean_rows, resumed = _load_resume_rows()' in txt
    assert 'resume_frame_idx = max(_start_frame, last_frame_idx + max(1, frame_step))' in txt
    assert '"resumed": bool(resumed),' in txt
    assert 'OCR fortgesetzt und vollstaendig ausgewertet' in txt
