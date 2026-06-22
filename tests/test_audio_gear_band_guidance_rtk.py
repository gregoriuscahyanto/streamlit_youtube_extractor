"""RTK checks for gear-band guidance during audio candidate selection."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_audio_extractor_accepts_gear_band_guidance():
    txt = _read("app.py")
    assert "def _audio_gear_band_freq_bonus(" in txt
    assert "def _audio_apply_gear_band_guidance(" in txt
    assert "gear_band_cfg=None" in txt
    assert "gear_band_mode = str((gear_band_cfg or {}).get(\"mode\", \"hard\") or \"hard\").strip().lower()" in txt
    assert "_sb_eval, _gear_guidance_meta = _audio_apply_gear_band_guidance(sb, fb, t_video, conv, gear_band_cfg)" in txt
    assert 'method_lines["Original Peak"] = np.asarray(_audio_smooth(_audio_peak_line(fb, _sb_eval), 5), dtype=float).copy()' in txt
    assert 'method_lines["STFT Ridge"] = _audio_greedy_ridge_line(fb, _sb_eval, flo, fhi' in txt
    assert 'method_lines["STFT Viterbi"] = _audio_viterbi_line(fb, _sb_eval, flo, fhi' in txt
    assert 'if mode == "hard":' in txt
    assert 'masked = np.where(bonus > 0.0, sb_arr, floor - penalty)' in txt


def test_audio_sweep_passes_gear_band_cfg_into_extractor():
    txt = _read("app_tabs/audio_tab.py")
    assert "gear_band_cfg=_gear_band_cfg_snap," in txt
    assert '"mode": str(_band_mode)' in txt
