"""RTK checks for reference-aware candidate selection in audio sweep."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_extractor_returns_rpm_candidate_lines():
    txt = _read("app.py")
    assert "rpm_lines = {}" in txt
    assert "rpm_lines[_cand_label]" in txt
    assert 'mp.get("max_reference_candidates", 120)' in txt
    assert "rpm_lines= rpm_lines" in txt or "rpm_lines=rpm_lines" in txt


def test_sweep_scores_reference_aware_candidates():
    txt = _read("app_tabs/audio_sweep.py")
    assert "def _score_one_rpm_candidate(" in txt
    assert "def _reference_aware_candidate_pool(" in txt
    assert '"selected_candidate_line"' in txt
    assert '"candidate_source_method"' in txt
    assert "rpm_lines = (extra or {}).get(\"rpm_lines\") or {}" in txt
    assert '"max_reference_candidates": 120' in txt
    assert "study.enqueue_trial(_params)" in txt
    assert "startup_grid" in txt


def test_reference_aware_candidate_runtime_prefers_better_line():
    from app_tabs.audio_sweep import _score_one_rpm_candidate

    t = [0.0, 1.0, 2.0, 3.0]
    ref = [1000.0, 2000.0, 3000.0, 4000.0]
    bad = [4000.0, 3000.0, 2000.0, 1000.0]
    good = [1000.0, 2010.0, 2990.0, 4000.0]

    bad_score = _score_one_rpm_candidate(
        t, bad, t, ref, 0.0, 0.0, 0.5, 100.0, 5.0, "ODER", None, "bad"
    )
    good_score = _score_one_rpm_candidate(
        t, good, t, ref, 0.0, 0.0, 0.5, 100.0, 5.0, "ODER", None, "good"
    )

    assert good_score["within_pct"] > bad_score["within_pct"]
    assert good_score["selected_candidate_line"] == "good"
