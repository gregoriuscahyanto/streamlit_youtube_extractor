"""RTK regression tests for audio sweep extractor compatibility and random-run wiring."""

from pathlib import Path

import numpy as np

from app_tabs.audio_sweep import _eval_single_params


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_eval_single_params_accepts_dict_return_from_extractor():
    params = {
        "method": "Hybrid",
        "nfft": 1024,
        "overlap_pct": 75.0,
        "fmax": 400.0,
        "cyl": 4,
        "takt": 4,
        "order": 1.0,
        "rpm_min": 800.0,
        "rpm_max": 7000.0,
        "ridge_smooth": 7,
        "ridge_jump_frac": 0.08,
        "viterbi_jump_hz": 25.0,
        "viterbi_penalty": 1.2,
        "viterbi_smooth": 5,
        "comb_harmonics": 4,
        "hybrid_smooth": 9,
    }

    t = np.linspace(0.0, 20.0, 401)
    rpm = 3000.0 + 250.0 * np.sin(2 * np.pi * 0.2 * t)

    def _extractor(**_kwargs):
        return {
            "t": t,
            "rpm": rpm,
            "fs": 48000,
            "params": {"dummy": True},
            "candidate_table": [],
        }

    res = _eval_single_params(
        params=params,
        y=np.zeros(48000, dtype=float),
        fs=48000.0,
        start_s=0.0,
        end_s=20.0,
        t_ref=t,
        rpm_ref=rpm,
        tol_abs_rpm=None,
        tol_pct=None,
        tol_logic="ODER",
        offset_base=0.0,
        offset_range=0.0,
        offset_step=0.25,
        extract_rpm_fn=_extractor,
        errors_out=[],
    )

    assert bool(res.get("ok")) is True
    assert float(res.get("combined_score", 0.0)) > 0.0


def test_run_sweep_random_passes_grid_keyword_to_run_sweep():
    txt = _read("app_tabs/audio_sweep.py")
    assert "grid=sampled" in txt
    assert "sampled, y, fs" not in txt


def test_audio_tab_sweep_worker_does_not_unpack_extractor_tuple():
    txt = _read("app_tabs/audio_tab.py")
    assert "t_a, r_a, _extra = _extract_fn(" not in txt
    assert "return _extract_fn(" in txt


def test_audio_tab_sweep_log_includes_best_score_so_far():
    txt = _read("app_tabs/audio_tab.py")
    assert "_best_seen = {\"score\": float(\"-inf\"), \"within\": 0.0, \"rmse\": float(\"inf\")}" in txt
    assert "Best bisher: Score=" in txt
    assert "WARN " in txt
