"""
Backend helpers shared by Streamlit GUI (app.py) and CLI (cli.py).
"""
from __future__ import annotations

import os
import re
from pathlib import Path
import io
from datetime import datetime
import tomllib
from typing import Any
import numpy as np
import scipy.io as sio
try:
    import h5py
except Exception:  # pragma: no cover
    h5py = None

from r2_client import R2Client


def load_r2_credentials(
    streamlit_secrets=None,
    secrets_path: str = ".streamlit/secrets.toml",
) -> tuple[str, str, str, str]:
    """
    Returns (account_id, access_key_id, secret_access_key, bucket).
    Priority:
    1) streamlit_secrets["r2"]
    2) env vars R2_ACCOUNT_ID / R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY / R2_BUCKET
    3) local secrets.toml [r2]
    """
    if streamlit_secrets is not None:
        try:
            sec = streamlit_secrets.get("r2", {})
            vals = (
                sec.get("account_id", "") or "",
                sec.get("access_key_id", "") or "",
                sec.get("secret_access_key", "") or "",
                sec.get("bucket", "") or "",
            )
            if any(vals):
                return vals
        except Exception:
            pass

    env_vals = (
        os.environ.get("R2_ACCOUNT_ID", ""),
        os.environ.get("R2_ACCESS_KEY_ID", ""),
        os.environ.get("R2_SECRET_ACCESS_KEY", ""),
        os.environ.get("R2_BUCKET", ""),
    )
    if any(env_vals):
        return env_vals

    try:
        path = Path(secrets_path)
        if path.exists():
            with open(path, "rb") as f:
                data = tomllib.load(f)
            sec = data.get("r2", {})
            return (
                sec.get("account_id", "") or "",
                sec.get("access_key_id", "") or "",
                sec.get("secret_access_key", "") or "",
                sec.get("bucket", "") or "",
            )
    except Exception:
        pass

    return ("", "", "", "")


def connect_r2_client(
    account_id: str, access_key_id: str, secret_access_key: str, bucket: str
) -> tuple[bool, str, R2Client | None]:
    if not all([account_id, access_key_id, secret_access_key, bucket]):
        return False, "Bitte alle Felder ausfüllen.", None
    client = R2Client(account_id, access_key_id, secret_access_key, bucket)
    ok, msg = client.test_connection()
    return ok, msg, client if ok else None


def list_root_prefixes(client: R2Client) -> list[str]:
    """Lists top-level 'folders' (key prefixes) in the bucket."""
    prefixes = [""]
    ok, items = client.list_files("")
    if ok and isinstance(items, list):
        for item in items:
            if item.endswith("/"):
                name = item.rstrip("/")
                if name:
                    prefixes.append(name)
    return sorted(prefixes)


def collect_r2_listing_debug(
    client: R2Client, prefix: str = "", capture_folder: str = ""
) -> list[dict]:
    pfx = prefix.strip("/")
    cap = (pfx + "/captures").strip("/") if pfx else "captures"
    res = (pfx + "/results").strip("/") if pfx else "results"
    probes = [("root", ""), ("prefix", pfx), ("captures", cap), ("results", res)]
    if capture_folder:
        probes.append(("capture_folder", (cap + "/" + capture_folder).strip("/")))

    report: list[dict] = []
    for label, remote_dir in probes:
        try:
            ok, items_or_err = client.list_files(remote_dir)
            if ok and isinstance(items_or_err, list):
                report.append({"probe": label, "prefix": remote_dir, "ok": True,
                               "count": len(items_or_err), "items": items_or_err[:100], "error": ""})
            else:
                report.append({"probe": label, "prefix": remote_dir, "ok": False,
                               "count": 0, "items": [], "error": str(items_or_err)})
        except Exception as e:
            report.append({"probe": label, "prefix": remote_dir, "ok": False,
                           "count": 0, "items": [], "error": f"{e.__class__.__name__}: {e}"})
    return report


