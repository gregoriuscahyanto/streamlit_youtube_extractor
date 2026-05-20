"""Interactive data-point editor: mark, remove and interpolate outliers in cleaned OCR data."""
from __future__ import annotations

import json
from pathlib import Path

_SCAN_FILE_CACHE: dict[str, dict] = {}


# ── helpers ───────────────────────────────────────────────────────────────────

def _base() -> Path:
    import streamlit as _st
    lp = str(_st.session_state.get("local_base_path") or "").strip()
    return Path(lp).expanduser().resolve() if lp else Path.cwd()


def _scan_editable_jsons() -> list[dict]:
    """Scan for JSONs with cleaned OCR data. Uses mtime cache to avoid re-reading
    unchanged files on every Streamlit rerun."""
    base = _base()
    res_dir = base / "results"
    if not res_dir.exists():
        return []
    out = []
    for jp in sorted(res_dir.glob("results_*.json"), reverse=True):
        path_str = str(jp.resolve())
        try:
            mtime = jp.stat().st_mtime
            cached = _SCAN_FILE_CACHE.get(path_str)
            if cached and cached.get("mtime") == mtime:
                if cached.get("skip"):
                    continue
                out.append(cached)
                continue
            doc = json.loads(jp.read_text(encoding="utf-8", errors="ignore"))
            rr = doc.get("recordResult") if isinstance(doc, dict) else {}
            if not isinstance(rr, dict):
                _SCAN_FILE_CACHE[path_str] = {"mtime": mtime, "skip": True}
                continue
            ocr = (rr or {}).get("ocr") or {}
            cleaned = ocr.get("cleaned") if isinstance(ocr.get("cleaned"), dict) else {}
            if not cleaned or not (cleaned.get("time_s") or cleaned.get("t_s")):
                _SCAN_FILE_CACHE[path_str] = {"mtime": mtime, "skip": True}
                continue
            folder = jp.stem.replace("results_", "", 1)
            meta = rr.get("metadata") or {}
            title = str(
                meta.get("title") or meta.get("video_title") or
                meta.get("youtube_title") or ""
            ).strip()
            entry = {
                "mtime": mtime,
                "skip": False,
                "path": path_str,
                "folder": folder,
                "title": title or folder,
            }
            _SCAN_FILE_CACHE[path_str] = entry
            out.append(entry)
        except Exception:
            continue
    return out


def _load_cleaned(json_path: str) -> dict[str, list]:
    """Load cleaned table as {col: [float|nan]}. All values are coerced to float."""
    def _to_f(x) -> float:
        """Coerce any value to float; unknown types become NaN."""
        if x is None or x == "":
            return float("nan")
        if isinstance(x, (list, tuple)):
            return _to_f(x[0]) if len(x) == 1 else float("nan")
        try:
            return float(x)
        except (TypeError, ValueError):
            return float("nan")

    try:
        doc = json.loads(Path(json_path).read_text(encoding="utf-8", errors="ignore"))
        rr = doc.get("recordResult") if isinstance(doc, dict) else {}
        ocr = (rr or {}).get("ocr") or {}
        cleaned = ocr.get("cleaned")
        if not isinstance(cleaned, dict):
            return {}
        t_key = "time_s" if "time_s" in cleaned else "t_s"
        t = cleaned.get(t_key)
        if not isinstance(t, list):
            return {}
        n = len(t)
        out: dict[str, list] = {}
        for k, v in cleaned.items():
            if not isinstance(v, list) or len(v) != n:
                continue
            out[k] = [_to_f(x) for x in v]
        return out
    except Exception:
        return {}


