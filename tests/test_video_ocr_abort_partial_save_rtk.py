"""RTK checks for abort/partial save logic in Video OCR Full (watchdog-like)."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_video_ocr_full_abort_saves_partial_params():
    txt = _read("app.py")
    assert 'def _save_ocr_progress(partial: bool) -> tuple[bool, str]:' in txt
    assert '_params.setdefault("start_s", 0.0)' in txt
    assert '_params["end_s"] = float(raw_rows[-1]["time_s"]) if raw_rows else 0.0' in txt
    assert '_params["partial"] = True' in txt
    assert '_params.pop("partial", None)' in txt
    assert 'ok_save, msg_save = _save_ocr_progress(partial=bool(cancelled))' in txt
    assert '"partial": bool(cancelled),' in txt


def test_video_ocr_full_has_periodic_checkpoint_saves_like_watchdog():
    txt = _read("app.py")
    assert 'processed_target = max(1, int(math.ceil(frame_count / max(1, frame_step))))' in txt
    assert 'checkpoint_every = max(1, processed_target // 10)' in txt
    assert 'if processed % checkpoint_every == 0:' in txt
    assert '_ok_ckpt, _msg_ckpt = _save_ocr_progress(partial=True)' in txt
