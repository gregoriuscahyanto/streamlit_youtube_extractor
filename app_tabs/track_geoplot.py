"""Shared track geoplot helpers for Video OCR Full and Compare tabs."""
from __future__ import annotations
import math


def transform_centerline(centerline_px, minimap_pts, ref_pts) -> list | None:
    """Transform centerline from minimap pixel space to track_xy space via homography."""
    try:
        import cv2
        import numpy as np
        src = np.asarray(minimap_pts, dtype=np.float32).reshape(-1, 2)
        dst = np.asarray(ref_pts, dtype=np.float32).reshape(-1, 2)
        n = min(len(src), len(dst))
        if n < 4:
            return None
        H, _ = cv2.findHomography(src[:n], dst[:n])
        if H is None:
            return None
        cl = np.asarray(centerline_px, dtype=np.float32).reshape(-1, 1, 2)
        out = cv2.perspectiveTransform(cl, H)
        return out.reshape(-1, 2).tolist()
    except Exception:
        return None


def _tr(xs, ys):
    """Coordinate transform: swap x/y so track displays correctly (Döttinger Höhe at bottom)."""
    return list(ys), list(xs)


def _clean_centerline(centerline) -> "object | None":
    """Return a finite Nx2 centerline without duplicate consecutive points."""
    try:
        import numpy as np

        pts = np.asarray(centerline, dtype=float).reshape(-1, 2)
        pts = pts[np.isfinite(pts).all(axis=1)]
        if len(pts) < 2:
            return None

        keep = np.ones(len(pts), dtype=bool)
        keep[1:] = np.linalg.norm(np.diff(pts, axis=0), axis=1) > 1e-9
        pts = pts[keep]
        if len(pts) < 2:
            return None

        # Close the polyline only when its endpoints are already geometrically close.
        seg_len = np.linalg.norm(np.diff(pts, axis=0), axis=1)
        finite_seg = seg_len[np.isfinite(seg_len) & (seg_len > 1e-9)]
        median_seg = float(np.median(finite_seg)) if finite_seg.size else 1.0
        diag = float(np.linalg.norm(np.nanmax(pts, axis=0) - np.nanmin(pts, axis=0)))
        end_gap = float(np.linalg.norm(pts[-1] - pts[0]))
        close_tol = max(4.0 * median_seg, 0.025 * diag)
        if end_gap > 1e-9 and end_gap <= close_tol:
            pts = np.vstack([pts, pts[0]])
        return pts
    except Exception:
        return None


def _centerline_geometry(centerline):
    """Precompute segment geometry and cumulative arc length for a centerline."""
    import numpy as np

    pts = _clean_centerline(centerline)
    if pts is None or len(pts) < 2:
        return None
    a = pts[:-1]
    vec = pts[1:] - pts[:-1]
    seg_len = np.linalg.norm(vec, axis=1)
    valid = seg_len > 1e-9
    if not valid.all():
        a = a[valid]
        vec = vec[valid]
        seg_len = seg_len[valid]
        if len(seg_len) == 0:
            return None
        pts = np.vstack([a[0], a + vec])
    seg_len2 = seg_len * seg_len
    cum = np.concatenate(([0.0], np.cumsum(seg_len)))
    total = float(cum[-1])
    if not math.isfinite(total) or total <= 0:
        return None
    median_seg = float(np.median(seg_len)) if len(seg_len) else 1.0
    diag = float(np.linalg.norm(np.nanmax(pts, axis=0) - np.nanmin(pts, axis=0)))
    return {
        "pts": pts,
        "a": a,
        "vec": vec,
        "seg_len": seg_len,
        "seg_len2": seg_len2,
        "cum": cum,
        "total": total,
        "median_seg": median_seg,
        "diag": diag,
    }