def _compute_s_m(data: dict[str, list]) -> list[float] | None:
    """Cumulative distance from v and t (matches MATLAB OCRExtractor method).

    NaN velocity values are filled via linear interpolation (nearest at edges)
    before integration — identical to MATLAB's fillmissing('linear','EndValues','nearest').
    Without this, a single NaN propagates through cumsum and makes all s_m NaN.
    """
    import numpy as np
    t = data.get("time_s") or data.get("t_s")
    v = data.get("v_Fzg_kmph") or data.get("v_Fzg_mph")
    if not t or not v or len(t) != len(v):
        return None
    t_arr = np.array(t, dtype=float)
    v_arr = np.array(v, dtype=float)
    if not data.get("v_Fzg_kmph") and data.get("v_Fzg_mph"):
        v_arr = v_arr * 1.60934

    # Fill NaN/inf before integration — matches MATLAB fillmissing linear + nearest ends
    nan_mask = ~np.isfinite(v_arr)
    if nan_mask.any():
        valid_idx = np.where(~nan_mask)[0]
        if len(valid_idx) == 0:
            return None
        v_arr = np.interp(np.arange(len(v_arr)), valid_idx, v_arr[valid_idx])

    v_mps = v_arr / 3.6
    dt = np.concatenate(([0.0], np.diff(t_arr)))
    dt[~np.isfinite(dt) | (dt < 0)] = 0.0
    return np.cumsum(v_mps * dt).tolist()


def _interpolate_column(
    xs: list[float],
    ys: list[float],
    remove_idx: set[int],
    method: str,
) -> list[float]:
    """Return ys with marked indices AND existing NaN values filled by interpolation.

    Points outside the valid source range (before first / after last finite source
    value) are set to NaN — no extrapolation.
    """
    import numpy as np

    n = len(xs)
    xs_arr = np.array(xs, dtype=float)
    ys_arr = np.array(ys, dtype=float)

    # Source: non-marked AND finite positions
    keep = np.ones(n, dtype=bool)
    for i in remove_idx:
        if 0 <= i < n:
            keep[i] = False
    xs_k = xs_arr[keep]
    ys_k = ys_arr[keep]
    valid = np.isfinite(xs_k) & np.isfinite(ys_k)
    if valid.sum() < 2:
        return ys

    # Positions that need filling: manually marked + existing NaN in the data
    need_fill = (~keep) | (~np.isfinite(ys_arr))

    # No extrapolation: clamp to [x_min, x_max] of the source — set NaN outside
    x_min = float(xs_k[valid].min())
    x_max = float(xs_k[valid].max())
    in_range = need_fill & np.isfinite(xs_arr) & (xs_arr >= x_min) & (xs_arr <= x_max)
    out_of_range = need_fill & ~in_range

    result = ys_arr.copy()
    result[out_of_range] = float("nan")

    if not in_range.any():
        return result.tolist()

    try:
        if method == "akima":
            from scipy.interpolate import Akima1DInterpolator
            f = Akima1DInterpolator(xs_k[valid], ys_k[valid])
            result[in_range] = f(xs_arr[in_range])
        else:
            from scipy.interpolate import interp1d
            kind = {"linear": "linear", "quadratic": "quadratic",
                    "cubic": "cubic", "nearest": "nearest"}.get(method, "linear")
            f = interp1d(xs_k[valid], ys_k[valid], kind=kind,
                         bounds_error=False, fill_value=float("nan"))
            result[in_range] = f(xs_arr[in_range])
        return result.tolist()
    except Exception:
        return ys


def _save_cleaned(json_path: str, new_data: dict[str, list]) -> None:
    """Overwrite recordResult.ocr.cleaned and invalidate caches."""
    doc = json.loads(Path(json_path).read_text(encoding="utf-8", errors="ignore"))
    rr = doc["recordResult"]
    rr["ocr"]["cleaned"] = new_data
    json_bytes = json.dumps(doc, ensure_ascii=False, indent=2).encode("utf-8")
    try:
        from core.watchdog_state import get_path_lock, _JSON_ROW_CACHE
        with get_path_lock(json_path):
            Path(json_path).write_bytes(json_bytes)
        _JSON_ROW_CACHE.pop(json_path, None)
    except Exception:
        Path(json_path).write_bytes(json_bytes)
    try:
        from app_tabs.media_tab import _DETAIL_CACHE
        _DETAIL_CACHE.pop(json_path, None)
    except Exception:
        pass
    # Invalidate scan cache so next scan picks up new mtime
    _SCAN_FILE_CACHE.pop(json_path, None)


# ── render ────────────────────────────────────────────────────────────────────

