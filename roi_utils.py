from __future__ import annotations


def clamp_roi_to_video(x: float, y: float, w: float, h: float, vid_w: int | float, vid_h: int | float):
    x = max(0.0, float(x))
    y = max(0.0, float(y))
    max_w = max(1.0, float(vid_w) - x) if vid_w else max(1.0, float(w))
    max_h = max(1.0, float(vid_h) - y) if vid_h else max(1.0, float(h))
    w = min(max(1.0, float(w)), max_w)
    h = min(max(1.0, float(h)), max_h)
    return x, y, w, h


def roi_from_crop_box(box: dict | None, vid_w: int | float, vid_h: int | float):
    if not isinstance(box, dict):
        return None
    bx = float(box.get("left", box.get("x", 0.0)) or 0.0)
    by = float(box.get("top", box.get("y", 0.0)) or 0.0)
    bw = float(box.get("width", 0.0) or 0.0)
    bh = float(box.get("height", 0.0) or 0.0)
    if bw < 1.0 or bh < 1.0:
        return None
    return clamp_roi_to_video(bx, by, bw, bh, vid_w, vid_h)


def can_add_roi_from_drag(drag_roi: dict | None) -> tuple[bool, str]:
    if not isinstance(drag_roi, dict):
        return False, "Bitte zuerst ROI per Maus ziehen."
    try:
        w = int(drag_roi.get("w", 0))
        h = int(drag_roi.get("h", 0))
    except Exception:
        return False, "Bitte zuerst ROI per Maus ziehen."
    if w < 1 or h < 1:
        return False, "Bitte zuerst ROI per Maus ziehen."
    return True, ""


def seed_drag_roi(vid_w: int | float, vid_h: int | float) -> dict:
    vw = max(1, int(round(float(vid_w or 1))))
    vh = max(1, int(round(float(vid_h or 1))))
    sw = max(32, int(round(vw * 0.20)))
    sh = max(24, int(round(vh * 0.18)))
    sx = max(0, int(round((vw - sw) / 2)))
    sy = max(0, int(round((vh - sh) / 2)))
    return {"x": sx, "y": sy, "w": sw, "h": sh}


def normalize_time_range(start_s: float, end_s: float, duration_s: float, fps: float) -> tuple[float, float]:
    dur = max(0.0, float(duration_s))
    min_gap = 1.0 / max(float(fps or 1.0), 1.0)
    end_v = float(min(max(float(end_s), min_gap), dur))
    start_v = float(min(max(float(start_s), 0.0), max(0.0, end_v - min_gap)))
    if start_v >= end_v:
        end_v = float(min(dur, start_v + min_gap))
    return start_v, end_v