def snap_trace_to_centerline(xs, ys, centerline) -> dict | None:
    """Project a measured XY trace onto a centerline.

    The projection is segment based, not nearest-vertex based. A continuity window
    around the previously selected centerline position prevents isolated points
    from jumping to a spatially close but topologically distant track section.

    Returns snapped ``xs``/``ys``, canonical centerline location ``s_ref`` and a
    monotonically increasing travelled coordinate ``s_progress`` in centerline
    coordinate units. ``indices`` maps the output points back to the raw trace.
    """
    import numpy as np

    geom = _centerline_geometry(centerline)
    if geom is None:
        return None

    x_arr = np.asarray(xs, dtype=float).ravel()
    y_arr = np.asarray(ys, dtype=float).ravel()
    n = min(len(x_arr), len(y_arr))
    if n == 0:
        return None

    a = geom["a"]
    vec = geom["vec"]
    seg_len = geom["seg_len"]
    seg_len2 = geom["seg_len2"]
    cum = geom["cum"]
    total = float(geom["total"])
    median_seg = float(geom["median_seg"])

    out_x: list[float] = []
    out_y: list[float] = []
    out_s: list[float] = []
    out_idx: list[int] = []
    prev_s: float | None = None

    # A 5 % arc-length neighbourhood is large enough for normal frame gaps but
    # small enough to reject most shortcuts between nearby Nordschleife sections.
    continuity_window = max(0.05 * total, 25.0 * median_seg)
    recovery_extra = max(8.0 * median_seg, 0.006 * max(float(geom["diag"]), 1.0))

    seg_mid_s = cum[:-1] + 0.5 * seg_len

    for raw_i in range(n):
        px = x_arr[raw_i]
        py = y_arr[raw_i]
        if not (np.isfinite(px) and np.isfinite(py)):
            continue
        p = np.array([px, py], dtype=float)
        ap = p - a
        t = np.einsum("ij,ij->i", ap, vec) / seg_len2
        t = np.clip(t, 0.0, 1.0)
        proj = a + t[:, None] * vec
        d2 = np.einsum("ij,ij->i", proj - p, proj - p)
        global_i = int(np.argmin(d2))
        chosen_i = global_i

        if prev_s is not None and len(seg_len) > 3:
            delta_s = np.abs(seg_mid_s - prev_s)
            delta_s = np.minimum(delta_s, np.maximum(0.0, total - delta_s))
            local_mask = delta_s <= continuity_window
            if local_mask.any():
                local_indices = np.flatnonzero(local_mask)
                local_i = int(local_indices[int(np.argmin(d2[local_mask]))])
                global_d = math.sqrt(max(float(d2[global_i]), 0.0))
                local_d = math.sqrt(max(float(d2[local_i]), 0.0))
                # Prefer topological continuity unless the local solution is
                # clearly geometrically implausible (large frame/data gap).
                if local_d <= max(global_d * 3.0, global_d + recovery_extra):
                    chosen_i = local_i

        tc = float(t[chosen_i])
        pc = proj[chosen_i]
        sc = float(cum[chosen_i] + tc * seg_len[chosen_i])
        if sc >= total:
            sc = 0.0
        out_x.append(float(pc[0]))
        out_y.append(float(pc[1]))
        out_s.append(sc)
        out_idx.append(raw_i)
        prev_s = sc

    if len(out_s) < 2:
        return None

    s_ref = np.asarray(out_s, dtype=float)
    wrapped_d = ((np.diff(s_ref) + 0.5 * total) % total) - 0.5 * total
    significant = wrapped_d[np.abs(wrapped_d) > max(1e-9, 0.25 * median_seg)]
    direction = 1.0
    if significant.size:
        direction = 1.0 if float(np.median(significant)) >= 0.0 else -1.0

    # Monotonic progress is intentionally separate from canonical s_ref. s_ref
    # identifies the same physical track location for every car; s_progress is
    # only used to judge coverage and to prevent backwards noise from accumulating.
    progress = np.zeros(len(s_ref), dtype=float)
    back_noise_tol = max(4.0 * median_seg, 0.003 * total)
    for i, d in enumerate(wrapped_d, start=1):
        advance = direction * float(d)
        if advance < 0.0:
            # Small backwards motion is projection noise. Large backwards jumps
            # are also rejected because vehicle progress around a lap is monotonic.
            advance = 0.0 if abs(advance) <= back_noise_tol else 0.0
        progress[i] = progress[i - 1] + advance

    return {
        "xs": out_x,
        "ys": out_y,
        "s_ref": s_ref.astype(float).tolist(),
        "s_progress": progress.astype(float).tolist(),
        "indices": out_idx,
        "centerline_length": total,
        "direction": int(direction),
    }


