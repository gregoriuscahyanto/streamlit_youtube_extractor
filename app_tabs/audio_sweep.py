"""Audio parameter sweep - find the best RPM-extraction parameters against a reference."""
from __future__ import annotations
import math
import threading
from pathlib import Path
from typing import Callable


def _extract_t_rpm(ret):
    """Accept legacy tuple return and newer dict return from extractor."""
    if isinstance(ret, dict):
        t_audio = ret.get("t")
        rpm_audio = ret.get("rpm")
        if t_audio is None or rpm_audio is None:
            raise ValueError("extractor-dict ohne 't'/'rpm'")
        return t_audio, rpm_audio, ret
    if isinstance(ret, (list, tuple)):
        if len(ret) < 2:
            raise ValueError("extractor-tuple zu kurz")
        t_audio = ret[0]
        rpm_audio = ret[1]
        extra = ret[2] if len(ret) >= 3 else {}
        return t_audio, rpm_audio, extra
    raise TypeError(f"Unerwarteter Extractor-Rueckgabewert: {type(ret).__name__}")

# ── Physical plausibility check ───────────────────────────────────────────────

def _fundamental_hz(rpm_val: float, cyl: int, order: float, takt: int) -> float:
    """Fundamental firing frequency in Hz."""
    return rpm_val * cyl * order / (takt * 60.0)


def _combo_plausible(cyl: int, order: float, takt: int, fmax: float,
                     rpm_min: float, rpm_max: float) -> bool:
    """Return False if this combination cannot produce detectable signal within fmax."""
    f_lo = _fundamental_hz(rpm_min, cyl, order, takt)
    f_hi = _fundamental_hz(rpm_max, cyl, order, takt)
    if f_hi < 20.0:      # below audio range
        return False
    if f_lo > fmax:      # fundamental above fmax → nothing visible
        return False
    return True


# ── Gear-band computation ─────────────────────────────────────────────────────

def compute_gear_bands(
    t_target,
    t_ocr,
    v_kmph_ocr,
    gear_ratios: list,
    axle_ratio: float,
    r_dyn: float,
    rpm_min: float,
    rpm_max: float,
    band_tol_pct: float = 5.0,
):
    """
    Expected RPM band for each gear at each point in *t_target*.

    Returns ndarray shape (len(t_target), n_gears, 2) — [rpm_lo, rpm_hi] per gear.
    Points where v ≤ 0.5 km/h, outside OCR range, or NaN → [0, 0] (skip in scoring).

    Formula: RPM_i = v_kmph/3.6 / (2π·r_dyn) · axle_ratio · gear_ratio_i · 60
    """
    import numpy as np

    t_tgt = np.asarray(t_target, dtype=float).ravel()
    t_o   = np.asarray(t_ocr,    dtype=float).ravel()
    v_o   = np.asarray(v_kmph_ocr, dtype=float).ravel()
    n      = len(t_tgt)
    n_gears = len(gear_ratios)
    bands  = np.zeros((n, n_gears, 2), dtype=float)

    if n == 0 or n_gears == 0 or t_o.size < 2:
        return bands

    # Interpolate; points outside OCR time range → 0
    v_interp = np.interp(t_tgt, t_o, v_o)
    in_range = (t_tgt >= t_o[0]) & (t_tgt <= t_o[-1])
    v_interp = np.where(in_range & np.isfinite(v_interp), v_interp, 0.0)

    valid     = v_interp > 0.5
    tol_frac  = band_tol_pct / 100.0
    denom     = 2.0 * math.pi * max(r_dyn, 0.001)

    for i, g_ratio in enumerate(gear_ratios):
        rpm_c  = (v_interp / 3.6) / denom * axle_ratio * g_ratio * 60.0
        rpm_lo = np.clip(rpm_c * (1.0 - tol_frac), rpm_min, rpm_max)
        rpm_hi = np.clip(rpm_c * (1.0 + tol_frac), rpm_min, rpm_max)
        bands[:, i, 0] = np.where(valid, rpm_lo, 0.0)
        bands[:, i, 1] = np.where(valid, rpm_hi, 0.0)

    return bands


def gear_band_reference_diagnostics(
    t_ref,
    rpm_ref,
    gear_band_cfg: dict | None,
    tolerances: list[float] | tuple[float, ...] = (5.0, 10.0, 15.0, 20.0),
    scale_lo: float = 0.75,
    scale_hi: float = 1.35,
    n_scale: int = 121,
) -> dict:
    """Check how well a reference RPM trace fits speed-derived gear bands."""
    import numpy as np

    out = {
        "ok": False,
        "ref_band_pct_by_tol": {},
        "recommended_tol_pct": None,
        "best_scale": 1.0,
        "best_scale_pct": 0.0,
    }
    if not isinstance(gear_band_cfg, dict) or not gear_band_cfg.get("gear_ratios"):
        out["error"] = "missing gear_band_cfg"
        return out

    t = np.asarray(t_ref, dtype=float).ravel()
    r = np.asarray(rpm_ref, dtype=float).ravel()
    n = min(t.size, r.size)
    if n < 4:
        out["error"] = "too few reference points"
        return out
    t = t[:n]
    r = r[:n]
    ref_valid = np.isfinite(t) & np.isfinite(r)
    if int(ref_valid.sum()) < 4:
        out["error"] = "too few finite reference points"
        return out

    def _pct_for(cfg: dict, tol: float) -> tuple[float, int]:
        local = dict(cfg)
        local["band_tol_pct"] = float(tol)
        bands = compute_gear_bands(
            t,
            local["t_ocr"],
            local["v_kmph_ocr"],
            local["gear_ratios"],
            float(local.get("axle_ratio", 3.15)),
            float(local.get("r_dyn", 0.35)),
            float(local.get("rpm_min", 500.0)),
            float(local.get("rpm_max", 8000.0)),
            float(local.get("band_tol_pct", 5.0)),
        )
        valid = ref_valid & (bands[:, :, 1] > 0).any(axis=1)
        if not valid.any():
            return 0.0, 0
        inside = (
            (r[:, None] >= bands[:, :, 0])
            & (r[:, None] <= bands[:, :, 1])
            & (bands[:, :, 1] > 0)
        ).any(axis=1)
        return float(inside[valid].mean() * 100.0), int(valid.sum())

    tol_values = [float(x) for x in tolerances if float(x) > 0]
    by_tol = {}
    valid_n = 0
    for tol in tol_values:
        pct, valid_n = _pct_for(gear_band_cfg, tol)
        by_tol[str(float(tol))] = round(pct, 2)
    out["ref_band_pct_by_tol"] = by_tol
    out["valid_points"] = int(valid_n)

    recommended = None
    for tol in tol_values:
        if by_tol.get(str(float(tol)), 0.0) >= 75.0:
            recommended = float(tol)
            break
    out["recommended_tol_pct"] = recommended if recommended is not None else (float(tol_values[-1]) if tol_values else None)

    base_gears = [float(g) for g in gear_band_cfg.get("gear_ratios") or []]
    cur_tol = float(gear_band_cfg.get("band_tol_pct", tol_values[0] if tol_values else 5.0))
    scale_values = np.linspace(float(scale_lo), float(scale_hi), int(n_scale))
    best_scale = 1.0
    best_pct = -1.0
    for scale in scale_values:
        cfg = dict(gear_band_cfg)
        cfg["gear_ratios"] = [g * float(scale) for g in base_gears]
        pct, _valid = _pct_for(cfg, cur_tol)
        if pct > best_pct:
            best_pct = pct
            best_scale = float(scale)
    out.update({
        "ok": True,
        "best_scale": round(float(best_scale), 4),
        "best_scale_pct": round(float(best_pct), 2),
        "best_within_pct": round(float(best_pct), 2),
    })
    return out