def build_result_payload(
    t_start: float,
    t_end: float,
    rois: list[dict],
    video: dict,
    track: dict | None = None,
) -> dict:
    return {
        "params": {"start_s": float(t_start), "end_s": float(t_end)},
        "roi_table": [
            {
                "name_roi": r.get("name", "_"),
                "roi": [float(r.get("x", 0)), float(r.get("y", 0)),
                        float(r.get("w", 0)), float(r.get("h", 0))],
                "fmt": r.get("fmt", "any"),
                "pattern": r.get("pattern", ""),
                "max_scale": float(r.get("max_scale", 1.2)),
            }
            for r in rois
        ],
        "video": {
            "width": int(video.get("width", 0)),
            "height": int(video.get("height", 0)),
            "fps": float(video.get("fps", 0)),
            "duration": float(video.get("duration", 0)),
        },
        "track": {
            "ref_pts": (track or {}).get("ref_pts"),
            "minimap_pts": (track or {}).get("minimap_pts"),
            "moving_pt_color_range": (track or {}).get("moving_pt_color_range"),
        },
    }


def build_mat_struct(result: dict, video_name: str = "") -> dict:
    roi_table = {}
    for field in ["name_roi", "roi", "fmt", "pattern", "max_scale"]:
        roi_table[field] = [row.get(field, "") for row in result.get("roi_table", [])]

    p = result.get("params", {})
    v = result.get("video", {})
    t = result.get("track", {})
    return {
        "recordResult": {
            "ocr": {
                "params": {
                    "start_s": float(p.get("start_s", 0.0)),
                    "end_s": float(p.get("end_s", 0.0)),
                    "fps": float(v.get("fps", 0.0)),
                    "duration_s": float(v.get("duration", 0.0)),
                    "video_size_wh": np.array([int(v.get("width", 0)), int(v.get("height", 0))]),
                },
                "roi_table": roi_table,
                "trkCalSlim": {
                    "ref_pts": np.array(t.get("ref_pts") or [], dtype=float),
                    "minimap_pts": np.array(t.get("minimap_pts") or [], dtype=float),
                },
                "created": str(datetime.now()),
            },
            "metadata": {"video": video_name},
        }
    }


def mat_bytes_from_result(result: dict, video_name: str = "") -> bytes:
    buf = io.BytesIO()
    sio.savemat(buf, build_mat_struct(result, video_name=video_name))
    return buf.getvalue()


def config_from_json_payload(data: dict, vid_duration: float = 0.0) -> dict:
    p = data.get("params", {})
    rois = []
    for r in data.get("roi_table", []):
        pos = r.get("roi", [0, 0, 100, 50])
        rois.append(
            dict(
                name=r.get("name_roi", "_"),
                x=float(pos[0]), y=float(pos[1]),
                w=float(pos[2]), h=float(pos[3]),
                fmt=r.get("fmt", "any"),
                pattern=r.get("pattern", ""),
                max_scale=float(r.get("max_scale", 1.2)),
            )
        )
    t = data.get("track", {})
    out = {
        "t_start": float(p.get("start_s", 0)),
        "t_end": float(p.get("end_s", vid_duration)),
        "rois": rois,
    }
    if t.get("ref_pts"):
        out["ref_track_pts"] = t["ref_pts"]
    if t.get("minimap_pts"):
        out["minimap_pts"] = t["minimap_pts"]
    if t.get("moving_pt_color_range"):
        out["moving_pt_color_range"] = t["moving_pt_color_range"]
    return out


def _parse_roi_coords(r) -> list[float] | None:
    """Parse ROI value as either a numeric array or a space-separated string like '41 52 105 52'."""
    try:
        arr = np.atleast_1d(r).astype(float)
        if arr.size >= 4:
            return [float(v) for v in arr.flat[:4]]
    except (ValueError, TypeError):
        pass
    try:
        nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", str(r))]
        if len(nums) >= 4:
            return nums[:4]
    except Exception:
        pass
    return None


