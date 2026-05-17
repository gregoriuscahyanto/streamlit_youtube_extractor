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
