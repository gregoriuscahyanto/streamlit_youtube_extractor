"""Multi-file OCR / Audio comparison tab."""
from __future__ import annotations

import json
from pathlib import Path

# mtime-keyed cache so we only re-read files that changed on disk.
# key = absolute path str  →  value = {mtime, folder, title, has_ocr, has_audio}
_SCAN_FILE_CACHE: dict[str, dict] = {}


# ── Data helpers ──────────────────────────────────────────────────────────────

def _base() -> Path:
    import streamlit as _st
    lp = str(_st.session_state.get("local_base_path") or "").strip()
    return Path(lp).expanduser().resolve() if lp else Path.cwd()


def _is_locked(json_path: str) -> bool:
    try:
        from core.watchdog_state import is_path_locked
        return is_path_locked(json_path)
    except Exception:
        return False


def _watchdog_active_paths() -> set[str]:
    """Paths currently being written by the watchdog."""
    try:
        from app_tabs.youtube_tab import watchdog_snapshot
        snap = watchdog_snapshot()
        active: set[str] = set()
        if snap.get("running"):
            live = snap.get("ocr_live") or {}
            folder = str(live.get("folder") or "")
            if folder and live.get("active"):
                b = _base()
                active.add(str((b / "results" / f"results_{folder}.json").resolve()))
        return active
    except Exception:
        return set()


def _scan_available_jsons() -> list[dict]:
    """Return list of result JSONs that have OCR or audio data.

    Uses a module-level mtime cache so each file is only re-read when it
    actually changed on disk.  Reduces per-rerun I/O from O(N × read+parse)
    to O(N × stat).
    """
    base = _base()
    res_dir = base / "results"
    if not res_dir.exists():
        return []
    locked = _watchdog_active_paths()
    out: list[dict] = []
    for jp in sorted(res_dir.glob("results_*.json"), reverse=True):
        path_str = str(jp.resolve())
        is_busy = path_str in locked or _is_locked(path_str)
        try:
            mtime = jp.stat().st_mtime
            cached = _SCAN_FILE_CACHE.get(path_str)
            if cached and cached.get("mtime") == mtime:
                if cached.get("skip"):
                    continue
                out.append({**cached, "busy": is_busy})
                continue
            # File is new or changed — parse it
            doc = json.loads(jp.read_text(encoding="utf-8", errors="ignore"))
            rr = doc.get("recordResult") if isinstance(doc, dict) else {}
            if not isinstance(rr, dict):
                _SCAN_FILE_CACHE[path_str] = {"mtime": mtime, "skip": True}
                continue
            meta = rr.get("metadata") or {}
            title = str(
                meta.get("title") or meta.get("video_title") or
                meta.get("youtube_title") or ""
            ).strip()
            ocr = rr.get("ocr") or {}
            has_ocr = bool(
                isinstance(ocr.get("cleaned"), dict) and ocr["cleaned"].get("time_s")
                or isinstance(ocr.get("table"), dict) and ocr["table"].get("time_s")
            )
            arpm = rr.get("audio_rpm") or {}
            has_audio = bool(
                isinstance(arpm.get("processed"), dict)
                and arpm["processed"].get("t_s")
            )
            if not (has_ocr or has_audio):
                _SCAN_FILE_CACHE[path_str] = {"mtime": mtime, "skip": True}
                continue
            entry = {
                "mtime": mtime,
                "skip": False,
                "folder": jp.stem.replace("results_", "", 1),
                "path": path_str,
                "title": title,
                "has_ocr": has_ocr,
                "has_audio": has_audio,
            }
            _SCAN_FILE_CACHE[path_str] = entry
            out.append({**entry, "busy": is_busy})
        except Exception:
            continue
    return out


def _load_file_data(json_path: str, offset_s: float, offset_m: float = 0.0) -> dict[str, list]:
    """Load OCR cleaned + audio RPM into {col: [values]} with time and distance offsets applied."""
    try:
        doc = json.loads(Path(json_path).read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return {}
    rr = doc.get("recordResult") if isinstance(doc, dict) else {}
    if not isinstance(rr, dict):
        return {}
    cols: dict[str, list] = {}

    # OCR cleaned table (columnar)
    ocr = rr.get("ocr") or {}
    tbl = ocr.get("cleaned") if isinstance(ocr.get("cleaned"), dict) else {}
    if not tbl:
        tbl = ocr.get("table") if isinstance(ocr.get("table"), dict) else {}
    if isinstance(tbl, dict) and tbl.get("time_s"):
        n = len(tbl["time_s"])
        for k, v in tbl.items():
            if isinstance(v, list) and len(v) == n:
                if k == "time_s":
                    cols["time_s"] = [float(x) + offset_s for x in v]
                elif k == "s_m" and offset_m != 0.0:
                    cols["s_m"] = [float(x) + offset_m if x not in ("", None) else float("nan") for x in v]
                else:
                    try:
                        cols[k] = [float(x) if x not in ("", None) else float("nan") for x in v]
                    except Exception:
                        cols[k] = list(v)

    # Interpolate track_xy_x / track_xy_y gaps so the track line is continuous
    _ts = cols.get("time_s")
    if _ts:
        import numpy as _np
        _t = _np.array(_ts, dtype=float)
        for _xy_col in ("track_xy_x", "track_xy_y"):
            if _xy_col not in cols:
                continue
            _v = _np.array(cols[_xy_col], dtype=float)
            _ok = _np.isfinite(_v) & _np.isfinite(_t)
            if _ok.sum() >= 2 and (~_ok).any():
                _v[~_ok] = _np.interp(_t[~_ok], _t[_ok], _v[_ok])
                cols[_xy_col] = _v.tolist()

    # Audio RPM processed
    arpm = rr.get("audio_rpm") or {}
    proc = arpm.get("processed") if isinstance(arpm.get("processed"), dict) else {}
    proc_col = arpm.get("processed_col") if isinstance(arpm.get("processed_col"), dict) else {}
    if proc_col:
        proc = {**proc_col, **proc}
    if isinstance(proc, dict) and proc.get("t_s"):
        t_audio = [float(x) + offset_s for x in proc["t_s"]]
        n_a = len(t_audio)
        if "time_s" not in cols:
            cols["time_s"] = t_audio
        else:
            cols["audio_time_s"] = t_audio
        for k, v in proc.items():
            if k == "t_s":
                continue
            if isinstance(v, list) and len(v) == n_a:
                try:
                    cols[f"audio_{k}"] = [float(x) if x not in ("", None) else float("nan") for x in v]
                except Exception:
                    cols[f"audio_{k}"] = list(v)
    return cols


def _read_external_table(uploaded_file, sheet_name=0):
    """Read an uploaded Excel/CSV table into a DataFrame."""
    import io
    import pandas as pd

    name = str(getattr(uploaded_file, "name", "") or "").lower()
    data = uploaded_file.getvalue()
    if name.endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(data), sheet_name=sheet_name)
    if name.endswith(".csv"):
        try:
            return pd.read_csv(io.BytesIO(data))
        except Exception:
            return pd.read_csv(io.BytesIO(data), sep=";")
    raise ValueError(f"Nicht unterstuetztes Format: {name}")


