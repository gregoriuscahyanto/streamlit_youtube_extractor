"""RTK checks for Standard-Analyse OCR-speed gear-band guidance."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_standard_analysis_builds_gear_band_cfg_from_ocr_speed():
    txt = _read("app_tabs/audio_tab.py")
    assert "def _audio_extract_v_from_doc(" in txt
    assert "recordResult" in txt
    assert "v_Fzg_kmph" in txt
    assert "def _audio_build_standard_gear_band_cfg(" in txt
    assert '"source": "standard_ocr_v_fzg_kmph"' in txt
    assert '"mode": "guide_and_clamp"' in txt
    assert "_std_gear_band_cfg = _audio_build_standard_gear_band_cfg(_sp)" in txt


def test_standard_analysis_passes_gear_band_cfg_to_background_worker():
    txt = _read("app_tabs/audio_tab.py")
    assert "gear_band_cfg=_std_gear_band_cfg" in txt
    assert "params_bg" in txt
    assert "gear_band_cfg=_std_gear_band_cfg," in txt
    assert "OCR-Speed Gear-Band aktiv" in txt
    assert "OCR-Speed Gear-Band inaktiv" in txt


def test_extractor_constrains_standard_rpm_and_persists_metadata():
    txt = _read("app.py")
    assert "from app_tabs.audio_sweep import _gear_band_cfg_for_candidate, constrain_rpm_to_gear_bands" in txt
    assert 'gear_limit_cfg = _gear_band_cfg_for_candidate(gear_band_cfg, str(best.get("method", "")))' in txt
    assert "rpm, gear_limit_meta = constrain_rpm_to_gear_bands(t_video, rpm, gear_limit_cfg)" in txt
    assert "Gear-Band Constraint:" in txt
    assert "policy={gear_limit_cfg.get('candidate_band_policy', 'default')}" in txt
    assert "gear_band_cfg=gear_band_cfg if isinstance(gear_band_cfg, dict) else {}" in txt
    assert "gear_band_active=gear_band_active" in txt
    assert "gear_band_mode=str((gear_band_cfg or {}).get(\"mode\", \"\"))" in txt
    assert "gear_band_policy=gear_band_policy" in txt
    assert "gear_band_coverage_pct=float(" in txt
    assert "gear_band_limited_points=int(gear_limit_meta.get(\"limited_points\", 0) or 0)" in txt
