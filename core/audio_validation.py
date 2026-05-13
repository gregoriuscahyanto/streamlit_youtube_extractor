"""
audio_validation.py
Standalone RPM-Validierungslogik (kein Streamlit, testbar mit RTK/pytest).
"""

from __future__ import annotations

import io
import tempfile
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# MAT-Struktur rekursiv durchsuchen
# ---------------------------------------------------------------------------

def mat_collect_numeric_arrays(
    obj,
    prefix: str = "",
    result: dict | None = None,
    depth: int = 0,
    min_size: int = 2,
) -> dict[str, np.ndarray]:
    """Traverse a scipy.io.loadmat result and collect 1-D numeric arrays.

    Returns a flat dict {dot-separated-path: 1-D finite float64 array}
    containing only entries with at least *min_size* finite values.
    """
    if result is None:
        result = {}
    if depth > 12:
        return result

    # scipy mat_struct
    if hasattr(obj, "_fieldnames"):
        for field in (obj._fieldnames or []):
            key = f"{prefix}.{field}" if prefix else field
            mat_collect_numeric_arrays(getattr(obj, field, None), key, result, depth + 1, min_size)
        return result

    # plain dict
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).startswith("__"):
                continue
            key = f"{prefix}.{k}" if prefix else str(k)
            mat_collect_numeric_arrays(v, key, result, depth + 1, min_size)
        return result

    # numpy ndarray
    if isinstance(obj, np.ndarray):
        if obj.dtype.names:
            for name in obj.dtype.names:
                key = f"{prefix}.{name}" if prefix else name
                mat_collect_numeric_arrays(obj[name], key, result, depth + 1, min_size)
            return result
        if obj.dtype.kind == "O":
            flat = obj.ravel()
            if flat.size == 1:
                mat_collect_numeric_arrays(flat[0], prefix, result, depth + 1, min_size)
            return result
        try:
            finite = np.asarray(obj, dtype=float).ravel()
            finite = finite[np.isfinite(finite)]
            if finite.size >= min_size:
                result[prefix] = finite  # store only finite values
        except (TypeError, ValueError):
            pass

    return result


def dataframe_from_mat_bytes(raw: bytes) -> pd.DataFrame:
    """Parse raw .mat bytes into a DataFrame; column names are dot-separated paths."""
    import scipy.io as sio

    # v5 MAT: sio.loadmat accepts BytesIO directly — no temp file needed
    data: dict | None = None
    try:
        data = sio.loadmat(
            io.BytesIO(raw),
            squeeze_me=True,
            struct_as_record=False,
            verify_compressed_data_integrity=False,
        )
    except NotImplementedError:
        pass  # v7.3 HDF5 — fall through to temp-file path
    except Exception:
        return pd.DataFrame()

    if data is None:
        # v7.3 HDF5 requires a real file path
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mat")
        try:
            tmp.write(raw)
            tmp.close()
            try:
                import h5py
                data = _h5_to_dict(tmp.name)
            except Exception:
                return pd.DataFrame()
        finally:
            try:
                Path(tmp.name).unlink(missing_ok=True)
            except Exception:
                pass

    cols = mat_collect_numeric_arrays(data)
    if not cols:
        return pd.DataFrame()

    # Each column may have a different length (different sample rates / fields).
    # Build the DataFrame column-by-column so callers can see what's available.
    return pd.DataFrame({k: pd.array(v, dtype="float64") for k, v in cols.items()})


def _h5_to_dict(path: str) -> dict:
    """Minimal HDF5 group → dict converter (fallback for v7.3 MAT)."""
    import h5py

    def _visit(grp: h5py.Group) -> dict:
        out: dict = {}
        for k, v in grp.items():
            if isinstance(v, h5py.Dataset):
                try:
                    out[k] = np.array(v)
                except Exception:
                    pass
            elif isinstance(v, h5py.Group):
                sub = _visit(v)
                if sub:
                    out[k] = sub
        return out

    with h5py.File(path, "r") as f:
        return _visit(f)


def dataframe_from_upload(raw: bytes, filename: str) -> pd.DataFrame:
    """Universal parser: .mat / .csv / .xlsx / .xls → DataFrame."""
    name = filename.lower()
    if name.endswith(".csv"):
        return pd.read_csv(io.BytesIO(raw))
    if name.endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(raw))
    if name.endswith(".mat"):
        return dataframe_from_mat_bytes(raw)
    return pd.DataFrame()


# ---------------------------------------------------------------------------
# Kurvenbasierter RPM-Vergleich
# ---------------------------------------------------------------------------

