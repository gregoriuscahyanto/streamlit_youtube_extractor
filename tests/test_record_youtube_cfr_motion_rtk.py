"""RTK checks for robust playback-motion detection in record_youtube_cfr.py."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_motion_detection_uses_multi_roi_builder():
    txt = _read("scripts/record_youtube_cfr.py")
    assert "def _build_motion_rois(rect):" in txt
    assert "return [" in txt[txt.index("def _build_motion_rois(rect):"):txt.index("def wait_for_playback_motion(")]
    assert "center" in txt
    assert "lower_left" in txt or "hud" in txt


def test_wait_for_motion_uses_adaptive_threshold_and_multi_roi_votes():
    txt = _read("scripts/record_youtube_cfr.py")
    block = txt[txt.index("def wait_for_playback_motion("):txt.index("# ===================== Mux mit ffmpeg (optional) =====================")]
    assert "rois = _build_motion_rois(rect)" in block
    assert "noise_floor" in block
    assert "dyn_thresh" in block
    assert "moving_rois >= 2" in block
    assert "safe_sleep(0.10)" in block


def test_ensure_playing_uses_fullframe_fallback_and_robust_toggle():
    txt = _read("scripts/record_youtube_cfr.py")
    assert "def _press_play_toggle_robust(" in txt
    blk = txt[txt.index("def _press_play_toggle_robust"):txt.index("def ensure_playing(")]
    assert "attempt_idx" in blk
    assert "if int(attempt_idx) % 2 == 0" in blk
    assert "key('space')" in blk
    assert "key('k')" in blk
    block = txt[txt.index("def ensure_playing("):txt.index("def wait_for_playback_motion(")]
    assert "_press_play_toggle_robust(i)" in block
    assert "wait_for_playback_motion_fullframe(" in block


def test_script_supports_new_window_and_other_display_flags():
    txt = _read("scripts/record_youtube_cfr.py")
    assert '--new-window' in txt
    assert '--other-display' in txt
    assert "new_window=bool(args.new_window)" in txt
    assert "move_to_other_display=bool(args.other_display)" in txt
    assert "key(['alt', 'tab'])" not in txt


def test_script_prefers_wasapi_loopback_then_stereomix():
    txt = _read("scripts/record_youtube_cfr.py")
    assert "sd.WasapiSettings(loopback=True)" in txt
    assert 'mode = "WASAPI loopback" if use_loopback else "input capture"' in txt
    assert "Kein echtes Audio-Capture verfuegbar" in txt
    assert "_try_start_audio" in txt


def test_capture_is_armed_before_async_playback_start():
    txt = _read("scripts/record_youtube_cfr.py")
    main_block = txt[txt.index("# 3) Sync & Start"):txt.index("# 4) Stop & Dateien schreiben")]
    assert "sync_countdown()" in main_block
    assert "key('0')" in main_block
    assert "audio.trigger()" in main_block
    assert "threading.Thread(target=_start_playback_worker, daemon=True)" in main_block
    assert "video.trigger(record_duration)" in main_block