def render(ns: dict) -> None:
    globals().update(ns)

    st.markdown('<div class="section-title">Datenpunkt-Editor</div>', unsafe_allow_html=True)
    st.caption(
        "Einzelne Datenpunkte im cleaned-Datensatz manuell markieren, "
        "entfernen und interpolieren. Änderungen werden erst nach 'Speichern' in die JSON geschrieben."
    )

    # defaults (set before fragment so they exist on first run)
    st.session_state.setdefault("edit_file_path", "")
    st.session_state.setdefault("edit_original", {})
    st.session_state.setdefault("edit_working", {})
    st.session_state.setdefault("edit_x_col", "s_m")
    st.session_state.setdefault("edit_y_col", "v_Fzg_kmph")
    st.session_state.setdefault("edit_chart_rev", 0)
    st.session_state.setdefault("edit_saved", False)

    available = _scan_editable_jsons()
    if not available:
        st.info("Keine JSON-Dateien mit cleaned OCR-Daten gefunden.")
        return

    # Everything below runs inside a single fragment — no full-page reruns
    @st.fragment
    def _editor() -> None:
        import copy as _copy
        import math as _math
        import numpy as _np
        import plotly.graph_objects as _go

        # re-scan uses mtime cache → fast (only stat() calls)
        _available = _scan_editable_jsons()
        if not _available:
            st.info("Keine JSON-Dateien mit cleaned OCR-Daten gefunden.")
            return
        _path_map = {a["path"]: a for a in _available}

        # ── file chooser ──────────────────────────────────────────────────────
        st.markdown("### Datei")
        _chosen = st.selectbox(
            "JSON auswählen",
            options=[a["path"] for a in _available],
            format_func=lambda p: _path_map[p]["title"],
            key="edit_file_chooser",
            label_visibility="collapsed",
        )

        if _chosen != st.session_state.edit_file_path:
            _data = _load_cleaned(_chosen)
            st.session_state.edit_file_path = _chosen
            st.session_state.edit_original = _data
            st.session_state.edit_working = _copy.deepcopy(_data)
            st.session_state.edit_chart_rev += 1
            st.session_state.edit_saved = False

        _orig = st.session_state.edit_original
        _work = st.session_state.edit_working
        if not _orig:
            st.warning("Keine cleaned-Daten geladen.")
            return

        # ── axis + interpolation selectors ────────────────────────────────────
        _all_cols = [k for k, v in _orig.items() if isinstance(v, list)]
        _ca, _cb, _cc = st.columns([2, 2, 2])

        _x_def = st.session_state.edit_x_col if st.session_state.edit_x_col in _all_cols else _all_cols[0]
        _x_col = _ca.selectbox("X-Achse", _all_cols, index=_all_cols.index(_x_def), key="edit_xcol")
        st.session_state.edit_x_col = _x_col

        _y_opts = [c for c in _all_cols if c != _x_col]
        _y_def = st.session_state.edit_y_col if st.session_state.edit_y_col in _y_opts else (_y_opts[0] if _y_opts else "")
        _y_col = (
            _cb.selectbox("Y-Achse", _y_opts, index=_y_opts.index(_y_def) if _y_def in _y_opts else 0, key="edit_ycol")
            if _y_opts else ""
        )
        st.session_state.edit_y_col = _y_col

        _interp_labels = {
            "linear": "Linear",
            "quadratic": "Quadratisch",
            "cubic": "Kubisch",
            "akima": "Akima (glatt, kein Überschwingen)",
            "nearest": "Nächster Wert",
        }
        _interp_method = _cc.selectbox(
            "Interpolation",
            options=list(_interp_labels),
            format_func=lambda v: _interp_labels[v],
            key="edit_interp",
            help="Akima empfohlen für Geschwindigkeitsdaten (kein Ringing).",
        )

        if not _y_col:
            st.warning("Keine Y-Spalte verfügbar.")
            return

        _xs_orig = _orig.get(_x_col, [])
        _ys_orig = _orig.get(_y_col, [])
        _xs_work = _work.get(_x_col, _xs_orig)
        _ys_work = _work.get(_y_col, _ys_orig)
        _n = len(_xs_work)

        if not _xs_work or not _ys_work or len(_ys_work) != _n:
            st.warning("Keine Daten für diese Achsenkombination.")
            return

        _orig_changed = (_xs_orig != _xs_work or _ys_orig != _ys_work)

        # ── threshold batch-remove ────────────────────────────────────────────
        with st.expander("Schwellenwert-Filter (Batch-Entfernung)", expanded=False):
            st.caption(f"Alle {_y_col}-Werte außerhalb des Bereichs markieren.")
            _valid_ys = [v for v in _ys_work if isinstance(v, (int, float)) and _np.isfinite(v)]
            _y_min_data = float(min(_valid_ys)) if _valid_ys else 0.0
            _y_max_data = float(max(_valid_ys)) if _valid_ys else 1.0
            _tc1, _tc2, _tc3 = st.columns([2, 2, 2])
            _thr_lo = _tc1.number_input("Min (y <)", value=_y_min_data, format="%.2f", key="edit_thr_lo")
            _thr_hi = _tc2.number_input("Max (y >)", value=_y_max_data, format="%.2f", key="edit_thr_hi")
            if _tc3.button("Markieren", key="edit_thr_apply"):
                _new_marked: set[int] = set()
                for _i2, _y2 in enumerate(_ys_work):
                    if isinstance(_y2, (int, float)) and _np.isfinite(_y2) and (_y2 < _thr_lo or _y2 > _thr_hi):
                        _new_marked.add(_i2)
                st.session_state["edit_threshold_marked"] = _new_marked
                st.rerun(scope="fragment")

        # ── chart ─────────────────────────────────────────────────────────────
        st.markdown("### Plot")
        _fig = _go.Figure()
        if _orig_changed and _xs_orig and _ys_orig:
            _fig.add_trace(_go.Scattergl(
                x=_xs_orig, y=_ys_orig, mode="lines",
                name="Original (Referenz)",
                line=dict(dash="dash", color="rgba(160,160,160,0.35)", width=1),
                hoverinfo="skip",
            ))
        _fig.add_trace(_go.Scattergl(
            x=_xs_work, y=_ys_work, mode="lines+markers",
            name="Aktuell",
            line=dict(color="#63d2ff", width=1.5),
            marker=dict(color="#63d2ff", size=5, opacity=0.8),
            customdata=list(range(_n)),
            hovertemplate=f"{_x_col}: %{{x:.2f}}<br>{_y_col}: %{{y:.2f}}<br>Index: %{{customdata}}<extra></extra>",
            selected=dict(marker=dict(color="#ff4444", size=9)),
            unselected=dict(marker=dict(opacity=0.4)),
        ))
        _chart_key = f"edit_chart_{st.session_state.edit_chart_rev}"
        _fig.update_layout(
            margin=dict(l=40, r=20, t=30, b=40), height=440,
            xaxis_title=_x_col, yaxis_title=_y_col,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            template="plotly_dark", dragmode="select",
            uirevision=_chart_key,
        )
        try:
            _event = st.plotly_chart(
                _fig, use_container_width=True,
                on_select="rerun",
                selection_mode=["points", "box", "lasso"],
                key=_chart_key,
            )
        except TypeError:
            st.plotly_chart(_fig, use_container_width=True, key=_chart_key)
            _event = None

        # derive marked set from Plotly selection
        _marked: set[int] = set()
        if _event is not None:
            try:
                _sel = _event.selection if hasattr(_event, "selection") else (_event or {}).get("selection", {})
                _pts = _sel.get("points", []) if isinstance(_sel, dict) else getattr(_sel, "points", [])
                _work_curve = 1 if _orig_changed else 0
                for _pt in (_pts or []):
                    _cn = _pt.get("curve_number", 0) if isinstance(_pt, dict) else getattr(_pt, "curve_number", 0)
                    if _cn != _work_curve:
                        continue
                    _i = _pt.get("point_index") if isinstance(_pt, dict) else getattr(_pt, "point_index", None)
                    if _i is None:
                        _i = _pt.get("point_number") if isinstance(_pt, dict) else getattr(_pt, "point_number", None)
                    if _i is not None and 0 <= _i < _n:
                        _marked.add(_i)
            except Exception:
                pass

        # merge threshold-filter marks
        _marked |= st.session_state.pop("edit_threshold_marked", set())
        _n_marked = len(_marked)
        _n_nans = sum(1 for v in _ys_work if isinstance(v, float) and _np.isnan(v))
        _caption = f"**{_n_marked}** Punkt(e) markiert (rot)"
        if _n_nans:
            _caption += f" · **{_n_nans}** NaN-Wert(e) in der Spalte (werden beim Anwenden mitgefüllt)"
        st.caption(_caption)

        # ── changed-points count (for save button style + warning) ────────────
        _ys_orig_b = _orig.get(_y_col, [])
        _ys_work_b = _work.get(_y_col, [])
        _n_changed = (
            sum(
                0 if (isinstance(_o, float) and isinstance(_w, float)
                      and _math.isnan(_o) and _math.isnan(_w))
                else (0 if _o == _w else 1)
                for _o, _w in zip(_ys_orig_b, _ys_work_b)
            )
            if len(_ys_orig_b) == len(_ys_work_b) else 0
        )

        # ── action buttons ────────────────────────────────────────────────────
        _ba, _bb, _bc, _bd, _be = st.columns(5)
        _apply = _ba.button(
            "✂ Entfernen & interpolieren", type="primary",
            key="edit_apply", disabled=(_n_marked == 0 and _n_nans == 0), use_container_width=True,
        )
        _clear = _bb.button(
            "↩ Selektion löschen",
            key="edit_reset_sel", disabled=_n_marked == 0, use_container_width=True,
        )
        _reset_all = _bc.button(
            "↺ Zurücksetzen", key="edit_reset_all", use_container_width=True,
            help="Setzt alle Änderungen zurück auf den gespeicherten Originalzustand.",
        )
        _calc_sm = _bd.button(
            "📏 s_m berechnen", key="edit_calc_sm", use_container_width=True,
            disabled=not ("v_Fzg_kmph" in _work or "v_Fzg_mph" in _work),
            help="Berechnet kumulative Strecke s_m aus v_Fzg_kmph und time_s.",
        )
        _save = _be.button(
            "💾 Speichern",
            type="primary" if _n_changed > 0 else "secondary",
            key="edit_save", use_container_width=True,
            help="Überschreibt recordResult.ocr.cleaned in der JSON-Datei.",
        )

        # ── button handlers (all fragment-scoped) ─────────────────────────────
        if _apply and _marked:
            _xs_apply = _work.get(_x_col, [])
            _new_work: dict[str, list] = {}
            for _cname, _cvals in _work.items():
                if _cname == _x_col:
                    _new_work[_cname] = _cvals
                elif isinstance(_cvals, list) and len(_cvals) == len(_xs_apply):
                    try:
                        _new_work[_cname] = _interpolate_column(_xs_apply, _cvals, _marked, _interp_method)
                    except Exception:
                        _new_work[_cname] = _cvals
                else:
                    _new_work[_cname] = _cvals
            st.session_state.edit_working = _new_work
            st.session_state.edit_chart_rev += 1
            st.session_state.edit_saved = False
            st.rerun(scope="fragment")

        if _clear:
            st.session_state.edit_chart_rev += 1
            st.rerun(scope="fragment")

        if _reset_all:
            st.session_state.edit_working = _copy.deepcopy(_orig)
            st.session_state.edit_chart_rev += 1
            st.session_state.edit_saved = False
            st.rerun(scope="fragment")

        if _calc_sm:
            _sm = _compute_s_m(_work)
            if _sm is not None:
                _work["s_m"] = _sm
                st.session_state.edit_working = _work
                st.session_state.edit_chart_rev += 1
                st.session_state.edit_saved = False
                st.rerun(scope="fragment")
            else:
                st.error("s_m konnte nicht berechnet werden — v_Fzg_kmph oder time_s fehlt.")

        if _save:
            try:
                _save_cleaned(_chosen, _work)
                st.session_state.edit_original = _copy.deepcopy(_work)
                st.session_state.edit_saved = True
                st.session_state.edit_chart_rev += 1
                st.rerun(scope="fragment")
            except Exception as _e:
                st.error(f"Speichern fehlgeschlagen: {_e}")

        # ── status messages ───────────────────────────────────────────────────
        if st.session_state.get("edit_saved") and _n_changed == 0:
            st.success(f"✅ Gespeichert in **{Path(_chosen).name}**.")
        elif _n_changed > 0 and not st.session_state.get("edit_saved"):
            st.info(
                f"**{_n_changed}** Punkt(e) gegenüber der gespeicherten Version verändert — "
                "bitte '💾 Speichern' klicken.",
                icon="⚠️",
            )

    _editor()
