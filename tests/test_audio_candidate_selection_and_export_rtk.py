"""RTK checks for audio RPM candidate selection and JSON trace export."""

from pathlib import Path
import json
import uuid

import numpy as np

from app_tabs.audio_sweep import (
    apply_audio_candidate_selection,
    audio_candidate_options_from_result,
    save_sweep_results,
)


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _gear_cfg() -> dict:
    return {
        "mode": "guide_and_clamp",
        "t_ocr": [0.0, 1.0, 2.0, 3.0],
        "v_kmph_ocr": [20.0, 20.0, 20.0, 20.0],
        "gear_ratios": [3.0, 1.5],
        "axle_ratio": 4.0,
        "r_dyn": 0.35,
        "rpm_min": 500.0,
        "rpm_max": 8000.0,
        "band_tol_pct": 20.0,
        "band_smooth_n": 3,
        "gear_shift_penalty": 0.35,
        "higher_gear_bias": 0.0,
        "band_center_weight": 0.65,
    }


def test_standard_candidate_selection_exposes_antispike_and_gear_trace():
    res = {
        "t": np.array([0.0, 1.0, 2.0, 3.0], dtype=float),
        "rpm": np.array([900.0, 920.0, 940.0, 960.0], dtype=float),
        "rpm_lines": {
            "Original Peak": np.array([1815.0, 5200.0, 1820.0, 1810.0], dtype=float),
        },
        "params": {"gear_band_cfg": _gear_cfg()},
    }

    opts = audio_candidate_options_from_result(res)
    assert "Extractor-Auswahl" in opts
    assert "Original Peak" in opts
    assert "Anti-Spike: Original Peak" in opts

    selected = apply_audio_candidate_selection(res, "Anti-Spike: Original Peak")

    assert selected["selected_candidate_line"] == "Anti-Spike: Original Peak"
    assert selected["params"]["candidate_selection_reference_free"] is True
    assert len(selected["rpm"]) == 4
    assert max(selected["rpm"]) < 3000.0
    assert selected["gear_trace"]["gear_band_active"] is True
    assert selected["gear_trace"]["gear"] == [1, 1, 1, 1]


def test_sweep_save_writes_selected_audio_rpm_and_gear_trace():
    tmp_dir = ROOT / "logs" / "rtk_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    path = tmp_dir / f"audio_candidate_export_{uuid.uuid4().hex}.json"
    path.write_text(json.dumps({"recordResult": {}}), encoding="utf-8")
    results = [
        {
            "rank": 1,
            "method": "Hybrid",
            "selected_candidate_line": "Extractor-Auswahl",
            "plot_t_s": [0.0, 1.0],
            "plot_rpm": [1810.0, 1820.0],
            "offset_s": 0.0,
            "combined_score": 10.0,
        },
        {
            "rank": 2,
            "method": "Peak",
            "selected_candidate_line": "Anti-Spike: Original Peak",
            "plot_t_s": [0.0, 1.0],
            "plot_rpm": [900.0, 910.0],
            "offset_s": 0.5,
            "combined_score": 9.0,
        },
    ]

    save_sweep_results(str(path), results, gear_band_cfg=_gear_cfg(), selected_index=1)

    doc = json.loads(path.read_text(encoding="utf-8"))
    rr = doc["recordResult"]
    assert rr["audio_sweep"]["selected_index"] == 1
    assert rr["audio_sweep"]["top1_trace"]["rpm"] == [1810.0, 1820.0]
    assert rr["audio_sweep"]["selected_trace"]["selected_candidate_line"] == "Anti-Spike: Original Peak"
    processed = rr["audio_rpm"]["processed"]
    assert processed["rpm"] == [900.0, 910.0]
    assert processed["selected_candidate_line"] == "Anti-Spike: Original Peak"
    assert processed["gear"] == [2, 2]
    assert len(processed["gear_center_rpm"]) == 2
    path.unlink(missing_ok=True)


def test_audio_tab_candidate_selection_ui_and_standard_save_fields_exist():
    tab = _read("app_tabs/audio_tab.py")
    app = _read("app.py")
    sweep = _read("app_tabs/audio_sweep.py")

    assert "RPM-Kandidat auswaehlen" in tab
    assert "Sweep-Kandidat auswaehlen" in tab
    assert "Audioanalyse in JSON speichern" in tab
    assert "Audioanalyse in MAT + JSON speichern" not in tab
    assert "_save_audio_result_to_selected_mat(res)" not in tab
    assert "Ausgewaehlten RPM-Verlauf in JSON speichern" in tab
    assert "def _write_audio_rpm_json_only" in tab
    assert "_write_audio_rpm_json_only(res_bg)" in tab
    assert "selected_index=_sw_selected_idx" in tab
    assert "save_sweep_results(str(_cur_jp), _sw_res, gear_band_cfg=_sw_gear_band_cfg)" in tab
    assert "audio_candidate_options_from_result" in sweep
    assert "apply_audio_candidate_selection" in sweep
    assert '"selected_candidate_line": selected_candidate_line' in app
    assert 'processed["gear"] = gear' in app
    assert 'processed["gear_center_rpm"] = gear_center' in app