def _atleast_1d_cell(val) -> list:
    """Convert a squeezed MATLAB cell-array value to a Python list, handling scalar strings."""
    arr = np.atleast_1d(val)
    # A 1-D numeric array of exactly 4 elements is a single ROI stored flat — wrap it.
    if arr.ndim == 1 and arr.dtype.kind in ("i", "u", "f") and arr.size == 4:
        return [arr]
    return list(arr)


def config_from_mat_file(mat_path: str, vid_duration: float = 0.0) -> dict:
    out: dict = {"rois": [], "t_start": 0.0, "t_end": float(vid_duration)}
    try:
        mat = sio.loadmat(mat_path, squeeze_me=True, struct_as_record=False)
        rr = mat.get("recordResult")
        if not rr:
            return out
        ocr = getattr(rr, "ocr", None)
        if not ocr:
            return out
        prm = getattr(ocr, "params", None)
        if prm:
            out["t_start"] = float(getattr(prm, "start_s", 0))
            out["t_end"] = float(getattr(prm, "end_s", vid_duration))
        roi_tbl = getattr(ocr, "roi_table", None)
        if roi_tbl:
            names    = _atleast_1d_cell(getattr(roi_tbl, "name_roi", []))
            rois_r   = _atleast_1d_cell(getattr(roi_tbl, "roi", []))
            fmts     = _atleast_1d_cell(getattr(roi_tbl, "fmt", []))
            patterns = _atleast_1d_cell(getattr(roi_tbl, "pattern", []))
            scales   = _atleast_1d_cell(getattr(roi_tbl, "max_scale", []))
            rois = []
            for i, (n, r, f) in enumerate(zip(names, rois_r, fmts)):
                coords = _parse_roi_coords(r)
                if coords:
                    x, y, w, h = coords
                    pat = str(patterns[i]).strip() if i < len(patterns) else ""
                    ms  = float(scales[i])         if i < len(scales)   else 1.2
                    rois.append(dict(
                        name=str(n).strip(), x=x, y=y, w=w, h=h,
                        fmt=str(f).strip(), pattern=pat, max_scale=ms,
                    ))
            out["rois"] = rois
        trk = getattr(ocr, "trkCalSlim", None)
        if trk:
            ref_pts = getattr(trk, "ref_pts", None)
            minimap_pts = getattr(trk, "minimap_pts", None)
            if ref_pts is not None and np.size(ref_pts) > 0:
                out["ref_track_pts"] = np.atleast_2d(ref_pts).astype(float).tolist()
            if minimap_pts is not None and np.size(minimap_pts) > 0:
                out["minimap_pts"] = np.atleast_2d(minimap_pts).astype(float).tolist()
    except NotImplementedError:
        # MATLAB -v7.3 files need HDF5 parsing.
        return _config_from_mat_file_v73(mat_path, vid_duration=vid_duration)
    except Exception:
        return out
    return out


def _h5_matlab_class(obj: Any) -> str:
    try:
        cls = obj.attrs.get("MATLAB_class", b"")
        if isinstance(cls, bytes):
            return cls.decode("utf-8", errors="ignore")
        return str(cls)
    except Exception:
        return ""


def _h5_decode_char_dataset(ds: Any) -> str:
    try:
        arr = np.array(ds[()]).reshape(-1)
        chars: list[str] = []
        for v in arr:
            try:
                iv = int(v)
            except Exception:
                continue
            if iv > 0:
                chars.append(chr(iv))
        return "".join(chars)
    except Exception:
        return ""