# ── Reference file parsing ────────────────────────────────────────────────────

def parse_ref_file(data: bytes, filename: str) -> dict:
    """
    Parse reference file (Excel / CSV / MAT) to a DataFrame.
    Returns {"df": pd.DataFrame, "error": str|None}.
    """
    import io
    try:
        import pandas as pd
        name_lower = filename.lower()
        if name_lower.endswith((".xlsx", ".xls")):
            df = pd.read_excel(io.BytesIO(data), engine="openpyxl" if name_lower.endswith(".xlsx") else None)
        elif name_lower.endswith(".csv"):
            for sep in (",", ";", "\t"):
                try:
                    df = pd.read_csv(io.BytesIO(data), sep=sep)
                    if len(df.columns) >= 2:
                        break
                except Exception:
                    continue
        elif name_lower.endswith(".mat"):
            from core.audio_validation import dataframe_from_upload  # type: ignore
            df = dataframe_from_upload(data, filename)
        else:
            return {"df": None, "error": f"Unbekanntes Format: {filename}"}
        return {"df": df, "error": None}
    except Exception as e:
        return {"df": None, "error": str(e)}


def embed_ref_in_doc(doc: dict, t_ref, rpm_ref, source_file: str,
                     time_col: str, rpm_col: str) -> dict:
    """Store reference data inside the result JSON (portable, no path dependency)."""
    import numpy as np
    from datetime import datetime
    rr = doc.get("recordResult")
    if not isinstance(rr, dict):
        rr = {}
        doc["recordResult"] = rr
    rr["audio_ref"] = {
        "source_file": source_file,
        "time_col": time_col,
        "rpm_col": rpm_col,
        "linked_at": datetime.now().isoformat(timespec="seconds"),
        "t_s": [float(v) for v in np.asarray(t_ref).ravel() if math.isfinite(float(v))],
        "rpm": [float(v) for v in np.asarray(rpm_ref).ravel() if math.isfinite(float(v))],
    }
    return doc


def load_ref_from_doc(doc: dict) -> dict | None:
    """
    Load embedded reference data from result JSON.
    Returns {"t_s": array, "rpm": array, "source_file": str} or None.
    """
    import numpy as np
    rr = doc.get("recordResult") if isinstance(doc, dict) else {}
    ref = (rr or {}).get("audio_ref")
    if not isinstance(ref, dict):
        return None
    t = ref.get("t_s")
    r = ref.get("rpm")
    if not t or not r or len(t) != len(r):
        return None
    return {
        "t_s": np.asarray(t, dtype=float),
        "rpm": np.asarray(r, dtype=float),
        "source_file": str(ref.get("source_file") or ""),
        "linked_at": str(ref.get("linked_at") or ""),
        "time_col": str(ref.get("time_col") or ""),
        "rpm_col": str(ref.get("rpm_col") or ""),
    }


# ── Cross-correlation offset search ───────────────────────────────────────────

def cross_corr_offset(t_audio, rpm_audio, t_ref, rpm_ref,
                      search_lo: float = -10.0, search_hi: float = 10.0,
                      step: float = 0.25) -> float:
    """
    Find the audio_offset_s that maximises Pearson r between rpm_audio and rpm_ref
    (after resampling to a common time grid).
    Returns best_offset_s.
    """
    import numpy as np
    t_a = np.asarray(t_audio, dtype=float).ravel()
    r_a = np.asarray(rpm_audio, dtype=float).ravel()
    t_r = np.asarray(t_ref, dtype=float).ravel()
    r_r = np.asarray(rpm_ref, dtype=float).ravel()

    if t_a.size < 4 or t_r.size < 4:
        return 0.0

    best_offset = 0.0
    best_corr = -2.0

    offsets = np.arange(search_lo, search_hi + step * 0.5, step)
    for off in offsets:
        t_r_shifted = t_r + off
        # Interpolate rpm_ref onto audio time grid
        t_lo = max(t_a[0], t_r_shifted[0])
        t_hi = min(t_a[-1], t_r_shifted[-1])
        if t_hi - t_lo < 0.5:
            continue
        t_common = np.linspace(t_lo, t_hi, min(2000, int((t_hi - t_lo) * 10)))
        try:
            r_a_interp = np.interp(t_common, t_a, r_a)
            r_r_interp = np.interp(t_common, t_r_shifted, r_r)
        except Exception:
            continue
        std_a = float(np.std(r_a_interp))
        std_r = float(np.std(r_r_interp))
        if std_a < 1e-6 or std_r < 1e-6:
            continue
        corr = float(np.corrcoef(r_a_interp, r_r_interp)[0, 1])
        if math.isfinite(corr) and corr > best_corr:
            best_corr = corr
            best_offset = float(off)

    return best_offset


# ── Agreement scoring ──────────────────────────────────────────────────────────