def _external_table_to_cols(df, mapping: dict, offset_s: float = 0.0, offset_m: float = 0.0) -> dict[str, list]:
    """Convert an external table to comparison columns using canonical names."""
    import pandas as pd

    cols: dict[str, list] = {}
    if df is None or getattr(df, "empty", True):
        return cols
    used: set[str] = set()
    for target, source in (mapping or {}).items():
        if not source or source not in df.columns:
            continue
        vals = pd.to_numeric(df[source], errors="coerce")
        out_name = str(target)
        if out_name == "time_s":
            vals = vals + float(offset_s)
        elif out_name == "s_m":
            vals = vals + float(offset_m)
        cols[out_name] = vals.astype(float).tolist()
        used.add(str(source))

    # Keep extra numeric columns available without forcing a mapping.
    for c in df.columns:
        if str(c) in used:
            continue
        vals = pd.to_numeric(df[c], errors="coerce")
        if vals.notna().any():
            out_name = str(c)
            if out_name in cols:
                out_name = f"ext_{out_name}"
            cols[out_name] = vals.astype(float).tolist()
    return cols


# ── Track calibration helper ──────────────────────────────────────────────────

def _to_float_or_none(value) -> float | None:
    try:
        if value is None:
            return None
        txt = str(value).strip().replace(",", ".")
        if not txt:
            return None
        val = float(txt)
        return val if val == val else None
    except Exception:
        return None


def _compute_s_m_from_speed(data: dict[str, list]) -> list[float] | None:
    """Cumulative distance from OCR speed and time; same integration as edit_tab."""
    import numpy as np

    t = data.get("time_s") or data.get("t_s") or data.get("audio_time_s")
    v = data.get("v_Fzg_kmph") or data.get("v_Fzg_mph")
    if not t or not v or len(t) != len(v):
        return None
    t_arr = np.asarray(t, dtype=float)
    v_arr = np.asarray(v, dtype=float)
    if not data.get("v_Fzg_kmph") and data.get("v_Fzg_mph"):
        v_arr = v_arr * 1.60934
    bad = ~np.isfinite(v_arr)
    if bad.any():
        good_idx = np.where(~bad)[0]
        if good_idx.size == 0:
            return None
        v_arr = np.interp(np.arange(v_arr.size), good_idx, v_arr[good_idx])
    v_mps = v_arr / 3.6
    dt = np.concatenate(([0.0], np.diff(t_arr)))
    dt[~np.isfinite(dt) | (dt < 0)] = 0.0
    return np.cumsum(v_mps * dt).astype(float).tolist()


def _fill_numeric_series(values) -> list[float] | None:
    import numpy as np

    if values is None:
        return None
    arr = np.asarray(values, dtype=float).ravel()
    if arr.size == 0:
        return None
    bad = ~np.isfinite(arr)
    if bad.any():
        good_idx = np.where(~bad)[0]
        if good_idx.size == 0:
            return None
        arr = np.interp(np.arange(arr.size), good_idx, arr[good_idx])
    return arr.astype(float).tolist()


