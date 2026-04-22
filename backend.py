"""
Backend helpers shared by Streamlit GUI (app.py) and CLI (cli.py).
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote, urlparse
import socket
import io
from datetime import datetime
import tomllib
import requests
from requests.auth import HTTPBasicAuth
import numpy as np
import scipy.io as sio

from webdav_client import WebDAVClient


def load_webdav_credentials(streamlit_secrets=None, secrets_path: str = ".streamlit/secrets.toml") -> tuple[str, str, str]:
    """
    Load WebDAV credentials.
    Priority:
    1) streamlit_secrets["webdav"] if available
    2) local secrets.toml fallback
    """
    sec_url = sec_user = sec_pass = ""

    if streamlit_secrets is not None:
        try:
            sec = streamlit_secrets.get("webdav", {})
            sec_url = sec.get("url", "") or ""
            sec_user = sec.get("username", "") or ""
            sec_pass = sec.get("password", "") or ""
            if sec_url or sec_user or sec_pass:
                return sec_url, sec_user, sec_pass
        except Exception:
            pass

    try:
        path = Path(secrets_path)
        if path.exists():
            with open(path, "rb") as f:
                data = tomllib.load(f)
            sec = data.get("webdav", {})
            sec_url = sec.get("url", "") or ""
            sec_user = sec.get("username", "") or ""
            sec_pass = sec.get("password", "") or ""
    except Exception:
        pass

    return sec_url, sec_user, sec_pass


def connect_webdav_client(url: str, user: str, password: str) -> tuple[bool, str, WebDAVClient | None]:
    if not (url and user and password):
        return False, "Bitte alle Felder ausfullen.", None
    client = WebDAVClient(url, user, password)
    ok, msg = client.test_connection()
    return ok, msg, client if ok else None


def list_root_folders(client: WebDAVClient, depth_levels: int = 2) -> list[str]:
    folders = ["/"]
    ok, items = client.list_files("")
    if ok and isinstance(items, list):
        for item in items:
            if item.endswith("/"):
                name = item.rstrip("/")
                if name:
                    folders.append("/" + name)
    if depth_levels >= 2:
        for folder in list(folders[1:]):
            ok2, sub = client.list_files(folder)
            if ok2 and isinstance(sub, list):
                for s in sub:
                    if s.endswith("/"):
                        sname = s.rstrip("/")
                        if sname:
                            full = folder.rstrip("/") + "/" + sname
                            if full not in folders:
                                folders.append(full)
    return sorted(folders)


def run_webdav_diagnostic(url: str, user: str, password: str) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    raw_url = (url or "").strip()
    if not raw_url:
        return [("Fehler", "WebDAV URL ist leer.")]

    parsed = urlparse(raw_url)
    host = parsed.hostname
    if not host:
        return [("Fehler", f"Ungueltige URL: {raw_url}")]

    results.append(("Host", host))

    # DNS
    try:
        dns_info = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
        ips = sorted({entry[4][0] for entry in dns_info})
        results.append(("DNS", f"OK ({', '.join(ips[:4])})"))
    except Exception as e:
        results.append(("DNS", f"Fehler: {e.__class__.__name__}: {e}"))
        return results

    # TCP
    try:
        with socket.create_connection((host, 443), timeout=8):
            pass
        results.append(("TCP 443", "OK"))
    except Exception as e:
        results.append(("TCP 443", f"Fehler: {e.__class__.__name__}: {e}"))
        return results

    # PROPFIND
    probe_url = raw_url.rstrip("/") + "/"
    if probe_url.lower().endswith("/remote.php/dav/files/") and user:
        probe_url = probe_url + quote(user.strip(), safe="") + "/"
    auth = HTTPBasicAuth(user, password) if user and password else None
    try:
        r = requests.request(
            "PROPFIND",
            probe_url,
            headers={"Depth": "0", "Content-Type": "application/xml; charset=utf-8"},
            data='<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/></d:prop></d:propfind>',
            auth=auth,
            timeout=(8, 20),
        )
        results.append(("PROPFIND", f"HTTP {r.status_code}"))
        results.append(("Probe URL", probe_url))
    except Exception as e:
        results.append(("PROPFIND", f"Fehler: {e.__class__.__name__}: {e}"))
        results.append(("Probe URL", probe_url))

    return results


def collect_webdav_listing_debug(client: WebDAVClient, root: str = "/", capture_folder: str = "") -> list[dict]:
    root = root or "/"
    root_rel = root.strip("/")
    cap_rel = ((root_rel + "/captures") if root_rel else "captures").strip("/")
    res_rel = ((root_rel + "/results") if root_rel else "results").strip("/")
    cap_folder_rel = (
        ((root_rel + "/captures/" + capture_folder) if root_rel else ("captures/" + capture_folder)).strip("/")
        if capture_folder else ""
    )

    probes = [
        ("base", ""),
        ("slash", "/"),
        ("root", root),
        ("root_rel", root_rel),
        ("captures", cap_rel),
        ("results", res_rel),
    ]
    if cap_folder_rel:
        probes.append(("capture_folder", cap_folder_rel))

    report: list[dict] = []
    for label, remote_dir in probes:
        try:
            ok, items_or_err = client.list_files(remote_dir)
            if ok and isinstance(items_or_err, list):
                report.append({
                    "probe": label,
                    "remote_dir": remote_dir,
                    "ok": True,
                    "count": len(items_or_err),
                    "items": items_or_err[:100],
                    "error": "",
                })
            else:
                report.append({
                    "probe": label,
                    "remote_dir": remote_dir,
                    "ok": False,
                    "count": 0,
                    "items": [],
                    "error": str(items_or_err),
                })
        except Exception as e:
            report.append({
                "probe": label,
                "remote_dir": remote_dir,
                "ok": False,
                "count": 0,
                "items": [],
                "error": f"{e.__class__.__name__}: {e}",
            })
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
                "roi": [float(r.get("x", 0)), float(r.get("y", 0)), float(r.get("w", 0)), float(r.get("h", 0))],
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
                x=float(pos[0]),
                y=float(pos[1]),
                w=float(pos[2]),
                h=float(pos[3]),
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
                rois.append(
                    dict(
                        name=str(n),
                        x=float(pos[0]),
                        y=float(pos[1]),
                        w=float(pos[2]),
                        h=float(pos[3]),
                        fmt=str(f),
                        pattern="",
                        max_scale=1.2,
                    )
                )
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
