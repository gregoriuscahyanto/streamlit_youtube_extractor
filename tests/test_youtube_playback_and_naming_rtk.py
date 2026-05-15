"""RTK checks for stable playback start and target media naming."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_tab_passes_screen_audio_stem_to_recorder():
    txt = _read("app_tabs/youtube_tab.py")
    assert "def _capture_media_stem(folder: str) -> str:" in txt
    assert 'return f"screen_{folder}_audio"' in txt
    assert "--out" in txt
    assert "_capture_media_stem(folder)" in txt
    assert '"capture"' not in txt[txt.index("def _download_one("):txt.index("def _status_lamp(")]


def test_recorder_builds_direct_audio_video_names_for_audio_stem():
    txt = _read("scripts/record_youtube_cfr.py")
    assert "def build_output_paths(outdir: str, base: str) -> tuple[str, str, str]:" in txt
    blk = txt[txt.index("def build_output_paths"):txt.index("# ===================== Main =====================")]
    assert 'if b.endswith("_audio"):' in blk
    assert 'audio_wav = os.path.join(outdir, f"{b}.wav")' in blk
    assert 'out_mux = os.path.join(outdir, f"{b}.avi")' in blk
    assert 'video_tmp = os.path.join(outdir, f"{b}_video_tmp.avi")' in blk


def test_playback_worker_uses_single_toggle_attempt_to_avoid_repause():
    txt = _read("scripts/record_youtube_cfr.py")
    main_block = txt[txt.index("def _start_playback_worker():"):txt.index("play_thread = threading.Thread")]
    assert "ensure_playing(max_tries=1, motion_timeout=8.0)" in main_block
    assert "max_tries=4" not in main_block


def test_duration_detection_uses_plausible_candidates_and_no_fixed_60s_fallback():
    txt = _read("scripts/record_youtube_cfr.py")
    blk = txt[txt.index("def get_youtube_duration(url):"):txt.index("def get_youtube_publish_date(url):")]
    assert "html_txt = fetch_html(url)" in blk
    assert 're.findall(r\'\"lengthSeconds\"' in blk
    assert 're.findall(r\'\"approxDurationMs\"' in blk
    assert "plausible = [v for v in candidates if 1.0 <= float(v) <= 43200.0]" in blk
    assert "return float(max(plausible))" in blk
    assert "return None" in blk
    assert "return 60.0" not in blk

    main_blk = txt[txt.index("vid_len = get_youtube_duration(url)"):txt.index("# Region optional überschreiben")]
    assert "if vid_len is not None and vid_len > 0:" in main_blk
