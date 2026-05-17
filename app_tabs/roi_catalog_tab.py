"""ROI Catalog tab — manage ROI names, FMT priority, and plausibility bounds."""
from __future__ import annotations
import json
import math
from pathlib import Path


_CATALOG_FILE = Path("logs") / "roi_catalog.json"

_BUILTIN_NAMES = [
    "_", "t_s", "v_Fzg_kmph", "v_Fzg_mph", "numgear_GET",
    "a_G", "a_mps2", "a_x_G", "a_x_pos_G", "a_x_neg_G", "a_x_mps",
    "a_y_G", "a_y_pos_G", "a_y_neg_G", "a_y_mps",
    "P_kW", "M_Nm", "n_mot_Upmin",
    "M_VL_Nm", "M_VR_Nm", "M_HL_Nm", "M_HR_Nm",
    "stellung_gaspedal_proz", "stellung_bremspedal_proz", "track_minimap",
]

# ROIs for which a numeric plausibility bound makes no sense.
# t_s is a time string (e.g. "1:23.4") — float() fails → check would always be "–".
# _ and track_minimap have no numeric OCR value at all.
_NO_PLAUS_NAMES = {"_", "t_s", "track_minimap"}

# ROIs for which FMT priority is not useful (no OCR, or fixed internal handling).
_NO_FMT_NAMES = {"_", "track_minimap"}

_DEFAULT_FMT_PRIORITY: dict[str, list[str]] = {
    "v_Fzg_kmph": ["int_min2_max3", "int_3"],
    "v_Fzg_mph":  ["int_min2_max3", "int_3"],
    "numgear_GET": ["int_1"],
    "t_s":         ["time_m:ss.S", "time_m:ss"],
    "a_G":         ["float"],
    "a_mps2":      ["float"],
    "P_kW":        ["int_3"],
    "M_Nm":        ["int_4"],
    "n_mot_Upmin": ["int_4"],
    "stellung_gaspedal_proz":  ["int_3"],
    "stellung_bremspedal_proz": ["int_3"],
}

_DEFAULT_PLAUSIBILITY: dict[str, dict] = {
    "v_Fzg_kmph": {"min": 0,     "max": 350,   "max_slope": 150},
    "v_Fzg_mph":  {"min": 0,     "max": 220,   "max_slope": 100},
    "numgear_GET":{"min": 0,     "max": 10,    "max_slope": 5},
    "a_G":        {"min": -5,    "max": 5},
    "a_mps2":     {"min": -50,   "max": 50},
    "P_kW":       {"min": -2000, "max": 2000,  "max_slope": 2000},
    "M_Nm":       {"min": -5000, "max": 5000,  "max_slope": 5000},
    "n_mot_Upmin":{"min": 0,     "max": 20000, "max_slope": 8000},
    "stellung_gaspedal_proz":   {"min": 0, "max": 100, "max_slope": 300},
    "stellung_bremspedal_proz": {"min": 0, "max": 100, "max_slope": 300},
}


# ── Public API ────────────────────────────────────────────────────────────────

