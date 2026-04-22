"""
Backend helpers shared by Streamlit GUI (app.py) and CLI (cli.py).
"""
from __future__ import annotations

import os
from pathlib import Path
import io
from datetime import datetime
import tomllib
import numpy as np
import scipy.io as sio

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


def config_from_mat_file(mat_path: str, vid_duration: float = 0.0) -> dict:
    out: dict = {"rois": [], "t_start": 0.0, "t_end": float(vid_duration)}
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
        names = list(np.atleast_1d(getattr(roi_tbl, "name_roi", [])))
        rois_r = list(np.atleast_1d(getattr(roi_tbl, "roi", [])))
        fmts = list(np.atleast_1d(getattr(roi_tbl, "fmt", [])))
        rois = []
        for n, r, f in zip(names, rois_r, fmts):
            pos = np.atleast_1d(r).astype(float)
            if len(pos) == 4:
                rois.append(dict(
                    name=str(n), x=float(pos[0]), y=float(pos[1]),
                    w=float(pos[2]), h=float(pos[3]),
                    fmt=str(f), pattern="", max_scale=1.2,
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
    return out