def _add_wheel_dynamics(data: dict[str, list], cfg: dict) -> tuple[bool, list[str]]:
    """Add wheel force/power/torque columns from speed and resistance inputs."""
    import numpy as np

    required = {
        "Masse m kg": cfg.get("mass_kg"),
        "Luftwiderstandsbeiwert Cw": cfg.get("cw"),
        "Stirnflaeche A m^2": cfg.get("area_m2"),
    }
    missing = [name for name, val in required.items() if val is None]
    if missing:
        return False, missing

    t = data.get("time_s") or data.get("t_s") or data.get("audio_time_s")
    v_raw = data.get("v_Fzg_kmph") or data.get("v_Fzg_mph")
    if not t or not v_raw or len(t) != len(v_raw):
        return False, ["time_s und v_Fzg_kmph"]

    t_arr = np.asarray(t, dtype=float)
    v_series = _fill_numeric_series(v_raw)
    if v_series is None:
        return False, ["gueltige Geschwindigkeit"]
    v_kmph = np.asarray(v_series, dtype=float)
    if not data.get("v_Fzg_kmph") and data.get("v_Fzg_mph"):
        v_kmph = v_kmph * 1.60934
    n = min(t_arr.size, v_kmph.size)
    if n < 2:
        return False, ["mindestens zwei Geschwindigkeitspunkte"]
    t_arr = t_arr[:n]
    v_mps = v_kmph[:n] / 3.6

    dt = np.gradient(t_arr)
    dt[~np.isfinite(dt) | (np.abs(dt) < 1e-6)] = 1e-6
    a_mps2 = np.gradient(v_mps) / dt
    rho = float(cfg.get("rho") if cfg.get("rho") is not None else 1.225)
    g = float(cfg.get("g") if cfg.get("g") is not None else 9.81)
    crr = float(cfg.get("crr") if cfg.get("crr") is not None else 0.01)
    lam = float(cfg.get("lambda_rot") if cfg.get("lambda_rot") is not None else 1.0)
    mass = float(cfg["mass_kg"])
    cw = float(cfg["cw"])
    area = float(cfg["area_m2"])

    f_aero = 0.5 * rho * cw * area * v_mps * v_mps
    f_roll = np.full(n, mass * g * crr, dtype=float)
    f_inertia = mass * lam * a_mps2
    f_grade = np.zeros(n, dtype=float)
    f_total = f_aero + f_roll + f_inertia + f_grade
    p_w = f_total * v_mps

    data["s_m_from_v"] = _compute_s_m_from_speed(data) or []
    if "s_m" not in data and data["s_m_from_v"]:
        data["s_m"] = list(data["s_m_from_v"])
    data["a_mps2"] = a_mps2.astype(float).tolist()
    data["wheel_force_n"] = f_total.astype(float).tolist()
    data["wheel_force_aero_n"] = f_aero.astype(float).tolist()
    data["wheel_force_roll_n"] = f_roll.astype(float).tolist()
    data["wheel_force_inertia_n"] = f_inertia.astype(float).tolist()
    data["wheel_force_grade_n"] = f_grade.astype(float).tolist()
    data["wheel_power_w"] = p_w.astype(float).tolist()
    data["wheel_power_kw"] = (p_w / 1000.0).astype(float).tolist()
    data["wheel_power_ps"] = (p_w / 735.49875).astype(float).tolist()

    r_dyn = cfg.get("r_dyn_m")
    if r_dyn is not None:
        data["wheel_torque_nm"] = (f_total * float(r_dyn)).astype(float).tolist()
    return True, []


def _add_compare_derivatives(data: dict[str, list], cfg: dict) -> tuple[bool, list[str]]:
    """Add distance and optional wheel-power derived columns to one loaded dataset."""
    s = _compute_s_m_from_speed(data)
    if s:
        data["s_m_from_v"] = s
        if "s_m" not in data:
            data["s_m"] = list(s)
    if not cfg.get("enable_wheel_dynamics"):
        return True, []
    return _add_wheel_dynamics(data, cfg)


def _load_trkCalSlim(json_path: str) -> dict:
    """Load trkCalSlim from a result JSON (centerline_px, minimap_pts, ref_pts)."""
    try:
        doc = json.loads(Path(json_path).read_text(encoding="utf-8", errors="ignore"))
        rr = doc.get("recordResult") if isinstance(doc, dict) else {}
        ocr = (rr or {}).get("ocr") or {}
        trk = ocr.get("trkCalSlim")
        return trk if isinstance(trk, dict) else {}
    except Exception:
        return {}


# ── Config persistence ────────────────────────────────────────────────────────

def _config_dir() -> Path:
    # Fixed path relative to this file — independent of local_base_path session state
    d = Path(__file__).parent.parent / "logs" / "compare_configs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save_config(name: str, cfg: dict) -> None:
    p = _config_dir() / f"{name}.json"
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_config(name: str) -> dict | None:
    p = _config_dir() / f"{name}.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _list_configs() -> list[str]:
    try:
        return [p.stem for p in sorted(_config_dir().glob("*.json"))]
    except Exception:
        return []


# ── Render ────────────────────────────────────────────────────────────────────

