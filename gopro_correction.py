"""GoPro video correction helpers used from ROI setup."""

from __future__ import annotations

from pathlib import Path
import time

import cv2
import numpy as np


def _emit_progress(progress_cb, msg: str, pct: float, eta_s: float | None) -> None:
    if not callable(progress_cb):
        return
    try:
        progress_cb(msg, pct, eta_s)
    except TypeError:
        progress_cb(msg)


def _undistort_wide_frame(frame: np.ndarray, k1: float = -0.48) -> np.ndarray:
    h, w = frame.shape[:2]
    fx = float(w) * 0.58
    fy = float(h) * 0.58
    cam = np.array([[fx, 0.0, w / 2.0], [0.0, fy, h / 2.0], [0.0, 0.0, 1.0]], dtype=np.float32)
    dist = np.array([float(k1), 0.18, 0.0, 0.0, -0.08], dtype=np.float32)
    new_cam, _roi = cv2.getOptimalNewCameraMatrix(cam, dist, (w, h), 0.0, (w, h))
    return cv2.undistort(frame, cam, dist, None, new_cam)


def _perspective_raise_camera(frame: np.ndarray, perspective_strength: float = 0.18) -> np.ndarray:
    strength = float(np.clip(perspective_strength, -1.50, 1.50))
    if abs(strength) < 1e-6:
        return frame
    h, w = frame.shape[:2]
    top_pull = float(w) * 0.22 * max(strength, 0.0)
    bottom_push = float(w) * 0.62 * abs(strength)
    y_raise = float(h) * 0.34 * strength
    src = np.float32([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]])
    dst = np.float32(
        [
            [top_pull, max(0.0, y_raise)],
            [w - 1 - top_pull, max(0.0, y_raise)],
            [w - 1 + bottom_push, h - 1],
            [-bottom_push, h - 1],
        ]
    )
    mat = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(frame, mat, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def _rotate_frame(
    frame: np.ndarray,
    rotation_deg: float = 0.0,
    rotation_center_x: float = 0.5,
    rotation_center_y: float = 0.5,
) -> np.ndarray:
    angle = float(rotation_deg or 0.0)
    if abs(angle) < 1e-6:
        return frame
    h, w = frame.shape[:2]
    cx = float(np.clip(rotation_center_x, 0.0, 1.0)) * float(w)
    cy = float(np.clip(rotation_center_y, 0.0, 1.0)) * float(h)
    mat = cv2.getRotationMatrix2D((cx, cy), angle, 1.0)
    return cv2.warpAffine(frame, mat, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def _manual_shift_frame(frame: np.ndarray, manual_shift_x_px: float = 0.0, manual_shift_y_px: float = 0.0) -> np.ndarray:
    dx = float(manual_shift_x_px or 0.0)
    dy = float(manual_shift_y_px or 0.0)
    if abs(dx) < 1e-6 and abs(dy) < 1e-6:
        return frame
    h, w = frame.shape[:2]
    mat = np.array([[1.0, 0.0, dx], [0.0, 1.0, dy]], dtype=np.float32)
    return cv2.warpAffine(frame, mat, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def _gray_for_shift(frame: np.ndarray, size: tuple[int, int] = (640, 360)) -> np.ndarray:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]
    x0 = int(w * 0.06)
    x1 = int(w * 0.94)
    y0 = int(h * 0.06)
    y1 = int(h * 0.94)
    crop = gray[y0:y1, x0:x1]
    small = cv2.resize(crop, size, interpolation=cv2.INTER_AREA)
    return np.asarray(small, dtype=np.float32)


def _small_gray_for_warp(frame: np.ndarray, max_w: int = 960) -> tuple[np.ndarray, float]:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]
    if w <= max_w:
        return gray, 1.0
    scale = float(w) / float(max_w)
    small_h = max(1, int(round(h / scale)))
    return cv2.resize(gray, (max_w, small_h), interpolation=cv2.INTER_AREA), scale


def _estimate_warp_affine(ref_frame: np.ndarray, cur_frame: np.ndarray) -> tuple[np.ndarray | None, bool]:
    ref, scale = _small_gray_for_warp(ref_frame)
    cur, _scale_cur = _small_gray_for_warp(cur_frame)
    try:
        orb = cv2.ORB_create(900)
        kp_ref, des_ref = orb.detectAndCompute(ref, None)
        kp_cur, des_cur = orb.detectAndCompute(cur, None)
        if des_ref is None or des_cur is None or len(kp_ref) < 24 or len(kp_cur) < 24:
            return None, False
        matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        matches = sorted(matcher.match(des_cur, des_ref), key=lambda m: m.distance)[:180]
        if len(matches) < 18:
            return None, False
        src = np.float32([kp_cur[m.queryIdx].pt for m in matches]).reshape(-1, 1, 2)
        dst = np.float32([kp_ref[m.trainIdx].pt for m in matches]).reshape(-1, 1, 2)
        mat, inliers = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=4.0)
        if mat is None or inliers is None or int(np.sum(inliers)) < 10:
            return None, False
        mat = np.asarray(mat, dtype=np.float32)
        mat[0, 2] *= scale
        mat[1, 2] *= scale
        return mat, True
    except Exception:
        return None, False


