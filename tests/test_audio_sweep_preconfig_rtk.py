"""RTK checks for sweep configuration shown before reference file upload."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_audio_sweep_preconfig_is_above_measurement_file():
    txt = (ROOT / "app_tabs/audio_tab.py").read_text(encoding="utf-8")
    assert "def _render_sweep_preconfig(" in txt
    assert "Sweep-Parameter vor Messdatei" in txt
    assert "_render_sweep_preconfig(_has_v_ocr, _v_ocr_t, _v_ocr_kmph)" in txt
    assert txt.index("_render_sweep_preconfig(_has_v_ocr, _v_ocr_t, _v_ocr_kmph)") < txt.index('st.markdown("#### Referenzdatei / Messdatei")')
    assert 'key="sw_methods"' in txt
    assert 'key="sw_nfft"' in txt
    assert 'key="sw_overlap"' in txt
    assert 'key="sw_strategy"' in txt
    assert 'key="sw_rdyn"' in txt
    assert 'key="sw_gear_ratios_text"' in txt
    assert 'key="sw_axle_ratio"' in txt
    assert '"Drehzahlbaender aus v_Fzg_kmph zur RPM-Begrenzung verwenden"' in txt
    assert '"Drehzahlbaender aus v_Fzg_kmph im Scoring verwenden"' not in txt