def render(ns: dict) -> None:
    globals().update(ns)

    st.markdown('<div class="section-title">Vergleich</div>', unsafe_allow_html=True)
    st.caption("Vergleiche OCR- und Audio-Auswertungen aus mehreren JSON-Dateien.")

    # ── Session state defaults ────────────────────────────────────────────────
    st.session_state.setdefault("cmp_files", [])
    st.session_state.setdefault("cmp_external_sources", {})
    # cmp_files: list of {"path": str, "label": str, "offset_s": float}
    st.session_state.setdefault("cmp_charts", [
        {"title": "Diagramm 1", "x_col": "time_s", "y_col": "", "plot_type": "line"}
    ])
    # cmp_data: {path: {col: [values]}}  — cache, rebuilt when selection/offset changes
    st.session_state.setdefault("cmp_data", {})

    # ── Apply pending widget-key sync (must happen before widgets are instantiated) ──
    _pending = st.session_state.pop("_cmp_pending_sync", None)
    if _pending is not None:
        for _ci, _ch in enumerate(_pending):
            st.session_state[f"cmp_ctitle_{_ci}"] = _ch.get("title", f"Diagramm {_ci+1}")
            st.session_state[f"cmp_ctype_{_ci}"] = _ch.get("plot_type", "line")
            if _ch.get("plot_type") == "geoplot":
                st.session_state[f"cmp_cgeo_{_ci}"] = _ch.get("color_col", "")
                st.session_state[f"cmp_gdelta_{_ci}"] = bool(_ch.get("show_delta", False))
                if _ch.get("ref_label"):
                    st.session_state[f"cmp_gref_{_ci}"] = _ch["ref_label"]
            else:
                st.session_state[f"cmp_cx_{_ci}"] = _ch.get("x_col", "time_s")
                st.session_state[f"cmp_cy_{_ci}"] = _ch.get("y_col", "")

    # ── 1. Datei-Auswahl ─────────────────────────────────────────────────────
    st.markdown("### Dateien")
    available = _scan_available_jsons()
    avail_paths = {a["path"] for a in available}

    busy_paths = {a["path"] for a in available if a["busy"]}
    selectable = [a for a in available if not a["busy"]]
    label_map = {
        a["path"]: (a["title"] if a.get("title") else a["folder"])
        for a in available
    }

    # Build label→path map (append short folder id if label is duplicate)
    _label_counts: dict[str, int] = {}
    for a in selectable:
        lbl = label_map.get(a["path"], Path(a["path"]).stem)
        _label_counts[lbl] = _label_counts.get(lbl, 0) + 1
    _seen: dict[str, int] = {}
    _opt_labels: list[str] = []
    _label_to_path: dict[str, str] = {}
    for a in selectable:
        lbl = label_map.get(a["path"], Path(a["path"]).stem)
        if _label_counts[lbl] > 1:
            _seen[lbl] = _seen.get(lbl, 0) + 1
            lbl = f"{lbl} [{Path(a['path']).stem[-8:]}]"
        _opt_labels.append(lbl)
        _label_to_path[lbl] = a["path"]

    current_paths = [f["path"] for f in st.session_state.cmp_files]
    _path_to_label = {v: k for k, v in _label_to_path.items()}
    valid_current_labels = [
        _path_to_label[p] for p in current_paths
        if p in _path_to_label and p not in busy_paths
    ]

    chosen_labels = st.multiselect(
        "JSON-Dateien auswählen (mit OCR oder Audio-Auswertung)",
        options=_opt_labels,
        default=valid_current_labels,
        key="cmp_file_chooser",
    )
    chosen = [_label_to_path[lbl] for lbl in chosen_labels if lbl in _label_to_path]
    if busy_paths:
        st.caption(f"⚠️ {len(busy_paths)} Datei(en) werden gerade vom Watchdog bearbeitet und sind nicht auswählbar.")

    # Sync cmp_files with chosen selection
    existing = {f["path"]: f for f in st.session_state.cmp_files}
    new_files = []
    for p in chosen:
        if p in existing:
            new_files.append(existing[p])
        else:
            # prefer title; folder as fallback so label is always human-readable
            _a = next((a for a in available if a["path"] == p), {})
            _lbl = _a.get("title") or _a.get("folder") or Path(p).stem
            new_files.append({"path": p, "label": _lbl, "offset_s": 0.0, "offset_m": 0.0})
    st.session_state.cmp_files = new_files

    st.markdown("### Externe Excel/CSV-Tabelle")
    ext_uploads = st.file_uploader(
        "Externe Tabelle laden",
        type=["xlsx", "xls", "csv"],
        accept_multiple_files=True,
        key="cmp_external_uploads",
        help="Spalten koennen auf interne Namen wie time_s, rpm oder v_Fzg_kmph gemappt werden.",
    )
    external_files: list[dict] = []
    external_data: dict[str, dict] = {}
    for ei, uf in enumerate(ext_uploads or []):
        ext_id = f"external::{ei}::{getattr(uf, 'name', 'table')}"
        try:
            df_ext = _read_external_table(uf)
        except Exception as exc:
            st.warning(f"Externe Tabelle '{getattr(uf, 'name', '')}' konnte nicht gelesen werden: {exc}")
            continue
        if df_ext is None or df_ext.empty:
            st.warning(f"Externe Tabelle '{getattr(uf, 'name', '')}' ist leer.")
            continue
        with st.container(border=True):
            st.caption(f"Extern: {getattr(uf, 'name', '')} ({len(df_ext)} Zeilen)")
            numeric_ext_cols = list(df_ext.columns)
            map_targets = ["time_s", "rpm", "v_Fzg_kmph", "s_m", "track_xy_x", "track_xy_y"]
            aliases = {
                "time_s": ["time_s", "t_s", "time", "t"],
                "rpm": ["rpm", "n_VKM_anzeige_Upm1n", "n", "engine_rpm"],
                "v_Fzg_kmph": ["v_Fzg_kmph", "v_kmph", "speed", "kmph"],
                "s_m": ["s_m", "distance", "dist_m"],
                "track_xy_x": ["track_xy_x", "x"],
                "track_xy_y": ["track_xy_y", "y"],
            }
            mapping: dict[str, str] = {}
            mcols = st.columns(3)
            for mi, target in enumerate(map_targets):
                opts = [""] + [str(c) for c in numeric_ext_cols]
                default = ""
                for a in aliases.get(target, []):
                    hit = next((str(c) for c in numeric_ext_cols if str(c).lower() == a.lower()), "")
                    if hit:
                        default = hit
                        break
                val = mcols[mi % 3].selectbox(
                    target,
                    options=opts,
                    index=opts.index(default) if default in opts else 0,
                    key=f"cmp_ext_map_{ei}_{target}",
                    format_func=lambda v: "(nicht zuordnen)" if v == "" else v,
                )
                if val:
                    mapping[target] = val
            ecol1, ecol2, ecol3 = st.columns([3, 2, 2])
            label = ecol1.text_input(
                "Label extern",
                value=Path(str(getattr(uf, "name", f"extern_{ei}"))).stem,
                key=f"cmp_ext_label_{ei}",
            )
            off_s = ecol2.number_input(
                "Zeitversatz extern [s]",
                value=0.0, step=0.001, format="%.3f", key=f"cmp_ext_offs_{ei}",
            )
            off_m = ecol3.number_input(
                "Streckenversatz extern [m]",
                value=0.0, step=1.0, format="%.1f", key=f"cmp_ext_offm_{ei}",
            )
        ext_cols = _external_table_to_cols(df_ext, mapping, off_s, off_m)
        st.session_state.cmp_external_sources[ext_id] = {"label": label, "columns": list(ext_cols.keys())}
        external_files.append({"path": ext_id, "label": label, "offset_s": off_s, "offset_m": off_m})
        external_data[ext_id] = ext_cols

    if not st.session_state.cmp_files and not external_files:
        st.info("Mindestens eine JSON-Datei auswählen.")
        _render_config_section()
        return

    # Per-file label + offsets
    for i, f in enumerate(st.session_state.cmp_files):
        f.setdefault("offset_m", 0.0)
        c1, c2, c3, c4 = st.columns([3, 2, 2, 1])
        f["label"] = c1.text_input(
            "Label", value=f["label"], key=f"cmp_lbl_{i}", label_visibility="collapsed"
        )
        f["offset_s"] = c2.number_input(
            "Zeitversatz [s]", value=float(f["offset_s"]),
            step=0.001, format="%.3f", key=f"cmp_off_{i}", label_visibility="collapsed",
            help="Zeitversatz: wird auf time_s addiert",
        )
        f["offset_m"] = c3.number_input(
            "Streckenversatz [m]", value=float(f["offset_m"]),
            step=1.0, format="%.1f", key=f"cmp_offm_{i}", label_visibility="collapsed",
            help="Streckenversatz: wird auf s_m addiert (nur wenn s_m im JSON vorhanden)",
        )
        c4.caption(f"{f['offset_s']:+.3f}s / {f['offset_m']:+.0f}m")

    st.markdown("### Abgeleitete Verlaeufe")
    with st.expander("Strecke, Radleistung und Raddrehmoment berechnen", expanded=False):
        st.caption(
            "s_m_from_v wird immer aus v_Fzg_kmph und time_s berechnet. "
            "Radleistung/Raddrehmoment werden nur berechnet, wenn die Pflichtwerte vorhanden sind. "
            "Steigung wird aktuell mit 0 % angesetzt; spaeter kann sie ueber Strecke/GPS per Lookup ergaenzt werden."
        )
        _cmp_enable_wheel = st.checkbox(
            "Radleistung und Raddrehmoment aus Fahrwiderstaenden berechnen",
            value=bool(st.session_state.get("cmp_enable_wheel_dynamics", False)),
            key="cmp_enable_wheel_dynamics",
        )
        _d1, _d2, _d3, _d4 = st.columns(4)
        _rho = _d1.text_input("Luftdichte rho [kg/m^3]", value=st.session_state.get("cmp_rho_txt", "1,225"), key="cmp_rho_txt")
        _g = _d2.text_input("Erdbeschleunigung g [m/s^2]", value=st.session_state.get("cmp_g_txt", "9,81"), key="cmp_g_txt")
        _crr = _d3.text_input("Rollreibungskoeffizient", value=st.session_state.get("cmp_crr_txt", "0,01"), key="cmp_crr_txt")
        _lam = _d4.text_input("Rotationsmassenfaktor Lambda", value=st.session_state.get("cmp_lambda_txt", "1,00"), key="cmp_lambda_txt")
        _r1, _r2, _r3, _r4 = st.columns(4)
        _mass = _r1.text_input("Masse m [kg] (Pflicht)", value=st.session_state.get("cmp_mass_txt", ""), key="cmp_mass_txt")
        _cw = _r2.text_input("Luftwiderstandsbeiwert Cw (Pflicht)", value=st.session_state.get("cmp_cw_txt", ""), key="cmp_cw_txt")
        _area = _r3.text_input("Stirnflaeche A [m^2] (Pflicht)", value=st.session_state.get("cmp_area_txt", ""), key="cmp_area_txt")
        _rdyn = _r4.text_input("r dyn [m] fuer Drehmoment", value=st.session_state.get("cmp_rdyn_txt", ""), key="cmp_rdyn_txt")
        st.caption("Hinweis: Fuer Raddrehmoment in Nm ist r dyn erforderlich. Ohne r dyn wird nur Radleistung berechnet.")
    _cmp_deriv_cfg = {
        "enable_wheel_dynamics": bool(_cmp_enable_wheel),
        "rho": _to_float_or_none(_rho),
        "g": _to_float_or_none(_g),
        "crr": _to_float_or_none(_crr),
        "lambda_rot": _to_float_or_none(_lam),
        "mass_kg": _to_float_or_none(_mass),
        "cw": _to_float_or_none(_cw),
        "area_m2": _to_float_or_none(_area),
        "r_dyn_m": _to_float_or_none(_rdyn),
    }
    if _cmp_enable_wheel:
        _missing_global = [
            name for name, val in {
                "Masse m kg": _cmp_deriv_cfg["mass_kg"],
                "Cw": _cmp_deriv_cfg["cw"],
                "Stirnflaeche A m^2": _cmp_deriv_cfg["area_m2"],
            }.items()
            if val is None
        ]
        if _missing_global:
            st.warning("Fahrwiderstandsberechnung unvollstaendig: " + ", ".join(_missing_global))
        if _cmp_deriv_cfg["r_dyn_m"] is None:
            st.info("Raddrehmoment wird erst berechnet, wenn r dyn [m] eingetragen ist.")

    # Build a short hash of the current plausibility catalog so that changes
    # to bounds/slopes invalidate the cache and trigger a reload+refilter.
    _cmp_catalog = st.session_state.get("roi_catalog") or {}
    try:
        import hashlib as _hl
        _plaus_hash = _hl.md5(
            json.dumps(_cmp_catalog.get("plausibility") or {}, sort_keys=True).encode()
        ).hexdigest()[:8]
    except Exception:
        _plaus_hash = "0"

    # Load data (cache by path + offsets + catalog hash + mtime)
    cmp_data: dict[str, dict] = {}
    for f in st.session_state.cmp_files:
        f.setdefault("offset_m", 0.0)
        try:
            _mtime = Path(f["path"]).stat().st_mtime
        except Exception:
            _mtime = 0
        key = f"{f['path']}::{f['offset_s']}::{f['offset_m']}::{_plaus_hash}::{_mtime}"
        cached = st.session_state.cmp_data.get(key)
        if cached is None:
            import copy as _copy
            cached = _load_file_data(f["path"], f["offset_s"], f["offset_m"])
            # Apply plausibility + slope filter using current catalog
            if _cmp_catalog and cached:
                try:
                    from app_tabs.plausibility_filter import filter_cols as _fc
                    _fc(cached, _cmp_catalog)
                except Exception:
                    pass
            st.session_state.cmp_data[key] = cached
        import copy as _copy
        cmp_data[f["path"]] = _copy.deepcopy(cached)
    for _ext_id, _ext_cols in external_data.items():
        import copy as _copy
        cmp_data[_ext_id] = _copy.deepcopy(_ext_cols)
    display_files = list(st.session_state.cmp_files) + list(external_files)

    _derive_missing: dict[str, list[str]] = {}
    for _src in display_files:
        _cols = cmp_data.get(_src["path"], {})
        if not _cols:
            continue
        _ok_der, _miss_der = _add_compare_derivatives(_cols, _cmp_deriv_cfg)
        if not _ok_der and _miss_der:
            _derive_missing[str(_src.get("label") or _src.get("path"))] = _miss_der
    if _derive_missing and _cmp_deriv_cfg.get("enable_wheel_dynamics"):
        _msg = "; ".join(f"{lbl}: {', '.join(vals)}" for lbl, vals in _derive_missing.items())
        st.warning("Radleistung/Raddrehmoment nicht fuer alle Quellen berechnet: " + _msg)

    # Collect all column names across all loaded files
    all_cols: list[str] = []
    for d in cmp_data.values():
        for c in d:
            if c not in all_cols:
                all_cols.append(c)
    numeric_cols = [c for c in all_cols if c != "frame_idx" or True]  # keep all for X

    st.divider()

    # ── 2. Diagramme ─────────────────────────────────────────────────────────
    _dh1, _dh2 = st.columns([6, 1])
    _dh1.markdown("### Diagramme")
    st.session_state.setdefault("cmp_light_mode", False)
    st.session_state["cmp_light_mode"] = _dh2.toggle(
        "Hell", value=bool(st.session_state.get("cmp_light_mode", False)),
        key="cmp_global_theme",
    )

    charts = st.session_state.cmp_charts
    to_remove = None

    for ci, chart in enumerate(charts):
        with st.container(border=True):
            h1, h2 = st.columns([6, 1])
            chart["title"] = h1.text_input(
                "Titel", value=chart.get("title", f"Diagramm {ci+1}"),
                key=f"cmp_ctitle_{ci}", label_visibility="collapsed"
            )
            if h2.button("✕", key=f"cmp_rm_{ci}", help="Diagramm entfernen"):
                to_remove = ci

            col_a, col_b, col_c = st.columns([2, 2, 2])

            _type_opts = ["line", "scatter", "geoplot"]
            _type_labels = {"line": "Linie", "scatter": "Punkte", "geoplot": "Geoplot"}
            _cur_type = chart.get("plot_type", "line")
            if _cur_type not in _type_opts:
                _cur_type = "line"
            chart["plot_type"] = col_c.selectbox(
                "Darstellung", options=_type_opts, index=_type_opts.index(_cur_type),
                format_func=lambda v: _type_labels.get(v, v),
                key=f"cmp_ctype_{ci}",
            )

            if chart["plot_type"] == "geoplot":
                # Color variable selector; X/Y are fixed to track_xy_x / track_xy_y
                _geo_opts = [""] + [c for c in all_cols if c not in ("track_xy_x", "track_xy_y")]
                _gc_def = chart.get("color_col", "v_Fzg_kmph")
                _gc_idx = _geo_opts.index(_gc_def) if _gc_def in _geo_opts else 0
                chart["color_col"] = col_a.selectbox(
                    "Farbvariable", options=_geo_opts, index=_gc_idx,
                    format_func=lambda v: "(keine)" if v == "" else v,
                    key=f"cmp_cgeo_{ci}",
                )
                col_b.caption("X: `track_xy_x`  ·  Y: `track_xy_y`")
                chart["x_col"] = "track_xy_x"
                chart["y_col"] = "track_xy_y"
            else:
                x_opts = ["time_s"] + [c for c in all_cols if c != "time_s"]
                x_def = chart.get("x_col", "time_s")
                x_idx = x_opts.index(x_def) if x_def in x_opts else 0
                chart["x_col"] = col_a.selectbox(
                    "X-Achse", options=x_opts, index=x_idx, key=f"cmp_cx_{ci}",
                )
                y_opts = [c for c in all_cols if c != chart["x_col"]]
                y_def = chart.get("y_col", "")
                y_idx = y_opts.index(y_def) if y_def in y_opts else 0
                chart["y_col"] = (
                    col_b.selectbox("Y-Achse", options=y_opts, index=y_idx if y_opts else 0, key=f"cmp_cy_{ci}")
                    if y_opts else ""
                )

            # Render this chart
            if chart["plot_type"] == "geoplot":
                _render_geoplot_chart(chart, display_files, cmp_data, ci)
            elif chart["y_col"] and all_cols:
                _render_chart(chart, display_files, cmp_data, ci)
            else:
                st.caption("Y-Achse auswählen um das Diagramm anzuzeigen.")

    if to_remove is not None:
        charts.pop(to_remove)
        st.rerun()

    if st.button("+ Diagramm hinzufügen", key="cmp_add_chart"):
        charts.append({
            "title": f"Diagramm {len(charts)+1}",
            "x_col": "time_s",
            "y_col": all_cols[1] if len(all_cols) > 1 else "",
            "plot_type": "line",
        })
        st.rerun()

    st.divider()
    _render_config_section()


