"""Shared plausibility + slope filtering and retroactive correction for OCR results."""
from __future__ import annotations
import math


def _atomic_write(path, doc: dict) -> None:
    """Write JSON atomically via a temp file + rename to prevent corruption on interrupt."""
    import json as _json
    from pathlib import Path
    p = Path(path)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(_json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)  # os.replace — atomic on POSIX, overwrites on Windows

# Columns that carry no numeric OCR value — never filtered by plausibility.
_SKIP_COLS = frozenset({
    "time_s", "frame_idx", "audio_time_s",
    "track_minimap_found", "track_minimap_x", "track_minimap_y",
    "track_xy_x", "track_xy_y", "track_pct",
})

# Track-related column names added by track_minimap processing.
_TRACK_COLS = (
    "track_minimap_found", "track_minimap_x", "track_minimap_y",
    "track_xy_x", "track_xy_y", "track_pct",
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _to_float(v) -> float | None:
    if v is None or v == "" or (isinstance(v, float) and math.isnan(v)):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _empty(v) -> str | float:
    """Return the correct 'missing' sentinel matching the original value type."""
    return "" if isinstance(v, str) else float("nan")


# ── plausibility / slope filter ───────────────────────────────────────────────

def filter_cols(cols: dict[str, list], catalog: dict) -> dict[str, list]:
    """
    Apply min/max bounds and max_slope from catalog plausibility to columnar data.

    Values that violate bounds are replaced with '' (string columns) or NaN
    (float columns). Works with both string values ('113') and float values.
    Modifies cols in-place and returns it.

    Slope is computed as |Δvalue / Δtime_s| and compared against max_slope [unit/s].
    The previous-valid-value is used so that NaN gaps don't suppress the check.
    """
    plaus: dict = catalog.get("plausibility") or {}
    time_raw = cols.get("time_s") or []
    time_s = [_to_float(t) for t in time_raw]

    for col, values in list(cols.items()):
        if col in _SKIP_COLS:
            continue
        bounds = plaus.get(col)
        if not bounds:
            continue
        lo = bounds.get("min")
        hi = bounds.get("max")
        max_slope = bounds.get("max_slope")
        if lo is None and hi is None and (max_slope is None or max_slope <= 0):
            continue

        filtered = list(values)
        floats = [_to_float(v) for v in filtered]

        # ── Min / Max ─────────────────────────────────────────────────────────
        if lo is not None or hi is not None:
            for i, fv in enumerate(floats):
                if fv is None:
                    continue
                if (lo is not None and fv < lo) or (hi is not None and fv > hi):
                    floats[i] = None
                    filtered[i] = _empty(filtered[i])

        # ── Slope ─────────────────────────────────────────────────────────────
        if max_slope is not None and max_slope > 0:
            prev_fv: float | None = None
            prev_t: float | None = None
            for i in range(len(floats)):
                fv = floats[i]
                t = time_s[i] if i < len(time_s) else None
                if fv is None or t is None:
                    continue
                if prev_fv is not None and prev_t is not None:
                    dt = t - prev_t
                    if dt > 0 and abs(fv - prev_fv) / dt > max_slope:
                        floats[i] = None
                        filtered[i] = _empty(filtered[i])
                        continue  # keep prev_fv/t at last valid point
                prev_fv = fv
                prev_t = t

        cols[col] = filtered

    return cols


# ── time-bounds trimming ──────────────────────────────────────────────────────

def _trim_tbl(tbl: dict, start_s: float, end_s: float | None) -> tuple[dict, int]:
    """
    Remove rows from a columnar dict where time_s < start_s or time_s > end_s.
    Returns (trimmed_tbl, n_removed).
    """
    ts_raw = tbl.get("time_s")
    if not ts_raw:
        return tbl, 0
    n = len(ts_raw)
    keep = []
    for i, t in enumerate(ts_raw):
        fv = _to_float(t)
        if fv is None:
            keep.append(i)
            continue
        if fv < start_s:
            continue
        if end_s is not None and fv > end_s:
            continue
        keep.append(i)
    removed = n - len(keep)
    if removed == 0:
        return tbl, 0
    out = {}
    for col, vals in tbl.items():
        if isinstance(vals, list) and len(vals) == n:
            out[col] = [vals[i] for i in keep]
        else:
            out[col] = vals
    return out, removed


# ── track-column status ───────────────────────────────────────────────────────

def needs_track_rerun(doc: dict) -> bool:
    """
    Return True when track_minimap is in the ROI table but track detection
    produced no results — signature of the list-vs-dict track_roi bug.

    Criteria:
      - track_minimap entry exists in roi_table
      - AND in cleaned/table: track_minimap_found is missing OR all zeros/empty
    """
    rr = doc.get("recordResult") if isinstance(doc, dict) else {}
    if not isinstance(rr, dict):
        return False
    ocr = rr.get("ocr")
    if not isinstance(ocr, dict):
        return False

    # Check roi_table for track_minimap
    has_track_roi = False
    rt = ocr.get("roi_table")
    if isinstance(rt, dict):
        names = rt.get("name_roi") or rt.get("name") or []
        if isinstance(names, list):
            has_track_roi = any(
                str(n or "").strip().lower() == "track_minimap" for n in names
            )
        else:
            has_track_roi = str(names or "").strip().lower() == "track_minimap"
    elif isinstance(rt, list):
        has_track_roi = any(
            str((r or {}).get("name_roi") or (r or {}).get("name") or "").strip().lower()
            == "track_minimap"
            for r in rt if isinstance(r, dict)
        )
    # Also accept trkCalSlim with a valid roi as indicator
    if not has_track_roi:
        trk = ocr.get("trkCalSlim") or {}
        roi = trk.get("roi") if isinstance(trk, dict) else None
        if isinstance(roi, (list, tuple)) and len(roi) >= 4:
            try:
                has_track_roi = float(roi[2]) > 0 and float(roi[3]) > 0
            except Exception:
                pass
    if not has_track_roi:
        return False

    # A partial run was saved (watchdog interrupted mid-video) → resume needed
    if isinstance(ocr.get("track_rerun_partial"), dict):
        return True

    # Check if track detection produced any results
    for key in ("cleaned", "table"):
        tbl = ocr.get(key)
        if not isinstance(tbl, dict) or not tbl.get("time_s"):
            continue
        tmf = tbl.get("track_minimap_found")
        if not isinstance(tmf, list) or not tmf:
            return True
        non_zero = sum(
            1 for v in tmf
            if v not in (0, 0.0, "", None) and not (isinstance(v, float) and math.isnan(v))
        )
        if non_zero == 0:
            return True
        return False

    return True


# ── combined retrofix ─────────────────────────────────────────────────────────

def retrofix_result_json(
    json_path: str,
    catalog: dict,
    do_trim: bool = True,
    do_filter: bool = True,
) -> tuple[bool, str, bool]:
    """
    Combined retroactive correction:
      1. Trim rows outside ocr.params.start_s / end_s (if do_trim)
      2. Apply plausibility + slope filter (if do_filter)

    Returns (changed, message, needs_track_rerun).
    Track re-run detection is always performed and reported in the third return value.
    """
    import json as _json
    import copy
    from pathlib import Path

    path = Path(json_path)
    try:
        doc = _json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception as e:
        return False, f"Lesen fehlgeschlagen: {e}", False

    rr = doc.get("recordResult") if isinstance(doc, dict) else None
    if not isinstance(rr, dict):
        return False, "kein recordResult", False
    ocr = rr.get("ocr")
    if not isinstance(ocr, dict):
        return False, "kein ocr", False

    track_needed = needs_track_rerun(doc)
    changed = False
    msgs: list[str] = []

    # ── 1. Time-bounds trimming ───────────────────────────────────────────────
    if do_trim:
        params = ocr.get("params") or {}
        start_s = float(params.get("start_s") or 0.0)
        end_s_raw = params.get("end_s")
        end_s = float(end_s_raw) if end_s_raw is not None and float(end_s_raw) > 0 else None

        if start_s > 0.0 or end_s is not None:
            for key in ("table", "cleaned"):
                tbl = ocr.get(key)
                if isinstance(tbl, dict) and tbl.get("time_s"):
                    trimmed, n_rm = _trim_tbl(tbl, start_s, end_s)
                    if n_rm > 0:
                        ocr[key] = trimmed
                        changed = True
                        msgs.append(f"trim {key}: -{n_rm} Zeilen")

    # ── 2. Plausibility + slope filter ───────────────────────────────────────
    if do_filter and catalog.get("plausibility"):
        for key in ("table", "cleaned"):
            tbl = ocr.get(key)
            if isinstance(tbl, dict) and tbl.get("time_s"):
                src = copy.deepcopy(tbl)
                filter_cols(src, catalog)
                ocr[key] = src
                changed = True
                msgs.append(f"filter {key}")

    if not changed:
        return False, "keine Änderungen", track_needed

    try:
        _atomic_write(path, doc)
    except Exception as e:
        return False, f"Schreiben fehlgeschlagen: {e}", track_needed

    return True, f"{path.name}: {', '.join(msgs)}", track_needed


def reclean_result_json(json_path: str, catalog: dict) -> tuple[bool, str]:
    """
    Re-apply plausibility + slope filter to a result JSON's cleaned table.
    Source: ocr.cleaned (preferred) or ocr.table. Result written to ocr.cleaned.
    """
    import json as _json
    import copy
    from pathlib import Path

    path = Path(json_path)
    try:
        doc = _json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception as e:
        return False, f"Lesen fehlgeschlagen: {e}"

    rr = doc.get("recordResult") if isinstance(doc, dict) else None
    if not isinstance(rr, dict):
        return False, "kein recordResult"
    ocr = rr.get("ocr")
    if not isinstance(ocr, dict):
        return False, "kein ocr"

    src = None
    for key in ("cleaned", "table"):
        tbl = ocr.get(key)
        if isinstance(tbl, dict) and tbl.get("time_s"):
            src = tbl
            break
    if src is None:
        return False, "keine Tabelle"

    cleaned = copy.deepcopy(src)
    filter_cols(cleaned, catalog)
    ocr["cleaned"] = cleaned

    try:
        _atomic_write(path, doc)
    except Exception as e:
        return False, f"Schreiben fehlgeschlagen: {e}"

    return True, path.name
