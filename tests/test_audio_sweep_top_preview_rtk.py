"""RTK checks for fast top-result plot previews from audio sweep."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_sweep_result_contains_compact_plot_preview():
    txt = _read("app_tabs/audio_sweep.py")
    assert "def _compact_plot_preview(" in txt
    assert '"plot_t_s"' in txt
    assert '"plot_rpm"' in txt
    assert "max_points: int = 2500" in txt


def test_audio_tab_uses_preview_before_recompute():
    txt = _read("app_tabs/audio_tab.py")
    assert "plot_t_s" in txt
    assert "plot_rpm" in txt
    assert '"always_run_cwt": False' in txt
    assert '"fast_mode": True' in txt
    assert "selected_candidate_line" in txt
    assert "rpm_lines" in txt