def _safe_sheet_name(label: str) -> str:
    """Sanitize a string for use as an Excel sheet name."""
    import re
    name = re.sub(r'[/\\?*:\[\]\']', "_", str(label or "Kurve"))
    return name[:31] or "Kurve"


def _build_excel_bytes(traces: list[dict], x_col: str, y_col: str) -> bytes:
    """Build an Excel workbook: one sheet per trace + one combined sheet."""
    import io
    import pandas as pd

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        combined_parts: list[pd.DataFrame] = []
        for trace in traces:
            df = pd.DataFrame({x_col: trace["xs"], y_col: trace["ys"]})
            df.to_excel(writer, sheet_name=_safe_sheet_name(trace["label"]), index=False)
            combined_parts.append(
                df.rename(columns={x_col: f"{x_col}_{trace['label'][:20]}",
                                   y_col: f"{y_col}_{trace['label'][:20]}"})
            )
        if len(combined_parts) > 1:
            import functools
            combined = functools.reduce(
                lambda a, b: pd.concat([a.reset_index(drop=True), b.reset_index(drop=True)], axis=1),
                combined_parts,
            )
            combined.to_excel(writer, sheet_name="Kombiniert", index=False)
    return buf.getvalue()


def _render_chart(chart: dict, files: list[dict], cmp_data: dict[str, dict], chart_idx: int = 0) -> None:
    try:
        import plotly.graph_objects as go
        fig = go.Figure()
        x_col = chart["x_col"]
        y_col = chart["y_col"]
        mode = "lines" if chart.get("plot_type") == "line" else "markers"
        traces: list[dict] = []

        for f in files:
            data = cmp_data.get(f["path"], {})
            xs = data.get(x_col)
            ys = data.get(y_col)
            if not xs or not ys or len(xs) != len(ys):
                continue
            fig.add_trace(go.Scatter(
                x=xs, y=ys,
                mode=mode,
                name=f["label"],
                marker=dict(size=4) if mode == "markers" else {},
            ))
            traces.append({"label": f["label"], "xs": list(xs), "ys": list(ys)})

        _light = bool(st.session_state.get("cmp_light_mode"))
        _chart_theme = "plotly_white" if _light else "plotly_dark"
        _fc = "black" if _light else "white"
        _gc = "rgba(0,0,0,0.15)" if _light else "rgba(255,255,255,0.1)"
        fig.update_layout(
            title=dict(text=chart.get("title", ""), font_color=_fc),
            margin=dict(l=40, r=20, t=40, b=40),
            height=340,
            legend=dict(orientation="h", yanchor="bottom", y=1.02,
                        xanchor="right", x=1, font_color=_fc),
            template=_chart_theme,
            paper_bgcolor="white" if _light else "#0e1117",
            plot_bgcolor="white" if _light else "#0e1117",
            font=dict(color=_fc),
        )
        fig.update_xaxes(
            title=dict(text=x_col, font=dict(color=_fc)),
            tickfont=dict(color=_fc),
            gridcolor=_gc, linecolor=_fc, zerolinecolor=_gc,
        )
        fig.update_yaxes(
            title=dict(text=y_col, font=dict(color=_fc)),
            tickfont=dict(color=_fc),
            gridcolor=_gc, linecolor=_fc, zerolinecolor=_gc,
        )
        st.plotly_chart(fig, use_container_width=True)

        if traces:
            try:
                excel_bytes = _build_excel_bytes(traces, x_col, y_col)
                safe_title = "".join(
                    c if c.isalnum() or c in " ._-" else "_"
                    for c in chart.get("title", f"Diagramm_{chart_idx + 1}")
                ).strip() or f"Diagramm_{chart_idx + 1}"
                st.download_button(
                    label="⬇ Als Excel herunterladen",
                    data=excel_bytes,
                    file_name=f"{safe_title}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key=f"cmp_dl_{chart_idx}",
                )
            except Exception as dl_err:
                st.caption(f"Excel-Export nicht verfügbar: {dl_err}")
    except Exception as e:
        st.caption(f"Diagramm-Fehler: {e}")


