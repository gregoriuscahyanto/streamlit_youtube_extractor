"""RTK checks for robust handling of malformed audio sweep result entries."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_audio_tab_filters_non_dict_sweep_entries_before_top1_access():
    txt = _read("app_tabs/audio_tab.py")
    assert '_sw_results_raw = st.session_state.get("audio_sweep_results") or []' in txt
    assert '_sw_results = [r for r in _sw_results_raw if isinstance(r, dict)]' in txt
    assert 'st.session_state.audio_sweep_results = _sw_results' in txt
    assert 'if _sw_results_raw and not _sw_results:' in txt
    assert '_top = _sw_results[0]' in txt
