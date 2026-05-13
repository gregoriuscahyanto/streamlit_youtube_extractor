"""Streamlit-independent helpers for MAT/JSON save operations.

Each function accepts raw bytes and returns raw bytes. No filesystem, no
Streamlit, no R2 client. This keeps the merge logic testable with RTK/pytest.
"""

from __future__ import annotations

import copy
import io
import json

import numpy as np
import scipy.io as sio


def _mat_struct_to_plain_simple(obj):
    """Minimal recursive mat_struct-to-dict converter without Streamlit deps."""
    if hasattr(obj, "_fieldnames"):
        return {f: _mat_struct_to_plain_simple(getattr(obj, f, None)) for f in (obj._fieldnames or [])}
    if isinstance(obj, dict):
        return {k: _mat_struct_to_plain_simple(v) for k, v in obj.items() if not str(k).startswith("#")}
    if isinstance(obj, np.ndarray):
        if obj.dtype.names:
            return {n: _mat_struct_to_plain_simple(obj[n]) for n in obj.dtype.names}
        if obj.dtype.kind == "O" and obj.size == 1:
            return _mat_struct_to_plain_simple(obj.ravel()[0])
        return obj
    return obj


def _to_jsonable(obj):
    """Recursively convert numpy values and arrays to JSON-serializable values."""
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    if isinstance(obj, (bytes, bytearray)):
        return obj.decode("utf-8", errors="ignore")
    return obj


def _deep_merge_missing(dst: dict, src: dict) -> dict:
    """Merge src into dst without overwriting existing values."""
    if not isinstance(dst, dict) or not isinstance(src, dict):
        return dst
    for k, v in src.items():
        if k not in dst or dst[k] is None:
            dst[k] = copy.deepcopy(v)
        elif isinstance(dst.get(k), dict) and isinstance(v, dict):
            _deep_merge_missing(dst[k], v)
    return dst


def _deep_merge_replace(dst: dict, src: dict) -> dict:
    """Merge src into dst and overwrite only keys present in src."""
    if not isinstance(dst, dict) or not isinstance(src, dict):
        return dst
    for k, v in src.items():
        if isinstance(dst.get(k), dict) and isinstance(v, dict):
            _deep_merge_replace(dst[k], v)
        else:
            dst[k] = copy.deepcopy(v)
    return dst


def _sanitize_keys(obj, max_len: int = 31):
    """Truncate dict keys to the MATLAB MAT-5 field-name limit."""
    if isinstance(obj, dict):
        seen: dict[str, int] = {}
        out: dict = {}
        for k, v in obj.items():
            base = str(k)[:max_len]
            if base not in seen:
                seen[base] = 0
                safe = base
            else:
                seen[base] += 1
                suffix = f"_{seen[base]}"
                safe = base[: max_len - len(suffix)] + suffix
            out[safe] = _sanitize_keys(v, max_len)
        return out
    if isinstance(obj, list):
        return [_sanitize_keys(v, max_len) for v in obj]
    return obj


def _load_rr_from_bytes(raw: bytes) -> tuple[dict, dict]:
    """Load MAT bytes and return (recordResult_dict, extra_top_level_dict)."""
    if not raw:
        return {}, {}
    try:
        data = sio.loadmat(
            io.BytesIO(raw),
            squeeze_me=True,
            struct_as_record=False,
            verify_compressed_data_integrity=False,
        )
    except NotImplementedError:
        return {}, {}
    except Exception:
        return {}, {}

    rr_raw = data.get("recordResult")
    rr = _mat_struct_to_plain_simple(rr_raw) if rr_raw is not None else {}
    if not isinstance(rr, dict):
        rr = {}

    extra = {
        k: v
        for k, v in data.items()
        if not str(k).startswith("__") and k != "recordResult"
    }
    return rr, extra


def field_exists_in_rr(mat_bytes: bytes, field_name: str) -> bool:
    """Return True if recordResult.<field_name> exists and is non-empty."""
    rr, _ = _load_rr_from_bytes(mat_bytes)
    val = rr.get(field_name)
    if val is None:
        return False
    if isinstance(val, (dict, list)) and len(val) == 0:
        return False
    if isinstance(val, np.ndarray) and val.size == 0:
        return False
    return True


def rr_from_mat_bytes(mat_bytes: bytes) -> tuple[dict, dict]:
    """Return (recordResult_dict, extra_top_level_dict) from raw MAT bytes."""
    return _load_rr_from_bytes(mat_bytes)


def build_merged_mat_json(
    existing_mat_bytes: bytes,
    field_name: str,
    new_value,
    extra_rr_fields: dict | None = None,
    base_record_result: dict | None = None,
) -> tuple[bytes, bytes]:
    """Replace one recordResult field and preserve all other fields."""
    return build_merged_mat_json_fields(
        existing_mat_bytes,
        {field_name: new_value},
        extra_rr_fields=extra_rr_fields,
        base_record_result=base_record_result,
    )


def build_merged_mat_json_fields(
    existing_mat_bytes: bytes,
    replace_rr_fields: dict,
    extra_rr_fields: dict | None = None,
    base_record_result: dict | None = None,
) -> tuple[bytes, bytes]:
    """Replace selected recordResult fields and preserve all other fields.

    Normal fields such as ``ocr``, ``audio_config``, ``audio_rpm`` and
    ``audio_validation`` are replaced as complete sections. ``metadata`` is
    merged key-by-key so status stamps can update their keys without erasing
    title, link, or other unrelated metadata.
    """
    rr, extra = _load_rr_from_bytes(existing_mat_bytes)

    if isinstance(base_record_result, dict) and base_record_result:
        if not rr:
            rr = copy.deepcopy(base_record_result)
        else:
            _deep_merge_missing(rr, base_record_result)

    if extra_rr_fields:
        _deep_merge_missing(rr, extra_rr_fields)

    for field_name, new_value in dict(replace_rr_fields or {}).items():
        if field_name == "metadata" and isinstance(new_value, dict) and isinstance(rr.get("metadata"), dict):
            _deep_merge_replace(rr["metadata"], new_value)
        else:
            rr[field_name] = new_value

    out_data = dict(extra)
    out_data["recordResult"] = rr
    out_data = _sanitize_keys(out_data)

    mat_buf = io.BytesIO()
    sio.savemat(mat_buf, out_data, do_compression=True)
    mat_bytes = mat_buf.getvalue()

    json_payload = _to_jsonable(out_data)
    json_bytes = json.dumps(json_payload, ensure_ascii=False, indent=2, default=str).encode("utf-8")
    return mat_bytes, json_bytes