def _render_geoplot_chart(chart: dict, files: list[dict], cmp_data: dict[str, dict], chart_idx: int) -> None:
    """Render a tiled geoplot — one subplot per file, side by side."""
    color_col = chart.get("color_col") or None
    if color_col == "":
        color_col = None

    # ── Build file traces ─────────────────────────────────────────────────────
    file_traces: list[dict] = []
    for f in files:
        d = cmp_data.get(f["path"], {})
        xs = d.get("track_xy_x")
        ys = d.get("track_xy_y")
        if not xs or not ys or len(xs) != len(ys):
            continue
        cl = None
        try:
            trk = _load_trkCalSlim(f["path"])
            cl_raw = trk.get("centerline_px")
            if isinstance(cl_raw, (list, tuple)) and len(cl_raw) >= 2:
                cl = [
                    [float(p[0]), float(p[1])]
                    for p in cl_raw
                    if isinstance(p, (list, tuple)) and len(p) >= 2
                ]
                if len(cl) < 2:
                    cl = None
        except Exception:
            pass
        file_traces.append({
            "name": f["label"],
            "xs": xs,
            "ys": ys,
            "cs": list(d.get(color_col) or []) if color_col else None,
            "ts": list(d.get("time_s") or []),
            "ps": list(d.get("s_m") or []),  # track position axis for delta
            "centerline": cl,
        })

    if not file_traces:
        st.caption("Keine track_xy-Daten in den ausgewählten Dateien vorhanden.")
        return

    # ── Delta options (only when multiple files and color column selected) ────
    is_delta = False
    if color_col and len(file_traces) > 1:
        _gd1, _gd2 = st.columns([1, 3])
        chart["show_delta"] = _gd1.checkbox(
            "Delta zur Referenz",
            value=bool(chart.get("show_delta", False)),
            key=f"cmp_gdelta_{chart_idx}",
            help="Zeigt Differenz (Datei − Referenz) der Farbvariable statt Absolutwert.",
        )
        if chart["show_delta"]:
            _ref_labels = [tr["name"] for tr in file_traces]
            _ref_def = chart.get("ref_label", _ref_labels[0])
            _ref_sel = _gd2.selectbox(
                "Referenzdatei", options=_ref_labels,
                index=_ref_labels.index(_ref_def) if _ref_def in _ref_labels else 0,
                key=f"cmp_gref_{chart_idx}",
                label_visibility="collapsed",
            )
            chart["ref_label"] = _ref_sel
            ref_i = _ref_labels.index(_ref_sel)

            # Compute delta aligned by s_m (track position) if available, else time_s
            import numpy as _np

            def _axis(tr):
                """Return (axis_array, label) — prefer s_m, fall back to time_s."""
                ps = _np.array(tr.get("ps") or [], dtype=float)
                ok = _np.isfinite(ps)
                if ok.sum() >= 10:
                    return ps, "s_m"
                return _np.array(tr.get("ts") or [], dtype=float), "time_s"

            ref_ax_raw, _ax_label = _axis(file_traces[ref_i])
            ref_cs_raw = _np.array(file_traces[ref_i].get("cs") or [], dtype=float)
            if len(ref_ax_raw) >= 2 and len(ref_cs_raw) == len(ref_ax_raw):
                _ref_ok = _np.isfinite(ref_ax_raw) & _np.isfinite(ref_cs_raw)
                ref_ax = ref_ax_raw[_ref_ok]
                ref_cs = ref_cs_raw[_ref_ok]
                if len(ref_ax) >= 2:
                    for j, tr in enumerate(file_traces):
                        tr_ax, _ = _axis(tr)
                        tr_cs = _np.array([
                            v if isinstance(v, (int, float)) and not (v != v) else float("nan")
                            for v in (tr.get("cs") or [])
                        ], dtype=float)
                        tr_xs = tr.get("xs") or []
                        tr_ys = tr.get("ys") or []
                        if len(tr_ax) > 0 and len(tr_cs) == len(tr_ax):
                            interp_ref = _np.interp(tr_ax, ref_ax, ref_cs,
                                                    left=float("nan"), right=float("nan"))
                            delta = tr_cs - interp_ref
                            no_cs = ~_np.isfinite(tr_cs)
                            no_xy = _np.array([
                                not (isinstance(x, (int, float)) and _np.isfinite(float(x)))
                                or not (isinstance(y, (int, float)) and _np.isfinite(float(y)))
                                for x, y in zip(tr_xs, tr_ys)
                            ] + [False] * max(0, len(delta) - len(tr_xs)), dtype=bool)
                            delta[no_cs | no_xy[:len(delta)]] = float("nan")
                            tr["cs"] = delta.tolist()
                        else:
                            tr["cs"] = None
                    # Reference shows as gray (cs=None) since delta with itself is always 0
                    file_traces[ref_i]["cs"] = None
                    is_delta = True

    _theme = "plotly_white" if st.session_state.get("cmp_light_mode") else "plotly_dark"
    try:
        from app_tabs.track_geoplot import make_geoplot_tiled
        fig = make_geoplot_tiled(file_traces, color_col=color_col, is_delta=is_delta, template=_theme)
        st.plotly_chart(fig, use_container_width=True, key=f"cmp_geo_{chart_idx}")
    except Exception as e:
        st.caption(f"Geoplot-Fehler: {e}")