def score_agreement(t_audio, rpm_audio, t_ref, rpm_ref,
                    offset_s: float,
                    tol_abs_rpm: float | None,
                    tol_pct: float | None,
                    tol_logic: str = "ODER",
                    gear_band_cfg: dict | None = None,
                    band_weight: float = 8.0) -> dict:
    """
    Compute agreement between rpm_audio and rpm_ref (shifted by offset_s).
    Returns dict with within_pct, rmse, mae, n, pearson_r, band_compliance_pct,
    jump_in_band_pct.

    gear_band_cfg (optional): used both for optional extractor guidance and
        for post-score band compliance reporting.
    """
    import numpy as np

    t_a = np.asarray(t_audio, dtype=float).ravel()
    r_a = np.asarray(rpm_audio, dtype=float).ravel()
    t_r = np.asarray(t_ref, dtype=float).ravel() + offset_s
    r_r = np.asarray(rpm_ref, dtype=float).ravel()

    if t_a.size < 2 or t_r.size < 2:
        return {"ok": False, "error": "zu wenig Datenpunkte"}

    t_lo = max(t_a[0], t_r[0])
    t_hi = min(t_a[-1], t_r[-1])
    if t_hi - t_lo < 0.1:
        return {"ok": False, "error": "keine Überlappung"}

    n_pts = min(4000, max(100, int((t_hi - t_lo) * 10)))
    t_common = np.linspace(t_lo, t_hi, n_pts)
    r_a_i = np.interp(t_common, t_a, r_a)
    r_r_i = np.interp(t_common, t_r, r_r)
    finite = np.isfinite(r_a_i) & np.isfinite(r_r_i)
    if int(finite.sum()) < 4:
        return {"ok": False, "error": "zu wenig gueltige Vergleichspunkte"}
    t_common = t_common[finite]
    r_a_i = r_a_i[finite]
    r_r_i = r_r_i[finite]
    n_pts = int(r_a_i.size)

    err = r_a_i - r_r_i
    abs_err = np.abs(err)
    rmse = float(np.sqrt(np.mean(err ** 2)))
    mae = float(np.mean(abs_err))

    # Tolerance
    checks = []
    if tol_abs_rpm is not None and tol_abs_rpm > 0:
        checks.append(abs_err <= tol_abs_rpm)
    if tol_pct is not None and tol_pct > 0:
        checks.append((abs_err / np.maximum(np.abs(r_r_i), 1.0)) * 100.0 <= tol_pct)
    if not checks:
        within = np.ones(n_pts, dtype=bool)
    elif len(checks) == 1:
        within = checks[0]
    elif str(tol_logic).upper() == "UND":
        within = np.logical_and.reduce(checks)
    else:
        within = np.logical_or.reduce(checks)

    dt = float(max(t_common[-1] - t_common[0], 1e-9)) if n_pts > 1 else 1.0
    diff_a = np.abs(np.diff(r_a_i)) if n_pts > 1 else np.array([], dtype=float)
    diff_r = np.abs(np.diff(r_r_i)) if n_pts > 1 else np.array([], dtype=float)
    roughness_rpm = float(np.nanmedian(diff_a)) if diff_a.size else 0.0
    ref_roughness_rpm = float(np.nanmedian(diff_r)) if diff_r.size else 0.0
    excess_roughness_rpm = max(0.0, roughness_rpm - max(120.0, 2.5 * ref_roughness_rpm))
    jump_thr = 250.0
    if tol_abs_rpm is not None and tol_abs_rpm > 0:
        jump_thr = max(jump_thr, float(tol_abs_rpm))
    if tol_pct is not None and tol_pct > 0:
        jump_thr = max(jump_thr, float(np.nanmedian(np.abs(r_r_i))) * float(tol_pct) / 100.0)
    jump_rate_per_min = float(np.count_nonzero(diff_a > jump_thr) / max(dt / 60.0, 1e-9)) if diff_a.size else 0.0

    within_pct = float(np.mean(within) * 100.0)

    # Pearson r
    try:
        pearson_r = float(np.corrcoef(r_a_i, r_r_i)[0, 1])
        if not math.isfinite(pearson_r):
            pearson_r = 0.0
    except Exception:
        pearson_r = 0.0

    # ── Optional gear-band scoring ─────────────────────────────────────────────
    band_compliance_pct = 0.0
    jump_in_band_pct    = 0.0
    if gear_band_cfg is not None and len(gear_band_cfg.get("gear_ratios") or []) > 0:
        try:
            _gb = compute_gear_bands(
                t_common,
                gear_band_cfg["t_ocr"],
                gear_band_cfg["v_kmph_ocr"],
                gear_band_cfg["gear_ratios"],
                float(gear_band_cfg.get("axle_ratio", 3.15)),
                float(gear_band_cfg.get("r_dyn", 0.35)),
                float(gear_band_cfg.get("rpm_min", 500.0)),
                float(gear_band_cfg.get("rpm_max", 8000.0)),
                float(gear_band_cfg.get("band_tol_pct", 5.0)),
            )
            _valid = (_gb[:, :, 1] > 0).any(axis=1)
            if _valid.any():
                _in_any = (
                    (r_a_i[:, None] >= _gb[:, :, 0]) &
                    (r_a_i[:, None] <= _gb[:, :, 1])
                ).any(axis=1)
                band_compliance_pct = float(_in_any[_valid].mean() * 100.0)

            _jump_thr = tol_abs_rpm if tol_abs_rpm and tol_abs_rpm > 0 else 200.0
            _ji = np.where(np.abs(np.diff(r_a_i)) > _jump_thr)[0]
            if len(_ji) > 0:
                _lo, _hi = _gb[:, :, 0], _gb[:, :, 1]
                _ib = (_lo[_ji] > 0) & (r_a_i[_ji, None] >= _lo[_ji]) & (r_a_i[_ji, None] <= _hi[_ji])
                _ia = (_lo[_ji + 1] > 0) & (r_a_i[_ji + 1, None] >= _lo[_ji + 1]) & (r_a_i[_ji + 1, None] <= _hi[_ji + 1])
                _bi = np.where(_ib.any(axis=1), _ib.argmax(axis=1), -1)
                _ai = np.where(_ia.any(axis=1), _ia.argmax(axis=1), -1)
                _both = (_bi >= 0) & (_ai >= 0)
                if _both.any():
                    jump_in_band_pct = float((_bi[_both] != _ai[_both]).mean() * 100.0)
            elif _valid.any():
                jump_in_band_pct = 100.0

        except Exception:
            pass

    band_bonus = band_compliance_pct * max(0.0, float(band_weight)) / 100.0
    smooth_penalty = 0.018 * excess_roughness_rpm + 0.08 * jump_rate_per_min
    combined = (
        within_pct * 1.25
        + max(0.0, pearson_r) * 15.0
        + band_bonus
        + jump_in_band_pct * 0.03
        - 0.006 * mae
        - 0.004 * rmse
        - smooth_penalty
    )

    return {
        "ok": True,
        "within_pct": round(within_pct, 2),
        "rmse": round(rmse, 1),
        "mae": round(mae, 1),
        "pearson_r": round(pearson_r, 4),
        "combined_score": round(combined, 3),
        "band_compliance_pct": round(band_compliance_pct, 1),
        "jump_in_band_pct":    round(jump_in_band_pct, 1),
        "roughness_rpm": round(roughness_rpm, 1),
        "excess_roughness_rpm": round(excess_roughness_rpm, 1),
        "jump_rate_per_min": round(jump_rate_per_min, 2),
        "n_pts": n_pts,
        "offset_s": round(offset_s, 4),
    }


