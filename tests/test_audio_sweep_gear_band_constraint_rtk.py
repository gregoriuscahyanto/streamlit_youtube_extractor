"""RTK checks for gear-band RPM constraints in audio sweep."""

import numpy as np

from app_tabs.audio_sweep import constrain_rpm_to_gear_bands


def test_constrain_rpm_to_gear_bands_clamps_per_timepoint():
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
        "band_tol_pct": 5.0,
    }

    limited, meta = constrain_rpm_to_gear_bands(t, rpm, cfg)

    assert limited.shape == rpm.shape
    assert limited[0] > rpm[0]
    assert limited[1] == rpm[1]
    assert limited[2] < rpm[2]
    assert meta["gear_band_constraint"] is True
    assert meta["limited_points"] == 2


def test_hard_band_mode_also_clamps_final_rpm():
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
        "band_tol_pct": 5.0,
        "mode": "hard",
    }

    limited, meta = constrain_rpm_to_gear_bands(t, rpm, cfg)

    assert limited[0] > rpm[0]
    assert limited[2] < rpm[2]
    assert meta["gear_band_constraint"] is True


def test_audio_sweep_source_uses_constraint_before_scoring():
    txt = __import__("pathlib").Path("app_tabs/audio_sweep.py").read_text(encoding="utf-8")
    assert "def constrain_rpm_to_gear_bands(" in txt
    assert "rpm_audio, _gear_limit_meta = constrain_rpm_to_gear_bands(" in txt
    assert '"gear_band_constraint"' in txt
    assert "band_compliance_pct * (band_weight / 100.0)" not in txt
