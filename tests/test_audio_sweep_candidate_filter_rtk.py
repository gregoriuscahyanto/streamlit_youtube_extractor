"""RTK checks for pre-sweep RPM candidate type filtering."""

from pathlib import Path

import numpy as np

from app_tabs.audio_sweep import (
    CANDIDATE_FILTER_OPTIONS,
    _reference_aware_candidate_pool,
)


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_candidate_filter_limits_pool_before_scoring():
    t = np.arange(5, dtype=float)
    rpm = np.linspace(1000.0, 2000.0, 5)
    extra = {
        "rpm_lines": {
            "Original Peak": rpm + 10.0,
            "Gear-Band Ridge": rpm + 20.0,
            "Hybrid": rpm + 30.0,
            "Kandidat 1: Hybrid C5 H1 N4096 O50": rpm + 40.0,
        }
    }

    only_original = _reference_aware_candidate_pool(t, rpm, extra, ["Original Peak"])
    assert [name for name, _ in only_original] == ["Original Peak"]

    only_antispike = _reference_aware_candidate_pool(t, rpm, extra, ["Anti-Spike"])
    assert only_antispike
    assert all(name.startswith("Anti-Spike:") for name, _ in only_antispike)

    gear_and_hybrid = _reference_aware_candidate_pool(t, rpm, extra, ["Gear-Band", "Hybrid"])
    names = [name for name, _ in gear_and_hybrid]
    assert "Gear-Band Ridge" in names
    assert "Hybrid" in names
    assert "Original Peak" not in names


def test_candidate_filter_ui_and_runner_wiring_exists():
    tab = _read("app_tabs/audio_tab.py")
    sweep = _read("app_tabs/audio_sweep.py")

    assert "CANDIDATE_FILTER_OPTIONS" in sweep
    assert "Zugelassene RPM-Kandidatentypen" in tab
    assert 'key="sw_candidate_filter"' in tab
    assert '"candidate_filter": list(_sw_candidate_filter or [])' in tab
    assert "candidate_filter=_cfg_snap.get(\"candidate_filter\") or None" in tab
    assert "not _sw_candidate_filter" in tab
    assert "Top-1 Parameter in Standard-Analyse" not in tab
    assert "sw_apply_top" not in tab
    for opt in CANDIDATE_FILTER_OPTIONS:
        assert opt in sweep