def _h5_decode_cell_char_list(h5f: Any, ds: Any) -> list[str]:
    out: list[str] = []
    try:
        arr = np.array(ds[()]).reshape(-1)
    except Exception:
        return out
    for ref in arr:
        try:
            obj = h5f[ref]
        except Exception:
            out.append("")
            continue
        if _h5_matlab_class(obj) == "char":
            out.append(_h5_decode_char_dataset(obj))
        else:
            out.append("")
    return out


def _h5_decode_numeric_codes(ds: Any) -> list[int]:
    try:
        raw = np.array(ds[()])
        if raw.dtype.fields and "real" in raw.dtype.fields:
            raw = np.array(raw["real"])
        arr = raw.reshape(-1)
        out: list[int] = []
        for v in arr:
            try:
                out.append(int(round(float(v))))
            except Exception:
                continue
        return out
    except Exception:
        return []


def _h5_decode_float_values(ds: Any) -> list[float]:
    try:
        raw = np.array(ds[()])
        if raw.dtype.fields and "real" in raw.dtype.fields:
            raw = np.array(raw["real"])
        arr = raw.reshape(-1)
        out: list[float] = []
        for v in arr:
            try:
                out.append(float(v))
            except Exception:
                continue
        return out
    except Exception:
        return []


def _h5_object_name(obj: Any) -> str:
    try:
        return str(obj.name)
    except Exception:
        return ""


def _h5_valid_category_codes(
    codes: list[int],
    categories: list[str],
    row_count: int,
) -> list[int]:
    if row_count <= 0 or not categories or len(codes) < row_count:
        return []
    out: list[int] = []
    for raw in codes[:row_count]:
        try:
            code = int(raw)
        except Exception:
            return []
        if code < 1 or code > len(categories):
            return []
        out.append(code)
    return out


def _h5_category_labels(categories: list[str], codes: list[int]) -> list[str]:
    labels: list[str] = []
    for code in codes:
        if 1 <= int(code) <= len(categories):
            labels.append(str(categories[int(code) - 1]).strip())
        else:
            labels.append("")
    return labels


def _h5_non_default_fmt_score(categories: list[str], codes: list[int]) -> int:
    labels = _h5_category_labels(categories, codes)
    return sum(1 for label in labels if label and label not in ("any", "<undefined>"))


def _h5_decode_u64_string_rows(ds: Any) -> list[str]:
    """
    Decode MATLAB v7.3 uint64-packed UTF-16 string vectors used in ROI table raw data.
    """
    try:
        vals = [int(v) for v in np.array(ds[()]).reshape(-1).astype(np.uint64)]
    except Exception:
        return []
    if len(vals) < 5 or vals[0] != 1 or vals[1] != 2:
        return []
    n_rows = max(1, int(vals[2]))
    if len(vals) < 4 + n_rows:
        return []
    lengths = [max(0, int(v)) for v in vals[4:4 + n_rows]]
    data_vals = vals[4 + n_rows:]

    chars: list[str] = []
    for word in data_vals:
        w = int(word)
        for _ in range(4):
            u = w & 0xFFFF
            if u != 0:
                chars.append(chr(u))
            w >>= 16
    flat = "".join(chars)

    rows: list[str] = []
    pos = 0
    for ln in lengths:
        if ln <= 0:
            rows.append("")
            continue
        rows.append(flat[pos:pos + ln])
        pos += ln
    if not rows and flat:
        rows = [flat]
    return rows


def _h5_read_scalar_float(h5f: Any, path: str, default: float) -> float:
    try:
        if path not in h5f:
            return float(default)
        arr = np.array(h5f[path][()])
        if arr.dtype.fields and "real" in arr.dtype.fields:
            arr = np.array(arr["real"])
        vals = arr.reshape(-1)
        if vals.size == 0:
            return float(default)
        return float(vals[0])
    except Exception:
        return float(default)