def validation_metrics(
    t_audio: np.ndarray,
    rpm_audio: np.ndarray,
    t_ref: np.ndarray,
    y_ref: np.ndarray,
    shift_s: float = 0.0,
    mode: str = "Absolutwert",
) -> dict:
    """Compare two RPM curves via interpolation on the overlapping time window.

    The reference curve is shifted by *shift_s* seconds before comparison.
    Returns a dict with ok, shift_s, mae, rmse, median_abs, mape_pct,
    sum_abs_err (optimisation target), n, score, and error on failure.
    """
    ta = np.asarray(t_audio,  dtype=float).ravel()
    ra = np.asarray(rpm_audio, dtype=float).ravel()
    tr = np.asarray(t_ref,    dtype=float).ravel() + float(shift_s)
    yr = np.asarray(y_ref,    dtype=float).ravel()

    if ta.size == 0 or ra.size == 0 or tr.size == 0 or yr.size == 0:
        return {"ok": False, "error": "Leere Zeitreihe."}

    n = min(ta.size, ra.size)
    ta, ra = ta[:n], ra[:n]

    m  = np.isfinite(ta) & np.isfinite(ra)
    ta, ra = ta[m], ra[m]
    mr = np.isfinite(tr) & np.isfinite(yr)
    tr, yr = tr[mr], yr[mr]

    if ta.size < 2 or tr.size < 2:
        return {"ok": False, "error": "Zu wenige gueltige Punkte nach NaN-Filter."}

    order = np.argsort(tr)
    tr, yr = tr[order], yr[order]

    lo = max(float(ta.min()), float(tr.min()))
    hi = min(float(ta.max()), float(tr.max()))
    if hi <= lo:
        return {
            "ok": False,
            "error": (
                f"Keine ueberlappende Zeitspanne "
                f"(audio {ta.min():.1f}–{ta.max():.1f}s, "
                f"ref {tr.min():.1f}–{tr.max():.1f}s nach Versatz)."
            ),
        }

    keep = (ta >= lo) & (ta <= hi)
    if int(keep.sum()) < 2:
        return {"ok": False, "error": "Zu wenige Punkte im ueberlappenden Bereich."}

    ta2 = ta[keep]
    ra2 = ra[keep]
    yr_i = np.interp(ta2, tr, yr)  # finite by construction

    err     = ra2 - yr_i
    abs_err = np.abs(err)
    pct     = abs_err / np.maximum(np.abs(yr_i), 1.0) * 100.0

    use_pct = "Prozent" in str(mode)
    score   = float(np.mean(pct if use_pct else abs_err))

    return {
        "ok":          True,
        "shift_s":     float(shift_s),
        "mode":        str(mode),
        "score":       score,
        "mae":         float(np.mean(abs_err)),
        "rmse":        float(np.sqrt(np.mean(err ** 2))),
        "median_abs":  float(np.median(abs_err)),
        "mape_pct":    float(np.mean(pct)),
        "sum_abs_err": float(np.sum(abs_err)),
        "n":           int(ta2.size),
    }


