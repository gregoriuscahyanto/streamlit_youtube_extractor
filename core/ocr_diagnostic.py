from __future__ import annotations

import csv
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image


def find_tesseract_cmd() -> str | None:
    env_cmd = os.environ.get("TESSERACT_CMD", "").strip()
    if env_cmd and Path(env_cmd).exists():
        return env_cmd

    found = shutil.which("tesseract")
    if found:
        return found

    candidates = [
        Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
        Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def get_charset_for_format(fmt: str) -> str:
    fmt_str = str(fmt or "any")
    if fmt_str == "<undefined>":
        fmt_str = "any"
    if "time_" in fmt_str:
        return "0123456789:.,"
    if fmt_str == "integer" or fmt_str.startswith("int_"):
        return "+-0123456789"
    if fmt_str == "float":
        return "+-0123456789.,"
    if fmt_str == "alnum":
        return "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    return ""


def clean_ocr_text(text: str) -> str:
    s = str(text or "")
    s = re.sub(r"\s+", "", s)
    return (
        s.replace(",", ".")
        .replace("O", "0")
        .replace("o", "0")
        .replace("I", "1")
        .replace("l", "1")
        .replace("S", "5")
    )


def validate_formatted(text: str, fmt: str, pattern: str = "") -> tuple[bool, str]:
    s = clean_ocr_text(text)
    fmt_str = str(fmt or "any")
    if fmt_str == "<undefined>":
        fmt_str = "any"

    if "time_" in fmt_str:
        temp_fmt = fmt_str.replace("time_", "")
        normalized = re.sub(r"[,.:]", " ", s.strip())
        parts = []
        for token in ("h", "m", "s", "S"):
            count = temp_fmt.count(token)
            if count > 0:
                parts.append(rf"\d{{{count}}}")
        ok = bool(re.fullmatch(r"\s+".join(parts), normalized))
        if not ok:
            return False, ""
        values = normalized.split()
        if "S" in temp_fmt and len(values) >= 2:
            return True, ":".join(values[:-1]) + "." + values[-1]
        return True, ":".join(values)

    patterns = {
        "integer": r"^[+\-]?\d+$",
        "int_1": r"^[+\-]?\d{1}$",
        "int_2": r"^[+\-]?\d{2}$",
        "int_3": r"^[+\-]?\d{3}$",
        "int_4": r"^[+\-]?\d{4}$",
        "int_min2_max3": r"^[+\-]?\d{2,3}$",
        "int_min3_max4": r"^[+\-]?\d{3,4}$",
        "float": r"^[+\-]?\d+(\.\d+)?$",
        "alnum": r"^[A-Za-z0-9]+$",
    }
    if fmt_str == "custom":
        ok = bool(re.search(str(pattern or ""), s)) if pattern else True
        return ok, s if ok else ""
    if fmt_str in patterns:
        ok = bool(re.fullmatch(patterns[fmt_str], s))
        return ok, s if ok else ""
    return True, s


def expand_rect(rect: list[float] | tuple[float, ...], scale: float, frame_wh: tuple[int, int]) -> tuple[int, int, int, int]:
    if len(rect) != 4:
        return (0, 0, int(frame_wh[0]), int(frame_wh[1]))
    x, y, w, h = [float(v) for v in rect]
    frame_w, frame_h = int(frame_wh[0]), int(frame_wh[1])
    cx = x + w / 2.0
    cy = y + h / 2.0
    w2 = max(1, int(round(w * max(scale, 1.0))))
    h2 = max(1, int(round(h * max(scale, 1.0))))
    x2 = int(round(cx - w2 / 2.0))
    y2 = int(round(cy - h2 / 2.0))
    x2 = max(0, min(max(0, frame_w - 1), x2))
    y2 = max(0, min(max(0, frame_h - 1), y2))
    w2 = max(1, min(w2, frame_w - x2))
    h2 = max(1, min(h2, frame_h - y2))
    return (x2, y2, w2, h2)


def _preprocess_variants(frame_rgb: np.ndarray, rect: tuple[int, int, int, int]) -> dict[str, np.ndarray]:
    x, y, w, h = rect
    crop = frame_rgb[y:y + h, x:x + w]
    if crop.size == 0:
        crop = frame_rgb
    up = cv2.resize(crop, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_LINEAR)
    gray = cv2.cvtColor(up, cv2.COLOR_RGB2GRAY) if up.ndim == 3 else up
    gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
    block_size = max(3, min(31, (min(gray.shape[:2]) // 2) * 2 + 1))
    bw = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        block_size,
        7,
    )
    return {"frUp": up, "bw": bw}


def _run_tesseract_tsv(
    image: np.ndarray,
    charset: str,
    tmp_root: str | Path = "logs/ocr_tmp",
    tesseract_cmd: str | None = None,
) -> dict[str, Any]:
    cmd = tesseract_cmd or find_tesseract_cmd()
    if not cmd:
        return {"text": "", "confidence": 0.0, "error": "Tesseract wurde nicht gefunden."}

    tmp_root = Path(tmp_root)
    tmp_root.mkdir(parents=True, exist_ok=True)
    image_path = tmp_root / f"tess_{os.getpid()}_{uuid.uuid4().hex}.png"
    try:
        Image.fromarray(image).save(image_path)
        args = [cmd, str(image_path), "stdout", "--psm", "6", "--oem", "3", "tsv"]
        if charset:
            args.extend(["-c", f"tessedit_char_whitelist={charset}"])
        proc = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
    except Exception as exc:
        return {"text": "", "confidence": 0.0, "error": f"{exc.__class__.__name__}: {exc}"}
    finally:
        try:
            image_path.unlink(missing_ok=True)
        except Exception:
            pass
    if proc.returncode != 0:
        return {"text": "", "confidence": 0.0, "error": proc.stderr.strip()}

    words: list[str] = []
    confidences: list[float] = []
    for row in csv.DictReader(proc.stdout.splitlines(), delimiter="\t"):
        text = (row.get("text") or "").strip()
        if not text:
            continue
        words.append(text)
        try:
            conf = float(row.get("conf", "-1"))
        except ValueError:
            conf = -1.0
        if conf >= 0:
            confidences.append(conf / 100.0)
    confidence = float(np.mean(confidences)) if confidences else 0.0
    return {"text": " ".join(words), "confidence": confidence, "error": ""}


def diagnose_roi_ocr(
    frame_rgb: np.ndarray,
    roi: dict[str, Any],
    frame_wh: tuple[int, int],
    tmp_root: str | Path = "logs/ocr_tmp",
) -> dict[str, Any]:
    fmt = str(roi.get("fmt", "any"))
    pattern = str(roi.get("pattern", ""))
    max_scale = float(roi.get("max_scale", 1.2) or 1.2)
    if not np.isfinite(max_scale) or max_scale < 1.0:
        max_scale = 1.0
    rect = [
        float(roi.get("x", 0)),
        float(roi.get("y", 0)),
        float(roi.get("w", 0)),
        float(roi.get("h", 0)),
    ]
    charset = get_charset_for_format(fmt)
    tesseract_cmd = find_tesseract_cmd()
    if not tesseract_cmd:
        return {"ok": False, "error": "Tesseract wurde nicht gefunden.", "attempts": []}

    attempts: list[dict[str, Any]] = []
    best: dict[str, Any] | None = None
    scale = 1.0
    while scale <= max_scale + 1e-9:
        rect_exp = expand_rect(rect, scale, frame_wh)
        variants = _preprocess_variants(frame_rgb, rect_exp)
        variant_results = []
        for variant_name, image in variants.items():
            ocr = _run_tesseract_tsv(image, charset, tmp_root=tmp_root, tesseract_cmd=tesseract_cmd)
            score = len(str(ocr.get("text", ""))) + 5.0 * float(ocr.get("confidence", 0.0))
            ok, value = validate_formatted(str(ocr.get("text", "")), fmt, pattern)
            item = {
                "variant": variant_name,
                "raw": ocr.get("text", ""),
                "confidence": float(ocr.get("confidence", 0.0)),
                "score": float(score),
                "valid": bool(ok),
                "value": value,
                "error": ocr.get("error", ""),
            }
            variant_results.append(item)
            if best is None or item["score"] > best["score"]:
                best = {**item, "scale": round(scale, 2), "rect": rect_exp}
        chosen = max(variant_results, key=lambda item: item["score"])
        attempts.append({"scale": round(scale, 2), "rect": rect_exp, "chosen": chosen, "variants": variant_results})
        if chosen["valid"]:
            return {
                "ok": True,
                "value": chosen["value"],
                "raw": chosen["raw"],
                "confidence": chosen["confidence"],
                "scale": round(scale, 2),
                "variant": chosen["variant"],
                "rect": rect_exp,
                "charset": charset,
                "attempts": attempts,
                "matlab_reference": "OCRExtractor.m: expandRect -> imcrop -> imresize(2.0) -> imadjust -> imbinarize(adaptive,dark) -> OCR(frUp/bw) -> score -> validateFormatted",
            }
        scale = round(scale + 0.05, 10)

    return {
        "ok": False,
        "value": "",
        "raw": best.get("raw", "") if best else "",
        "confidence": best.get("confidence", 0.0) if best else 0.0,
        "scale": best.get("scale", 1.0) if best else 1.0,
        "variant": best.get("variant", "") if best else "",
        "rect": best.get("rect", tuple(rect)) if best else tuple(rect),
        "charset": charset,
        "attempts": attempts,
        "error": "Keine OCR-Variante passte zum Format/Pattern.",
        "matlab_reference": "OCRExtractor.m: expandRect -> imcrop -> imresize(2.0) -> imadjust -> imbinarize(adaptive,dark) -> OCR(frUp/bw) -> score -> validateFormatted",
    }
