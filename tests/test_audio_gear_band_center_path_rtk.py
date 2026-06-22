"""RTK checks for band-center guidance, gear-path smoothing, and high-gear bias."""

from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_audio_extractor_uses_center_weighted_band_guidance():
    txt = _read("app.py")
    assert "center_weight = float(gear_band_cfg.get(\"band_center_weight\", 0.65) or 0.65)" in txt
    assert "higher_gear_bias = float(gear_band_cfg.get(\"higher_gear_bias\", 0.08) or 0.08)" in txt
    assert "center_score = np.clip(1.0 - np.abs(rpm_grid - rpm_c[None, :])" in txt
    assert "_audio_motor_spectrum_contrast(" in txt


def test_sweep_clamp_uses_viterbi_gear_path():
    txt = _read("app_tabs/audio_sweep.py")
    assert "def _viterbi_gear_path(" in txt
    assert "gear_shift_penalty" in txt
    assert "higher_gear_bias" in txt
    assert "band_center_weight" in txt
    assert "_viterbi_gear_path(" in txt


def test_audio_tab_exposes_reference_free_band_guidance_controls():
    txt = _read("app_tabs/audio_tab.py")
    assert '"Bandzentrum-Gewichtung"' in txt
    assert '"Hoehere Gaenge bevorzugen"' in txt
    assert '"Gangwechsel-Strafe"' in txt
    assert '"band_center_weight": float(_band_center_w)' in txt
    assert '"higher_gear_bias": float(_higher_gear_bias_v)' in txt
    assert '"gear_shift_penalty": max(float(_gear_shift_penalty_v), 1.2) if str(_band_mode) == "hard" else float(_gear_shift_penalty_v)' in txt
    assert '"snap_to_band_center": str(_band_mode) == "hard"' in txt
    assert '"center_blend": 1.0 if str(_band_mode) == "hard" else 0.0' in txt
    assert '"band_smooth_n": max(int(_band_smooth_n), 21) if str(_band_mode) == "hard" else int(_band_smooth_n)' in txt
    assert "_gear_band_cfg_snap = _sw_gear_band_cfg" in txt
    assert '"center_blend": 0.0, "snap_to_band_center": False' not in txt


def test_hard_mode_blends_rpm_toward_band_center_without_reference():
    from app_tabs.audio_sweep import compute_gear_bands, constrain_rpm_to_gear_bands

    t = np.array([0.0, 1.0, 2.0], dtype=float)
    rpm = np.array([900.0, 2300.0, 9000.0], dtype=float)
    cfg = {
        "t_ocr": [0.0, 2.0],
        "v_kmph_ocr": [100.0, 100.0],
        "gear_ratios": [1.0],
        "axle_ratio": 3.0,
        "r_dyn": 0.35,
        "rpm_min": 500.0,
        "rpm_max": 8000.0,
        "band_tol_pct": 20.0,
        "mode": "hard",
        "center_blend": 1.0,
    }

    limited, meta = constrain_rpm_to_gear_bands(t, rpm, cfg)
    bands = compute_gear_bands(t, cfg["t_ocr"], cfg["v_kmph_ocr"], cfg["gear_ratios"], cfg["axle_ratio"], cfg["r_dyn"], cfg["rpm_min"], cfg["rpm_max"], cfg["band_tol_pct"])
    center = ((bands[:, 0, 0] + bands[:, 0, 1]) * 0.5).tolist()

    assert np.allclose(limited, center)
    assert meta["snap_to_band_center"] is True
    assert meta["center_blend"] == 1.0
