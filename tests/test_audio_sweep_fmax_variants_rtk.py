"""RTK checks for physically motivated fmax variants in audio sweep."""

from pathlib import Path

from app_tabs.audio_sweep import _balanced_optuna_startup_grid, _fmax_candidates_for_combo, build_param_grid


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_fmax_candidates_exclude_unphysical_legacy_200_hz_floor():
    vals = dict(_fmax_candidates_for_combo(7500.0, 5, 0.5, 4, 1.5))

    assert "legacy_floor_200" not in vals
    assert vals["harmonic_3x"] == 230.0


def test_build_param_grid_uses_harmonic_fmax_variant_only():
    grid = build_param_grid(
        {
            "method": "Harmonic Comb/HPS",
            "sweep_method": False,
            "nfft_values": [4096],
            "overlap_values": [50.0],
            "order_values": [0.5],
            "cyl": 5,
            "takt": 4,
            "rpm_min": 800.0,
            "rpm_max": 7500.0,
            "fmax_headroom": 1.5,
        }
    )

    pairs = {(row["fmax_variant"], row["fmax"]) for row in grid}
    assert pairs == {("harmonic_3x", 230.0)}


def test_balanced_optuna_startup_grid_has_no_known_good_shape_bias():
    trials = _balanced_optuna_startup_grid(
        methods=["STFT/Ridge", "Harmonic Comb/HPS", "Hybrid"],
        nffts=[1024, 4096],
        overlaps=[50.0, 75.0],
        orders=[0.5, 1.0],
        cyls=["5"],
        takts=["4"],
        max_trials=12,
    )

    assert len(trials) == 12
    assert {row["method"] for row in trials} == {"STFT/Ridge", "Harmonic Comb/HPS", "Hybrid"}
    assert {row["nfft"] for row in trials} == {1024, 4096}
    assert {row["overlap"] for row in trials} == {50.0, 75.0}
    assert {row["fmax_variant"] for row in trials} == {"harmonic_3x"}


def test_optuna_source_searches_fmax_variant_without_specific_combo_priority():
    txt = _read("app_tabs/audio_sweep.py")

    assert 'trial.suggest_categorical("fmax_variant", FMAX_VARIANTS)' in txt
    assert '"fmax_variant": str(fmax_variant)' in txt
    assert '"legacy_floor_200"' not in txt
    assert "_balanced_optuna_startup_grid(" in txt
    assert "pref_nfft" not in txt
    assert "pref_overlap" not in txt
    assert "priority_methods" not in txt
