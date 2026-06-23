"""RTK checks that sweep reference data validates but does not alter RPM traces."""

from pathlib import Path
import sys

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_no_reference_filtered_candidate_in_sweep_source():
    txt = _read("app_tabs/audio_sweep.py")
    assert "Referenz-gefiltert" not in txt
    assert "def _reference_guided_rpm_candidate(" not in txt
    assert '"reference_guided_candidate": False' in txt
    assert "score_agreement(" in txt
    assert '"plot_rpm"' in txt


def test_reference_validation_does_not_modify_candidate_preview():
    from app_tabs.audio_sweep import _score_one_rpm_candidate

    t = np.linspace(0.0, 9.0, 10)
    ref = np.full_like(t, 5500.0, dtype=float)
    spiky = np.array([1200.0, 7900.0, 1500.0, 7600.0, 1800.0, 7800.0, 1600.0, 7600.0, 1700.0, 7900.0])

    res = _score_one_rpm_candidate(
        t,
        spiky,
        t,
        ref,
        offset_base=0.0,
        offset_range=0.0,
        offset_step=0.5,
        tol_abs_rpm=300.0,
        tol_pct=5.0,
        tol_logic="ODER",
        gear_band_cfg=None,
        candidate_name="spiky",
    )

    assert res["ok"] is True
    assert res["selected_candidate_line"] == "spiky"
    assert res["reference_guided_candidate"] is False
    assert res["plot_rpm"] == [float(v) for v in spiky]


def test_reference_free_antispike_candidate_reduces_single_frame_spikes():
    from app_tabs.audio_sweep import _reference_aware_candidate_pool, _reference_free_antispike_rpm

    t = np.arange(11, dtype=float)
    rpm = np.array([5200, 5250, 5300, 2500, 5350, 5400, 5450, 7800, 5500, 5550, 5600], dtype=float)

    clean = _reference_free_antispike_rpm(t, rpm, window=5)
    pool = _reference_aware_candidate_pool(t, rpm, {"rpm_lines": {"raw": rpm}})
    names = [name for name, _line in pool]

    assert "Anti-Spike: Extractor-Auswahl" in names
    assert "Anti-Spike: raw" in names
    assert abs(clean[3] - 5325.0) < abs(rpm[3] - 5325.0)
    assert abs(clean[7] - 5475.0) < abs(rpm[7] - 5475.0)
