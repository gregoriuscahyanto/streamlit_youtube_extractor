"""RTK checks for GoPro correction in ROI setup."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_roi_setup_exposes_gopro_correction_controls():
    txt = _read("app_tabs/roi_setup_tab.py")
    assert "from gopro_correction import apply_gopro_corrections_to_frame, run_gopro_correction_2fps" in txt
    assert '"GoPro-Korrektur"' in txt
    assert '"Weitwinkelkorrektur"' in txt
    assert '"Bildlagewanderung kompensieren"' in txt
    assert '"Kamera hoeher simulieren"' in txt
    assert '"Warp / Kamerahoehe"' in txt
    assert '"Drehung"' in txt
    assert '"Drehzentrum X"' in txt
    assert '"Drehzentrum Y"' in txt
    assert '"Bildlage X"' in txt
    assert '"Bildlage Y"' in txt
    assert "Live-Vorschau" in txt
    assert '"Vorher"' in txt
    assert '"Nachher"' in txt
    assert "st.slider(" in txt
    assert "apply_gopro_corrections_to_frame(" in txt
    assert '"Korrekturvideo erzeugen"' in txt
    assert "run_gopro_correction_2fps(" in txt
    assert 'globals().get("_apply_video")' in txt
    assert 'st.session_state.tab_default = "ROI Setup"' in txt
    assert "progress_box = st.progress(" in txt
    assert "eta_s" in txt
    assert "pct" in txt
    assert "log_box = st.empty()" in txt
    assert "target_fps=2.0" in txt
    assert "wide_k1=" in txt
    assert "shift_gain=" in txt
    assert "max_shift_px=" in txt
    assert "perspective_strength=" in txt
    assert "rotation_deg=" in txt
    assert "rotation_center_x=" in txt
    assert "rotation_center_y=" in txt
    assert "manual_shift_x_px=" in txt
    assert "manual_shift_y_px=" in txt


def test_gopro_correction_module_contains_warp_stabilization():
    txt = _read("gopro_correction.py")
    assert "def run_gopro_correction_2fps(" in txt
    assert "def apply_gopro_corrections_to_frame(" in txt
    assert "def _undistort_wide_frame(" in txt
    assert "k1: float = -0.48" in txt
    assert "shift_gain: float = 2.2" in txt
    assert "max_shift_px: float = 360.0" in txt
    assert "perspective_strength: float = 0.18" in txt
    assert "rotation_deg: float = 0.0" in txt
    assert "rotation_center_x: float = 0.5" in txt
    assert "rotation_center_y: float = 0.5" in txt
    assert "manual_shift_x_px: float = 0.0" in txt
    assert "manual_shift_y_px: float = 0.0" in txt
    assert "cv2.phaseCorrelate" in txt
    assert "cv2.estimateAffinePartial2D" in txt
    assert "cv2.getPerspectiveTransform" in txt
    assert "cv2.warpPerspective" in txt
    assert "cv2.warpAffine" in txt
    assert "cv2.getRotationMatrix2D" in txt
    assert "def _rotate_frame(" in txt
    assert "def _manual_shift_frame(" in txt
    assert "def _emit_progress(" in txt
    assert "progress_cb(msg, pct, eta_s)" in txt
    assert '"manual_shift_x_px"' in txt
    assert '"manual_shift_y_px"' in txt
    assert "target_fps = float(target_fps or 2.0)" in txt
    assert '"rotation_deg"' in txt
    assert '"perspective_warp"' in txt
    assert '"wide_angle_correction"' in txt
    assert '"frame_stabilization"' in txt
    assert '"warp_stabilization"' in txt


def test_local_import_no_longer_references_gopro_correction():
    media = _read("app_tabs/media_tab.py")
    ingest = _read("local_media_ingest.py")
    assert "GoPro-Kompensation" not in media
    assert "compensate_gopro" not in media
    assert "gopro_correction" not in ingest
    assert "compensate_gopro" not in ingest