def _estimate_track_length_m(file_traces: list[dict]) -> float | None:
    """Estimate physical lap length from existing s_m traces when available."""
    try:
        import numpy as np

        lengths: list[float] = []
        for tr in file_traces:
            ps = np.asarray(tr.get("ps") or [], dtype=float)
            ps = ps[np.isfinite(ps)]
            if ps.size < 10:
                continue
            # Robust against a few offset/outlier samples.
            lo = float(np.percentile(ps, 1))
            hi = float(np.percentile(ps, 99))
            span = hi - lo
            if 1000.0 <= span <= 100000.0:
                lengths.append(span)
        return float(np.median(lengths)) if lengths else None
    except Exception:
        return None


def _sample_centerline(geom: dict, s_values):
    """Interpolate canonical XY coordinates at centerline arc-length positions."""
    import numpy as np

    s = np.asarray(s_values, dtype=float)
    total = float(geom["total"])
    s = np.clip(s, 0.0, total)
    cum = np.asarray(geom["cum"], dtype=float)
    pts = np.asarray(geom["pts"], dtype=float)
    # geom points and cumulative vector normally have identical length. Rebuild a
    # compatible point sequence defensively when duplicate segments were removed.
    if len(pts) != len(cum):
        pts = np.vstack([geom["a"][0], geom["a"] + geom["vec"]])
    x = np.interp(s, cum, pts[:, 0])
    y = np.interp(s, cum, pts[:, 1])
    return x, y


def _interp_trace_on_grid(s_loc, values, grid, period: float, full_lap: bool):
    """Interpolate one signal on a canonical track grid."""
    import numpy as np

    s = np.asarray(s_loc, dtype=float)
    v = np.asarray(values, dtype=float)
    ok = np.isfinite(s) & np.isfinite(v)
    s, v = s[ok], v[ok]
    if len(s) < 2:
        return np.full(len(grid), np.nan, dtype=float)

    order = np.argsort(s, kind="stable")
    s, v = s[order], v[order]

    # Average repeated/near-identical projected positions before interpolation.
    # Rounding is only for grouping; actual grid precision is much coarser (5 m).
    keys = np.round(s, 6)
    unique_keys, inv = np.unique(keys, return_inverse=True)
    if len(unique_keys) != len(s):
        sums = np.zeros(len(unique_keys), dtype=float)
        counts = np.zeros(len(unique_keys), dtype=float)
        loc_sums = np.zeros(len(unique_keys), dtype=float)
        for i, group in enumerate(inv):
            sums[group] += v[i]
            loc_sums[group] += s[i]
            counts[group] += 1.0
        s = loc_sums / np.maximum(counts, 1.0)
        v = sums / np.maximum(counts, 1.0)

    if len(s) < 2:
        return np.full(len(grid), np.nan, dtype=float)

    if full_lap and period > 0:
        # Periodic extension makes the start/finish transition continuous even if
        # the arbitrary centerline index zero lies inside the recorded lap.
        s_ext = np.concatenate([s - period, s, s + period])
        v_ext = np.concatenate([v, v, v])
        return np.interp(grid, s_ext, v_ext).astype(float)

    return np.interp(grid, s, v, left=np.nan, right=np.nan).astype(float)


