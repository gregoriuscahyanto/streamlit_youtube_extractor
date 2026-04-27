from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from ocr_diagnostic import diagnose_roi_ocr, find_tesseract_cmd, get_charset_for_format, validate_formatted


LOG_PATH = Path("logs/ocr_diagnostic_test.log")


def _write_log(message: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text(message, encoding="utf-8")


def test_tesseract_roi_diagnostic_reads_synthetic_roi() -> None:
    tesseract_cmd = find_tesseract_cmd()
    if not tesseract_cmd:
        _write_log("SKIP: Tesseract wurde nicht gefunden.")
        pytest.skip("Tesseract wurde nicht gefunden.")

    try:
        frame = np.full((90, 240, 3), 255, dtype=np.uint8)
        cv2.putText(
            frame,
            "123",
            (45, 62),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.8,
            (0, 0, 0),
            4,
            cv2.LINE_AA,
        )
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        roi = {
            "x": 30,
            "y": 18,
            "w": 155,
            "h": 58,
            "fmt": "int_min2_max3",
            "pattern": "",
            "max_scale": 1.2,
        }

        result = diagnose_roi_ocr(
            frame_rgb,
            roi,
            (frame_rgb.shape[1], frame_rgb.shape[0]),
            tmp_root="logs/ocr_test_tmp",
        )

        assert result["ok"], result
        assert result["value"] == "123", result
        assert result["variant"] in {"frUp", "bw"}
        assert result["confidence"] >= 0.5
        _write_log(
            "OK: Tesseract ROI-Test hat synthetische ROI gelesen. "
            f"value={result['value']}, raw={result['raw']}, "
            f"variant={result['variant']}, confidence={result['confidence']:.2f}"
        )
    except Exception as exc:
        _write_log(f"ERROR: {exc.__class__.__name__}: {exc}")
        raise


def test_python_ocr_rules_match_matlab_ocr_extractor() -> None:
    try:
        matlab_source = Path("OCRExtractor.m").read_text(encoding="utf-8")
        assert "imresize(frCrop, 2.0, 'bilinear')" in matlab_source
        assert "'Sensitivity', 0.45" in matlab_source
        assert "scoreA = double(strlength(rawA)) + 5*double(confA)" in matlab_source
        assert "scoreB = double(strlength(rawB)) + 5*double(confB)" in matlab_source
        assert "cs = '0123456789:.,'" in matlab_source
        assert get_charset_for_format("time_m:ss") == "0123456789:.,"
        assert get_charset_for_format("int_min2_max3") == "+-0123456789"
        assert validate_formatted("O12", "int_min2_max3") == (True, "012")
    except Exception as exc:
        _write_log(f"ERROR: {exc.__class__.__name__}: {exc}")
        raise