def _h5_extract_rois_from_roi_table_raw(h5f: Any) -> list[dict]:
    """
    Extract ROI rows from MATLAB v7.3 recordResult.ocr.roi_table_raw.
    Works for OCRExtractor-generated files where roi_table_raw is stored as table/object.
    """
    if "recordResult/ocr/roi_table_raw" not in h5f or "#subsystem#/MCOS" not in h5f:
        return []
    try:
        desc = np.array(h5f["recordResult/ocr/roi_table_raw"][()]).reshape(-1)
        if len(desc) < 5:
            return []
        base_idx = int(desc[4])
        mcos = h5f["#subsystem#/MCOS"][()]
    except Exception:
        return []

    def mcos_obj(idx: int) -> Any | None:
        try:
            if idx < 0:
                return None
            ref = mcos[0, idx]
            return h5f[ref]
        except Exception:
            return None

    data_cell = mcos_obj(base_idx + 2)
    if data_cell is None or _h5_matlab_class(data_cell) != "cell":
        return []
    try:
        data_refs = np.array(data_cell[()]).reshape(-1)
        if len(data_refs) < 5:
            return []
    except Exception:
        return []

    try:
        d_name_cat = np.array(h5f[data_refs[0]][()]).reshape(-1)
        d_name_codes = np.array(h5f[data_refs[1]][()]).reshape(-1)
        d_roi_rows = np.array(h5f[data_refs[2]][()]).reshape(-1)
        d_fmt_cat = np.array(h5f[data_refs[3]][()]).reshape(-1)
    except Exception:
        return []

    def desc_idx(arr: np.ndarray) -> int | None:
        try:
            if arr.size < 5:
                return None
            return int(arr[4])
        except Exception:
            return None

    idx_name_cat = desc_idx(d_name_cat)
    idx_name_codes = desc_idx(d_name_codes)
    idx_roi_rows = desc_idx(d_roi_rows)
    idx_fmt_cat = desc_idx(d_fmt_cat)
    if None in (idx_name_cat, idx_name_codes, idx_roi_rows, idx_fmt_cat):
        return []

    obj_name_cat = mcos_obj(int(idx_name_cat))
    obj_name_codes = mcos_obj(int(idx_name_codes))
    obj_roi_rows = mcos_obj(int(idx_roi_rows))
    obj_fmt_cat = mcos_obj(int(idx_fmt_cat))
    obj_fmt_codes = mcos_obj(base_idx + 3)
    obj_max_scale = h5f[data_refs[4]] if len(data_refs) >= 5 else None

    if obj_name_cat is None or obj_name_codes is None or obj_roi_rows is None:
        return []

    name_categories = _h5_decode_cell_char_list(h5f, obj_name_cat)
    name_codes = _h5_decode_numeric_codes(obj_name_codes)
    roi_rows = _h5_decode_u64_string_rows(obj_roi_rows)
    fmt_categories = _h5_decode_cell_char_list(h5f, obj_fmt_cat) if obj_fmt_cat is not None else []
    max_scales = _h5_decode_float_values(obj_max_scale) if obj_max_scale is not None else []

    if not roi_rows and not name_codes:
        return []

    rois: list[dict] = []
    row_count = max(len(name_codes), len(roi_rows), len(max_scales), 1)

    excluded_code_sources = {
        _h5_object_name(obj_name_cat),
        _h5_object_name(obj_name_codes),
        _h5_object_name(obj_roi_rows),
        _h5_object_name(obj_fmt_cat),
        _h5_object_name(obj_max_scale),
    }
    primary_fmt_codes: list[int] = []
    if (
        obj_fmt_codes is not None
        and _h5_object_name(obj_fmt_codes) not in excluded_code_sources
    ):
        primary_fmt_codes = _h5_valid_category_codes(
            _h5_decode_numeric_codes(obj_fmt_codes),
            fmt_categories,
            row_count,
        )

    fmt_codes = primary_fmt_codes
    if fmt_categories and (
        not fmt_codes or _h5_non_default_fmt_score(fmt_categories, fmt_codes) == 0
    ):
        best_codes = fmt_codes
        best_score = _h5_non_default_fmt_score(fmt_categories, best_codes)
        try:
            n_mcos = int(mcos.shape[1])
        except Exception:
            n_mcos = 0
        for idx in range(n_mcos):
            candidate_obj = mcos_obj(idx)
            candidate_name = _h5_object_name(candidate_obj)
            if candidate_obj is None or candidate_name in excluded_code_sources:
                continue
            candidate_codes = _h5_valid_category_codes(
                _h5_decode_numeric_codes(candidate_obj),
                fmt_categories,
                row_count,
            )
            if not candidate_codes:
                continue
            score = _h5_non_default_fmt_score(fmt_categories, candidate_codes)
            if score > best_score:
                best_codes = candidate_codes
                best_score = score
        fmt_codes = best_codes

    for i in range(row_count):
        code = name_codes[i] if i < len(name_codes) else 1
        if 1 <= code <= len(name_categories):
            name = name_categories[code - 1] or "_"
        else:
            name = "_"

        roi_txt = roi_rows[i] if i < len(roi_rows) else ""
        nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", roi_txt)]
        if len(nums) >= 4:
            x, y, w, h = nums[:4]
        else:
            x, y, w, h = 0.0, 0.0, 100.0, 50.0

        fmt = "any"
        fmt_code = None
        if i < len(fmt_codes):
            fmt_code = fmt_codes[i]
        elif fmt_codes:
            fmt_code = fmt_codes[0]
        if fmt_code is not None and 1 <= int(fmt_code) <= len(fmt_categories):
            fmt = fmt_categories[int(fmt_code) - 1] or "any"

        if i < len(max_scales):
            max_scale = float(max_scales[i])
        elif max_scales:
            max_scale = float(max_scales[0])
        else:
            max_scale = 1.2

        rois.append(
            dict(
                name=str(name),
                x=float(x),
                y=float(y),
                w=float(w),
                h=float(h),
                fmt=str(fmt),
                pattern="",
                max_scale=float(max_scale),
            )
        )
    return rois


