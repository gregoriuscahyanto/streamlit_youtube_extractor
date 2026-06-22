"""RTK checks for the reference-free gear-center spectrum candidate."""

import ast
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]


class _Roll:
    def __init__(self, values, window):
        self.values = np.asarray(values, dtype=float)
        self.window = int(max(1, window))

    def median(self):
        half = self.window // 2
        out = np.empty_like(self.values, dtype=float)
        for idx in range(self.values.size):
            lo = max(0, idx - half)
            hi = min(self.values.size, idx + half + 1)
            out[idx] = np.nanmedian(self.values[lo:hi])
        return _Series(out)


class _Series:
    def __init__(self, values):
        self.values = np.asarray(values, dtype=float)

    def rolling(self, window, center=True, min_periods=1):
        del center, min_periods
        return _Roll(self.values, window)

    def to_numpy(self, dtype=float):
        return np.asarray(self.values, dtype=dtype).copy()


class _Pandas:
    Series = _Series


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _load_audio_helpers():
    src = _read("app.py")
    tree = ast.parse(src)
    names = {
        "_audio_interp_nan",
        "_audio_smooth",
        "_audio_gear_center_line_from_spectrum",
        "_audio_gear_ridge_line_from_spectrum",
        "_audio_gear_ridge_viterbi_line_from_spectrum",
    }
    nodes = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in names
    ]
    ns = {"np": np, "pd": _Pandas}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(ROOT / "app.py"), "exec"), ns)
    return ns


def test_audio_extractor_registers_gear_center_candidate():
    txt = _read("app.py")
    assert "def _audio_gear_center_line_from_spectrum(" in txt
    assert "_audio_gear_center_line_from_spectrum(fb, sb, t_video, conv, gear_band_cfg)" in txt
    assert 'method_lines["Gear-Band Center"]' in txt
    assert "_audio_gear_ridge_line_from_spectrum(fb, sb, t_video, conv, gear_band_cfg)" in txt
    assert 'method_lines["Gear-Band Ridge"]' in txt
    assert "_audio_gear_ridge_viterbi_line_from_spectrum(fb, sb, t_video, conv, gear_band_cfg)" in txt
    assert 'method_lines["Gear-Band Ridge Viterbi"]' in txt
    assert "gear_center_score_bonus" in txt
    assert "gear_ridge_score_bonus" in txt
    assert "gear_ridge_viterbi_score_bonus" in txt


def test_gear_center_candidate_follows_audio_energy_without_reference():
    ns = _load_audio_helpers()
    from app_tabs.audio_sweep import compute_gear_bands

    t = np.linspace(0.0, 5.0, 6)
    freqs = np.linspace(10.0, 150.0, 281)
    cfg = {
        "t_ocr": t.tolist(),
        "v_kmph_ocr": [100.0] * len(t),
        "gear_ratios": [1.0, 2.0],
        "axle_ratio": 3.0,
        "r_dyn": 0.35,
        "rpm_min": 500.0,
        "rpm_max": 8000.0,
        "band_tol_pct": 12.0,
        "gear_shift_penalty": 1.2,
        "higher_gear_bias": 0.0,
    }
    conv = 1.0
    bands = compute_gear_bands(t, cfg["t_ocr"], cfg["v_kmph_ocr"], cfg["gear_ratios"], cfg["axle_ratio"], cfg["r_dyn"], cfg["rpm_min"], cfg["rpm_max"], cfg["band_tol_pct"])
    centers_hz = ((bands[:, :, 0] + bands[:, :, 1]) * 0.5) * conv / 60.0

    score = np.zeros((len(freqs), len(t)), dtype=np.float32)
    for i, fc in enumerate(centers_hz[:, 1]):
        score[int(np.argmin(np.abs(freqs - fc))), i] = 10.0
    for i, fc in enumerate(centers_hz[:, 0]):
        score[int(np.argmin(np.abs(freqs - fc))), i] = 1.0

    line, meta = ns["_audio_gear_center_line_from_spectrum"](freqs, score, t, conv, cfg)

    assert meta["active"] is True
    assert meta["valid_points"] == len(t)
    assert np.allclose(line, centers_hz[:, 1])