def _estimate_shift_matrix(
    ref_frame: np.ndarray,
    cur_frame: np.ndarray,
    shift_gain: float = 2.2,
    max_shift_px: float = 360.0,
) -> tuple[np.ndarray, tuple[float, float], bool]:
    ref = _gray_for_shift(ref_frame)
    cur = _gray_for_shift(cur_frame)
    (dx_small, dy_small), response = cv2.phaseCorrelate(ref, cur)
    scale_x = cur_frame.shape[1] * 0.88 / 640.0
    scale_y = cur_frame.shape[0] * 0.88 / 360.0
    dx = float(np.clip(dx_small * scale_x * shift_gain, -max_shift_px, max_shift_px))
    dy = float(np.clip(dy_small * scale_y * shift_gain, -max_shift_px, max_shift_px))
    valid = bool(response >= 0.018)
    if not valid:
        dx, dy = 0.0, 0.0
    mat = np.array([[1.0, 0.0, -dx], [0.0, 1.0, -dy]], dtype=np.float32)
    return mat, (dx, dy), valid


def apply_gopro_corrections_to_frame(
    frame: np.ndarray,
    ref_frame: np.ndarray | None = None,
    *,
    apply_wide: bool = True,
    apply_shift: bool = True,
    apply_warp: bool = True,
    wide_k1: float = -0.48,
    shift_gain: float = 2.2,
    max_shift_px: float = 360.0,
    perspective_strength: float = 0.18,
    rotation_deg: float = 0.0,
    rotation_center_x: float = 0.5,
    rotation_center_y: float = 0.5,
    manual_shift_x_px: float = 0.0,
    manual_shift_y_px: float = 0.0,
) -> tuple[np.ndarray, dict]:
    corr = _undistort_wide_frame(frame, k1=float(wide_k1)) if apply_wide else frame.copy()
    corr = _rotate_frame(
        corr,
        rotation_deg=float(rotation_deg),
        rotation_center_x=float(rotation_center_x),
        rotation_center_y=float(rotation_center_y),
    )
    if apply_warp:
        corr = _perspective_raise_camera(corr, perspective_strength=float(perspective_strength))
    meta = {"warp_used": False, "shift_used": False, "shift": (0.0, 0.0)}
    if ref_frame is not None:
        mat = None
        if apply_warp:
            mat, ok_warp = _estimate_warp_affine(ref_frame, corr)
            if ok_warp:
                meta["warp_used"] = True
        if mat is None and apply_shift:
            mat, shift, ok_shift = _estimate_shift_matrix(
                ref_frame,
                corr,
                shift_gain=float(shift_gain),
                max_shift_px=float(max_shift_px),
            )
            meta["shift"] = shift
            if ok_shift:
                meta["shift_used"] = True
        if mat is not None:
            h, w = corr.shape[:2]
            corr = cv2.warpAffine(corr, mat, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    corr = _manual_shift_frame(corr, manual_shift_x_px=float(manual_shift_x_px), manual_shift_y_px=float(manual_shift_y_px))
    meta["manual_shift_x_px"] = float(manual_shift_x_px)
    meta["manual_shift_y_px"] = float(manual_shift_y_px)
    return corr, meta


def run_gopro_correction_2fps(
    src_video: Path | str,
    out_video: Path | str,
    trim_start_s: float,
    trim_end_s: float | None,
    *,
    apply_wide: bool = True,
    apply_shift: bool = True,
    apply_warp: bool = True,
    wide_k1: float = -0.48,
    shift_gain: float = 2.2,
    max_shift_px: float = 360.0,
    perspective_strength: float = 0.18,
    rotation_deg: float = 0.0,
    rotation_center_x: float = 0.5,
    rotation_center_y: float = 0.5,
    manual_shift_x_px: float = 0.0,
    manual_shift_y_px: float = 0.0,
    target_fps: float = 2.0,
    progress_cb=None,
) -> tuple[bool, str, dict]:
    src = Path(src_video)
    out = Path(out_video)
    cap = cv2.VideoCapture(str(src))
    if not cap.isOpened():
        return False, f"Video konnte nicht geoeffnet werden: {src}", {}
    src_fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    total_frames = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
    duration = total_frames / src_fps if src_fps > 0 and total_frames > 0 else 0.0
    start_s = max(0.0, float(trim_start_s or 0.0))
    end_s = float(trim_end_s) if trim_end_s is not None else (duration if duration > 0 else start_s)
    if end_s <= start_s:
        cap.release()
        return False, "Ungueltiger Zeitraum fuer GoPro-Korrektur.", {}

    target_fps = float(target_fps or 2.0)
    expected_frames = max(1, int(np.ceil((end_s - start_s) * target_fps)))
    started_at = time.monotonic()
    cap.set(cv2.CAP_PROP_POS_MSEC, start_s * 1000.0)
    ok, frame0 = cap.read()
    if not ok or frame0 is None:
        cap.release()
        return False, "Startframe konnte nicht gelesen werden.", {}
    frame0, _meta0 = apply_gopro_corrections_to_frame(
        frame0,
        None,
        apply_wide=apply_wide,
        apply_shift=False,
        apply_warp=apply_warp,
        wide_k1=wide_k1,
        shift_gain=shift_gain,
        max_shift_px=max_shift_px,
        perspective_strength=perspective_strength,
        rotation_deg=rotation_deg,
        rotation_center_x=rotation_center_x,
        rotation_center_y=rotation_center_y,
        manual_shift_x_px=manual_shift_x_px,
        manual_shift_y_px=manual_shift_y_px,
    )
    h, w = frame0.shape[:2]
    out.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"MJPG"), target_fps, (w, h))
    if not writer.isOpened():
        cap.release()
        return False, f"VideoWriter konnte nicht geoeffnet werden: {out}", {}

    ref_frame = frame0.copy()
    frames_written = 0
    warp_used = 0
    shift_used = 0
    shifts: list[tuple[float, float]] = []
    t = start_s
    while t < end_s:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
        ok, frame = cap.read()
        if not ok or frame is None:
            break
        corr, frame_meta = apply_gopro_corrections_to_frame(
            frame,
            ref_frame,
            apply_wide=apply_wide,
            apply_shift=apply_shift,
            apply_warp=apply_warp,
            wide_k1=wide_k1,
            shift_gain=shift_gain,
            max_shift_px=max_shift_px,
            perspective_strength=perspective_strength,
            rotation_deg=rotation_deg,
            rotation_center_x=rotation_center_x,
            rotation_center_y=rotation_center_y,
            manual_shift_x_px=manual_shift_x_px,
            manual_shift_y_px=manual_shift_y_px,
        )
        if frame_meta.get("warp_used"):
            warp_used += 1
        if frame_meta.get("shift_used"):
            shift_used += 1
        shifts.append(tuple(frame_meta.get("shift", (0.0, 0.0))))
        writer.write(corr)
        frames_written += 1
        if frames_written == 1 or frames_written % 10 == 0:
            pct = min(1.0, float(frames_written) / float(expected_frames))
            elapsed = max(0.001, time.monotonic() - started_at)
            eta_s = (elapsed / max(pct, 1e-6)) - elapsed if pct < 1.0 else 0.0
            _emit_progress(
                progress_cb,
                f"GoPro-Korrektur laeuft ({frames_written}/{expected_frames} Frames, {pct * 100.0:.1f}%)",
                pct,
                eta_s,
            )
        t += 1.0 / target_fps

    writer.release()
    cap.release()
    if frames_written <= 0:
        return False, "Keine Frames fuer GoPro-Korrektur geschrieben.", {}
    arr = np.asarray(shifts, dtype=float) if shifts else np.zeros((0, 2), dtype=float)
    meta = {
        "enabled": True,
        "wide_angle_correction": bool(apply_wide),
        "frame_stabilization": bool(apply_shift),
        "warp_stabilization": bool(apply_warp),
        "perspective_warp": bool(apply_warp),
        "distortion_k1": float(wide_k1),
        "shift_gain": float(shift_gain),
        "max_shift_px": float(max_shift_px),
        "perspective_strength": float(perspective_strength),
        "rotation_deg": float(rotation_deg),
        "rotation_center_x": float(rotation_center_x),
        "rotation_center_y": float(rotation_center_y),
        "manual_shift_x_px": float(manual_shift_x_px),
        "manual_shift_y_px": float(manual_shift_y_px),
        "target_fps": target_fps,
        "frames_written": int(frames_written),
        "expected_frames": int(expected_frames),
        "warp_used_frames": int(warp_used),
        "translation_used_frames": int(shift_used),
        "max_abs_shift_px": float(np.max(np.abs(arr))) if arr.size else 0.0,
        "mean_abs_shift_px": float(np.mean(np.abs(arr))) if arr.size else 0.0,
    }
    _emit_progress(progress_cb, "GoPro-Korrektur abgeschlossen (100.0%)", 1.0, 0.0)
    return True, "", meta