def _config_from_mat_file_v73(mat_path: str, vid_duration: float = 0.0) -> dict:
    out: dict = {"rois": [], "t_start": 0.0, "t_end": float(vid_duration)}
    if h5py is None:
        return out
    try:
        with h5py.File(mat_path, "r") as h5f:
            out["t_start"] = _h5_read_scalar_float(
                h5f,
                "recordResult/ocr/params/start_s",
                default=0.0,
            )
            out["t_end"] = _h5_read_scalar_float(
                h5f,
                "recordResult/ocr/params/end_s",
                default=float(vid_duration),
            )
            rois = _h5_extract_rois_from_roi_table_raw(h5f)
            if rois:
                out["rois"] = rois
    except Exception:
        return out
    return out


def _mat_get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _is_nonempty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) > 0
    if isinstance(value, np.ndarray):
        return value.size > 0
    return True


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    try:
        if isinstance(value, np.ndarray):
            if value.size == 0:
                return ""
            value = value.flatten()[0]
        return str(value).strip()
    except Exception:
        return ""


def _guess_capture_folder(mat_name: str, video_ref: str = "") -> str:
    name = Path(mat_name).name
    if name.startswith("results_") and name.lower().endswith(".mat"):
        return name[len("results_"):-4]
    video_name = Path(video_ref).name
    if video_name.lower().endswith(".mp4"):
        return Path(video_name).stem
    return ""


def _count_roi_entries(roi_table: Any) -> int:
    names = _mat_get(roi_table, "name_roi")
    if names is None:
        return 0
    try:
        return int(np.atleast_1d(names).size)
    except Exception:
        return 0


def _has_track_roi(roi_table: Any) -> bool:
    names = _mat_get(roi_table, "name_roi")
    if names is None:
        return False
    try:
        values = [str(x) for x in np.atleast_1d(names).tolist()]
        return any(v == "track_minimap" for v in values)
    except Exception:
        return False