def find_best_shift(
    t_audio: np.ndarray,
    rpm_audio: np.ndarray,
    t_ref: np.ndarray,
    y_ref: np.ndarray,
    mode: str = "Absolutwert",
    min_s: float = -5.0,
    max_s: float = 5.0,
    step_s: float = 0.05,
    progress_cb: Callable[[float, str], None] | None = None,
) -> tuple[dict, list[str]]:
    """Brute-force search for the time shift minimising *sum_abs_err*.

    Uses linspace (not arange) to avoid float-step accumulation errors.
    Returns (best_result_dict, debug_log_lines).
    """
    step = max(1e-6, abs(float(step_s)))
    n_steps = max(1, int(round((float(max_s) - float(min_s)) / step)) + 1)
    shifts = np.linspace(float(min_s), float(max_s), n_steps)

    best: dict | None = None
    log:  list[str]   = []
    total = int(shifts.size)

    for i, sh in enumerate(shifts, 1):
        cur = validation_metrics(t_audio, rpm_audio, t_ref, y_ref, float(sh), mode)
        if cur.get("ok") and (best is None or cur["sum_abs_err"] < best["sum_abs_err"]):
            best = cur
            if best["sum_abs_err"] == 0.0:
                log.append(f"Shift {sh:+.3f}s | sum_err=0 (perfekter Match) — Suche beendet.")
                if callable(progress_cb):
                    progress_cb(1.0, "Perfekter Match gefunden.")
                break

        if i == 1 or i == total or i % max(1, total // 20) == 0:
            msg = (
                f"Shift {sh:+.3f}s | "
                + (f"sum_err={cur['sum_abs_err']:.1f} RPM·n" if cur.get("ok") else cur.get("error", "n/a"))
            )
            log.append(msg)
            if callable(progress_cb):
                progress_cb(i / total, msg)

    if best is None:
        best = {"ok": False, "error": "Kein gueltiger Shift gefunden."}
        log.append("FEHLER: kein gueltiger Shift in gesuchtem Bereich.")
    else:
        log.append(
            f"Bestes Ergebnis: shift={best['shift_s']:+.3f}s | "
            f"sum_err={best['sum_abs_err']:.1f} | mae={best['mae']:.2f} RPM | n={best['n']}"
        )

    return best, log


# ---------------------------------------------------------------------------
# Visualisierung
# ---------------------------------------------------------------------------

def build_validation_figure(
    t_audio: np.ndarray,
    rpm_audio: np.ndarray,
    t_ref: np.ndarray,
    y_ref: np.ndarray,
    shift_s: float = 0.0,
    label_audio: str = "RPM Analyse",
    label_ref: str = "RPM Messung",
):
    """Build a two-panel Plotly figure for RPM validation results.

    Panel 1: both RPM curves overlaid on a shared time axis.
    Panel 2: point-wise error (Analyse − Messung) on the overlapping window.

    Returns a plotly.graph_objects.Figure, or None if plotly is unavailable
    or the inputs yield no overlap.
    """
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError:
        return None

    ta = np.asarray(t_audio,  dtype=float).ravel()
    ra = np.asarray(rpm_audio, dtype=float).ravel()
    tr = np.asarray(t_ref,    dtype=float).ravel() + float(shift_s)
    yr = np.asarray(y_ref,    dtype=float).ravel()

    # clean audio curve
    n  = min(ta.size, ra.size)
    ta, ra = ta[:n], ra[:n]
    m  = np.isfinite(ta) & np.isfinite(ra)
    ta, ra = ta[m], ra[m]

    # clean reference curve
    mr = np.isfinite(tr) & np.isfinite(yr)
    tr, yr = tr[mr], yr[mr]
    order  = np.argsort(tr)
    tr, yr = tr[order], yr[order]

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        row_heights=[0.65, 0.35],
        vertical_spacing=0.06,
        subplot_titles=["RPM-Kurven", "Fehler (Analyse − Messung)"],
    )

    # ── Panel 1: both curves ─────────────────────────────────────────────────
    fig.add_trace(go.Scatter(
        x=ta, y=ra, mode="lines", name=label_audio,
        line=dict(color="#4a90d4", width=1.5),
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=tr, y=yr, mode="lines", name=label_ref,
        line=dict(color="#e87040", width=1.5, dash="dot"),
    ), row=1, col=1)

    # ── Panel 2: error on overlapping window ─────────────────────────────────
    lo = max(float(ta.min()) if ta.size else 0, float(tr.min()) if tr.size else 0)
    hi = min(float(ta.max()) if ta.size else 0, float(tr.max()) if tr.size else 0)

    if hi > lo and ta.size >= 2 and tr.size >= 2:
        keep = (ta >= lo) & (ta <= hi)
        ta2, ra2 = ta[keep], ra[keep]
        yr_i = np.interp(ta2, tr, yr)
        err  = ra2 - yr_i

        # zero line
        fig.add_hline(y=0, line=dict(color="rgba(255,255,255,0.25)", width=1), row=2, col=1)

        # shaded error area
        fig.add_trace(go.Scatter(
            x=np.concatenate([ta2, ta2[::-1]]),
            y=np.concatenate([err, np.zeros_like(err)]),
            fill="toself",
            fillcolor="rgba(220,80,80,0.18)",
            line=dict(width=0),
            showlegend=False,
            name="Fehlerflaeche",
        ), row=2, col=1)

        # error line
        fig.add_trace(go.Scatter(
            x=ta2, y=err, mode="lines", name="Fehler",
            line=dict(color="#e84040", width=1.2),
        ), row=2, col=1)

        mae = float(np.mean(np.abs(err)))
        fig.add_annotation(
            x=0.01, y=0.95, xref="paper", yref="paper",
            text=f"MAE={mae:.1f} RPM  ·  Versatz={shift_s:+.3f}s",
            showarrow=False, font=dict(size=11, color="#aaaaaa"),
            xanchor="left", yanchor="top",
        )

    fig.update_layout(
        template="plotly_dark",
        height=480,
        margin=dict(l=50, r=20, t=50, b=30),
        legend=dict(orientation="h", y=1.08, x=0),
        hovermode="x unified",
    )
    fig.update_yaxes(title_text="RPM [1/min]", row=1, col=1)
    fig.update_yaxes(title_text="Δ RPM", row=2, col=1)
    fig.update_xaxes(title_text="Zeit [s]", row=2, col=1)

    return fig