def constrain_rpm_to_gear_bands(t_audio, rpm_audio, gear_band_cfg: dict | None):
    """Clamp extracted RPM to speed-derived per-time gear bands, with optional mode-filter smoothing."""
    import numpy as np

    r = np.asarray(rpm_audio, dtype=float).ravel().copy()
    t = np.asarray(t_audio, dtype=float).ravel()
    meta = {"gear_band_constraint": False, "limited_points": 0, "valid_band_points": 0}
    if gear_band_cfg is None or t.size == 0 or r.size == 0 or len(gear_band_cfg.get("gear_ratios") or []) <= 0:
        return r, meta
    mode = str(gear_band_cfg.get("mode", "clamp") or "clamp").strip().lower()
    if mode not in ("hard", "clamp", "guide_and_clamp", "clamp_and_guide"):
        return r, meta
    n = min(t.size, r.size)
    r = r[:n]
    band_smooth_n = int(gear_band_cfg.get("band_smooth_n", 5))
    try:
        bands = compute_gear_bands(
            t[:n],
            gear_band_cfg["t_ocr"],
            gear_band_cfg["v_kmph_ocr"],
            gear_band_cfg["gear_ratios"],
            float(gear_band_cfg.get("axle_ratio", 3.15)),
            float(gear_band_cfg.get("r_dyn", 0.35)),
            float(gear_band_cfg.get("rpm_min", 500.0)),
            float(gear_band_cfg.get("rpm_max", 8000.0)),
            float(gear_band_cfg.get("band_tol_pct", 5.0)),
        )
        valid = (bands[:, :, 1] > 0).any(axis=1)
        limited = 0
        # Step 1: per-point clamp + track band assignment
        band_asgn = np.full(n, -1, dtype=np.int32)
        valid_rpm = valid & np.isfinite(r)
        if bool(gear_band_cfg.get("use_gear_path_viterbi", True)):
            band_asgn = _viterbi_gear_path(
                r,
                bands,
                gear_shift_penalty=float(gear_band_cfg.get("gear_shift_penalty", 0.35) or 0.35),
                higher_gear_bias=float(gear_band_cfg.get("higher_gear_bias", 0.08) or 0.08),
                band_center_weight=float(gear_band_cfg.get("band_center_weight", 0.65) or 0.65),
            )
            for i in np.where(valid_rpm & (band_asgn >= 0))[0]:
                b = int(band_asgn[i])
                lo_b, hi_b = bands[i, b, 0], bands[i, b, 1]
                if hi_b <= 0:
                    continue
                old = r[i]
                r[i] = float(np.clip(r[i], lo_b, hi_b))
                if r[i] != old:
                    limited += 1
        else:
            for i in np.where(valid_rpm)[0]:
                lo = bands[i, :, 0]
                hi = bands[i, :, 1]
                ok = hi > 0
                if not ok.any():
                    continue
                in_band = (r[i] >= lo) & (r[i] <= hi) & ok
                if in_band.any():
                    band_asgn[i] = int(in_band.argmax())
                    continue
                ok_idx = np.where(ok)[0]
                lo_ok, hi_ok = lo[ok], hi[ok]
                bounds = np.concatenate([lo_ok, hi_ok])
                best_b = int(np.argmin(np.abs(bounds - r[i])))
                nearest = float(bounds[best_b])
                r[i] = nearest
                limited += 1
                # assign to the band whose boundary was nearest
                b_idx = best_b if best_b < len(ok_idx) else best_b - len(ok_idx)
                band_asgn[i] = int(ok_idx[min(b_idx, len(ok_idx) - 1)])

        # Step 2: mode-filter on band assignments to suppress rapid band-hopping
        if band_smooth_n >= 2:
            hw = max(1, band_smooth_n // 2)
            smoothed = band_asgn.copy()
            for i in np.where(valid_rpm)[0]:
                window = band_asgn[max(0, i - hw): i + hw + 1]
                assigned = window[window >= 0]
                if assigned.size == 0:
                    continue
                smoothed[i] = int(np.bincount(assigned).argmax())
            # Step 3: re-clamp to smoothed band where assignment changed
            changed = valid_rpm & (smoothed != band_asgn) & (smoothed >= 0)
            for i in np.where(changed)[0]:
                b = smoothed[i]
                lo_b, hi_b = bands[i, b, 0], bands[i, b, 1]
                if hi_b <= 0:
                    continue
                r[i] = float(np.clip(r[i], lo_b, hi_b))
            band_asgn = smoothed

        snap_to_center = bool(gear_band_cfg.get("snap_to_band_center", mode == "hard"))
        center_blend = float(gear_band_cfg.get("center_blend", 1.0 if mode == "hard" else 0.0) or 0.0)
        center_blend = float(np.clip(center_blend, 0.0, 1.0))
        if snap_to_center and center_blend > 0.0:
            use_idx = np.where(valid_rpm & (band_asgn >= 0))[0]
            for i in use_idx:
                b = int(band_asgn[i])
                lo_b, hi_b = bands[i, b, 0], bands[i, b, 1]
                if hi_b <= 0:
                    continue
                center_b = 0.5 * (lo_b + hi_b)
                r[i] = float((1.0 - center_blend) * r[i] + center_blend * center_b)

        meta = {
            "gear_band_constraint": True,
            "limited_points": int(limited),
            "valid_band_points": int(valid.sum()),
            "snap_to_band_center": bool(snap_to_center),
            "center_blend": float(center_blend),
        }
    except Exception as exc:
        meta["gear_band_constraint_error"] = str(exc)
    return r, meta


def _viterbi_gear_path(rpm, bands, gear_shift_penalty: float = 0.35, higher_gear_bias: float = 0.08, band_center_weight: float = 0.65):
    """Find a smooth gear path for one RPM line through speed-derived bands."""
    import numpy as np

    r = np.asarray(rpm, dtype=float).ravel()
    b = np.asarray(bands, dtype=float)
    n = min(r.size, b.shape[0] if b.ndim == 3 else 0)
    if n <= 0 or b.ndim != 3 or b.shape[1] <= 0:
        return np.full(max(n, 0), -1, dtype=np.int32)
    g_n = int(b.shape[1])
    cost = np.full((n, g_n), 1e9, dtype=float)
    prev = np.full((n, g_n), -1, dtype=np.int32)
    gear_rank = np.linspace(0.0, 1.0, g_n) if g_n > 1 else np.zeros(1)
    for i in range(n):
        if not np.isfinite(r[i]):
            cost[i, :] = 1e6
            continue
        lo = b[i, :, 0]
        hi = b[i, :, 1]
        ok = hi > 0
        center = (lo + hi) * 0.5
        half = np.maximum((hi - lo) * 0.5, 1.0)
        center_score = np.clip(1.0 - np.abs(r[i] - center) / half, 0.0, 1.0)
        outside = np.where(r[i] < lo, lo - r[i], np.where(r[i] > hi, r[i] - hi, 0.0))
        local = (outside / half) + band_center_weight * (1.0 - center_score) - higher_gear_bias * gear_rank
        local = np.where(ok, local, 1e6)
        if i == 0:
            cost[i] = local
            continue
        trans = cost[i - 1][:, None] + gear_shift_penalty * np.abs(np.arange(g_n)[:, None] - np.arange(g_n)[None, :])
        best_prev = np.argmin(trans, axis=0)
        cost[i] = local + trans[best_prev, np.arange(g_n)]
        prev[i] = best_prev.astype(np.int32)
    path = np.full(n, -1, dtype=np.int32)
    if n > 0:
        path[-1] = int(np.argmin(cost[-1]))
        for i in range(n - 1, 0, -1):
            path[i - 1] = int(prev[i, path[i]]) if path[i] >= 0 else -1
    return path


# ── Parameter grid ─────────────────────────────────────────────────────────────

# Valid cylinder counts (skip 7, 9, 11, 13, 14, 15 — physically uncommon)
CYL_OPTIONS = ["any", 1, 2, 3, 4, 5, 6, 8, 10, 12, 16]
CYL_SWEEP_VALUES = [3, 4, 5, 6, 8, 10, 12]  # used when cyl="any"
TAKT_OPTIONS = ["any", 2, 4]
TAKT_SWEEP_VALUES = [2, 4]  # used when takt="any"

METHOD_OPTIONS = [
    "STFT/Ridge", "Viterbi", "Peak", "Autokorrelation/YIN",
    "Cepstrum", "Harmonic Comb/HPS", "CWT/Wavelet", "Hybrid",
    "pYIN", "CQT/Constant-Q", "Harmonische Summe", "Bandpass/Autokorr",
]


def build_param_grid(cfg: dict) -> list[dict]:
    """
    Build full parameter grid from sweep config dict.

    fmax is computed automatically per (cyl, takt, order, rpm_max) combination:
        fmax = f_fundamental_max * fmax_headroom
    where f_fundamental_max = rpm_max * cyl * order / (takt * 60).
    fmax_headroom defaults to 1.5 (50% headroom above the highest fundamental).

    cfg keys (all optional, defaults used if missing):
      sweep_method: bool
      nfft_values: list[int]
      overlap_values: list[float]  (percent 0-100)
      fmax_headroom: float          (multiplier above f_fundamental_max, default 1.5)
      order_values: list[float]
      cyl: int|"any"
      takt: int|"any"
      rpm_min: float
      rpm_max: float
      sweep_ridge, sweep_viterbi, sweep_comb, sweep_hybrid: bool
      ridge_smooth_values, ridge_jump_frac_values,
      viterbi_jump_hz_values, viterbi_penalty_values, viterbi_smooth_values,
      comb_harmonics_values, hybrid_smooth_values: list
    """
    methods = METHOD_OPTIONS if cfg.get("sweep_method", True) else [cfg.get("method", "Hybrid")]
    nffts   = cfg.get("nfft_values")    or [1024, 2048, 4096]
    overlaps = cfg.get("overlap_values") or [75.0]
    orders  = cfg.get("order_values")   or [1.0]
    fmax_headroom = float(cfg.get("fmax_headroom") or 1.5)

    cyl_raw  = cfg.get("cyl", "any")
    cyls     = CYL_SWEEP_VALUES if cyl_raw == "any" else [int(cyl_raw)]
    takt_raw = cfg.get("takt", "any")
    takts    = TAKT_SWEEP_VALUES if takt_raw == "any" else [int(takt_raw)]

    rpm_min = float(cfg.get("rpm_min") or 500.0)
    rpm_max = float(cfg.get("rpm_max") or 8000.0)

    # Method-specific param options
    ridge_smooths   = cfg.get("ridge_smooth_values",    [7])    if cfg.get("sweep_ridge")   else [7]
    ridge_jumps     = cfg.get("ridge_jump_frac_values",  [0.08]) if cfg.get("sweep_ridge")   else [0.08]
    viterbi_jumps   = cfg.get("viterbi_jump_hz_values",  [25.0]) if cfg.get("sweep_viterbi") else [25.0]
    viterbi_pens    = cfg.get("viterbi_penalty_values",  [1.2])  if cfg.get("sweep_viterbi") else [1.2]
    viterbi_smooths = cfg.get("viterbi_smooth_values",   [5])    if cfg.get("sweep_viterbi") else [5]
    comb_hs         = cfg.get("comb_harmonics_values",   [4])    if cfg.get("sweep_comb")    else [4]
    hybrid_smooths  = cfg.get("hybrid_smooth_values",    [9])    if cfg.get("sweep_hybrid")  else [9]

    grid: list[dict] = []
    for method in methods:
        for nfft in nffts:
            for overlap in overlaps:
                for cyl in cyls:
                    for takt in takts:
                        for order in orders:
                            # fmax: max of (headroom × fundamental) and (3 harmonics), min 30 Hz
                            f_fund_max = _fundamental_hz(rpm_max, cyl, order, takt)
                            if f_fund_max < 10.0:
                                continue  # below audio range
                            fmax = min(max(f_fund_max * fmax_headroom, f_fund_max * 3.0, 30.0), 5000.0)
                            # round to nearest 10 Hz for cleaner STFT bins
                            fmax = round(fmax / 10) * 10

                            # Method-specific param sweep
                            r_smooths = ridge_smooths   if "Ridge"   in method or "Hybrid" in method else [7]
                            r_jumps   = ridge_jumps     if "Ridge"   in method or "Hybrid" in method else [0.08]
                            v_jumps   = viterbi_jumps   if "Viterbi" in method or "Hybrid" in method else [25.0]
                            v_pens    = viterbi_pens    if "Viterbi" in method or "Hybrid" in method else [1.2]
                            v_smooths = viterbi_smooths if "Viterbi" in method or "Hybrid" in method else [5]
                            c_hs      = comb_hs         if "Comb" in method or "HPS" in method or "Hybrid" in method else [4]
                            h_smooths = hybrid_smooths  if "Hybrid"  in method else [9]

                            for rs in r_smooths:
                                for rj in r_jumps:
                                    for vj in v_jumps:
                                        for vp in v_pens:
                                            for vs in v_smooths:
                                                for ch in c_hs:
                                                    for hs in h_smooths:
                                                        grid.append({
                                                            "method":           method,
                                                            "nfft":             int(nfft),
                                                            "overlap_pct":      float(overlap),
                                                            "fmax":             float(fmax),
                                                            "cyl":              int(cyl),
                                                            "takt":             int(takt),
                                                            "order":            float(order),
                                                            "rpm_min":          rpm_min,
                                                            "rpm_max":          rpm_max,
                                                            "ridge_smooth":     int(rs),
                                                            "ridge_jump_frac":  float(rj),
                                                            "viterbi_jump_hz":  float(vj),
                                                            "viterbi_penalty":  float(vp),
                                                            "viterbi_smooth":   int(vs),
                                                            "comb_harmonics":   int(ch),
                                                            "hybrid_smooth":    int(hs),
                                                        })
    return grid


# ── Sweep runner ──────────────────────────────────────────────────────────────

def _eval_single_params(
    params: dict,
    y, fs: float,
    start_s: float, end_s: float,
    t_ref, rpm_ref,
    tol_abs_rpm: float | None,
    tol_pct: float | None,
    tol_logic: str,
    offset_base: float,
    offset_range: float,
    offset_step: float,
    extract_rpm_fn: Callable,
    errors_out: list | None = None,
    gear_band_cfg: dict | None = None,
) -> dict:
    """Evaluate one parameter combination. Always returns a result dict (score=0 on failure)."""
    import numpy as np

    def _record_skip(reason: str, detail: str = "") -> None:
        if errors_out is not None:
            errors_out.append({
                "method": params.get("method", ""),
                "nfft":   params.get("nfft", ""),
                "fmax":   params.get("fmax", ""),
                "cyl":    params.get("cyl", ""),
                "takt":   params.get("takt", ""),
                "order":  params.get("order", ""),
                "reason": reason,
                "detail": detail,
            })

    def _failed(reason: str, detail: str = "") -> dict:
        _record_skip(reason, detail)
        return {
            **params,
            "ok": False, "within_pct": 0.0,
            "rmse": float("inf"), "mae": float("inf"),
            "pearson_r": 0.0, "combined_score": 0.0,
            "band_compliance_pct": 0.0, "jump_in_band_pct": 0.0,
            "n_pts": 0, "offset_s": 0.0,
            "score_error": detail or reason,
            "rank": 0,
        }

    try:
        method_params = {
            "ridge_smooth":    params.get("ridge_smooth", 7),
            "ridge_jump_frac": params.get("ridge_jump_frac", 0.08),
            "viterbi_jump_hz": params.get("viterbi_jump_hz", 25.0),
            "viterbi_penalty": params.get("viterbi_penalty", 1.2),
            "viterbi_smooth":  params.get("viterbi_smooth", 5),
            "comb_harmonics":  params.get("comb_harmonics", 4),
            "hybrid_smooth":   params.get("hybrid_smooth", 9),
            "fast_mode": True,
            "max_reference_candidates": 120,
        }
        _ret = extract_rpm_fn(
            y=y, fs=fs, start_s=start_s, end_s=end_s, offset_s=0.0,
            nfft=params["nfft"], overlap_pct=params["overlap_pct"],
            fmax=params["fmax"], cyl=params["cyl"], takt=params["takt"],
            order=params["order"], rpm_min=params["rpm_min"], rpm_max=params["rpm_max"],
            method=params["method"],
            cyl_mode="Fest auswählen", harmonic_mode="Fest auswählen",
            drive_type="Verbrenner/Hybrid", stft_mode="Fest auswählen",
            method_params=method_params,
            gear_band_cfg=gear_band_cfg,
        )
        t_audio, rpm_audio, _extra = _extract_t_rpm(_ret)
        rpm_audio, _gear_limit_meta = constrain_rpm_to_gear_bands(t_audio, rpm_audio, gear_band_cfg)
    except Exception as e:
        return _failed("extraction_error", str(e))

    if t_audio is None or len(t_audio) < 4:
        return _failed("too_few_points", f"n={0 if t_audio is None else len(t_audio)}")

    best_score_dict = None
    last_score_error = ""
    for cand_name, cand_rpm in _reference_aware_candidate_pool(t_audio, rpm_audio, _extra):
        sd = _score_one_rpm_candidate(
            t_audio, cand_rpm, t_ref, rpm_ref,
            offset_base=offset_base,
            offset_range=offset_range,
            offset_step=offset_step,
            tol_abs_rpm=tol_abs_rpm,
            tol_pct=tol_pct,
            tol_logic=tol_logic,
            gear_band_cfg=gear_band_cfg,
            candidate_name=cand_name,
        )
        if not sd.get("ok"):
            last_score_error = sd.get("error", "scoring failed")
            continue
        if best_score_dict is None or sd["combined_score"] > best_score_dict["combined_score"]:
            best_score_dict = sd

    if best_score_dict is None:
        return _failed("no_valid_score", last_score_error)

    return {**params, **_gear_limit_meta, **best_score_dict, "rank": 0}


def _score_one_rpm_candidate(
    t_audio,
    rpm_candidate,
    t_ref,
    rpm_ref,
    offset_base: float,
    offset_range: float,
    offset_step: float,
    tol_abs_rpm: float | None,
    tol_pct: float | None,
    tol_logic: str,
    gear_band_cfg: dict | None,
    candidate_name: str,
) -> dict:
    """Score one candidate RPM line against the reference and return its best offset."""
    import numpy as np

    score_gear_band_cfg = _gear_band_cfg_for_candidate(gear_band_cfg, candidate_name)
    rpm_eval, gear_meta = constrain_rpm_to_gear_bands(t_audio, rpm_candidate, score_gear_band_cfg)
    if offset_range > 0:
        _coarse_step = max(offset_step, 0.5)
        best_off = cross_corr_offset(
            t_audio, rpm_eval, t_ref, rpm_ref,
            search_lo=offset_base - offset_range,
            search_hi=offset_base + offset_range,
            step=_coarse_step,
        )
        _fine_step = min(0.1, offset_step)
        fine_offsets = np.arange(
            best_off - _coarse_step,
            best_off + _coarse_step + _fine_step * 0.5,
            _fine_step,
        ).tolist()
    else:
        fine_offsets = [offset_base]

    best = None
    for off in fine_offsets:
        sd = score_agreement(
            t_audio, rpm_eval, t_ref, rpm_ref,
            offset_s=off,
            tol_abs_rpm=tol_abs_rpm,
            tol_pct=tol_pct,
            tol_logic=tol_logic,
            gear_band_cfg=score_gear_band_cfg,
        )
        if not sd.get("ok"):
            continue
        sd = {
            **sd,
            **gear_meta,
            **_compact_plot_preview(t_audio, rpm_eval),
            "selected_candidate_line": str(candidate_name),
            "candidate_source_method": str(candidate_name).split(":", 1)[0],
            "reference_guided_candidate": False,
        }
        if best is None or sd["combined_score"] > best["combined_score"]:
            best = sd
    return best or {"ok": False, "error": "candidate scoring failed"}


def _gear_band_cfg_for_candidate(gear_band_cfg: dict | None, candidate_name: str) -> dict | None:
    """Keep ridge candidates inside gear bands without destroying their spectral line."""
    if not isinstance(gear_band_cfg, dict):
        return gear_band_cfg
    name = str(candidate_name)
    if "Gear-Band Ridge" not in name:
        return gear_band_cfg
    cfg = dict(gear_band_cfg)
    cfg["snap_to_band_center"] = False
    cfg["center_blend"] = 0.0
    cfg["candidate_band_policy"] = "ridge_no_center_snap"
    return cfg


def _compact_plot_preview(t_audio, rpm_audio, max_points: int = 2500) -> dict:
    """Store a bounded preview trace so Top-1 plots do not need a slow re-run."""
    import numpy as np

    t = np.asarray(t_audio, dtype=float).ravel()
    r = np.asarray(rpm_audio, dtype=float).ravel()
    n = min(t.size, r.size)
    if n < 2:
        return {"plot_t_s": [], "plot_rpm": []}
    t = t[:n]
    r = r[:n]
    ok = np.isfinite(t) & np.isfinite(r)
    idx = np.where(ok)[0]
    if idx.size > int(max_points):
        idx = idx[np.linspace(0, idx.size - 1, int(max_points)).astype(int)]
    return {
        "plot_t_s": np.round(t[idx], 4).astype(float).tolist(),
        "plot_rpm": np.round(r[idx], 2).astype(float).tolist(),
    }


def _reference_aware_candidate_pool(t_audio, rpm_audio, extra: dict | None) -> list[tuple[str, object]]:
    """Return baseline plus extractor-provided RPM candidate lines."""
    pool: list[tuple[str, object]] = [("Extractor-Auswahl", rpm_audio)]
    rpm_lines = (extra or {}).get("rpm_lines") or {}
    if isinstance(rpm_lines, dict):
        for name, rpm_line in rpm_lines.items():
            pool.append((str(name), rpm_line))
    return pool


def _sort_and_rank(results: list[dict], top_n: int) -> list[dict]:
    results.sort(key=lambda r: (
        -r.get("combined_score", 0),
        r.get("rmse", 1e9) if r.get("rmse") != float("inf") else 1e9,
    ))
    for rank, r in enumerate(results[:top_n], start=1):
        r["rank"] = rank
    return results[:top_n]


def run_sweep(
    y,
    fs: float,
    start_s: float,
    end_s: float,
    t_ref,
    rpm_ref,
    grid: list[dict],
    tol_abs_rpm: float | None,
    tol_pct: float | None,
    tol_logic: str,
    offset_base: float,
    offset_range: float,
    offset_step: float,
    progress_cb: Callable | None,
    stop_event: threading.Event | None,
    extract_rpm_fn: Callable,
    top_n: int = 20,
    errors_out: list | None = None,
    pre_trial_cb: Callable | None = None,
    gear_band_cfg: dict | None = None,
) -> list[dict]:
    """
    Run the parameter sweep.

    For each grid entry:
      1. Extract RPM with given params (no OCR speed — cyl_mode='Fest auswählen',
         harmonic_mode='Fest auswählen', use_ocr_v=False)
      2. Find best offset via cross-corr around offset_base ± offset_range
      3. Score with tolerance metric
    Returns top_n results sorted by combined_score descending.
    """
    import numpy as np

    offset_candidates = np.arange(
        offset_base - offset_range,
        offset_base + offset_range + offset_step * 0.5,
        offset_step,
    ).tolist() if offset_range > 0 else [offset_base]

    results: list[dict] = []
    n_total = len(grid)
    _kw = dict(
        y=y, fs=fs, start_s=start_s, end_s=end_s,
        t_ref=t_ref, rpm_ref=rpm_ref,
        tol_abs_rpm=tol_abs_rpm, tol_pct=tol_pct, tol_logic=tol_logic,
        offset_base=offset_base, offset_range=offset_range, offset_step=offset_step,
        extract_rpm_fn=extract_rpm_fn, errors_out=errors_out,
        gear_band_cfg=gear_band_cfg,
    )
    for i, params in enumerate(grid):
        if stop_event is not None and stop_event.is_set():
            break
        if callable(pre_trial_cb):
            try:
                pre_trial_cb(i, n_total, params)
            except Exception:
                pass
        result = _eval_single_params(params, **_kw)
        results.append(result)
        if callable(progress_cb):
            try:
                progress_cb(i + 1, n_total, params, result)
            except Exception:
                pass
        # Free intermediate arrays every 10 iterations
        if i % 10 == 9:
            import gc as _gc
            _gc.collect()

    return _sort_and_rank(results, top_n)


def run_sweep_random(
    y, fs: float, start_s: float, end_s: float,
    t_ref, rpm_ref,
    cfg: dict,
    tol_abs_rpm: float | None, tol_pct: float | None, tol_logic: str,
    offset_base: float, offset_range: float, offset_step: float,
    progress_cb: Callable | None, stop_event: threading.Event | None,
    extract_rpm_fn: Callable,
    top_n: int = 20, n_trials: int = 200,
    errors_out: list | None = None,
    pre_trial_cb: Callable | None = None,
    gear_band_cfg: dict | None = None,
) -> list[dict]:
    """Random search: shuffle the full grid, evaluate first n_trials entries."""
    import random as _rnd

    methods = cfg.get("methods") or ["Hybrid"]
    full_grid: list[dict] = []
    for m in methods:
        full_grid.extend(build_param_grid({**cfg, "method": m, "sweep_method": False}))

    _rnd.shuffle(full_grid)
    sampled = full_grid[:n_trials]

    return run_sweep(
        y=y, fs=fs, start_s=start_s, end_s=end_s, t_ref=t_ref, rpm_ref=rpm_ref, grid=sampled,
        tol_abs_rpm=tol_abs_rpm, tol_pct=tol_pct, tol_logic=tol_logic,
        offset_base=offset_base, offset_range=offset_range, offset_step=offset_step,
        progress_cb=progress_cb, stop_event=stop_event,
        extract_rpm_fn=extract_rpm_fn, top_n=top_n, errors_out=errors_out,
        pre_trial_cb=pre_trial_cb, gear_band_cfg=gear_band_cfg,
    )


def run_sweep_optuna(
    y, fs: float, start_s: float, end_s: float,
    t_ref, rpm_ref,
    cfg: dict,
    tol_abs_rpm: float | None, tol_pct: float | None, tol_logic: str,
    offset_base: float, offset_range: float, offset_step: float,
    progress_cb: Callable | None, stop_event: threading.Event | None,
    extract_rpm_fn: Callable,
    top_n: int = 20, n_trials: int = 80,
    errors_out: list | None = None,
    pre_trial_cb: Callable | None = None,
    gear_band_cfg: dict | None = None,
) -> list[dict]:
    """Bayesian optimisation with Optuna (TPE sampler)."""
    try:
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)
    except ImportError:
        raise ImportError(
            "optuna nicht installiert. Bitte 'pip install optuna' ausführen."
        )

    methods  = cfg.get("methods")  or ["Hybrid"]
    nffts    = cfg.get("nfft_values")    or [2048]
    overlaps = cfg.get("overlap_values") or [75.0]
    orders   = cfg.get("order_values")   or [1.0]
    cyl_raw  = cfg.get("cyl", "any")
    cyls     = [str(c) for c in (CYL_SWEEP_VALUES if cyl_raw == "any" else [int(cyl_raw)])]
    takt_raw = cfg.get("takt", "any")
    takts    = [str(t) for t in (TAKT_SWEEP_VALUES if takt_raw == "any" else [int(takt_raw)])]
    rpm_min  = float(cfg.get("rpm_min") or 500.0)
    rpm_max  = float(cfg.get("rpm_max") or 8000.0)
    fmax_headroom = float(cfg.get("fmax_headroom") or 1.5)

    results_all: list[dict] = []
    trial_idx   = [0]
    _kw = dict(
        y=y, fs=fs, start_s=start_s, end_s=end_s,
        t_ref=t_ref, rpm_ref=rpm_ref,
        tol_abs_rpm=tol_abs_rpm, tol_pct=tol_pct, tol_logic=tol_logic,
        offset_base=offset_base, offset_range=offset_range, offset_step=offset_step,
        extract_rpm_fn=extract_rpm_fn, errors_out=errors_out,
        gear_band_cfg=gear_band_cfg,
    )

    def objective(trial: "optuna.Trial") -> float:
        if stop_event is not None and stop_event.is_set():
            raise optuna.exceptions.TrialPruned()

        method  = trial.suggest_categorical("method",  methods)
        nfft    = trial.suggest_categorical("nfft",    nffts)
        overlap = trial.suggest_categorical("overlap", overlaps)
        order   = float(trial.suggest_categorical("order", [str(o) for o in orders]))
        cyl     = int(trial.suggest_categorical("cyl",  cyls))
        takt    = int(trial.suggest_categorical("takt", takts))

        f_fund_max = _fundamental_hz(rpm_max, cyl, order, takt)
        if f_fund_max < 10.0:
            raise optuna.exceptions.TrialPruned()
        fmax = round(min(max(f_fund_max * fmax_headroom, f_fund_max * 3.0, 30.0), 5000.0) / 10) * 10

        params = {
            "method": method, "nfft": int(nfft), "overlap_pct": float(overlap),
            "fmax": float(fmax), "cyl": cyl, "takt": takt, "order": order,
            "rpm_min": rpm_min, "rpm_max": rpm_max,
            "ridge_smooth": 7, "ridge_jump_frac": 0.08,
            "viterbi_jump_hz": 25.0, "viterbi_penalty": 1.2, "viterbi_smooth": 5,
            "comb_harmonics": 4, "hybrid_smooth": 9,
        }
        if callable(pre_trial_cb):
            try:
                pre_trial_cb(trial_idx[0], n_trials, params)
            except Exception:
                pass
        result = _eval_single_params(params, **_kw)
        results_all.append(result)

        trial_idx[0] += 1
        if callable(progress_cb):
            try:
                progress_cb(trial_idx[0], n_trials, params, result)
            except Exception:
                pass
        if trial_idx[0] % 10 == 0:
            import gc as _gc
            _gc.collect()

        return float(result.get("combined_score", 0.0))

    study = optuna.create_study(
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=42),
    )
    startup_grid = []
    for _m in methods:
        for _ord in orders:
            startup_grid.append({
                "method": _m,
                "nfft": int(nffts[min(len(nffts) // 2, len(nffts) - 1)]),
                "overlap": float(overlaps[min(len(overlaps) // 2, len(overlaps) - 1)]),
                "order": str(_ord),
                "cyl": str(cyls[0]),
                "takt": str(takts[0]),
            })
    for _params in startup_grid[:max(0, min(len(startup_grid), n_trials // 2))]:
        study.enqueue_trial(_params)
    study.optimize(
        objective, n_trials=n_trials,
        catch=(Exception,),
        callbacks=[
            lambda study, trial: (
                stop_event.is_set() and study.stop()
                if stop_event is not None else None
            )
        ],
    )

    return _sort_and_rank(results_all, top_n)


# ── Persist sweep results ─────────────────────────────────────────────────────

def save_sweep_results(json_path: str, results: list[dict]) -> None:
    """Write top sweep results to recordResult.audio_sweep in the result JSON."""
    import json as _json
    from datetime import datetime
    from app_tabs.plausibility_filter import _atomic_write

    path = Path(json_path)
    try:
        doc = _json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return
    rr = doc.get("recordResult")
    if not isinstance(rr, dict):
        return
    rr["audio_sweep"] = {
        "created": datetime.now().isoformat(timespec="seconds"),
        "n_results": len(results),
        "results": results,
    }
    doc["recordResult"] = rr
    _atomic_write(path, doc)


def load_sweep_results(json_path: str) -> list[dict]:
    """Load previously saved sweep results from a result JSON."""
    import json as _json
    try:
        doc = _json.loads(Path(json_path).read_text(encoding="utf-8", errors="ignore"))
        rr = doc.get("recordResult") or {}
        sweep = rr.get("audio_sweep") or {}
        return list(sweep.get("results") or [])
    except Exception:
        return []
