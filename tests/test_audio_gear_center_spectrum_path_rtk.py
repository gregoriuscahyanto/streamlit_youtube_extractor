"""RTK checks for the reference-free gear-center spectrum candidate."""

import ast
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _load_audio_helpers():
    src = _read("app.py")
    tree = ast.parse(src)
    nodes = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_audio_gear_center_line_from_spectrum"
    ]
    ns = {"np": np}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(ROOT / "app.py"), "exec"), ns)
    return ns


def test_audio_extractor_registers_gear_center_candidate():
    txt = _read("app.py")
    assert "def _audio_gear_center_line_from_spectrum(" in txt
    assert "_audio_gear_center_line_from_spectrum(fb, sb, t_video, conv, gear_band_cfg)" in txt
    assert 'method_lines["Gear-Band Center"]' in txt
    assert "gear_center_score_bonus" in txt


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