def _count_points(pts: Any) -> int:
    if pts is None:
        return 0
    try:
        arr = np.atleast_2d(np.asarray(pts, dtype=float))
        if arr.size == 0:
            return 0
        if arr.shape[1] != 2:
            return 0
        return int(arr.shape[0])
    except Exception:
        return 0


def summarize_mat_file(mat_path: str) -> dict:
    """
    Reads one MAT file and returns status booleans/details for pipeline progress.
    """
    out = {
        "mat_file": Path(mat_path).name,
        "error": "",
        "capture_folder": "",
        "video_ref": "",
        "audio_ref": "",
        "video_ref_present": False,
        "audio_ref_present": False,
        "roi_selected": False,
        "roi_count": 0,
        "track_selected": False,
        "track_points_ref": 0,
        "track_points_minimap": 0,
        "start_end_selected": False,
        "start_s": None,
        "end_s": None,
        "ocr_done": False,
        "ocr_complete": False,
        "audio_spectrogram_done": False,
        "validation_done": False,
    }
    try:
        mat = sio.loadmat(mat_path, squeeze_me=True, struct_as_record=False)
        rr = mat.get("recordResult")
        if rr is None:
            out["error"] = "recordResult fehlt"
            return out

        meta = _mat_get(rr, "metadata")
        video_ref = _safe_str(_mat_get(meta, "video")) or _safe_str(_mat_get(rr, "video"))
        audio_ref = _safe_str(_mat_get(meta, "audio")) or _safe_str(_mat_get(rr, "audio"))
        out["video_ref"] = video_ref
        out["audio_ref"] = audio_ref
        out["video_ref_present"] = bool(video_ref)
        out["audio_ref_present"] = bool(audio_ref)
        out["capture_folder"] = _guess_capture_folder(out["mat_file"], video_ref)

        ocr = _mat_get(rr, "ocr")
        roi_table = _mat_get(ocr, "roi_table")
        roi_count = _count_roi_entries(roi_table)
        out["roi_count"] = roi_count
        out["roi_selected"] = roi_count > 0

        trk = _mat_get(ocr, "trkCalSlim")
        ref_pts = _count_points(_mat_get(trk, "ref_pts"))
        minimap_pts = _count_points(_mat_get(trk, "minimap_pts"))
        out["track_points_ref"] = ref_pts
        out["track_points_minimap"] = minimap_pts
        out["track_selected"] = _has_track_roi(roi_table) or (ref_pts >= 4 and minimap_pts >= 4)

        prm = _mat_get(ocr, "params")
        start_s = _mat_get(prm, "start_s")
        end_s = _mat_get(prm, "end_s")
        try:
            start_f = float(start_s)
            end_f = float(end_s)
            out["start_s"] = start_f
            out["end_s"] = end_f
            out["start_end_selected"] = end_f > start_f
        except Exception:
            out["start_end_selected"] = False

        ocr_outputs = [
            _mat_get(ocr, "table"),
            _mat_get(ocr, "raw"),
            _mat_get(ocr, "result"),
            _mat_get(ocr, "results"),
            _mat_get(ocr, "text"),
            _mat_get(ocr, "ocr_table"),
        ]
        out["ocr_done"] = any(_is_nonempty(v) for v in ocr_outputs)
        out["ocr_complete"] = bool(
            out["ocr_done"]
            and out["roi_selected"]
            and out["start_end_selected"]
        )

        out["audio_spectrogram_done"] = any(
            _is_nonempty(_mat_get(rr, field))
            for field in ("audio_rpm", "audio_analysis", "spectrogram", "audioSpectrogram")
        )
        out["validation_done"] = any(
            _is_nonempty(_mat_get(rr, field))
            for field in ("validation", "validierung", "comparison", "vergleich")
        )
        return out
    except NotImplementedError as e:
        if h5py is None:
            out["error"] = (
                f"{e.__class__.__name__}: {e}. "
                "Für MATLAB v7.3 bitte h5py installieren."
            )
            return out
        try:
            return _summarize_mat_file_v73(mat_path, out)
        except Exception as e2:
            out["error"] = f"{e2.__class__.__name__}: {e2}"
            return out
    except Exception as e:
        out["error"] = f"{e.__class__.__name__}: {e}"
        return out