def test_gear_ridge_candidate_tracks_audio_peak_inside_band_without_reference():
    ns = _load_audio_helpers()
    from app_tabs.audio_sweep import compute_gear_bands

    t = np.linspace(0.0, 5.0, 6)
    freqs = np.linspace(10.0, 150.0, 281)
    cfg = {
        "t_ocr": t.tolist(),
        "v_kmph_ocr": [100.0] * len(t),
        "gear_ratios": [1.0, 2.0],
        "axle_ratio": 3.0,
        "r_dyn": 0.35,
        "rpm_min": 500.0,
        "rpm_max": 8000.0,
        "band_tol_pct": 20.0,
        "gear_shift_penalty": 1.2,
        "higher_gear_bias": 0.0,
        "band_center_weight": 0.2,
    }
    conv = 1.0
    bands = compute_gear_bands(t, cfg["t_ocr"], cfg["v_kmph_ocr"], cfg["gear_ratios"], cfg["axle_ratio"], cfg["r_dyn"], cfg["rpm_min"], cfg["rpm_max"], cfg["band_tol_pct"])
    centers_hz = ((bands[:, :, 0] + bands[:, :, 1]) * 0.5) * conv / 60.0
    target = centers_hz[:, 1] * 1.08

    score = np.zeros((len(freqs), len(t)), dtype=np.float32)
    for i, fc in enumerate(target):
        score[int(np.argmin(np.abs(freqs - fc))), i] = 10.0
    for i, fc in enumerate(centers_hz[:, 1]):
        score[int(np.argmin(np.abs(freqs - fc))), i] = 2.0

    line, meta = ns["_audio_gear_ridge_line_from_spectrum"](freqs, score, t, conv, cfg)

    assert meta["active"] is True
    assert meta["valid_points"] == len(t)
    assert np.nanmedian(np.abs(line - target)) < 0.6


def test_gear_ridge_viterbi_rejects_alternating_spikes_without_reference():
    ns = _load_audio_helpers()
    from app_tabs.audio_sweep import compute_gear_bands

    t = np.linspace(0.0, 7.0, 12)
    freqs = np.linspace(12.0, 80.0, 273)
    cfg = {
        "t_ocr": t.tolist(),
        "v_kmph_ocr": [100.0] * len(t),
        "gear_ratios": [1.0],
        "axle_ratio": 3.0,
        "r_dyn": 0.35,
        "rpm_min": 500.0,
        "rpm_max": 8000.0,
        "band_tol_pct": 60.0,
        "band_center_weight": 0.2,
        "ridge_viterbi_jump_hz": 4.0,
        "ridge_viterbi_penalty": 3.0,
        "ridge_viterbi_smooth_n": 3,
    }
    conv = 1.0
    bands = compute_gear_bands(t, cfg["t_ocr"], cfg["v_kmph_ocr"], cfg["gear_ratios"], cfg["axle_ratio"], cfg["r_dyn"], cfg["rpm_min"], cfg["rpm_max"], cfg["band_tol_pct"])
    center = ((bands[:, 0, 0] + bands[:, 0, 1]) * 0.5) * conv / 60.0
    target = center * (1.0 + 0.03 * np.sin(np.linspace(0.0, np.pi, len(t))))
    spike = center * 1.42

    score = np.zeros((len(freqs), len(t)), dtype=np.float32)
    for i, fc in enumerate(target):
        score[int(np.argmin(np.abs(freqs - fc))), i] = 6.0
    for i in range(1, len(t), 2):
        score[int(np.argmin(np.abs(freqs - spike[i]))), i] = 10.0

    line, meta = ns["_audio_gear_ridge_viterbi_line_from_spectrum"](freqs, score, t, conv, cfg)

    assert meta["active"] is True
    assert meta["valid_points"] == len(t)
    assert np.nanmedian(np.abs(line - target)) < 0.8
