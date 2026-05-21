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


def make_geoplot_figure(traces: list[dict], centerline_xy: list | None = None):
    """
    Build a Plotly figure for track position.

    traces: [{"name": str, "xs": list, "ys": list, "ts": list | None}]
    centerline_xy: [[x, y], ...] from transform_centerline, or None
    """
    import plotly.graph_objects as go

    fig = go.Figure()

    if centerline_xy and len(centerline_xy) >= 2:
        cx = [p[0] for p in centerline_xy]
        cy = [p[1] for p in centerline_xy]
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
        # drop NaN pairs
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
        hover = [
            f"t={t:.2f}s" if isinstance(t, (int, float)) and not math.isnan(float(t)) else ""
            for t in vt
        ]
        fig.add_trace(go.Scatter(
            x=vx, y=vy,
            mode="markers+lines",
            name=tr["name"],
            text=hover,
            hovertemplate="%{text}<extra>%{fullData.name}</extra>",
            marker=dict(size=4),
            line=dict(width=1),
        ))

    fig.update_layout(
        xaxis=dict(scaleanchor="y", scaleratio=1, title="X"),
        yaxis=dict(title="Y"),
        template="plotly_dark",
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
):
    """Tiled geoplot: one subplot per file, all in a single row.

    file_traces entries:
        name       str
        xs         list[float]        track_xy_x
        ys         list[float]        track_xy_y
        cs         list[float]|None   color variable (or delta values)
        centerline [[x,y],...]|None   centerline_px in pixel coords

    Features:
        - Shared colorbar with global cmin/cmax across all subplots
        - Y axis flipped (image pixel coords have Y=0 at top)
        - Synchronized zoom: zooming one subplot mirrors all others
        - Delta mode: diverging colorscale symmetric around zero
    """
    from plotly.subplots import make_subplots
    import plotly.graph_objects as go

    n = len(file_traces)
    if n == 0:
        return go.Figure()

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
        # Symmetric range around zero; diverging colorscale
        abs_max = max(abs(cmin), abs(cmax))
        cmin, cmax = -abs_max, abs_max
        _cs = colorscale or "RdYlGn"
    else:
        _cs = colorscale or "Viridis"

    # ── Traces ────────────────────────────────────────────────────────────────
    for col_i, tr in enumerate(file_traces, 1):
        cl = tr.get("centerline")
        if cl and len(cl) >= 2:
            fig.add_trace(go.Scattergl(
                x=[p[0] for p in cl], y=[p[1] for p in cl],
                mode="lines",
                line=dict(color="rgba(180,180,180,0.4)", dash="dot", width=1.5),
                name="Centerline", showlegend=(col_i == 1),
                legendgroup="centerline", hoverinfo="skip",
            ), row=1, col=col_i)

        xs = tr.get("xs") or []
        ys = tr.get("ys") or []
        cs_raw = tr.get("cs")
        vx, vy, vc = [], [], []
        for ip, (x, y) in enumerate(zip(xs, ys)):
            try:
                if math.isnan(float(x)) or math.isnan(float(y)):
                    continue
            except (TypeError, ValueError):
                continue
            vx.append(x)
            vy.append(y)
            if cs_raw is not None and ip < len(cs_raw):
                try:
                    vc.append(float(cs_raw[ip]) if cs_raw[ip] not in (None, "") else float("nan"))
                except (TypeError, ValueError):
                    vc.append(float("nan"))

        show_colorbar = bool(color_col and vc and col_i == n)
        if color_col and vc:
            fig.add_trace(go.Scattergl(
                x=vx, y=vy, mode="markers",
                name=tr["name"], showlegend=False,
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
                x=vx, y=vy, mode="lines+markers",
                name=tr["name"], showlegend=False,
                marker=dict(size=3), line=dict(width=1),
            ), row=1, col=col_i)

    # ── Axes: equal aspect + Y-flip + zoom sync ───────────────────────────────
    # Y=0 is at the top in minimap pixel coords → reverse Y to match real-world maps
    fig.update_yaxes(autorange="reversed")

    # Equal aspect ratio for subplot 1; linked subplots inherit via matches
    fig.update_xaxes(scaleanchor="y", scaleratio=1, row=1, col=1)
    # Sync zoom: all axes after col=1 match col=1
    for col_i in range(2, n + 1):
        fig.update_xaxes(matches="x", row=1, col=col_i)
        fig.update_yaxes(matches="y", row=1, col=col_i)

    fig.update_layout(
        template="plotly_dark",
        height=500 + (max_lines - 1) * 18,
        margin=dict(l=40, r=90, t=top_margin, b=40),
    )
    return fig