def _summarize_mat_file_v73(mat_path: str, out: dict) -> dict:
    """
    Fallback reader for MATLAB v7.3 MAT files (HDF5-based).
    This extracts robust status signals from dataset/group names.
    """
    if h5py is None:
        raise RuntimeError("h5py ist nicht verfügbar")

    names: list[str] = []
    with h5py.File(mat_path, "r") as h5f:
        h5f.visit(names.append)

    def has_token(token: str) -> bool:
        t = token.lower()
        return any(t in n.lower() for n in names)

    out["error"] = ""
    out["roi_selected"] = has_token("name_roi") or has_token("roi_table")
    out["track_selected"] = has_token("track_minimap") or has_token("trkcalslim")
    out["start_end_selected"] = has_token("start_s") and has_token("end_s")
    out["ocr_done"] = has_token("ocr/table") or has_token("ocr/result") or has_token("ocr/results")
    out["ocr_complete"] = bool(
        out["ocr_done"]
        and out["roi_selected"]
        and out["start_end_selected"]
    )
    out["audio_spectrogram_done"] = has_token("audio_rpm") or has_token("spectrogram") or has_token("audio_analysis")
    out["validation_done"] = has_token("validation") or has_token("vergleich") or has_token("comparison")
    return out


def summarize_mat_status_rows(summary: dict) -> list[dict]:
    """
    Converts summarize_mat_file output into a table-friendly row list.
    """
    start = summary.get("start_s")
    end = summary.get("end_s")
    if isinstance(start, (int, float)) and isinstance(end, (int, float)):
        start_end_detail = f"{start:.3f} -> {end:.3f} s"
    else:
        start_end_detail = "-"

    video_ok = summary.get("video_file_exists")
    audio_ok = summary.get("audio_file_exists")
    if video_ok is None:
        video_ok = summary.get("video_ref_present")
    if audio_ok is None:
        audio_ok = summary.get("audio_ref_present")

    return [
        {
            "check": "Audio- und Video-Referenz vorhanden",
            "status": "Ja" if video_ok and audio_ok else "Nein",
            "detail": f"video='{summary.get('video_ref', '')}', audio='{summary.get('audio_ref', '')}'",
        },
        {
            "check": "ROI ausgewählt",
            "status": "Ja" if summary.get("roi_selected") else "Nein",
            "detail": f"ROI-Anzahl: {summary.get('roi_count', 0)}",
        },
        {
            "check": "Track ausgewählt",
            "status": "Ja" if summary.get("track_selected") else "Nein",
            "detail": f"ref_pts={summary.get('track_points_ref', 0)}, minimap_pts={summary.get('track_points_minimap', 0)}",
        },
        {
            "check": "Anfang/Ende ausgewählt",
            "status": "Ja" if summary.get("start_end_selected") else "Nein",
            "detail": start_end_detail,
        },
        {
            "check": "OCR durchgeführt",
            "status": "Ja" if summary.get("ocr_done") else "Nein",
            "detail": "vollständig" if summary.get("ocr_complete") else "unvollständig/keine Daten",
        },
        {
            "check": "Audioanalyse/Spektrogramm durchgeführt",
            "status": "Ja" if summary.get("audio_spectrogram_done") else "Nein",
            "detail": "",
        },
        {
            "check": "Validierung durchgeführt",
            "status": "Ja" if summary.get("validation_done") else "Nein",
            "detail": "",
        },
    ]
