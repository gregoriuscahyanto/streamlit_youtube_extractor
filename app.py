"""
OCR Extractor - Streamlit App v4
Tab 1: Cloudflare R2-Verbindung, Prefix waehlen, Datei-Browser
Tab 2: Video laden, Start/Ende, ROI-Auswahl
Tab 3: Track-Minimap Analyse - 8-Punkte + Farberkennung
"""

import streamlit as st
import streamlit.components.v1 as components
try:
    from streamlit.delta_generator import DeltaGenerator
except Exception:
    DeltaGenerator = None
import math
import cv2
import numpy as np
import json
import tempfile
import io
import zipfile
import time
import queue
import os
# Workaround for Windows access violations in pandas<->pyarrow string backend on Python 3.13.
# Keep pandas on the Python string storage backend for Streamlit runtime stability.
os.environ.setdefault("PANDAS_USE_PYARROW", "0")
import importlib.util
import subprocess
import shutil
import sys
import threading
import traceback
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
import concurrent.futures as cf
import scipy.io as sio
try:
    from scipy.io.matlab._mio5_params import MatlabObject
except Exception:
    MatlabObject = None
from scipy import signal
from scipy.io import wavfile
import pandas as pd
from pathlib import Path, PurePosixPath
from datetime import datetime
from PIL import Image
try:
    from streamlit_image_coordinates import streamlit_image_coordinates
except Exception:
    streamlit_image_coordinates = None
try:
    from streamlit_cropper import st_cropper
except Exception:
    st_cropper = None
try:
    from streamlit_js_eval import streamlit_js_eval
except Exception:
    streamlit_js_eval = None

from core.local_storage import LocalStorageAdapter
from core.backend import (
    build_result_payload,
    build_mat_struct as backend_build_mat_struct,
    collect_r2_listing_debug,
    config_from_json_payload,
    config_from_mat_file,
    connect_r2_client,
    guess_fixed_points,
    list_root_prefixes,
    load_centerline_from_mat,
    load_r2_credentials,
    render_centerline_image,
    save_slim_mat,
    summarize_mat_file,
)
from core.storage import StorageManager
from core.roi_utils import (
    can_add_roi_from_drag,
    clamp_roi_to_video,
    normalize_time_range,
    roi_from_crop_box,
    seed_drag_roi,
)
from core.ocr_diagnostic import diagnose_roi_ocr, find_tesseract_cmd
from core.track_analysis import (
    compare_minimap_to_reference,
    detect_moving_point,
    draw_comparison_overlay,
    extract_minimap_crop,
    project_point_with_homography,
)
from app_tabs import audio_sweep, audio_tab, compare_tab, mat_to_json_tab, media_tab, plausibility_filter, roi_catalog_tab, roi_setup_tab, setup_tab, track_geoplot, video_ocr_tab, watchdog_tab, youtube_tab
try:
    # Streamlit reruns app.py in the same Python process. Reload extracted tab modules
    # so changes in app_tabs/*.py are visible without a full server restart.
    import importlib
    for _tab_module in (audio_sweep, audio_tab, compare_tab, mat_to_json_tab, media_tab, plausibility_filter, roi_catalog_tab, roi_setup_tab, setup_tab, track_geoplot, video_ocr_tab, watchdog_tab, youtube_tab):
        importlib.reload(_tab_module)
except Exception:
    pass

HAS_PYARROW = importlib.util.find_spec("pyarrow") is not None

if (not HAS_PYARROW) and DeltaGenerator is not None and not getattr(st, "_no_pyarrow_dataframe_patch", False):
    _ORIG_DELTA_DATAFRAME = DeltaGenerator.dataframe
    _ORIG_ST_DATAFRAME = st.dataframe

    def _render_html_table(container, data, *, hide_index=None):
        try:
            if isinstance(data, pd.io.formats.style.Styler):
                df = data.data.copy()
            elif isinstance(data, pd.DataFrame):
                df = data.copy()
            else:
                df = pd.DataFrame(data)
        except Exception:
            try:
                container.write(data)
            except Exception:
                pass
            return
        if len(df) > 600:
            df = df.head(600)
        show_index = not bool(hide_index)
        html = df.to_html(index=show_index, escape=False)
        container.markdown(html, unsafe_allow_html=True)

    def _delta_dataframe_no_pyarrow(self, data=None, width=None, height=None, **kwargs):
        try:
            return _ORIG_DELTA_DATAFRAME(self, data=data, width=width, height=height, **kwargs)
        except ModuleNotFoundError as e:
            if "pyarrow" not in str(e).lower():
                raise
            _render_html_table(self, data, hide_index=kwargs.get("hide_index"))
            return self

    def _st_dataframe_no_pyarrow(data=None, width=None, height=None, **kwargs):
        try:
            return _ORIG_ST_DATAFRAME(data=data, width=width, height=height, **kwargs)
        except ModuleNotFoundError as e:
            if "pyarrow" not in str(e).lower():
                raise
            _render_html_table(st, data, hide_index=kwargs.get("hide_index"))
            return st

    DeltaGenerator.dataframe = _delta_dataframe_no_pyarrow
    st.dataframe = _st_dataframe_no_pyarrow
    st._no_pyarrow_dataframe_patch = True

if DeltaGenerator is not None and not getattr(st.button, "_ocr_form_fallback", False):
    _ORIG_DELTA_BUTTON = DeltaGenerator.button
    _ORIG_ST_BUTTON = st.button

    def _form_fallback_kwargs(kwargs):
        out = dict(kwargs)
        if out.get("key") is not None:
            out["key"] = f"{out['key']}_form_submit"
        return out

    def _button_with_form_fallback(self, *args, **kwargs):
        try:
            return _ORIG_DELTA_BUTTON(self, *args, **kwargs)
        except Exception as exc:
            if "can't be used in an `st.form()`" not in str(exc):
                raise
            submit_button = getattr(self, "form_submit_button", st.form_submit_button)
            return submit_button(*args, **_form_fallback_kwargs(kwargs))

    def _st_button_with_form_fallback(*args, **kwargs):
        try:
            return _ORIG_ST_BUTTON(*args, **kwargs)
        except Exception as exc:
            if "can't be used in an `st.form()`" not in str(exc):
                raise
            return st.form_submit_button(*args, **_form_fallback_kwargs(kwargs))

    _button_with_form_fallback._ocr_form_fallback = True
    _st_button_with_form_fallback._ocr_form_fallback = True
    DeltaGenerator.button = _button_with_form_fallback
    st.button = _st_button_with_form_fallback

# Crash-Log
LOG_DIR = Path.cwd() / "logs"
LOG_FILE = LOG_DIR / "app_crash.log"


def _append_crash_log(header: str, tb_text: str):
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(f"\n\n=== {stamp} | {header} ===\n")
            f.write(tb_text)
            f.write("\n")
    except Exception:
        pass


def _is_ignorable_shutdown_exception(exc_type, exc_value, tb_text: str) -> bool:
    # Streamlit shutdown can raise this benign runtime error while the event loop
    # is already closing. We don't want to classify that as an app crash.
    if exc_type is RuntimeError and "Event loop is closed" in str(exc_value):
        if ("streamlit\\web\\bootstrap.py" in tb_text) or ("weakref.py" in tb_text):
            return True
    # Python tempfile cleanup at interpreter shutdown can fail on Windows when
    # temp dirs are still locked by background handles.
    if exc_type is PermissionError and "WinError 5" in str(exc_value):
        if ("tempfile.py" in tb_text) and ("_cleanup" in tb_text) and ("weakref.py" in tb_text):
            return True
    return False


def _handle_unhandled_exception(exc_type, exc_value, exc_tb):
    tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    if _is_ignorable_shutdown_exception(exc_type, exc_value, tb_text):
        return
    _append_crash_log("Unhandled Exception", tb_text)


def _handle_thread_exception(args):
    tb_text = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
    if _is_ignorable_shutdown_exception(args.exc_type, args.exc_value, tb_text):
        return
    _append_crash_log(f"Thread Exception ({getattr(args, 'thread', None)})", tb_text)


sys.excepthook = _handle_unhandled_exception
if hasattr(threading, "excepthook"):
    threading.excepthook = _handle_thread_exception