def align_traces_to_centerline(file_traces: list[dict], grid_step_m: float = 5.0) -> list[dict]:
    """Snap comparison traces to one canonical centerline and common s grid.

    The canonical line comes from the reference-track centerline stored in the
    result files, not from any vehicle trajectory. When ``s_m`` data is present,
    the canonical arc length is scaled to a robust physical lap-length estimate
    and all signals are interpolated onto a common 5 m grid.
    """
    import numpy as np

    if len(file_traces) < 2:
        return file_traces

    candidates = []
    for tr in file_traces:
        cl = _clean_centerline(tr.get("centerline"))
        if cl is not None and len(cl) >= 2:
            candidates.append(cl)
    if not candidates:
        return file_traces

    # The stored centerline is a reference-track object. Prefer the densest copy
    # available among the selected result files; no vehicle trajectory is used as
    # the geometric truth.
    canonical = max(candidates, key=len)
    geom = _centerline_geometry(canonical)
    if geom is None:
        return file_traces
    ref_len = float(geom["total"])

    snapped_entries: list[tuple[dict, dict | None]] = []
    for tr in file_traces:
        snapped_entries.append((tr, snap_trace_to_centerline(tr.get("xs") or [], tr.get("ys") or [], canonical)))

    if not any(snap is not None for _, snap in snapped_entries):
        return file_traces

    track_length_m = _estimate_track_length_m(file_traces)
    if track_length_m is not None and track_length_m > 0:
        step_m = max(1.0, float(grid_step_m))
        grid_metric = np.arange(0.0, track_length_m + 0.5 * step_m, step_m, dtype=float)
        grid_ref = grid_metric / track_length_m * ref_len
        grid_label = "s_m"
    else:
        # Generic fallback for tracks without a usable distance channel: common
        # normalized centerline grid. This still guarantees identical XY geometry.
        n_grid = max(500, min(4000, int(max(len(canonical) * 2, 500))))
        grid_ref = np.linspace(0.0, ref_len, n_grid, endpoint=False, dtype=float)
        grid_metric = grid_ref.copy()
        track_length_m = None
        grid_label = "s_ref"

    gx, gy = _sample_centerline(geom, grid_ref)
    out: list[dict] = []

    for tr, snap in snapped_entries:
        tr_out = dict(tr)
        tr_out["centerline"] = canonical.astype(float).tolist()
        if snap is None:
            out.append(tr_out)
            continue

        raw_indices = snap["indices"]
        s_ref = np.asarray(snap["s_ref"], dtype=float)
        if track_length_m is not None:
            s_loc = s_ref / ref_len * track_length_m
            progress = np.asarray(snap["s_progress"], dtype=float) / ref_len * track_length_m
            period = float(track_length_m)
            full_lap = bool(len(progress) >= 10 and float(progress[-1] - progress[0]) >= 0.65 * period)
        else:
            s_loc = s_ref
            progress = np.asarray(snap["s_progress"], dtype=float)
            period = ref_len
            full_lap = bool(len(progress) >= 10 and float(progress[-1] - progress[0]) >= 0.65 * period)

        cs_raw = tr.get("cs")
        if cs_raw is not None:
            selected_cs: list[float] = []
            for raw_i in raw_indices:
                try:
                    val = cs_raw[raw_i]
                    selected_cs.append(float(val) if val not in (None, "") else float("nan"))
                except (IndexError, TypeError, ValueError):
                    selected_cs.append(float("nan"))
            grid_cs = _interp_trace_on_grid(s_loc, selected_cs, grid_metric, period, full_lap)
            tr_out["cs"] = grid_cs.astype(float).tolist()
        else:
            tr_out["cs"] = None

        tr_out["xs"] = gx.astype(float).tolist()
        tr_out["ys"] = gy.astype(float).tolist()
        tr_out["snap_s"] = grid_metric.astype(float).tolist()
        tr_out["snap_s_label"] = grid_label
        tr_out["snap_track_length_m"] = float(track_length_m) if track_length_m is not None else None
        tr_out["snap_grid_step_m"] = float(grid_step_m) if track_length_m is not None else None
        tr_out["snap_full_lap"] = full_lap
        out.append(tr_out)

    return out


