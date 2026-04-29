"""
save_helpers.py
Streamlit-unabhängige Hilfsfunktionen für MAT/JSON-Speicheroperationen.

Jede Funktion nimmt raw bytes entgegen und gibt bytes zurück – kein
Dateisystem, kein Streamlit, kein R2-Client. Testbar mit RTK/pytest.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import numpy as np
import scipy.io as sio


# ---------------------------------------------------------------------------
# Interne Helfer
# ---------------------------------------------------------------------------

def _mat_struct_to_plain_simple(obj) -> dict:
    """Minimal recursive mat_struct → dict converter (no Streamlit dep)."""
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


def _to_jsonable(obj) -> object:
    """Recursively convert numpy types and arrays to JSON-serializable types."""
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
    return obj


def _sanitize_keys(obj, max_len: int = 31) -> object:
    """Truncate all dict keys to max_len characters (MATLAB MAT-5 limit)."""
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
                sfx = f"_{seen[base]}"
                safe = base[: max_len - len(sfx)] + sfx
            out[safe] = _sanitize_keys(v, max_len)
        return out
    if isinstance(obj, list):
        return [_sanitize_keys(v, max_len) for v in obj]
    return obj


def _load_rr_from_bytes(raw: bytes) -> tuple[dict, dict]:
    """Load a MAT bytes blob and return (recordResult_plain_dict, extra_top_level_dict).

    Returns ({}, {}) on any error.
    """
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
        # v7.3 HDF5 — no BytesIO support; return empty
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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def field_exists_in_rr(mat_bytes: bytes, field_name: str) -> bool:
    """Return True if recordResult.<field_name> exists and is non-empty in mat_bytes."""
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
    new_value: object,
    extra_rr_fields: dict | None = None,
) -> tuple[bytes, bytes]:
    """Merge *new_value* into recordResult.<field_name> and return (mat_bytes, json_bytes).

    *extra_rr_fields* are merged into recordResult for fields not already present
    (e.g. {"metadata": {"title": "..."}}).  Does not overwrite existing rr keys.

    If *existing_mat_bytes* is empty or unreadable, starts from a blank recordResult.
    The output JSON and MAT always contain the same recordResult structure.
    """
    rr, extra = _load_rr_from_bytes(existing_mat_bytes)
    if extra_rr_fields:
        for k, v in extra_rr_fields.items():
            if rr.get(k) is None:
                rr[k] = v

    rr[field_name] = new_value

    out_data: dict = dict(extra)
    out_data["recordResult"] = rr
    out_data = _sanitize_keys(out_data)

    # ── MAT ─────────────────────────────────────────────────────────────────
    mat_buf = io.BytesIO()
    sio.savemat(mat_buf, out_data, do_compression=True)
    mat_bytes = mat_buf.getvalue()

    # ── JSON ─────────────────────────────────────────────────────────────────
    json_payload = _to_jsonable(out_data)
    json_bytes = json.dumps(
        json_payload, ensure_ascii=False, indent=2, default=str
    ).encode("utf-8")

    return mat_bytes, json_bytes
