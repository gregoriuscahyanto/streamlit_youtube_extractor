"""
OCR Extractor â€“ Streamlit App v4
Tab â˜  : Cloudflare R2-Verbindung, Prefix wÃ¤hlen, Datei-Browser
Tab ðŸŽ¬  : Video laden, Start/Ende, ROI-Auswahl
Tab ðŸ—º  : Track-Minimap Analyse â€“ 8-Punkte + Farberkennung
"""

import streamlit as st
import cv2
import numpy as np
import json
import tempfile
import io
import scipy.io as sio
import pandas as pd
from pathlib import Path
from datetime import datetime
from PIL import Image

from backend import (
    build_result_payload,
    build_mat_struct as backend_build_mat_struct,
    collect_r2_listing_debug,
    config_from_json_payload,
    config_from_mat_file,
    connect_r2_client,
    list_root_prefixes,
    load_r2_credentials,
    summarize_mat_file,
)
from storage import StorageManager
from track_analysis import (
    compare_minimap_to_reference,
    detect_moving_point,
    draw_comparison_overlay,
    extract_minimap_crop,
    project_point_with_homography,
)

# â”€â”€ Seitenkonfiguration â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
st.set_page_config(
    page_title="OCR Extractor",
    page_icon="OCR",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# â”€â”€ CSS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Syne:wght@400;600;800&display=swap');

html, body, [class*="css"] { font-family: 'Syne', sans-serif; }
.stApp { background: #0d0f14; color: #e8eaf0; overflow: auto; }
.block-container { padding-top: 1.1rem !important; max-width: 1500px; height: calc(100vh - 3.2rem); overflow: auto; }

.app-header { display:flex; align-items:baseline; gap:14px;
  margin-bottom:1rem; border-bottom:1px solid #1e2535; padding-bottom:.7rem; }
.app-header h1 { font-family:'Syne',sans-serif; font-weight:800; font-size:1.5rem;
  color:#e8eaf0; margin:0; letter-spacing:-.02em; }
.app-header .subtitle { font-family:'JetBrains Mono',monospace; font-size:.68rem;
  color:#4a90a4; letter-spacing:.1em; text-transform:uppercase; }

.status-badge { display:inline-block; padding:3px 10px; border-radius:3px;
  font-family:'JetBrains Mono',monospace; font-size:.7rem; font-weight:600;
  letter-spacing:.05em; text-transform:uppercase; }
.status-ok   { background:#0d2e1a; color:#3ddc84; border:1px solid #1a5c34; }
.status-warn { background:#2e1f0d; color:#ffa040; border:1px solid #5c3a1a; }
.status-info { background:#0d1e2e; color:#4a90a4; border:1px solid #1a3a5c; }

.section-card { background:#13161f; border:1px solid #1e2535; border-radius:6px;
  padding:.9rem 1.1rem; margin-bottom:.9rem; }
.section-card:empty { display:none !important; padding:0 !important; margin:0 !important; border:0 !important; }
.mat-selection-no-scroll {
  max-height: calc(100vh - 230px);
  overflow-y: auto;
  overflow-x: hidden;
}
.st-key-cloud_access_card,
.st-key-cloud_root_card,
.st-key-cloud_access_card [data-testid="stVerticalBlockBorderWrapper"],
.st-key-cloud_root_card [data-testid="stVerticalBlockBorderWrapper"] {
  background: #0b1524 !important;
  border-color: #2b4f77 !important;
}
.st-key-local_access_card,
.st-key-local_access_card [data-testid="stVerticalBlockBorderWrapper"] {
  background: #132114 !important;
  border-color: #376a3d !important;
}
.section-title { font-family:'JetBrains Mono',monospace; font-size:.68rem;
  letter-spacing:.15em; text-transform:uppercase; color:#4a90a4;
  margin-bottom:.6rem; border-bottom:1px solid #1e2535; padding-bottom:.35rem; }

.breadcrumb { font-family:'JetBrains Mono',monospace; font-size:.72rem;
  color:#4a90a4; background:#0a0c10; border:1px solid #1e2535;
  border-radius:4px; padding:5px 10px; margin-bottom:.7rem; }

.conn-dot { display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:6px; }
.conn-dot.ok  { background:#3ddc84; box-shadow:0 0 6px #3ddc8466; }
.conn-dot.off { background:#4a5060; }

.roi-tag { background:#1e2535; color:#4a90a4; padding:1px 6px; border-radius:3px;
  font-size:.65rem; font-family:'JetBrains Mono',monospace; white-space:nowrap; }
.roi-tag-track { background:#1e3520; color:#3ddc84; }
.roi-tag-sel   { background:#1a3a5c; color:#90c8e0; }

.frame-info { font-family:'JetBrains Mono',monospace; font-size:.7rem; color:#8892a4;
  padding:4px 8px; background:#0a0c10; border-radius:3px; display:inline-block; }

.metric-box { background:#0d0f14; border:1px solid #1e2535; border-radius:5px;
  padding:.6rem .8rem; text-align:center; }
.metric-val { font-family:'JetBrains Mono',monospace; font-size:1.3rem;
  font-weight:700; color:#4a90a4; }
.metric-lbl { font-family:'JetBrains Mono',monospace; font-size:.62rem;
  color:#4a5060; text-transform:uppercase; letter-spacing:.1em; margin-top:2px; }

.stButton>button { font-family:'JetBrains Mono',monospace !important;
  font-size:.75rem !important; font-weight:600 !important;
  letter-spacing:.04em !important; border-radius:4px !important; }
.stButton>button[kind="primary"] { background:#4a90a4 !important;
  border-color:#4a90a4 !important; color:#0d0f14 !important; }

hr { border-color:#1e2535 !important; }

/* selected row highlight in dataframe */
.stDataFrame [aria-selected="true"] {
  background-color: rgba(74, 144, 164, 0.30) !important;
}
</style>
""", unsafe_allow_html=True)

# â”€â”€ ROI / Format Listen â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
ROI_NAMES = [
    "_","t_s","v_Fzg_kmph","v_Fzg_mph","numgear_GET",
    "a_G","a_mps2","a_x_G","a_x_pos_G","a_x_neg_G","a_x_mps",
    "a_y_G","a_y_pos_G","a_y_neg_G","a_y_mps",
    "P_kW","M_Nm","n_mot_Upmin",
    "M_VL_Nm","M_VR_Nm","M_HL_Nm","M_HR_Nm",
    "stellung_gaspedal_proz","stellung_bremspedal_proz","track_minimap",
]
FMT_OPTIONS = [
    "any","time_m:ss","time_m:ss.S","time_m:ss.SS","time_m:ss.SSS",
    "time_m:ss.SSSS","time_m:ss.SSSSSS","time_mm:ss","time_mm:ss.S",
    "time_mm:ss.SS","time_mm:ss.SSS","time_mm:ss.SSSS","time_mm:ss.SSSSSS",
    "time_hh:mm:ss","time_hh:mm:ss.S","time_hh:mm:ss.SS","time_hh:mm:ss.SSS",
    "time_hh:mm:ss.SSSS","time_hh:mm:ss.SSSSSS",
    "integer","int_1","int_2","int_3","int_4","int_min2_max3","int_min3_max4",
    "float","alnum","custom",
]
MAT_OVERVIEW_COLCFG = {
    "mat_datei": st.column_config.TextColumn("mat_datei", width="medium"),
    "remote_key": st.column_config.TextColumn("remote_key", width="large"),
    "audio_video_vorhanden": st.column_config.TextColumn("Audio+Video vorhanden", width="small"),
    "roi_ausgewaehlt": st.column_config.TextColumn("ROI", width="small"),
    "track_ausgewaehlt": st.column_config.TextColumn("Track", width="small"),
    "anfang_ende_ausgewaehlt": st.column_config.TextColumn("Start/Ende", width="small"),
    "ocr_durchgefuehrt": st.column_config.TextColumn("OCR", width="small"),
    "ocr_vollstaendig": st.column_config.TextColumn("OCR vollstaendig", width="small"),
    "audioanalyse_spektrogramm": st.column_config.TextColumn("Audio/Spektrogramm", width="small"),
    "validierung": st.column_config.TextColumn("Validierung", width="small"),
    "fehler": st.column_config.TextColumn("Fehler", width="large"),
}
MAT_TABLE_HEIGHT = 430

# â”€â”€ Session-State â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def init_state():
    _acc, _key, _sec, _bkt = load_r2_credentials(streamlit_secrets=st.secrets)

    defs = dict(
        # R2
        r2_account_id=_acc,
        r2_access_key_id=_key,
        r2_secret_access_key=_sec,
        r2_bucket=_bkt,
        r2_connected=False, r2_client=None,
        r2_prefix="",
        r2_prefix_options=[],
        r2_listing_debug=[],
        auto_connect_attempted=False,
        auto_connect_used=False,
        # Local DB
        local_base_path=str(Path.cwd()),
        local_base_path_input=str(Path.cwd()),
        local_connected=False,
        local_root="",
        local_root_options=[],
        mat_files=[],
        mat_scan_prefix=None,
        mat_selected_key="",
        mat_selected_summary=None,
        mat_overview_rows=[],
        mat_auto_updated_prefix=None,
        jump_to_mat_tab=False,
        mat_update_running=False,
        mat_update_idx=0,
        mat_update_total=0,
        mat_update_keys=[],
        mat_run_state="idle",
        # Datei-Browser
        fb_path="", fb_items=[], fb_selected=None,
        # Aufnahme
        capture_folder="",
        # Video / ROI
        video_path=None, video_name="",
        vid_duration=0.0, vid_fps=25.0, vid_width=0, vid_height=0,
        t_start=0.0, t_end=0.0, t_current=0.0,
        rois=[], selected_roi=None,
        # Track
        ref_track_img=None, ref_track_pts=None, minimap_pts=None,
        track_comparison=None, moving_pt_history=[],
        moving_pt_color_range=dict(h_lo=0,h_hi=30,s_lo=150,s_hi=255,v_lo=150,v_hi=255),
        # Status
        status_msg="Bereit", status_type="info",
    )
    for k, v in defs.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()

# â”€â”€ Hilfsfunktionen â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@st.cache_data(show_spinner=False)
def get_frame(video_path: str, time_s: float):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened(): return None
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(time_s * fps))
    ret, frame = cap.read()
    cap.release()
    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB) if ret else None

@st.cache_data(show_spinner=False)
def get_video_info(video_path: str):
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    info = dict(fps=fps,
                width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                frames=int(cap.get(cv2.CAP_PROP_FRAME_COUNT)))
    info["duration"] = info["frames"] / fps
    cap.release()
    return info

def set_status(msg, kind="info"):
    st.session_state.status_msg  = msg
    st.session_state.status_type = kind


def _list_local_root_options(base_path: str) -> list[str]:
    try:
        base = Path(base_path).expanduser().resolve()
    except Exception:
        return [""]
    if not base.exists() or not base.is_dir():
        return [""]
    opts = [""]
    try:
        for p in sorted(base.iterdir(), key=lambda x: x.name.lower()):
            if p.is_dir():
                opts.append(p.name)
    except Exception:
        pass
    return opts


def _local_effective_root() -> str:
    base = Path(st.session_state.local_base_path).expanduser()
    root = st.session_state.local_root.strip("/\\")
    return str((base / root).resolve() if root else base.resolve())


def _pick_local_folder_dialog(initial_dir: str = "") -> tuple[bool, str]:
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        start_dir = initial_dir or str(Path.cwd())
        selected = filedialog.askdirectory(initialdir=start_dir)
        root.destroy()
        if selected:
            return True, selected
        return False, ""
    except Exception as e:
        return False, str(e)


def _has_valid_8_points(points):
    if not isinstance(points, list) or len(points) != 8:
        return False
    for p in points:
        if not isinstance(p, (list, tuple)) or len(p) != 2:
            return False
        try:
            float(p[0]); float(p[1])
        except Exception:
            return False
    return True


def _clamp_roi_to_video(x, y, w, h, vid_w, vid_h):
    x = max(0.0, float(x))
    y = max(0.0, float(y))
    max_w = max(1.0, float(vid_w) - x) if vid_w else max(1.0, float(w))
    max_h = max(1.0, float(vid_h) - y) if vid_h else max(1.0, float(h))
    w = min(max(1.0, float(w)), max_w)
    h = min(max(1.0, float(h)), max_h)
    return x, y, w, h


def _try_auto_connect_once():
    if st.session_state.r2_connected or st.session_state.auto_connect_attempted:
        return

    st.session_state.auto_connect_attempted = True
    acc = st.session_state.r2_account_id.strip()
    key = st.session_state.r2_access_key_id.strip()
    sec = st.session_state.r2_secret_access_key.strip()
    bkt = st.session_state.r2_bucket.strip()
    if not all([acc, key, sec, bkt]):
        return

    ok, msg, client = connect_r2_client(acc, key, sec, bkt)
    if not ok or client is None:
        set_status(f"Auto-Connect fehlgeschlagen: {msg}", "warn")
        return

    st.session_state.r2_connected = True
    st.session_state.r2_client = client
    opts = list_root_prefixes(client)
    st.session_state.r2_prefix_options = opts
    real = [o for o in opts if o]
    if len(real) == 1:
        st.session_state.r2_prefix = real[0]
        st.session_state.fb_path = real[0]
        st.session_state.fb_items = r2_list(real[0])
    else:
        st.session_state.fb_path = ""
        st.session_state.fb_items = r2_list("")
    st.session_state.auto_connect_used = True
    set_status("Auto-Connect erfolgreich.", "ok")

def _file_icon(name):
    ext = Path(name).suffix.lower()
    return {
        ".mp4": "[VID]", ".mov": "[VID]", ".avi": "[VID]", ".mkv": "[VID]",
        ".mat": "[MAT]", ".json": "[JSON]", ".wav": "[AUD]", ".mp3": "[AUD]",
        ".png": "[IMG]", ".jpg": "[IMG]", ".jpeg": "[IMG]",
        ".txt": "[TXT]", ".md": "[TXT]",
    }.get(ext, "[FILE]")

def draw_rois(frame, rois, sel, vid_w, vid_h):
    img = frame.copy()
    dh, dw = img.shape[:2]
    sx = dw/vid_w if vid_w else 1.0
    sy = dh/vid_h if vid_h else 1.0
    for i, r in enumerate(rois):
        x,y,w,h = int(r["x"]*sx),int(r["y"]*sy),int(r["w"]*sx),int(r["h"]*sy)
        is_track = r["name"]=="track_minimap"
        color = (74,200,150) if is_track else ((90,180,255) if i==sel else (255,80,80))
        cv2.rectangle(img,(x,y),(x+w,y+h),color,2)
        cv2.putText(img,r["name"],(x+3,y+14),cv2.FONT_HERSHEY_SIMPLEX,.42,color,1,cv2.LINE_AA)
    return img

def build_result_json():
    return build_result_payload(
        t_start=st.session_state.t_start,
        t_end=st.session_state.t_end,
        rois=st.session_state.rois,
        video={
            "width": st.session_state.vid_width,
            "height": st.session_state.vid_height,
            "fps": st.session_state.vid_fps,
            "duration": st.session_state.vid_duration,
        },
        track={
            "ref_pts": st.session_state.ref_track_pts,
            "minimap_pts": st.session_state.minimap_pts,
            "moving_pt_color_range": st.session_state.moving_pt_color_range,
        },
    )

def build_mat_struct(result):
    return backend_build_mat_struct(result, video_name=st.session_state.video_name)

def load_json_config(data):
    cfg = config_from_json_payload(data, vid_duration=st.session_state.vid_duration)
    st.session_state.t_start = cfg.get("t_start", st.session_state.t_start)
    st.session_state.t_end = cfg.get("t_end", st.session_state.t_end)
    st.session_state.rois = cfg.get("rois", [])
    if cfg.get("ref_track_pts"):
        st.session_state.ref_track_pts = cfg["ref_track_pts"]
    if cfg.get("minimap_pts"):
        st.session_state.minimap_pts = cfg["minimap_pts"]
    if cfg.get("moving_pt_color_range"):
        st.session_state.moving_pt_color_range = cfg["moving_pt_color_range"]

def _apply_video(local_path, display_name):
    info = get_video_info(local_path)
    st.session_state.update(
        video_path=local_path, video_name=display_name,
        vid_fps=info["fps"], vid_width=info["width"],
        vid_height=info["height"], vid_duration=info["duration"],
        t_start=0.0, t_end=info["duration"], t_current=0.0, rois=[])
    if not st.session_state.capture_folder:
        st.session_state.capture_folder = Path(display_name).stem
    get_frame.clear(); get_video_info.clear()
    set_status(f"Video geladen: {display_name}", "ok")

def r2_list(prefix):
    """Lists objects under prefix. Returns [{"name", "path", "is_dir"}]."""
    if not st.session_state.r2_connected: return []
    client = st.session_state.r2_client
    ok, items = client.list_files(prefix)
    if not ok or not isinstance(items, list): return []
    result = []
    base = prefix.rstrip("/")
    for item in items:
        is_dir = item.endswith("/")
        name   = item.rstrip("/")
        if not name: continue
        full_path = (base + "/" + name) if base else name
        result.append({"name": name, "path": full_path, "is_dir": is_dir})
    result.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
    return result

def get_root_prefixes():
    if not st.session_state.r2_connected: return [""]
    return list_root_prefixes(st.session_state.r2_client)


def _results_dir_key() -> str:
    pfx = st.session_state.r2_prefix.strip("/")
    return f"{pfx}/results" if pfx else "results"


def _refresh_mat_files():
    if not st.session_state.r2_connected or st.session_state.r2_client is None:
        st.session_state.mat_files = []
        return
    res_key = _results_dir_key()
    ok, items = st.session_state.r2_client.list_files(res_key)
    if not ok or not isinstance(items, list):
        st.session_state.mat_files = []
        return
    mats = []
    for name in items:
        if not name.endswith("/"):
            full_key = f"{res_key}/{name}" if res_key else name
            if full_key.lower().endswith(".mat"):
                mats.append(full_key.strip("/"))
    mats.sort(reverse=True)
    st.session_state.mat_files = mats
    if st.session_state.mat_selected_key not in mats:
        st.session_state.mat_selected_key = mats[0] if mats else ""
        st.session_state.mat_selected_summary = None
    st.session_state.mat_scan_prefix = st.session_state.r2_prefix


def _mat_capture_guess_from_key(remote_key: str) -> str:
    filename = Path(remote_key).name
    if filename.startswith("results_") and filename.lower().endswith(".mat"):
        return filename[len("results_"):-4]
    return ""


def _download_mat_to_temp(remote_key: str):
    client = st.session_state.r2_client
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mat")
    tmp.close()
    ok, msg = client.download_file(remote_key, tmp.name)
    if not ok:
        return False, msg, None
    return True, "", tmp.name


def _get_mat_summary_from_r2(remote_key: str):
    ok, msg, tmp_path = _download_mat_to_temp(remote_key)
    if not ok or not tmp_path:
        return {"mat_file": Path(remote_key).name, "error": f"Download: {msg}"}
    summary = summarize_mat_file(tmp_path)
    summary["mat_file"] = Path(remote_key).name
    summary["remote_key"] = remote_key
    if not summary.get("capture_folder"):
        summary["capture_folder"] = _mat_capture_guess_from_key(remote_key)
    capture_folder = summary.get("capture_folder", "")
    summary["video_file_exists"] = None
    summary["audio_file_exists"] = None
    if capture_folder and st.session_state.r2_client is not None:
        pfx = st.session_state.r2_prefix.strip("/")
        cap_dir = f"{pfx}/captures/{capture_folder}" if pfx else f"captures/{capture_folder}"
        ok_list, items = st.session_state.r2_client.list_files(cap_dir)
        if ok_list and isinstance(items, list):
            files = [n for n in items if not n.endswith("/")]
            lower_files = [n.lower() for n in files]
            summary["video_file_exists"] = any(
                n.endswith((".mp4", ".mov", ".avi", ".mkv")) for n in lower_files
            )
            summary["audio_file_exists"] = any(
                n.endswith((".wav", ".mp3", ".m4a", ".aac")) for n in lower_files
            )
    return summary


def _analyze_mat_from_r2(remote_key: str):
    summary = _get_mat_summary_from_r2(remote_key)
    if summary.get("error"):
        set_status(f"MAT-Analysefehler: {summary['error']}", "warn")
    st.session_state.mat_selected_summary = summary


def _jn(value) -> str:
    return "Ja" if bool(value) else "Nein"


def _summary_to_overview_row(summary: dict) -> dict:
    return {
        "mat_datei": summary.get("mat_file", ""),
        "remote_key": summary.get("remote_key", ""),
        "audio_video_vorhanden": _jn(
            bool(summary.get("video_file_exists")) and bool(summary.get("audio_file_exists"))
        ),
        "roi_ausgewaehlt": _jn(summary.get("roi_selected")),
        "track_ausgewaehlt": _jn(summary.get("track_selected")),
        "anfang_ende_ausgewaehlt": _jn(summary.get("start_end_selected")),
        "ocr_durchgefuehrt": _jn(summary.get("ocr_done")),
        "ocr_vollstaendig": _jn(summary.get("ocr_complete")),
        "audioanalyse_spektrogramm": _jn(summary.get("audio_spectrogram_done")),
        "validierung": _jn(summary.get("validation_done")),
        "fehler": summary.get("error", ""),
    }


def _placeholder_overview_row(remote_key: str) -> dict:
    return {
        "mat_datei": Path(remote_key).name,
        "remote_key": remote_key,
        "audio_video_vorhanden": "...",
        "roi_ausgewaehlt": "...",
        "track_ausgewaehlt": "...",
        "anfang_ende_ausgewaehlt": "...",
        "ocr_durchgefuehrt": "...",
        "ocr_vollstaendig": "...",
        "audioanalyse_spektrogramm": "...",
        "validierung": "...",
        "fehler": "",
    }


def _build_mat_overview_rows(remote_keys: list[str]) -> list[dict]:
    rows = []
    for key in remote_keys:
        summary = _get_mat_summary_from_r2(key)
        rows.append(_summary_to_overview_row(summary))
    return rows


def _start_mat_update(remote_keys: list[str]):
    st.session_state.mat_update_keys = list(remote_keys)
    st.session_state.mat_update_total = len(remote_keys)
    st.session_state.mat_update_idx = 0
    st.session_state.mat_update_running = len(remote_keys) > 0
    st.session_state.mat_run_state = "running" if len(remote_keys) > 0 else "idle"
    st.session_state.mat_overview_rows = [_placeholder_overview_row(k) for k in remote_keys]


def _step_mat_update_once():
    if not st.session_state.mat_update_running:
        return
    idx = st.session_state.mat_update_idx
    total = st.session_state.mat_update_total
    keys = st.session_state.mat_update_keys
    if idx >= total:
        st.session_state.mat_update_running = False
        st.session_state.mat_run_state = "idle"
        return

    key = keys[idx]
    summary = _get_mat_summary_from_r2(key)
    st.session_state.mat_overview_rows[idx] = _summary_to_overview_row(summary)
    st.session_state.mat_update_idx = idx + 1

    if st.session_state.mat_update_idx >= total:
        st.session_state.mat_update_running = False
        st.session_state.mat_run_state = "idle"
        set_status(f"Analyse fuer {total} MAT-Dateien abgeschlossen.", "ok")


def _status_cell_style(value):
    if str(value) == "Ja":
        return "background-color: #0f3d1f; color: #e8ffe8;"
    if str(value) == "Nein":
        return "background-color: #4a1d1d; color: #ffe8e8;"
    return ""


def _style_overview_dataframe(df: pd.DataFrame):
    status_cols = [
        "audio_video_vorhanden",
        "roi_ausgewaehlt",
        "track_ausgewaehlt",
        "anfang_ende_ausgewaehlt",
        "ocr_durchgefuehrt",
        "ocr_vollstaendig",
        "audioanalyse_spektrogramm",
        "validierung",
    ]
    styler = df.style
    if hasattr(styler, "map"):
        return styler.map(_status_cell_style, subset=status_cols)
    if hasattr(styler, "applymap"):
        return styler.applymap(_status_cell_style, subset=status_cols)
    return df


def _update_all_mat_overview_rows(remote_keys: list[str], live_table=None, progress_slot=None):
    """
    Backward-compatible synchronous updater for MAT overview rows.
    """
    _start_mat_update(remote_keys)
    total = len(remote_keys)
    progress = progress_slot.progress(0, text=f"0/{total} MAT-Dateien analysiert") if (total > 0 and progress_slot is not None) else None

    while st.session_state.mat_update_running:
        _step_mat_update_once()
        done = int(st.session_state.mat_update_idx or 0)
        if live_table is not None:
            live_table.dataframe(
                _style_overview_dataframe(pd.DataFrame(st.session_state.mat_overview_rows)),
                width="stretch",
                hide_index=True,
                height=MAT_TABLE_HEIGHT,
                column_config=MAT_OVERVIEW_COLCFG,
            )
        if progress is not None and total > 0:
            progress.progress(min(1.0, done / total), text=f"{done}/{total} MAT-Dateien analysiert")

    if progress is not None:
        progress.empty()


def _try_load_video_for_capture_folder(capture_folder: str) -> bool:
    if not capture_folder:
        return False
    client = st.session_state.r2_client
    if client is None:
        return False
    pfx = st.session_state.r2_prefix.strip("/")
    cap_dir = f"{pfx}/captures/{capture_folder}" if pfx else f"captures/{capture_folder}"
    ok_list, items = client.list_files(cap_dir)
    if not ok_list or not isinstance(items, list):
        return False
    preferred_name = f"{capture_folder}.mp4".lower()
    if preferred_name in [n.lower() for n in items if not n.endswith("/")]:
        _load_video_from_r2(f"{cap_dir}/{capture_folder}.mp4".strip("/"))
        return True
    for name in items:
        if name.lower().endswith((".mp4", ".mov", ".avi", ".mkv")) and not name.endswith("/"):
            _load_video_from_r2(f"{cap_dir}/{name}".strip("/"))
            return True
    return False

def _load_video_from_r2(remote_key):
    client = st.session_state.r2_client
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=Path(remote_key).suffix)
    tmp.close()
    with st.spinner(f"Lade {Path(remote_key).name} ..."):
        ok, msg = client.download_file(remote_key, tmp.name)
    if ok: _apply_video(tmp.name, Path(remote_key).name)
    else:  set_status(f"Download: {msg}", "warn")

def _load_json_from_r2(remote_key):
    client = st.session_state.r2_client
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json"); tmp.close()
    ok, msg = client.download_file(remote_key, tmp.name)
    if ok:
        try:
            with open(tmp.name) as f: load_json_config(json.load(f))
            set_status("JSON geladen OK", "ok")
        except Exception as e: set_status(f"JSON-Parse: {e}", "warn")
    else: set_status(f"JSON-Download: {msg}", "warn")

def _load_mat_from_r2(remote_key):
    client = st.session_state.r2_client
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mat"); tmp.close()
    ok, msg = client.download_file(remote_key, tmp.name)
    if not ok: set_status(f"MAT-Download: {msg}", "warn"); return None
    try:
        cfg = config_from_mat_file(tmp.name, vid_duration=st.session_state.vid_duration)
        st.session_state.t_start = cfg.get("t_start", st.session_state.t_start)
        st.session_state.t_end = cfg.get("t_end", st.session_state.t_end)
        st.session_state.rois = cfg.get("rois", st.session_state.rois)
        if cfg.get("ref_track_pts"):
            st.session_state.ref_track_pts = cfg["ref_track_pts"]
        if cfg.get("minimap_pts"):
            st.session_state.minimap_pts = cfg["minimap_pts"]
        set_status("MAT geladen OK","ok")
        return tmp.name
    except Exception as e: set_status(f"MAT-Parse: {e}","warn")
    return None

def _load_ref_from_r2(remote_key):
    client = st.session_state.r2_client
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=Path(remote_key).suffix)
    tmp.close()
    ok, msg = client.download_file(remote_key, tmp.name)
    if ok:
        img = np.array(Image.open(tmp.name).convert("RGB"))
        st.session_state.ref_track_img = img
        set_status("Referenz-Track geladen OK","ok")
    else: set_status(f"Ref-Download: {msg}","warn")


_try_auto_connect_once()

# â”€â”€ Header + Status â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
st.markdown("""
<div class="app-header">
  <h1>OCR Extractor</h1>
  <span class="subtitle">R2 | ROI | TRACK</span>
</div>""", unsafe_allow_html=True)

stype = st.session_state.status_type
_pfx_display = st.session_state.r2_prefix or ""
_pfx_badge = (f'<span class="status-badge status-ok" style="margin-left:8px">'
              f'PREFIX: {_pfx_display.upper()}</span>'
              if st.session_state.r2_connected and _pfx_display
              else "")
st.markdown(
    f'<span class="status-badge status-{stype}">{st.session_state.status_msg}</span>' + _pfx_badge,
    unsafe_allow_html=True)

# â”€â”€ TABS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
tab_setup, tab_mat, tab_roi, tab_track = st.tabs(
    ["Cloud Connection & Root", "MAT Selection", "ROI Setup", "Track Analysis"]
)

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# TAB â˜ï¸  â€“ CLOUD & DATEIEN
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
with tab_setup:
    cloud_ok = bool(st.session_state.r2_connected)
    local_ok = bool(st.session_state.local_connected)

    col_cloud, col_local = st.columns(2, gap="large")

    with col_cloud:
        st.markdown('<div class="section-card" style="background:#0b1524;border-color:#234465;">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">Cloud DB | Cloudflare R2</div>', unsafe_allow_html=True)
        # Card 1: Status
        st.markdown(
            f"""
            <div style="background:#0b1524;border:1px solid #2b4f77;border-radius:10px;padding:.8rem 1rem;margin-bottom:.7rem;">
              <div style="font-family:'JetBrains Mono',monospace;font-size:.66rem;color:#8aa8c7;text-transform:uppercase;letter-spacing:.08em;">Cloud DB Status</div>
              <div style="display:flex;align-items:center;gap:10px;margin-top:6px;">
                <span class="conn-dot {'ok' if cloud_ok else 'off'}" style="width:13px;height:13px;"></span>
                <span style="font-family:'Syne',sans-serif;font-size:1.03rem;font-weight:700;color:{'#3ddc84' if cloud_ok else '#a0a7b4'};">
                  {'Verbunden' if cloud_ok else 'Nicht verbunden'}
                </span>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # Card 2: Credentials + connect
        with st.container(border=True, key="cloud_access_card"):
            st.markdown(
                "<div style=\"font-family:JetBrains Mono,monospace;font-size:.66rem;color:#8aa8c7;text-transform:uppercase;letter-spacing:.08em;margin-bottom:.45rem;\">Cloud Zugang</div>",
                unsafe_allow_html=True,
            )
            r2_account = st.text_input(
                "Account ID",
                key="r2_account_id",
                help="Cloudflare Dashboard -> R2 -> Account ID",
            )
            r2_key = st.text_input(
                "Access Key ID",
                key="r2_access_key_id",
                help="R2 -> Manage API Tokens -> Create API Token",
            )
            r2_secret = st.text_input(
                "Secret Access Key",
                key="r2_secret_access_key",
                type="password",
            )
            r2_bucket = st.text_input(
                "Bucket Name",
                key="r2_bucket",
                placeholder="mein-bucket",
            )

            if st.button("Cloud DB verbinden", type="primary", use_container_width=True, key="r2_connect_btn"):
                if r2_account and r2_key and r2_secret and r2_bucket:
                    with st.spinner("Verbinde Cloud DB ..."):
                        _ok, _msg, _client = connect_r2_client(r2_account, r2_key, r2_secret, r2_bucket)
                    if _ok:
                        st.session_state.r2_connected = True
                        st.session_state.r2_client = _client
                        st.session_state.r2_prefix_options = list_root_prefixes(_client)
                        st.session_state.r2_prefix = ""
                        st.session_state.mat_scan_prefix = None
                        set_status("Cloud DB verbunden.", "ok")
                    else:
                        st.session_state.r2_connected = False
                        set_status(f"Cloud DB Verbindung fehlgeschlagen: {_msg}", "warn")
                    st.rerun()
                else:
                    set_status("Bitte alle Cloud-DB Felder ausfuellen.", "warn")
                    st.rerun()

        # Card 3: Root + refresh
        with st.container(border=True, key="cloud_root_card"):
            st.markdown(
                "<div style=\"font-family:JetBrains Mono,monospace;font-size:.66rem;color:#8aa8c7;text-transform:uppercase;letter-spacing:.08em;margin-bottom:.45rem;\">Cloud Root</div>",
                unsafe_allow_html=True,
            )
            if st.session_state.r2_connected:
                opts = st.session_state.r2_prefix_options or [""]
                cur = st.session_state.r2_prefix
                idx = opts.index(cur) if cur in opts else 0
                chosen = st.selectbox(
                    "Cloud Prefix",
                    opts,
                    index=idx,
                    format_func=lambda x: x or "(Bucket-Root)",
                    label_visibility="collapsed",
                    key="root_dd",
                )
                if chosen != st.session_state.r2_prefix:
                    st.session_state.r2_prefix = chosen
                    st.session_state.mat_scan_prefix = None
                    set_status(f"Cloud Root: {chosen or '(root)'}", "ok")
                if st.button("Cloud Liste aktualisieren", use_container_width=True, key="refresh_root"):
                    st.session_state.r2_prefix_options = get_root_prefixes()
                    st.rerun()
            else:
                st.caption("Erst Cloud DB verbinden.")
        st.markdown('</div>', unsafe_allow_html=True)

    with col_local:
        st.markdown('<div class="section-card" style="background:#132114;border-color:#305b34;">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">Lokale DB</div>', unsafe_allow_html=True)
        # Card 1: Status
        st.markdown(
            f"""
            <div style="background:#132114;border:1px solid #376a3d;border-radius:10px;padding:.8rem 1rem;margin-bottom:.7rem;">
              <div style="font-family:'JetBrains Mono',monospace;font-size:.66rem;color:#9fbe9f;text-transform:uppercase;letter-spacing:.08em;">Lokale DB Status</div>
              <div style="display:flex;align-items:center;gap:10px;margin-top:6px;">
                <span class="conn-dot {'ok' if local_ok else 'off'}" style="width:13px;height:13px;"></span>
                <span style="font-family:'Syne',sans-serif;font-size:1.03rem;font-weight:700;color:{'#3ddc84' if local_ok else '#a0a7b4'};">
                  {'Verbunden' if local_ok else 'Nicht verbunden'}
                </span>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        # Card 2: Notice + picker + path
        with st.container(border=True, key="local_access_card"):
            st.markdown(
                "<div style=\"font-family:JetBrains Mono,monospace;font-size:.66rem;color:#9fbe9f;text-transform:uppercase;letter-spacing:.08em;margin-bottom:.45rem;\">Lokaler Zugriff</div>",
                unsafe_allow_html=True,
            )
            st.markdown(
                """
                <div style="background:#17301a;border:1px solid #2b5a31;border-radius:8px;padding:.55rem .7rem;
                     font-family:'JetBrains Mono',monospace;font-size:.68rem;color:#b8ddb9;line-height:1.5;margin-bottom:.6rem;">
                Hinweis: Nur auf localhost nutzbar. Der gewaehlte Ordner muss einen Unterordner <b>captures</b> enthalten.
                </div>
                """,
                unsafe_allow_html=True,
            )

            if st.button("Ordner waehlen (lokal)", use_container_width=True, key="local_pick_btn"):
                ok_pick, picked = _pick_local_folder_dialog(st.session_state.local_base_path_input)
                if ok_pick and picked:
                    st.session_state.local_base_path_input = picked
                    lp = Path(picked).expanduser().resolve()
                    captures_dir = lp / "captures"
                    if captures_dir.exists() and captures_dir.is_dir():
                        st.session_state.local_connected = True
                        st.session_state.local_base_path = str(lp)
                        st.session_state.local_root = ""
                        set_status(f"Lokale DB verbunden: {lp}", "ok")
                    else:
                        st.session_state.local_connected = False
                        set_status("Lokale DB nicht verbunden: Unterordner 'captures' fehlt.", "warn")
                    st.rerun()
                elif picked:
                    set_status(f"Ordnerdialog nicht verfuegbar: {picked}", "warn")
            st.markdown(
                f'<div class="breadcrumb">Lokaler Basispfad: {st.session_state.local_base_path if st.session_state.local_connected else "(noch nicht gesetzt)"}</div>',
                unsafe_allow_html=True,
            )
        st.markdown('</div>', unsafe_allow_html=True)


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# TAB ðŸ§® â€“ MAT-AUSWAHL
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
with tab_mat:
    st.markdown('<div class="section-card mat-selection-no-scroll">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">MAT-Auswahl und Analyse</div>', unsafe_allow_html=True)

    connected = st.session_state.r2_connected and st.session_state.r2_client is not None
    if connected and st.session_state.mat_scan_prefix != st.session_state.r2_prefix:
        _refresh_mat_files()
        st.session_state.mat_auto_updated_prefix = None

    mats = st.session_state.mat_files if connected else []
    running = bool(st.session_state.mat_update_running)

    c1, c2 = st.columns(2)
    update_clicked = c1.button(
        "Update",
        use_container_width=True,
        key="mat_update_tab",
        disabled=not connected,
    )
    can_load = connected and bool(st.session_state.mat_selected_key) and not running
    load_clicked = c2.button(
        "MAT + Video laden",
        type="primary",
        use_container_width=True,
        key="mat_load_all_tab",
        disabled=not can_load,
    )

    # Progress appears below the buttons.
    progress_slot = st.empty()
    table_slot = st.empty()

    if update_clicked:
        if running:
            st.session_state.mat_update_running = False
            st.session_state.mat_run_state = "idle"
            set_status("Analyse abgebrochen.", "warn")
        else:
            _refresh_mat_files()
            mats = st.session_state.mat_files
            st.session_state.mat_auto_updated_prefix = st.session_state.r2_prefix
            if mats:
                st.session_state.mat_run_state = "running"
                set_status(f"Analyse gestartet ({len(mats)} MAT-Dateien).", "info")
                _update_all_mat_overview_rows(mats, live_table=table_slot, progress_slot=progress_slot)
                st.session_state.mat_run_state = "idle"
                set_status(f"Analyse fuer {len(mats)} MAT-Dateien abgeschlossen.", "ok")
            else:
                st.session_state.mat_run_state = "idle"
                set_status("Keine MAT-Dateien gefunden.", "warn")

    if connected and mats and st.session_state.mat_auto_updated_prefix != st.session_state.r2_prefix and not running:
        st.session_state.mat_auto_updated_prefix = st.session_state.r2_prefix
        st.session_state.mat_run_state = "running"
        _update_all_mat_overview_rows(mats, live_table=table_slot, progress_slot=progress_slot)
        st.session_state.mat_run_state = "idle"
        set_status(f"Analyse fuer {len(mats)} MAT-Dateien abgeschlossen.", "ok")

    if not connected:
        st.caption("Erst in Tab 'Verbindung & Root' verbinden und Projektroot wählen.")
    if st.session_state.mat_overview_rows:
        df_overview = pd.DataFrame(st.session_state.mat_overview_rows)
        is_running_now = bool(st.session_state.mat_update_running)
        colorize_cells = not is_running_now
        styled_df = _style_overview_dataframe(df_overview) if colorize_cells else df_overview
        allow_select = not is_running_now
        if allow_select:
            try:
                event = table_slot.dataframe(
                    styled_df,
                    width="stretch",
                    hide_index=True,
                    height=MAT_TABLE_HEIGHT,
                    column_config=MAT_OVERVIEW_COLCFG,
                    on_select="rerun",
                    selection_mode="single-row",
                )
            except Exception:
                event = table_slot.dataframe(
                    df_overview,
                    width="stretch",
                    hide_index=True,
                    height=MAT_TABLE_HEIGHT,
                    column_config=MAT_OVERVIEW_COLCFG,
                    on_select="rerun",
                    selection_mode="single-row",
                )
        else:
            table_slot.dataframe(
                styled_df,
                width="stretch",
                hide_index=True,
                height=MAT_TABLE_HEIGHT,
                column_config=MAT_OVERVIEW_COLCFG,
            )
            event = None
        if isinstance(event, dict):
            sel_rows = event.get("selection", {}).get("rows", [])
        else:
            sel = getattr(event, "selection", None)
            sel_rows = getattr(sel, "rows", []) if sel is not None else []
        if sel_rows:
            selected_idx = sel_rows[0]
            if 0 <= selected_idx < len(st.session_state.mat_overview_rows):
                selected_key = st.session_state.mat_overview_rows[selected_idx].get("remote_key", "")
                if selected_key and selected_key != st.session_state.mat_selected_key:
                    st.session_state.mat_selected_key = selected_key
                    st.session_state.mat_selected_summary = _get_mat_summary_from_r2(selected_key)
    else:
        table_slot.empty()
        st.caption("Noch keine MAT analysiert.")

    if load_clicked:
        selected = st.session_state.mat_selected_key
        with st.spinner("Lade MAT + Video ..."):
            _analyze_mat_from_r2(selected)
            _load_mat_from_r2(selected)
            summary = st.session_state.mat_selected_summary or {}
            capture_folder = summary.get("capture_folder") or _mat_capture_guess_from_key(selected)
            video_ok = _try_load_video_for_capture_folder(capture_folder)
            if video_ok:
                st.session_state.capture_folder = capture_folder
            else:
                set_status("MAT geladen, aber kein passendes Video gefunden.", "warn")

    st.markdown('</div>', unsafe_allow_html=True)


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# TAB ðŸŽ¬ â€“ ROI-SETUP
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
with tab_roi:
    if not st.session_state.video_path:
        st.markdown("""
        <div style="text-align:center;padding:3rem 2rem;color:#4a5060;">
          <div style="font-size:2.5rem;margin-bottom:.8rem">VIDEO</div>
          <div style="font-family:'Syne',sans-serif;font-size:1rem;font-weight:600">
            Kein Video geladen</div>
          <div style="font-family:'JetBrains Mono',monospace;font-size:.72rem;
               margin-top:.4rem;color:#2e3545">
            -> Tab CLOUD oeffnen -> Video laden oder von R2 laden</div>
        </div>""", unsafe_allow_html=True)
    else:
        dur=st.session_state.vid_duration; fps=st.session_state.vid_fps
        fw=st.session_state.vid_width;    fh=st.session_state.vid_height
        tot=max(1,int(dur*fps))

        col_v, col_r = st.columns([3,1], gap="medium")
        with col_v:
            st.markdown('<div class="section-card">',unsafe_allow_html=True)
            st.markdown('<div class="section-title">Zeitbereich</div>',unsafe_allow_html=True)
            c1,c2=st.columns([5,1])
            t_start=c1.slider("Start [s]",0.0,float(dur),float(st.session_state.t_start),
                               step=round(1/fps,4),format="%.2f s",key="sl_start")
            c2.markdown(f'<div class="frame-info" style="margin-top:26px">F{int(t_start*fps)+1}/{tot}</div>',
                        unsafe_allow_html=True)
            c1,c2=st.columns([5,1])
            t_end=c1.slider("Ende [s]",0.0,float(dur),float(st.session_state.t_end),
                             step=round(1/fps,4),format="%.2f s",key="sl_end")
            c2.markdown(f'<div class="frame-info" style="margin-top:26px">F{int(t_end*fps)+1}/{tot}</div>',
                        unsafe_allow_html=True)
            st.session_state.t_start=t_start
            st.session_state.t_end=max(t_end,t_start+1.0/fps)
            st.markdown('</div>',unsafe_allow_html=True)

            st.markdown('<div class="section-card">',unsafe_allow_html=True)
            st.markdown('<div class="section-title">Video-Frame</div>',unsafe_allow_html=True)
            t_cur=st.slider("Position [s]",0.0,float(dur),float(st.session_state.t_current),
                             step=round(1/fps,4),format="%.3f s",key="sl_cur")
            st.session_state.t_current=t_cur
            frame=get_frame(st.session_state.video_path,t_cur)
            if frame is not None:
                st.image(draw_rois(frame,st.session_state.rois,
                                   st.session_state.selected_roi,fw,fh),
                         width="stretch",
                         caption=f"t={t_cur:.3f}s  |  {fw}x{fh}  |  {fps:.1f}fps")
            else:
                st.warning("Frame nicht verfuegbar.")
            st.markdown('</div>',unsafe_allow_html=True)

            st.markdown('<div class="section-card">',unsafe_allow_html=True)
            st.markdown('<div class="section-title">ROI hinzufuegen</div>',unsafe_allow_html=True)
            rc=st.columns(4)
            rx=rc[0].number_input("X",0,fw or 9999,0,1,key="rx")
            ry=rc[1].number_input("Y",0,fh or 9999,0,1,key="ry")
            rw=rc[2].number_input("W",1,fw or 9999,min(200,fw or 200),1,key="rw")
            rh=rc[3].number_input("H",1,fh or 9999,min(60,fh or 60),1,key="rh")
            rn=st.columns([2,2,1,1])
            roi_name=rn[0].selectbox("Name",ROI_NAMES,key="rn_name")
            dfmt=("time_hh:mm:ss" if roi_name=="t_s"
                  else "integer" if any(x in roi_name for x in ["v_Fzg","n_mot","gear"])
                  else "any")
            roi_fmt=rn[1].selectbox("Format",FMT_OPTIONS,
                                     index=FMT_OPTIONS.index(dfmt),key="rn_fmt")
            roi_pat=rn[2].text_input("Pattern","",key="rn_pat",placeholder="Regex")
            roi_sc=rn[3].number_input("max_scale",1.2,step=0.1,key="rn_sc")
            if roi_name=="track_minimap":
                st.info("[i] Danach in Tab Track Analysis weiterarbeiten.")
            if st.button("+ ROI hinzufuegen",type="primary",use_container_width=True):
                if roi_name == "track_minimap" and any(r["name"] == "track_minimap" for r in st.session_state.rois):
                    set_status("track_minimap ist nur einmal erlaubt.", "warn")
                    st.rerun()
                cx, cy, cw_roi, ch_roi = _clamp_roi_to_video(rx, ry, rw, rh, fw, fh)
                st.session_state.rois.append(dict(name=roi_name,
                    x=cx,y=cy,w=cw_roi,h=ch_roi,
                    fmt=roi_fmt,pattern=roi_pat,max_scale=roi_sc))
                st.session_state.selected_roi=len(st.session_state.rois)-1
                get_frame.clear(); set_status(f"ROI '{roi_name}' hinzugefuegt.","ok"); st.rerun()
            st.markdown('</div>',unsafe_allow_html=True)

        with col_r:
            st.markdown('<div class="section-card">',unsafe_allow_html=True)
            st.markdown('<div class="section-title">ROI-Liste</div>',unsafe_allow_html=True)
            if not st.session_state.rois:
                st.markdown('<div style="font-family:\'JetBrains Mono\',monospace;'
                            'font-size:.72rem;color:#2e3545;text-align:center;padding:1rem;">'
                            'Keine ROIs</div>',unsafe_allow_html=True)
            for i,roi in enumerate(st.session_state.rois):
                is_track=roi["name"]=="track_minimap"; is_sel=i==st.session_state.selected_roi
                pos=f'[{int(roi["x"])},{int(roi["y"])},{int(roi["w"])},{int(roi["h"])}]'
                if st.button(("> " if is_sel else "")+roi["name"],
                              key=f"rsel_{i}",use_container_width=True):
                    st.session_state.selected_roi=i; st.rerun()
                tag_cls="roi-tag-track" if is_track else ("roi-tag-sel" if is_sel else "roi-tag")
                st.markdown(f'<span class="roi-tag {tag_cls}">{pos}</span> '
                            f'<span style="font-family:\'JetBrains Mono\',monospace;'
                            f'font-size:.62rem;color:#4a5060">{roi["fmt"]}</span><br>',
                            unsafe_allow_html=True)
            st.markdown('</div>',unsafe_allow_html=True)

            sel=st.session_state.selected_roi
            if sel is not None and sel<len(st.session_state.rois):
                roi=st.session_state.rois[sel]
                st.markdown('<div class="section-card">',unsafe_allow_html=True)
                st.markdown(f'<div class="section-title">ROI #{sel} bearbeiten</div>',
                            unsafe_allow_html=True)
                en=st.selectbox("Name",ROI_NAMES,
                    index=ROI_NAMES.index(roi["name"]) if roi["name"] in ROI_NAMES else 0,
                    key=f"en_{sel}")
                c1,c2=st.columns(2)
                ex=c1.number_input("X",value=int(roi["x"]),step=1,key=f"ex_{sel}")
                ew=c1.number_input("W",value=int(roi["w"]),step=1,min_value=1,key=f"ew_{sel}")
                ey=c2.number_input("Y",value=int(roi["y"]),step=1,key=f"ey_{sel}")
                eh=c2.number_input("H",value=int(roi["h"]),step=1,min_value=1,key=f"eh_{sel}")
                ef=st.selectbox("Format",FMT_OPTIONS,
                    index=FMT_OPTIONS.index(roi["fmt"]) if roi["fmt"] in FMT_OPTIONS else 0,
                    key=f"ef_{sel}")
                ep=st.text_input("Pattern",roi.get("pattern",""),key=f"ep_{sel}")
                esc=st.number_input("max_scale",float(roi.get("max_scale",1.2)),
                                     step=0.1,min_value=0.5,key=f"esc_{sel}")
                ca,cb=st.columns(2)
                if ca.button("Save",use_container_width=True,key=f"sv_{sel}"):
                    cx, cy, cw_roi, ch_roi = _clamp_roi_to_video(ex, ey, ew, eh, fw, fh)
                    if en == "track_minimap" and any(
                        idx != sel and r["name"] == "track_minimap"
                        for idx, r in enumerate(st.session_state.rois)
                    ):
                        set_status("track_minimap ist nur einmal erlaubt.", "warn")
                        st.rerun()
                    st.session_state.rois[sel]=dict(name=en,x=float(ex),y=float(ey),
                        w=float(ew),h=float(eh),fmt=ef,pattern=ep,max_scale=esc)
                    st.session_state.rois[sel].update(dict(x=cx, y=cy, w=cw_roi, h=ch_roi))
                    get_frame.clear(); set_status("ROI gespeichert.","ok"); st.rerun()
                if cb.button("Delete",use_container_width=True,key=f"dl_{sel}"):
                    st.session_state.rois.pop(sel); st.session_state.selected_roi=None
                    get_frame.clear(); set_status("ROI geloescht.","info"); st.rerun()
                st.markdown('</div>',unsafe_allow_html=True)

            st.markdown('<div class="section-card">',unsafe_allow_html=True)
            st.markdown('<div class="section-title">Lokal speichern</div>',unsafe_allow_html=True)
            cf=st.session_state.capture_folder or "output"
            result=build_result_json()
            result_str=json.dumps(result,indent=2,ensure_ascii=False)
            st.download_button("Download JSON",result_str,f"results_{cf}.json",
                               "application/json",use_container_width=True)
            mat_buf=io.BytesIO(); sio.savemat(mat_buf,build_mat_struct(result))
            st.download_button("Download MAT",mat_buf.getvalue(),f"results_{cf}.mat",
                               "application/octet-stream",use_container_width=True)
            st.markdown('</div>',unsafe_allow_html=True)

            st.markdown('<div class="section-card">',unsafe_allow_html=True)
            st.markdown('<div class="section-title">Info</div>',unsafe_allow_html=True)
            n_t=sum(1 for r in st.session_state.rois if r["name"]=="track_minimap")
            st.markdown(f"""
            <div style="font-family:'JetBrains Mono',monospace;font-size:.67rem;
                 color:#8892a4;line-height:2.0;">
            <b style="color:#e8eaf0">Video</b> {fw}x{fh} @ {fps:.1f}fps<br>
            <b style="color:#e8eaf0">Dauer</b> {dur:.2f}s<br>
            <b style="color:#e8eaf0">Bereich</b> {t_start:.2f}->{st.session_state.t_end:.2f}s<br>
            <b style="color:#e8eaf0">ROIs</b> {len(st.session_state.rois)} ({n_t} track)
            </div>""",unsafe_allow_html=True)
            st.markdown('</div>',unsafe_allow_html=True)


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# TAB ðŸ—º â€“ TRACK-ANALYSE
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
with tab_track:
    has_ref   = st.session_state.ref_track_img is not None
    track_roi = next((r for r in st.session_state.rois if r["name"]=="track_minimap"),None)
    has_vid   = st.session_state.video_path is not None
    fw=st.session_state.vid_width; fh=st.session_state.vid_height

    if not has_ref:
        st.info("[i] Referenz-Track fehlt -> Tab CLOUD -> Bild laden.")
    if not track_roi:
        st.info("[i] Keine track_minimap ROI -> Tab ROI Setup -> ROI anlegen.")

    col_a,col_b=st.columns(2,gap="medium")
    clrs=[(255,80,80),(255,160,0),(255,255,0),(80,255,80),
          (0,200,255),(100,100,255),(200,80,255),(255,80,200)]

    with col_a:
        st.markdown('<div class="section-card">',unsafe_allow_html=True)
        st.markdown('<div class="section-title">Referenz-Track | 8 Kalibrierpunkte</div>',
                    unsafe_allow_html=True)
        if has_ref:
            ref_pts=st.session_state.ref_track_pts or [[0,0]]*8
            if len(ref_pts)!=8: ref_pts=[[0,0]]*8
            st.caption("Pixel-Koordinaten auf der Referenzkarte:")
            pt_data=[]
            for pi,pt in enumerate(ref_pts):
                c1,c2,c3=st.columns([.4,1,1])
                c1.markdown(f'<div style="font-family:\'JetBrains Mono\',monospace;'
                            f'font-size:.8rem;color:#4a90a4;padding-top:28px">P{pi+1}</div>',
                            unsafe_allow_html=True)
                px=c2.number_input(f"RX{pi}",value=int(pt[0]),step=1,
                                    label_visibility="collapsed",key=f"rp_x_{pi}")
                py=c3.number_input(f"RY{pi}",value=int(pt[1]),step=1,
                                    label_visibility="collapsed",key=f"rp_y_{pi}")
                pt_data.append([px,py])
            if st.button("Save Referenzpunkte",use_container_width=True):
                st.session_state.ref_track_pts=pt_data
                set_status("Referenzpunkte gespeichert.","ok"); st.rerun()
            vis=st.session_state.ref_track_img.copy()
            for pi,pt in enumerate(ref_pts):
                if pt and len(pt)==2:
                    cv2.circle(vis,(int(pt[0]),int(pt[1])),8,clrs[pi%8],-1)
                    cv2.putText(vis,f"P{pi+1}",(int(pt[0])+10,int(pt[1])),
                                cv2.FONT_HERSHEY_SIMPLEX,.5,clrs[pi%8],1)
            st.image(vis, width="stretch", caption="Referenz-Track")
        else:
            st.markdown('<div style="text-align:center;color:#2e3545;padding:2rem;">'
                        'Kein Referenzbild</div>',unsafe_allow_html=True)
        st.markdown('</div>',unsafe_allow_html=True)

    with col_b:
        st.markdown('<div class="section-card">',unsafe_allow_html=True)
        st.markdown('<div class="section-title">Minimap | 8 Punkte + Bewegungserkennung</div>',
                    unsafe_allow_html=True)
        if has_vid and track_roi:
            frame=get_frame(st.session_state.video_path,st.session_state.t_current)
            if frame is not None:
                crop=extract_minimap_crop(frame,track_roi,fw,fh)
                ch,cw=crop.shape[:2]
                mm_pts=st.session_state.minimap_pts or [[0,0]]*8
                if len(mm_pts)!=8: mm_pts=[[0,0]]*8
                st.caption("Pixel-Koordinaten auf der Minimap:")
                mm_data=[]
                for pi,pt in enumerate(mm_pts):
                    c1,c2,c3=st.columns([.4,1,1])
                    c1.markdown(f'<div style="font-family:\'JetBrains Mono\',monospace;'
                                f'font-size:.8rem;color:#3ddc84;padding-top:28px">P{pi+1}</div>',
                                unsafe_allow_html=True)
                    px=c2.number_input(f"MX{pi}",value=int(pt[0]),min_value=0,
                                        max_value=max(1,cw),step=1,
                                        label_visibility="collapsed",key=f"mp_x_{pi}")
                    py=c3.number_input(f"MY{pi}",value=int(pt[1]),min_value=0,
                                        max_value=max(1,ch),step=1,
                                        label_visibility="collapsed",key=f"mp_y_{pi}")
                    mm_data.append([px,py])
                if st.button("Save Minimap-Punkte",use_container_width=True):
                    st.session_state.minimap_pts=mm_data
                    set_status("Minimap-Punkte gespeichert.","ok"); st.rerun()
                vis_c=crop.copy()
                for pi,pt in enumerate(st.session_state.minimap_pts or []):
                    if pt and len(pt)==2:
                        cv2.circle(vis_c,(int(pt[0]),int(pt[1])),6,clrs[pi%8],-1)
                        cv2.putText(vis_c,f"P{pi+1}",(int(pt[0])+7,int(pt[1])),
                                    cv2.FONT_HERSHEY_SIMPLEX,.4,clrs[pi%8],1)
                st.image(vis_c, width="stretch", caption=f"Minimap ({cw}x{ch}px)")
        else:
            st.markdown('<div style="text-align:center;color:#2e3545;padding:2rem;">'
                        'Video + track_minimap ROI benoetigt</div>',unsafe_allow_html=True)
        st.markdown('</div>',unsafe_allow_html=True)

    st.markdown('<div class="section-card">',unsafe_allow_html=True)
    st.markdown('<div class="section-title">Vergleich | Ueberlagerung | Bewegende Punkte</div>',
                unsafe_allow_html=True)
    cv1,cv2_,cv3=st.columns([2,2,1])
    with cv3:
        st.markdown("**Farberkennung (HSV)**")
        cr=st.session_state.moving_pt_color_range
        h_lo=st.slider("H min",0,179,cr["h_lo"],key="h_lo")
        h_hi=st.slider("H max",0,179,cr["h_hi"],key="h_hi")
        s_lo=st.slider("S min",0,255,cr["s_lo"],key="s_lo")
        s_hi=st.slider("S max",0,255,cr["s_hi"],key="s_hi")
        v_lo=st.slider("V min",0,255,cr["v_lo"],key="v_lo")
        v_hi=st.slider("V max",0,255,cr["v_hi"],key="v_hi")
        st.session_state.moving_pt_color_range=dict(
            h_lo=h_lo,h_hi=h_hi,s_lo=s_lo,s_hi=s_hi,v_lo=v_lo,v_hi=v_hi)
        h_m=(h_lo+h_hi)//2; s_m=(s_lo+s_hi)//2; v_m=(v_lo+v_hi)//2
        px=np.zeros((28,56,3),dtype=np.uint8)
        px[:]=cv2.cvtColor(np.array([[[h_m,s_m,v_m]]],dtype=np.uint8),cv2.COLOR_HSV2RGB)[0,0]
        st.image(px, caption="Zielfarbe", width="stretch")

    can_cmp=(has_ref and track_roi and has_vid and
             _has_valid_8_points(st.session_state.ref_track_pts) and
             _has_valid_8_points(st.session_state.minimap_pts))
    with cv1:
        if can_cmp and st.button("> Vergleich",type="primary",use_container_width=True):
            frame=get_frame(st.session_state.video_path,st.session_state.t_current)
            if frame is not None:
                crop=extract_minimap_crop(frame,track_roi,fw,fh)
                cmp=compare_minimap_to_reference(crop,st.session_state.ref_track_img,
                    st.session_state.minimap_pts,st.session_state.ref_track_pts)
                st.session_state.track_comparison=cmp
                if cmp.get("error"):
                    set_status(f"Vergleich fehlgeschlagen: {cmp['error']}", "warn")
                    st.rerun()
                mp=detect_moving_point(crop,st.session_state.moving_pt_color_range)
                if mp:
                    ref_pt = project_point_with_homography((mp["x"], mp["y"]), cmp.get("H"))
                    st.session_state.moving_pt_history.append({
                        "t": st.session_state.t_current,
                        "x_minimap": mp["x"],
                        "y_minimap": mp["y"],
                        "x_ref": ref_pt[0] if ref_pt else None,
                        "y_ref": ref_pt[1] if ref_pt else None,
                        "confidence": mp.get("confidence", 0.0),
                    })
                set_status("Vergleich durchgefuehrt.","ok"); st.rerun()
        cmp=st.session_state.track_comparison
        if cmp:
            if cmp.get("error"):
                st.warning(cmp["error"])
            m1,m2,m3=st.columns(3)
            for col,val,lbl in [(m1,cmp["mean_dist_px"],"O px"),
                                 (m2,cmp["max_dist_px"],"Max px"),
                                 (m3,cmp["homography_err"],"H-Err")]:
                col.markdown(f'<div class="metric-box"><div class="metric-val">'
                             f'{val:.2f}</div><div class="metric-lbl">{lbl}</div></div>',
                             unsafe_allow_html=True)
    with cv2_:
        cmp=st.session_state.track_comparison
        if cmp and has_ref and track_roi and has_vid:
            frame=get_frame(st.session_state.video_path,st.session_state.t_current)
            if frame is not None:
                crop=extract_minimap_crop(frame,track_roi,fw,fh)
                overlay=draw_comparison_overlay(crop,st.session_state.ref_track_img,
                    st.session_state.minimap_pts,st.session_state.ref_track_pts,
                    cmp,st.session_state.moving_pt_color_range)
                st.image(overlay, width="stretch",
                         caption="Minimap (blau) vs. Referenz (gruen)")
    st.markdown('</div>',unsafe_allow_html=True)

    if st.session_state.moving_pt_history:
        st.markdown('<div class="section-card">',unsafe_allow_html=True)
        st.markdown('<div class="section-title">Verlauf bewegender Punkt</div>',
                    unsafe_allow_html=True)
        import pandas as pd
        c1,c2=st.columns([1,4])
        c1.metric("Positionen",len(st.session_state.moving_pt_history))
        if c1.button("Leeren",key="hist_clear"):
            st.session_state.moving_pt_history=[]; st.rerun()
        df=pd.DataFrame(st.session_state.moving_pt_history[-100:])
        c2.dataframe(df, width="stretch", height=180)
        st.markdown('</div>',unsafe_allow_html=True)