def make_geoplot_figure(traces: list[dict], centerline_xy: list | None = None, template: str = "plotly_dark"):
    """
    Build a Plotly figure for track position.

    traces: [{"name": str, "xs": list, "ys": list, "ts": list | None}]
    centerline_xy: [[x, y], ...] from transform_centerline, or None
    """
    import plotly.graph_objects as go

    fig = go.Figure()

    if centerline_xy and len(centerline_xy) >= 2:
        cx, cy = _tr([p[0] for p in centerline_xy], [p[1] for p in centerline_xy])
        fig.add_trace(go.Scatter(
            x=cx, y=cy,
            mode="lines",
            name="Centerline",
            line=dict(color="rgba(180,180,180,0.35)", width=1.5, dash="dot"),
            hoverinfo="skip",
        ))

    for tr in traces:
        xs = tr.get("xs") or []
        ys = tr.get("ys") or []
        ts = tr.get("ts") or [None] * len(xs)
        if not xs or not ys or len(xs) != len(ys):
            continue
        vx, vy, vt = [], [], []
        for x, y, t in zip(xs, ys, ts):
            if isinstance(x, float) and math.isnan(x):
                continue
            if isinstance(y, float) and math.isnan(y):
                continue
            vx.append(x)
            vy.append(y)
            vt.append(t)
        if not vx:
            continue
        vx_t, vy_t = _tr(vx, vy)
        hover = [
            f"t={t:.2f}s" if isinstance(t, (int, float)) and not math.isnan(float(t)) else ""
            for t in vt
        ]
        fig.add_trace(go.Scatter(
            x=vx_t, y=vy_t,
            mode="markers+lines",
            name=tr["name"],
            text=hover,
            hovertemplate="%{text}<extra>%{fullData.name}</extra>",
            marker=dict(size=4),
            line=dict(width=1),
        ))

    _light = "dark" not in template
    fig.update_layout(
        xaxis=dict(scaleanchor="y", scaleratio=1, title="X"),
        yaxis=dict(title="Y"),
        template=template,
        paper_bgcolor="white" if _light else "#0e1117",
        plot_bgcolor="white" if _light else "#0e1117",
        font_color="black" if _light else "white",
        height=420,
        margin=dict(l=40, r=20, t=10, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def _wrap_title(s: str, width: int = 28) -> str:
    """Wrap a title string at word boundaries using <br> for Plotly HTML annotations."""
    words = s.split()
    lines: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for w in words:
        extra = len(w) + (1 if cur else 0)
        if cur_len + extra > width and cur:
            lines.append(" ".join(cur))
            cur, cur_len = [w], len(w)
        else:
            cur.append(w)
            cur_len += extra
    if cur:
        lines.append(" ".join(cur))
    return "<br>".join(lines)


def make_geoplot_tiled(
    file_traces: list[dict],
    color_col: str | None = None,
    colorscale: str | None = None,
    is_delta: bool = False,
    template: str = "plotly_dark",
):
    """Tiled geoplot: one subplot per file, all in a single row.

    With two or more traces, vehicle XY points are snapped to one canonical
    reference centerline and resampled on a common 5 m grid when a physical
    distance estimate is available.
    """
    from plotly.subplots import make_subplots
    import plotly.graph_objects as go

    n = len(file_traces)
    if n == 0:
        return go.Figure()

    if n > 1:
        try:
            file_traces = align_traces_to_centerline(file_traces, grid_step_m=5.0)
        except Exception:
            # Comparison must remain usable even with malformed legacy track data.
            pass

    wrapped_titles = [_wrap_title(tr["name"]) for tr in file_traces]
    max_lines = max(t.count("<br>") + 1 for t in wrapped_titles)
    top_margin = 30 + max_lines * 18

    fig = make_subplots(rows=1, cols=n, subplot_titles=wrapped_titles)

    # ── Global color range (shared colorbar) ──────────────────────────────────
    all_cv: list[float] = []
    for tr in file_traces:
        for v in (tr.get("cs") or []):
            try:
                f = float(v)
                if not math.isnan(f):
                    all_cv.append(f)
            except (TypeError, ValueError):
                pass
    cmin = min(all_cv) if all_cv else None
    cmax = max(all_cv) if all_cv else None

    if is_delta and all_cv:
        import numpy as _np
        _arr = _np.array(all_cv, dtype=float)
        _arr = _arr[_np.isfinite(_arr)]
        if len(_arr) >= 4:
            abs_max = float(max(abs(_np.percentile(_arr, 2)), abs(_np.percentile(_arr, 98))))
        else:
            abs_max = max(abs(cmin), abs(cmax))
        cmin, cmax = -abs_max, abs_max
        _cs = colorscale or "RdYlGn"
    else:
        _cs = colorscale or "Viridis"

    # ── Traces ────────────────────────────────────────────────────────────────
    for col_i, tr in enumerate(file_traces, 1):
        cl = tr.get("centerline")
        if cl and len(cl) >= 2:
            cx, cy = _tr([p[0] for p in cl], [p[1] for p in cl])
            fig.add_trace(go.Scattergl(
                x=cx, y=cy,
                mode="lines",
                line=dict(color="rgba(180,180,180,0.4)", dash="dot", width=1.5),
                name="Centerline", showlegend=(col_i == 1),
                legendgroup="centerline", hoverinfo="skip",
            ), row=1, col=col_i)

        xs = tr.get("xs") or []
        ys = tr.get("ys") or []
        cs_raw = tr.get("cs")
        snap_s = tr.get("snap_s") or []
        snap_s_label = tr.get("snap_s_label") or ""
        vx, vy, vc, vs = [], [], [], []
        for ip, (x, y) in enumerate(zip(xs, ys)):
            try:
                if math.isnan(float(x)) or math.isnan(float(y)):
                    continue
            except (TypeError, ValueError):
                continue
            vx.append(x)
            vy.append(y)
            if ip < len(snap_s):
                try:
                    vs.append(float(snap_s[ip]))
                except (TypeError, ValueError):
                    vs.append(float("nan"))
            else:
                vs.append(float("nan"))
            if cs_raw is not None and ip < len(cs_raw):
                try:
                    vc.append(float(cs_raw[ip]) if cs_raw[ip] not in (None, "") else float("nan"))
                except (TypeError, ValueError):
                    vc.append(float("nan"))

        vx_t, vy_t = _tr(vx, vy)
        show_colorbar = bool(color_col and vc and col_i == n)
        hovertemplate = None
        customdata = None
        if vs and snap_s_label == "s_m":
            customdata = vs
            hovertemplate = "s=%{customdata:.0f} m<extra></extra>"

        if color_col and vc:
            fig.add_trace(go.Scattergl(
                x=vx_t, y=vy_t, mode="markers",
                name=tr["name"], showlegend=False,
                customdata=customdata,
                hovertemplate=hovertemplate,
                marker=dict(
                    color=vc, colorscale=_cs, cmin=cmin, cmax=cmax, size=4,
                    showscale=show_colorbar,
                    colorbar=dict(
                        title=dict(text=color_col, side="right"),
                        thickness=14, len=0.8,
                        tickformat=".1f",
                    ) if show_colorbar else None,
                ),
            ), row=1, col=col_i)
        else:
            fig.add_trace(go.Scattergl(
                x=vx_t, y=vy_t, mode="lines+markers",
                name=tr["name"], showlegend=False,
                customdata=customdata,
                hovertemplate=hovertemplate,
                marker=dict(size=3, color="#555555"),
                line=dict(width=1, color="#555555"),
            ), row=1, col=col_i)

    # ── Axes: equal aspect + no gridlines + zoom sync ────────────────────────
    _ax_color = "black" if "dark" not in template else "white"
    fig.update_xaxes(showgrid=False, zeroline=False,
                     tickfont_color=_ax_color, title_font_color=_ax_color,
                     linecolor=_ax_color, tickcolor=_ax_color)
    fig.update_yaxes(showgrid=False, zeroline=False,
                     tickfont_color=_ax_color, title_font_color=_ax_color,
                     linecolor=_ax_color, tickcolor=_ax_color)
    fig.update_xaxes(scaleanchor="y", scaleratio=1, row=1, col=1)
    for col_i in range(2, n + 1):
        fig.update_xaxes(matches="x", row=1, col=col_i)
        fig.update_yaxes(matches="y", row=1, col=col_i)

    _light = "dark" not in template
    _fc = "black" if _light else "white"
    fig.update_layout(
        template=template,
        paper_bgcolor="white" if _light else "#0e1117",
        plot_bgcolor="white" if _light else "#0e1117",
        font_color=_fc,
        height=500 + (max_lines - 1) * 18,
        margin=dict(l=40, r=90, t=top_margin, b=40),
    )
    # Subplot titles use annotations
    for ann in fig.layout.annotations:
        ann.font.color = _fc
    return fig
