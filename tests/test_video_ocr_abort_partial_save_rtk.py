"""RTK checks for abort/partial save logic in Video OCR Full (watchdog-like)."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_video_ocr_full_abort_saves_partial_params():
    txt = _read("app.py")
    assert 'def _save_ocr_progress(partial: bool) -> tuple[bool, str]:' in txt
    assert '_params["start_s"] = float(_start_s)' in txt
    assert '_params["end_s"] = float(_end_s)' in txt
    assert '_params["partial"] = True' in txt
    assert '_params.pop("partial", None)' in txt
    assert 'ok_save, msg_save = _save_ocr_progress(partial=bool(cancelled))' in txt
    assert '"partial": bool(cancelled),' in txt


def test_video_ocr_full_has_periodic_checkpoint_saves_like_watchdog():
    txt = _read("app.py")
    assert 'processed_target = max(1, int(math.ceil(frames_in_range / max(1, frame_step))))' in txt
    assert 'checkpoint_interval_s = float(_tpo.get("checkpoint_interval_s") or st.session_state.get("video_ocr_full_checkpoint_interval_s") or 30.0)' in txt
    assert 'next_checkpoint_at = time.perf_counter() + checkpoint_interval_s' in txt
    assert 'if time.perf_counter() >= next_checkpoint_at:' in txt
    assert 'next_checkpoint_at = time.perf_counter() + checkpoint_interval_s' in txt
    assert '_ok_ckpt, _msg_ckpt = _save_ocr_progress(partial=True)' in txt


def test_video_ocr_full_stop_requests_force_partial_save():
    txt = _read("app.py")
    assert 'if bool(stop_cb()):' in txt
    assert '_ok_stop, _msg_stop = _save_ocr_progress(partial=True)' in txt
    assert 'save_error = str(_msg_stop)' in txt
    assert 'cancelled = True' in txt
    assert 'break' in txt
