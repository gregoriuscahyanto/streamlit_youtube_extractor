"""RTK checks that partial Video OCR saves keep the original target end time."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_partial_save_keeps_original_end_s_for_resume():
    # Resume must preserve the target window instead of shrinking it to progress time.
    txt = _read("app.py")
    assert '_params["end_s"] = float(_end_s)' in txt
    assert '_params["start_s"] = float(_start_s)' in txt
    assert '_params["partial"] = True' in txt
    assert '_params.pop("partial", None)' in txt
    assert 'resume_frame_idx = max(_start_frame, last_frame_idx + max(1, frame_step))' in txt
