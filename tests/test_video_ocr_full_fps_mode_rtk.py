"""RTK checks for Video OCR Full FPS mode selector."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_video_ocr_full_tab_has_fps_selector_default_2():
    txt = _read("app_tabs/video_ocr_tab.py")
    assert 'st.session_state.setdefault("video_ocr_full_target_fps", "2")' in txt
    assert '_fps_options = ["10", "5", "2", "1", "max"]' in txt
    assert '"10": "10 fps"' in txt
    assert '"5": "5 fps"' in txt
    assert '"2": "2 fps (Standard)"' in txt
    assert '"1": "1 fps"' in txt
    assert '"max": "max (native fps)"' in txt
    assert 'fps_mode = st.selectbox(' in txt
    assert 'key="video_ocr_full_target_fps"' in txt


def test_video_ocr_full_runner_accepts_target_fps_and_persists_mode():
    txt = _read("app.py")
    assert 'target_fps_str: str = "2"' in txt
    assert 'fps_mode = str(target_fps_str or "2").strip().lower()' in txt
    assert 'if fps_mode == "max":' in txt
    assert 'target_fps = float(fps_mode)' in txt
    assert 'frame_step = max(1, int(round(fps / target_fps)))' in txt
    assert 'ocr_doc_local["fps_mode"] = str(fps_mode)' in txt
    assert 'ocr_doc_local["frame_step"] = int(max(1, frame_step))' in txt
    assert '"fps_mode": str(fps_mode),' in txt
    assert '"frame_step": int(max(1, frame_step)),' in txt