def _render_config_section() -> None:
    """Save / load comparison configuration."""
    st.markdown("### Konfiguration speichern / laden")
    sc1, sc2 = st.columns(2)

    with sc1:
        st.markdown("**Speichern**")
        cfg_name = st.text_input(
            "Name", value="vergleich_1", key="cmp_save_name", label_visibility="collapsed"
        )
        if st.button("Speichern", key="cmp_save_btn"):
            cfg = {
                "files": [
                    {"path": f["path"], "label": f["label"],
                     "offset_s": f["offset_s"], "offset_m": f.get("offset_m", 0.0)}
                    for f in st.session_state.cmp_files
                ],
                "charts": list(st.session_state.cmp_charts),
            }
            try:
                _save_config(cfg_name.strip() or "vergleich", cfg)
                st.success(f"Gespeichert: {cfg_name}")
            except Exception as e:
                st.error(f"Fehler: {e}")

    with sc2:
        st.markdown("**Laden**")
        configs = _list_configs()
        if configs:
            sel = st.selectbox(
                "Konfiguration", options=configs, key="cmp_load_sel",
                label_visibility="collapsed"
            )
            if st.button("Laden", key="cmp_load_btn"):
                loaded = _load_config(sel)
                if loaded:
                    st.session_state.cmp_files = loaded.get("files", [])
                    st.session_state.cmp_charts = loaded.get("charts", [])
                    st.session_state.cmp_data = {}
                    st.session_state["_cmp_pending_sync"] = loaded.get("charts", [])
                    st.rerun()
                else:
                    _cfg_path = _config_dir() / f"{sel}.json"
                    st.error(f"Laden fehlgeschlagen. Datei: {_cfg_path}")
        else:
            st.caption("Noch keine gespeicherten Konfigurationen.")