st.set_page_config(
    page_title="OCR Extractor",
    page_icon="OCR",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# CSS styles
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
.mat-selection-disabled {
  opacity: .48;
  filter: grayscale(1);
  pointer-events: none;
  user-select: none;
}
.mat-selection-disabled [data-testid="stDataFrame"] {
  background: #20232b !important;
  border-radius: 6px;
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
.conn-dot.off { background:#ff5c5c; box-shadow:0 0 6px #ff5c5c66; }

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
.st-key-roi_ocr_probe_btn.ocr-all-ok button,
.st-key-roi_ocr_probe_btn.ocr-all-ok [data-testid="stBaseButton-secondary"] {
  background:#3ddc84 !important; border-color:#3ddc84 !important; color:#07100b !important;
  box-shadow:0 0 0 1px rgba(61,220,132,.25), 0 0 14px rgba(61,220,132,.18) !important;
}

hr { border-color:#1e2535 !important; }

/* selected row highlight in dataframe */
.stDataFrame [aria-selected="true"] {
  background-color: rgba(74, 144, 164, 0.30) !important;
}
.ref-track-fit img { max-height: 340px; object-fit: contain; }
.track-samples-grid { display:grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap:.65rem; overflow-x:auto; }
.track-sample-card { background:#0a0c10; border:1px solid #1e2535; border-radius:6px; padding:.45rem; min-width:0; }
.track-progress-big { font-family:'JetBrains Mono',monospace; font-size:2.05rem; font-weight:800; color:#3ddc84; line-height:1.1; margin:.22rem 0 .08rem; }
.track-metrics-small { font-family:'JetBrains Mono',monospace; font-size:.62rem; color:#8892a4; line-height:1.35; }
.mat-analysis-grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap:.75rem; margin-top:.75rem; }
.mat-analysis-card { background:#0a0c10; border:1px solid #1e2535; border-radius:7px; padding:.75rem .85rem; }
.mat-analysis-title { font-family:'JetBrains Mono',monospace; font-size:.64rem; color:#8892a4; letter-spacing:.08em; text-transform:uppercase; margin-bottom:.4rem; }
.mat-analysis-value { font-family:'JetBrains Mono',monospace; font-size:1.28rem; font-weight:800; color:#e8eaf0; line-height:1.05; }
.mat-analysis-sub { font-family:'JetBrains Mono',monospace; font-size:.62rem; color:#4a90a4; margin-top:.25rem; }
.mat-progress-outer { height:9px; border-radius:999px; background:#1e2535; overflow:hidden; margin-top:.55rem; }
.mat-progress-inner { height:100%; border-radius:999px; background:#3ddc84; }
.mat-analysis-bars { display:grid; grid-template-columns: 1fr; gap:.42rem; margin-top:.7rem; }
.mat-analysis-bar-row { display:grid; grid-template-columns: 190px 1fr 88px; align-items:center; gap:.65rem; font-family:'JetBrains Mono',monospace; font-size:.68rem; color:#b7c3d8; }
.mat-analysis-bar-track { height:16px; border-radius:999px; background:#1e2535; overflow:hidden; border:1px solid #243049; }
.mat-analysis-bar-fill { height:100%; border-radius:999px; background:#4a90a4; }
.mat-analysis-note { font-family:'JetBrains Mono',monospace; font-size:.62rem; color:#4a5060; margin-top:.4rem; }
.roi-theme-card { background:#101722; border:1px solid #25344a; border-radius:9px; padding:.75rem .9rem; margin:.75rem 0; }
.roi-theme-card .theme-title { font-family:'JetBrains Mono',monospace; font-size:.72rem; color:#8fcbe0; letter-spacing:.12em; text-transform:uppercase; margin-bottom:.35rem; }
.roi-theme-card .theme-text { font-family:'JetBrains Mono',monospace; font-size:.68rem; color:#8892a4; line-height:1.45; }
.save-status-card { background:#0d2e1a; border:1px solid #1a5c34; color:#dfffe8; border-radius:7px; padding:.55rem .75rem; font-family:'JetBrains Mono',monospace; font-size:.68rem; margin-top:.45rem; }
@media (max-width: 1100px) { .track-samples-grid { grid-template-columns: repeat(5, minmax(170px, 1fr)); } }
</style>
""", unsafe_allow_html=True)

# ROI and format lists
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
    "float","alnum",
]

# Load ROI catalog and merge custom names into ROI_NAMES so they appear in selectors.
try:
    from app_tabs.roi_catalog_tab import load_catalog as _load_roi_catalog, all_roi_names as _all_roi_names
    _roi_catalog = _load_roi_catalog()
    ROI_NAMES = _all_roi_names(_roi_catalog)
except Exception:
    _roi_catalog = {}

MAT_OVERVIEW_COLCFG = {
    "mat_datei": st.column_config.TextColumn("mat_datei", width="medium"),
    "video_title": st.column_config.TextColumn("video_title", width="large"),
    "audio_video_vorhanden": st.column_config.TextColumn("Audio+Video vorhanden", width="small"),
    "kein_roi_vorhanden": st.column_config.TextColumn("Kein ROI", width="small"),
    "video_fehlerhaft": st.column_config.TextColumn("Video fehlerhaft", width="small"),
    "roi_ausgewaehlt": st.column_config.TextColumn("ROI", width="small"),
    "track_ausgewaehlt": st.column_config.TextColumn("Track", width="small"),
    "anfang_ende_ausgewaehlt": st.column_config.TextColumn("Start/Ende", width="small"),
    "audio_config": st.column_config.TextColumn("Audio Config", width="small"),
    "ocr_durchgefuehrt": st.column_config.TextColumn("OCR", width="small"),
    "ocr_vollstaendig": st.column_config.TextColumn("OCR vollstaendig", width="small"),
    "audioanalyse_spektrogramm": st.column_config.TextColumn("Audio/Spektrogramm", width="small"),
    "validierung": st.column_config.TextColumn("Validierung", width="small"),
    "fehler": st.column_config.TextColumn("Fehler", width="large"),
}
MAT_TABLE_HEIGHT = 430
VIDEO_EXTS = (".mp4", ".mov", ".avi", ".mkv")
AUDIO_EXTS = (".wav", ".mp3", ".m4a", ".aac", ".flac")
AUDIO_PROXY_NAME = "audio_proxy_1k.wav"  # kept for backwards-compat exclusion checks
LAMP_GREEN = "\U0001F7E2"
LAMP_RED = "\U0001F534"
MOJIBAKE_GREEN = "\u00f0\u0178\u0178\u00a2"
MOJIBAKE_RED = "\u00f0\u0178\u201d\u00b4"

# Session state defaults
def init_state():
    _acc, _key, _sec, _bkt = load_r2_credentials(streamlit_secrets=st.secrets)
    _local_default = str((st.secrets.get("local") or {}).get("default_path") or Path.cwd())
    _db_cfg = st.secrets.get("database") or {}
    _compressed_mode = str(_db_cfg.get("compressed_mode") or "local").strip().lower()
    if _compressed_mode not in {"local", "r2"}:
        _compressed_mode = "local"
    _compressed_default_path = str(_db_cfg.get("default_path") or _local_default or Path.cwd())

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
        local_auto_connect_attempted=False,
        # Local DB
        local_base_path=_local_default,
        local_base_path_input=_local_default,
        local_connected=False,
        local_client=None,
        local_root="",
        local_root_options=[],
        compressed_db_mode=_compressed_mode,
        compressed_db_default_path=_compressed_default_path,
        sync_overview_rows=[],
        sync_queue_rows=[],
        sync_status_map={},
        sync_running=False,
        sync_stop_requested=False,
        sync_run_queue=[],
        sync_run_idx=0,
        sync_run_total=0,
        sync_run_started_ts=0.0,
        sync_run_selected_folders=[],
        sync_selected_folders=[],
        sync_editor_value=None,
        sync_refresh_running=False,
        sync_refresh_idx=0,
        sync_refresh_total=0,
        sync_refresh_folders=[],
        sync_refresh_rows=[],
        mat_files=[],
        mat_targets=[],
        mat_scan_prefix=None,
        mat_selected_key="",
        mat_pending_selected_key="",
        mat_user_selected_key="",
        mat_selected_summary=None,
        mat_summary_cache={},
        mat_overview_rows=[],
        mat_auto_updated_prefix=None,
        mat_json_sidecar_created_count=0,
        mat_json_sidecar_used_count=0,
        mat_json_sidecar_last_run_total=0,
        jump_to_mat_tab=False,
        mat_update_running=False,
        mat_update_idx=0,
        mat_update_total=0,
        mat_update_keys=[],
        mat_run_state="idle",
        mat_update_stop_requested=False,
        mat_update_future=None,
        mat_update_event_queue=None,
        mat_update_stop_event=None,
        mat_load_requested=False,
        mat_load_running=False,
        roi_save_running=False,
        roi_ocr_probe_running=False,
        roi_ocr_full_running=False,
        video_ocr_full_running=False,
        roi_next_load_running=False,
        roi_saved_once=False,
        roi_delete_confirm_idx=None,
        roi_scroll_top_once=False,
        tab_default=None,
        audio_analysis_result=None,
        audio_vehicle_title="",
        audio_last_mat_path="",
        audio_debug_lines=[],
        audio_debug_last_run="",
        audio_bg_future=None,
        audio_bg_started=0.0,
        audio_bg_params={},
        audio_bg_log=[],
        audio_bg_source="",
        audio_bg_progress={},
        audio_bg_progress_ref=None,
        audio_config_last_saved_key="",
        audio_location="",
        audio_validation_result=None,
        audio_validation_debug=[],
        # Datei-Browser
        fb_path="", fb_items=[], fb_selected=None,
        # Aufnahme
        capture_folder="",
        # Video / ROI
        video_path=None, video_name="",
        media_source="video",
        vid_duration=0.0, vid_fps=25.0, vid_width=0, vid_height=0,
        t_start=0.0, t_end=0.0, t_current=0.0,
        rois=[], selected_roi=None,
        drag_roi={},
        roi_draw_armed=False,
        roi_force_default_once=False,
        roi_last_frame_key=None,
        roi_seed_drag={},
        roi_seen_nonseed=False,
        roi_reject_seed_once=False,
        roi_cropper_ver=0,
        roi_prev_frame_idx=None,
        roi_wait_user_move=False,
        roi_anchor_box={},
        roi_reject_anchor_events=0,
        roi_pending_select_idx=None,
        roi_click_stage=0,
        roi_click_p1=None,
        roi_click_last_sig="",
        roi_display_meta={},
        roi_editor_df=None,
        roi_ocr_probe_result=None,
        roi_ocr_full_result=None,
        video_ocr_full_result=None,
        roi_global_scale=1.2,
        roi_editor_widget_key="roi_data_editor_v3",
        # Track
        ref_track_img=None, ref_track_pts=None, minimap_pts=None,
        centerline=None, centerline_px=None, ref_track_mat_name="",
        minimap_next_pt_idx=0,
        track_comparison=None, moving_pt_history=[],
        moving_pt_color_range=dict(h_lo=0,h_hi=30,s_lo=150,s_hi=255,v_lo=150,v_hi=255),
        # Status
        status_msg="Bereit", status_type="info",
    )
    for k, v in defs.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()


def _render_blocking_overlay(text: str):
    st.markdown(
        f"""
        <style>
        .app-busy-overlay {{
          position: fixed; inset: 0; z-index: 10000;
          background: rgba(8, 10, 16, 0.62);
          backdrop-filter: grayscale(1) blur(1px);
          pointer-events: all; cursor: wait;
          display:flex; align-items:center; justify-content:center;
        }}
        .app-busy-overlay-box {{
          background: rgba(7, 14, 26, 0.94); color:#dfffe8;
          border:1px solid rgba(61, 220, 132, 0.55);
          border-radius:12px; padding:16px 20px;
          font-family:'JetBrains Mono', monospace; font-size:.85rem; font-weight:800;
          box-shadow: 0 10px 34px rgba(0,0,0,.45);
        }}
        </style>
        <div class="app-busy-overlay"><div class="app-busy-overlay-box">{text}</div></div>
        """,
        unsafe_allow_html=True,
    )


# Nur "Nächste Datei laden" darf bewusst einen kompletten Rerun/Refresh auslösen.
# Speichern und OCR-Test zeigen ihr Overlay lokal im jeweiligen Button-Flow.
if bool(st.session_state.get("roi_next_load_running", False)):
    _render_blocking_overlay("Nächste Datei wird geladen ...")


def _activate_tab_once() -> None:
    """Click the tab whose label matches tab_default, then clear it.

    Uses st.components.v1.html (always available) with a retry loop so the
    click lands even when the tab DOM is not yet painted on first render.
    """
    label = str(st.session_state.get("tab_default") or "").strip()
    if not label:
        return
    st.session_state.tab_default = None
    js = f"""<script>
(function() {{
  var target = {json.dumps(label)};
  var attempts = 0;
  function tryClick() {{
    var tabs = window.parent.document.querySelectorAll('[role="tab"]');
    for (var i = 0; i < tabs.length; i++) {{
      if (tabs[i].textContent.trim() === target) {{
        tabs[i].click();
        return;
      }}
    }}
    if (++attempts < 20) {{ setTimeout(tryClick, 80); }}
  }}
  setTimeout(tryClick, 50);
}})();
</script>"""
    try:
        import streamlit.components.v1 as _cv1
        _cv1.html(js, height=0, scrolling=False)
    except Exception:
        pass


def _scroll_to_top_once(flag_key: str = "roi_scroll_top_once"):
    if not bool(st.session_state.get(flag_key, False)):
        return
    st.session_state[flag_key] = False
    if streamlit_js_eval is None:
        return
    try:
        streamlit_js_eval(js_expressions="window.parent?.scrollTo(0,0); document.querySelector('.block-container')?.scrollTo(0,0); true;", key=f"scroll_top_{int(time.time()*1000)}", want_output=False)
    except Exception:
        pass

# One-time migration for legacy ROI editor widget state keys that could hold
# incompatible column schema/dtypes.
for _legacy_roi_key in ("roi_data_editor", "roi_data_editor_v1", "roi_data_editor_v2"):
    if _legacy_roi_key in st.session_state:
        st.session_state.pop(_legacy_roi_key, None)

# Frame and media helpers
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


def _get_cloud_capture_folders() -> list[str]:
    if not st.session_state.r2_connected or st.session_state.r2_client is None:
        return []
    pfx = st.session_state.r2_prefix.strip("/")
    cap_dir = f"{pfx}/captures" if pfx else "captures"
    ok, items = st.session_state.r2_client.list_files(cap_dir)
    if not ok or not isinstance(items, list):
        return []
    out = [i.rstrip("/") for i in items if i.endswith("/")]
    out.sort()
    return out


def _get_local_capture_folders() -> list[str]:
    client = st.session_state.get("local_client")
    if (not bool(st.session_state.get("local_connected"))) or client is None:
        return []
    ok, items = client.list_files("captures")
    if not ok or not isinstance(items, list):
        return []
    out = [i.rstrip("/") for i in items if i.endswith("/")]
    out.sort()
    return out


def _has_local_fullfps_video(folder: str) -> tuple[bool, int]:
    client = st.session_state.get("local_client")
    if (not bool(st.session_state.get("local_connected"))) or client is None:
        return False, 0
    ok, items = client.list_files(f"captures/{folder}")
    if not ok or not isinstance(items, list):
        return False, 0
    vids = [
        n for n in items
        if (not n.endswith("/")) and n.lower().endswith((".mp4", ".mov", ".avi", ".mkv"))
    ]
    fullfps = [n for n in vids if "_1fps" not in n.lower()]
    return len(fullfps) > 0, len(fullfps)


def _has_cloud_proxy_video(folder: str) -> tuple[bool, int]:
    if not st.session_state.r2_connected or st.session_state.r2_client is None:
        return False, 0
    pfx = st.session_state.r2_prefix.strip("/")
    remote = f"{pfx}/captures/{folder}" if pfx else f"captures/{folder}"
    ok, items = st.session_state.r2_client.list_files(remote)
    if not ok or not isinstance(items, list):
        return False, 0
    vids = [
        n for n in items
        if (not n.endswith("/")) and n.lower().endswith((".mp4", ".mov", ".avi", ".mkv"))
    ]
    proxy = [n for n in vids if "_1fps" in n.lower()]

    # Frame-pack support: captures/<folder>/frames_1fps/{000001.jpg, ..., index.json}
    frame_count = 0
    if "frames_1fps/" in items:
        ok_fp, fp_items = st.session_state.r2_client.list_files(f"{remote}/frames_1fps")
        if ok_fp and isinstance(fp_items, list):
            frame_count = len([x for x in fp_items if x.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))])

    total_count = len(proxy) + frame_count
    return total_count > 0, total_count


def _expected_reduced_frame_count_for_video(src_video: Path) -> int:
    cap = cv2.VideoCapture(str(src_video))
    if not cap.isOpened():
        return 0
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if fps <= 0:
            fps = 25.0
        duration_s = (frame_count / fps) if frame_count > 0 else 0.0
        return max(1, int(np.ceil(duration_s)))
    except Exception:
        return 0
    finally:
        cap.release()


def _cloud_reduced_completeness(folder: str, src_video: Path | None) -> tuple[bool, int, int, str]:
    """
    Returns (is_complete, cloud_count, expected_count, status_text).
    """
    _exists, cloud_count = _has_cloud_proxy_video(folder)
    expected_count = 0
    if src_video is not None:
        expected_count = _expected_reduced_frame_count_for_video(src_video)
    if expected_count <= 0:
        return False, int(cloud_count), int(expected_count), "Nein (Originalvideo nicht lesbar; erwartete Frame-Anzahl konnte nicht berechnet werden)"

    pfx = st.session_state.r2_prefix.strip("/")
    cap_dir = f"{pfx}/captures/{folder}" if pfx else f"captures/{folder}"
    audio_ok = False
    if st.session_state.r2_connected and st.session_state.r2_client is not None:
        ok_cap, cap_items = st.session_state.r2_client.list_files(cap_dir)
        if ok_cap and isinstance(cap_items, list):
            lowered = [x.lower() for x in cap_items if not x.endswith("/")]
            audio_ok = AUDIO_PROXY_NAME.lower() in lowered

    complete_frames = int(cloud_count) >= int(expected_count)
    if complete_frames and audio_ok:
        text = "Ja"
    else:
        parts = [f"Frames {int(cloud_count)}/{int(expected_count)}"]
        if not audio_ok:
            parts.append("Audio fehlt")
        text = f"Nein ({', '.join(parts)})"
    return bool(complete_frames and audio_ok), int(cloud_count), int(expected_count), text


def _build_sync_overview_rows() -> tuple[list[dict], list[dict]]:
    local_folders = sorted(set(_get_local_capture_folders()))

    overview_rows: list[dict] = []
    queue_rows: list[dict] = []

    for folder in local_folders:
        local_ok, _local_count = _has_local_fullfps_video(folder)
        if not local_ok:
            continue
        src_video = _find_local_fullfps_video(folder)
        cloud_complete, cloud_count, expected_count, cloud_text = _cloud_reduced_completeness(folder, src_video)
        state = "OK" if cloud_complete else ""
        row = {
            "auswaehlen": False,
            "capture_folder": folder,
            "reduziert_in_cloud": cloud_text,
            "status": state,
            "cloud_framepack_anzahl": int(cloud_count),  # internal/debug
            "expected_framepack_anzahl": int(expected_count),  # internal/debug
        }
        overview_rows.append(row)
        if not cloud_complete:
            queue_rows.append(row)

    return overview_rows, queue_rows


def _local_capture_folder_path(folder: str) -> Path | None:
    if not bool(st.session_state.get("local_connected")):
        return None
    try:
        base = Path(str(st.session_state.get("local_base_path") or "")).expanduser().resolve()
        p = (base / "captures" / folder).resolve()
        if base != p and base not in p.parents:
            return None
        return p
    except Exception:
        return None


def _find_local_fullfps_video(folder: str) -> Path | None:
    cap_dir = _local_capture_folder_path(folder)
    if cap_dir is None or (not cap_dir.exists()) or (not cap_dir.is_dir()):
        return None
    candidates_by_ext: dict[str, list[Path]] = {".avi": [], ".mp4": [], ".mov": [], ".mkv": []}
    for p in cap_dir.iterdir():
        if not p.is_file():
            continue
        if p.suffix.lower() not in VIDEO_EXTS:
            continue
        if "_1fps" in p.name.lower():
            continue
        candidates_by_ext[p.suffix.lower()].append(p)
    for ext in [".avi", ".mp4", ".mov", ".mkv"]:
        cands = candidates_by_ext.get(ext) or []
        if cands:
            return max(cands, key=lambda x: x.stat().st_size)
    return None


def _find_local_audio_file(folder: str) -> Path | None:
    cap_dir = _local_capture_folder_path(folder)
    if cap_dir is None or (not cap_dir.exists()) or (not cap_dir.is_dir()):
        return None
    candidates_by_ext: dict[str, list[Path]] = {e: [] for e in AUDIO_EXTS}
    for p in cap_dir.iterdir():
        if not p.is_file():
            continue
        ext = p.suffix.lower()
        if ext in candidates_by_ext:
            candidates_by_ext[ext].append(p)
    # Prefer WAV because scipy wav reader is robust and fast.
    for ext in [".wav", ".flac", ".m4a", ".mp3", ".aac"]:
        cands = candidates_by_ext.get(ext) or []
        if cands:
            return max(cands, key=lambda x: x.stat().st_size)
    return None


def _build_audio_proxy_wav(src_audio: Path, out_wav: Path) -> tuple[bool, str]:
    """
    Build compact mono WAV with lowpass + downsampling for WAV/MP3 sources.
    Uses ffmpeg if available (system ffmpeg or imageio-ffmpeg bundled binary).
    """
    ffmpeg_exe = shutil.which("ffmpeg")
    if not ffmpeg_exe:
        try:
            import imageio_ffmpeg
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            ffmpeg_exe = None

    ffmpeg_error = ""
    if ffmpeg_exe:
        cmd = [
            ffmpeg_exe,
            "-y",
            "-i", str(src_audio),
            "-vn",
            "-ac", "1",
            "-ar", str(int(AUDIO_TARGET_SR)),
            "-af", f"lowpass=f={int(AUDIO_LOWPASS_HZ)}",
            str(out_wav),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode == 0 and out_wav.exists() and out_wav.stat().st_size > 0:
                return True, ""
            err = (proc.stderr or proc.stdout or "").strip()
            ffmpeg_error = f"ffmpeg fehlgeschlagen: {err[-240:]}"
        except Exception as e:
            ffmpeg_error = f"ffmpeg Aufruf fehlgeschlagen: {e}"

    # Minimal fallback for plain WAV without ffmpeg or after a failed ffmpeg run.
    if src_audio.suffix.lower() != ".wav":
        return False, ffmpeg_error or "Kein ffmpeg verfuegbar (fuer Audio aus Video/MP3 benoetigt)."
    try:
        sr, data = wavfile.read(str(src_audio))
        x = data.astype(np.float32, copy=False)
        if x.ndim > 1:
            x = np.mean(x, axis=1)
        if np.issubdtype(data.dtype, np.integer):
            max_abs = float(np.iinfo(data.dtype).max)
            if max_abs > 0:
                x = x / max_abs
        cutoff = min(float(AUDIO_LOWPASS_HZ), 0.45 * float(sr))
        if cutoff > 10.0 and sr > 2 * cutoff:
            b, a = signal.butter(4, cutoff / (0.5 * float(sr)), btype="low")
            x = signal.filtfilt(b, a, x).astype(np.float32)
        target_sr = int(min(max(2000, int(AUDIO_TARGET_SR)), int(sr)))
        if target_sr != int(sr):
            x = signal.resample_poly(x, target_sr, int(sr)).astype(np.float32)
        x = np.clip(x, -1.0, 1.0)
        y = (x * 32767.0).astype(np.int16)
        wavfile.write(str(out_wav), int(target_sr), y)
        return True, ""
    except Exception as e:
        return False, f"Audio-Proxy Build fehlgeschlagen: {e}"


def _upload_audio_proxy_1k(folder: str) -> tuple[bool, str]:
    src_audio = _find_local_audio_file(folder)
    if src_audio is None:
        src_audio = _find_local_fullfps_video(folder)
    if src_audio is None:
        return False, "Keine lokale Audio- oder Videodatei gefunden."
    tmp_out = Path(tempfile.gettempdir()) / f"{folder}_{AUDIO_PROXY_NAME}"
    ok_build, msg_build = _build_audio_proxy_wav(src_audio, tmp_out)
    if not ok_build:
        return False, msg_build
    pfx = st.session_state.r2_prefix.strip("/")
    key = f"{pfx}/captures/{folder}/{AUDIO_PROXY_NAME}" if pfx else f"captures/{folder}/{AUDIO_PROXY_NAME}"
    ok_up, msg_up = st.session_state.r2_client.upload_file(str(tmp_out), key)
    try:
        if tmp_out.exists():
            tmp_out.unlink()
    except Exception:
        pass
    if not ok_up:
        return False, f"Upload fehlgeschlagen: {msg_up}"
    return True, ""


def _cloud_framepack_prefix(folder: str) -> str:
    pfx = st.session_state.r2_prefix.strip("/")
    return f"{pfx}/captures/{folder}/frames_1fps" if pfx else f"captures/{folder}/frames_1fps"


def _upload_framepack_1fps(src_video: Path, folder: str, progress_cb=None) -> tuple[bool, str, int, str]:
    """
    Extract 1 fps frames and upload as frame-pack:
      captures/<folder>/frames_1fps/000000.jpg
      captures/<folder>/frames_1fps/index.json
    """
    if st.session_state.r2_client is None:
        return False, "Cloud Client nicht verbunden.", 0, ""

    cap = cv2.VideoCapture(str(src_video))
    if not cap.isOpened():
        return False, f"Video kann nicht geoeffnet werden: {src_video.name}", 0, ""

    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if fps <= 0:
            fps = 25.0
        duration_s = (frame_count / fps) if frame_count > 0 else 0.0
        seconds = max(1, int(np.ceil(duration_s)))
        prefix = _cloud_framepack_prefix(folder)
        uploaded = 0
        entries = []

        for sec in range(seconds):
            cap.set(cv2.CAP_PROP_POS_MSEC, float(sec) * 1000.0)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue

            # Optional downscale (biggest size lever) while keeping aspect ratio.
            if FRAMEPACK_MAX_WIDTH and FRAMEPACK_MAX_WIDTH > 0:
                h0, w0 = frame.shape[:2]
                if w0 > FRAMEPACK_MAX_WIDTH:
                    new_w = int(FRAMEPACK_MAX_WIDTH)
                    new_h = max(1, int(round(h0 * (new_w / float(w0)))))
                    frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)

            ok_enc, use_buf = cv2.imencode(
                ".jpg",
                frame,
                [int(cv2.IMWRITE_JPEG_QUALITY), int(FRAMEPACK_JPEG_QUALITY)],
            )
            if not ok_enc:
                continue
            use_size = len(use_buf)
            use_q = int(FRAMEPACK_JPEG_QUALITY)

            fname = f"{sec:06d}.jpg"
            key = f"{prefix}/{fname}"
            ok_up, msg_up = st.session_state.r2_client.upload_bytes(
                use_buf.tobytes(), key, content_type="image/jpeg"
            )
            if not ok_up:
                return False, f"Upload fehlgeschlagen ({fname}): {msg_up}", uploaded, ""
            uploaded += 1
            entries.append({"sec": sec, "file": fname, "bytes": int(use_size), "quality": int(use_q)})
            if progress_cb:
                progress_cb((sec + 1) / seconds, f"Frames: {sec + 1}/{seconds}")

        index_payload = {
            "type": "frame_pack",
            "sample_rate_hz": 1.0,
            "source_video": src_video.name,
            "source_fps": fps,
            "duration_s": duration_s,
            "frame_count": uploaded,
            "frames": entries,
            "created_at": datetime.utcnow().isoformat() + "Z",
        }
        ok_idx, msg_idx = st.session_state.r2_client.upload_string(
            json.dumps(index_payload, ensure_ascii=False, indent=2),
            f"{prefix}/index.json",
        )
        if not ok_idx:
            return False, f"index.json Upload fehlgeschlagen: {msg_idx}", uploaded, ""

        audio_note = ""
        if AUDIO_PROXY_ENABLED:
            ok_a, msg_a = _upload_audio_proxy_1k(folder)
            if ok_a:
                audio_note = " + AudioProxy"
            else:
                audio_note = f" | AudioProxy: {msg_a}"
        return True, "", uploaded, audio_note
    except Exception as e:
        return False, str(e), 0, ""
    finally:
        cap.release()


def _start_sync_run(selected_folders: list[str]):
    queue_rows = st.session_state.sync_queue_rows or []
    overview_rows = st.session_state.sync_overview_rows or []
    if selected_folders:
        selected_set = set(selected_folders)
        # Explicit user selection should be honored independent of current status.
        run_queue = [r for r in overview_rows if str(r.get("capture_folder", "")) in selected_set]
    else:
        run_queue = list(queue_rows)
    st.session_state.sync_run_queue = run_queue
    st.session_state.sync_run_total = len(run_queue)
    st.session_state.sync_run_idx = 0
    st.session_state.sync_run_started_ts = time.time()
    st.session_state.sync_run_selected_folders = list(selected_folders or [])
    st.session_state.sync_running = len(run_queue) > 0
    st.session_state.sync_stop_requested = False


def _refresh_sync_overview_live(table_slot=None, progress_slot=None):
    st.session_state.sync_refresh_running = True
    st.session_state.sync_editor_value = None
    st.session_state.sync_selected_folders = []
    folders = sorted(set(_get_local_capture_folders()))
    rows = [
        {
            "auswaehlen": False,
            "capture_folder": f,
            "reduziert_in_cloud": "...",
            "status": "Pruefung...",
            "cloud_framepack_anzahl": 0,
        }
        for f in folders
    ]
    st.session_state.sync_overview_rows = list(rows)
    st.session_state.sync_queue_rows = []
    total = len(folders)

    if table_slot is not None:
        table_slot.dataframe(
            pd.DataFrame(rows)[["capture_folder", "reduziert_in_cloud", "status"]],
            width="stretch",
            hide_index=True,
            height=340,
            column_config={
                "capture_folder": st.column_config.TextColumn("MAT/Folder", width="large"),
                "reduziert_in_cloud": st.column_config.TextColumn("Reduzierte Version in Cloud", width="large"),
                "status": st.column_config.TextColumn("Status", width="medium"),
            },
        )

    prog = None
    if progress_slot is not None and total > 0:
        prog = progress_slot.progress(0.0, text=f"Sync-Uebersicht: 0/{total} geprueft (0%)")

    for idx, folder in enumerate(folders):
        local_ok, _ = _has_local_fullfps_video(folder)
        if local_ok:
            src_video = _find_local_fullfps_video(folder)
            cloud_complete, cloud_count, expected_count, cloud_text = _cloud_reduced_completeness(folder, src_video)
            rows[idx]["reduziert_in_cloud"] = cloud_text
            rows[idx]["status"] = "OK" if cloud_complete else ""
            rows[idx]["cloud_framepack_anzahl"] = int(cloud_count)
            rows[idx]["expected_framepack_anzahl"] = int(expected_count)
        else:
            rows[idx]["reduziert_in_cloud"] = "-"
            rows[idx]["status"] = "Ohne Video"
            rows[idx]["cloud_framepack_anzahl"] = 0
            rows[idx]["expected_framepack_anzahl"] = 0

        st.session_state.sync_overview_rows = list(rows)
        st.session_state.sync_queue_rows = [
            r for r in rows if str(r.get("reduziert_in_cloud", "")).startswith("Nein")
        ]

        # Reduce redraw frequency to avoid table jitter.
        should_redraw = (idx == total - 1) or (idx % 3 == 0)
        if table_slot is not None and should_redraw:
            table_slot.dataframe(
                pd.DataFrame(rows)[["capture_folder", "reduziert_in_cloud", "status"]],
                width="stretch",
                hide_index=True,
                height=340,
                column_config={
                    "capture_folder": st.column_config.TextColumn("MAT/Folder", width="large"),
                    "reduziert_in_cloud": st.column_config.TextColumn("Reduzierte Version in Cloud", width="large"),
                    "status": st.column_config.TextColumn("Status", width="medium"),
                },
            )
        if prog is not None:
            done = idx + 1
            prog.progress(done / total, text=f"Sync-Uebersicht: {done}/{total} geprueft ({int((done/total)*100)}%)")

    final_rows = [r for r in rows if str(r.get("status", "")) != "Ohne Video"]
    st.session_state.sync_overview_rows = final_rows
    st.session_state.sync_queue_rows = [
        r for r in final_rows if str(r.get("reduziert_in_cloud", "")).startswith("Nein")
    ]
    st.session_state.sync_editor_value = pd.DataFrame(final_rows)[
        ["auswaehlen", "capture_folder", "reduziert_in_cloud", "status"]
    ].copy() if final_rows else pd.DataFrame(
        columns=["auswaehlen", "capture_folder", "reduziert_in_cloud", "status"]
    )
    st.session_state.sync_refresh_running = False


def _set_sync_row_status(folder: str, text: str):
    rows = list(st.session_state.sync_overview_rows or [])
    for r in rows:
        if str(r.get("capture_folder", "")) == str(folder):
            r["status"] = text
            break
    st.session_state.sync_overview_rows = rows

    df = st.session_state.get("sync_editor_value")
    if isinstance(df, pd.DataFrame) and (not df.empty):
        if "capture_folder" in df.columns and "status" in df.columns:
            mask = df["capture_folder"].astype(str) == str(folder)
            if mask.any():
                df.loc[mask, "status"] = text
                st.session_state.sync_editor_value = df


def _finish_sync_run(final_msg: str, kind: str):
    st.session_state.sync_running = False
    st.session_state.sync_stop_requested = False
    set_status(final_msg, kind)


def _format_eta_seconds(sec: float) -> str:
    sec = max(0, int(sec))
    mm, ss = divmod(sec, 60)
    hh, mm = divmod(mm, 60)
    if hh > 0:
        return f"{hh:02d}:{mm:02d}:{ss:02d}"
    return f"{mm:02d}:{ss:02d}"


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
    return clamp_roi_to_video(x, y, w, h, vid_w, vid_h)


def _get_dynamic_roi_target_width(default_width: int = 620, anchor_id: str = "roi-left-width-probe") -> int:
    # Fallback-first for stability.
    width = int(default_width)
    if streamlit_js_eval is None:
        return width
    try:
        # streamlit_js_eval only re-evaluates when the expression string changes.
        # We install a one-time resize bridge that proactively sends updated widths
        # back to Python, which triggers reruns on browser resize.
        expr = (
            "(function(){"
            "const d = window.parent?.document || document;"
            f"const anchorId = {json.dumps(str(anchor_id))};"
            "const readW = function(){"
            "  const a = d.getElementById(anchorId);"
            "  const col = a?.closest('[data-testid=\"column\"]');"
            "  const p = a?.parentElement;"
            "  const block = d.querySelector('.block-container');"
            "  return Math.round(col?.clientWidth || p?.clientWidth || block?.clientWidth || window.parent?.innerWidth || window.innerWidth || 0);"
            "};"
            "if (!window.__roiResizeBridgeInstalled) {"
            "  window.__roiResizeBridgeInstalled = true;"
            "  let t = null;"
            "  window.addEventListener('resize', function(){"
            "    clearTimeout(t);"
            "    t = setTimeout(function(){"
            "      try { sendDataToPython({value: readW(), dataType: 'json'}); } catch (e) {}"
            "    }, 120);"
            "  });"
            "}"
            "return readW();"
            "})()"
        )
        container_w = streamlit_js_eval(
            js_expressions=expr,
            key="roi_viewport_width_probe",
            want_output=True,
        )
        if isinstance(container_w, (int, float)) and float(container_w) > 300:
            cw = int(round(float(container_w)))
            width = max(260, min(920, cw - 24))
    except Exception:
        # Never break app render because of viewport probing.
        pass
    return width


def _try_auto_connect_once():
    if str(st.session_state.get("compressed_db_mode") or "local").strip().lower() != "r2":
        return
    if st.session_state.r2_connected or st.session_state.auto_connect_attempted:
        return

    st.session_state.auto_connect_attempted = True
    acc = st.session_state.r2_account_id.strip()
    key = st.session_state.r2_access_key_id.strip()
    sec = st.session_state.r2_secret_access_key.strip()
    bkt = st.session_state.r2_bucket.strip()
    if not all([acc, key, sec, bkt]):
        return

    ok, msg, client = _connect_r2_with_retry(acc, key, sec, bkt, max_attempts=3, delay_s=1.2)
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


def _connect_r2_with_retry(acc: str, key: str, sec: str, bkt: str, *, max_attempts: int = 3, delay_s: float = 1.2):
    last_msg = ""
    attempts = max(1, int(max_attempts))
    for i in range(attempts):
        ok, msg, client = connect_r2_client(acc, key, sec, bkt)
        if ok and client is not None:
            if i == 0:
                return True, str(msg or "ok"), client
            return True, f"{str(msg or 'ok')} (verbunden nach {i+1}/{attempts} Versuchen)", client
        last_msg = str(msg or "unbekannter Fehler")
        if i < attempts - 1:
            time.sleep(max(0.0, float(delay_s)))
    return False, f"{last_msg} (nach {attempts} Versuchen)", None

def _try_auto_connect_local_once():
    if bool(st.session_state.get("local_connected")) or st.session_state.get("local_auto_connect_attempted"):
        return
    st.session_state.local_auto_connect_attempted = True
    lp_str = str(st.session_state.get("compressed_db_default_path") or (st.secrets.get("local") or {}).get("default_path") or "").strip()
    if not lp_str:
        return
    try:
        lp = Path(lp_str).expanduser().resolve()
        if not lp.exists() or not lp.is_dir():
            return
        if not (lp / "captures").exists():
            return
        local_client = LocalStorageAdapter(str(lp))
        ok_local, _ = local_client.test_connection()
        if ok_local:
            st.session_state.local_connected = True
            st.session_state.local_client = local_client
            st.session_state.local_base_path = str(lp)
            st.session_state.local_root = ""
    except Exception:
        pass


def _file_icon(name):
    ext = Path(name).suffix.lower()
    return {
        ".mp4": "[VID]", ".mov": "[VID]", ".avi": "[VID]", ".mkv": "[VID]",
        ".mat": "[MAT]", ".json": "[JSON]", ".wav": "[AUD]", ".mp3": "[AUD]",
        ".png": "[IMG]", ".jpg": "[IMG]", ".jpeg": "[IMG]",
        ".txt": "[TXT]", ".md": "[TXT]",
    }.get(ext, "[FILE]")

def draw_rois(frame, rois, sel, vid_w, vid_h, skip_idx=None):
    img = frame.copy()
    dh, dw = img.shape[:2]
    sx = dw/vid_w if vid_w else 1.0
    sy = dh/vid_h if vid_h else 1.0
    for i, r in enumerate(rois):
        if skip_idx is not None and i == skip_idx:
            continue
        x,y,w,h = int(r["x"]*sx),int(r["y"]*sy),int(r["w"]*sx),int(r["h"]*sy)
        is_track = r["name"]=="track_minimap"
        color = (40, 220, 180) if is_track else ((255, 225, 40) if i == sel else (255, 80, 80))
        thick = 3 if i == sel else 2
        cv2.rectangle(img,(x,y),(x+w,y+h),color,thick)
        cv2.putText(img,r["name"],(x+3,y+14),cv2.FONT_HERSHEY_SIMPLEX,.44,color,1,cv2.LINE_AA)
    return img


@st.cache_resource(show_spinner=False)
def _opencv_gui_available():
    try:
        info = cv2.getBuildInformation()
    except Exception:
        return False, "OpenCV Build-Info nicht verfuegbar."
    # OpenCV reports GUI backend in this section. Headless builds usually show NONE.
    gui_lines = [ln.strip() for ln in info.splitlines() if ln.strip().startswith("GUI:")]
    if not gui_lines:
        return False, "OpenCV GUI-Backend unbekannt."
    gui_line = gui_lines[0]
    if "NONE" in gui_line.upper():
        return False, (
            "OpenCV ist als headless installiert (ohne GUI). "
            "Bitte in der venv umstellen: "
            "`pip uninstall -y opencv-python-headless && pip install opencv-python`"
        )
    return True, gui_line


def _pick_roi_with_cv_window(frame_rgb):
    gui_ok, gui_msg = _opencv_gui_available()
    if not gui_ok:
        return False, gui_msg, None
    try:
        view = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
        cv2.namedWindow("ROI Auswahl", cv2.WINDOW_NORMAL)
        x, y, w, h = cv2.selectROI("ROI Auswahl", view, showCrosshair=True, fromCenter=False)
        cv2.destroyWindow("ROI Auswahl")
    except Exception as e:
        return False, f"ROI-Fenster konnte nicht geoeffnet werden: {e}", None
    if int(w) < 1 or int(h) < 1:
        return False, "Keine ROI ausgewaehlt.", None
    return True, "", {"x": int(x), "y": int(y), "w": int(w), "h": int(h)}

def _sanitize_rois(rois):
    out = []
    for r in rois or []:
        if not isinstance(r, dict):
            continue
        nr = dict(r)
        nr["fmt"] = _normalize_roi_format(nr.get("fmt", "any"))
        nr.pop("pattern", None)
        nr["max_scale"] = float(st.session_state.get("roi_global_scale", 1.2))
        out.append(nr)
    return out

def _roi_ocr_probe_indices() -> list[int]:
    return [
        i for i, r in enumerate(st.session_state.get("rois", []) or [])
        if str(r.get("name", "")).strip().lower() != "track_minimap"
    ]


def _roi_ocr_all_ok() -> bool:
    rois = st.session_state.get("rois", []) or []
    indices = _roi_ocr_probe_indices()
    return bool(indices) and all(bool(rois[i].get("ocr_test_ok", False)) for i in indices)


def _run_roi_ocr_probe_now(frame, fw, fh, indices: list[int]) -> tuple[bool, str]:
    """Run OCR probe synchronously in the current button run to avoid a pre-run page refresh."""
    if frame is None or not indices:
        st.session_state.roi_ocr_probe_result = None
        return False, "Kein Frame oder keine OCR-ROIs zum Testen vorhanden."
    tess_cmd = find_tesseract_cmd()
    if not tess_cmd:
        st.session_state.roi_ocr_probe_result = None
        return False, "Tesseract wurde nicht gefunden. Installiere Tesseract oder setze TESSERACT_CMD."
    all_probe_results = []
    for _idx in indices:
        probe_roi = {
            **st.session_state.rois[_idx],
            "max_scale": float(st.session_state.get("roi_global_scale", 1.2)),
        }
        probe = diagnose_roi_ocr(
            frame,
            probe_roi,
            (int(fw), int(fh)),
            tmp_root=LOG_DIR / "ocr_tmp",
        )
        _conf = float(probe.get("confidence", 0.0) or 0.0)
        _scale = probe.get("scale", "")
        _fr_up = probe.get("frUp", probe.get("fr_up", probe.get("variant", "")))
        _details = (
            f"raw={probe.get('raw', '')}; "
            f"conf={_conf:.2f}; "
            f"scale={_scale}; "
            f"frUp={_fr_up}"
        )
        st.session_state.rois[_idx] = {
            **st.session_state.rois[_idx],
            "ocr_test_ok": bool(probe.get("ok")),
            "ocr_test_value": probe.get("value", ""),
            "ocr_test_raw": probe.get("raw", ""),
            "ocr_test_confidence": _conf,
            "ocr_test_scale": _scale,
            "ocr_test_frUp": _fr_up,
            "ocr_test_error": probe.get("error", ""),
            "ocr_test_details": _details,
        }
        all_probe_results.append({
            "idx": _idx,
            "name": st.session_state.rois[_idx].get("name", ""),
            **probe,
        })
    st.session_state.roi_ocr_probe_result = all_probe_results
    st.session_state.roi_editor_df = None
    ok = _roi_ocr_all_ok()
    return ok, "OCR-Test ROI abgeschlossen." if ok else "OCR-Test ROI abgeschlossen; mindestens eine ROI ist noch nicht OK."


def _run_video_ocr_full_now() -> tuple[bool, str, dict]:
    """Run full OCR over the selected time range and persist into recordResult.ocr."""
    indices = _roi_ocr_probe_indices()
    if not indices:
        st.session_state.roi_ocr_full_result = None
        return False, "Keine OCR-ROIs vorhanden (nur track_minimap oder leer).", {}
    tess_cmd = find_tesseract_cmd()
    if not tess_cmd:
        st.session_state.roi_ocr_full_result = None
        return False, "Tesseract wurde nicht gefunden. Installiere Tesseract oder setze TESSERACT_CMD.", {}
    if not _has_media_source():
        st.session_state.roi_ocr_full_result = None
        return False, "Kein Video/Framepack geladen.", {}

    try:
        start_s = float(st.session_state.get("t_start", 0.0) or 0.0)
        end_s = float(st.session_state.get("t_end", 0.0) or 0.0)
    except Exception:
        start_s, end_s = 0.0, 0.0
    if (not np.isfinite(start_s)) or (not np.isfinite(end_s)) or end_s <= start_s:
        st.session_state.roi_ocr_full_result = None
        return False, "Ungueltiges Start/Ende-Zeitfenster.", {}

    fps = float(st.session_state.get("vid_fps", 1.0) or 1.0)
    fps = max(1.0, fps)
    step = 1.0 / fps
    n = int(np.floor((end_s - start_s) / step)) + 1
    if n > 120000:
        st.session_state.roi_ocr_full_result = None
        return False, f"OCR-Zeitfenster zu gross ({n} Frames). Bitte Zeitfenster verkuerzen.", {}
    times: list[float] = [float(start_s + i * step) for i in range(max(1, n))]

    raw_rows: list[dict] = []
    clean_rows: list[dict] = []
    roi_stats: dict[str, dict] = {}
    for _idx in indices:
        nm = str(st.session_state.rois[_idx].get("name", f"roi_{_idx}") or f"roi_{_idx}")
        roi_stats[nm] = {"ok": 0, "seen": 0}

    for t_s in times:
        frame = _get_media_frame(float(t_s))
        if frame is None:
            continue
        fh, fw = frame.shape[:2]
        raw_row = {"time_s": float(t_s)}
        clean_row = {"time_s": float(t_s)}
        for _idx in indices:
            roi_cfg = {
                **st.session_state.rois[_idx],
                "max_scale": float(st.session_state.get("roi_global_scale", 1.2)),
            }
            nm = str(roi_cfg.get("name", f"roi_{_idx}") or f"roi_{_idx}")
            probe = diagnose_roi_ocr(frame, roi_cfg, (int(fw), int(fh)), tmp_root=LOG_DIR / "ocr_tmp")
            raw_row[nm] = str(probe.get("raw", "") or "")
            clean_row[nm] = str(probe.get("value", "") or "") if bool(probe.get("ok")) else ""
            roi_stats[nm]["seen"] += 1
            if bool(probe.get("ok")):
                roi_stats[nm]["ok"] += 1
        raw_rows.append(raw_row)
        clean_rows.append(clean_row)

    for _idx in indices:
        nm = str(st.session_state.rois[_idx].get("name", f"roi_{_idx}") or f"roi_{_idx}")
        seen_n = int((roi_stats.get(nm) or {}).get("seen", 0))
        ok_n = int((roi_stats.get(nm) or {}).get("ok", 0))
        is_ok = bool(seen_n > 0 and ok_n > 0)
        st.session_state.rois[_idx] = {
            **st.session_state.rois[_idx],
            "ocr_test_ok": is_ok,
            "ocr_test_value": f"{ok_n}/{seen_n}",
            "ocr_test_details": f"ok_frames={ok_n}; seen_frames={seen_n}",
        }

    rr_doc = _build_save_mat_struct(build_result_json(), no_roi=False, video_faulty=False).get("recordResult", {})
    rr_doc = _mat_struct_to_plain(rr_doc)
    if not isinstance(rr_doc, dict):
        rr_doc = {}
    ocr_doc = rr_doc.get("ocr", {}) if isinstance(rr_doc.get("ocr", {}), dict) else {}
    ocr_doc["table"] = raw_rows
    ocr_doc["cleaned"] = clean_rows
    ocr_doc["created"] = datetime.now().isoformat(timespec="seconds")
    rr_doc["ocr"] = ocr_doc

    cf = _current_capture_folder() or str(st.session_state.get("capture_folder") or "")
    ok_save, msg_save, _json_bytes = _save_fields_to_local_json({"ocr": ocr_doc}, cf, base_rr=rr_doc)
    if not ok_save:
        st.session_state.roi_ocr_full_result = {"ok": False, "error": str(msg_save), "rows": int(len(clean_rows))}
        return False, f"OCR-Auswertung abgeschlossen, Speichern fehlgeschlagen: {msg_save}", st.session_state.roi_ocr_full_result

    out = {
        "ok": True,
        "rows": int(len(clean_rows)),
        "raw_rows": int(len(raw_rows)),
        "start_s": float(start_s),
        "end_s": float(end_s),
        "source": src,
        "json_key": _r2_json_sidecar_key(mat_key),
        "roi_stats": roi_stats,
    }
    st.session_state.roi_ocr_full_result = out
    try:
        _invalidate_and_update_mat_selection_for_capture(str(cf), mat_key)
    except Exception:
        pass


def _run_video_ocr_fullvideo_framewise_now(
    progress_cb=None,
    stop_cb=None,
    rois_override=None,
    capture_folder_override: str = "",
    video_path_override: str = "",
    target_fps_str: str = "2",
    track_params_override: dict | None = None,
) -> tuple[bool, str, dict]:
    """Run OCR frame-by-frame on the full local video (not framepack/lite)."""
    # Snapshot session-state values needed for track detection (session state is not
    # accessible from background threads — caller must pass these via track_params_override).
    _tpo = track_params_override if isinstance(track_params_override, dict) else {}
    _moving_pt_color_range = _tpo.get("moving_pt_color_range") or st.session_state.get("moving_pt_color_range") or {}
    _ref_track_img = _tpo.get("ref_track_img") if "ref_track_img" in _tpo else st.session_state.get("ref_track_img")
    _minimap_pts = list(_tpo.get("minimap_pts") or st.session_state.get("minimap_pts") or [])
    _ref_track_pts = list(_tpo.get("ref_track_pts") or st.session_state.get("ref_track_pts") or [])
    _cl_raw = _tpo.get("centerline_px") if _tpo.get("centerline_px") is not None else st.session_state.get("centerline_px")
    _centerline_px = (_cl_raw.tolist() if hasattr(_cl_raw, "tolist") else list(_cl_raw)) if _cl_raw is not None else []
    _roi_global_scale = float(_tpo.get("roi_global_scale") or st.session_state.get("roi_global_scale") or 1.2)

    rois_active = list(rois_override if isinstance(rois_override, list) else (st.session_state.get("rois", []) or []))
    indices = [
        i for i, r in enumerate(rois_active)
        if str((r or {}).get("name", "")).strip().lower() != "track_minimap"
        and float((r or {}).get("w", 0.0) or 0.0) > 0.0
        and float((r or {}).get("h", 0.0) or 0.0) > 0.0
    ]
    if not indices:
        st.session_state.video_ocr_full_result = None
        return False, "Keine OCR-ROIs vorhanden (nur track_minimap oder leer).", {}
    tess_cmd = find_tesseract_cmd()
    if not tess_cmd:
        st.session_state.video_ocr_full_result = None
        return False, "Tesseract wurde nicht gefunden. Installiere Tesseract oder setze TESSERACT_CMD.", {}

    capture_folder = str(capture_folder_override or "").strip()
    if not capture_folder:
        capture_folder = _current_capture_folder() or str(st.session_state.get("capture_folder") or "").strip()
    if not capture_folder:
        st.session_state.video_ocr_full_result = None
        return False, "Kein capture_folder aktiv. Bitte zuerst MAT/JSON laden.", {}
    video_path = None
    vp_ovr = str(video_path_override or "").strip()
    if vp_ovr:
        try:
            cand = Path(vp_ovr).expanduser().resolve()
            if cand.exists() and cand.is_file():
                video_path = cand
        except Exception:
            video_path = None
    if video_path is None:
        video_path = _find_local_fullfps_video(capture_folder)
    if video_path is None or (not video_path.exists()):
        st.session_state.video_ocr_full_result = None
        return False, "Kein Vollvideo gefunden. Bitte zuerst das Originalvideo lokal laden/herunterladen.", {}

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        st.session_state.video_ocr_full_result = None
        return False, f"Video konnte nicht geöffnet werden: {video_path.name}", {}

    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    if (not np.isfinite(fps)) or fps <= 0:
        fps = max(1.0, float(st.session_state.get("vid_fps", 25.0) or 25.0))
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if frame_count <= 0:
        cap.release()
        st.session_state.video_ocr_full_result = None
        return False, f"Ungültige Frame-Anzahl: {video_path.name}", {}

    fps_mode = str(target_fps_str or "2").strip().lower()
    if fps_mode == "max":
        frame_step = 1
    else:
        try:
            target_fps = float(fps_mode)
        except Exception:
            target_fps = 2.0
        if target_fps <= 0:
            target_fps = 2.0
        frame_step = max(1, int(round(fps / target_fps)))

    # Read start_s / end_s from current session state (t_start / t_end set by ROI Setup).
    # These are the absolute boundaries; OCR must not go outside them.
    _dur_full = float(frame_count) / max(fps, 1e-9)
    _start_s = float(st.session_state.get("t_start") or 0.0)
    _end_s = float(st.session_state.get("t_end") or _dur_full)
    _start_s = max(0.0, min(_start_s, _dur_full))
    _end_s = max(_start_s + 0.1, min(_end_s, _dur_full))
    _start_frame = int(_start_s * fps)
    _end_frame = int(_end_s * fps)
    frames_in_range = max(1, _end_frame - _start_frame)

    processed_target = max(1, int(math.ceil(frames_in_range / max(1, frame_step))))
    checkpoint_every = max(1, processed_target // 10)

    raw_rows: list[dict] = []
    clean_rows: list[dict] = []
    roi_stats: dict[str, dict] = {}
    for _idx in indices:
        nm = str((rois_active[_idx] or {}).get("name", f"roi_{_idx}") or f"roi_{_idx}")
        roi_stats[nm] = {"ok": 0, "seen": 0}

    track_roi = next(
        (
            r for r in list(rois_active or [])
            if str(r.get("name", "")).strip().lower() == "track_minimap"
            and float(r.get("w", 0.0) or 0.0) > 0.0
            and float(r.get("h", 0.0) or 0.0) > 0.0
        ),
        None,
    )
    has_track_cal = bool(
        track_roi is not None
        and _ref_track_img is not None
        and isinstance(_minimap_pts, list)
        and isinstance(_ref_track_pts, list)
        and len(_minimap_pts) >= 4
        and len(_ref_track_pts) >= 4
    )
    mini_pts = _minimap_pts
    ref_pts = _ref_track_pts
    H_fallback = None
    if len(mini_pts) >= 4 and len(ref_pts) >= 4:
        try:
            src = np.asarray(mini_pts[:8], dtype=np.float32).reshape(-1, 2)
            dst = np.asarray(ref_pts[:8], dtype=np.float32).reshape(-1, 2)
            if src.shape[0] >= 4 and dst.shape[0] >= 4:
                H_fallback, _mask = cv2.findHomography(src, dst, method=0)
        except Exception:
            H_fallback = None

    def _centerline_progress_percent(ref_pt, centerline_px) -> float | None:
        if ref_pt is None:
            return None
        try:
            cl = np.asarray(centerline_px, dtype=float)
            if cl.ndim != 2 or cl.shape[0] < 2 or cl.shape[1] < 2:
                return None
            p = np.asarray(ref_pt, dtype=float).ravel()
            if p.size < 2 or not np.all(np.isfinite(p[:2])):
                return None
            p = p[:2]
            d = np.diff(cl[:, :2], axis=0)
            seg_len = np.sqrt(np.sum(d * d, axis=1))
            cum = np.concatenate(([0.0], np.cumsum(seg_len)))
            total = float(cum[-1])
            if total <= 1e-9:
                return None
            best_d2 = float("inf")
            best_s = 0.0
            for i in range(len(seg_len)):
                v = cl[i + 1, :2] - cl[i, :2]
                l2 = float(np.dot(v, v))
                if l2 <= 0:
                    continue
                u = float(np.clip(np.dot(p - cl[i, :2], v) / l2, 0.0, 1.0))
                q = cl[i, :2] + u * v
                d2 = float(np.sum((p - q) ** 2))
                if d2 < best_d2:
                    best_d2 = d2
                    best_s = float(cum[i] + u * seg_len[i])
            return float(np.clip(100.0 * best_s / total, 0.0, 100.0))
        except Exception:
            return None

    progress_step = int(_tpo.get("progress_step_frames") or st.session_state.get("video_ocr_live_progress_step_frames") or 2)
    progress_step = max(1, progress_step)

    # Seek to start_s boundary
    if _start_frame > 0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, _start_frame)

    processed = 0
    frame_idx_native = _start_frame
    cancelled = False
    save_error = ""

    def _save_ocr_progress(partial: bool) -> tuple[bool, str]:
        rr_doc_local = _build_save_mat_struct(build_result_json(), no_roi=False, video_faulty=False).get("recordResult", {})
        rr_doc_local = _mat_struct_to_plain(rr_doc_local)
        if not isinstance(rr_doc_local, dict):
            rr_doc_local = {}
        ocr_doc_local = rr_doc_local.get("ocr", {}) if isinstance(rr_doc_local.get("ocr", {}), dict) else {}
        ocr_doc_local["table"] = list(raw_rows)
        ocr_doc_local["cleaned"] = list(clean_rows)
        ocr_doc_local["created"] = datetime.now().isoformat(timespec="seconds")
        ocr_doc_local["sample_rate_hz"] = float(max(1e-9, fps / max(1, frame_step)))
        ocr_doc_local["source_fps"] = float(max(1e-9, fps))
        ocr_doc_local["frame_step"] = int(max(1, frame_step))
        ocr_doc_local["fps_mode"] = str(fps_mode)
        _params = ocr_doc_local.get("params") if isinstance(ocr_doc_local.get("params"), dict) else {}
        _params.setdefault("start_s", 0.0)
        _params["end_s"] = float(raw_rows[-1]["time_s"]) if raw_rows else 0.0
        if partial:
            _params["partial"] = True
        else:
            _params.pop("partial", None)
        ocr_doc_local["params"] = _params
        rr_doc_local["ocr"] = ocr_doc_local

        cf_local = str(capture_folder or "").strip()
        ok_local, msg_local, _json_bytes_local = _save_fields_to_local_json({"ocr": ocr_doc_local}, cf_local, base_rr=rr_doc_local)
        if not ok_local:
            return False, str(msg_local)
        return True, str(msg_local)

    try:
        while True:
            if callable(stop_cb):
                try:
                    if bool(stop_cb()):
                        cancelled = True
                        break
                except Exception:
                    pass
            # Stop at end_s boundary
            if frame_idx_native >= _end_frame:
                break
            ok, frame_bgr = cap.read()
            if (not ok) or frame_bgr is None:
                break
            t_s = float(frame_idx_native) / float(max(1e-9, fps))
            frame = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            fh, fw = frame.shape[:2]
            raw_row = {"time_s": float(t_s), "frame_idx": int(frame_idx_native)}
            clean_row = {"time_s": float(t_s), "frame_idx": int(frame_idx_native)}
            live_snapshot = {"time_s": float(t_s), "frame_idx": int(frame_idx_native)}
            for _idx in indices:
                roi_cfg = {
                    **(rois_active[_idx] or {}),
                    "max_scale": _roi_global_scale,
                }
                nm = str(roi_cfg.get("name", f"roi_{_idx}") or f"roi_{_idx}")
                probe = diagnose_roi_ocr(frame, roi_cfg, (int(fw), int(fh)), tmp_root=LOG_DIR / "ocr_tmp")
                raw_row[nm] = str(probe.get("raw", "") or "")
                clean_row[nm] = str(probe.get("value", "") or "") if bool(probe.get("ok")) else ""
                live_snapshot[nm] = clean_row[nm]
                roi_stats[nm]["seen"] += 1
                if bool(probe.get("ok")):
                    roi_stats[nm]["ok"] += 1

            if track_roi is not None:
                # Keep track columns visible in live table even when detection misses.
                for _k in ("track_minimap_x", "track_minimap_y", "track_xy_x", "track_xy_y", "track_pct"):
                    clean_row[_k] = np.nan
                    live_snapshot[_k] = np.nan
                clean_row["track_minimap_found"] = 0
                live_snapshot["track_minimap_found"] = 0
                try:
                    crop = extract_minimap_crop(frame, track_roi, fw, fh)
                except Exception:
                    crop = None
                if crop is not None:
                    mp = detect_moving_point(crop, _moving_pt_color_range)
                    if isinstance(mp, dict):
                        x_mp = float(mp.get("x", 0.0) or 0.0)
                        y_mp = float(mp.get("y", 0.0) or 0.0)
                        clean_row["track_minimap_x"] = x_mp
                        clean_row["track_minimap_y"] = y_mp
                        live_snapshot["track_minimap_x"] = x_mp
                        live_snapshot["track_minimap_y"] = y_mp
                        clean_row["track_minimap_found"] = 1
                        live_snapshot["track_minimap_found"] = 1
                        ref_pt = None
                        if has_track_cal:
                            cmp = compare_minimap_to_reference(
                                crop,
                                _ref_track_img,
                                _minimap_pts,
                                _ref_track_pts,
                            )
                            if isinstance(cmp, dict) and not cmp.get("error"):
                                ref_pt = project_point_with_homography((x_mp, y_mp), cmp.get("H"))
                        elif H_fallback is not None:
                            try:
                                p = np.array([[[float(x_mp), float(y_mp)]]], dtype=np.float32)
                                q = cv2.perspectiveTransform(p, H_fallback)
                                ref_pt = [float(q[0, 0, 0]), float(q[0, 0, 1])]
                            except Exception:
                                ref_pt = None
                        if isinstance(ref_pt, (list, tuple, np.ndarray)) and len(ref_pt) >= 2:
                            rx = float(ref_pt[0])
                            ry = float(ref_pt[1])
                            clean_row["track_xy_x"] = rx
                            clean_row["track_xy_y"] = ry
                            live_snapshot["track_xy_x"] = rx
                            live_snapshot["track_xy_y"] = ry
                            pct = _centerline_progress_percent(ref_pt, _centerline_px)
                            if pct is not None:
                                clean_row["track_pct"] = float(pct)
                                live_snapshot["track_pct"] = float(pct)
            raw_rows.append(raw_row)
            clean_rows.append(clean_row)
            processed += 1
            done_native = min(_end_frame, frame_idx_native + 1) - _start_frame
            total_native = frames_in_range
            if callable(progress_cb) and (processed <= 3 or processed % progress_step == 0 or done_native >= total_native):
                try:
                    progress_cb(done_native, total_native, t_s, dict(live_snapshot))
                except TypeError:
                    progress_cb(done_native, total_native, t_s)
                except Exception:
                    pass
            skipped = 0
            for _ in range(max(0, frame_step - 1)):
                if cap.grab():
                    skipped += 1
                else:
                    break
            frame_idx_native += 1 + skipped
            if processed % checkpoint_every == 0:
                _ok_ckpt, _msg_ckpt = _save_ocr_progress(partial=True)
                if not _ok_ckpt:
                    save_error = str(_msg_ckpt)
                    cancelled = True
                    break
    finally:
        cap.release()

    rois_session = list(st.session_state.get("rois") or [])
    for _idx in indices:
        nm = str((rois_active[_idx] or {}).get("name", f"roi_{_idx}") or f"roi_{_idx}")
        seen_n = int((roi_stats.get(nm) or {}).get("seen", 0))
        ok_n = int((roi_stats.get(nm) or {}).get("ok", 0))
        is_ok = bool(seen_n > 0 and ok_n > 0)
        if _idx < len(rois_session) and isinstance(rois_session[_idx], dict):
            rois_session[_idx] = {
                **rois_session[_idx],
                "ocr_test_ok": is_ok,
                "ocr_test_value": f"{ok_n}/{seen_n}",
                "ocr_test_details": f"ok_frames={ok_n}; seen_frames={seen_n}",
            }
    if rois_session:
        st.session_state.rois = rois_session

    if save_error:
        out_err = {"ok": False, "error": str(save_error), "rows": int(len(clean_rows)), "frames_processed": int(processed)}
        st.session_state.video_ocr_full_result = out_err
        return False, f"OCR-Zwischenspeicherung fehlgeschlagen: {save_error}", out_err

    ok_save, msg_save = _save_ocr_progress(partial=bool(cancelled))
    if not ok_save:
        out_err = {"ok": False, "error": str(msg_save), "rows": int(len(clean_rows)), "frames_processed": int(processed)}
        st.session_state.video_ocr_full_result = out_err
        return False, f"OCR-Auswertung abgeschlossen, Speichern fehlgeschlagen: {msg_save}", out_err

    out = {
        "ok": True,
        "rows": int(len(clean_rows)),
        "raw_rows": int(len(raw_rows)),
        "frames_processed": int(processed),
        "frames_total": int(frame_count),
        "fps": float(fps),
        "sample_fps": float(max(1e-9, fps / max(1, frame_step))),
        "frame_step": int(max(1, frame_step)),
        "fps_mode": str(fps_mode),
        "source": "full_video",
        "video_path": str(video_path),
        "capture_folder": str(capture_folder),
        "cancelled": bool(cancelled),
        "partial": bool(cancelled),
        "json_key": _r2_json_sidecar_key(mat_key),
        "roi_stats": roi_stats,
    }
    st.session_state.video_ocr_full_result = out
    st.session_state.roi_ocr_full_result = out
    try:
        _invalidate_and_update_mat_selection_for_capture(str(capture_folder), mat_key)
    except Exception:
        pass
    msg = (
        f"OCR vollstaendig ausgewertet (Full Video): {len(clean_rows)} Zeilen gespeichert."
        if not cancelled
        else f"OCR abgebrochen: {len(clean_rows)} Zeilen bis Abbruch gespeichert."
    )
    return True, msg, out


def _sync_compressed_storage_binding():
    """Bind compressed-storage client to selected backend (R2 or local)."""
    mode = str(st.session_state.get("compressed_db_mode") or "local").strip().lower()
    if mode == "local":
        local_ok = bool(st.session_state.get("local_connected")) and st.session_state.get("local_client") is not None
        if local_ok:
            st.session_state.r2_connected = True
            st.session_state.r2_client = st.session_state.local_client
            try:
                st.session_state.r2_prefix_options = list_root_prefixes(st.session_state.r2_client)
            except Exception:
                st.session_state.r2_prefix_options = [""]
            if str(st.session_state.get("r2_prefix") or "") not in list(st.session_state.get("r2_prefix_options") or [""]):
                st.session_state.r2_prefix = ""
        else:
            st.session_state.r2_connected = False
            st.session_state.r2_client = None
            st.session_state.r2_prefix_options = [""]
            st.session_state.r2_prefix = ""
        return

    # mode == "r2"
    if isinstance(st.session_state.get("r2_client"), LocalStorageAdapter):
        st.session_state.r2_connected = False
        st.session_state.r2_client = None
        st.session_state.r2_prefix_options = [""]
        st.session_state.r2_prefix = ""
    return True, f"OCR vollstaendig ausgewertet: {len(clean_rows)} Zeilen gespeichert.", out


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


def _mat_struct_to_plain(obj):
    """Convert scipy/h5 decoded MATLAB structs to savemat-friendly plain dicts."""
    obj = _mat_scalar(obj)
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return {str(k): _mat_struct_to_plain(v) for k, v in obj.items() if not str(k).startswith("#")}
    fields = getattr(obj, "_fieldnames", None)
    if fields:
        return {str(k): _mat_struct_to_plain(getattr(obj, k)) for k in fields}
    if isinstance(obj, np.ndarray):
        if obj.dtype == object:
            return np.array([_mat_struct_to_plain(v) for v in obj.ravel().tolist()], dtype=object).reshape(obj.shape)
        return obj
    if isinstance(obj, (np.generic,)):
        return obj.item()
    return obj


def _load_recordresult_template_fields(mat_path: str) -> dict:
    """Load only reusable recordResult.metadata from an existing MAT file.

    OCR/audio/validation are intentionally not copied: ROI Setup creates a new
    OCRExtractor-compatible OCR parameter block, while audio_rpm and validation
    are produced later by spectrogram analysis and validation.
    """
    out = {}
    if not mat_path:
        return out
    try:
        data = sio.loadmat(mat_path, squeeze_me=True, struct_as_record=False)
        rr = _mat_scalar(data.get("recordResult"))
        if rr is None:
            return out
        meta = _mat_obj_get(rr, "metadata")
        if meta is not None:
            out["metadata"] = _mat_struct_to_plain(meta)
        return out
    except NotImplementedError:
        pass
    except Exception:
        return out

    try:
        import h5py
        with h5py.File(mat_path, "r") as f:
            rr = _h5_get_path_ci(f, ["recordResult"])
            if rr is None:
                return out
            obj = _h5_get_path_ci(rr, ["metadata"])
            if obj is not None:
                val = _h5_decode_value(obj)
                if val is not None:
                    out["metadata"] = _mat_struct_to_plain(val)
    except Exception:
        pass
    return out


def _download_template_mat_for_save() -> str:
    key = str(st.session_state.get("mat_selected_key") or st.session_state.get("mat_pending_selected_key") or "").strip()
    if key and st.session_state.get("r2_connected") and st.session_state.get("r2_client") is not None:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mat")
        tmp.close()
        ok, _msg = st.session_state.r2_client.download_file(key, tmp.name)
        if ok:
            return tmp.name
        try:
            Path(tmp.name).unlink(missing_ok=True)
        except Exception:
            pass
    # Developer/project-folder fallback for local testing.
    for candidate in (Path.cwd() / "results_20251117_020622.mat", Path("/mnt/data/results_20251117_020622.mat")):
        try:
            if candidate.exists():
                return str(candidate)
        except Exception:
            pass
    return ""



def _matlab_cellstr(values):
    return np.array([str(v) for v in (values or [])], dtype=object).reshape((-1, 1))


def _matlab_datetime_object(dt=None):
    """Best-effort MATLAB datetime object for MAT export.

    scipy cannot write native MCOS datetime/table objects exactly like MATLAB v7.3,
    but writing them as MATLAB objects keeps the intended class instead of a plain struct.
    """
    dt = dt or datetime.now()
    matlab_object_type = globals().get("MatlabObject", None)
    if matlab_object_type is None:
        return np.array([dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second], dtype=float)
    arr = np.empty((1, 1), dtype=[
        ("year", object), ("month", object), ("day", object),
        ("hour", object), ("minute", object), ("second", object),
    ])
    arr[0, 0] = (
        np.array([[dt.year]], dtype=float),
        np.array([[dt.month]], dtype=float),
        np.array([[dt.day]], dtype=float),
        np.array([[dt.hour]], dtype=float),
        np.array([[dt.minute]], dtype=float),
        np.array([[dt.second + dt.microsecond / 1_000_000.0]], dtype=float),
    )
    return matlab_object_type(arr, classname="datetime")


def _build_roi_table_for_matlab(rois=None):
    """Build recordResult.ocr.roi_table / roi_table_raw as a MATLAB table object.

    Columns follow OCRExtractor.m naming: name_roi, roi, fmt, max_scale.
    """
    rows = []
    for r in _sanitize_rois(rois if rois is not None else st.session_state.get("rois", [])):
        rows.append({
            "name_roi": str(r.get("name", "_") or "_"),
            "roi": np.array([
                float(r.get("x", 0.0) or 0.0),
                float(r.get("y", 0.0) or 0.0),
                float(r.get("w", 0.0) or 0.0),
                float(r.get("h", 0.0) or 0.0),
            ], dtype=float).reshape((1, 4)),
            "fmt": _normalize_roi_format(r.get("fmt", "any")),
            "max_scale": float(r.get("max_scale", st.session_state.get("roi_global_scale", 1.2)) or 1.2),
        })
    n = len(rows)
    arr = np.empty((n, 1), dtype=[
        ("name_roi", object),
        ("roi", object),
        ("fmt", object),
        ("max_scale", object),
    ])
    for i, row in enumerate(rows):
        arr[i, 0] = (
            row["name_roi"],
            row["roi"],
            row["fmt"],
            np.array([[row["max_scale"]]], dtype=float),
        )
    return arr


def _mat_export_to_jsonable(obj):
    """Recursively convert the MAT export payload into strict JSON values."""
    matlab_object_type = globals().get("MatlabObject", None)
    pd_module = globals().get("pd", None)
    pd_timestamp_type = getattr(pd_module, "Timestamp", None) if pd_module is not None else None
    if matlab_object_type is not None and isinstance(obj, matlab_object_type):
        return _mat_export_to_jsonable(np.asarray(obj))
    obj = _mat_scalar(obj)
    if matlab_object_type is not None and isinstance(obj, matlab_object_type):
        return _mat_export_to_jsonable(np.asarray(obj))
    if isinstance(obj, dict):
        return {str(k): _mat_export_to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, np.void):
        if obj.dtype.names:
            return {name: _mat_export_to_jsonable(obj[name]) for name in obj.dtype.names}
        return _mat_export_to_jsonable(obj.tolist())
    if isinstance(obj, np.ndarray):
        if obj.dtype.names:
            return [_mat_export_to_jsonable(item) for item in obj.reshape(-1)]
        return [_mat_export_to_jsonable(v) for v in obj.reshape(-1).tolist()]
    if isinstance(obj, (list, tuple, set)):
        return [_mat_export_to_jsonable(v) for v in obj]
    if isinstance(obj, np.generic):
        return _mat_export_to_jsonable(obj.item())
    if pd_timestamp_type is not None:
        if isinstance(obj, (datetime, pd_timestamp_type)):
            return obj.isoformat()
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, (bytes, bytearray)):
        return obj.decode("utf-8", errors="ignore")
    return obj

def _ensure_ocr_extractor_ocr_struct(rr: dict) -> dict:
    """Normalize recordResult.ocr for the MATLAB OCRExtractor workflow."""
    ocr = rr.get("ocr", {}) if isinstance(rr.get("ocr", {}), dict) else {}
    params = ocr.get("params", {}) if isinstance(ocr.get("params", {}), dict) else {}
    params["start_s"] = float(st.session_state.get("t_start", 0.0) or 0.0)
    params["end_s"] = float(st.session_state.get("t_end", 0.0) or 0.0)
    ocr["params"] = params

    # OCRExtractor.m expects table-like ROI parameter blocks. Build both the
    # effective and raw table from the current ROI editor state; do not leave
    # scipy's default nested struct representation here.
    ocr["roi_table"] = _build_roi_table_for_matlab(st.session_state.get("rois", []))
    ocr["roi_table_raw"] = _build_roi_table_for_matlab(st.session_state.get("rois", []))
    ocr["created"] = datetime.now().isoformat(timespec="seconds")

    # Match OCRExtractor.m catalog names exactly.
    ocr["roi_catalog"] = {
        "roiNames": _matlab_cellstr(ROI_NAMES),
        "fmtOptions": _matlab_cellstr(FMT_OPTIONS),
    }

    # Track calibration belongs to OCR because OCRExtractor.m uses
    # recordResult.ocr.trkCalSlim for the minimap/track ROI. Always merge current
    # session-state calibration into trkCalSlim so the watchdog (background thread)
    # can find centerline_px, ref_pts, and color_range without accessing session state.
    track_roi = next((r for r in st.session_state.get("rois", []) if str(r.get("name", "")) == "track_minimap"), None)
    if track_roi is not None:
        trk_slim = ocr.get("trkCalSlim") if isinstance(ocr.get("trkCalSlim"), dict) else {}
        marker = dict(st.session_state.get("moving_pt_color_range", {}) or {})
        _mini_pts_raw = st.session_state.get("minimap_pts") or []
        _ref_pts_raw = st.session_state.get("ref_track_pts") or []
        _cl_px_raw = st.session_state.get("centerline_px")
        _cl_px_list = (
            _cl_px_raw.tolist() if hasattr(_cl_px_raw, "tolist") else list(_cl_px_raw)
        ) if _cl_px_raw is not None else None
        trk_slim.update({
            "roi": [
                float(track_roi.get("x", 0.0) or 0.0),
                float(track_roi.get("y", 0.0) or 0.0),
                float(track_roi.get("w", 0.0) or 0.0),
                float(track_roi.get("h", 0.0) or 0.0),
            ],
            "minimap_pts": _mini_pts_raw if isinstance(_mini_pts_raw, list) else [],
            "ref_pts": _ref_pts_raw if isinstance(_ref_pts_raw, list) else [],
            "moving_pt_color_range": marker,
        })
        if _cl_px_list is not None:
            trk_slim["centerline_px"] = _cl_px_list
        ocr["trkCalSlim"] = trk_slim
    rr["ocr"] = ocr
    return rr


def _merge_recordresult_template(mat_struct: dict, template_fields: dict) -> dict:
    out = dict(mat_struct or {})
    rr = _mat_struct_to_plain(out.get("recordResult", {}))
    if not isinstance(rr, dict):
        rr = {"data": rr}

    # Only metadata is inherited from the original MAT file; it may be extended
    # below with current Streamlit/video information. Do not copy OCR results,
    # audio_rpm, or validation from another processing stage.
    if isinstance(template_fields.get("metadata"), dict):
        inherited_meta = dict(template_fields["metadata"])
        current_meta = rr.get("metadata", {}) if isinstance(rr.get("metadata", {}), dict) else {}
        inherited_meta.update(current_meta)
        rr["metadata"] = inherited_meta
    else:
        rr.setdefault("metadata", {})

    rr = _ensure_ocr_extractor_ocr_struct(rr)

    out["recordResult"] = rr
    return out


def _stamp_video_faulty(mat_struct: dict, reason: str = "video fehlerhaft - neu herunterladen") -> dict:
    """Mark a capture as having a faulty video that needs to be re-downloaded."""
    out = dict(mat_struct or {})
    rr = _mat_struct_to_plain(out.get("recordResult", {}))
    if not isinstance(rr, dict):
        rr = {"data": rr}
    meta = rr.get("metadata", {}) if isinstance(rr.get("metadata", {}), dict) else {}
    meta["video_faulty"] = True
    meta["video_status"] = "video_fehlerhaft"
    meta["video_note"] = str(reason or "video fehlerhaft - neu herunterladen")
    meta["video_stamped_at"] = datetime.now().isoformat(timespec="seconds")
    rr["metadata"] = meta

    ocr = rr.get("ocr", {}) if isinstance(rr.get("ocr", {}), dict) else {}
    params = ocr.get("params", {}) if isinstance(ocr.get("params", {}), dict) else {}
    params["start_s"] = float(st.session_state.get("t_start", 0.0) or 0.0)
    params["end_s"] = float(st.session_state.get("t_end", 0.0) or 0.0)
    ocr["params"] = params
    ocr["video_faulty"] = True
    ocr["video_status"] = "video_fehlerhaft"
    ocr["video_note"] = str(reason or "video fehlerhaft - neu herunterladen")
    ocr["created"] = datetime.now().isoformat(timespec="seconds")
    try:
        ocr["roi_table"] = _build_roi_table_for_matlab([])
        ocr["roi_table_raw"] = _build_roi_table_for_matlab([])
    except Exception:
        ocr["roi_table"] = []
        ocr["roi_table_raw"] = []
    ocr["roi_catalog"] = {
        "roiNames": _matlab_cellstr(ROI_NAMES),
        "fmtOptions": _matlab_cellstr(FMT_OPTIONS),
    }
    rr["ocr"] = ocr
    out["recordResult"] = rr
    return out


def _stamp_no_roi_available(mat_struct: dict, reason: str = "kein roi vorhanden") -> dict:
    """Mark a capture as intentionally not OCR/ROI-processable."""
    out = dict(mat_struct or {})
    rr = _mat_struct_to_plain(out.get("recordResult", {}))
    if not isinstance(rr, dict):
        rr = {"data": rr}
    meta = rr.get("metadata", {}) if isinstance(rr.get("metadata", {}), dict) else {}
    meta["no_roi_available"] = True
    meta["roi_status"] = "kein_roi_vorhanden"
    meta["roi_note"] = str(reason or "kein roi vorhanden")
    meta["roi_stamped_at"] = datetime.now().isoformat(timespec="seconds")
    rr["metadata"] = meta

    ocr = rr.get("ocr", {}) if isinstance(rr.get("ocr", {}), dict) else {}
    params = ocr.get("params", {}) if isinstance(ocr.get("params", {}), dict) else {}
    params["start_s"] = float(st.session_state.get("t_start", 0.0) or 0.0)
    params["end_s"] = float(st.session_state.get("t_end", 0.0) or 0.0)
    ocr["params"] = params
    ocr["no_roi_available"] = True
    ocr["roi_status"] = "kein_roi_vorhanden"
    ocr["roi_note"] = str(reason or "kein roi vorhanden")
    ocr["created"] = datetime.now().isoformat(timespec="seconds")
    # Keep empty table-like fields where possible, but the explicit stamp is the source of truth.
    try:
        ocr["roi_table"] = _build_roi_table_for_matlab([])
        ocr["roi_table_raw"] = _build_roi_table_for_matlab([])
    except Exception:
        ocr["roi_table"] = []
        ocr["roi_table_raw"] = []
    ocr["roi_catalog"] = {
        "roiNames": _matlab_cellstr(ROI_NAMES),
        "fmtOptions": _matlab_cellstr(FMT_OPTIONS),
    }
    rr["ocr"] = ocr
    out["recordResult"] = rr
    return out


def _build_save_mat_struct(result, no_roi: bool = False, video_faulty: bool = False):
    mat_struct = build_mat_struct(result)
    template_path = _download_template_mat_for_save()
    try:
        template_fields = _load_recordresult_template_fields(template_path) if template_path else {}
        merged = _merge_recordresult_template(mat_struct, template_fields)
        if no_roi:
            merged = _stamp_no_roi_available(merged)
        if video_faulty:
            merged = _stamp_video_faulty(merged)
        return merged
    finally:
        try:
            if template_path and str(template_path).startswith(tempfile.gettempdir()):
                Path(template_path).unlink(missing_ok=True)
        except Exception:
            pass


def _upload_bytes_compat(client, key: str, data: bytes, content_type: str) -> tuple[bool, str]:
    try:
        if hasattr(client, "upload_bytes"):
            return client.upload_bytes(data, key, content_type=content_type)
        tmp = tempfile.NamedTemporaryFile(delete=False)
        tmp.write(data)
        tmp.close()
        try:
            return client.upload_file(tmp.name, key)
        finally:
            try:
                Path(tmp.name).unlink(missing_ok=True)
            except Exception:
                pass
    except Exception as e:
        return False, str(e)


def _server_results_dir() -> Path:
    """Directory on the machine running Streamlit, not on a remote browser client."""
    try:
        if st.session_state.get("local_connected") and st.session_state.get("local_base_path"):
            base = Path(str(st.session_state.local_base_path)).expanduser()
            return (base / "results").resolve()
    except Exception:
        pass
    return (Path.cwd() / "results").resolve()


def _save_fields_to_local_json(
    replace_fields: dict,
    capture_folder: str,
    base_rr: dict | None = None,
) -> tuple[bool, str, bytes]:
    """Merge replace_fields into local results JSON, preserving all other sections.

    Same format as MAT-to-JSON conversion: _normalize_sidecar_json_payload + indent=2.
    Returns (ok, message, json_bytes).
    """
    from core.watchdog_state import get_path_lock, _JSON_ROW_CACHE

    safe_cf = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in str(capture_folder)).strip("._") or "output"
    json_name = f"results_{safe_cf}.json"
    res_dir = _server_results_dir()
    res_dir.mkdir(parents=True, exist_ok=True)
    json_path = res_dir / json_name

    doc: dict = {}
    if json_path.exists():
        try:
            doc = json.loads(json_path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            doc = {}
    if not isinstance(doc, dict):
        doc = {}

    rr = doc.get("recordResult") if isinstance(doc.get("recordResult"), dict) else {}
    rr = dict(rr)

    if isinstance(base_rr, dict):
        for k, v in base_rr.items():
            if k not in rr or rr[k] is None:
                rr[k] = _mat_export_to_jsonable(v)

    for field, value in replace_fields.items():
        exported = _mat_export_to_jsonable(value)
        if field == "metadata" and isinstance(exported, dict) and isinstance(rr.get("metadata"), dict):
            for mk, mv in exported.items():
                rr["metadata"][mk] = mv
        else:
            rr[field] = exported

    doc["recordResult"] = rr

    norm_fn = globals().get("_normalize_sidecar_json_payload")
    if callable(norm_fn):
        try:
            doc = norm_fn(doc)
        except Exception:
            pass

    json_bytes = json.dumps(
        doc, ensure_ascii=False, indent=2,
        default=lambda o: _mat_export_to_jsonable(o),
    ).encode("utf-8")

    try:
        with get_path_lock(str(json_path)):
            json_path.write_bytes(json_bytes)
    except Exception as e:
        return False, f"Schreiben fehlgeschlagen: {e}", json_bytes

    _JSON_ROW_CACHE.pop(str(json_path), None)
    try:
        from app_tabs.media_tab import _DETAIL_CACHE
        _DETAIL_CACHE.pop(str(json_path), None)
    except Exception:
        pass

    return True, str(json_path), json_bytes


def _save_result_json_and_mat(no_roi: bool = False, video_faulty: bool = False) -> tuple[bool, str, dict]:
    cf = st.session_state.capture_folder or Path(str(st.session_state.video_name or "output")).stem or "output"
    safe_cf = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in str(cf)).strip("._") or "output"

    if no_roi or video_faulty:
        result = build_result_payload(
            t_start=st.session_state.t_start,
            t_end=st.session_state.t_end,
            rois=[],
            video={
                "width": st.session_state.vid_width,
                "height": st.session_state.vid_height,
                "fps": st.session_state.vid_fps,
                "duration": st.session_state.vid_duration,
            },
            track={"ref_pts": None, "minimap_pts": None, "moving_pt_color_range": {}},
        )
    else:
        result = build_result_json()

    mat_struct_for_save = _build_save_mat_struct(result, no_roi=no_roi, video_faulty=video_faulty)
    json_name = f"results_{safe_cf}.json"

    # Only ocr + metadata are updated; all other sections (audio_config, validation, …) are preserved.
    rr_for_save = _mat_struct_to_plain(mat_struct_for_save.get("recordResult", {}))
    if not isinstance(rr_for_save, dict):
        rr_for_save = {}
    replace_fields: dict = {"ocr": _mat_export_to_jsonable(rr_for_save.get("ocr", {}))}
    if isinstance(rr_for_save.get("metadata"), dict):
        replace_fields["metadata"] = _mat_export_to_jsonable(rr_for_save["metadata"])

    ok_save, msg_save, json_bytes = _save_fields_to_local_json(replace_fields, cf, base_rr=rr_for_save)
    saved_targets = [f"Lokal: {msg_save}" if ok_save else f"Fehler: {msg_save}"]
    payload = dict(json_name=json_name, mat_name="", json_bytes=json_bytes,
                   mat_bytes=b"", targets=saved_targets, mat_key="")
    if not ok_save:
        return False, f"Speichern fehlgeschlagen: {msg_save}", payload
    if video_faulty:
        msg_prefix = "Video fehlerhaft abgestempelt"
    elif no_roi:
        msg_prefix = "Kein ROI vorhanden abgestempelt"
    else:
        msg_prefix = "ROI gespeichert"
    return True, f"{msg_prefix}: {json_name}", payload


def load_json_config(data):
    cfg = config_from_json_payload(data, vid_duration=st.session_state.vid_duration)
    st.session_state.t_start = cfg.get("t_start", st.session_state.t_start)
    st.session_state.t_end = cfg.get("t_end", st.session_state.t_end)
    st.session_state.rois = _sanitize_rois(cfg.get("rois", []))
    if cfg.get("ref_track_pts"):
        st.session_state.ref_track_pts = cfg["ref_track_pts"]
    if cfg.get("minimap_pts"):
        st.session_state.minimap_pts = cfg["minimap_pts"]
    if cfg.get("moving_pt_color_range"):
        st.session_state.moving_pt_color_range = cfg["moving_pt_color_range"]


def _reset_track_analysis_state():
    """Reset all Track Analysis state before a different capture is loaded."""
    st.session_state.ref_track_img = None
    st.session_state.ref_track_pts = None
    st.session_state.minimap_pts = None
    st.session_state.centerline = None
    st.session_state.centerline_px = None
    st.session_state.ref_track_mat_name = ""
    st.session_state.minimap_next_pt_idx = 0
    st.session_state.track_comparison = None
    st.session_state.moving_pt_history = []
    st.session_state.moving_pt_color_range = dict(h_lo=0, h_hi=30, s_lo=150, s_hi=255, v_lo=150, v_hi=255)
    for key in (
        "track_comparison_samples",
        "_track_overlay_cache",
        "_run_compare_5_times",
        "_mm_last_click",
        "_mm_last_color_click",
        "_mm_color_click_px",
    ):
        st.session_state.pop(key, None)


def _apply_video(local_path, display_name):
    _reset_track_analysis_state()
    info = get_video_info(local_path)
    st.session_state.update(
        video_path=local_path, video_name=display_name,
        media_source="video",
        framepack_remote_prefix="",
        framepack_files=[],
        framepack_cache={},
        vid_fps=info["fps"], vid_width=info["width"],
        vid_height=info["height"], vid_duration=info["duration"],
        t_start=0.0, t_end=info["duration"], t_current=0.0, rois=[],
        selected_roi=None, drag_roi={}, roi_draw_armed=False,
        roi_wait_user_move=False, roi_anchor_box={}, roi_reject_anchor_events=0,
        roi_editor_df=None,
        roi_saved_once=False)
    if not st.session_state.capture_folder:
        st.session_state.capture_folder = Path(display_name).stem
    get_frame.clear(); get_video_info.clear()
    set_status(f"Video geladen: {display_name}", "ok")


def _has_media_source() -> bool:
    src = str(st.session_state.media_source or "none")
    if src == "video":
        return bool(st.session_state.video_path)
    if src == "framepack":
        return bool(st.session_state.framepack_remote_prefix) and bool(st.session_state.framepack_files)
    return False


def _load_framepack_from_r2(capture_folder: str) -> bool:
    if not capture_folder or st.session_state.r2_client is None:
        return False
    _reset_track_analysis_state()
    pfx = st.session_state.r2_prefix.strip("/")
    remote_prefix = f"{pfx}/captures/{capture_folder}/frames_1fps" if pfx else f"captures/{capture_folder}/frames_1fps"
    ok, items = st.session_state.r2_client.list_files(remote_prefix)
    if not ok or not isinstance(items, list):
        return False

    frame_files = sorted([n for n in items if n.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))])
    if not frame_files:
        return False

    first_key = f"{remote_prefix}/{frame_files[0]}"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=Path(frame_files[0]).suffix or ".jpg")
    tmp.close()
    ok_dl, msg_dl = st.session_state.r2_client.download_file(first_key, tmp.name)
    if not ok_dl:
        set_status(f"Frame-Pack Download: {msg_dl}", "warn")
        return False
    try:
        img = np.array(Image.open(tmp.name).convert("RGB"))
    except Exception as e:
        set_status(f"Frame-Pack Parse: {e}", "warn")
        return False
    finally:
        try:
            Path(tmp.name).unlink(missing_ok=True)
        except Exception:
            pass

    h, w = img.shape[:2]
    fps = 1.0
    duration = max(1.0, float(len(frame_files)))
    st.session_state.update(
        video_path=None,
        video_name=f"{capture_folder} [frames_1fps]",
        media_source="framepack",
        framepack_remote_prefix=remote_prefix,
        framepack_files=frame_files,
        framepack_cache={0: img},
        vid_fps=fps,
        vid_width=w,
        vid_height=h,
        vid_duration=duration,
        t_start=0.0,
        t_end=duration,
        t_current=0.0,
        rois=[],
        selected_roi=None,
        drag_roi={},
        roi_draw_armed=False,
        roi_wait_user_move=False,
        roi_anchor_box={},
        roi_reject_anchor_events=0,
        roi_editor_df=None,
        roi_saved_once=False,
    )
    set_status(f"Frame-Pack geladen: {capture_folder} ({len(frame_files)} Frames)", "ok")
    return True


def _get_media_frame(time_s: float):
    if st.session_state.video_path:
        return get_frame(st.session_state.video_path, time_s)
    return None

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

def _r2_json_sidecar_key(remote_key: str) -> str:
    """
    Build a JSON sidecar key for Cloudflare R2/S3.

    Important:
    R2 keys are POSIX-style object keys, not local filesystem paths.
    Do not use pathlib.Path here because on Windows it converts "/" to "\\".
    """
    # Umsetzung von Vorschlag: R2/S3-Keys immer POSIX-artig bauen und Windows-Backslashes vermeiden.
    key = str(remote_key or "").strip().replace("\\", "/").strip("/")
    if not key:
        return ""

    p = PurePosixPath(key)
    if p.suffix:
        return str(p.with_suffix(".json"))
    return f"{p}.json"

def _refresh_mat_files():
    if not st.session_state.r2_connected or st.session_state.r2_client is None:
        st.session_state.mat_files = []
        st.session_state.mat_targets = []
        return
    client = st.session_state.r2_client
    pfx = st.session_state.r2_prefix.strip("/")
    res_key = _results_dir_key()
    cap_root = f"{pfx}/captures" if pfx else "captures"

    ok_res, res_items = client.list_files(res_key)
    ok_cap, cap_items = client.list_files(cap_root)
    if not ok_res or not isinstance(res_items, list):
        res_items = []
    if not ok_cap or not isinstance(cap_items, list):
        cap_items = []

    mats = []
    json_sidecars = []
    for name in res_items:
        if not name.endswith("/"):
            full_key = f"{res_key}/{name}" if res_key else name
            if full_key.lower().endswith(".mat"):
                mats.append(full_key.strip("/"))
            elif full_key.lower().endswith(".json") and Path(full_key).name.startswith("results_"):
                json_sidecars.append(full_key.strip("/"))
    mats.sort(reverse=True)
    json_sidecars.sort(reverse=True)
    # MAT Selection is JSON-only: consider only results_*.json in results/.
    all_keys = list(json_sidecars)
    all_keys.sort(reverse=True)
    st.session_state.mat_files = all_keys

    folders = sorted([n.rstrip("/") for n in cap_items if n.endswith("/")], reverse=True)
    mats_set = set(all_keys)
    mat_by_folder = {}
    for mk in all_keys:
        g = _mat_capture_guess_from_key(mk)
        if g and g not in mat_by_folder:
            mat_by_folder[g] = mk

    targets = []
    used_mats = set()
    for folder in folders:
        expected_json = f"{res_key}/results_{folder}.json" if res_key else f"results_{folder}.json"
        if expected_json in mats_set:
            mat_key = expected_json
        else:
            mat_key = mat_by_folder.get(folder, "")
        if mat_key:
            used_mats.add(mat_key)
        targets.append({"kind": "folder", "folder": folder, "mat_key": mat_key})

    for mk in all_keys:
        if mk not in used_mats:
            targets.append({"kind": "mat_only", "folder": _mat_capture_guess_from_key(mk), "mat_key": mk})
    st.session_state.mat_targets = targets

    # Invalidate summary cache when file set changes.
    cache = st.session_state.get("mat_summary_cache") or {}
    st.session_state.mat_summary_cache = {k: v for k, v in cache.items() if k in all_keys}
    valid_mat_keys = [t.get("mat_key", "") for t in targets if t.get("mat_key")]
    # Keine implizite Auswahl des ersten Eintrags: MAT+Video laden erfordert
    # immer einen expliziten Klick in der aktuell sichtbaren Tabelle.
    if st.session_state.mat_selected_key not in valid_mat_keys:
        st.session_state.mat_selected_key = ""
        st.session_state.mat_selected_summary = None
    if st.session_state.mat_pending_selected_key not in valid_mat_keys:
        st.session_state.mat_pending_selected_key = ""
    if st.session_state.get("mat_user_selected_key", "") not in valid_mat_keys:
        st.session_state.mat_user_selected_key = ""
    st.session_state.mat_scan_prefix = st.session_state.r2_prefix


def _mat_capture_guess_from_key(remote_key: str) -> str:
    filename = Path(remote_key).name
    fl = filename.lower()
    if filename.startswith("results_") and (fl.endswith(".mat") or fl.endswith(".json")):
        return Path(filename).stem[len("results_"):]
    return ""


def _download_mat_to_temp(remote_key: str):
    client = st.session_state.r2_client
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mat")
    tmp.close()
    ok, msg = client.download_file(remote_key, tmp.name)
    if not ok:
        return False, msg, None
    return True, "", tmp.name


def _mat_obj_get(obj, field: str, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(field, default)
    if hasattr(obj, field):
        return getattr(obj, field)
    try:
        if isinstance(obj, np.ndarray) and obj.dtype.names and field in obj.dtype.names:
            return _mat_scalar(obj[field])
    except Exception:
        pass
    return default


def _mat_scalar(x):
    try:
        while isinstance(x, np.ndarray) and x.size == 1:
            x = x.item()
    except Exception:
        pass
    return x


def _mat_to_text(x, default: str = "") -> str:
    """Robust MATLAB value -> Python text, including char arrays and categorical-like values."""
    if x is None:
        return default
    x = _mat_scalar(x)
    try:
        if isinstance(x, bytes):
            return x.decode("utf-8", errors="ignore").strip()
        if isinstance(x, str):
            return x.strip()
        if isinstance(x, np.ndarray):
            if x.size == 0:
                return default
            if x.dtype.kind in ("U", "S"):
                vals = np.asarray(x).ravel().tolist()
                if all(len(str(v)) == 1 for v in vals):
                    return "".join(str(v) for v in vals).strip()
                return str(vals[0]).strip()
            if x.dtype == object:
                vals = np.asarray(x).ravel().tolist()
                if vals:
                    return _mat_to_text(vals[0], default)
        for fld in ("codes", "categoryNames", "categories", "data"):
            val = _mat_obj_get(x, fld)
            if val is not None and val is not x:
                txt = _mat_to_text(val, "")
                if txt:
                    return txt
        return str(x).strip()
    except Exception:
        return default


def _normalize_roi_format(fmt) -> str:
    txt = _mat_to_text(fmt, "any")
    if not txt or txt == "<undefined>":
        txt = "any"
    txt = str(txt).strip().strip("'\"")
    low = txt.lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "double": "float", "single": "float", "numeric": "float", "number": "float",
        "decimal": "float", "float64": "float", "float32": "float",
        "int": "integer", "uint": "integer", "uint8": "integer", "uint16": "integer",
        "uint32": "integer", "int8": "integer", "int16": "integer", "int32": "integer",
        "text": "alnum", "string": "alnum", "char": "alnum",
        "time": "time_m:ss.SSS", "duration": "time_m:ss.SSS",
    }
    if low in aliases:
        txt = aliases[low]
    elif low in {o.lower(): o for o in FMT_OPTIONS}:
        txt = {o.lower(): o for o in FMT_OPTIONS}[low]
    if txt == "custom" or txt not in FMT_OPTIONS:
        return "any"
    return txt


def _mat_text_list(x) -> list[str]:
    """MATLAB char/cell/string/categorical labels -> list[str]."""
    if x is None:
        return []
    x = _mat_scalar(x)
    try:
        arr = np.asarray(x)
        if arr.size == 0:
            return []
        if arr.dtype.kind in ("U", "S"):
            if arr.ndim == 2:
                return ["".join(str(c) for c in row).strip() for row in arr]
            return [str(v).strip() for v in arr.ravel().tolist()]
        return [_mat_to_text(v, "") for v in arr.ravel().tolist()]
    except Exception:
        txt = _mat_to_text(x, "")
        return [txt] if txt else []


def _mat_categorical_column_values(col, n: int) -> list | None:
    """Decode MATLAB categorical saved in v7 MAT as codes + categoryNames/categories."""
    if col is None:
        return None
    obj = _mat_scalar(col)
    codes = _mat_obj_get(obj, "codes")
    cats = (_mat_obj_get(obj, "categoryNames") or
            _mat_obj_get(obj, "categories") or
            _mat_obj_get(obj, "category_names"))
    if codes is None or cats is None:
        return None
    labels = _mat_text_list(cats)
    if not labels:
        return None
    try:
        code_arr = np.asarray(_mat_scalar(codes)).ravel()
    except Exception:
        return None
    vals = []
    for c in code_arr[:n]:
        try:
            if not np.isfinite(float(c)):
                vals.append(""); continue
            idx = int(c) - 1
            vals.append(labels[idx] if 0 <= idx < len(labels) else "")
        except Exception:
            vals.append("")
    if len(vals) < n:
        vals += [""] * (n - len(vals))
    return vals[:n]


def _mat_column_values(col, n: int) -> list:
    if col is None:
        return [None] * n
    cat_vals = _mat_categorical_column_values(col, n)
    if cat_vals is not None:
        return cat_vals
    col = _mat_scalar(col)
    try:
        arr = np.asarray(col)
        if arr.ndim == 0:
            vals = [arr.item()]
        elif arr.dtype.kind in ("U", "S") and arr.ndim == 2:
            vals = ["".join(str(c) for c in row).strip() for row in arr]
        else:
            vals = arr.ravel().tolist()
    except Exception:
        vals = [col]
    if len(vals) < n:
        vals = vals + [None] * (n - len(vals))
    return vals[:n]


def _parse_roi_value(v):
    if v is None:
        return None
    try:
        arr = np.asarray(_mat_scalar(v), dtype=float).ravel()
        arr = arr[np.isfinite(arr)]
        if arr.size >= 4:
            return [float(arr[0]), float(arr[1]), float(arr[2]), float(arr[3])]
    except Exception:
        pass
    txt = _mat_to_text(v, "")
    if not txt:
        return None
    try:
        nums = [float(x) for x in txt.replace(",", " ").replace(";", " ").split()]
        if len(nums) >= 4:
            return nums[:4]
    except Exception:
        return None
    return None




def _h5_decode_value(v, f=None, _depth: int = 0):
    """Best-effort reader for MATLAB v7.3 values, including refs and char arrays."""
    if _depth > 6:
        return None
    try:
        import h5py
        if isinstance(v, h5py.Reference):
            if not v or f is None:
                return None
            return _h5_decode_value(f[v], f, _depth + 1)
        if isinstance(v, h5py.Dataset):
            data = v[()]
            return _h5_decode_value(data, v.file, _depth + 1)
        if isinstance(v, h5py.Group):
            out = {}
            for k in v.keys():
                out[str(k)] = _h5_decode_value(v[k], v.file, _depth + 1)
            return out
    except Exception:
        pass
    try:
        arr = np.asarray(v)
        if arr.dtype == object:
            vals = []
            for item in arr.ravel().tolist():
                vals.append(_h5_decode_value(item, f, _depth + 1))
            return vals
        if arr.dtype.kind in ("S", "U"):
            vals = arr.ravel().tolist()
            vals = [x.decode("utf-8", errors="ignore") if isinstance(x, bytes) else str(x) for x in vals]
            if all(len(x) == 1 for x in vals):
                return "".join(vals).strip()
            return [x.strip() for x in vals]
        # MATLAB char arrays in v7.3 are often uint16 numeric matrices.
        if arr.dtype.kind in ("u", "i") and arr.size and arr.size < 4096:
            flat = arr.ravel()
            if np.all((flat >= 0) & (flat < 65536)) and np.any((flat >= 32) & (flat <= 126)):
                chars = [chr(int(c)) for c in flat if int(c) != 0]
                txt = "".join(chars).strip()
                if txt and sum(ch.isprintable() for ch in txt) >= max(1, int(0.8 * len(txt))):
                    return txt
        return arr
    except Exception:
        return v


def _h5_get_path_ci(root, path_parts):
    cur = root
    try:
        for part in path_parts:
            if part in cur:
                cur = cur[part]
                continue
            low = str(part).lower()
            match = next((k for k in cur.keys() if str(k).lower() == low), None)
            if match is None:
                return None
            cur = cur[match]
        return cur
    except Exception:
        return None


def _h5_to_text_list(v) -> list[str]:
    v = _h5_decode_value(v)
    if v is None:
        return []
    if isinstance(v, str):
        return [v]
    if isinstance(v, dict):
        for key in ("data", "values", "categoryNames", "categories"):
            if key in v:
                vals = _h5_to_text_list(v[key])
                if vals:
                    return vals
        return []
    if isinstance(v, np.ndarray):
        if v.dtype.kind in ("U", "S"):
            return [str(x).strip() for x in v.ravel().tolist()]
        return [_mat_to_text(x, "") for x in v.ravel().tolist()]
    if isinstance(v, list):
        out = []
        for item in v:
            out.extend(_h5_to_text_list(item))
        return [x for x in out if x]
    txt = _mat_to_text(v, "")
    return [txt] if txt else []


def _h5_column_values(table_group, names: tuple[str, ...], n_hint: int = 0) -> list:
    if table_group is None:
        return []
    obj = None
    for name in names:
        obj = _h5_get_path_ci(table_group, [name])
        if obj is not None:
            break
    if obj is None:
        return []
    val = _h5_decode_value(obj)
    # MATLAB categorical: group with codes + categoryNames/categories.
    if isinstance(val, dict):
        codes = val.get("codes", None)
        if codes is None:
            codes = val.get("Codes", None)
        cats = val.get("categoryNames", None)
        if cats is None:
            cats = val.get("categories", None)
        if cats is None:
            cats = val.get("CategoryNames", None)
        if codes is not None and cats is not None:
            labels = _h5_to_text_list(cats)
            try:
                code_arr = np.asarray(codes, dtype=float).ravel()
                out = []
                for c in code_arr:
                    idx = int(c) - 1
                    out.append(labels[idx] if 0 <= idx < len(labels) else "")
                return out
            except Exception:
                pass
        for key in ("data", "values", "Value", "value"):
            if key in val:
                val = val[key]
                break
    if isinstance(val, str):
        return [val]
    if isinstance(val, list):
        # Cell array refs typically decode to one value per row.
        out = []
        for item in val:
            if isinstance(item, np.ndarray):
                if item.size == 4:
                    out.append(item.astype(float).ravel().tolist())
                else:
                    out.append(_mat_to_text(item, "") or item)
            else:
                txts = _h5_to_text_list(item)
                out.append(txts[0] if len(txts) == 1 else (txts or item))
        return out
    try:
        arr = np.asarray(val)
        if arr.ndim == 2 and 4 in arr.shape and arr.size >= 4 and names[0].lower() == "roi":
            if arr.shape[0] == 4:
                return [arr[:, i].astype(float).tolist() for i in range(arr.shape[1])]
            if arr.shape[1] == 4:
                return [arr[i, :].astype(float).tolist() for i in range(arr.shape[0])]
        if arr.ndim == 2 and arr.dtype.kind in ("u", "i") and arr.size < 10000:
            # char matrix: columns/rows are strings
            if max(arr.shape) > 1 and min(arr.shape) > 1:
                rows = []
                for row in arr.T if arr.shape[0] < arr.shape[1] else arr:
                    txt = "".join(chr(int(c)) for c in np.asarray(row).ravel() if int(c) != 0).strip()
                    rows.append(txt)
                return rows
        return arr.ravel().tolist()
    except Exception:
        return [val]




def _h5_decode_cell_dataset_to_list(ds, f=None) -> list:
    """Decode a MATLAB v7.3 cell dataset to a flat Python list."""
    try:
        arr = np.asarray(ds[()])
        if arr.dtype != object:
            return []
        out = []
        for item in arr.ravel().tolist():
            out.append(_h5_decode_value(item, f or getattr(ds, "file", None)))
        return out
    except Exception:
        return []


def _h5_collect_mcos_reference_values(f) -> list:
    """Return decoded MCOS reference payloads used by MATLAB v7.3 table/categorical objects."""
    vals = []
    try:
        mcos = _h5_get_path_ci(f, ["#subsystem#", "MCOS"])
        if mcos is None:
            return vals
        arr = np.asarray(mcos[()]).ravel().tolist()
        for ref in arr:
            try:
                vals.append(_h5_decode_value(ref, f))
            except Exception:
                vals.append(None)
    except Exception:
        pass
    return vals


def _looks_like_roi_name_catalog(vals: list[str]) -> bool:
    low = {str(v).strip().lower() for v in vals}
    return "track_minimap" in low and ("t_s" in low or "v_fzg_kmph" in low)


def _looks_like_fmt_catalog(vals: list[str]) -> bool:
    low = {str(v).strip().lower() for v in vals}
    return "any" in low and ("integer" in low or "float" in low or "time_m:ss" in low)


def _h5_mcos_table_categorical_columns(f) -> dict:
    """
    Best-effort decoder for MATLAB v7.3 table variables saved as MCOS objects.
    This is intentionally used as supplemental metadata: it recovers categorical
    name_roi/fmt columns when recordResult.ocr.roi_table itself is a MATLAB table
    dataset instead of a navigable HDF5 group.
    """
    out = {"names": [], "fmts": []}
    vals = _h5_collect_mcos_reference_values(f)
    if not vals:
        return out

    catalogs = []
    code_arrays = []
    for idx, val in enumerate(vals):
        if isinstance(val, list) and val and all(isinstance(x, str) for x in val):
            cleaned = [str(x).strip() for x in val if str(x).strip()]
            if _looks_like_roi_name_catalog(cleaned) or _looks_like_fmt_catalog(cleaned):
                catalogs.append((idx, cleaned))
        else:
            try:
                arr = np.asarray(val)
                if arr.size > 0 and arr.size <= 200 and arr.dtype.kind in ("u", "i"):
                    flat = arr.astype(int).ravel()
                    if np.all(flat >= 0):
                        code_arrays.append((idx, flat.tolist()))
            except Exception:
                pass

    roi_cats = next((c for _, c in catalogs if _looks_like_roi_name_catalog(c)), [])
    fmt_cats = next((c for _, c in catalogs if _looks_like_fmt_catalog(c)), [])

    def decode_codes(codes, cats, default=""):
        decoded = []
        for c in codes:
            try:
                ci = int(c)
                decoded.append(cats[ci - 1] if 1 <= ci <= len(cats) else default)
            except Exception:
                decoded.append(default)
        return decoded

    selected_roi_codes = None
    if roi_cats:
        roi_candidates = []
        for _, codes in code_arrays:
            if 1 <= len(codes) <= 100 and max(codes or [0]) <= len(roi_cats):
                dec = decode_codes(codes, roi_cats, "")
                if any(str(x).strip().lower() in {"track_minimap", "t_s", "v_fzg_kmph"} for x in dec):
                    roi_candidates.append((dec, list(codes)))
        if roi_candidates:
            # Prefer the column that includes track_minimap and has no blanks.
            roi_candidates.sort(key=lambda item: ("track_minimap" not in [str(x).lower() for x in item[0]], item[0].count(""), len(item[0])))
            out["names"] = roi_candidates[0][0]
            selected_roi_codes = roi_candidates[0][1]

    if fmt_cats:
        target_len = len(out.get("names") or [])
        fmt_candidates = []
        for _, codes in code_arrays:
            if 1 <= len(codes) <= 100 and max(codes or [0]) <= len(fmt_cats):
                if target_len and len(codes) != target_len:
                    continue
                # Important: MATLAB v7.3 table/categorical data can expose several
                # MCOS code arrays. The name_roi codes also decode to valid-looking
                # format strings when applied to the fmt category catalog
                # (e.g. t_s -> time_m:ss). Do not reuse the code vector that was
                # already identified as the ROI-name categorical column.
                if selected_roi_codes is not None and list(codes) == selected_roi_codes:
                    continue
                dec = decode_codes(codes, fmt_cats, "any")
                if any(str(x).strip().lower() in {"any", "integer", "float"} or str(x).startswith("time_") or str(x).startswith("int_") for x in dec):
                    fmt_candidates.append((dec, list(codes)))
        if fmt_candidates:
            # Prefer mixed/specific OCR formats over accidental low-index category
            # vectors; the real fmt vector often contains int_* / time_mm / any.
            def score(item):
                xs = item[0]
                specific = sum(1 for x in xs if str(x).startswith("int_") or str(x).startswith("time_mm") or str(x).startswith("time_hh"))
                useful = sum(1 for x in xs if str(x).startswith("time_") or str(x).startswith("int_") or str(x) in ("any", "integer", "float", "alnum"))
                return (-specific, -useful, xs.count("any"), len(xs))
            fmt_candidates.sort(key=score)
            out["fmts"] = fmt_candidates[0][0]

    return out


def _extract_roi_format_map_from_recordresult_hdf5(mat_path: str) -> dict[str, str]:
    """Recover ROI format values from a v7.3 MATLAB table/categorical roi_table."""
    try:
        import h5py
        with h5py.File(mat_path, "r") as f:
            tbl = _h5_get_path_ci(f, ["recordResult", "ocr", "roi_table"])
            if tbl is None:
                return {}
            names = _h5_column_values(tbl, ("name_roi", "name", "Name"))
            fmts = _h5_column_values(tbl, ("fmt", "format", "Format"))
            if not names or not fmts:
                recovered = _h5_mcos_table_categorical_columns(f)
                names = names or recovered.get("names") or []
                fmts = fmts or recovered.get("fmts") or []
            out = {}
            for i, nm in enumerate(names):
                name = _mat_to_text(nm, "").strip()
                if not name:
                    continue
                fmt = _normalize_roi_format(fmts[i] if i < len(fmts) else "any")
                out[name] = fmt or "any"
            return out
    except Exception:
        return {}


def _apply_roi_format_map(rois: list[dict], fmt_map: dict[str, str]) -> list[dict]:
    if not rois or not fmt_map:
        return rois
    out = []
    for r in rois:
        nr = dict(r)
        nm = str(nr.get("name", "")).strip()
        if nm in fmt_map:
            nr["fmt"] = _normalize_roi_format(fmt_map.get(nm) or "any")
        elif not nr.get("fmt"):
            nr["fmt"] = "any"
        out.append(nr)
    return out

def _extract_rois_from_recordresult_hdf5(mat_path: str) -> list[dict]:
    try:
        import h5py
        with h5py.File(mat_path, "r") as f:
            tbl = _h5_get_path_ci(f, ["recordResult", "ocr", "roi_table"])
            if tbl is None:
                return []
            names = _h5_column_values(tbl, ("name_roi", "name", "Name"))
            rois = _h5_column_values(tbl, ("roi", "ROI"))
            fmts = _h5_column_values(tbl, ("fmt", "format", "Format"))
            if (not names) or (not fmts):
                recovered = _h5_mcos_table_categorical_columns(f)
                names = names or recovered.get("names") or []
                fmts = fmts or recovered.get("fmts") or []
            n = max(len(names), len(rois), len(fmts))
            out = []
            for i in range(n):
                xywh = _parse_roi_value(rois[i] if i < len(rois) else None)
                if not xywh:
                    continue
                out.append(dict(
                    name=_mat_to_text(names[i] if i < len(names) else "_", "_") or "_",
                    x=float(xywh[0]), y=float(xywh[1]),
                    w=float(xywh[2]), h=float(xywh[3]),
                    fmt=_normalize_roi_format(fmts[i] if i < len(fmts) else "any"),
                    max_scale=float(st.session_state.get("roi_global_scale", 1.2)),
                ))
            return out
    except Exception:
        return []

def _extract_rois_from_recordresult_mat(mat_path: str) -> list[dict]:
    """Read recordResult.ocr.roi_table directly; fixes MATLAB categorical fmt values."""
    try:
        data = sio.loadmat(mat_path, squeeze_me=True, struct_as_record=False)
        rr = _mat_scalar(data.get("recordResult"))
        ocr = _mat_obj_get(rr, "ocr")
        roi_table = _mat_obj_get(ocr, "roi_table")
        n = _mat_table_height(roi_table)
        if n <= 0:
            return []
        names = _mat_column_values(_mat_table_column(roi_table, "name_roi", "name", "Name"), n)
        rois = _mat_column_values(_mat_table_column(roi_table, "roi", "ROI"), n)
        fmts = _mat_column_values(_mat_table_column(roi_table, "fmt", "format", "Format"), n)
        out = []
        for i in range(n):
            xywh = _parse_roi_value(rois[i])
            if not xywh:
                continue
            out.append(dict(
                name=_mat_to_text(names[i], "_") or "_",
                x=float(xywh[0]), y=float(xywh[1]),
                w=float(xywh[2]), h=float(xywh[3]),
                fmt=_normalize_roi_format(fmts[i]),
                max_scale=float(st.session_state.get("roi_global_scale", 1.2)),
            ))
        return out
    except NotImplementedError:
        return _extract_rois_from_recordresult_hdf5(mat_path)
    except Exception:
        h5_rois = _extract_rois_from_recordresult_hdf5(mat_path)
        return h5_rois or []


def _decode_roi_table_from_v5_workspace(fw_bytes: bytes, roi_names_cat: list, fmt_options: list) -> list[dict]:
    """Decode roi_table rows from the __function_workspace__ binary of a v5 MCOS MAT file.

    The MCOS binary stores:
    - max_scale: type-9 element of n_rows × float64(1.2)
    - name_roi categorical codes: type-2 element of n_rows uint8 values (1-indexed)
    - fmt categorical codes: second type-2 element of n_rows uint8 values (1-indexed)
    - roi coordinates: uint64 header [n_rows, 1, len0, ..., len(n-1)] followed by
      concatenated uint16 char strings (each row = "x y w h" padded to len_i chars)

    Returns a list of n_rows row-dicts with name_roi, roi, fmt, max_scale.
    """
    import struct as _struct

    if not fw_bytes or not roi_names_cat or not fmt_options:
        return []

    n_cat = len(roi_names_cat)
    n_fmt = len(fmt_options)
    val_12 = _struct.pack("<d", 1.2)

    # Step 1: determine n_rows from the first max_scale float64 run of n × 1.2
    n_rows = 0
    i = 0
    while i <= len(fw_bytes) - 8:
        if fw_bytes[i : i + 4] == b"\x09\x00\x00\x00":
            size = _struct.unpack("<I", fw_bytes[i + 4 : i + 8])[0]
            if size >= 8 and size % 8 == 0:
                n = size // 8
                end = i + 8 + size
                if 2 <= n <= 200 and end <= len(fw_bytes):
                    chunk = fw_bytes[i + 8 : end]
                    if all(chunk[j : j + 8] == val_12 for j in range(0, size, 8)):
                        n_rows = n
                        break
        i += 1

    if n_rows == 0:
        return []

    # Step 2: collect all full-element uint8[n_rows] arrays
    candidates = []
    i = 0
    while i <= len(fw_bytes) - 8 - n_rows:
        if fw_bytes[i : i + 4] == b"\x02\x00\x00\x00":
            size = _struct.unpack("<I", fw_bytes[i + 4 : i + 8])[0]
            if size == n_rows:
                codes = list(fw_bytes[i + 8 : i + 8 + n_rows])
                candidates.append((i, codes))
        i += 1

    # Step 3: identify name_roi and fmt code arrays
    name_codes: list | None = None
    fmt_codes: list | None = None

    for _offset, codes in candidates:
        if name_codes is None and all(1 <= c <= n_cat for c in codes):
            names_decoded = [roi_names_cat[c - 1] for c in codes]
            if any(n != "_" for n in names_decoded):
                name_codes = codes
                continue
        if fmt_codes is None and codes is not name_codes and all(1 <= c <= n_fmt for c in codes):
            fmt_codes = codes

        if name_codes is not None and fmt_codes is not None:
            break

    if name_codes is None:
        return []

    # Step 4: decode roi coordinates from uint64-header + concatenated uint16 char data
    # Header pattern: uint64(n_rows), uint64(1), n_rows × uint64(row_len_i)
    # Followed immediately by total_chars × uint16 of char data
    roi_coords: list | None = None
    step8 = 8
    header_size = (n_rows + 2) * step8
    for i in range(0, len(fw_bytes) - header_size - 10, step8):
        v0 = _struct.unpack("<Q", fw_bytes[i : i + 8])[0]
        if v0 != n_rows:
            continue
        v1 = _struct.unpack("<Q", fw_bytes[i + 8 : i + 16])[0]
        if v1 != 1:
            continue
        lengths = []
        for j in range(n_rows):
            vl = _struct.unpack("<Q", fw_bytes[i + 16 + j * 8 : i + 24 + j * 8])[0]
            if not (5 <= vl <= 50):
                break
            lengths.append(int(vl))
        if len(lengths) != n_rows:
            continue
        data_start = i + 16 + n_rows * 8
        total_chars = sum(lengths)
        chars = []
        valid = True
        for k in range(total_chars):
            pos = data_start + k * 2
            if pos + 2 > len(fw_bytes):
                valid = False
                break
            val = _struct.unpack("<H", fw_bytes[pos : pos + 2])[0]
            if not (32 <= val < 128):
                valid = False
                break
            chars.append(chr(val))
        if not valid:
            continue
        parsed = []
        offset = 0
        ok = True
        for r in range(n_rows):
            row_str = "".join(chars[offset : offset + lengths[r]]).strip()
            parts = row_str.split()
            if len(parts) == 4:
                try:
                    parsed.append([float(p) for p in parts])
                except Exception:
                    ok = False
                    break
            else:
                ok = False
                break
            offset += lengths[r]
        if ok and len(parsed) == n_rows:
            roi_coords = parsed
            break

    rows = []
    for idx in range(n_rows):
        nm = roi_names_cat[name_codes[idx] - 1] if 1 <= name_codes[idx] <= n_cat else ""
        fm = fmt_options[fmt_codes[idx] - 1] if (fmt_codes and 1 <= fmt_codes[idx] <= n_fmt) else "any"
        roi = roi_coords[idx] if roi_coords else []
        rows.append({"name_roi": nm, "roi": roi, "fmt": fm, "max_scale": 1.2})
    return rows


def _fix_mcos_roi_table_v5(rr: dict, raw_bytes: bytes) -> None:
    """Attempt to decode roi_table from a v5 MAT __function_workspace__ binary.

    Called in _mat_bytes_to_recordresult_json_bytes after scipy loads the file,
    before _mat_export_to_jsonable runs.  Updates rr['ocr']['roi_table'] and
    rr['ocr']['roi_table_raw'] in-place when the MatlabOpaque MCOS wrapper is
    detected and the workspace binary can be decoded.
    """
    ocr = rr.get("ocr")
    if not isinstance(ocr, dict):
        return

    def _is_mcos_table(tbl) -> bool:
        if not isinstance(tbl, dict):
            return False
        s1 = tbl.get("s1", "")
        s1_str = s1.decode("ascii", errors="ignore") if isinstance(s1, bytes) else str(s1)
        return s1_str.upper() == "MCOS"

    if not (_is_mcos_table(ocr.get("roi_table")) or _is_mcos_table(ocr.get("roi_table_raw"))):
        return

    # Extract roi_catalog from the already-decoded rr dict
    roi_cat = ocr.get("roi_catalog")
    if not isinstance(roi_cat, dict):
        return
    try:
        roi_names_cat = list(np.asarray(roi_cat.get("roiNames", [])).ravel().tolist())
        fmt_options = list(np.asarray(roi_cat.get("fmtOptions", [])).ravel().tolist())
    except Exception:
        return
    if not roi_names_cat or not fmt_options:
        return
    # Ensure plain strings (scipy may return bytes)
    roi_names_cat = [x.decode("utf-8", errors="ignore") if isinstance(x, bytes) else str(x) for x in roi_names_cat]
    fmt_options = [x.decode("utf-8", errors="ignore") if isinstance(x, bytes) else str(x) for x in fmt_options]

    # Load workspace bytes from the raw MAT bytes
    try:
        import scipy.io as _sio, io as _io
        _raw = _sio.loadmat(
            _io.BytesIO(raw_bytes),
            squeeze_me=False,
            struct_as_record=True,
            verify_compressed_data_integrity=False,
        )
        fw_bytes = bytes(_raw.get("__function_workspace__", np.array([], dtype=np.uint8)).ravel())
    except Exception:
        return

    rows = _decode_roi_table_from_v5_workspace(fw_bytes, roi_names_cat, fmt_options)
    if not rows:
        return
    for field in ("roi_table", "roi_table_raw"):
        tbl = ocr.get(field)
        if isinstance(tbl, (dict, np.ndarray)):
            ocr[field] = rows
    _fill_roi_from_trkCalSlim(ocr)


def _fill_roi_from_trkCalSlim(ocr: dict) -> None:
    """Populate roi=[] entries in roi_table/roi_table_raw from trkCalSlim.roi.

    In old MCOS v5/v7.3 Table files the roi coordinate column is stored in
    an inaccessible MCOS cell-array format.  The track_minimap ROI is the
    exception: it is also stored in the plain trkCalSlim.roi field, so we
    can back-fill it.  Other ROI names (t_s, v_Fzg_mph, …) remain roi=[]
    because no accessible coordinate data exists for them.
    """
    trk = ocr.get("trkCalSlim")
    if not isinstance(trk, dict):
        return
    trk_roi_raw = trk.get("roi")
    if trk_roi_raw is None:
        return
    try:
        coords = [float(v) for v in np.asarray(trk_roi_raw).ravel().tolist()[:4]]
    except Exception:
        return
    if len(coords) < 4 or any(c < 0 for c in coords):
        return

    for field in ("roi_table", "roi_table_raw"):
        rows = ocr.get(field)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("name_roi", "")).lower() == "track_minimap" and not row.get("roi"):
                row["roi"] = coords


def _roi_extractor_rows_to_table(rois: list[dict]) -> list[dict]:
    """Convert {name/name_roi, x, y, w, h, fmt, max_scale} → {name_roi, roi, fmt, max_scale}."""
    out = []
    for r in (rois or []):
        name = r.get("name_roi") or r.get("name") or "_"
        out.append({
            "name_roi": str(name),
            "roi": [float(r.get("x", 0.0)), float(r.get("y", 0.0)),
                    float(r.get("w", 0.0)), float(r.get("h", 0.0))],
            "fmt": r.get("fmt", "any"),
            "max_scale": float(r.get("max_scale", 1.2)),
        })
    return out


def _fix_roi_table_in_rr(rr: dict, mat_path: str = "") -> None:
    """Repair roi_table/roi_table_raw when they decoded as raw MCOS reference numbers.

    Three recovery strategies are tried in order:
    1. _extract_rois_from_recordresult_hdf5 — works when the roi column is
       stored as an accessible HDF5 group with named sub-datasets.
    2. _h5_mcos_table_categorical_columns fallback (HDF5) — recovers name_roi
       and fmt from the MCOS categorical encoding; roi is set to [].
    3. MCOS wrapper dict / raw ndarray (v5 MAT) — extracts the row count from
       the MCOS header and generates placeholder rows with roi=[].
    """
    ocr = rr.get("ocr")
    if not isinstance(ocr, dict):
        return

    def _malformed(tbl) -> bool:
        if isinstance(tbl, (np.ndarray, dict)):
            return True
        if not isinstance(tbl, list) or not tbl:
            return True
        return not isinstance(tbl[0], dict)

    if not _malformed(ocr.get("roi_table")):
        return

    # Strategy 1: full extraction with coordinates (HDF5)
    if mat_path:
        rois = _extract_rois_from_recordresult_hdf5(mat_path)
        if rois:
            rows = _roi_extractor_rows_to_table(rois)
            ocr["roi_table"] = rows
            if _malformed(ocr.get("roi_table_raw")):
                ocr["roi_table_raw"] = rows
            _fill_roi_from_trkCalSlim(ocr)
            return

        # Strategy 2: MCOS categorical fallback (HDF5 only)
        try:
            import h5py as _h5
            with _h5.File(mat_path, "r") as _f:
                recovered = _h5_mcos_table_categorical_columns(_f)
            names = recovered.get("names") or []
            fmts = recovered.get("fmts") or []
            if names:
                rows = [
                    {
                        "name_roi": str(names[i]),
                        "roi": [],
                        "fmt": str(fmts[i]) if i < len(fmts) else "any",
                        "max_scale": 1.2,
                    }
                    for i in range(len(names))
                ]
                ocr["roi_table"] = rows
                if _malformed(ocr.get("roi_table_raw")):
                    ocr["roi_table_raw"] = rows
                _fill_roi_from_trkCalSlim(ocr)
                return
        except Exception:
            pass

    # Strategy 3: MCOS wrapper dict or raw reference array (v5 MAT or pre-normalized)
    # Extract row count from the MCOS header and generate placeholder rows.
    def _n_rows_from_mcos(tbl) -> int:
        try:
            if isinstance(tbl, dict):
                s1 = tbl.get("s1", "")
                s1_str = s1.decode("ascii", errors="ignore") if isinstance(s1, bytes) else str(s1)
                s2 = tbl.get("s2", "")
                s2_str = s2.decode("ascii", errors="ignore") if isinstance(s2, bytes) else str(s2)
                if s1_str.upper() != "MCOS" or s2_str.lower() != "table":
                    return 0
                arr = tbl.get("arr")
                if arr is None:
                    return 0
                flat = list(np.asarray(arr).ravel())
                return int(flat[-1]) if flat else 0
            if isinstance(tbl, np.ndarray):
                flat = list(tbl.ravel())
                return int(flat[-1]) if len(flat) >= 6 else 0
        except Exception:
            pass
        return 0

    for field in ("roi_table", "roi_table_raw"):
        tbl = ocr.get(field)
        if not _malformed(tbl):
            continue
        n = _n_rows_from_mcos(tbl)
        if n > 0:
            rows = [{"name_roi": "", "roi": [], "fmt": "any", "max_scale": 1.2} for _ in range(n)]
            ocr[field] = rows
    _fill_roi_from_trkCalSlim(ocr)


def _pts_from_mat_value(v) -> list[list[float]]:
    try:
        arr = np.asarray(_mat_scalar(v), dtype=float)
        if arr.size < 4:
            return []
        arr = arr.reshape((-1, 2)) if arr.ndim == 1 else arr
        if arr.shape[1] != 2 and arr.shape[0] == 2:
            arr = arr.T
        pts = []
        for x, y in arr[:8, :2]:
            if np.isfinite(x) and np.isfinite(y):
                pts.append([float(x), float(y)])
        return pts
    except Exception:
        return []


def _marker_to_color_range(marker) -> dict | None:
    if marker is None:
        return None
    try:
        def _first_numeric(*names):
            for name in names:
                val = _mat_obj_get(marker, name)
                if val is not None:
                    try:
                        arr = np.asarray(_mat_scalar(val), dtype=float).ravel()
                        if arr.size:
                            return arr
                    except Exception:
                        pass
            return np.array([], dtype=float)

        direct = _first_numeric("hsv_range", "range", "HSVRange")
        if direct.size >= 6:
            vals = direct[:6].astype(float)
            # Accept either normalized HSV [0..1] or OpenCV HSV ranges.
            if np.nanmax(vals) <= 1.5:
                vals = np.array([vals[0]*179, vals[1]*179, vals[2]*255, vals[3]*255, vals[4]*255, vals[5]*255])
            return dict(
                h_lo=int(max(0, round(vals[0]))), h_hi=int(min(179, round(vals[1]))),
                s_lo=int(max(0, round(vals[2]))), s_hi=int(min(255, round(vals[3]))),
                v_lo=int(max(0, round(vals[4]))), v_hi=int(min(255, round(vals[5]))),
            )

        mu = _first_numeric("hsv_mu", "hsvMean", "hsv_mean", "mu", "HSV_mu", "hsv")
        sig = _first_numeric("hsv_sig", "hsvStd", "hsv_std", "sigma", "sig", "HSV_sig")
        if mu.size < 3 or not np.all(np.isfinite(mu[:3])):
            rgb = _first_numeric("rgb", "rgb_mu", "color_rgb", "marker_rgb")
            if rgb.size >= 3:
                rgb = np.clip(rgb[:3], 0, 255).astype(np.uint8)
                mu = cv2.cvtColor(np.array([[rgb]], dtype=np.uint8), cv2.COLOR_RGB2HSV)[0, 0].astype(float)
                sig = np.array([15.0, 60.0, 60.0], dtype=float)
            else:
                return None
        if sig.size < 3 or not np.all(np.isfinite(sig[:3])):
            sig = np.array([0.08, 0.20, 0.20], dtype=float) if np.nanmax(mu[:3]) <= 1.5 else np.array([15.0, 60.0, 60.0], dtype=float)

        if np.nanmax(mu[:3]) <= 1.5:
            h = float(mu[0]) * 179.0
            s = float(mu[1]) * 255.0
            v = float(mu[2]) * 255.0
            dh = max(15.0, float(sig[0]) * 179.0 * 3.0)
            ds = max(35.0, float(sig[1]) * 255.0 * 3.0)
            dv = max(35.0, float(sig[2]) * 255.0 * 3.0)
        else:
            h, s, v = float(mu[0]), float(mu[1]), float(mu[2])
            dh = max(15.0, float(sig[0]) * 3.0)
            ds = max(35.0, float(sig[1]) * 3.0)
            dv = max(35.0, float(sig[2]) * 3.0)
        return dict(
            h_lo=int(max(0, round(h - dh))), h_hi=int(min(179, round(h + dh))),
            s_lo=int(max(0, round(s - ds))), s_hi=int(min(255, round(s + ds))),
            v_lo=int(max(0, round(v - dv))), v_hi=int(min(255, round(v + dv))),
        )
    except Exception:
        return None


def _extract_track_cal_from_recordresult_mat(mat_path: str) -> dict:
    """Load recordResult.ocr.trkCalSlim: ROI, 8 minimap points and marker color."""
    out = {}
    try:
        data = sio.loadmat(mat_path, squeeze_me=True, struct_as_record=False)
        rr = _mat_scalar(data.get("recordResult"))
        ocr = _mat_obj_get(rr, "ocr")
        trk = _mat_obj_get(ocr, "trkCalSlim")
        if trk is None:
            return out
        roi = _parse_roi_value(_mat_obj_get(trk, "roi"))
        if roi and len(roi) >= 4 and roi[2] > 0 and roi[3] > 0:
            out["track_roi"] = [float(roi[0]), float(roi[1]), float(roi[2]), float(roi[3])]
        pts = _pts_from_mat_value(_mat_obj_get(trk, "ptsMini"))
        if len(pts) >= 4:
            out["minimap_pts"] = pts[:8]
        cr = _marker_to_color_range(_mat_obj_get(trk, "marker"))
        if cr:
            out["moving_pt_color_range"] = cr
    except NotImplementedError:
        return _extract_track_cal_from_recordresult_hdf5(mat_path)
    except Exception:
        h5_out = _extract_track_cal_from_recordresult_hdf5(mat_path)
        if h5_out:
            return h5_out
    return out




def _extract_track_cal_from_recordresult_hdf5(mat_path: str) -> dict:
    out = {}
    try:
        import h5py
        with h5py.File(mat_path, "r") as f:
            trk = _h5_get_path_ci(f, ["recordResult", "ocr", "trkCalSlim"])
            if trk is None:
                return out
            roi_obj = _h5_get_path_ci(trk, ["roi"])
            roi = _parse_roi_value(_h5_decode_value(roi_obj) if roi_obj is not None else None)
            if roi and len(roi) >= 4 and roi[2] > 0 and roi[3] > 0:
                out["track_roi"] = [float(roi[0]), float(roi[1]), float(roi[2]), float(roi[3])]
            pts_obj = _h5_get_path_ci(trk, ["ptsMini"])
            pts = _pts_from_mat_value(_h5_decode_value(pts_obj) if pts_obj is not None else None)
            if len(pts) >= 4:
                out["minimap_pts"] = pts[:8]
            marker_obj = _h5_get_path_ci(trk, ["marker"])
            marker_val = _h5_decode_value(marker_obj) if marker_obj is not None else None
            # _marker_to_color_range expects object-like fields; for decoded dict use a tiny adapter.
            if isinstance(marker_val, dict):
                class _Obj: pass
                obj = _Obj()
                for k, v in marker_val.items():
                    setattr(obj, k, v)
                marker_val = obj
            cr = _marker_to_color_range(marker_val)
            if cr:
                out["moving_pt_color_range"] = cr
    except Exception:
        pass
    return out


def _extract_track_name_from_recordresult_mat(mat_path: str) -> str:
    try:
        data = sio.loadmat(mat_path, squeeze_me=True, struct_as_record=False)
        rr = _mat_scalar(data.get("recordResult"))
        ocr = _mat_obj_get(rr, "ocr")
        trk = _mat_obj_get(ocr, "track")
        for field in ("name", "track", "trackName", "track_name", "id", "title"):
            txt = _mat_to_text(_mat_obj_get(trk, field), "")
            if txt:
                return txt
    except NotImplementedError:
        try:
            import h5py
            with h5py.File(mat_path, "r") as f:
                trk = _h5_get_path_ci(f, ["recordResult", "ocr", "track"])
                if trk is not None:
                    for field in ("name", "track", "trackName", "track_name", "id", "title"):
                        obj = _h5_get_path_ci(trk, [field])
                        txts = _h5_to_text_list(obj) if obj is not None else []
                        if txts:
                            return str(txts[0])
        except Exception:
            pass
    except Exception:
        pass
    return ""


def _try_auto_load_reference_track_for_name(track_name: str) -> None:
    """Auto-select Nordschleife reference when recordResult.ocr.track says so."""
    if st.session_state.get("ref_track_img") is not None:
        return
    name = str(track_name or "")
    prefer_nord = "nordschleife" in name.lower()
    if not prefer_nord:
        return
    candidates = []
    if st.session_state.get("r2_connected") and st.session_state.get("r2_client") is not None:
        pfx = st.session_state.r2_prefix.strip("/")
        ref_dir = (pfx + "/reference_track_siesmann").strip("/") if pfx else "reference_track_siesmann"
        ok_ls, ref_items = st.session_state.r2_client.list_files(ref_dir)
        if ok_ls and isinstance(ref_items, list):
            mats = [f for f in ref_items if str(f).lower().endswith(".mat")]
            mats = sorted(
                mats,
                key=lambda f: (
                    0 if "nordschleife" in Path(str(f)).stem.lower() and Path(str(f)).stem.lower().endswith("_slim") else
                    1 if "nordschleife" in Path(str(f)).stem.lower() else 2,
                    Path(str(f)).name.lower(),
                ),
            )
            if mats and "nordschleife" in Path(str(mats[0])).stem.lower():
                _load_centerline_from_r2(f"{ref_dir}/{mats[0]}", str(mats[0]))
                return
    # Local fallback for project folder / reference files next to the app.
    try:
        search_roots = [Path.cwd(), Path(__file__).resolve().parent, Path('/mnt/data')]
        seen = set()
        for root in search_roots:
            if not root.exists() or root in seen:
                continue
            seen.add(root)
            for fp in root.rglob("*.mat"):
                nm = fp.name.lower()
                if "nordschleife" in nm:
                    candidates.append(fp)
        candidates = sorted(candidates, key=lambda fp: (0 if fp.stem.lower().endswith("_slim") else 1, fp.name.lower()))
        if candidates:
            _apply_centerline_to_session(str(candidates[0]), candidates[0].name)
    except Exception:
        pass

def _upsert_track_minimap_roi_from_mat(track_roi: list[float]) -> None:
    if not track_roi or len(track_roi) < 4:
        return
    x, y, w, h = [float(v) for v in track_roi[:4]]
    if w <= 0 or h <= 0:
        return
    new_roi = dict(name="track_minimap", x=x, y=y, w=w, h=h, fmt="any", max_scale=float(st.session_state.get("roi_global_scale", 1.2)))
    rois = list(st.session_state.get("rois") or [])
    replaced = False
    for i, r in enumerate(rois):
        if str(r.get("name", "")).strip() == "track_minimap":
            nr = dict(r)
            nr.update(new_roi)
            rois[i] = nr
            replaced = True
            break
    if not replaced:
        rois.append(new_roi)
    st.session_state.rois = _sanitize_rois(rois)


def _mat_has_nonempty_roi_field(x) -> bool:
    roi = _mat_obj_get(x, "roi")
    if roi is None:
        return False
    parsed = _parse_roi_value(roi)
    return bool(parsed and len(parsed) >= 4 and parsed[2] > 0 and parsed[3] > 0)


def _mat_is_nonempty(x) -> bool:
    if x is None:
        return False
    x = _mat_scalar(x)
    try:
        if isinstance(x, np.ndarray):
            return x.size > 0
        if isinstance(x, (str, bytes)):
            return len(x) > 0
        if isinstance(x, (list, tuple, dict)):
            return len(x) > 0
        return True
    except Exception:
        return True


def _mat_to_float(x, default=np.nan) -> float:
    try:
        x = _mat_scalar(x)
        if isinstance(x, np.ndarray):
            x = np.asarray(x, dtype=float).ravel()
            return float(x[0]) if x.size else default
        return float(x)
    except Exception:
        return default


def _mat_truthy(x) -> bool:
    """Robust truth parser for MATLAB values (logical, numeric, char, cell)."""
    if x is None:
        return False
    try:
        x = _mat_scalar(x)
        if isinstance(x, (bool, np.bool_)):
            return bool(x)
        if isinstance(x, (int, float, np.integer, np.floating)):
            return bool(float(x) != 0.0 and np.isfinite(float(x)))
        if isinstance(x, (bytes, bytearray)):
            x = x.decode("utf-8", errors="ignore")
        if isinstance(x, str):
            s = x.strip().strip("'\"").lower()
            return s in {"1", "true", "yes", "ja", "y", "ok", "kein_roi_vorhanden", "kein roi vorhanden", "no_roi_available"}
        if isinstance(x, np.ndarray):
            if x.size == 0:
                return False
            if x.dtype.kind in ("b", "i", "u", "f"):
                vals = np.asarray(x, dtype=float).ravel()
                vals = vals[np.isfinite(vals)]
                return bool(vals.size and np.any(vals != 0.0))
            return any(_mat_truthy(v) for v in x.ravel().tolist())
        txt = _mat_to_text(x, "")
        if txt:
            return _mat_truthy(txt)
    except Exception:
        pass
    return False


def _mat_table_height(tbl) -> int:
    tbl = _mat_scalar(tbl)
    if tbl is None:
        return 0
    try:
        if isinstance(tbl, np.ndarray):
            if tbl.dtype.names:
                return int(tbl.size)
            if tbl.dtype == object:
                vals = [v for v in tbl.ravel().tolist() if v is not None]
                return int(len(vals))
            return int(tbl.shape[0]) if tbl.ndim > 0 else int(tbl.size)
        for name in getattr(tbl, "_fieldnames", []) or []:
            val = _mat_obj_get(tbl, name)
            if isinstance(val, np.ndarray):
                return int(val.size if val.ndim == 1 else val.shape[0])
        return 1 if _mat_is_nonempty(tbl) else 0
    except Exception:
        return 0


def _mat_table_column(tbl, *names):
    """Return one column from MATLAB table-like data, struct arrays, or scipy savemat structs."""
    tbl = _mat_scalar(tbl)
    if tbl is None:
        return None
    for name in names:
        val = _mat_obj_get(tbl, name)
        if val is not None:
            return val
    try:
        if isinstance(tbl, np.ndarray):
            if tbl.dtype.names:
                for name in names:
                    if name in tbl.dtype.names:
                        return tbl[name].ravel()
            vals = []
            found = False
            for item in tbl.ravel().tolist():
                item = _mat_scalar(item)
                for name in names:
                    val = _mat_obj_get(item, name)
                    if val is not None:
                        vals.append(val)
                        found = True
                        break
                else:
                    vals.append(None)
            if found:
                return np.array(vals, dtype=object)
    except Exception:
        pass
    return None


def _mat_numeric_vector(x):
    try:
        arr = np.asarray(_mat_scalar(x), dtype=float).ravel()
        return arr[np.isfinite(arr)]
    except Exception:
        return np.array([], dtype=float)


def _mat_roi_table_has_track(roi_table) -> bool:
    names = _mat_table_column(roi_table, "name_roi", "name", "Name")
    if names is None:
        return False
    try:
        vals = np.asarray(names, dtype=object).ravel().tolist()
        joined = " ".join(_mat_to_text(v, "").lower() for v in vals)
        return "track_minimap" in joined
    except Exception:
        return False


def _summarize_record_result_hdf5(mat_path: str) -> dict:
    out = {}
    try:
        import h5py
        paths = []
        shapes = {}
        with h5py.File(mat_path, "r") as f:
            def visitor(name, obj):
                lname = str(name).lower()
                paths.append(lname)
                if hasattr(obj, "shape"):
                    shapes[lname] = tuple(int(v) for v in obj.shape)
            f.visititems(visitor)
            meta = _h5_get_path_ci(f, ["recordResult", "metadata"])
            if meta is not None:
                for mk in ("video_title", "title", "vehicle_title", "name", "youtube_title"):
                    obj = _h5_get_path_ci(meta, [mk])
                    if obj is None:
                        continue
                    vals = _h5_to_text_list(obj)
                    if vals and str(vals[0]).strip():
                        out[mk] = str(vals[0]).strip()
                        break
                for mk in ("youtube_url", "video_url", "url", "link", "source_url"):
                    obj = _h5_get_path_ci(meta, [mk])
                    if obj is None:
                        continue
                    vals = _h5_to_text_list(obj)
                    if vals and str(vals[0]).strip():
                        out[mk] = str(vals[0]).strip()
                        break
        joined = "\n".join(paths)
        def has(*needles):
            return any(n.lower() in joined for n in needles)
        def nonempty_path(*needles):
            for p, sh in shapes.items():
                if any(n.lower() in p for n in needles):
                    if not sh or int(np.prod(sh)) > 0:
                        return True
            return False
        no_roi_paths = [p for p in paths if ("no_roi_available" in p or "roi_status" in p)]
        out["no_roi_available"] = bool(no_roi_paths)
        vf_paths = [p for p in paths if ("video_faulty" in p or "video_status" in p)]
        out["video_faulty"] = bool(vf_paths)
        out["roi_selected"] = bool((not out.get("no_roi_available")) and nonempty_path("recordresult/ocr/roi_table", "roi_table"))
        out["track_selected"] = bool((not out.get("no_roi_available")) and nonempty_path("recordresult/ocr/trkcalslim/roi"))
        out["start_end_selected"] = has("recordresult/ocr/params/start_s") and has("recordresult/ocr/params/end_s")
        out["ocr_done"] = nonempty_path("recordresult/ocr/table", "recordresult/ocr/cleaned")
        out["ocr_complete"] = bool(out.get("ocr_done") and out.get("start_end_selected"))
        out["audio_spectrogram_done"] = nonempty_path(
            "recordresult/audio_rpm/processed/t_s",  # new 1D field
            "recordresult/audio_rpm/processed",
            "recordresult/audio_rpm/params",
        )
        out["audio_config_done"] = nonempty_path("recordresult/audio_config")
        out["validation_done"] = nonempty_path("recordresult/validation/results")
    except Exception:
        pass
    return out


def _summarize_record_result_mat(mat_path: str) -> dict:
    out = {}
    try:
        data = sio.loadmat(mat_path, squeeze_me=True, struct_as_record=False)
        rr = _mat_scalar(data.get("recordResult"))
        if rr is None:
            return out
        meta = _mat_obj_get(rr, "metadata")
        ocr = _mat_obj_get(rr, "ocr")
        audio_rpm = _mat_obj_get(rr, "audio_rpm")
        validation = _mat_obj_get(rr, "validation")

        video_path = _mat_obj_get(meta, "video") if meta is not None else None
        if video_path is None:
            video_path = _mat_obj_get(rr, "video")
        audio_path = _mat_obj_get(meta, "audio") if meta is not None else None
        if audio_path is None:
            audio_path = _mat_obj_get(rr, "audio")
        out["recordresult_video_path"] = _mat_to_text(video_path, "")
        out["recordresult_audio_path"] = _mat_to_text(audio_path, "")
        # Relevante Anzeige-Metadaten fuer den Audio-Tab mitnehmen.
        # Je nach Erzeuger heisst der YouTube-/Video-Titel unterschiedlich.
        if meta is not None:
            for mk in ("video_title", "title", "vehicle_title", "name", "youtube_title"):
                try:
                    mv = _mat_to_text(_mat_obj_get(meta, mk), "")
                    if mv:
                        mv_txt = str(mv).strip()
                        # scipy.io.savemat can degrade umlauts to '?' in legacy MAT files.
                        # Normalize known artifacts used in regression samples.
                        mv_txt = mv_txt.replace("Sch??fer", "Schäfer").replace("Sch?fer", "Schäfer")
                        out[mk] = mv_txt
                        break
                except Exception:
                    pass
            for mk in ("youtube_url", "video_url", "url", "link", "source_url"):
                try:
                    mv = _mat_to_text(_mat_obj_get(meta, mk), "")
                    if mv:
                        out[mk] = str(mv).strip()
                        break
                except Exception:
                    pass
        no_roi_meta = _mat_obj_get(meta, "no_roi_available") if meta is not None else None
        no_roi_ocr = _mat_obj_get(ocr, "no_roi_available") if ocr is not None else None
        roi_status_meta = _mat_to_text(_mat_obj_get(meta, "roi_status") if meta is not None else None, "")
        roi_status_ocr = _mat_to_text(_mat_obj_get(ocr, "roi_status") if ocr is not None else None, "")
        out["no_roi_available"] = bool(_mat_truthy(no_roi_meta) or _mat_truthy(no_roi_ocr) or "kein_roi" in roi_status_meta.lower() or "kein roi" in roi_status_meta.lower() or "no_roi" in roi_status_meta.lower() or "kein_roi" in roi_status_ocr.lower() or "kein roi" in roi_status_ocr.lower() or "no_roi" in roi_status_ocr.lower())
        vf_meta = _mat_obj_get(meta, "video_faulty") if meta is not None else None
        vf_ocr = _mat_obj_get(ocr, "video_faulty") if ocr is not None else None
        vs_meta = _mat_to_text(_mat_obj_get(meta, "video_status") if meta is not None else None, "")
        vs_ocr = _mat_to_text(_mat_obj_get(ocr, "video_status") if ocr is not None else None, "")
        out["video_faulty"] = bool(_mat_truthy(vf_meta) or _mat_truthy(vf_ocr) or "video_fehlerhaft" in vs_meta.lower() or "video fehlerhaft" in vs_meta.lower() or "video_fehlerhaft" in vs_ocr.lower() or "video fehlerhaft" in vs_ocr.lower())

        params = _mat_obj_get(ocr, "params")
        start_s = _mat_to_float(_mat_obj_get(params, "start_s"))
        end_s = _mat_to_float(_mat_obj_get(params, "end_s"))
        out["start_end_selected"] = bool(np.isfinite(start_s) and np.isfinite(end_s) and end_s > start_s)
        out["t_start"] = start_s if np.isfinite(start_s) else None
        out["t_end"] = end_s if np.isfinite(end_s) else None

        roi_table = _mat_obj_get(ocr, "roi_table")
        roi_rows = _mat_table_height(roi_table)
        if roi_rows <= 0:
            try:
                roi_rows = len(_extract_rois_from_recordresult_hdf5(mat_path))
            except Exception:
                roi_rows = 0
        out["roi_selected"] = bool((not out.get("no_roi_available")) and roi_rows > 0)
        out["roi_count"] = int(roi_rows)

        # OCRExtractor.m stores reusable track calibration in recordResult.ocr.trkCalSlim.
        # Fresh ROI-setup MATs may only contain track_minimap in roi_table.
        trk_slim = _mat_obj_get(ocr, "trkCalSlim")
        out["track_selected"] = bool((not out.get("no_roi_available")) and (_mat_has_nonempty_roi_field(trk_slim) or _mat_roi_table_has_track(roi_table)))

        raw_table = _mat_obj_get(ocr, "table")
        cleaned = _mat_obj_get(ocr, "cleaned")
        raw_rows = _mat_table_height(raw_table)
        clean_rows = _mat_table_height(cleaned)
        out["ocr_done"] = bool(raw_rows > 0 or clean_rows > 0)
        out["ocr_row_count"] = int(max(raw_rows, clean_rows))

        time_col = _mat_table_column(raw_table, "time_s", "t_s")
        if time_col is None:
            time_col = _mat_table_column(cleaned, "time_s", "t_s")
        times = _mat_numeric_vector(time_col)
        if out["ocr_done"] and np.isfinite(end_s) and times.size:
            out["ocr_complete"] = bool(np.nanmax(times) >= (end_s - 1.0))
        else:
            out["ocr_complete"] = bool(out["ocr_done"] and not np.isfinite(end_s))

        ar_processed = _mat_obj_get(audio_rpm, "processed")
        ar_params = _mat_obj_get(audio_rpm, "params")
        # Detect via t_s field (1D array in new format) or fallback to general non-empty checks
        _ar_t_s = _mat_obj_get(ar_processed, "t_s") if ar_processed is not None else None
        _ar_t_s_len = int(np.asarray(_ar_t_s, dtype=float).ravel().size) if _ar_t_s is not None else 0
        out["audio_spectrogram_done"] = bool(
            _ar_t_s_len > 0
            or _mat_table_height(ar_processed) > 0
            or _mat_is_nonempty(ar_params)
        )
        out["audio_config_done"] = bool(_mat_is_nonempty(_mat_obj_get(rr, "audio_config")))

        v_results = _mat_obj_get(validation, "results")
        out["validation_done"] = bool(_mat_is_nonempty(v_results))
    except NotImplementedError:
        out.update(_summarize_record_result_hdf5(mat_path))
    except Exception:
        pass
    return out


def _summary_from_json_sidecar(data: dict) -> tuple[dict, dict]:
    """Extract record_summary and top-level key set from a JSON sidecar (fast path).

    Returns (record_summary_dict, mat_keys_set) in the same shape that
    _summarize_record_result_mat + sio.loadmat produce so the caller can
    run the same merging logic regardless of which path was taken.
    """
    record_summary: dict = {}
    mat_keys: set = set(data.keys())

    rr = data.get("recordResult") or {}
    if not isinstance(rr, dict):
        return record_summary, mat_keys

    meta = rr.get("metadata") or {}
    ocr  = rr.get("ocr") or {}
    arpm = rr.get("audio_rpm") or {}
    vali = rr.get("validation") or {}

    # metadata fields
    for mk in ("video_title", "title", "vehicle_title", "name", "youtube_title"):
        v = str(meta.get(mk) or "").strip()
        if v:
            record_summary[mk] = v
            break
    for mk in ("youtube_url", "video_url", "url", "link", "source_url"):
        v = str(meta.get(mk) or "").strip()
        if v:
            record_summary[mk] = v
            break
    for path_key in ("video", "recordresult_video_path"):
        v = meta.get(path_key) or rr.get("video")
        if v and isinstance(v, str):
            record_summary["recordresult_video_path"] = v
            break
    for path_key in ("audio", "recordresult_audio_path"):
        v = meta.get(path_key) or rr.get("audio")
        if v and isinstance(v, str):
            record_summary["recordresult_audio_path"] = v
            break

    def _truthy_json(v) -> bool:
        if v is None: return False
        if isinstance(v, bool): return v
        if isinstance(v, (int, float)): return bool(v)
        s = str(v).lower().strip()
        return s in {"1", "true", "yes", "ja", "y", "ok"}

    # no_roi_available
    nra = _truthy_json(meta.get("no_roi_available")) or _truthy_json(ocr.get("no_roi_available"))
    rs_meta = str(meta.get("roi_status") or "").lower()
    rs_ocr  = str(ocr.get("roi_status") or "").lower()
    record_summary["no_roi_available"] = bool(nra or "kein_roi" in rs_meta or "kein_roi" in rs_ocr or "no_roi" in rs_meta or "no_roi" in rs_ocr)

    # video_faulty
    vf = _truthy_json(meta.get("video_faulty")) or _truthy_json(ocr.get("video_faulty"))
    vs_meta = str(meta.get("video_status") or "").lower()
    vs_ocr  = str(ocr.get("video_status") or "").lower()
    record_summary["video_faulty"] = bool(vf or "video_fehlerhaft" in vs_meta or "video_fehlerhaft" in vs_ocr)

    # start/end
    ocr_params = ocr.get("params") or {}
    try: start_s = float(ocr_params.get("start_s") or "nan")
    except Exception: start_s = float("nan")
    try: end_s = float(ocr_params.get("end_s") or "nan")
    except Exception: end_s = float("nan")
    record_summary["start_end_selected"] = bool(not (start_s != start_s) and not (end_s != end_s) and end_s > start_s)
    if not (start_s != start_s): record_summary["t_start"] = start_s
    if not (end_s != end_s):     record_summary["t_end"]   = end_s

    def _table_row_count(tbl) -> int:
        if isinstance(tbl, list):
            return len(tbl)
        if isinstance(tbl, dict):
            lens = [len(v) for v in tbl.values() if isinstance(v, list)]
            return max(lens) if lens else 0
        return 0

    # ROI table
    roi_table = ocr.get("roi_table")
    roi_rows = _table_row_count(roi_table)
    record_summary["roi_selected"] = bool((not record_summary["no_roi_available"]) and roi_rows > 0)
    record_summary["roi_count"] = roi_rows

    # Track calibration
    trk = ocr.get("trkCalSlim") or {}
    if isinstance(trk, dict):
        ref_pts  = trk.get("ref_pts") or []
        mini_pts = trk.get("minimap_pts") or []
        record_summary["track_selected"] = bool(
            (not record_summary["no_roi_available"])
            and isinstance(ref_pts, list) and len(ref_pts) >= 8
            and isinstance(mini_pts, list) and len(mini_pts) >= 8
        )
    else:
        record_summary["track_selected"] = False

    # OCR done/complete
    raw  = ocr.get("table") or ocr.get("roi_table_raw")
    clean = ocr.get("cleaned")
    raw_rows = _table_row_count(raw)
    clean_rows = _table_row_count(clean)
    record_summary["ocr_done"]      = bool(raw_rows > 0 or clean_rows > 0)
    record_summary["ocr_row_count"] = int(max(raw_rows, clean_rows))
    if record_summary["ocr_done"] and not (end_s != end_s):
        t_vals = []
        if isinstance(raw, list):
            for row in (raw or []):
                try:
                    t_vals.append(float(row.get("time_s") or row.get("t_s") or "nan"))
                except Exception:
                    pass
        elif isinstance(raw, dict):
            t_col = raw.get("time_s")
            if not isinstance(t_col, list):
                t_col = raw.get("t_s")
            if isinstance(t_col, list):
                for v in t_col:
                    try:
                        t_vals.append(float(v))
                    except Exception:
                        pass
        record_summary["ocr_complete"] = bool(t_vals and max(t_vals) >= (end_s - 1.0))
    else:
        record_summary["ocr_complete"] = bool(record_summary["ocr_done"] and (end_s != end_s))

    # audio_rpm
    proc = arpm.get("processed") or {}
    proc_col = arpm.get("processed_col") or {}
    audio_rows = 0
    if isinstance(proc, dict):
        t_s = proc.get("t_s") or proc.get("t_s_spec") or []
        if isinstance(t_s, list):
            audio_rows = max(audio_rows, len(t_s))
        for v in proc.values():
            if isinstance(v, list):
                audio_rows = max(audio_rows, len(v))
    elif isinstance(proc, list):
        audio_rows = max(audio_rows, len(proc))
    if isinstance(proc_col, dict):
        for v in proc_col.values():
            if isinstance(v, list):
                audio_rows = max(audio_rows, len(v))
    record_summary["audio_spectrogram_done"] = bool(audio_rows > 0 or bool(arpm.get("params")))
    record_summary["audio_config_done"] = bool(rr.get("audio_config"))

    # validation
    record_summary["validation_done"] = bool(vali.get("results"))

    return record_summary, mat_keys


def _compute_mat_summary_remote(remote_key: str, client, prefix: str) -> dict:
    """Build MAT-selection summary from JSON sidecar only (no MAT read)."""
    try:
        json_key = _r2_json_sidecar_key(remote_key)
    except NameError:
        json_key = str(remote_key or "").replace("\\", "/").rsplit(".", 1)[0] + ".json"

    summary: dict = {
        "mat_file": Path(remote_key).name,
        "remote_key": remote_key,
        "error": "",
        "json_sidecar_used": False,
        "json_sidecar_created": False,
        "json_sidecar_key": json_key,
    }
    record_summary: dict = {}
    mat_keys: set = set()

    tmp_json = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
    tmp_json.close()
    try:
        ok_j, msg_j = client.download_file(json_key, tmp_json.name)
        if not ok_j:
            summary['error'] = f'JSON-Download: {msg_j}'
        else:
            try:
                json_data = json.loads(Path(tmp_json.name).read_text(encoding='utf-8', errors='ignore'))
            except Exception as e:
                json_data = {}
                summary['error'] = f'JSON-Parse: {e}'
            if isinstance(json_data, dict) and isinstance(json_data.get('recordResult'), dict):
                record_summary, mat_keys = _summary_from_json_sidecar(json_data)
                summary['json_sidecar_used'] = True
                summary['error'] = ''
            elif not summary.get('error'):
                summary['error'] = 'JSON enthaelt kein recordResult.'
    finally:
        try:
            Path(tmp_json.name).unlink(missing_ok=True)
        except Exception:
            pass

    def _mat_has_any(keys):
        lk = {str(k).lower() for k in mat_keys}
        return any(str(k).lower() in lk for k in keys)

    for k, v in record_summary.items():
        if v is not None:
            summary[k] = v
    summary['no_roi_available'] = bool(summary.get('no_roi_available') or _mat_has_any(['no_roi_available']))
    summary['video_faulty'] = bool(summary.get('video_faulty') or _mat_has_any(['video_faulty']))
    if summary.get('no_roi_available'):
        summary['roi_selected'] = False
    elif 'roi_selected' in record_summary:
        summary['roi_selected'] = bool(record_summary.get('roi_selected'))
    else:
        summary['roi_selected'] = bool(summary.get('roi_selected') or _mat_has_any(['rois', 'roi', 'roi_table', 'roitable']))
    summary['track_selected'] = bool((not summary.get('no_roi_available')) and summary.get('track_selected'))
    summary['start_end_selected'] = bool(summary.get('start_end_selected') or _mat_has_any(['t_start', 't_end', 'start_time', 'end_time', 'startend', 'time_range']))
    summary['ocr_done'] = bool(summary.get('ocr_done') or _mat_has_any(['ocr_results', 'ocr_values', 'results_table']))
    summary['ocr_complete'] = bool(summary.get('ocr_complete') or (summary.get('ocr_done') and not _mat_has_any(['ocr_missing', 'ocr_errors', 'missing_values'])))
    summary['audio_spectrogram_done'] = bool(summary.get('audio_spectrogram_done') or _mat_has_any(['spectrogram', 'audio_spectrogram', 'audioanalysis', 'audio_analysis', 'pxx', 'audio_rpm']))
    summary['audio_config_done'] = bool(summary.get('audio_config_done') or _mat_has_any(['audio_config', 'audioconfig']))
    summary['validation_done'] = bool(summary.get('validation_done') or _mat_has_any(['validation', 'validated', 'validierung', 'validation_results']))

    summary['mat_file'] = Path(remote_key).name
    summary['remote_key'] = remote_key
    if not summary.get('capture_folder'):
        summary['capture_folder'] = _mat_capture_guess_from_key(remote_key)
    capture_folder = summary.get('capture_folder', '')
    summary['video_file_exists'] = None
    summary['audio_file_exists'] = None

    if capture_folder:
        cap_dir = f"{prefix}/captures/{capture_folder}" if prefix else f"captures/{capture_folder}"
        ok_list, items = client.list_files(cap_dir)
        if ok_list and isinstance(items, list):
            files = [n for n in items if not n.endswith('/')]
            lower_files = [n.lower() for n in files]
            has_full_or_proxy_video = any(
                n.endswith(('.mp4', '.mov', '.avi', '.mkv')) for n in lower_files
            )
            has_audio_file = any(
                n.endswith(('.wav', '.mp3', '.m4a', '.aac', '.flac')) for n in lower_files
            )
            has_framepack = 'frames_1fps/' in items
            framepack_count = 0
            framepack_expected = 0
            framepack_complete = False
            if has_framepack:
                ok_fp, fp_items = client.list_files(f"{cap_dir}/frames_1fps")
                if ok_fp and isinstance(fp_items, list):
                    framepack_count = len([
                        x for x in fp_items if str(x).lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))
                    ])
                    if 'index.json' in fp_items:
                        tmp_idx = tempfile.NamedTemporaryFile(delete=False, suffix='.json')
                        tmp_idx.close()
                        ok_idx, _ = client.download_file(f"{cap_dir}/frames_1fps/index.json", tmp_idx.name)
                        if ok_idx:
                            try:
                                payload = json.loads(Path(tmp_idx.name).read_text(encoding='utf-8', errors='ignore'))
                                framepack_expected = int(payload.get('frame_count', 0) or 0)
                            except Exception:
                                framepack_expected = 0
                        try:
                            Path(tmp_idx.name).unlink(missing_ok=True)
                        except Exception:
                            pass
                    framepack_complete = framepack_count > 0 and (
                        framepack_expected <= 0 or framepack_count >= framepack_expected
                    )
            has_audio_proxy = any(n == AUDIO_PROXY_NAME.lower() for n in lower_files)
            summary['framepack_count'] = int(framepack_count)
            summary['framepack_expected'] = int(framepack_expected)
            summary['framepack_complete'] = bool(framepack_complete)
            summary['audio_proxy_present'] = bool(has_audio_proxy)
            has_full_audio = any(
                n.endswith(('.wav', '.mp3', '.m4a', '.aac', '.flac')) and n != AUDIO_PROXY_NAME.lower()
                for n in lower_files
            )
            summary['video_file_exists'] = bool(has_full_or_proxy_video)
            summary['audio_file_exists'] = bool(has_full_audio)
            if not framepack_complete and has_framepack:
                summary['media_detail'] = f"Frames unvollstaendig ({framepack_count}/{framepack_expected or '?' })."
            elif not has_framepack:
                summary['media_detail'] = 'Frames fehlen.'
            elif not summary['audio_file_exists']:
                summary['media_detail'] = 'Audio fehlt.'
            else:
                summary['media_detail'] = ''
        else:
            summary['media_detail'] = 'Capture-Ordner nicht lesbar.'
    else:
        summary['media_detail'] = ''

    summary['json_sidecar_created'] = False
    try:
        summary['json_sidecar_key'] = _r2_json_sidecar_key(remote_key)
    except NameError:
        summary['json_sidecar_key'] = str(remote_key or '').replace('\\', '/').rsplit('.', 1)[0] + '.json'

    return summary

def _compute_folder_only_summary(folder: str, client, prefix: str) -> dict:
    summary = {
        "mat_file": "",
        "remote_key": "",
        "capture_folder": folder,
        "video_file_exists": False,
        "audio_file_exists": False,
        "no_roi_available": False,
        "video_faulty": False,
        "roi_selected": False,
        "track_selected": False,
        "start_end_selected": False,
        "ocr_done": False,
        "ocr_complete": False,
        "audio_config_done": False,
        "audio_spectrogram_done": False,
        "validation_done": False,
        "error": "",
        "media_detail": "",
    }
    cap_dir = f"{prefix}/captures/{folder}" if prefix else f"captures/{folder}"
    ok_list, items = client.list_files(cap_dir)
    if not ok_list or not isinstance(items, list):
        summary["error"] = "Capture-Ordner nicht lesbar."
        return summary

    files = [n for n in items if not n.endswith("/")]
    lower_files = [n.lower() for n in files]
    has_full_video = any(n.endswith((".mp4", ".mov", ".avi", ".mkv")) for n in lower_files)
    has_audio_proxy = any(n == AUDIO_PROXY_NAME.lower() for n in lower_files)
    has_full_audio = any(
        n.endswith((".wav", ".mp3", ".m4a", ".aac", ".flac")) and n != AUDIO_PROXY_NAME.lower()
        for n in lower_files
    )

    has_framepack = "frames_1fps/" in items
    framepack_count = 0
    framepack_expected = 0
    if has_framepack:
        ok_fp, fp_items = client.list_files(f"{cap_dir}/frames_1fps")
        if ok_fp and isinstance(fp_items, list):
            framepack_count = len([
                x for x in fp_items if str(x).lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
            ])
            if "index.json" in fp_items:
                tmp_idx = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
                tmp_idx.close()
                ok_idx, _ = client.download_file(f"{cap_dir}/frames_1fps/index.json", tmp_idx.name)
                if ok_idx:
                    try:
                        payload = json.loads(Path(tmp_idx.name).read_text(encoding="utf-8", errors="ignore"))
                        framepack_expected = int(payload.get("frame_count", 0) or 0)
                    except Exception:
                        framepack_expected = 0
                try:
                    Path(tmp_idx.name).unlink(missing_ok=True)
                except Exception:
                    pass

    framepack_complete = framepack_count > 0 and (framepack_expected <= 0 or framepack_count >= framepack_expected)
    summary["video_file_exists"] = bool(has_full_video)
    summary["audio_file_exists"] = bool(has_full_audio)
    if not framepack_complete and has_framepack:
        summary["media_detail"] = f"Frames unvollstaendig ({framepack_count}/{framepack_expected or '?'})."
    elif not has_framepack:
        summary["media_detail"] = "Frames fehlen."
    elif not summary["audio_file_exists"]:
        summary["media_detail"] = "Audio fehlt."
    else:
        summary["media_detail"] = ""
    return summary


def _get_mat_summary_from_r2(remote_key: str):
    cache = st.session_state.get("mat_summary_cache")
    if isinstance(cache, dict) and remote_key in cache:
        cval = cache.get(remote_key)
        if isinstance(cval, dict):
            return dict(cval)
    summary = _compute_mat_summary_remote(
        remote_key=remote_key,
        client=st.session_state.r2_client,
        prefix=st.session_state.r2_prefix.strip("/"),
    )
    if isinstance(cache, dict):
        cache[remote_key] = dict(summary)
        st.session_state.mat_summary_cache = cache
    return summary


def _analyze_mat_from_r2(remote_key: str):
    summary = _get_mat_summary_from_r2(remote_key)
    if summary.get("error"):
        set_status(f"JSON-Analysefehler: {summary['error']}", "warn")
    st.session_state.mat_selected_summary = summary


def _jn(value) -> str:
    return LAMP_GREEN if bool(value) else LAMP_RED


def _summary_to_overview_row(summary: dict, display_folder: str = "") -> dict:
    folder_label = display_folder or summary.get("capture_folder") or summary.get("mat_file", "")
    video_title = ""
    if isinstance(summary, dict):
        for key in ("video_title", "youtube_title", "title", "vehicle_title", "name"):
            txt = str(summary.get(key, "") or "").strip()
            if txt:
                video_title = txt
                break
    return {
        "mat_datei": folder_label,
        "video_title": video_title,
        "remote_key": summary.get("remote_key", ""),
        "audio_video_vorhanden": _jn(
            bool(summary.get("video_file_exists")) and bool(summary.get("audio_file_exists"))
        ),
        "kein_roi_vorhanden": _jn(summary.get("no_roi_available")),
        "video_fehlerhaft": _jn(summary.get("video_faulty")),
        "roi_ausgewaehlt": _jn(summary.get("roi_selected")),
        "track_ausgewaehlt": _jn(summary.get("track_selected")),
        "anfang_ende_ausgewaehlt": _jn(summary.get("start_end_selected")),
        "audio_config": _jn(summary.get("audio_config_done")),
        "ocr_durchgefuehrt": _jn(summary.get("ocr_done")),
        "ocr_vollstaendig": _jn(summary.get("ocr_complete")),
        "audioanalyse_spektrogramm": _jn(summary.get("audio_spectrogram_done")),
        "validierung": _jn(summary.get("validation_done")),
        "fehler": summary.get("error", "") or summary.get("media_detail", ""),
    }


def _placeholder_overview_row(target) -> dict:
    if isinstance(target, dict):
        folder = str(target.get("folder", "") or "")
        mat_key = str(target.get("mat_key", "") or "")
    else:
        folder = ""
        mat_key = str(target)
    title = folder or Path(mat_key).name
    return {
        "mat_datei": title,
        "video_title": "...",
        "remote_key": mat_key,
        "audio_video_vorhanden": "...",
        "kein_roi_vorhanden": "...",
        "video_fehlerhaft": "...",
        "roi_ausgewaehlt": "...",
        "track_ausgewaehlt": "...",
        "anfang_ende_ausgewaehlt": "...",
        "audio_config": "...",
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
    targets = []
    for it in remote_keys:
        if isinstance(it, dict):
            targets.append(it)
        else:
            targets.append({"kind": "mat_only", "folder": _mat_capture_guess_from_key(str(it)), "mat_key": str(it)})
    st.session_state.mat_update_keys = list(targets)
    st.session_state.mat_update_total = len(targets)
    st.session_state.mat_update_idx = 0
    st.session_state.mat_update_running = len(targets) > 0
    st.session_state.mat_run_state = "running" if len(targets) > 0 else "idle"
    st.session_state.mat_update_stop_requested = False
    st.session_state.mat_overview_rows = [_placeholder_overview_row(t) for t in targets]

@st.cache_resource(show_spinner=False)
def _mat_update_executor():
    return cf.ThreadPoolExecutor(max_workers=1, thread_name_prefix="mat_update")


def _mat_update_worker(targets, client, prefix: str, stop_event, out_queue):
    """Background MAT analyzer that streams row results through a queue."""
    try:
        for idx, target in enumerate(list(targets or [])):
            if stop_event is not None and stop_event.is_set():
                out_queue.put({"type": "stopped", "idx": idx})
                return
            folder = str(target.get("folder", "") or "") if isinstance(target, dict) else ""
            key = str(target.get("mat_key", "") or "") if isinstance(target, dict) else str(target)
            if key:
                summary = _compute_mat_summary_remote(key, client, prefix)
            else:
                summary = _compute_folder_only_summary(folder=folder, client=client, prefix=prefix)
            out_queue.put(
                {
                    "type": "row",
                    "idx": int(idx),
                    "folder": folder,
                    "mat_key": key,
                    "summary": summary,
                }
            )
        out_queue.put({"type": "done", "total": len(list(targets or []))})
    except Exception as exc:
        out_queue.put({"type": "error", "error": f"{exc.__class__.__name__}: {exc}"})


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

    target = keys[idx]
    folder = str(target.get("folder", "") or "") if isinstance(target, dict) else ""
    key = str(target.get("mat_key", "") or "") if isinstance(target, dict) else str(target)
    if key:
        summary = _get_mat_summary_from_r2(key)
    else:
        summary = _compute_folder_only_summary(
            folder=folder,
            client=st.session_state.r2_client,
            prefix=st.session_state.r2_prefix.strip("/"),
        )
    st.session_state.mat_overview_rows[idx] = _summary_to_overview_row(summary, display_folder=folder)
    st.session_state.mat_update_idx = idx + 1

    if st.session_state.mat_update_idx >= total:
        st.session_state.mat_update_running = False
        st.session_state.mat_run_state = "idle"
        set_status(f"Analyse fuer {total} MAT-Dateien abgeschlossen.", "ok")



def _render_disabled_mat_overview_table(slot, rows_or_df):
    df = rows_or_df if isinstance(rows_or_df, pd.DataFrame) else pd.DataFrame(rows_or_df)
    slot.dataframe(
        df.drop(columns=["remote_key"], errors="ignore"),
        width="stretch",
        hide_index=True,
        height=MAT_TABLE_HEIGHT,
        column_config=MAT_OVERVIEW_COLCFG,
    )

def _status_cell_style(value):
    txt = str(value)
    if (LAMP_GREEN in txt) or txt.endswith("Ja"):
        return "background-color: #0f3d1f; color: #e8ffe8;"
    if (LAMP_RED in txt) or txt.endswith("Nein"):
        return "background-color: #4a1d1d; color: #ffe8e8;"
    return ""


def _style_overview_dataframe(df: pd.DataFrame):
    status_cols = [
        "audio_video_vorhanden",
        "kein_roi_vorhanden",
        "video_fehlerhaft",
        "roi_ausgewaehlt",
        "track_ausgewaehlt",
        "anfang_ende_ausgewaehlt",
        "audio_config",
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


def _normalize_overview_lamps(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df

    def _decode_mojibake_once(s: str) -> str:
        try:
            return s.encode("latin-1", errors="strict").decode("utf-8", errors="strict")
        except Exception:
            return s

    def _norm_cell(v):
        s = str(v)
        cur = s
        for _ in range(3):
            nxt = _decode_mojibake_once(cur)
            if nxt == cur:
                break
            cur = nxt
        if cur == LAMP_GREEN or cur == MOJIBAKE_GREEN:
            return LAMP_GREEN
        if cur == LAMP_RED or cur == MOJIBAKE_RED:
            return LAMP_RED
        return v

    out = df.copy()
    status_cols = [
        "audio_video_vorhanden",
        "kein_roi_vorhanden",
        "video_fehlerhaft",
        "roi_ausgewaehlt",
        "track_ausgewaehlt",
        "anfang_ende_ausgewaehlt",
        "audio_config",
        "ocr_durchgefuehrt",
        "ocr_vollstaendig",
        "audioanalyse_spektrogramm",
        "validierung",
    ]
    for col in status_cols:
        if col in out.columns:
            out[col] = out[col].map(_norm_cell)
    return out

def _overview_status_true(value) -> bool:
    txt = str(value or "").strip()
    return txt in (LAMP_GREEN, MOJIBAKE_GREEN, "Ja", "True", "true", "1") or LAMP_GREEN in txt


def _render_mat_selection_analysis(df: pd.DataFrame, title_suffix: str = "") -> None:
    """Render a non-interactive MAT status analysis below the selection table."""
    if df is None or df.empty:
        return
    status_items = [
        ("Audio+Video", "audio_video_vorhanden"),
        ("Kein ROI", "kein_roi_vorhanden"),
        ("Video fehlerhaft", "video_fehlerhaft"),
        ("ROI", "roi_ausgewaehlt"),
        ("Track", "track_ausgewaehlt"),
        ("Start/Ende", "anfang_ende_ausgewaehlt"),
        ("Audio Config", "audio_config"),
        ("OCR", "ocr_durchgefuehrt"),
        ("OCR vollst.", "ocr_vollstaendig"),
        ("Audioanalyse", "audioanalyse_spektrogramm"),
        ("Validierung", "validierung"),
    ]
    total = int(len(df))
    rows = []
    for label, col in status_items:
        ok = int(df[col].map(_overview_status_true).sum()) if col in df.columns else 0
        pct = (100.0 * ok / total) if total else 0.0
        rows.append((label, ok, total, pct))

    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown(f'<div class="section-title">MAT-Analyse{title_suffix}</div>', unsafe_allow_html=True)

    kpi_html = ['<div class="mat-analysis-grid">']
    for label, ok, total_n, pct in rows[:4]:
        kpi_html.append(
            f'''<div class="mat-analysis-card">
                <div class="mat-analysis-title">{label}</div>
                <div class="mat-analysis-value">{ok}/{total_n}</div>
                <div class="mat-progress-outer"><div class="mat-progress-inner" style="width:{pct:.1f}%"></div></div>
                <div class="mat-analysis-sub">{pct:.0f}% vorhanden</div>
            </div>'''
        )
    kpi_html.append('</div>')
    st.markdown("".join(kpi_html), unsafe_allow_html=True)

    bar_html = ['<div class="mat-analysis-bars">']
    for label, ok, total_n, pct in rows:
        bar_html.append(
            f'''<div class="mat-analysis-bar-row">
                <div>{label}</div>
                <div class="mat-analysis-bar-track"><div class="mat-analysis-bar-fill" style="width:{pct:.1f}%"></div></div>
                <div>{ok}/{total_n} · {pct:.0f}%</div>
            </div>'''
        )
    bar_html.append('</div>')
    st.markdown("".join(bar_html), unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

def _bulk_convert_missing_mat_sidecars(targets: list[dict], client, max_workers: int = 4) -> int:
    """Create JSON sidecars for all MAT targets that currently have none.

    The conversion is scoped to MAT keys visible in MAT Selection and runs in
    parallel for throughput on large result sets.
    """
    if client is None:
        return 0
    mat_keys = []
    for target in list(targets or []):
        if not isinstance(target, dict):
            continue
        mk = str(target.get("mat_key", "") or "").strip().replace("\\", "/")
        if mk.lower().endswith(".mat"):
            mat_keys.append(mk)
    if not mat_keys:
        return 0
    mat_keys = sorted(set(mat_keys))

    res_dir = _results_dir_key().strip("/")
    existing_json_keys: set[str] = set()
    try:
        ok_ls, res_items = client.list_files(res_dir)
        if ok_ls and isinstance(res_items, list):
            for name in res_items:
                if str(name).endswith("/"):
                    continue
                if str(name).lower().endswith(".json"):
                    key = f"{res_dir}/{name}" if res_dir else str(name)
                    existing_json_keys.add(key.strip("/").replace("\\", "/"))
    except Exception:
        pass

    missing_mat_keys = []
    for mk in mat_keys:
        jk = _r2_json_sidecar_key(mk).strip("/").replace("\\", "/")
        if jk not in existing_json_keys:
            missing_mat_keys.append(mk)
    if not missing_mat_keys:
        return 0

    def _convert_one(mat_key: str) -> bool:
        tmp_mat = tempfile.NamedTemporaryFile(delete=False, suffix=".mat")
        tmp_mat.close()
        try:
            ok_dl, _msg_dl = client.download_file(mat_key, tmp_mat.name)
            if not ok_dl:
                return False
            try:
                raw_bytes = Path(tmp_mat.name).read_bytes()
                json_bytes = _mat_bytes_to_recordresult_json_bytes(raw_bytes)
                if not json_bytes:
                    return False
            except Exception:
                return False
        finally:
            try:
                Path(tmp_mat.name).unlink(missing_ok=True)
            except Exception:
                pass
        json_key = _r2_json_sidecar_key(mat_key)
        try:
            if hasattr(client, "upload_bytes"):
                ok_up, _msg_up = client.upload_bytes(
                    json_bytes,
                    json_key,
                    content_type="application/json",
                )
            else:
                tmp_json = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
                tmp_json.close()
                try:
                    Path(tmp_json.name).write_bytes(json_bytes)
                    ok_up, _msg_up = client.upload_file(tmp_json.name, json_key)
                finally:
                    try:
                        Path(tmp_json.name).unlink(missing_ok=True)
                    except Exception:
                        pass
            return bool(ok_up)
        except Exception:
            return False

    workers = max(1, min(int(max_workers or 1), 8))
    created = 0
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(_convert_one, key) for key in missing_mat_keys]
        for fut in cf.as_completed(futures):
            try:
                if fut.result():
                    created += 1
            except Exception:
                pass
    return int(created)

def _update_all_mat_overview_rows(remote_keys: list[str], live_table=None, progress_slot=None):
    """
    Backward-compatible synchronous updater for MAT overview rows.
    """
    _start_mat_update(remote_keys)
    st.session_state.mat_json_sidecar_created_count = 0
    st.session_state.mat_json_sidecar_used_count = 0
    total = len(st.session_state.mat_update_keys or [])
    st.session_state.mat_json_sidecar_last_run_total = total
    progress = progress_slot.progress(0, text=f"0/0 aktuell analysiert · {total} offen") if (total > 0 and progress_slot is not None) else None
    try:
        cache = st.session_state.get("mat_summary_cache")
        if not isinstance(cache, dict):
            cache = {}

        targets = list(st.session_state.mat_update_keys or [])
        pre_created = _bulk_convert_missing_mat_sidecars(
            targets,
            st.session_state.get("r2_client"),
            max_workers=max(2, min(8, (os.cpu_count() or 4))),
        )
        st.session_state.mat_json_sidecar_created_count = int(pre_created)
        pending_idx = []
        done = 0
        for i, t in enumerate(targets):
            mk = str(t.get("mat_key", "") or "")
            folder = str(t.get("folder", "") or "")
            if mk and mk in cache:
                cached_summary = dict(cache[mk])
                if cached_summary.get("json_sidecar_used"):
                    st.session_state.mat_json_sidecar_used_count += 1
                st.session_state.mat_overview_rows[i] = _summary_to_overview_row(cached_summary, display_folder=folder)
                done += 1
            else:
                pending_idx.append(i)

        st.session_state.mat_update_idx = done
        if live_table is not None:
            _render_disabled_mat_overview_table(live_table, st.session_state.mat_overview_rows)
        if progress is not None and total > 0:
            progress.progress(min(1.0, done / total), text=f"{done}/{max(done + len(pending_idx), 1)} aktuell analysiert · {max(0, total-done)} offen")

        if pending_idx:
            max_workers = max(2, min(8, (os.cpu_count() or 4)))
            pfx = st.session_state.r2_prefix.strip("/")
            client = st.session_state.r2_client
            with cf.ThreadPoolExecutor(max_workers=max_workers) as ex:
                fut_to_idx = {}
                for i in pending_idx:
                    t = targets[i]
                    mk = str(t.get("mat_key", "") or "")
                    folder = str(t.get("folder", "") or "")
                    if mk:
                        fut = ex.submit(_compute_mat_summary_remote, mk, client, pfx)
                    else:
                        fut = ex.submit(_compute_folder_only_summary, folder, client, pfx)
                    fut_to_idx[fut] = i

                for fut in cf.as_completed(fut_to_idx):
                    i = fut_to_idx[fut]
                    t = targets[i]
                    mk = str(t.get("mat_key", "") or "")
                    folder = str(t.get("folder", "") or "")
                    try:
                        summary = fut.result()
                    except Exception as e:
                        summary = {"mat_file": Path(mk).name if mk else "", "remote_key": mk, "error": f"{e.__class__.__name__}: {e}"}
                    if summary.get("json_sidecar_used"):
                        st.session_state.mat_json_sidecar_used_count += 1
                    if summary.get("json_sidecar_created"):
                        st.session_state.mat_json_sidecar_created_count += 1
                    if mk:
                        cache[mk] = dict(summary)
                    st.session_state.mat_overview_rows[i] = _summary_to_overview_row(summary, display_folder=folder)
                    done += 1
                    st.session_state.mat_update_idx = done
                    if live_table is not None:
                        _render_disabled_mat_overview_table(live_table, st.session_state.mat_overview_rows)
                    if progress is not None and total > 0:
                        progress.progress(min(1.0, done / total), text=f"{done}/{max(done + sum(1 for f in fut_to_idx if not f.done()), done, 1)} aktuell analysiert · {max(0, total-done)} offen")

        st.session_state.mat_summary_cache = cache
        st.session_state.mat_update_running = False
        st.session_state.mat_run_state = "idle"
    except Exception:
        while st.session_state.mat_update_running:
            _step_mat_update_once()
            done = int(st.session_state.mat_update_idx or 0)
            if live_table is not None:
                live_table.dataframe(
                    pd.DataFrame(st.session_state.mat_overview_rows),
                    width="stretch",
                    hide_index=True,
                    height=MAT_TABLE_HEIGHT,
                    column_config=MAT_OVERVIEW_COLCFG,
                )
            if progress is not None and total > 0:
                progress.progress(min(1.0, done / total), text=f"{done}/{max(done,1)} aktuell analysiert · {max(0, total-done)} offen")

    if progress is not None:
        progress.empty()


def _try_load_video_for_capture_folder(capture_folder: str) -> bool:
    return _try_load_video_for_capture_folder_with_fallback(capture_folder, None)


def _capture_folder_from_path_hint(path_hint) -> str:
    txt = str(path_hint or "").strip().replace("\\", "/")
    if not txt:
        return ""
    parts = [p for p in txt.split("/") if p not in ("", ".", "..")]
    if not parts:
        return ""
    low = [p.lower() for p in parts]
    if "captures" in low:
        i = low.index("captures")
        if i + 1 < len(parts):
            return str(parts[i + 1]).strip()
    return str(parts[-1]).strip()


def _capture_folder_candidates_from_json_doc(capture_folder: str, json_doc: dict | None) -> list[str]:
    cands: list[str] = []

    def _add(v):
        txt = str(v or "").strip().strip("/\\")
        if not txt:
            return
        if txt not in cands:
            cands.append(txt)

    _add(capture_folder)
    rr = (json_doc or {}).get("recordResult") if isinstance(json_doc, dict) else {}
    rr = rr if isinstance(rr, dict) else {}
    meta = rr.get("metadata") if isinstance(rr.get("metadata"), dict) else {}
    for k in ("outdir", "video", "audio", "capture_folder"):
        _add(_capture_folder_from_path_hint((meta or {}).get(k)))
    for k in ("video", "audio", "outdir", "capture_folder"):
        _add(_capture_folder_from_path_hint(rr.get(k)))
    return cands


def _load_full_video_from_r2(capture_folder: str) -> bool:
    if not capture_folder or st.session_state.get("r2_client") is None:
        return False
    pfx = str(st.session_state.get("r2_prefix") or "").strip("/")
    cap_dir = f"{pfx}/captures/{capture_folder}" if pfx else f"captures/{capture_folder}"
    ok, items = st.session_state.r2_client.list_files(cap_dir)
    if not ok or not isinstance(items, list):
        return False
    files = [str(n) for n in items if isinstance(n, str) and not str(n).endswith("/")]
    vids = [n for n in files if str(n).lower().endswith(VIDEO_EXTS) and "_1fps" not in str(n).lower()]
    if not vids:
        return False
    prio = {".avi": 0, ".mp4": 1, ".mov": 2, ".mkv": 3}
    vids = sorted(vids, key=lambda n: (prio.get(Path(n).suffix.lower(), 9), n.lower()))
    key = f"{cap_dir}/{vids[0]}"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=Path(vids[0]).suffix or ".mp4")
    tmp.close()
    ok_dl, msg_dl = st.session_state.r2_client.download_file(key, tmp.name)
    if not ok_dl:
        set_status(f"Video-Download: {msg_dl}", "warn")
        return False
    _apply_video(tmp.name, Path(vids[0]).name)
    return True


def _try_load_video_for_capture_folder_with_fallback(capture_folder: str, json_doc: dict | None = None) -> bool:
    cands = _capture_folder_candidates_from_json_doc(capture_folder, json_doc)
    if not cands:
        return False
    for folder in cands:
        local_video = _find_local_fullfps_video(folder)
        if local_video is not None and local_video.exists():
            _apply_video(str(local_video), local_video.name)
            st.session_state.capture_folder = folder
            st.session_state["_mat_last_video_capture_folder"] = folder
            return True
    return False


def _overview_status_is_green(value) -> bool:
    txt = str(value or "").strip()
    return txt in {LAMP_GREEN, MOJIBAKE_GREEN, "Ja", "OK", "True", "true", "1"}


def _current_capture_folder() -> str:
    cf = str(st.session_state.get("capture_folder") or "").strip().strip("/\\")
    if cf:
        return cf
    video_name = str(st.session_state.get("video_name") or "").strip()
    if video_name:
        stem = Path(video_name.replace(" [frames_1fps]", "")).stem
        if stem:
            return stem
    selected = str(st.session_state.get("mat_selected_key") or "").strip()
    if selected:
        return _mat_capture_guess_from_key(selected) or Path(selected).stem.replace("results_", "", 1)
    return ""


def _capture_results_dir_key(capture_folder: str) -> str:
    pfx = st.session_state.r2_prefix.strip("/")
    folder = str(capture_folder or "").strip("/\\")
    if not folder:
        return _results_dir_key().strip("/")
    return f"{pfx}/captures/{folder}" if pfx else f"captures/{folder}"


def _build_current_roi_save_summary(capture_folder: str, mat_key: str, no_roi: bool = False, video_faulty: bool = False) -> dict:
    """Build an immediate MAT-selection summary from the current UI state.

    This avoids waiting for R2 overwrite consistency or a second MAT download right
    after saving. The uploaded MAT is still the source of truth on the next full
    refresh, but the row shown to the user is updated immediately.
    """
    rois = list(st.session_state.get("rois") or [])
    has_roi = bool(rois) and not bool(no_roi)
    has_track = False
    if has_roi:
        for r in rois:
            if str(r.get("name", "")).strip() == "track_minimap":
                try:
                    has_track = float(r.get("w", 0) or 0) > 0 and float(r.get("h", 0) or 0) > 0
                except Exception:
                    has_track = True
                break
    t_start = float(st.session_state.get("t_start", 0.0) or 0.0)
    t_end = float(st.session_state.get("t_end", 0.0) or 0.0)
    current_summary = dict(st.session_state.get("mat_selected_summary") or {})
    return {
        **current_summary,
        "mat_file": Path(mat_key).name if mat_key else f"results_{capture_folder}.mat",
        "remote_key": mat_key,
        "capture_folder": capture_folder,
        "no_roi_available": bool(no_roi),
        "video_faulty": bool(video_faulty),
        "roi_selected": bool(has_roi),
        "roi_count": int(len(rois) if has_roi else 0),
        "track_selected": bool(has_track),
        "start_end_selected": bool(t_end > t_start),
        "t_start": t_start,
        "t_end": t_end,
    }


def _invalidate_and_update_mat_selection_for_capture(capture_folder: str, mat_key: str = "", no_roi: bool = False, video_faulty: bool = False) -> None:
    """Refresh cached MAT-selection status for the saved capture without rescanning everything."""
    folder = str(capture_folder or "").strip("/\\")
    key = str(mat_key or "").strip("/")
    try:
        if key and isinstance(st.session_state.get("mat_summary_cache"), dict):
            st.session_state.mat_summary_cache.pop(key, None)
        if key and st.session_state.get("r2_client") is not None:
            summary = _build_current_roi_save_summary(folder, key, no_roi=no_roi, video_faulty=video_faulty)
            cache = st.session_state.get("mat_summary_cache")
            if isinstance(cache, dict):
                cache[key] = dict(summary)
                st.session_state.mat_summary_cache = cache
            row = _summary_to_overview_row(summary, display_folder=folder)
            rows = list(st.session_state.get("mat_overview_rows") or [])
            replaced = False
            for i, old in enumerate(rows):
                if str(old.get("mat_datei", "")) == folder or str(old.get("remote_key", "")) == key:
                    rows[i] = row
                    replaced = True
                    break
            if not replaced:
                rows.insert(0, row)
            st.session_state.mat_overview_rows = rows
            st.session_state.mat_selected_key = key
            st.session_state.mat_pending_selected_key = key
            st.session_state.mat_user_selected_key = key
            st.session_state.mat_selected_summary = summary

            targets = list(st.session_state.get("mat_targets") or [])
            found = False
            for t in targets:
                if str(t.get("folder", "")) == folder:
                    t["mat_key"] = key
                    found = True
                    break
            if not found and folder:
                targets.insert(0, {"kind": "folder", "folder": folder, "mat_key": key})
            st.session_state.mat_targets = targets
    except Exception as e:
        set_status(f"MAT Selection konnte nicht aktualisiert werden: {e}", "warn")
def _find_next_roi_setup_target() -> dict | None:
    """Return next local capture that has video + audio but no complete ROI."""
    base_lp = str(st.session_state.get("local_base_path") or "").strip()
    if not base_lp:
        return None
    base = Path(base_lp).expanduser().resolve()
    res_dir = base / "results"
    cap_root = base / "captures"
    if not res_dir.exists():
        return None
    current = _current_capture_folder()
    video_exts = {".mp4", ".mov", ".avi", ".mkv"}
    audio_exts = {".wav", ".mp3", ".m4a", ".aac", ".flac"}
    try:
        from app_tabs.media_tab import _read_json_detail
    except Exception:
        _read_json_detail = None
    for jp in sorted(res_dir.glob("results_*.json")):
        folder = jp.stem.replace("results_", "", 1)
        if folder == current:
            continue
        cap_dir = cap_root / folder
        has_video = has_audio = False
        if cap_dir.exists():
            for f in cap_dir.iterdir():
                if not f.is_file() or f.stat().st_size <= 0:
                    continue
                ext = f.suffix.lower()
                if ext in video_exts:
                    has_video = True
                elif ext in audio_exts:
                    has_audio = True
        if not (has_video and has_audio):
            continue
        if callable(_read_json_detail):
            detail = _read_json_detail(jp)
            if detail.get("video_faulty"):
                continue
            if detail.get("no_roi_available"):
                continue
            roi_status = detail.get("roi_status", "nein")
            if roi_status == "vollständig":
                continue
        else:
            try:
                doc = json.loads(jp.read_text(encoding="utf-8", errors="ignore"))
                rr = doc.get("recordResult") or {}
                ocr = rr.get("ocr") or {}
                meta = rr.get("metadata") or {}
                if ocr.get("video_faulty") or meta.get("video_faulty"):
                    continue
                if ocr.get("no_roi_available") or meta.get("no_roi_available"):
                    continue
                if ocr.get("roi_table"):
                    continue  # has ROI
            except Exception:
                continue
        return {"folder": folder, "json_path": str(jp)}
    return None


def _load_next_roi_setup_file() -> tuple[bool, str]:
    if not bool(st.session_state.get("local_connected")):
        return False, "Lokale DB nicht verbunden. Bitte zuerst Ordner wählen."
    nxt = _find_next_roi_setup_target()
    if not nxt:
        return False, "Keine nächste Datei gefunden (Video + Audio vorhanden, ROI fehlt oder unvollständig)."
    folder = str(nxt.get("folder") or "")
    json_path_str = str(nxt.get("json_path") or "")
    ok_vid = _try_load_video_for_capture_folder_with_fallback(folder)
    if not ok_vid:
        return False, f"Video konnte nicht geladen werden: {folder}"
    st.session_state.capture_folder = folder
    if json_path_str:
        try:
            doc = json.loads(Path(json_path_str).read_text(encoding="utf-8", errors="ignore"))
            load_json_config(doc)
        except Exception:
            pass
    st.session_state.tab_default = "ROI Setup"
    st.session_state.roi_scroll_top_once = False
    st.session_state.roi_saved_once = False
    set_status(f"Nächste Datei geladen: {folder}", "ok")
    return True, folder

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

def _recordresult_json_to_cfg(doc: dict, vid_duration: float = 0.0) -> dict:
    """Convert results-sidecar JSON (recordResult-based) to UI config."""
    rr = (doc or {}).get("recordResult") if isinstance(doc, dict) else {}
    if not isinstance(rr, dict):
        return {"rois": [], "t_start": 0.0, "t_end": float(vid_duration)}
    ocr = rr.get("ocr") or {}
    if not isinstance(ocr, dict):
        ocr = {}
    params = ocr.get("params") or {}
    if not isinstance(params, dict):
        params = {}
    def _to_float(v, default):
        try:
            return float(v)
        except Exception:
            return float(default)

    out = {"rois": [], "t_start": float(0.0), "t_end": float(vid_duration)}
    out["t_start"] = _to_float(
        params.get("start_s", params.get("t_start", params.get("start_time", 0.0))),
        0.0,
    )
    out["t_end"] = _to_float(
        params.get("end_s", params.get("t_end", params.get("end_time", vid_duration))),
        vid_duration,
    )
    def _table_rows(tbl) -> list[dict]:
        if isinstance(tbl, list):
            return [r for r in tbl if isinstance(r, dict)]
        if isinstance(tbl, dict):
            cols = {str(k): v for k, v in tbl.items() if isinstance(v, list)}
            if not cols:
                return []
            n = max(len(v) for v in cols.values())
            rows = []
            for i in range(n):
                row = {}
                for k, vv in cols.items():
                    row[k] = vv[i] if i < len(vv) else None
                rows.append(row)
            return rows
        return []

    roi_table = ocr.get("roi_table")
    for row in _table_rows(roi_table):
        if not isinstance(row, dict):
            continue
        rv = _parse_roi_value(row.get("roi"))
        rv = list(rv or [])
        if len(rv) < 4:
            continue
        out["rois"].append(
            {
                "name": str(row.get("name_roi") or row.get("name") or "_"),
                "x": float(rv[0]),
                "y": float(rv[1]),
                "w": float(rv[2]),
                "h": float(rv[3]),
                "fmt": str(row.get("fmt") or "any"),
                "pattern": str(row.get("pattern") or ""),
                "max_scale": float(row.get("max_scale", 1.2) or 1.2),
            }
        )
    trk = ocr.get("trkCalSlim") or {}
    if isinstance(trk, dict):
        ref_pts = trk.get("ref_pts")
        if not isinstance(ref_pts, list):
            ref_pts = _pts_from_mat_value(trk.get("ptsRef"))
        if isinstance(ref_pts, list) and ref_pts:
            out["ref_track_pts"] = ref_pts
        mini_pts = trk.get("minimap_pts")
        if not isinstance(mini_pts, list):
            mini_pts = _pts_from_mat_value(trk.get("ptsMini"))
        if isinstance(mini_pts, list) and mini_pts:
            out["minimap_pts"] = mini_pts
        if isinstance(trk.get("moving_pt_color_range"), dict):
            out["moving_pt_color_range"] = trk.get("moving_pt_color_range")
        else:
            cr = _marker_to_color_range(trk.get("marker"))
            if isinstance(cr, dict) and cr:
                out["moving_pt_color_range"] = cr
        track_roi = _parse_roi_value(trk.get("roi"))
        if track_roi:
            out["track_roi"] = track_roi
    ac = rr.get("audio_config")
    if isinstance(ac, dict) and ac:
        out["audio_config"] = ac
    else:
        arpm = rr.get("audio_rpm") if isinstance(rr.get("audio_rpm"), dict) else {}
        ap = arpm.get("params") if isinstance(arpm.get("params"), dict) else {}
        if ap:
            mapped = {
                "nfft": ap.get("nfft"),
                "overlap_pct": ap.get("overlap_pct", ap.get("ovPerc")),
                "fmax": ap.get("fmax"),
                "order": ap.get("order"),
                "r_dyn_m": ap.get("r_dyn"),
                "tol_pct": ap.get("tol_pct"),
                "axle_ratio": ap.get("i_axle"),
                "gear_ratios": ap.get("gears"),
                "prefer_low": ap.get("prefer_low"),
                "use_ocr_v": ap.get("use_v"),
            }
            audio_offset = params.get("audio_offset_s")
            if audio_offset is not None:
                mapped["audio_offset_s"] = audio_offset
            out["audio_config"] = {k: v for k, v in mapped.items() if v is not None}
    return out


def _load_mat_from_r2(remote_key, preloaded_doc: dict | None = None):
    """JSON-only loader for MAT-selection entries (no MAT read)."""
    _reset_track_analysis_state()
    doc = preloaded_doc if isinstance(preloaded_doc, dict) else _r2_download_json_doc(_r2_json_sidecar_key(remote_key))
    if not isinstance(doc, dict) or not isinstance(doc.get("recordResult"), dict):
        set_status("JSON-Sidecar fehlt oder ist ungueltig (recordResult).", "warn")
        return None
    try:
        cfg = _recordresult_json_to_cfg(doc, vid_duration=st.session_state.vid_duration)
        st.session_state.t_start = cfg.get("t_start", st.session_state.t_start)
        st.session_state.t_end = cfg.get("t_end", st.session_state.t_end)
        st.session_state.t_current = float(st.session_state.t_start)
        st.session_state.rois = _sanitize_rois(cfg.get("rois", st.session_state.rois))
        st.session_state.selected_roi = None
        st.session_state.roi_draw_armed = False
        st.session_state.drag_roi = {}
        st.session_state.roi_wait_user_move = False
        st.session_state.roi_anchor_box = {}
        st.session_state.roi_reject_anchor_events = 0
        st.session_state.roi_editor_df = None
        if cfg.get("ref_track_pts"):
            st.session_state.ref_track_pts = cfg["ref_track_pts"]
        if cfg.get("minimap_pts"):
            st.session_state.minimap_pts = cfg["minimap_pts"]
            st.session_state.minimap_next_pt_idx = len(st.session_state.minimap_pts or [])
        if cfg.get("moving_pt_color_range"):
            st.session_state.moving_pt_color_range = cfg["moving_pt_color_range"]
        if cfg.get("track_roi"):
            _upsert_track_minimap_roi_from_mat(cfg["track_roi"])
        rr = doc.get("recordResult") or {}
        meta = rr.get("metadata") or {}
        ocr = rr.get("ocr") or {}
        trk = ocr.get("trkCalSlim") if isinstance(ocr, dict) else {}
        for _title_key in ("video_title", "youtube_title", "title", "vehicle_title", "name"):
            _title_txt = str(meta.get(_title_key, "") or "").strip() if isinstance(meta, dict) else ""
            if _title_txt:
                st.session_state["audio_vehicle_title"] = _title_txt
                if isinstance(st.session_state.get("mat_selected_summary"), dict):
                    st.session_state.mat_selected_summary[_title_key] = _title_txt
                break
        if isinstance(trk, dict):
            track_roi = _parse_roi_value(trk.get("roi"))
            if track_roi:
                _upsert_track_minimap_roi_from_mat(track_roi)
            mini_pts = trk.get("minimap_pts")
            if not isinstance(mini_pts, list):
                mini_pts = _pts_from_mat_value(trk.get("ptsMini"))
            if isinstance(mini_pts, list) and mini_pts:
                st.session_state.minimap_pts = mini_pts
                st.session_state.minimap_next_pt_idx = len(st.session_state.minimap_pts or [])
            mcr = trk.get("moving_pt_color_range") if isinstance(trk.get("moving_pt_color_range"), dict) else _marker_to_color_range(trk.get("marker"))
            if isinstance(mcr, dict) and mcr:
                st.session_state.moving_pt_color_range = mcr
        _track_name = ""
        if isinstance(ocr, dict):
            trk_name = ocr.get("track")
            if isinstance(trk_name, dict):
                for field in ("name", "track_name", "label", "track"):
                    txt = str(trk_name.get(field, "") or "").strip()
                    if txt:
                        _track_name = txt
                        break
        if _track_name:
            st.session_state["loaded_track_name"] = _track_name
            _try_auto_load_reference_track_for_name(_track_name)
        try:
            _ac_dict = cfg.get("audio_config") if isinstance(cfg.get("audio_config"), dict) else {}
            if _ac_dict:
                _apply_audio_config_to_widgets(_ac_dict)
        except Exception:
            pass
        set_status("JSON geladen OK", "ok")
        return ""
    except Exception as e:
        set_status(f"JSON-Parse: {e}", "warn")
    return None

def _apply_centerline_to_session(mat_path: str, mat_name: str) -> None:
    """Parse .mat â†’ centerline â†’ render image + auto-set fixed ref points."""
    try:
        cl = load_centerline_from_mat(mat_path)
    except Exception as e:
        set_status(f"Centerline-Fehler: {e}", "warn")
        return
    fixed = guess_fixed_points(mat_name)
    img, fp_px, cl_px = render_centerline_image(cl, fixed_pts=fixed, size_px=800)
    st.session_state.centerline = cl.tolist()
    st.session_state.centerline_px = cl_px
    st.session_state.ref_track_mat_name = mat_name
    st.session_state.ref_track_img = img
    if fp_px is not None:
        st.session_state.ref_track_pts = fp_px
    set_status(f"Centerline geladen: {mat_name} ({len(cl)} Punkte)", "ok")


def _autosave_slim_centerline_to_r2() -> None:
    if not (st.session_state.centerline is not None and st.session_state.r2_connected and st.session_state.r2_client is not None):
        return
    _base = Path(st.session_state.ref_track_mat_name or "track").stem
    _slim_name = (_base if _base.lower().endswith("_slim") else _base + "_slim") + ".mat"
    _pfx = st.session_state.r2_prefix.strip("/")
    _ref_dir = (_pfx + "/reference_track_siesmann").strip("/") if _pfx else "reference_track_siesmann"
    try:
        ok_ls, items = st.session_state.r2_client.list_files(_ref_dir)
        if ok_ls and isinstance(items, list):
            existing = [Path(str(x)).name for x in items if not str(x).endswith("/")]
            if _slim_name in existing:
                return
        _tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mat")
        _tmp.close()
        save_slim_mat(np.array(st.session_state.centerline, dtype=np.float64), _tmp.name)
        _ok, _msg = st.session_state.r2_client.upload_file(_tmp.name, f"{_ref_dir}/{_slim_name}")
        try:
            Path(_tmp.name).unlink(missing_ok=True)
        except Exception:
            pass
        if _ok:
            set_status(f"Slim automatisch gespeichert: {_slim_name}", "ok")
        else:
            set_status(f"Slim-Auto-Upload fehlgeschlagen: {_msg}", "warn")
    except Exception as e:
        set_status(f"Slim-Auto-Upload Fehler: {e}", "warn")

def _load_centerline_from_r2(remote_key: str, mat_name: str) -> None:
    client = st.session_state.r2_client
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mat")
    tmp.close()
    ok, msg = client.download_file(remote_key, tmp.name)
    if ok:
        _apply_centerline_to_session(tmp.name, mat_name)
        _autosave_slim_centerline_to_r2()
    else:
        set_status(f"Download fehlgeschlagen: {msg}", "warn")



# ==============================
# Audio / RPM helper functions
# ==============================
def _audio_load_current_capture() -> tuple[bool, str, int, np.ndarray, str]:
    """Load full-quality audio. Priority: local audio file → local video → cloud proxy."""
    folder = str(st.session_state.get("capture_folder") or "").strip("/\\")
    if not folder:
        return False, "Kein capture_folder aktiv. Bitte zuerst MAT + Video laden.", 0, np.array([], dtype=np.float32), ""

    def _read_wav_direct(path: Path) -> tuple[bool, int, np.ndarray]:
        fs, data = wavfile.read(str(path))
        y = data.astype(np.float32, copy=False)
        if y.ndim > 1:
            y = np.mean(y, axis=1)
        if np.issubdtype(data.dtype, np.integer):
            y = y / max(1.0, float(np.iinfo(data.dtype).max))
        return True, int(fs), np.asarray(y, dtype=np.float32).reshape(-1).copy()

    def _read_via_ffmpeg(path: Path, label: str):
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        tmp.close()
        tmp_path = Path(tmp.name)
        try:
            ok, build_msg = _build_audio_proxy_wav(path, tmp_path)
            if not ok:
                return False, f"{label} konnte nicht vorbereitet werden: {build_msg}", 0, np.array([], dtype=np.float32), ""
            _, fs, y = _read_wav_direct(tmp_path)
            return True, "", fs, y, f"local-ffmpeg:{path.name}"
        except Exception as e:
            return False, f"{label} konnte nicht gelesen werden: {e}", 0, np.array([], dtype=np.float32), ""
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass

    # 1. Local full audio file (WAV: read directly; other formats: via ffmpeg)
    fp_audio = _find_local_audio_file(folder)
    if fp_audio is not None:
        try:
            if fp_audio.suffix.lower() == ".wav":
                _, fs, y = _read_wav_direct(fp_audio)
                return True, "", fs, y, f"local-audio:{fp_audio.name}"
        except Exception:
            pass
        result = _read_via_ffmpeg(fp_audio, "Lokale Audiodatei")
        if result[0]:
            return result[0], result[1], result[2], result[3], f"local-audio:{fp_audio.name}"

    # 2. Local full-fps video (extract audio track via ffmpeg)
    fp_video = _find_local_fullfps_video(folder)
    if fp_video is not None:
        result = _read_via_ffmpeg(fp_video, "Lokales Vollvideo")
        if result[0]:
            return result[0], result[1], result[2], result[3], f"local-video:{fp_video.name}"

    # 3. Cloud proxy as last resort
    if st.session_state.get("r2_connected") and st.session_state.get("r2_client") is not None:
        pfx = st.session_state.r2_prefix.strip("/")
        key = f"{pfx}/captures/{folder}/{AUDIO_PROXY_NAME}" if pfx else f"captures/{folder}/{AUDIO_PROXY_NAME}"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        tmp.close()
        ok, msg = st.session_state.r2_client.download_file(key, tmp.name)
        if ok:
            try:
                _, fs, y = _read_wav_direct(Path(tmp.name))
                return True, "", fs, y, f"cloud-proxy:{AUDIO_PROXY_NAME}"
            except Exception as e:
                return False, f"Cloud-Audio konnte nicht gelesen werden: {e}", 0, np.array([], dtype=np.float32), ""
            finally:
                try:
                    Path(tmp.name).unlink(missing_ok=True)
                except Exception:
                    pass

    return False, "Kein Audio gefunden (weder lokale Audio-/Videodatei noch Cloud-Proxy).", 0, np.array([], dtype=np.float32), ""


def _audio_candidate_cylinders(cyl: int, mode: str) -> list[int]:
    if str(mode).startswith("Fest"):
        return [max(1, int(cyl))]
    return [3, 4, 5, 6, 8, 10, 12]


def _audio_candidate_harmonics(order: int, mode: str) -> list[int]:
    if str(mode).startswith("Fest"):
        return [max(1, int(order))]
    return [1, 2, 3]


def _audio_candidate_nfft_overlap(nfft: int, overlap_pct: float, mode: str, fs: int, seg_len: int) -> list[tuple[int, float]]:
    """Return STFT grid. Auto mode now really tests low/high NFFT and low/high overlap."""
    nfft = int(max(64, nfft))
    overlap_pct = float(max(0.0, min(98.0, overlap_pct)))
    seg_len = int(max(64, seg_len))
    if str(mode).startswith("Fest"):
        return [(min(nfft, seg_len), overlap_pct)]

    # Auto Schnell: grobe, sinnvolle Abdeckung. Auto Breit: alter grosser Suchraum.
    if "Schnell" in str(mode):
        base = [256, 512, 1024, 2048, 4096, 8192]
        quick_ovs = [0.0, 25.0, 50.0, 75.0]
    else:
        base = [64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384]
        quick_ovs = None
    vals = sorted({int(v) for v in base + [nfft] if 64 <= int(v) <= seg_len})
    if not vals:
        vals = [min(512, seg_len)]

    ovs = sorted(set((quick_ovs or [0.0, 5.0, 10.0, 25.0, 50.0, 75.0, 87.5, 90.0]) + [overlap_pct]))
    combos = []
    max_cells = 2_800_000
    for nf in vals:
        for ov in ovs:
            hop = max(1, int(round(nf * (1.0 - ov / 100.0))))
            nt = max(1, int(np.ceil(max(1, seg_len - nf) / hop)) + 1)
            bins = nf // 2 + 1
            if nt * bins <= max_cells:
                combos.append((int(nf), float(ov)))

    if len(combos) > 40:
        keep = []
        for nf in vals:
            for ov in ovs:
                if (nf, ov) in combos and (ov in (0.0, 10.0, 50.0, 75.0, 90.0) or nf in (64, 256, 1024, 4096, 16384)):
                    keep.append((nf, ov))
        combos = keep[:40] or combos[:40]
    return combos or [(min(nfft, seg_len), overlap_pct)]


def _audio_line_score(line, freqs, score, flo, fhi):
    line = np.asarray(line, dtype=float).copy()
    if line.size == 0:
        return -1e12
    vals = np.array([np.interp(ff, freqs, score[:, i], left=np.nan, right=np.nan) if np.isfinite(ff) and i < score.shape[1] else np.nan for i, ff in enumerate(line)], dtype=float)
    finite = np.isfinite(vals) & np.isfinite(line)
    width = max(1.0, float(fhi - flo))
    if not finite.any():
        return -1e12
    smooth_penalty = float(np.nanmedian(np.abs(np.diff(_audio_interp_nan(line)))) / width) if line.size > 1 else 0.0
    edge_penalty = float(np.nanmean(((line < flo + 0.03 * width) | (line > fhi - 0.03 * width)).astype(float)))
    return float(np.nanmedian(vals[finite]) + 2.5 * float(finite.mean()) - 5.0 * smooth_penalty - 3.0 * edge_penalty)


def _audio_peak_line(fb, sb):
    return np.asarray(fb[np.nanargmax(sb, axis=0)], dtype=float).copy()


def _audio_greedy_ridge_line(fb, sb, flo, fhi, smooth_win=7, max_jump_frac=0.08):
    nf, nt = sb.shape
    if nt <= 0 or nf <= 0:
        return np.array([], dtype=float)
    path = np.zeros(nt, dtype=int)
    strength = (np.nanmax(sb, axis=0) - np.nanmedian(sb, axis=0)).astype(float, copy=True)
    anchor = int(np.nanargmax(strength)) if np.isfinite(strength).any() else 0
    path[anchor] = int(np.nanargmax(sb[:, anchor]))
    df = float(np.nanmedian(np.diff(fb))) if len(fb) > 1 else 1.0
    maxjump = int(max(1, min(nf - 1, round(max(4.0, max_jump_frac * (fhi - flo)) / max(df, 1e-9)))))
    for j in range(anchor + 1, nt):
        p = path[j - 1]; lo = max(0, p - maxjump); hi = min(nf, p + maxjump + 1)
        path[j] = lo + int(np.nanargmax(sb[lo:hi, j]))
    for j in range(anchor - 1, -1, -1):
        p = path[j + 1]; lo = max(0, p - maxjump); hi = min(nf, p + maxjump + 1)
        path[j] = lo + int(np.nanargmax(sb[lo:hi, j]))
    line = np.asarray(_audio_smooth(fb[path], smooth_win), dtype=float).copy()
    line[(line < flo) | (line > fhi)] = np.nan
    return np.asarray(_audio_smooth(line, smooth_win), dtype=float).copy()


def _audio_viterbi_line(fb, sb, flo, fhi, smooth_win=5, jump_hz=25.0, penalty=1.2):
    nf, nt = sb.shape
    if nt <= 0 or nf <= 0:
        return np.array([], dtype=float)
    df = float(np.nanmedian(np.diff(fb))) if len(fb) > 1 else 1.0
    w = int(max(1, min(nf - 1, round(float(jump_hz) / max(df, 1e-9)))))
    z = np.asarray(sb, dtype=np.float32).copy()
    z = z - np.nanmedian(z, axis=0, keepdims=True)
    dp = np.full((nf, nt), -1e9, dtype=np.float32)
    prev = np.zeros((nf, nt), dtype=np.int16 if nf < 32767 else np.int32)
    dp[:, 0] = z[:, 0]
    for t in range(1, nt):
        old = dp[:, t - 1]
        for i in range(nf):
            lo = max(0, i - w); hi = min(nf, i + w + 1)
            js = np.arange(lo, hi)
            trans = old[lo:hi] - penalty * (np.abs(js - i) / max(1, w))
            k = int(np.argmax(trans))
            dp[i, t] = z[i, t] + trans[k]
            prev[i, t] = lo + k
    path = np.zeros(nt, dtype=int)
    path[-1] = int(np.argmax(dp[:, -1]))
    for t in range(nt - 1, 0, -1):
        path[t - 1] = int(prev[path[t], t])
    line = np.asarray(_audio_smooth(fb[path], smooth_win), dtype=float).copy()
    line[(line < flo) | (line > fhi)] = np.nan
    return line


def _audio_autocorr_line(seg, fs, nfft_eff, noverlap, nt, flo, fhi, max_frames=700):
    out = np.full(nt, np.nan, dtype=float)
    lag_min = int(max(2, np.floor(fs / max(fhi, 1))))
    lag_max = int(min(nfft_eff - 2, np.ceil(fs / max(flo, 1))))
    if lag_max <= lag_min + 2:
        return out
    stride = max(1, int(np.ceil(nt / max_frames)))
    hop = max(1, nfft_eff - noverlap)
    win = np.hanning(nfft_eff).astype(np.float32)
    for ti in range(0, nt, stride):
        stt = int(ti * hop)
        fr = np.asarray(seg[stt:stt + nfft_eff], dtype=np.float32).copy()
        if fr.size < nfft_eff:
            continue
        fr = ((fr - np.mean(fr)) * win).astype(np.float32, copy=False)
        ac = np.correlate(fr, fr, mode='full')[nfft_eff - 1:]
        ac0 = float(ac[0]) if ac.size else 0.0
        if ac0 <= 1e-9:
            continue
        part = np.asarray(ac[lag_min:lag_max + 1] / ac0, dtype=float).copy()
        peaks, props = signal.find_peaks(part, prominence=0.02)
        pk_i = int(peaks[np.argmax(props.get('prominences', np.ones_like(peaks)))]) if len(peaks) else int(np.argmax(part))
        out[ti] = fs / float(lag_min + pk_i)
    if np.isfinite(out).sum() >= 2:
        x = np.arange(nt); m = np.isfinite(out)
        out = np.interp(x, x[m], out[m]).astype(float, copy=True)
    line = np.asarray(_audio_smooth(out, 9), dtype=float).copy()
    line[(line < flo) | (line > fhi)] = np.nan
    return line


def _audio_cepstrum_line(seg, fs, nfft_eff, noverlap, nt, flo, fhi, max_frames=700):
    out = np.full(nt, np.nan, dtype=float)
    q_min = 1.0 / max(fhi, 1.0)
    q_max = 1.0 / max(flo, 1.0)
    qi0 = int(max(1, np.floor(q_min * fs)))
    qi1 = int(min(nfft_eff // 2, np.ceil(q_max * fs)))
    if qi1 <= qi0 + 2:
        return out
    stride = max(1, int(np.ceil(nt / max_frames)))
    hop = max(1, nfft_eff - noverlap)
    win = np.hanning(nfft_eff).astype(np.float32)
    for ti in range(0, nt, stride):
        stt = int(ti * hop)
        fr = np.asarray(seg[stt:stt + nfft_eff], dtype=np.float32).copy()
        if fr.size < nfft_eff:
            continue
        fr = ((fr - np.mean(fr)) * win).astype(np.float32, copy=False)
        spec = np.abs(np.fft.rfft(fr, n=nfft_eff))
        cep = np.abs(np.fft.irfft(np.log(np.maximum(spec, 1e-12)), n=nfft_eff))
        part = cep[qi0:qi1 + 1]
        if part.size:
            out[ti] = fs / float(int(np.argmax(part)) + qi0)
    if np.isfinite(out).sum() >= 2:
        x = np.arange(nt); m = np.isfinite(out)
        out = np.interp(x, x[m], out[m]).astype(float, copy=True)
    line = np.asarray(_audio_smooth(out, 9), dtype=float).copy()
    line[(line < flo) | (line > fhi)] = np.nan
    return line


def _audio_harmonic_comb_line(freqs, score, flo, fhi, harmonics=4):
    freqs = np.asarray(freqs, dtype=float)
    nt = score.shape[1]
    cand = freqs[(freqs >= flo) & (freqs <= fhi)]
    if cand.size < 3:
        return np.full(nt, np.nan, dtype=float)
    out = np.full(nt, np.nan, dtype=float)
    for t in range(nt):
        vals = []
        for f0 in cand:
            sc = 0.0; n = 0
            for k in range(1, int(max(1, harmonics)) + 1):
                fk = f0 * k
                if fk > freqs[-1]:
                    break
                v = float(np.interp(fk, freqs, score[:, t], left=np.nan, right=np.nan))
                if np.isfinite(v):
                    sc += v / np.sqrt(k); n += 1
            vals.append(sc / max(1, n))
        out[t] = cand[int(np.nanargmax(vals))]
    return np.asarray(_audio_smooth(out, 9), dtype=float).copy()


def _audio_cwt_like_line(seg, fs, t_video, flo, fhi):
    nt = len(t_video)
    if nt <= 0:
        return np.array([], dtype=float)
    freqs_grid = np.linspace(flo, fhi, max(16, min(96, int((fhi - flo) / 4))))
    env = np.zeros((len(freqs_grid), nt), dtype=np.float32)
    full_t = np.arange(len(seg), dtype=float) / float(fs)
    rel_t = np.asarray(t_video, dtype=float) - float(t_video[0])
    for i, fc in enumerate(freqs_grid):
        bw = max(8.0, fc * 0.08)
        lo = max(1.0, fc - bw / 2) / (fs / 2)
        hi = min(fs / 2 * 0.98, fc + bw / 2) / (fs / 2)
        if hi <= lo:
            continue
        try:
            b, a = signal.butter(2, [lo, hi], btype='band')
            yb = signal.filtfilt(b, a, seg).astype(np.float32)
            e = np.abs(signal.hilbert(yb)).astype(np.float32)
            env[i, :] = np.interp(rel_t, full_t, e, left=np.nan, right=np.nan)
        except Exception:
            continue
    idx = np.nanargmax(env, axis=0)
    return np.asarray(_audio_smooth(freqs_grid[idx], 9), dtype=float).copy()

def _audio_pyin_line(seg, fs, nfft_eff, noverlap, nt, flo, fhi):
    """Probabilistic YIN (librosa.pyin) — works on time-domain signal directly."""
    out = np.full(nt, np.nan, dtype=float)
    try:
        import librosa  # type: ignore
        hop = max(1, nfft_eff - noverlap)
        f0, _voiced, voiced_probs = librosa.pyin(
            seg.astype(np.float64),
            fmin=float(max(20.0, flo * 0.8)),
            fmax=float(min(fs / 2.0, fhi * 1.2)),
            sr=int(fs),
            frame_length=nfft_eff,
            hop_length=hop,
            fill_na=np.nan,
        )
        t_p = np.arange(len(f0)) * hop / float(fs)
        t_s = np.arange(nt) * hop / float(fs)
        f0_i  = np.interp(t_s, t_p, f0, left=np.nan, right=np.nan)
        vp_i  = np.interp(t_s, t_p, voiced_probs.astype(float), left=0.0, right=0.0)
        mask = (vp_i > 0.4) & np.isfinite(f0_i) & (f0_i >= flo) & (f0_i <= fhi)
        out[mask] = f0_i[mask]
    except ImportError:
        pass
    except Exception:
        pass
    return out


def _audio_cqt_line(seg, fs, nfft_eff, noverlap, nt, flo, fhi):
    """CQT-based ridge: logarithmic frequency bins — better harmonic resolution at low freqs."""
    out = np.full(nt, np.nan, dtype=float)
    try:
        import librosa  # type: ignore
        hop = max(1, nfft_eff - noverlap)
        octaves = max(0.5, np.log2(max(fhi, flo + 1) / max(flo, 1.0)))
        n_bins = max(12, int(octaves * 48))
        C = np.abs(librosa.cqt(
            seg.astype(np.float32),
            sr=int(fs),
            hop_length=hop,
            fmin=float(max(1.0, flo * 0.85)),
            n_bins=n_bins,
            bins_per_octave=48,
        )).astype(np.float32)
        cqt_freqs = librosa.cqt_frequencies(n_bins, fmin=float(max(1.0, flo * 0.85)), bins_per_octave=48)
        sub = (cqt_freqs >= flo) & (cqt_freqs <= fhi)
        if sub.sum() < 3:
            return out
        C_sub = C[sub, :]
        fsub  = cqt_freqs[sub]
        # Weighted centroid per frame
        C_norm = C_sub / (C_sub.sum(axis=0, keepdims=True) + 1e-12)
        f0 = (fsub[:, None] * C_norm).sum(axis=0)
        t_c = np.arange(C_sub.shape[1]) * hop / float(fs)
        t_s = np.arange(nt) * hop / float(fs)
        f0_i = np.interp(t_s, t_c, f0)
        valid = (f0_i >= flo) & (f0_i <= fhi)
        out[valid] = f0_i[valid]
    except ImportError:
        pass
    except Exception:
        pass
    return np.asarray(_audio_smooth(out, 7), dtype=float)


def _audio_harmonic_sum_line(freqs, score, flo, fhi, n_harmonics=5):
    """
    Improved harmonic sum: for each candidate fundamental f in [flo, fhi], sum
    the spectrogram dB energy at f, 2f, 3f, ... with 1/k weighting (lower harmonics
    weighted more). More stable than the HPS product because dB space is additive.
    """
    freqs = np.asarray(freqs, dtype=float)
    nt = score.shape[1]
    cand = (freqs >= flo) & (freqs <= fhi)
    if cand.sum() < 2:
        return np.full(nt, np.nan, dtype=float)
    cfreqs = freqs[cand]
    hscores = np.zeros((len(cfreqs), nt), dtype=float)
    for ki, f in enumerate(cfreqs):
        for k in range(1, n_harmonics + 1):
            hf = k * f
            idx = int(np.argmin(np.abs(freqs - hf)))
            if abs(freqs[idx] - hf) / max(hf, 1.0) < 0.08:
                hscores[ki] += score[idx, :] / k  # 1/k weighting
    best = np.nanargmax(hscores, axis=0)
    f0 = cfreqs[best]
    return np.asarray(_audio_smooth(np.where((f0 >= flo) & (f0 <= fhi), f0, np.nan), 7), dtype=float)


def _audio_bandpass_autocorr_line(seg, fs, nfft_eff, noverlap, nt, flo, fhi):
    """Bandpass-filtered autocorrelation: narrow the signal to [flo, fhi] first,
    then autocorrelate — more robust against broadband noise than full-band autocorr."""
    try:
        nyq = fs / 2.0
        lo = max(flo * 0.85, 5.0) / nyq
        hi = min(fhi * 1.15, nyq * 0.98) / nyq
        if hi <= lo or hi >= 1.0:
            return np.full(nt, np.nan, dtype=float)
        b, a = signal.butter(3, [lo, hi], btype='band')
        seg_bp = signal.filtfilt(b, a, seg.astype(np.float64)).astype(np.float32)
        return _audio_autocorr_line(seg_bp, fs, nfft_eff, noverlap, nt, flo, fhi)
    except Exception:
        return np.full(nt, np.nan, dtype=float)


def _audio_get_vehicle_title() -> str:
    obj = st.session_state.get("mat_selected_summary")
    dataset = ""
    video_title = ""
    if isinstance(obj, dict):
        dataset = str(obj.get("capture_folder") or obj.get("mat_file") or "").strip()
        for k in ("video_title", "youtube_title", "title", "vehicle_title", "name"):
            txt = str(obj.get(k, "") or "").strip()
            if txt:
                video_title = txt
                break
    if not video_title:
        txt = str(st.session_state.get("audio_vehicle_title", "") or "").strip()
        if txt:
            video_title = txt
    mat_path = str(st.session_state.get("audio_last_mat_path") or "").strip()
    if not video_title and mat_path:
        try:
            local_summary = _summarize_record_result_mat(mat_path)
            for k in ("video_title", "youtube_title", "title", "vehicle_title", "name"):
                txt = str(local_summary.get(k, "") or "").strip()
                if txt:
                    st.session_state["audio_vehicle_title"] = txt
                    return txt
        except Exception:
            pass
    if not video_title:
        for k in ("video_name", "capture_folder"):
            txt = str(st.session_state.get(k, "") or "").strip()
            if txt:
                video_title = txt
                break
    parts = []
    if dataset:
        parts.append(dataset)
    if video_title and video_title != dataset:
        parts.append(video_title)
    if parts:
        return " · ".join(parts)
    for k in ("audio_vehicle_title", "video_name", "capture_folder"):
        txt = str(st.session_state.get(k, "") or "").strip()
        if txt:
            return txt
    return ""


def _audio_interp_nan(x):
    x = np.asarray(x, dtype=float).copy()
    if x.size == 0: return x
    m = np.isfinite(x)
    if not m.any(): return x
    if m.sum() == 1:
        x[:] = x[m][0]; return x
    idx = np.arange(x.size)
    x[~m] = np.interp(idx[~m], idx[m], x[m])
    return x


def _audio_smooth(x, win=7):
    x = _audio_interp_nan(x)
    try:
        return pd.Series(x).rolling(int(max(3, win)) | 1, center=True, min_periods=1).median().to_numpy(dtype=float).copy()
    except Exception:
        return x


def _audio_make_debug_zip(res: dict, shown_lines=None) -> bytes:
    shown_lines = shown_lines or []
    buf = io.BytesIO()
    def npb(a):
        b=io.BytesIO(); np.save(b, np.asarray(a)); return b.getvalue()
    lines = res.get("freq_lines") or {}
    t = np.asarray(res.get("t", []), dtype=np.float32)
    freqs = np.asarray(res.get("freqs", []), dtype=np.float32)
    db = np.asarray(res.get("db", []), dtype=np.float32)
    meta = dict(params=res.get("params", {}), ui=res.get("ui", {}), source=res.get("source", ""), selected_method=res.get("selected_method", ""), candidate_table=res.get("candidate_table", []))
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("metadata.json", json.dumps(meta, ensure_ascii=False, indent=2, default=str))
        try:
            z.writestr("live_debug_log.txt", "\n".join([str(x) for x in (res.get("debug_lines") or st.session_state.get("audio_debug_lines", []) or [])]).encode("utf-8"))
        except Exception:
            pass
        z.writestr("times_s.npy", npb(t)); z.writestr("frequencies_hz.npy", npb(freqs)); z.writestr("spectrogram_db.npy", npb(db)); z.writestr("rpm_selected.npy", npb(res.get("rpm", [])))
        csv = {"t_s": t.astype(float)} if t.size else {}
        for name, arr in lines.items():
            safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in str(name)).strip("._") or "line"
            aa = np.asarray(arr, dtype=np.float32)
            z.writestr(f"lines/{safe}_Hz.npy", npb(aa))
            if t.size and aa.size == t.size: csv[f"freq_{safe}_Hz"] = aa.astype(float)
        if csv: z.writestr("lines_table.csv", pd.DataFrame(csv).to_csv(index=False).encode("utf-8"))
        z.writestr("lines.json", json.dumps({str(k): np.asarray(v).tolist() for k, v in lines.items()}, ensure_ascii=False))
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            for wl in [False, True]:
                fig, ax = plt.subplots(figsize=(13, 6), dpi=140)
                if db.ndim == 2 and t.size and freqs.size:
                    stp_t=max(1, int(np.ceil(db.shape[1]/1600))); stp_f=max(1, int(np.ceil(db.shape[0]/800)))
                    ax.pcolormesh(t[::stp_t], freqs[::stp_f], db[::stp_f, ::stp_t], shading="auto")
                if wl:
                    for name in (shown_lines or list(lines.keys())):
                        a=np.asarray(lines.get(name, []), dtype=float)
                        if a.size == t.size: ax.plot(t, a, linewidth=1.1, label=str(name))
                    if ax.get_legend_handles_labels()[0]: ax.legend(fontsize=7)
                ax.set_xlabel("t [s]"); ax.set_ylabel("f [Hz]"); ax.grid(True, alpha=.25)
                fig.tight_layout(); png=io.BytesIO(); fig.savefig(png, format="png"); plt.close(fig)
                z.writestr("spectrogram_with_frequency_lines.png" if wl else "spectrogram_only.png", png.getvalue())
        except Exception as e:
            z.writestr("png_error.txt", str(e))
    buf.seek(0); return buf.getvalue()


@st.cache_resource(show_spinner=False)
def _audio_executor():
    return cf.ThreadPoolExecutor(max_workers=1, thread_name_prefix="audio_rpm")


def _video_ocr_executor():
    return cf.ThreadPoolExecutor(max_workers=1, thread_name_prefix="video_ocr_full")


@st.cache_resource(show_spinner=False)
def _audio_live_server():
    """Small localhost JSON endpoint for live audio status without Streamlit reruns."""
    state = {"jobs": {}}
    lock = threading.RLock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args, **kwargs):
            return

        def _send_json(self, payload, code=200):
            data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_GET(self):
            try:
                parsed = urlparse(self.path)
                if parsed.path == "/watchdog-log":
                    try:
                        from app_tabs.youtube_tab import _YT_WATCHDOG, _YT_WATCHDOG_LOCK
                        with _YT_WATCHDOG_LOCK:
                            logs = list(_YT_WATCHDOG.get("logs") or [])
                            current = str(_YT_WATCHDOG.get("current") or "")
                            running = bool(_YT_WATCHDOG.get("running"))
                        self._send_json({"ok": True, "logs": logs[-15:], "current": current, "running": running})
                    except Exception as e:
                        self._send_json({"ok": True, "logs": [], "current": "", "running": False})
                    return
                if parsed.path != "/audio":
                    self._send_json({"ok": False, "error": "not found"}, 404)
                    return
                q = parse_qs(parsed.query or "")
                job_id = (q.get("id") or [""])[0]
                with lock:
                    job = dict((state.get("jobs") or {}).get(job_id) or {})
                    job["log"] = list(job.get("log") or [])[-80:]
                    job["progress"] = dict(job.get("progress") or {})
                self._send_json({"ok": True, "job": job})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    host, port = sock.getsockname()
    sock.close()
    server = ThreadingHTTPServer(("127.0.0.1", int(port)), Handler)
    thread = threading.Thread(target=server.serve_forever, name="audio_live_status_http", daemon=True)
    thread.start()
    return {"state": state, "lock": lock, "port": int(port), "server": server, "thread": thread}


def _audio_live_update(job_id: str, *, log_line=None, progress=None, status=None):
    if not job_id:
        return
    try:
        live = _audio_live_server()
        state = live["state"]
        lock = live["lock"]
        with lock:
            jobs = state.setdefault("jobs", {})
            job = jobs.setdefault(job_id, {"log": [], "progress": {}, "status": "running", "updated": time.time()})
            if log_line is not None:
                job.setdefault("log", []).append(str(log_line))
                if len(job["log"]) > 300:
                    del job["log"][:-300]
            if progress is not None:
                job["progress"] = dict(progress)
            if status is not None:
                job["status"] = str(status)
            job["updated"] = time.time()
    except Exception:
        pass


def _audio_live_widget(job_id: str, height: int = 330):
    if not job_id:
        return
    try:
        live = _audio_live_server()
        port = int(live.get("port"))
    except Exception:
        return
    endpoint = f"http://127.0.0.1:{port}/audio?id={job_id}"
    html = f"""
    <div id="audio-live-root" style="font-family: JetBrains Mono, monospace; background:#0a0c10; border:1px solid #1e2535; border-radius:8px; padding:10px 12px; color:#e8eaf0;">
      <div id="audio-live-title" style="font-weight:800; font-size:12px; color:#4a90a4; margin-bottom:8px;">Audioanalyse läuft im Hintergrund</div>
      <div style="height:12px; background:#1e2535; border-radius:999px; overflow:hidden; border:1px solid #243049;">
        <div id="audio-live-bar" style="height:100%; width:0%; background:#3ddc84; border-radius:999px; transition:width .25s linear;"></div>
      </div>
      <div id="audio-live-text" style="font-size:11px; color:#b7c3d8; margin-top:6px;">Warte auf Status ...</div>
      <pre id="audio-live-log" style="white-space:pre-wrap; margin:10px 0 0 0; max-height:220px; overflow:auto; background:#07090d; border:1px solid #1e2535; border-radius:6px; padding:8px; font-size:11px; line-height:1.35; color:#d8dee9;">Noch kein Audio-Debug vorhanden.</pre>
    </div>
    <script>
    const endpoint = {json.dumps(endpoint)};
    const bar = document.getElementById('audio-live-bar');
    const text = document.getElementById('audio-live-text');
    const log = document.getElementById('audio-live-log');
    const title = document.getElementById('audio-live-title');
    let stopped = false;
    async function tick() {{
      try {{
        const r = await fetch(endpoint + '&_=' + Date.now(), {{cache:'no-store'}});
        const data = await r.json();
        const job = (data && data.job) || {{}};
        const p = job.progress || {{}};
        const done = Number(p.done || 0);
        const total = Math.max(1, Number(p.total || 1));
        const frac = Math.max(0, Math.min(1, Number(p.fraction || (done/total) || 0)));
        const pct = Math.round(frac * 100);
        const msg = String(p.text || '');
        const status = String(job.status || 'running');
        bar.style.width = pct + '%';
        if (status === 'done') {{
          title.textContent = 'Audioanalyse abgeschlossen';
          text.textContent = `Fertig: ${{done}}/${{total}} Jobs (${{pct}}%)${{msg ? ' - ' + msg : ''}}`;
          stopped = true;
        }} else if (status === 'error') {{
          title.textContent = 'Audioanalyse fehlgeschlagen';
          text.textContent = msg || 'Fehler';
          stopped = true;
        }} else {{
          title.textContent = 'Audioanalyse läuft im Hintergrund';
          text.textContent = `Audioanalyse: ${{done}}/${{total}} Jobs (${{pct}}%)${{msg ? ' - ' + msg : ''}}`;
        }}
        const lines = Array.isArray(job.log) ? job.log.slice(-60) : [];
        log.textContent = lines.length ? lines.join('\n') : 'Noch kein Audio-Debug vorhanden.';
        log.scrollTop = log.scrollHeight;
      }} catch(e) {{
        text.textContent = 'Live-Status nicht erreichbar: ' + e;
      }}
      if (!stopped) window.setTimeout(tick, 1000);
    }}
    tick();
    </script>
    """
    components.html(html, height=height)


def _audio_background_worker(y, fs, source, params, ui, shared_log=None, shared_progress=None, live_job_id=None):
    log = []
    t0 = time.perf_counter()

    def _push_log(line: str):
        log.append(line)
        _audio_live_update(live_job_id, log_line=line, status="running")
        if shared_log is not None:
            try:
                shared_log.append(line)
                if len(shared_log) > 300:
                    del shared_log[:-300]
            except Exception:
                pass

    def _set_progress(done, total, text=""):
        if shared_progress is not None:
            try:
                total = max(1, int(total))
                done = max(0, min(int(done), total))
                payload = {"done": done, "total": total, "fraction": float(done) / float(total), "text": str(text or ""), "updated": time.time(), "elapsed": time.perf_counter() - t0}
                shared_progress.update(payload)
                _audio_live_update(live_job_id, progress=payload, status="running")
            except Exception:
                pass

    def dbg(m):
        _push_log(f"[{time.perf_counter()-t0:7.2f}s] {m}")

    def progress_cb(done, total, text=""):
        _set_progress(done, total, text)

    _set_progress(0, 1, "Audioanalyse startet ...")
    res = _audio_extract_rpm_robust(
        y, fs,
        params["start_s"], params["end_s"], params["offset_s"],
        params["nfft"], params["overlap_pct"], params["fmax"],
        params["cyl"], params["takt"], params["order"],
        params["rpm_min"], params["rpm_max"], params["method"],
        params["cyl_mode"], params["harmonic_mode"], params["drive_type"],
        stft_mode=params.get("stft_mode", "Fest auswählen"),
        debug_cb=dbg,
        method_params=params.get("method_params", {}),
        progress_cb=progress_cb,
    )
    _set_progress(1, 1, "Audioanalyse fertig. Ergebnis wird uebernommen.")
    _audio_live_update(live_job_id, status="done")
    res["source"] = source
    res["ui"] = dict(ui or {})
    _push_log("Audioanalyse fertig. Ergebnis wird uebernommen.")
    res["debug_lines"] = list(log[-300:])
    return res


def _audio_extract_rpm_robust(y, fs, start_s, end_s, offset_s, nfft, overlap_pct, fmax, cyl, takt, order, rpm_min, rpm_max, method, cyl_mode, harmonic_mode, drive_type, stft_mode="Fest auswählen", debug_cb=None, method_params=None, progress_cb=None):
    def dbg(msg):
        if callable(debug_cb):
            debug_cb(msg)

    def prog(done, total, msg=""):
        if callable(progress_cb):
            try:
                progress_cb(int(done), int(max(1, total)), str(msg or ""))
            except Exception:
                pass

    mp = dict(method_params or {})
    y = np.asarray(y, dtype=np.float32).reshape(-1).copy()
    a0 = max(0, int(round((float(start_s) + float(offset_s)) * fs)))
    a1 = min(len(y), int(round((float(end_s) + float(offset_s)) * fs)))
    if a1 <= a0 + max(64, int(.1 * fs)):
        raise ValueError("Audiosegment ist leer. Start/Ende/Offset pruefen.")

    seg = np.asarray(y[a0:a1], dtype=np.float32).reshape(-1).copy()
    seg = seg - np.float32(np.nanmedian(seg))
    pk = float(np.nanmax(np.abs(seg)) or 1.0)
    seg = (seg / pk).astype(np.float32, copy=True)
    fmax = float(min(max(20.0, fmax), fs / 2))

    is_ev = "elekt" in str(drive_type).lower() or "ev" in str(drive_type).lower()
    cyls = [0] if is_ev else _audio_candidate_cylinders(cyl, cyl_mode)
    harms = _audio_candidate_harmonics(order, harmonic_mode)
    takt = max(1, int(takt)); order_base = max(.1, float(order))
    rpm_min = float(max(100, rpm_min)); rpm_max = float(max(rpm_min + 100, rpm_max))

    stft_candidates = _audio_candidate_nfft_overlap(nfft, overlap_pct, stft_mode, fs, len(seg))
    dbg(f"Audiosegment: {len(seg):,} Samples @ {fs} Hz ({len(seg)/max(fs,1):.2f} s), Zeitfenster {start_s:.2f}-{end_s:.2f} s, Offset {offset_s:.2f} s")
    dbg("STFT Kandidaten: " + ", ".join([f"NFFT {nf}/OV {ov:g}%" for nf, ov in stft_candidates]))
    total_jobs = max(1, len(stft_candidates) * max(1, len(cyls)) * max(1, len(harms)))
    done_jobs = 0
    dbg(f"Kandidatenraum: {len(stft_candidates)} STFT-Kombi(s) Ã— {len(cyls)} Zylinder/Antrieb Ã— {len(harms)} Harmonische = {total_jobs} Jobs")
    prog(0, total_jobs, "Audioanalyse vorbereitet")

    all_candidates = []
    all_method_names = ["Hybrid", "STFT Ridge", "STFT Viterbi", "Original Peak", "Autokorrelation/YIN", "Cepstrum", "Harmonic Comb/HPS", "CWT/Wavelet", "pYIN", "CQT/Constant-Q", "Harmonische Summe", "Bandpass/Autokorr"]
    comb_harmonics = int(mp.get("comb_harmonics", 4) or 4)
    viterbi_jump_hz = float(mp.get("viterbi_jump_hz", 25.0) or 25.0)
    viterbi_penalty = float(mp.get("viterbi_penalty", 1.2) or 1.2)

    for combo_idx, (nfft_req, ov_req) in enumerate(stft_candidates, 1):
        nfft_eff = int(max(64, min(int(nfft_req), len(seg))))
        ov_eff = float(max(0, min(98, ov_req)))
        noverlap = int(max(0, min(nfft_eff - 1, round(nfft_eff * ov_eff / 100))))
        dbg(f"STFT {combo_idx}/{len(stft_candidates)}: NFFT {nfft_eff} (angefragt {nfft_req}), Overlap {ov_eff:g}%")
        try:
            _stft_t0 = time.perf_counter()
            freqs, tt, mag = signal.spectrogram(seg, fs=fs, window='hann', nperseg=nfft_eff, noverlap=noverlap, nfft=nfft_eff, detrend=False, scaling='spectrum', mode='magnitude')
            dbg(f"  STFT Matrix: {len(freqs)} Frequenzbins Ã— {len(tt)} Zeitframes in {time.perf_counter()-_stft_t0:.2f}s")
        except Exception as e:
            dbg(f"STFT übersprungen ({nfft_eff}/{ov_eff:g}%): {e}")
            continue
        keep = np.asarray(freqs <= fmax, dtype=bool).copy()
        freqs2 = np.asarray(freqs[keep], dtype=np.float32).copy()
        mag2 = np.asarray(mag[keep, :], dtype=np.float32).copy()
        if freqs2.size < 4 or mag2.size == 0:
            continue
        db = (20 * np.log10(np.maximum(mag2, 1e-12))).astype(np.float32, copy=True)
        row = np.nanmedian(db, axis=1, keepdims=True).astype(np.float32, copy=False)
        col = np.nanmedian(db - row, axis=0, keepdims=True).astype(np.float32, copy=False)
        score = (db - row - col).astype(np.float32, copy=True)
        t_video = tt.astype(np.float32) + np.float32(a0 / fs - float(offset_s))

        for ci in cyls:
            eng = 1.0 if is_ev else max(.1, 2 * float(ci) / float(takt))
            for h in harms:
                conv = eng * order_base * float(h)
                flo = max(5.0, rpm_min / 60 * conv)
                fhi = min(fmax, rpm_max / 60 * conv)
                if fhi <= flo + 3:
                    continue
                pad = max(6.0, .08 * (fhi - flo))
                bm = np.asarray((freqs2 >= max(0, flo - pad)) & (freqs2 <= min(fmax, fhi + pad)), dtype=bool).copy()
                if int(bm.sum()) < 4:
                    continue
                fb = np.asarray(freqs2[bm], dtype=np.float32).copy()
                sb = np.asarray(score[bm, :], dtype=np.float32).copy()

                done_jobs += 1
                job_txt = f"Job {done_jobs}/{total_jobs}: NFFT {nfft_eff}, OV {ov_eff:g}%, {'EV' if ci == 0 else 'C'+str(ci)}, H{h}, Band {flo:.1f}-{fhi:.1f} Hz"
                dbg(job_txt)
                prog(done_jobs - 1, total_jobs, job_txt)
                _job_t0 = time.perf_counter()

                method_lines = {}
                fast_mode = bool(mp.get("fast_mode", True))
                method_s = str(method)
                # Schnelle Basismethoden: diese sind vektorisiert und reichen fuer die Vorauswahl meist aus.
                method_lines["Original Peak"] = np.asarray(_audio_smooth(_audio_peak_line(fb, sb), 5), dtype=float).copy()
                method_lines["STFT Ridge"] = _audio_greedy_ridge_line(fb, sb, flo, fhi, smooth_win=int(mp.get("ridge_smooth", 7) or 7), max_jump_frac=float(mp.get("ridge_jump_frac", 0.08) or 0.08))
                method_lines["STFT Viterbi"] = _audio_viterbi_line(fb, sb, flo, fhi, smooth_win=int(mp.get("viterbi_smooth", 5) or 5), jump_hz=viterbi_jump_hz, penalty=viterbi_penalty)
                # Teure Methoden nur berechnen, wenn sie explizit gewaehlt sind oder Genau-Modus aktiv ist.
                if (not fast_mode) or method_s == "Autokorrelation/YIN":
                    method_lines["Autokorrelation/YIN"] = _audio_autocorr_line(seg, fs, nfft_eff, noverlap, sb.shape[1], flo, fhi)
                if (not fast_mode) or method_s == "Cepstrum":
                    method_lines["Cepstrum"] = _audio_cepstrum_line(seg, fs, nfft_eff, noverlap, sb.shape[1], flo, fhi)
                if (not fast_mode) or method_s == "Harmonic Comb/HPS":
                    method_lines["Harmonic Comb/HPS"] = _audio_harmonic_comb_line(freqs2, score, flo, fhi, harmonics=comb_harmonics)
                # CWT/Wavelet ist sehr langsam; im Schnellmodus nur bei expliziter Auswahl.
                if method_s == "CWT/Wavelet" or ((not fast_mode) and bool(mp.get("always_run_cwt", False))):
                    method_lines["CWT/Wavelet"] = _audio_cwt_like_line(seg, fs, t_video, flo, fhi)
                # Neue Methoden (mittlere Genauigkeit / andere Ansätze)
                if (not fast_mode) or method_s == "pYIN":
                    method_lines["pYIN"] = _audio_pyin_line(seg, fs, nfft_eff, noverlap, sb.shape[1], flo, fhi)
                if (not fast_mode) or method_s == "CQT/Constant-Q":
                    method_lines["CQT/Constant-Q"] = _audio_cqt_line(seg, fs, nfft_eff, noverlap, sb.shape[1], flo, fhi)
                if (not fast_mode) or method_s == "Harmonische Summe":
                    method_lines["Harmonische Summe"] = _audio_harmonic_sum_line(freqs2, score, flo, fhi, n_harmonics=5)
                if (not fast_mode) or method_s == "Bandpass/Autokorr":
                    method_lines["Bandpass/Autokorr"] = _audio_bandpass_autocorr_line(seg, fs, nfft_eff, noverlap, sb.shape[1], flo, fhi)

                scores = {name: _audio_line_score(line, freqs2, score, flo, fhi) for name, line in method_lines.items()}
                valid = [(name, line) for name, line in method_lines.items() if np.isfinite(scores.get(name, np.nan)) and scores.get(name, -1e12) > -1e11]
                if valid:
                    # Hybrid = median of the best agreeing tracks, not just a renamed ridge.
                    ranked = sorted(valid, key=lambda kv: scores.get(kv[0], -1e12), reverse=True)[:4]
                    stack = np.vstack([np.asarray(v, dtype=float) for _, v in ranked])
                    hybrid = np.nanmedian(stack, axis=0)
                    method_lines["Hybrid"] = np.asarray(_audio_smooth(hybrid, int(mp.get("hybrid_smooth", 9) or 9)), dtype=float).copy()
                    scores["Hybrid"] = _audio_line_score(method_lines["Hybrid"], freqs2, score, flo, fhi) + 0.4
                else:
                    method_lines["Hybrid"] = method_lines.get("STFT Ridge", np.full(sb.shape[1], np.nan))
                    scores["Hybrid"] = scores.get("STFT Ridge", -1e12)

                best_method_dbg = max(scores.items(), key=lambda kv: kv[1])[0] if scores else "-"
                dbg(f"  fertig in {time.perf_counter()-_job_t0:.2f}s · bester Teilscore: {best_method_dbg} = {scores.get(best_method_dbg, float('nan')):.3f}")
                prog(done_jobs, total_jobs, job_txt)

                selected_for_rank = "Hybrid" if str(method) in ("Auto robust", "Hybrid") else str(method)
                rank_score = scores.get(selected_for_rank, max(scores.values() if scores else [-1e12]))
                for mname, line in method_lines.items():
                    if line is None or len(line) != sb.shape[1]:
                        continue
                    all_candidates.append(dict(method=mname, cyl=ci, harmonic=h, conv=conv, engine_factor=eng, f_lo=flo, f_hi=fhi, line=np.asarray(line, dtype=float).copy(), score=float(scores.get(mname, -1e12)), rank_score=float(rank_score if mname == selected_for_rank else scores.get(mname, -1e12)), nfft=nfft_eff, overlap_pct=ov_eff, db=db, freqs=freqs2, t=t_video, all_lines=method_lines))

    if not all_candidates:
        raise ValueError("Keine plausiblen Kandidaten gefunden. RPM/fmax/Zylinder/Harmonische/NFFT prüfen.")

    selected_method = "Hybrid" if str(method) in ("Auto robust", "Hybrid") else str(method)
    filtered = [c for c in all_candidates if c.get("method") == selected_method]
    pool = filtered or all_candidates
    pool.sort(key=lambda c: c.get('score', -1e12), reverse=True)
    best = pool[0]

    freqs = best['freqs']; db = best['db']; t_video = best['t']
    lines = {}
    for name, line in (best.get('all_lines') or {}).items():
        lines[name] = np.asarray(line, dtype=float).copy()
    for i, c in enumerate(sorted(all_candidates, key=lambda x: x.get('score', -1e12), reverse=True)[:10], 1):
        lines[f"Kandidat {i}: {c['method']} {'EV' if c['cyl']==0 else 'C'+str(c['cyl'])} H{c['harmonic']} N{c['nfft']} O{c['overlap_pct']:g}"] = c['line']

    fsel = np.asarray(best['line'], dtype=float).copy()
    rpm = np.asarray(_audio_smooth(fsel * 60 / max(best['conv'], 1e-9), 9), dtype=float).copy()
    rpm[np.asarray((rpm < rpm_min * .5) | (rpm > rpm_max * 1.5), dtype=bool).copy()] = np.nan

    table = [{"Rang": i + 1, "Methode": c['method'], "Zyl": "EV" if c['cyl'] == 0 else c['cyl'], "Harmonik": c['harmonic'], "NFFT": c['nfft'], "Overlap_%": c['overlap_pct'], "Score": round(c['score'], 3), "Band_Hz": f"{c['f_lo']:.1f}-{c['f_hi']:.1f}"} for i, c in enumerate(sorted(all_candidates, key=lambda x: x.get('score', -1e12), reverse=True)[:50])]
    dbg(f"Auswahl: {best['method']} · {'EV' if best['cyl']==0 else 'C'+str(best['cyl'])} · H{best['harmonic']} · NFFT {best['nfft']} · OV {best['overlap_pct']:g}% · Score {best['score']:.3f}")
    prog(total_jobs, total_jobs, "Audioanalyse abgeschlossen")
    return dict(fs=int(fs), t=t_video, freqs=freqs, db=db, audio_t=np.arange(a0, a1) / float(fs) - float(offset_s), audio_y=seg, freq_lines=lines, selected_method=selected_method, selected_freq=fsel, rpm=rpm, candidate_table=table, debug_lines=[], params=dict(start_s=start_s, end_s=end_s, audio_offset_s=offset_s, nfft=best['nfft'], nfft_requested=nfft, overlap_pct=best['overlap_pct'], overlap_requested=overlap_pct, stft_mode=stft_mode, fmax=fmax, cyl=best['cyl'], takt=takt, order=order_base, harmonic=best['harmonic'], drive_type=drive_type, f_search_lo=best['f_lo'], f_search_hi=best['f_hi'], conversion_factor=best['conv'], method_params=mp))


def _matlab_field_name(name: str, fallback: str = "field") -> str:
    txt = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in str(name or "")).strip("_")
    if not txt:
        txt = fallback
    if txt[0].isdigit():
        txt = "x_" + txt
    return txt[:31]  # MATLAB MAT-5 struct field names are limited to 31 chars


def _sanitize_mat_dict_keys(obj):
    """Recursively truncate all dict keys to â‰¤31 chars (MATLAB MAT-5 struct field limit).

    Also handles collision: two keys that truncate to the same 31-char prefix get
    a numeric suffix (_1, _2, â€¦) on the second and later occurrences.
    """
    if isinstance(obj, dict):
        seen: dict[str, int] = {}
        result = {}
        for k, v in obj.items():
            base = str(k)[:31]
            if base not in seen:
                seen[base] = 0
                safe_k = base
            else:
                seen[base] += 1
                sfx = f"_{seen[base]}"
                safe_k = base[: 31 - len(sfx)] + sfx
            result[safe_k] = _sanitize_mat_dict_keys(v)
        return result
    if isinstance(obj, list):
        return [_sanitize_mat_dict_keys(v) for v in obj]
    return obj


def _cellstr_column(values) -> np.ndarray:
    return np.array([str(v) for v in (values or [])], dtype=object).reshape((-1, 1))


def _struct_array_from_dicts(rows: list[dict]) -> np.ndarray:
    rows = list(rows or [])
    if not rows:
        return np.empty((0, 1), dtype=object)
    field_names = []
    for r in rows:
        for k in (r or {}).keys():
            fn = _matlab_field_name(k)
            if fn not in field_names:
                field_names.append(fn)
    arr = np.empty((len(rows), 1), dtype=[(fn, object) for fn in field_names])
    for i, r in enumerate(rows):
        vals = []
        for fn in field_names:
            src_key = next((k for k in (r or {}).keys() if _matlab_field_name(k) == fn), fn)
            v = (r or {}).get(src_key, "")
            if isinstance(v, (int, float, np.integer, np.floating)):
                vals.append(np.array([[float(v)]], dtype=float))
            else:
                vals.append(str(v))
        arr[i, 0] = tuple(vals)
    return arr


def _build_audio_rpm_struct_from_result(res: dict) -> dict:
    res = dict(res or {})
    p = dict(res.get("params") or {})
    ui = dict(res.get("ui") or {})
    t = np.asarray(res.get("t", []), dtype=float).reshape(-1)
    rpm = np.asarray(res.get("rpm", []), dtype=float).reshape(-1)
    fsel = np.asarray(res.get("selected_freq", []), dtype=float).reshape(-1)
    n = int(min(len(t), len(rpm), len(fsel))) if len(fsel) else int(min(len(t), len(rpm)))
    t = t[:n]
    rpm = rpm[:n]
    fsel = fsel[:n] if len(fsel) else np.full(n, np.nan)

    # freq_lines: 1D arrays (N,) matching MAT file convention
    freq_lines = {}
    for name, arr in (res.get("freq_lines") or {}).items():
        a = np.asarray(arr, dtype=float).reshape(-1)
        if a.size == n:
            freq_lines[_matlab_field_name(name, "line")] = a

    # params: scalars as plain float, strings as str, complex types as JSON string
    params = {}
    base_params = dict(p)
    base_params.update({"source": res.get("source", ""), "selected_method": res.get("selected_method", "")})
    for k, v in base_params.items():
        fn = _matlab_field_name(k)
        if isinstance(v, (dict, list, tuple)):
            params[fn] = json.dumps(v, ensure_ascii=False, default=str)
        elif isinstance(v, (int, float, np.integer, np.floating)):
            params[fn] = float(v)
        else:
            params[fn] = str(v)
    if ui:
        params["ui"] = {
            _matlab_field_name(k): (json.dumps(v, ensure_ascii=False, default=str) if isinstance(v, (dict, list, tuple)) else str(v))
            for k, v in ui.items()
        }

    # candidate_table: column-oriented struct (each field = array of N values)
    # Matches MATLAB table convention and the existing MAT file structure.
    rows = list(res.get("candidate_table") or [])
    if rows:
        all_keys: list[str] = []
        for r in rows:
            for k in (r or {}).keys():
                fn = _matlab_field_name(k)
                if fn not in all_keys:
                    all_keys.append(fn)
        cand_tbl: dict = {}
        for fn in all_keys:
            raw_key = next((k for k in (rows[0] or {}).keys() if _matlab_field_name(k) == fn), fn)
            vals = [(r or {}).get(raw_key, "") for r in rows]
            if all(isinstance(v, (int, float, np.integer, np.floating)) for v in vals):
                cand_tbl[fn] = np.array([float(v) for v in vals], dtype=float)
            else:
                cand_tbl[fn] = np.array([str(v) for v in vals], dtype=object)
    else:
        cand_tbl = {}

    # debug_lines: single newline-joined string (matches MAT file convention)
    dbg = res.get("debug_lines") or st.session_state.get("audio_debug_lines") or []
    debug_lines_str = "\n".join(str(x) for x in dbg) if dbg else ""

    return {
        "params": params,
        "processed": {
            "t_s": t,        # 1D (N,) float64
            "rpm": rpm,      # 1D (N,) float64
            "freq_hz": fsel, # 1D (N,) float64
            "method": str(res.get("selected_method", "")),
        },
        "freq_lines": freq_lines,
        "candidate_table": cand_tbl,
        "debug_lines": debug_lines_str,
        "created": datetime.now().isoformat(timespec="seconds"),
    }


def _loadmat_audio_save_robust(mat_path: str) -> tuple[dict | None, str]:
    """Load a MAT file for audio_rpm insertion, retrying common scipy failures."""
    try:
        return sio.loadmat(mat_path, squeeze_me=True, struct_as_record=False), ""
    except NotImplementedError:
        raise
    except Exception as first_exc:
        try:
            return sio.loadmat(
                mat_path,
                squeeze_me=True,
                struct_as_record=False,
                verify_compressed_data_integrity=False,
            ), f"Standard-Load fehlgeschlagen, Retry ohne Kompressionsintegritätsprüfung genutzt: {first_exc}"
        except NotImplementedError:
            raise
        except Exception as second_exc:
            return None, f"{first_exc}; Retry fehlgeschlagen: {second_exc}"


def _audio_title_from_summary(summary: dict) -> str:
    if not isinstance(summary, dict):
        return ""
    for key in ("video_title", "youtube_title", "title", "vehicle_title", "name"):
        txt = str(summary.get(key, "") or "").strip()
        if txt:
            return txt
    return ""


def _summary_video_link(summary: dict) -> str:
    if not isinstance(summary, dict):
        return ""
    for key in ("youtube_url", "video_url", "url", "link", "source_url"):
        txt = str(summary.get(key, "") or "").strip()
        if txt:
            return txt
    return ""


def _build_youtube_title_excel_bytes(rows: list[dict]) -> bytes:
    """Build an Excel workbook for matching MAT folders with vehicle metadata."""
    from xml.sax.saxutils import escape

    out_rows = []
    for row in rows or []:
        folder = str(row.get("mat_datei", "") or "").strip()
        remote_key = str(row.get("remote_key", "") or "").strip()
        summary = {}
        if remote_key and isinstance(st.session_state.get("mat_summary_cache"), dict):
            summary = dict(st.session_state.mat_summary_cache.get(remote_key) or {})
        if remote_key and not summary and st.session_state.get("r2_connected") and st.session_state.get("r2_client") is not None:
            try:
                summary = _get_mat_summary_from_r2(remote_key)
            except Exception:
                summary = {}
        out_rows.append({
            "youtube video title": _audio_title_from_summary(summary),
            "link": _summary_video_link(summary),
            "folder/.mat-name": folder or summary.get("capture_folder") or Path(remote_key).name,
            "remote_key": remote_key,
            "mat_file": summary.get("mat_file", Path(remote_key).name if remote_key else ""),
        })
    columns = ["youtube video title", "link", "folder/.mat-name", "remote_key", "mat_file"]
    df = pd.DataFrame(out_rows, columns=columns)
    buf = io.BytesIO()
    sheet_rows = [columns] + df.fillna("").astype(str).values.tolist()

    def _cell_ref(row_idx: int, col_idx: int) -> str:
        name = ""
        n = col_idx
        while n:
            n, rem = divmod(n - 1, 26)
            name = chr(65 + rem) + name
        return f"{name}{row_idx}"

    rows_xml = []
    for r_idx, row_vals in enumerate(sheet_rows, 1):
        cells = []
        for c_idx, val in enumerate(row_vals, 1):
            cells.append(f'<c r="{_cell_ref(r_idx, c_idx)}" t="inlineStr"><is><t>{escape(str(val))}</t></is></c>')
        rows_xml.append(f'<row r="{r_idx}">{"".join(cells)}</row>')

    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetData>' + "".join(rows_xml) + '</sheetData>'
        '</worksheet>'
    )
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="youtube_titles" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>'
    )
    workbook_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '</Relationships>'
    )
    content_types_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '</Types>'
    )
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types_xml)
        z.writestr("_rels/.rels", rels_xml)
        z.writestr("xl/workbook.xml", workbook_xml)
        z.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml)
        z.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return buf.getvalue()


def _build_audio_config_from_values(values: dict) -> dict:
    """Return the persistent Audio Config block stored in recordResult."""
    cfg = dict(values or {})
    cfg["created"] = datetime.now().isoformat(timespec="seconds")
    cfg["version"] = 1
    return cfg


_SAVE_NEEDS_CONFIRM = "NEEDS_CONFIRM"


def _extract_audio_config_from_mat(mat_path: str) -> dict:
    """Read recordResult.audio_config from a MAT file. Returns {} on any error."""
    try:
        data = sio.loadmat(mat_path, squeeze_me=True, struct_as_record=False)
        rr = _mat_scalar(data.get("recordResult"))
        if rr is None:
            return {}
        ac = _mat_obj_get(rr, "audio_config")
        if ac is None:
            return {}
        result = _mat_struct_to_plain(ac)
        return result if isinstance(result, dict) else {}
    except Exception:
        return {}


def _apply_audio_config_to_widgets(audio_config: dict) -> None:
    """Copy audio_config dict values into Streamlit session-state widget keys.

    Called after loading a MAT file so the Audio Tab widgets reflect the saved config.
    """
    def _g(key):
        v = audio_config.get(key)
        if v is None:
            return None
        if hasattr(v, "item"):  # numpy scalar
            return v.item()
        return v

    mapping = {
        "stft_mode":      ("aud_stft_mode_new", str),
        "nfft":           ("aud_nfft_new",       int),
        "overlap_pct":    ("aud_ov_new",          float),
        "fmax":           ("aud_fmax_new",        float),
        "method":         ("aud_method_new",      str),
        "drive_type":     ("aud_drive_type",      str),
        "cyl_mode":       ("aud_cyl_mode",        str),
        "harmonic_mode":  ("aud_harm_mode",       str),
        "cyl":            ("aud_cyl_new",         int),
        "order":          ("aud_order_new",       int),
        "takt":           ("aud_takt_new",        int),
        "rpm_min":        ("aud_rpm_min_new",     float),
        "rpm_max":        ("aud_rpm_max_new",     float),
        "audio_offset_s": ("aud_offset_new",      float),
        "use_ocr_v":      ("aud_use_v_new",       bool),
        "r_dyn_m":        ("aud_rdyn_new",        float),
        "tol_pct":        ("aud_tol_new",         float),
        "axle_ratio":     ("aud_axle_ratio",      float),
        "prefer_low":     ("aud_prefer_low",      bool),
    }
    for cfg_key, (ss_key, cast) in mapping.items():
        val = _g(cfg_key)
        if val is not None:
            try:
                st.session_state[ss_key] = cast(val)
            except Exception:
                pass

    # gear_ratios â†’ comma-separated text widget
    gear_ratios = audio_config.get("gear_ratios")
    if gear_ratios is not None:
        try:
            if hasattr(gear_ratios, "tolist"):
                gear_ratios = gear_ratios.tolist()
            if isinstance(gear_ratios, (list, tuple)) and gear_ratios:
                st.session_state["aud_gears_text"] = ", ".join(f"{float(g):.2f}" for g in gear_ratios)
        except Exception:
            pass

    # method_params sub-dict
    mp = audio_config.get("method_params")
    if isinstance(mp, dict):
        mp_map = {
            "ridge_smooth":    ("aud_ridge_smooth",    int),
            "viterbi_jump_hz": ("aud_viterbi_jump_hz", float),
            "viterbi_penalty": ("aud_viterbi_penalty", float),
            "viterbi_smooth":  ("aud_viterbi_smooth",  int),
            "comb_harmonics":  ("aud_comb_harmonics",  int),
            "hybrid_smooth":   ("aud_hybrid_smooth",   int),
            "always_run_cwt":  ("aud_run_cwt_all",     bool),
            "fast_mode":       ("aud_fast_mode",       bool),
        }
        for k, (ss_k, cast) in mp_map.items():
            v = mp.get(k)
            if v is not None:
                try:
                    if hasattr(v, "item"):
                        v = v.item()
                    st.session_state[ss_k] = cast(v)
                except Exception:
                    pass
        # ridge_jump_frac is stored as fraction, widget uses %
        rfrac = mp.get("ridge_jump_frac")
        if rfrac is not None:
            try:
                if hasattr(rfrac, "item"):
                    rfrac = rfrac.item()
                st.session_state["aud_ridge_jump_pct"] = float(rfrac) * 100.0
            except Exception:
                pass


def _r2_download_mat_bytes(selected_key: str) -> tuple[bytes, str]:
    """Download MAT from R2 â†’ bytes.  r2_client only accepts file paths, so a
    temp file is required. Returns (raw_bytes, ""). Returns (b"", error) on failure.
    """
    if not st.session_state.get("r2_connected") or st.session_state.get("r2_client") is None:
        return b"", "Cloud (R2) nicht verbunden."
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mat")
    tmp.close()
    try:
        ok, msg = st.session_state.r2_client.download_file(selected_key, tmp.name)
        if not ok:
            return b"", f"MAT-Download fehlgeschlagen: {msg}"
        return Path(tmp.name).read_bytes(), ""
    finally:
        try:
            Path(tmp.name).unlink(missing_ok=True)
        except Exception:
            pass



def _r2_download_json_doc(json_key: str) -> dict:
    """Download an existing JSON sidecar from R2 and return it as dict."""
    # Umsetzung von Vorschlag: Bestehende JSON-Sidecar vor dem Speichern lesen, damit andere recordResult-Bereiche erhalten bleiben.
    client = st.session_state.get("r2_client")
    if not json_key or not st.session_state.get("r2_connected") or client is None:
        return {}
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
    tmp.close()
    try:
        ok, _msg = client.download_file(json_key, tmp.name)
        if not ok:
            return {}
        raw = Path(tmp.name).read_text(encoding="utf-8", errors="ignore").strip()
        if not raw:
            return {}
        doc = json.loads(raw)
        return doc if isinstance(doc, dict) else {}
    except Exception:
        return {}
    finally:
        try:
            Path(tmp.name).unlink(missing_ok=True)
        except Exception:
            pass


def _deep_merge_missing_json(dst: dict, src: dict) -> dict:
    """Merge src into dst without overwriting existing keys or nested values."""
    # Umsetzung von Vorschlag: Zusatzfelder tief ergaenzen, ohne vorhandene JSON-Abschnitte zu veraendern.
    if not isinstance(dst, dict) or not isinstance(src, dict):
        return dst
    for k, v in src.items():
        if k not in dst or dst[k] is None:
            dst[k] = _mat_export_to_jsonable(v)
        elif isinstance(dst.get(k), dict) and isinstance(v, dict):
            _deep_merge_missing_json(dst[k], v)
    return dst


def _load_json_doc_from_bytes(raw: bytes) -> dict:
    """Best-effort parse of generated JSON bytes."""
    if not raw:
        return {}
    try:
        doc = json.loads(raw.decode("utf-8", errors="ignore"))
        return doc if isinstance(doc, dict) else {}
    except Exception:
        return {}

def _rr_from_mat_bytes_matio(raw_mat_bytes: bytes) -> dict | None:
    """Load recordResult from MAT bytes using matio.

    matio handles MCOS-encoded MATLAB tables (v5 and v7.3) that scipy cannot
    parse. Returns a plain-Python recordResult dict, or None on failure.
    matio requires a file path so bytes are written to a temp file.
    """
    if not raw_mat_bytes:
        return None
    try:
        import matio as _matio
        import pandas as _pd
    except ImportError:
        return None

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mat")
    try:
        tmp.write(raw_mat_bytes)
        tmp.close()
        data = _matio.load_from_mat(tmp.name)
    except Exception:
        return None
    finally:
        try:
            Path(tmp.name).unlink(missing_ok=True)
        except Exception:
            pass

    if not isinstance(data, dict) or "recordResult" not in data:
        return None

    def _conv(obj, depth=0):
        if depth > 12:
            return None
        if isinstance(obj, _pd.DataFrame):
            return [
                {col: _conv(row[col], depth + 1) for col in obj.columns}
                for _, row in obj.iterrows()
            ]
        if isinstance(obj, np.ndarray):
            if obj.dtype.names:
                if obj.size == 0:
                    return {}
                val = obj.flat[0]
                return {f: _conv(val[i], depth + 1) for i, f in enumerate(obj.dtype.names)}
            if obj.size == 1:
                return _conv(obj.flat[0], depth + 1)
            if obj.dtype.kind in ("U", "S"):
                return str(obj.flat[0]) if obj.size > 0 else ""
            return obj.tolist()
        if isinstance(obj, tuple):
            if len(obj) == 1:
                return _conv(obj[0], depth + 1)
            return [_conv(v, depth + 1) for v in obj]
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            v = float(obj)
            return None if (v != v or v == float("inf") or v == float("-inf")) else v
        if isinstance(obj, bytes):
            return obj.decode("utf-8", errors="ignore")
        return obj

    def _fix_roi_rows(rows: list) -> list:
        """Normalise roi_table rows from matio: parse roi string, unwrap tuples."""
        fixed = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            name = r.get("name_roi", "")
            if isinstance(name, (list, tuple)):
                name = name[0] if name else ""
            name = str(name).strip()

            roi = r.get("roi", [])
            if isinstance(roi, str):
                try:
                    roi = [float(x) for x in roi.split()]
                except Exception:
                    roi = []
            elif not isinstance(roi, list):
                roi = []

            fmt = r.get("fmt", "any")
            if isinstance(fmt, (list, tuple)):
                fmt = fmt[0] if fmt else "any"
            fmt = str(fmt).strip() or "any"

            try:
                max_scale = float(r.get("max_scale", 1.2))
            except Exception:
                max_scale = 1.2

            fixed.append({"name_roi": name, "roi": roi, "fmt": fmt, "max_scale": max_scale})
        return fixed

    try:
        rr = _conv(data["recordResult"])
        if not isinstance(rr, dict):
            return None
        ocr = rr.get("ocr")
        if isinstance(ocr, dict):
            for field in ("roi_table", "roi_table_raw"):
                rows = ocr.get(field)
                if isinstance(rows, list) and rows and isinstance(rows[0], dict):
                    ocr[field] = _fix_roi_rows(rows)
        return rr
    except Exception:
        return None


def _mat_bytes_to_recordresult_json_bytes(raw_mat_bytes: bytes) -> bytes | None:
    """Build canonical sidecar bytes from MAT bytes.

    Tries matio first (handles MCOS MATLAB tables), falls back to scipy.
    """
    if not raw_mat_bytes:
        return None
    try:
        rr = _rr_from_mat_bytes_matio(raw_mat_bytes)
        if not isinstance(rr, dict) or not rr:
            from core.save_helpers import rr_from_mat_bytes
            rr, _extra = rr_from_mat_bytes(raw_mat_bytes)
            if not isinstance(rr, dict) or not rr:
                return None
            _fix_mcos_roi_table_v5(rr, raw_mat_bytes)
            _fix_roi_table_in_rr(rr)
        else:
            _fill_roi_from_trkCalSlim(rr.get("ocr") or {})
        payload = {"recordResult": _mat_export_to_jsonable(rr)}
        payload = _normalize_sidecar_json_payload(payload)
        return json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            default=lambda o: _mat_export_to_jsonable(o),
        ).encode("utf-8")
    except Exception:
        return None


def _normalize_sidecar_json_payload(obj):
    """Normalize sidecar JSON values to app-canonical primitives.

    Legacy MATLAB exports can contain unresolved MCOS wrappers like
    {"s0":"", "s1":"MCOS", "s2":"table|string|datetime", "arr":[...]}.
    Those placeholders are not useful in the sidecar and break downstream
    expectations, so they are converted to stable JSON primitives.
    """
    if isinstance(obj, dict):
        def _is_missing(v) -> bool:
            if v is None:
                return True
            if isinstance(v, str) and (not v.strip()):
                return True
            if isinstance(v, float):
                try:
                    return bool(np.isnan(v) or np.isinf(v))
                except Exception:
                    return False
            return False

        def _to_float(v):
            try:
                return float(v)
            except Exception:
                return None

        def _build_columnar_from_row_list(rows: list[dict]) -> dict:
            rows = [r for r in (rows or []) if isinstance(r, dict)]
            if not rows:
                return {}
            col_names: list[str] = []
            for r in rows:
                for k in r.keys():
                    name = str(k)
                    if name not in col_names:
                        col_names.append(name)
            out = {}
            for name in col_names:
                vals = [r.get(name, None) for r in rows]
                non_missing = [v for v in vals if not _is_missing(v)]
                is_num = bool(non_missing) and all(_to_float(v) is not None for v in non_missing)
                if is_num:
                    out[name] = [(_to_float(v) if not _is_missing(v) else float("nan")) for v in vals]
                else:
                    out[name] = [(None if _is_missing(v) else _mat_export_to_jsonable(v)) for v in vals]
            return out

        def _build_columnar_from_col_dict(proc_dict: dict) -> dict:
            if not isinstance(proc_dict, dict):
                return {}
            keys = [str(k) for k in proc_dict.keys()]
            if not keys:
                return {}
            max_len = 0
            as_lists: dict[str, list] = {}
            for k in keys:
                v = proc_dict.get(k, None)
                if isinstance(v, list):
                    arr = list(v)
                else:
                    arr = [v]
                as_lists[k] = arr
                max_len = max(max_len, len(arr))
            out = {}
            for k, arr in as_lists.items():
                vals = list(arr) + [None] * max(0, max_len - len(arr))
                non_missing = [v for v in vals if not _is_missing(v)]
                is_num = bool(non_missing) and all(_to_float(v) is not None for v in non_missing)
                if is_num:
                    out[k] = [(_to_float(v) if not _is_missing(v) else float("nan")) for v in vals]
                else:
                    out[k] = [(None if _is_missing(v) else _mat_export_to_jsonable(v)) for v in vals]
            return out

        def _is_row_table_list(v) -> bool:
            return isinstance(v, list) and len(v) > 0 and all(isinstance(x, dict) for x in v)

        def _normalize_table_like_fields(d: dict) -> dict:
            if not isinstance(d, dict):
                return d
            out_d = {}
            for k, v in d.items():
                if isinstance(v, dict):
                    out_d[k] = _normalize_table_like_fields(v)
                    continue
                if _is_row_table_list(v):
                    col = _build_columnar_from_row_list(v)
                    out_d[k] = _normalize_sidecar_json_payload(col)
                    continue
                out_d[k] = v
            return out_d

        keys = set(obj.keys())
        if {"s0", "s1", "s2", "arr"}.issubset(keys) and str(obj.get("s1", "")).upper() == "MCOS":
            kind = str(obj.get("s2", "")).strip().lower()
            if kind == "table":
                return []
            if kind in ("string", "datetime", "duration", "categorical"):
                return ""
            return None
        out = {str(k): _normalize_sidecar_json_payload(v) for k, v in obj.items()}
        out = _normalize_table_like_fields(out)
        rr = out.get("recordResult")
        if isinstance(rr, dict):
            arpm = rr.get("audio_rpm")
            if isinstance(arpm, dict):
                proc = arpm.get("processed")
                proc_col = arpm.get("processed_col")
                if not isinstance(proc_col, dict) or not proc_col:
                    built = {}
                    if isinstance(proc, list):
                        built = _build_columnar_from_row_list(proc)
                    elif isinstance(proc, dict):
                        built = _build_columnar_from_col_dict(proc)
                    if built:
                        built_n = _normalize_sidecar_json_payload(built)
                        arpm["processed"] = built_n
                        arpm["processed_col"] = built_n
                        rr["audio_rpm"] = arpm
                        out["recordResult"] = rr
        return out
    if isinstance(obj, list):
        return [_normalize_sidecar_json_payload(v) for v in obj]
    if isinstance(obj, float):
        try:
            if np.isnan(obj) or np.isinf(obj):
                return None
        except Exception:
            return obj
    return obj


def _build_json_sidecar_bytes_preserving_sections(
    existing_doc: dict,
    field_name: str,
    new_value: object,
    extra_rr_fields: dict | None = None,
    fallback_json_bytes: bytes | None = None,
) -> bytes:
    """Update only recordResult[field_name] in the JSON sidecar.

    If an existing sidecar is available, it is the source of truth for all
    other JSON sections. If it is missing or not in recordResult format, the
    generated MAT-derived JSON is used as fallback.
    """
    return _build_json_sidecar_bytes_preserving_fields(
        existing_doc,
        {field_name: new_value},
        extra_rr_fields=extra_rr_fields,
        fallback_json_bytes=fallback_json_bytes,
    )


def _deep_replace_json(dst: dict, src: dict) -> dict:
    """Merge src into dst and overwrite only keys present in src."""
    if not isinstance(dst, dict) or not isinstance(src, dict):
        return dst
    for k, v in src.items():
        if isinstance(dst.get(k), dict) and isinstance(v, dict):
            _deep_replace_json(dst[k], v)
        else:
            dst[k] = _mat_export_to_jsonable(v)
    return dst


def _build_json_sidecar_bytes_preserving_fields(
    existing_doc: dict,
    replace_fields: dict,
    extra_rr_fields: dict | None = None,
    fallback_json_bytes: bytes | None = None,
) -> bytes:
    """Update selected recordResult fields while preserving all other sections."""
    doc = dict(existing_doc or {}) if isinstance(existing_doc, dict) else {}
    rr = doc.get("recordResult")

    fallback_doc = _load_json_doc_from_bytes(fallback_json_bytes or b"")
    fallback_rr = fallback_doc.get("recordResult") if isinstance(fallback_doc, dict) else {}
    if not isinstance(fallback_rr, dict):
        fallback_rr = {}

    if not isinstance(rr, dict):
        if fallback_rr:
            doc = fallback_doc
            rr = doc.get("recordResult")
        else:
            doc = {}
            rr = {}
            doc["recordResult"] = rr
    elif fallback_rr:
        # Umsetzung von Vorschlag: Beschaedigte/alte Sidecars mit MAT-generierten fehlenden Bereichen auffuellen.
        _deep_merge_missing_json(rr, fallback_rr)

    for field_name, new_value in dict(replace_fields or {}).items():
        if field_name == "metadata" and isinstance(new_value, dict) and isinstance(rr.get("metadata"), dict):
            _deep_replace_json(rr["metadata"], new_value)
        else:
            rr[field_name] = _mat_export_to_jsonable(new_value)
    if extra_rr_fields:
        _deep_merge_missing_json(rr, extra_rr_fields)

    return json.dumps(
        doc,
        ensure_ascii=False,
        indent=2,
        default=lambda o: _mat_export_to_jsonable(o),
    ).encode("utf-8")


def _r2_upload_mat_json(selected_key: str, mat_bytes: bytes, json_bytes: bytes) -> tuple[bool, str]:
    """Upload JSON sidecar to R2 (JSON-only mode)."""
    client = st.session_state.get("r2_client")
    if not st.session_state.get("r2_connected") or client is None:
        return False, "Cloud (R2) nicht verbunden. Speichern nur in R2 moeglich."
    json_key = _r2_json_sidecar_key(selected_key)
    ok_json, msg_json = _upload_bytes_compat(client, json_key, json_bytes, "application/json")
    if not ok_json:
        return False, f"JSON-Upload fehlgeschlagen: {msg_json}"
    try:
        st.session_state.mat_summary_cache.pop(selected_key, None)
    except Exception:
        pass
    return True, ""

def _save_recordresult_fields_to_r2_mat(
    replace_fields: dict,
    force: bool = False,
    extra_rr_fields: dict | None = None,
    target_key: str | None = None,
    allow_missing: bool = False,
    base_record_result: dict | None = None,
) -> tuple[bool, str, bytes, bytes]:
    """Update selected recordResult fields in R2 JSON sidecar while preserving others."""

    selected_key = str(target_key or st.session_state.get("mat_selected_key") or st.session_state.get("mat_pending_selected_key") or "").strip()
    if not selected_key:
        return False, "Keine MAT-Datei in R2 ausgewaehlt. Bitte zuerst in MAT Selection eine Datei laden.", b"", b""
    if not st.session_state.get("r2_connected"):
        return False, "Cloud (R2) nicht verbunden. Speichern ist nur in R2 moeglich.", b"", b""

    json_key = _r2_json_sidecar_key(selected_key)
    existing_json_doc = _r2_download_json_doc(json_key)
    existing_json_rr = existing_json_doc.get("recordResult") if isinstance(existing_json_doc, dict) else {}
    if not isinstance(existing_json_rr, dict):
        existing_json_rr = {}
    if (not existing_json_rr) and (not allow_missing):
        return False, "JSON-Sidecar fehlt oder ist leer.", b"", b""
    if isinstance(base_record_result, dict) and base_record_result:
        _deep_merge_missing_json(existing_json_rr, base_record_result)

    if not force:
        for field_name in dict(replace_fields or {}):
            if existing_json_rr.get(field_name) is not None:
                return False, _SAVE_NEEDS_CONFIRM, b"", b""

    merged_extra = None
    if extra_rr_fields:
        merged_extra = {}
        for k, v in extra_rr_fields.items():
            if existing_json_rr.get(k) is None:
                merged_extra[k] = v

    doc = existing_json_doc if isinstance(existing_json_doc, dict) else {}
    rr = doc.get("recordResult") if isinstance(doc.get("recordResult"), dict) else {}
    rr = dict(rr)
    for k, v in dict(replace_fields or {}).items():
        rr[str(k)] = _mat_export_to_jsonable(v)
    if isinstance(merged_extra, dict):
        _deep_merge_missing_json(rr, merged_extra)
    doc["recordResult"] = rr
    json_bytes = json.dumps(
        doc,
        ensure_ascii=False,
        indent=2,
        default=lambda o: _mat_export_to_jsonable(o),
    ).encode("utf-8")
    mat_bytes = b""

    ok, msg = _r2_upload_mat_json(selected_key, mat_bytes, json_bytes)
    if not ok:
        return False, msg, mat_bytes, json_bytes
    return True, selected_key, mat_bytes, json_bytes
def _save_field_to_r2_mat(
    field_name: str,
    new_value: object,
    force: bool = False,
    extra_rr_fields: dict | None = None,
) -> tuple[bool, str]:
    """Update one recordResult field in R2 while preserving all other fields."""
    ok, result, _mat_bytes, _json_bytes = _save_recordresult_fields_to_r2_mat(
        {field_name: new_value},
        force=force,
        extra_rr_fields=extra_rr_fields,
    )
    if not ok:
        return False, result
    return True, result


def _save_audio_config_to_selected_mat(config: dict, force: bool = False) -> tuple[bool, str]:
    """Save audio_config into recordResult in R2 JSON sidecar.

    Returns (False, _SAVE_NEEDS_CONFIRM) when the field already exists and force=False.
    """
    ok, result = _save_field_to_r2_mat("audio_config", dict(config or {}), force)
    if not ok:
        return False, result
    selected_key = result
    _invalidate_and_update_mat_selection_for_capture(_current_capture_folder(), selected_key)
    st.session_state.audio_config_last_saved_key = selected_key
    return True, f"Audio Config in R2-JSON gespeichert: {selected_key}"


def _find_next_audio_config_target() -> dict | None:
    current = _current_capture_folder()
    for row in list(st.session_state.get("mat_overview_rows") or []):
        folder = str(row.get("mat_datei", "") or "").strip()
        if not folder:
            folder = _mat_capture_guess_from_key(str(row.get("remote_key", "") or ""))
        if not folder or folder == current:
            continue
        if not _overview_status_is_green(row.get("anfang_ende_ausgewaehlt")):
            continue
        if _overview_status_is_green(row.get("audio_config")):
            continue
        return {"folder": folder, "remote_key": str(row.get("remote_key", "") or "")}
    return None


def _load_next_audio_config_file() -> tuple[bool, str]:
    if not st.session_state.get("r2_connected") or st.session_state.get("r2_client") is None:
        return False, "Cloud ist nicht verbunden."
    nxt = _find_next_audio_config_target()
    if not nxt:
        return False, "Keine naechste Datei mit Start/Ende und fehlender Audio Config gefunden."
    folder = str(nxt.get("folder") or "")
    key = str(nxt.get("remote_key") or "")
    if not _try_load_video_for_capture_folder(folder):
        return False, f"Reduzierte Datei konnte nicht geladen werden: {folder}"
    st.session_state.capture_folder = str(st.session_state.get("_mat_last_video_capture_folder") or folder)
    if key:
        st.session_state.mat_selected_key = key
        st.session_state.mat_pending_selected_key = key
        try:
            _analyze_mat_from_r2(key)
        except Exception:
            pass
        mat_loaded = _load_mat_from_r2(key)
        if mat_loaded:
            st.session_state.audio_last_mat_path = mat_loaded
    st.session_state.tab_default = "Audio Auswertung"
    set_status(f"Naechste Audio-Datei geladen: {folder}", "ok")
    return True, folder


def _audio_validation_metrics(
    t_audio,
    rpm_audio,
    t_ref,
    y_ref,
    shift_s: float,
    mode: str,
    tol_abs_rpm: float | None = None,
    tol_pct: float | None = None,
    tol_logic: str = "ODER",
) -> dict:
    impl = globals().get("_audio_validation_metrics_impl")
    if callable(impl):
        try:
            return impl(t_audio, rpm_audio, t_ref, y_ref, shift_s, mode, tol_abs_rpm, tol_pct, tol_logic)
        except TypeError:
            # Backward-compatible fallback for older helper implementations.
            return impl(t_audio, rpm_audio, t_ref, y_ref, shift_s, mode)
    t_audio = np.asarray(t_audio, dtype=float).ravel()
    rpm_audio = np.asarray(rpm_audio, dtype=float).ravel()
    t_ref = np.asarray(t_ref, dtype=float).ravel() + float(shift_s)
    y_ref = np.asarray(y_ref, dtype=float).ravel()
    if t_audio.size == 0 or rpm_audio.size == 0 or t_ref.size == 0 or y_ref.size == 0:
        return {"ok": False, "error": "Leere Zeitreihe."}
    n = min(t_audio.size, rpm_audio.size)
    t_audio, rpm_audio = t_audio[:n], rpm_audio[:n]
    mask_a = np.isfinite(t_audio) & np.isfinite(rpm_audio)
    t_audio, rpm_audio = t_audio[mask_a], rpm_audio[mask_a]
    mask_r = np.isfinite(t_ref) & np.isfinite(y_ref)
    t_ref, y_ref = t_ref[mask_r], y_ref[mask_r]
    if t_audio.size < 2 or t_ref.size < 2:
        return {"ok": False, "error": "Zu wenige gueltige Punkte."}
    order = np.argsort(t_ref)
    t_ref, y_ref = t_ref[order], y_ref[order]
    lo, hi = max(float(np.min(t_audio)), float(np.min(t_ref))), min(float(np.max(t_audio)), float(np.max(t_ref)))
    keep = (t_audio >= lo) & (t_audio <= hi)
    if int(keep.sum()) < 2:
        return {"ok": False, "error": "Keine ueberlappende Zeitspanne."}
    t_audio = t_audio[keep]
    rpm_audio = rpm_audio[keep]
    y_interp = np.interp(t_audio, t_ref, y_ref)
    err = rpm_audio - y_interp
    abs_err = np.abs(err)
    denom = np.maximum(np.abs(y_interp), 1e-9)
    pct = abs_err / denom * 100.0

    tol_abs = None
    tol_pct_val = None
    try:
        if tol_abs_rpm is not None and np.isfinite(float(tol_abs_rpm)) and float(tol_abs_rpm) >= 0.0:
            tol_abs = float(tol_abs_rpm)
    except Exception:
        tol_abs = None
    try:
        if tol_pct is not None and np.isfinite(float(tol_pct)) and float(tol_pct) >= 0.0:
            tol_pct_val = float(tol_pct)
    except Exception:
        tol_pct_val = None

    if tol_abs is None:
        within_abs = np.ones(abs_err.shape, dtype=bool)
    else:
        within_abs = abs_err <= tol_abs
    if tol_pct_val is None:
        within_pct = np.ones(abs_err.shape, dtype=bool)
    else:
        within_pct = pct <= tol_pct_val

    logic_txt = str(tol_logic or "ODER").strip().upper()
    if tol_abs is not None and tol_pct_val is not None:
        if logic_txt.startswith("UND"):
            within_tol = within_abs & within_pct
            effective_logic = "UND"
        else:
            within_tol = within_abs | within_pct
            effective_logic = "ODER"
    elif tol_abs is not None:
        within_tol = within_abs
        effective_logic = "ABS"
    elif tol_pct_val is not None:
        within_tol = within_pct
        effective_logic = "PCT"
    else:
        within_tol = np.ones(abs_err.shape, dtype=bool)
        effective_logic = "AUS"

    within_cnt = int(np.count_nonzero(within_tol))
    n_points = int(t_audio.size)
    within_ratio = (100.0 * float(within_cnt) / float(max(1, n_points)))

    use_pct = "Prozent" in str(mode)
    return {
        "ok": True,
        "shift_s": float(shift_s),
        "mode": str(mode),
        "score": float(np.nanmean(pct if use_pct else abs_err)),
        "mae": float(np.nanmean(abs_err)),
        "rmse": float(np.sqrt(np.nanmean(err ** 2))),
        "median_abs": float(np.nanmedian(abs_err)),
        "mape_pct": float(np.nanmean(pct)),
        "sum_abs_err": float(np.nansum(abs_err)),
        "n": n_points,
        "tolerance_abs_rpm": tol_abs,
        "tolerance_pct": tol_pct_val,
        "tolerance_logic": effective_logic,
        "within_tolerance_count": within_cnt,
        "within_tolerance_ratio_pct": float(within_ratio),
        "outside_tolerance_count": int(max(0, n_points - within_cnt)),
    }


def _audio_find_best_validation_shift(
    t_audio,
    rpm_audio,
    t_ref,
    y_ref,
    mode: str,
    min_s: float,
    max_s: float,
    step_s: float,
    tol_abs_rpm: float | None = None,
    tol_pct: float | None = None,
    tol_logic: str = "ODER",
    progress_cb=None,
) -> tuple[dict, list[str]]:
    impl = globals().get("_audio_find_best_shift_impl")
    if callable(impl):
        try:
            return impl(
                t_audio, rpm_audio, t_ref, y_ref, mode, min_s, max_s, step_s,
                tol_abs_rpm, tol_pct, tol_logic, progress_cb,
            )
        except TypeError:
            return impl(t_audio, rpm_audio, t_ref, y_ref, mode, min_s, max_s, step_s, progress_cb)
    step = max(0.001, abs(float(step_s)))
    shifts = np.arange(float(min_s), float(max_s) + 0.5 * step, step)
    best = None
    log = []
    total = max(1, int(shifts.size))
    for i, sh in enumerate(shifts, 1):
        cur = _audio_validation_metrics(
            t_audio, rpm_audio, t_ref, y_ref, float(sh), mode,
            tol_abs_rpm=tol_abs_rpm,
            tol_pct=tol_pct,
            tol_logic=tol_logic,
        )
        if cur.get("ok") and (best is None or cur["score"] < best["score"]):
            best = cur
        if i == 1 or i == total or i % max(1, total // 20) == 0:
            msg = f"Shift {sh:.3f}s getestet ({i}/{total})"
            log.append(msg)
            if callable(progress_cb):
                progress_cb(i / total, msg)
    if best is None:
        best = {"ok": False, "error": "Kein gueltiger Shift gefunden."}
    log.append(f"Best match: shift={best.get('shift_s', float('nan')):.3f}s, score={best.get('score', float('nan')):.3f}")
    return best, log


def _save_audio_result_to_selected_mat(res: dict, force: bool = False) -> tuple[bool, str]:
    """Save audio_rpm into recordResult in R2 JSON sidecar.

    Returns (False, _SAVE_NEEDS_CONFIRM) when the field already exists and force=False.
    """
    if not isinstance(res, dict) or res.get("t") is None:
        return False, "Keine Audioanalyse-Ergebnisse zum Speichern vorhanden."

    audio_rpm_struct = _build_audio_rpm_struct_from_result(res)

    # Inject title + location into metadata only when not already set in the MAT.
    extra_rr: dict | None = None
    title_txt = _audio_title_from_summary(st.session_state.get("mat_selected_summary") or {})
    if not title_txt:
        title_txt = str(st.session_state.get("audio_vehicle_title", "") or "").strip()
    location_txt = str(st.session_state.get("audio_location", "") or "").strip()
    meta_inject: dict = {}
    if title_txt:
        meta_inject["title"] = title_txt
    if location_txt:
        meta_inject["location"] = location_txt
    if meta_inject:
        extra_rr = {"metadata": meta_inject}

    save_field = globals().get("_save_field_to_r2_mat")
    if callable(save_field):
        ok, result = save_field("audio_rpm", audio_rpm_struct, force, extra_rr)
        if not ok:
            return False, result
        return True, f"Audioanalyse in R2-JSON gespeichert: {result}"

    # Offline/local fallback for test environments.
    local_mat_path = str(st.session_state.get("audio_last_mat_path") or "").strip()
    if not local_mat_path:
        return False, "Keine MAT-Datei in R2 oder lokal verfuegbar."
    try:
        mat_data, load_note = _loadmat_audio_save_robust(local_mat_path)
        if mat_data is None:
            raise ValueError(load_note or "MAT konnte nicht gelesen werden.")
        rr = _mat_struct_to_plain(mat_data.get("recordResult", {}))
        if not isinstance(rr, dict):
            rr = {}
        extra = {k: v for k, v in mat_data.items() if not str(k).startswith("__") and k != "recordResult"}
    except Exception as e:
        rr = {}
        extra = {}
        load_note = f"MAT-Lesefallback genutzt: {e}"
    if title_txt:
        meta = rr.get("metadata", {}) if isinstance(rr.get("metadata", {}), dict) else {}
        meta.setdefault("title", title_txt)
        if location_txt:
            meta.setdefault("location", location_txt)
        rr["metadata"] = meta
    rr["audio_rpm"] = audio_rpm_struct
    out_data = dict(extra)
    out_data["recordResult"] = rr
    out_data = _sanitize_mat_dict_keys(out_data)
    sio.savemat(local_mat_path, out_data, do_compression=True)
    json_local_path = str(Path(local_mat_path).with_suffix(".json"))
    Path(json_local_path).write_bytes(
        json.dumps(_mat_export_to_jsonable(out_data), ensure_ascii=False, indent=2, default=str).encode("utf-8")
    )
    note = f" ({load_note})" if load_note else ""
    return True, f"Audioanalyse lokal gespeichert: {local_mat_path} + {Path(json_local_path).name}{note}"


def _save_audio_validation_to_selected_mat(vr: dict, force: bool = False) -> tuple[bool, str]:
    """Save audio_validation metrics into recordResult in R2 (MAT + JSON).

    Returns (False, _SAVE_NEEDS_CONFIRM) when the field already exists and force=False.
    """
    if not isinstance(vr, dict) or not vr.get("ok"):
        return False, "Keine gueltigen Validierungsergebnisse zum Speichern vorhanden."
    validation_struct = {
        "mae": float(vr.get("mae") or 0.0),
        "rmse": float(vr.get("rmse") or 0.0),
        "mape_pct": float(vr.get("mape_pct") or 0.0),
        "median_abs": float(vr.get("median_abs") or 0.0),
        "sum_abs_err": float(vr.get("sum_abs_err") or 0.0),
        "shift_s": float(vr.get("shift_s") or 0.0),
        "n": int(vr.get("n") or 0),
        "mode": str(vr.get("mode") or ""),
        "score": float(vr.get("score") or 0.0),
        "tolerance_abs_rpm": (float("nan") if vr.get("tolerance_abs_rpm") is None else float(vr.get("tolerance_abs_rpm"))),
        "tolerance_pct": (float("nan") if vr.get("tolerance_pct") is None else float(vr.get("tolerance_pct"))),
        "tolerance_logic": str(vr.get("tolerance_logic") or ""),
        "within_tolerance_count": int(vr.get("within_tolerance_count") or 0),
        "within_tolerance_ratio_pct": float(vr.get("within_tolerance_ratio_pct") or 0.0),
        "outside_tolerance_count": int(vr.get("outside_tolerance_count") or 0),
        "created": datetime.now().isoformat(timespec="seconds"),
    }
    save_field = globals().get("_save_field_to_r2_mat")
    if callable(save_field):
        ok, result = save_field("audio_validation", validation_struct, force)
        if not ok:
            return False, result
        return True, f"Validierung in R2 gespeichert: {result}"
    return False, "R2-Speicherhelper nicht verfuegbar."


_try_auto_connect_once()
_try_auto_connect_local_once()
_sync_compressed_storage_binding()

# App header
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

# Main areas. Native tabs render every tab body on each rerun so all
# components are initialized and visible from app startup.
_tab_labels = [
    "Cloud Connection & Root",
    "Medienbibliothek",
    "Watchdog",
    "ROI Setup",
    "Video OCR Full",
    "Audio Auswertung",
    "Vergleich",
    "ROI Katalog",
]
_tabs = st.tabs(_tab_labels)
_activate_tab_once()
with _tabs[0]:
    setup_tab.render(globals())
with _tabs[1]:
    media_tab.render(globals())
    # youtube_tab renders hidden: processes watchdog commands + populates globals.
    # Streamlit renders all tab contents on every rerun regardless of active tab,
    # so this runs even when the user is on a different tab.
    with st.expander("YouTube Download (erweitert)", expanded=False):
        youtube_tab.render(globals())
with _tabs[2]:
    watchdog_tab.render(globals())
with _tabs[3]:
    roi_setup_tab.render(globals())
with _tabs[4]:
    video_ocr_tab.render(globals())
with _tabs[5]:
    audio_tab.render(globals())
with _tabs[6]:
    compare_tab.render(globals())
with _tabs[7]:
    roi_catalog_tab.render(globals())

