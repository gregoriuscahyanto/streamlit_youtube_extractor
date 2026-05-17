"""Audio parameter sweep â€” find the best RPM-extraction parameters against a reference."""
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

# â”€â”€ Physical plausibility check â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
    if f_lo > fmax:      # fundamental above fmax â†’ nothing visible
        return False
    return True


# â”€â”€ Reference file parsing â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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


# â”€â”€ Cross-correlation offset search â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
        t_common = np.linspace(t_lo, t_hi, min(500, int((t_hi - t_lo) * 4)))
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


# â”€â”€ Agreement scoring â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def score_agreement(t_audio, rpm_audio, t_ref, rpm_ref,
                    offset_s: float,
                    tol_abs_rpm: float | None,
                    tol_pct: float | None,
                    tol_logic: str = "ODER") -> dict:
    """
    Compute agreement between rpm_audio and rpm_ref (shifted by offset_s).
    Returns dict with within_pct, rmse, mae, n, pearson_r.
    Pure audio-based â€” no OCR speed influence.
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
        return {"ok": False, "error": "keine Ãœberlappung"}

    n_pts = min(2000, max(50, int((t_hi - t_lo) * 4)))
    t_common = np.linspace(t_lo, t_hi, n_pts)
    r_a_i = np.interp(t_common, t_a, r_a)
    r_r_i = np.interp(t_common, t_r, r_r)

    err = r_a_i - r_r_i
    abs_err = np.abs(err)
    rmse = float(np.sqrt(np.mean(err ** 2)))
    mae = float(np.mean(abs_err))

    # Tolerance
    within = np.ones(n_pts, dtype=bool)
    if tol_abs_rpm is not None and tol_abs_rpm > 0:
        abs_ok = abs_err <= tol_abs_rpm
        within = abs_ok if tol_logic == "UND" else within | abs_ok
        if tol_logic == "UND":
            within = within & abs_ok
        else:
            within = abs_ok.copy()
    if tol_pct is not None and tol_pct > 0:
        pct_ok = (abs_err / np.maximum(np.abs(r_r_i), 1.0)) * 100.0 <= tol_pct
        if tol_logic == "UND":
            within = within & pct_ok
        else:
            within = within | pct_ok

    within_pct = float(np.mean(within) * 100.0)

    # Pearson r
    try:
        pearson_r = float(np.corrcoef(r_a_i, r_r_i)[0, 1])
        if not math.isfinite(pearson_r):
            pearson_r = 0.0
    except Exception:
        pearson_r = 0.0

    # Combined score: primary = within_pct, tie-break with pearson_r
    combined = within_pct * 0.7 + max(0.0, pearson_r) * 30.0

    return {
        "ok": True,
        "within_pct": round(within_pct, 2),
        "rmse": round(rmse, 1),
        "mae": round(mae, 1),
        "pearson_r": round(pearson_r, 4),
        "combined_score": round(combined, 3),
        "n_pts": n_pts,
        "offset_s": round(offset_s, 4),
    }


# â”€â”€ Parameter grid â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

# Valid cylinder counts (skip 7, 9, 11, 13, 14, 15 â€” physically uncommon)
CYL_OPTIONS = ["any", 1, 2, 3, 4, 5, 6, 8, 10, 12, 16]
CYL_SWEEP_VALUES = [3, 4, 5, 6, 8, 10, 12]  # used when cyl="any"
TAKT_OPTIONS = ["any", 2, 4]
TAKT_SWEEP_VALUES = [2, 4]  # used when takt="any"

METHOD_OPTIONS = [
    "STFT/Ridge", "Viterbi", "Peak", "Autokorrelation/YIN",
    "Cepstrum", "Harmonic Comb/HPS", "CWT/Wavelet", "Hybrid",
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
                            # fmax derived from physics: fundamental at rpm_max + headroom
                            f_fund_max = _fundamental_hz(rpm_max, cyl, order, takt)
                            if f_fund_max < 10.0:
                                continue  # below audio range
                            fmax = max(200.0, min(f_fund_max * fmax_headroom, 5000.0))
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


# â”€â”€ Sweep runner â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
        }
        _ret = extract_rpm_fn(
            y=y, fs=fs, start_s=start_s, end_s=end_s, offset_s=0.0,
            nfft=params["nfft"], overlap_pct=params["overlap_pct"],
            fmax=params["fmax"], cyl=params["cyl"], takt=params["takt"],
            order=params["order"], rpm_min=params["rpm_min"], rpm_max=params["rpm_max"],
            method=params["method"],
            cyl_mode="Fest auswÃ¤hlen", harmonic_mode="Fest auswÃ¤hlen",
            drive_type="Verbrenner/Hybrid", stft_mode="Fest auswÃ¤hlen",
            method_params=method_params,
        )
        t_audio, rpm_audio, _extra = _extract_t_rpm(_ret)
    except Exception as e:
        return _failed("extraction_error", str(e))

    if t_audio is None or len(t_audio) < 4:
        return _failed("too_few_points", f"n={0 if t_audio is None else len(t_audio)}")

    if offset_range > 0:
        best_off = cross_corr_offset(
            t_audio, rpm_audio, t_ref, rpm_ref,
            search_lo=offset_base - offset_range,
            search_hi=offset_base + offset_range,
            step=max(offset_step, 0.1),
        )
        fine_offsets = np.arange(
            best_off - offset_step * 2,
            best_off + offset_step * 2 + offset_step * 0.5,
            offset_step,
        ).tolist()
    else:
        fine_offsets = [offset_base]

    best_score_dict = None
    last_score_error = ""
    for off in fine_offsets:
        sd = score_agreement(t_audio, rpm_audio, t_ref, rpm_ref,
                             offset_s=off,
                             tol_abs_rpm=tol_abs_rpm,
                             tol_pct=tol_pct,
                             tol_logic=tol_logic)
        if not sd.get("ok"):
            last_score_error = sd.get("error", "scoring failed")
            continue
        if best_score_dict is None or sd["combined_score"] > best_score_dict["combined_score"]:
            best_score_dict = sd

    if best_score_dict is None:
        return _failed("no_valid_score", last_score_error)

    return {**params, **best_score_dict, "rank": 0}


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
) -> list[dict]:
    """
    Run the parameter sweep.

    For each grid entry:
      1. Extract RPM with given params (no OCR speed â€” cyl_mode='Fest auswÃ¤hlen',
         harmonic_mode='Fest auswÃ¤hlen', use_ocr_v=False)
      2. Find best offset via cross-corr around offset_base Â± offset_range
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
    )
    for i, params in enumerate(grid):
        if stop_event is not None and stop_event.is_set():
            break
        result = _eval_single_params(params, **_kw)
        results.append(result)
        if callable(progress_cb):
            try:
                progress_cb(i + 1, n_total, params, result)
            except Exception:
                pass

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
) -> list[dict]:
    """Bayesian optimisation with Optuna (TPE sampler)."""
    try:
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)
    except ImportError:
        raise ImportError(
            "optuna nicht installiert. Bitte 'pip install optuna' ausfÃ¼hren."
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
        fmax = round(max(200.0, min(f_fund_max * fmax_headroom, 5000.0)) / 10) * 10

        params = {
            "method": method, "nfft": int(nfft), "overlap_pct": float(overlap),
            "fmax": float(fmax), "cyl": cyl, "takt": takt, "order": order,
            "rpm_min": rpm_min, "rpm_max": rpm_max,
            "ridge_smooth": 7, "ridge_jump_frac": 0.08,
            "viterbi_jump_hz": 25.0, "viterbi_penalty": 1.2, "viterbi_smooth": 5,
            "comb_harmonics": 4, "hybrid_smooth": 9,
        }
        result = _eval_single_params(params, **_kw)
        results_all.append(result)

        trial_idx[0] += 1
        if callable(progress_cb):
            try:
                progress_cb(trial_idx[0], n_trials, params, result)
            except Exception:
                pass

        return float(result.get("combined_score", 0.0))

    study = optuna.create_study(
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=42),
    )
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


# â”€â”€ Persist sweep results â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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


