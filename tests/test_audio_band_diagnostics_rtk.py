"""RTK checks for audio gear-band diagnostics, calibration, and scoring contracts."""

from pathlib import Path
import math
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_audio_sweep_has_band_precheck_and_auto_scale_helpers():
    txt = _read("app_tabs/audio_sweep.py")
    assert "def gear_band_reference_diagnostics(" in txt
    assert "scale_values = np.linspace(float(scale_lo), float(scale_hi), int(n_scale))" in txt
    assert '"recommended_tol_pct"' in txt
    assert '"best_scale"' in txt
    assert '"best_within_pct"' in txt
    assert '"ref_band_pct_by_tol"' in txt


def test_audio_score_is_within_dominant():
    txt = _read("app_tabs/audio_sweep.py")
    assert "within_pct * 1.55" in txt
    assert "smooth_penalty = 0.018 * excess_roughness_rpm + 0.08 * jump_rate_per_min" in txt
    assert "band_bonus = band_compliance_pct * max(0.0, float(band_weight)) / 100.0" in txt


def test_audio_tab_exposes_band_mode_precheck_scale_and_plot():
    txt = _read("app_tabs/audio_tab.py")
    assert '.selectbox("Bandmodus"' in txt
    assert '"Hard: nur Kandidaten im Band"' in txt
    assert '"Auto-Skalierung der effektiven Uebersetzung"' in txt
    assert 'gear_band_reference_diagnostics(' in txt
    assert 'Band-Precheck' in txt
    assert 'Band-Diagnoseplot' in txt
    assert '"gear_scale": float(_gear_scale_v)' in txt
    assert '_linked_ref["t_s"]' in txt
    assert '_linked_ref["rpm"]' in txt
    assert '"Youtube-Hotlap-Extractor" / "results"' in txt
    assert '"Band-Precheck / Korrekturfaktor berechnen"' in txt
    assert "_sw_band_diag_cache" in txt
    assert "_sw_pending_gear_scale" in txt
    assert "_sw_pending_band_tol_pct" in txt
    assert '"Bandbreite automatisch uebernehmen"' in txt
    assert '"sw_auto_band_tol"' in txt
    assert "_render_sweep_preconfig(_has_v_ocr, _v_ocr_t, _v_ocr_kmph, _precheck_ref)" in txt
    assert 'np.asarray(\n                                    pd.to_numeric(_ref_precheck["t_s"], errors="coerce"),' in txt
    assert 'np.asarray(\n                                    pd.to_numeric(_ref_precheck["rpm"], errors="coerce"),' in txt


def test_gear_band_reference_diagnostics_runtime_fit():
    from app_tabs.audio_sweep import gear_band_reference_diagnostics

    t = [0.0, 1.0, 2.0, 3.0]
    v = [100.0, 100.0, 100.0, 100.0]
    axle = 4.0
    gear = 1.5
    r_dyn = 0.35
    rpm = [(100.0 / 3.6) / (2.0 * math.pi * r_dyn) * axle * gear * 60.0] * 4
    cfg = {
        "t_ocr": t,
        "v_kmph_ocr": v,
        "gear_ratios": [gear],
        "axle_ratio": axle,
        "r_dyn": r_dyn,
        "rpm_min": 500.0,
        "rpm_max": 8000.0,
        "band_tol_pct": 5.0,
    }

    diag = gear_band_reference_diagnostics(t, rpm, cfg, tolerances=(5.0,))

    assert diag["ok"] is True
    assert diag["ref_band_pct_by_tol"]["5.0"] == 100.0
    assert diag["best_within_pct"] == 100.0