def load_catalog() -> dict:
    try:
        if _CATALOG_FILE.exists():
            raw = json.loads(_CATALOG_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                raw.setdefault("custom_names", [])
                raw.setdefault("fmt_priority", dict(_DEFAULT_FMT_PRIORITY))
                raw.setdefault("plausibility", dict(_DEFAULT_PLAUSIBILITY))
                return raw
    except Exception:
        pass
    return {
        "custom_names": [],
        "fmt_priority": dict(_DEFAULT_FMT_PRIORITY),
        "plausibility": dict(_DEFAULT_PLAUSIBILITY),
    }


def save_catalog(catalog: dict) -> None:
    _CATALOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CATALOG_FILE.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def all_roi_names(catalog: dict) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for n in _BUILTIN_NAMES + list(catalog.get("custom_names") or []):
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def ordered_fmt_options(roi_name: str, catalog: dict, all_fmts: list[str]) -> list[str]:
    priority = list(catalog.get("fmt_priority", {}).get(roi_name) or [])
    rest = [f for f in all_fmts if f not in priority]
    return [f for f in priority if f in all_fmts] + rest


# ── Render ────────────────────────────────────────────────────────────────────

def render(ns: dict) -> None:
    globals().update(ns)
    import pandas as pd

    st.markdown('<div class="section-title">ROI Katalog</div>', unsafe_allow_html=True)

    st.session_state.setdefault("roi_catalog", load_catalog())
    catalog: dict = st.session_state.roi_catalog
    all_fmts: list[str] = globals().get("FMT_OPTIONS") or []
    changed = False

    # ── 1. ROI-Namen ──────────────────────────────────────────────────────────
    with st.expander("ROI-Namen", expanded=True):
        st.markdown("**Eingebaute Namen** (nicht löschbar):")
        st.caption(", ".join(_BUILTIN_NAMES))

        st.markdown("**Eigene Namen:**")
        custom_names: list[str] = list(catalog.get("custom_names") or [])
        custom_df = pd.DataFrame({"ROI Name": pd.Series(custom_names, dtype="object")})
        edited_custom = st.data_editor(
            custom_df,
            column_config={
                "ROI Name": st.column_config.TextColumn("ROI Name", width=220),
            },
            num_rows="dynamic",
            hide_index=True,
            use_container_width=False,
            key="cat_custom_names_editor",
        )
        if edited_custom is not None:
            new_custom = [
                str(r.get("ROI Name") or "").strip()
                for _, r in edited_custom.iterrows()
                if str(r.get("ROI Name") or "").strip()
                and str(r.get("ROI Name") or "").strip() not in _BUILTIN_NAMES
            ]
            # deduplicate, preserve order
            seen_c: set[str] = set()
            deduped: list[str] = []
            for n in new_custom:
                if n not in seen_c:
                    seen_c.add(n)
                    deduped.append(n)
            if deduped != custom_names:
                catalog["custom_names"] = deduped
                changed = True

    # ── 2. FMT-Priorität ──────────────────────────────────────────────────────
    with st.expander("FMT-Priorität", expanded=True):
        st.caption(
            "Wähle die bevorzugten Formate aus der Liste. "
            "Die Reihenfolge bestimmt die Priorität (oben = höchste Priorität). "
            "Wähle in der gewünschten Reihenfolge aus."
        )
        fmt_prio: dict = dict(catalog.get("fmt_priority") or {})
        all_roi = all_roi_names(catalog)
        fmt_roi_names = [n for n in all_roi if n not in _NO_FMT_NAMES]

        for roi in fmt_roi_names:
            cur = [f for f in (fmt_prio.get(roi) or []) if f in all_fmts]
            new_sel = st.multiselect(
                roi,
                options=all_fmts,
                default=cur,
                key=f"cat_fmt_ms_{roi}",
                label_visibility="visible",
            )
            if new_sel != cur:
                fmt_prio[roi] = new_sel
                changed = True

        if changed:
            catalog["fmt_priority"] = fmt_prio

    # ── 3. Plausibilitätsgrenzen ──────────────────────────────────────────────
    with st.expander("Plausibilitätsgrenzen", expanded=True):
        st.caption(
            "Min/Max und max. Steigung [Einheit/s] für numerische ROIs. "
            "Werte außerhalb Min/Max oder mit Sprung > Max Steigung/s werden beim "
            "Filtern auf leer gesetzt. "
            "t_s, _ und track_minimap sind ausgenommen (kein numerischer OCR-Wert)."
        )
        plaus: dict = dict(catalog.get("plausibility") or {})
        plaus_names = [n for n in all_roi_names(catalog) if n not in _NO_PLAUS_NAMES]

        plaus_rows = []
        for n in plaus_names:
            cur = plaus.get(n) or {}
            ms = cur.get("max_slope")
            plaus_rows.append({
                "ROI Name": n,
                "Min": float(cur.get("min", 0.0)),
                "Max": float(cur.get("max", 9999.0)),
                "Max Steigung /s": float(ms) if ms is not None else None,
            })
        plaus_df = pd.DataFrame(plaus_rows) if plaus_rows else pd.DataFrame(
            columns=["ROI Name", "Min", "Max", "Max Steigung /s"]
        )
        # Ensure float dtype so NumberColumn works even when all values are None
        for _c in ("Min", "Max", "Max Steigung /s"):
            plaus_df[_c] = pd.to_numeric(plaus_df[_c], errors="coerce")

        edited_plaus = st.data_editor(
            plaus_df,
            column_config={
                "ROI Name": st.column_config.TextColumn("ROI Name", width=180, disabled=True),
                "Min": st.column_config.NumberColumn("Min", width=90, format="%.2f"),
                "Max": st.column_config.NumberColumn("Max", width=90, format="%.2f"),
                "Max Steigung /s": st.column_config.NumberColumn(
                    "Max Steigung /s", width=130, format="%.1f",
                    help="Maximale Wertänderung pro Sekunde. Leer = kein Limit.",
                ),
            },
            num_rows="fixed",
            hide_index=True,
            use_container_width=False,
            key="cat_plaus_editor",
        )
        if edited_plaus is not None and not plaus_df.equals(
            edited_plaus.reset_index(drop=True)
        ):
            for _, row in edited_plaus.iterrows():
                n = str(row.get("ROI Name") or "").strip()
                if not n:
                    continue
                try:
                    entry: dict = {
                        "min": float(row["Min"]),
                        "max": float(row["Max"]),
                    }
                    ms_val = row.get("Max Steigung /s")
                    if ms_val is not None and not (isinstance(ms_val, float) and math.isnan(ms_val)):
                        entry["max_slope"] = float(ms_val)
                    plaus[n] = entry
                except Exception:
                    pass
            catalog["plausibility"] = plaus
            changed = True

    if changed:
        save_catalog(catalog)
        st.session_state.roi_catalog = catalog

    st.caption(f"Katalog: `{_CATALOG_FILE}`")
