"""Pure vehicle dynamics helpers for comparison workflows."""

from __future__ import annotations

import math

import numpy as np


def _series(data: dict[str, list], names: tuple[str, ...]) -> tuple[str, np.ndarray] | tuple[None, None]:
    for name in names:
        vals = data.get(name)
        if vals is None:
            continue
        try:
            arr = np.asarray(vals, dtype=float).ravel()
        except Exception:
            continue
        if arr.size and np.isfinite(arr).any():
            return name, arr
    return None, None


def _fill(arr: np.ndarray) -> np.ndarray | None:
    arr = np.asarray(arr, dtype=float).ravel()
    if arr.size == 0:
        return None
    ok = np.isfinite(arr)
    if ok.sum() == 0:
        return None
    if ok.sum() < arr.size:
        idx = np.arange(arr.size)
        arr = np.interp(idx, idx[ok], arr[ok])
    return arr.astype(float)


def _smooth(arr: np.ndarray, window: int) -> np.ndarray:
    window = int(window or 1)
    if window <= 1 or arr.size < 3:
        return arr
    if window % 2 == 0:
        window += 1
    window = min(window, arr.size if arr.size % 2 else arr.size - 1)
    if window < 3:
        return arr
    pad = window // 2
    padded = np.pad(arr, (pad, pad), mode="edge")
    kernel = np.ones(window, dtype=float) / float(window)
    return np.convolve(padded, kernel, mode="valid")


def _speed_mps(data: dict[str, list]) -> np.ndarray | None:
    name, arr = _series(data, ("v_Fzg_kmph", "v_fzg_kmph", "speed_kmph", "v_kmph", "v_Fzg_mph", "v_fzg_mph"))
    if arr is None:
        return None
    arr = _fill(arr)
    if arr is None:
        return None
    if name and "kmph" not in name.lower() and name.lower().endswith("mph"):
        arr = arr * 1.60934
    return arr / 3.6


def _lat_lon_to_m(lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    lat0 = math.radians(float(lat[0]))
    r = 6371000.0
    x = np.radians(lon - lon[0]) * math.cos(lat0) * r
    y = np.radians(lat - lat[0]) * r
    return x.astype(float), y.astype(float)


def _track_m(data: dict[str, list], cfg: dict) -> tuple[np.ndarray | None, np.ndarray | None, str | None]:
    force_track = str(cfg.get("gg_source") or "").strip().lower() == "track_xy"
    if not force_track:
        for xs_name, ys_name in (("gps_x_m", "gps_y_m"), ("x_m", "y_m"), ("track_x_m", "track_y_m")):
            _, xs = _series(data, (xs_name,))
            _, ys = _series(data, (ys_name,))
            if xs is not None and ys is not None:
                return _fill(xs), _fill(ys), f"{xs_name}/{ys_name}"
        _, lat = _series(data, ("lat", "latitude", "gps_lat"))
        _, lon = _series(data, ("lon", "longitude", "gps_lon"))
        if lat is not None and lon is not None:
            lat_f, lon_f = _fill(lat), _fill(lon)
            if lat_f is not None and lon_f is not None:
                return (*_lat_lon_to_m(lat_f, lon_f), "lat/lon")

    _, xs = _series(data, ("track_xy_x",))
    _, ys = _series(data, ("track_xy_y",))
    if xs is None or ys is None:
        return None, None, None
    xs_f, ys_f = _fill(xs), _fill(ys)
    if xs_f is None or ys_f is None:
        return None, None, None
    scale = float(cfg.get("gg_m_per_px") if cfg.get("gg_m_per_px") is not None else 1.0)
    return xs_f * scale, ys_f * scale, "track_xy"


def _curvature(x: np.ndarray, y: np.ndarray, t: np.ndarray) -> np.ndarray:
    dx = np.gradient(x, t, edge_order=1)
    dy = np.gradient(y, t, edge_order=1)
    ddx = np.gradient(dx, t, edge_order=1)
    ddy = np.gradient(dy, t, edge_order=1)
    denom = np.power(dx * dx + dy * dy, 1.5)
    out = np.full(x.size, np.nan, dtype=float)
    ok = np.isfinite(denom) & (denom > 1e-9)
    out[ok] = (dx[ok] * ddy[ok] - dy[ok] * ddx[ok]) / denom[ok]
    filled = _fill(out)
    return filled if filled is not None else np.zeros(x.size, dtype=float)


def add_gg_dynamics(data: dict[str, list], cfg: dict) -> tuple[bool, list[str]]:
    """Add gx_g/gy_g columns to data in-place from OCR speed and GPS/track path."""
    if not cfg.get("enable_gg_dynamics"):
        return True, []
    _, t_raw = _series(data, ("time_s", "t_s", "audio_time_s"))
    v = _speed_mps(data)
    x_m, y_m, source = _track_m(data, cfg)
    missing = []
    if t_raw is None:
        missing.append("time_s")
    if v is None:
        missing.append("v_Fzg_kmph")
    if x_m is None or y_m is None:
        missing.append("GPS/Meterdaten oder track_xy_x/y")
    if missing:
        return False, missing

    t = _fill(t_raw)
    if t is None:
        return False, ["gueltige Zeitachse"]
    n = min(t.size, v.size, x_m.size, y_m.size)
    if n < 3:
        return False, ["mindestens drei Punkte"]
    t, v, x_m, y_m = t[:n], v[:n], x_m[:n], y_m[:n]
    order = np.argsort(t, kind="stable")
    inv = np.empty_like(order)
    inv[order] = np.arange(order.size)
    t_s, v_s, x_s, y_s = t[order], v[order], x_m[order], y_m[order]
    for i in range(1, t_s.size):
        if t_s[i] <= t_s[i - 1]:
            t_s[i] = t_s[i - 1] + 1e-6

    win = int(cfg.get("gg_smooth_window") or 5)
    v_s = _smooth(v_s, win)
    x_s = _smooth(x_s, win)
    y_s = _smooth(y_s, win)
    g = float(cfg.get("g") if cfg.get("g") is not None else 9.81)
    gx = np.gradient(v_s, t_s, edge_order=1) / g
    curv = _curvature(x_s, y_s, t_s)
    gy = (v_s * v_s * curv) / g

    data["gx_g"] = gx[inv].astype(float).tolist()
    data["gy_g"] = gy[inv].astype(float).tolist()
    data["curvature_1pm"] = curv[inv].astype(float).tolist()
    data["track_x_m"] = x_s[inv].astype(float).tolist()
    data["track_y_m"] = y_s[inv].astype(float).tolist()
    data["gg_source"] = [source or ""] * n
    return True, []
