"""
OCR Extractor – Streamlit App v3
Tab ☁  : Nextcloud-Verbindung, Hauptordner wählen, Datei-Browser
Tab 🎬  : Video laden, Start/Ende, ROI-Auswahl
Tab 🗺  : Track-Minimap Analyse – 8-Punkte + Farberkennung
"""

import streamlit as st
import cv2
import numpy as np
import json
import tempfile
import io
import scipy.io as sio
from pathlib import Path
from datetime import datetime
from PIL import Image

from webdav_client import WebDAVClient
from storage import StorageManager
from track_analysis import (
    compare_minimap_to_reference,
    detect_moving_point,
    draw_comparison_overlay,
    extract_minimap_crop,
)

# ── Seitenkonfiguration ───────────────────────────────────────────────────────
st.set_page_config(
    page_title="OCR Extractor",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Syne:wght@400;600;800&display=swap');

html, body, [class*="css"] { font-family: 'Syne', sans-serif; }
.stApp { background: #0d0f14; color: #e8eaf0; }
.block-container { padding-top: 1.1rem !important; max-width: 1500px; }

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
</style>
""", unsafe_allow_html=True)

# ── ROI / Format Listen ───────────────────────────────────────────────────────
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

# ── Session-State ──────────────────────────────────────────────────────────────
def init_state():
    # Secrets sofort laden bevor session_state initialisiert wird
    _sec_url = _sec_user = _sec_pass = ""
    try:
        _sec = st.secrets.get("webdav", {})
        _sec_url  = _sec.get("url", "")
        _sec_user = _sec.get("username", "")
        _sec_pass = _sec.get("password", "")
    except Exception:
        pass

    defs = dict(
        # WebDAV
        webdav_url=_sec_url or "https://bwsyncandshare.kit.edu/remote.php/dav/files/",
        webdav_user=_sec_user, webdav_pass=_sec_pass,
        webdav_connected=False, webdav_client=None,
        webdav_root="/",
        webdav_root_options=[],
        # Datei-Browser
        fb_path="/", fb_items=[], fb_selected=None,
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

# ── Hilfsfunktionen ───────────────────────────────────────────────────────────
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

def _file_icon(name):
    ext = Path(name).suffix.lower()
    return {".mp4":"🎬",".mov":"🎬",".avi":"🎬",".mkv":"🎬",
            ".mat":"🧮",".json":"📋",".wav":"🎵",".mp3":"🎵",
            ".png":"🖼",".jpg":"🖼",".jpeg":"🖼",
            ".txt":"📄",".md":"📄"}.get(ext,"📄")

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
    return {
        "params": {"start_s":st.session_state.t_start,"end_s":st.session_state.t_end},
        "roi_table": [
            {"name_roi":r["name"],"roi":[r["x"],r["y"],r["w"],r["h"]],
             "fmt":r["fmt"],"pattern":r.get("pattern",""),"max_scale":r.get("max_scale",1.2)}
            for r in st.session_state.rois
        ],
        "video": {"width":st.session_state.vid_width,"height":st.session_state.vid_height,
                  "fps":st.session_state.vid_fps,"duration":st.session_state.vid_duration},
        "track": {"ref_pts":st.session_state.ref_track_pts,
                  "minimap_pts":st.session_state.minimap_pts,
                  "moving_pt_color_range":st.session_state.moving_pt_color_range},
    }

def build_mat_struct(result):
    roi_table = {}
    for f in ["name_roi","roi","fmt","pattern","max_scale"]:
        key = "name" if f=="name_roi" else f
        roi_table[f] = [r.get(key,"") for r in result["roi_table"]]
    p=result["params"]; v=result["video"]; t=result.get("track",{})
    return {"recordResult":{
        "ocr":{
            "params":{"start_s":float(p["start_s"]),"end_s":float(p["end_s"]),
                      "fps":float(v["fps"]),"duration_s":float(v["duration"]),
                      "video_size_wh":np.array([v["width"],v["height"]])},
            "roi_table":roi_table,
            "trkCalSlim":{"ref_pts":np.array(t.get("ref_pts") or [],dtype=float),
                          "minimap_pts":np.array(t.get("minimap_pts") or [],dtype=float)},
            "created":str(datetime.now()),
        },
        "metadata":{"video":st.session_state.video_name}
    }}

def load_json_config(data):
    p=data.get("params",{})
    st.session_state.t_start=float(p.get("start_s",0))
    st.session_state.t_end=float(p.get("end_s",st.session_state.vid_duration))
    rois=[]
    for r in data.get("roi_table",[]):
        pos=r.get("roi",[0,0,100,50])
        rois.append(dict(name=r.get("name_roi","_"),
                         x=float(pos[0]),y=float(pos[1]),w=float(pos[2]),h=float(pos[3]),
                         fmt=r.get("fmt","any"),pattern=r.get("pattern",""),
                         max_scale=float(r.get("max_scale",1.2))))
    st.session_state.rois=rois
    t=data.get("track",{})
    if t.get("ref_pts"):     st.session_state.ref_track_pts=t["ref_pts"]
    if t.get("minimap_pts"): st.session_state.minimap_pts=t["minimap_pts"]
    if t.get("moving_pt_color_range"):
        st.session_state.moving_pt_color_range=t["moving_pt_color_range"]

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

def webdav_list(path):
    """
    Listet Verzeichnis auf.
    path="" oder "/" -> Root (base_url)
    path="/captures" -> captures-Ordner
    Gibt [{"name", "path", "is_dir"}] zurueck.
    """
    if not st.session_state.webdav_connected: return []
    client = st.session_state.webdav_client
    # Fuer list_files: "/" und "" sind beide = Root
    list_path = path.strip("/")   # "" fuer Root, "captures" fuer Unterordner
    ok, items = client.list_files(list_path)
    if not ok or not isinstance(items, list): return []
    result = []
    base = path.rstrip("/")  # logischer Basispfad fuer Navigation
    for item in items:
        is_dir = item.endswith("/")
        name   = item.rstrip("/")
        if not name: continue
        full_path = (base + "/" + name) if base else ("/" + name)
        result.append({"name": name, "path": full_path, "is_dir": is_dir})
    result.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
    return result

def get_root_folders():
    """Listet Ordner fuer Hauptordner-Dropdown, 2 Ebenen tief."""
    if not st.session_state.webdav_connected: return ["/"]
    client = st.session_state.webdav_client
    # "" = Benutzer-Root (base_url)
    ok, items = client.list_files("")
    folders = ["/"]
    if ok and isinstance(items, list):
        for item in items:
            if item.endswith("/"):
                name = item.rstrip("/")
                if name:
                    folders.append("/" + name)
    # Ebene 2
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


def _load_video_from_webdav(remote_path):
    client = st.session_state.webdav_client
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=Path(remote_path).suffix)
    tmp.close()
    with st.spinner(f"Lade {Path(remote_path).name} …"):
        ok, msg = client.download_file(remote_path, tmp.name)
    if ok: _apply_video(tmp.name, Path(remote_path).name)
    else:  set_status(f"Video-Download: {msg}", "warn")

def _load_json_from_webdav(remote_path):
    client = st.session_state.webdav_client
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json"); tmp.close()
    ok, msg = client.download_file(remote_path, tmp.name)
    if ok:
        try:
            with open(tmp.name) as f: load_json_config(json.load(f))
            set_status("JSON geladen ✓", "ok")
        except Exception as e: set_status(f"JSON-Parse: {e}", "warn")
    else: set_status(f"JSON-Download: {msg}", "warn")

def _load_mat_from_webdav(remote_path):
    client = st.session_state.webdav_client
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mat"); tmp.close()
    ok, msg = client.download_file(remote_path, tmp.name)
    if not ok: set_status(f"MAT-Download: {msg}", "warn"); return
    try:
        mat = sio.loadmat(tmp.name, squeeze_me=True, struct_as_record=False)
        rr  = mat.get("recordResult")
        if rr:
            ocr = getattr(rr,"ocr",None)
            if ocr:
                prm = getattr(ocr,"params",None)
                if prm:
                    st.session_state.t_start=float(getattr(prm,"start_s",0))
                    st.session_state.t_end=float(getattr(prm,"end_s",st.session_state.vid_duration))
                roi_tbl = getattr(ocr,"roi_table",None)
                if roi_tbl:
                    names=list(np.atleast_1d(roi_tbl.name_roi))
                    rois_r=list(np.atleast_1d(roi_tbl.roi))
                    fmts=list(np.atleast_1d(roi_tbl.fmt))
                    rois=[]
                    for n,r,f in zip(names,rois_r,fmts):
                        pos=np.atleast_1d(r).astype(float)
                        if len(pos)==4:
                            rois.append(dict(name=str(n),x=pos[0],y=pos[1],
                                             w=pos[2],h=pos[3],fmt=str(f),
                                             pattern="",max_scale=1.2))
                    st.session_state.rois=rois
        set_status("MAT geladen ✓","ok")
    except Exception as e: set_status(f"MAT-Parse: {e}","warn")

def _load_ref_from_webdav(remote_path):
    client = st.session_state.webdav_client
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=Path(remote_path).suffix)
    tmp.close()
    ok, msg = client.download_file(remote_path, tmp.name)
    if ok:
        img = np.array(Image.open(tmp.name).convert("RGB"))
        st.session_state.ref_track_img=img
        set_status("Referenz-Track geladen ✓","ok")
    else: set_status(f"Ref-Download: {msg}","warn")

# ── Header + Status ───────────────────────────────────────────────────────────
st.markdown("""
<div class="app-header">
  <h1>OCR Extractor</h1>
  <span class="subtitle">Cloud · ROI · Track</span>
</div>""", unsafe_allow_html=True)

stype = st.session_state.status_type
_root_display = st.session_state.webdav_root or ""
_root_badge = (f'<span class="status-badge status-ok" style="margin-left:8px">'
               f'HAUPTORDNER: {_root_display.upper()}</span>'
               if st.session_state.webdav_connected and _root_display and _root_display != "/"
               else "")
st.markdown(
    f'<span class="status-badge status-{stype}">{st.session_state.status_msg}</span>' + _root_badge,
    unsafe_allow_html=True)

# ── TABS ──────────────────────────────────────────────────────────────────────
tab_cloud, tab_roi, tab_track = st.tabs(
    ["☁️  Cloud & Dateien", "🎬  ROI-Setup", "🗺  Track-Analyse"]
)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB ☁️  – CLOUD & DATEIEN
# ═══════════════════════════════════════════════════════════════════════════════
with tab_cloud:

    col_l, col_r = st.columns([1, 2], gap="large")

    # ── Linke Spalte ───────────────────────────────────────────────────────────
    with col_l:

        # ── Verbindung ─────────────────────────────────────────────────────────
        # --- section ---
        st.markdown('<div class="section-title">Verbindung · bwSyncAndShare / Nextcloud</div>',
                    unsafe_allow_html=True)

        # key= an session_state gebunden -> Felder sind immer befuellt
        wdav_url  = st.text_input("WebDAV URL",
                                   key="webdav_url",
                                   help="Vollstaendige URL inkl. UUID-Ordner, z.B. .../dav/files/UUID%40bwidm.../")
        wdav_user = st.text_input("Benutzername",
                                   key="webdav_user",
                                   placeholder="UUID@bwidm.scc.kit.edu")
        wdav_pass = st.text_input("App-Passwort",
                                   key="webdav_pass",
                                   type="password",
                                   help="Nextcloud: Einstellungen > Sicherheit > App-Passwoerter")

        if st.button("🔌 Verbinden", type="primary", use_container_width=True):
            if wdav_url and wdav_user and wdav_pass:
                with st.spinner("Verbinde ..."):
                    _client = WebDAVClient(wdav_url, wdav_user, wdav_pass)
                    _ok, _msg = _client.test_connection()
                if _ok:
                    # ERST client und connected setzen, DANN Ordner laden
                    st.session_state.webdav_connected = True
                    st.session_state.webdav_client    = _client
                    # Ordner direkt mit dem neuen Client laden (nicht ueber get_root_folders
                    # weil session_state update noch nicht geschrieben ist)
                    _ok_r, _items_r = _client.list_files("")
                    _opts = ["/"]
                    if _ok_r and isinstance(_items_r, list):
                        for _item in _items_r:
                            if _item.endswith("/"):
                                _n = _item.rstrip("/")
                                if _n:
                                    _opts.append("/" + _n)
                        # Ebene 2
                        for _folder in list(_opts[1:]):
                            _ok2, _sub = _client.list_files(_folder)
                            if _ok2 and isinstance(_sub, list):
                                for _s in _sub:
                                    if _s.endswith("/"):
                                        _sn = _s.rstrip("/")
                                        if _sn:
                                            _full = _folder.rstrip("/") + "/" + _sn
                                            if _full not in _opts:
                                                _opts.append(_full)
                    _opts = sorted(_opts)
                    st.session_state.webdav_root_options = _opts
                    # Wenn es nur "/" und einen weiteren Ordner gibt -> auto-select
                    _real = [o for o in _opts if o != "/"]
                    if len(_real) == 1:
                        st.session_state.webdav_root = _real[0]
                        st.session_state.fb_path  = _real[0]
                        st.session_state.fb_items = webdav_list(_real[0])
                        set_status(f"Verbunden. Hauptordner automatisch gesetzt: {_real[0]}", "ok")
                    else:
                        st.session_state.fb_path  = "/"
                        st.session_state.fb_items = webdav_list("")
                        set_status(f"Verbunden. {len(_opts)} Ordner gefunden.", "ok")
                else:
                    st.session_state.webdav_connected = False
                    set_status(f"Verbindung fehlgeschlagen: {_msg}", "warn")
                st.rerun()
            else:
                set_status("Bitte alle Felder ausfullen.", "warn"); st.rerun()

        if st.session_state.webdav_connected:
            st.markdown('<div style="display:flex;align-items:center;margin-top:.4rem;">' +
                        '<span class="conn-dot ok"></span>' +
                        '<span style="font-family:JetBrains Mono,monospace;font-size:.72rem;' +
                        'color:#3ddc84">Verbunden</span></div>', unsafe_allow_html=True)
        else:
            st.markdown('<div style="display:flex;align-items:center;margin-top:.4rem;">' +
                        '<span class="conn-dot off"></span>' +
                        '<span style="font-family:JetBrains Mono,monospace;font-size:.72rem;' +
                        'color:#4a5060">Nicht verbunden</span></div>', unsafe_allow_html=True)


        # ── Hauptordner ────────────────────────────────────────────────────────
        # --- section ---
        st.markdown('<div class="section-title">Hauptordner (Projekt-Root)</div>',
                    unsafe_allow_html=True)
        st.caption("Dieser Ordner enthaelt captures/, results/, reference_track_siesmann/ usw.")

        if st.session_state.webdav_connected:
            opts = st.session_state.webdav_root_options or ["/"]
            root_mode = st.radio("Eingabe", ["Aus Liste waehlen", "Manuell eingeben"],
                                  horizontal=True, label_visibility="collapsed",
                                  key="root_mode")

            if root_mode == "Aus Liste waehlen":
                cur = st.session_state.webdav_root
                idx = opts.index(cur) if cur in opts else 0
                # key enthaelt Anzahl Optionen -> zwingt Neurender wenn Liste sich aendert
                _dd_key = f"root_dd_{len(opts)}"
                chosen = st.selectbox("Hauptordner", opts, index=idx,
                                       label_visibility="collapsed", key=_dd_key)
                c1, c2 = st.columns(2)
                if c1.button("Uebernehmen", use_container_width=True, key="set_root_dd"):
                    st.session_state.webdav_root = chosen
                    st.session_state.fb_path     = chosen
                    st.session_state.fb_items    = webdav_list(chosen)
                    set_status(f"Hauptordner: {chosen}", "ok"); st.rerun()
                if c2.button("Liste neu", use_container_width=True, key="refresh_root"):
                    st.session_state.webdav_root_options = get_root_folders(); st.rerun()
            else:
                manual = st.text_input("Pfad", value=st.session_state.webdav_root,
                                        placeholder="/mein_projekt",
                                        label_visibility="collapsed", key="root_manual")
                if st.button("Uebernehmen", use_container_width=True, key="set_root_manual"):
                    path = (manual.rstrip("/") or "/")
                    st.session_state.webdav_root = path
                    st.session_state.fb_path     = path
                    st.session_state.fb_items    = webdav_list(path)
                    set_status(f"Hauptordner: {path}", "ok"); st.rerun()

            # Pfad-Vorschau
            root = st.session_state.webdav_root
            cf   = st.session_state.capture_folder
            _r2 = root.strip("/")
            _cap_disp = ("/" + _r2 + "/captures/") if _r2 else "/captures/"
            _res_disp = ("/" + _r2 + "/results/")  if _r2 else "/results/"
            st.markdown(f"""
            <div style="font-family:'JetBrains Mono',monospace;font-size:.64rem;
                 color:#4a5060;line-height:2.0;margin-top:.6rem;
                 border-top:1px solid #1e2535;padding-top:.5rem;">
            <span style="color:#8892a4">Root</span>&nbsp;&nbsp;&nbsp;&nbsp;{root or "/"}<br>
            <span style="color:#8892a4">captures/</span>&nbsp;{_cap_disp}<br>
            <span style="color:#8892a4">results/</span>&nbsp;&nbsp;{_res_disp}<br>
            <span style="color:#ffa040">{cf or "Aufnahme noch nicht gesetzt"}</span>
            </div>""", unsafe_allow_html=True)
        else:
            st.markdown('<div style="font-family:JetBrains Mono,monospace;font-size:.72rem;' +
                        'color:#2e3545;padding:.5rem 0;">Erst verbinden.</div>',
                        unsafe_allow_html=True)


        # ── Aufnahme-Ordner ────────────────────────────────────────────────────
        with st.container(border=True):
            st.markdown('**Aufnahme-Ordner**')
        st.caption("Format: YYYYMMDD_HHMMSS aus captures/ — bestimmt alle Datei-Pfade.")

        if st.session_state.webdav_connected and st.session_state.webdav_root:
            root     = st.session_state.webdav_root
            # cap_path relativ zum root: wenn root="/foo" -> "foo/captures"
            _cap_rel = (root.strip("/") + "/captures").strip("/")
            _ok_cap, _cap_items = st.session_state.webdav_client.list_files(_cap_rel)
            cap_folders = []
            if _ok_cap and isinstance(_cap_items, list):
                cap_folders = sorted(
                    [i.rstrip("/") for i in _cap_items if i.endswith("/") and i.rstrip("/")],
                    reverse=True)

            if cap_folders:
                cf_idx = (cap_folders.index(st.session_state.capture_folder)
                          if st.session_state.capture_folder in cap_folders else 0)
                chosen_cf = st.selectbox(
                    "Aufnahme auswahlen",
                    cap_folders,
                    index=cf_idx,
                    format_func=lambda x: f"📁 {x}",
                    label_visibility="collapsed",
                    key="cf_dd")
                if st.button("Auswahlen", use_container_width=True, key="set_cf"):
                    st.session_state.capture_folder = chosen_cf
                    nav = f"{root}/captures/{chosen_cf}".replace("//", "/")
                    st.session_state.fb_path  = nav
                    st.session_state.fb_items = webdav_list(nav)
                    set_status(f"Aufnahme: {chosen_cf}", "ok"); st.rerun()
            else:
                st.caption("Keine Unterordner in captures/ — ggf. Hauptordner setzen.")

        cf_manual = st.text_input("Oder manuell eingeben",
                                   value=st.session_state.capture_folder,
                                   placeholder="20251104_202910",
                                   label_visibility="collapsed", key="cf_manual")
        if cf_manual != st.session_state.capture_folder:
            st.session_state.capture_folder = cf_manual


        # ── Lokal laden ────────────────────────────────────────────────────────
        with st.container(border=True):
            st.markdown('**Lokal laden**')

        up_v = st.file_uploader("Video (MP4/MOV/AVI)",
                                 type=["mp4","mov","avi","mkv"],
                                 label_visibility="collapsed", key="up_v")
        if up_v and st.session_state.video_name != up_v.name:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=Path(up_v.name).suffix)
            tmp.write(up_v.read()); tmp.close()
            _apply_video(tmp.name, up_v.name)
            st.rerun()

        up_r = st.file_uploader("Referenz-Bild (PNG/JPG)",
                                 type=["png","jpg","jpeg"],
                                 label_visibility="collapsed", key="up_r")
        if up_r:
            img = np.array(Image.open(up_r).convert("RGB"))
            st.session_state.ref_track_img = img
            set_status("Referenz-Track geladen", "ok")

        up_j = st.file_uploader("Config (JSON)",
                                 type=["json"],
                                 label_visibility="collapsed", key="up_j")
        if up_j:
            try:
                load_json_config(json.load(up_j))
                set_status("JSON-Config geladen", "ok"); st.rerun()
            except Exception as e:
                set_status(f"JSON-Fehler: {e}", "warn")


    # ── Rechte Spalte: Datei-Browser ───────────────────────────────────────────
    with col_r:
        with st.container(border=True):
            st.markdown('**Datei-Browser**')

        if not st.session_state.webdav_connected:
            st.markdown('<div style="text-align:center;color:#2e3545;padding:3rem;' +
                        'font-family:JetBrains Mono,monospace;font-size:.8rem;">' +
                        'Erst verbinden und Hauptordner setzen</div>', unsafe_allow_html=True)
        else:
            cur = st.session_state.fb_path or "/"

            # Breadcrumb + Buttons
            nav1, nav2, nav3 = st.columns([4, 1, 1])
            with nav1:
                st.markdown(f'<div class="breadcrumb">📂 {cur}</div>', unsafe_allow_html=True)
            with nav2:
                if st.button("Hoch", use_container_width=True, key="fb_up"):
                    parts = cur.rstrip("/").split("/")
                    parent = "/".join(parts[:-1]) or "/"
                    st.session_state.fb_path  = parent
                    st.session_state.fb_items = webdav_list(parent)
                    st.rerun()
            with nav3:
                if st.button("Neu", use_container_width=True, key="fb_refresh", help="Aktualisieren"):
                    st.session_state.fb_items = webdav_list(cur)
                    st.rerun()

            # Schnellzugriff
            root = st.session_state.webdav_root or "/"
            cf   = st.session_state.capture_folder
            qa   = st.columns(4)
            def _p(*parts):
                """Baut logischen Pfad: _p("foo","bar") -> "/foo/bar" """
                return "/" + "/".join(p.strip("/") for p in parts if p.strip("/"))
            _r = root.strip("/")
            shortcuts = [
                ("captures/",  _p(_r, "captures")),
                ("results/",   _p(_r, "results")),
                ("reference/", _p(_r, "reference_track_siesmann")),
                (f"{cf[:8]}.." if len(cf) > 8 else (cf or "—"),
                 _p(_r, "captures", cf) if cf else None),
            ]
            for i, (label, path) in enumerate(shortcuts):
                if path:
                    if qa[i].button(label, use_container_width=True, key=f"qa_{i}"):
                        st.session_state.fb_path  = path
                        st.session_state.fb_items = webdav_list(path)
                        st.rerun()

            st.markdown("<hr>", unsafe_allow_html=True)

            # Eintraege laden
            items = st.session_state.fb_items
            if not items:
                items = webdav_list(cur)
                st.session_state.fb_items = items

            if not items:
                st.markdown('<div style="font-family:JetBrains Mono,monospace;' +
                            'font-size:.72rem;color:#2e3545;padding:1rem;">' +
                            'Leer oder kein Zugriff.</div>', unsafe_allow_html=True)
            else:
                for entry in items:
                    icon = "📁" if entry["is_dir"] else _file_icon(entry["name"])
                    c_name, c_btn = st.columns([5, 1])
                    with c_name:
                        if st.button(f"{icon}  {entry['name']}",
                                     key=f"fb_{entry['path']}",
                                     use_container_width=True):
                            if entry["is_dir"]:
                                nav_p = entry["path"].rstrip("/")
                                st.session_state.fb_path  = nav_p
                                st.session_state.fb_items = webdav_list(nav_p)
                                st.session_state.fb_selected = None
                            else:
                                st.session_state.fb_selected = entry["path"]
                            st.rerun()
                    with c_btn:
                        if not entry["is_dir"]:
                            ext = Path(entry["name"]).suffix.lower()
                            if ext in (".mp4",".mov",".avi",".mkv"):
                                if st.button("Play", key=f"act_{entry['path']}",
                                             help="Als Video laden", use_container_width=True):
                                    _load_video_from_webdav(entry["path"]); st.rerun()
                            elif ext == ".json":
                                if st.button("Laden", key=f"act_{entry['path']}",
                                             help="Als JSON-Config laden", use_container_width=True):
                                    _load_json_from_webdav(entry["path"]); st.rerun()
                            elif ext == ".mat":
                                if st.button("Laden", key=f"act_{entry['path']}",
                                             help="Als MAT-Config laden", use_container_width=True):
                                    _load_mat_from_webdav(entry["path"]); st.rerun()
                            elif ext in (".png",".jpg",".jpeg"):
                                if st.button("Ref", key=f"act_{entry['path']}",
                                             help="Als Referenz-Track laden", use_container_width=True):
                                    _load_ref_from_webdav(entry["path"]); st.rerun()


        # Ergebnis hochladen
        if st.session_state.webdav_connected and st.session_state.rois:
            # --- section ---
            st.markdown('<div class="section-title">Ergebnis hochladen (JSON + MAT)</div>',
                        unsafe_allow_html=True)
            cf   = st.session_state.capture_folder or "output"
            root = st.session_state.webdav_root
            save_name = st.text_input("Dateiname (ohne Endung)",
                                       value=f"results_{cf}",
                                       label_visibility="collapsed",
                                       key="cloud_save")
            if st.button("Hochladen", type="primary", use_container_width=True, key="cloud_up"):
                result     = build_result_json()
                result_str = json.dumps(result, indent=2, ensure_ascii=False)
                _client    = st.session_state.webdav_client
                _ok1, _m1  = _client.upload_string(
                    result_str, f"{root}/results/{save_name}.json".replace("//","/"))
                mat_buf = io.BytesIO(); sio.savemat(mat_buf, build_mat_struct(result))
                _ok2, _m2  = _client.upload_bytes(
                    mat_buf.getvalue(), f"{root}/results/{save_name}.mat".replace("//","/"))
                if _ok1 and _ok2:
                    set_status(f"Hochgeladen: results/{save_name}.*", "ok")
                    res_p = f"{root}/results".replace("//","/")
                    st.session_state.fb_path  = res_p
                    st.session_state.fb_items = webdav_list(res_p)
                else:
                    set_status(f"Upload: JSON={'OK' if _ok1 else _m1}  MAT={'OK' if _ok2 else _m2}", "warn")
                st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 🎬 – ROI-SETUP
# ═══════════════════════════════════════════════════════════════════════════════
with tab_roi:
    if not st.session_state.video_path:
        st.markdown("""
        <div style="text-align:center;padding:3rem 2rem;color:#4a5060;">
          <div style="font-size:2.5rem;margin-bottom:.8rem">🎬</div>
          <div style="font-family:'Syne',sans-serif;font-size:1rem;font-weight:600">
            Kein Video geladen</div>
          <div style="font-family:'JetBrains Mono',monospace;font-size:.72rem;
               margin-top:.4rem;color:#2e3545">
            → Tab ☁️  öffnen → Video laden oder von WebDAV laden</div>
        </div>""", unsafe_allow_html=True)
    else:
        dur=st.session_state.vid_duration; fps=st.session_state.vid_fps
        fw=st.session_state.vid_width;    fh=st.session_state.vid_height
        tot=max(1,int(dur*fps))

        col_v, col_r = st.columns([3,1], gap="medium")
        with col_v:
            with st.container(border=True):
                st.markdown('**Zeitbereich**',unsafe_allow_html=True)
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

            with st.container(border=True):
                st.markdown('**Video-Frame**',unsafe_allow_html=True)
            t_cur=st.slider("Position [s]",0.0,float(dur),float(st.session_state.t_current),
                             step=round(1/fps,4),format="%.3f s",key="sl_cur")
            st.session_state.t_current=t_cur
            frame=get_frame(st.session_state.video_path,t_cur)
            if frame is not None:
                st.image(draw_rois(frame,st.session_state.rois,
                                   st.session_state.selected_roi,fw,fh),
                         use_container_width=True,
                         caption=f"t={t_cur:.3f}s  |  {fw}×{fh}  |  {fps:.1f}fps")
            else:
                st.warning("Frame nicht verfügbar.")

            with st.container(border=True):
                st.markdown('**ROI hinzufügen**',unsafe_allow_html=True)
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
                st.info("ℹ️ Danach in Tab 🗺 Track-Analyse weiterarbeiten.")
            if st.button("➕ ROI hinzufügen",type="primary",use_container_width=True):
                st.session_state.rois.append(dict(name=roi_name,
                    x=float(rx),y=float(ry),w=float(rw),h=float(rh),
                    fmt=roi_fmt,pattern=roi_pat,max_scale=roi_sc))
                st.session_state.selected_roi=len(st.session_state.rois)-1
                get_frame.clear(); set_status(f"ROI '{roi_name}' hinzugefügt.","ok"); st.rerun()

        with col_r:
            with st.container(border=True):
                st.markdown('**ROI-Liste**',unsafe_allow_html=True)
            if not st.session_state.rois:
                st.markdown('<div style="font-family:\'JetBrains Mono\',monospace;'
                            'font-size:.72rem;color:#2e3545;text-align:center;padding:1rem;">'
                            'Keine ROIs</div>',unsafe_allow_html=True)
            for i,roi in enumerate(st.session_state.rois):
                is_track=roi["name"]=="track_minimap"; is_sel=i==st.session_state.selected_roi
                pos=f'[{int(roi["x"])},{int(roi["y"])},{int(roi["w"])},{int(roi["h"])}]'
                if st.button(("▶ " if is_sel else "")+roi["name"],
                              key=f"rsel_{i}",use_container_width=True):
                    st.session_state.selected_roi=i; st.rerun()
                tag_cls="roi-tag-track" if is_track else ("roi-tag-sel" if is_sel else "roi-tag")
                st.markdown(f'<span class="roi-tag {tag_cls}">{pos}</span> '
                            f'<span style="font-family:\'JetBrains Mono\',monospace;'
                            f'font-size:.62rem;color:#4a5060">{roi["fmt"]}</span><br>',
                            unsafe_allow_html=True)

            sel=st.session_state.selected_roi
            if sel is not None and sel<len(st.session_state.rois):
                roi=st.session_state.rois[sel]
                with st.container(border=True):
                    st.markdown('**ROI #{sel} bearbeiten**',
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
                if ca.button("💾",use_container_width=True,key=f"sv_{sel}"):
                    st.session_state.rois[sel]=dict(name=en,x=float(ex),y=float(ey),
                        w=float(ew),h=float(eh),fmt=ef,pattern=ep,max_scale=esc)
                    get_frame.clear(); set_status("ROI gespeichert.","ok"); st.rerun()
                if cb.button("🗑",use_container_width=True,key=f"dl_{sel}"):
                    st.session_state.rois.pop(sel); st.session_state.selected_roi=None
                    get_frame.clear(); set_status("ROI gelöscht.","info"); st.rerun()

            with st.container(border=True):
                st.markdown('**Lokal speichern**',unsafe_allow_html=True)
            cf=st.session_state.capture_folder or "output"
            result=build_result_json()
            result_str=json.dumps(result,indent=2,ensure_ascii=False)
            st.download_button("⬇ JSON",result_str,f"results_{cf}.json",
                               "application/json",use_container_width=True)
            mat_buf=io.BytesIO(); sio.savemat(mat_buf,build_mat_struct(result))
            st.download_button("⬇ MAT",mat_buf.getvalue(),f"results_{cf}.mat",
                               "application/octet-stream",use_container_width=True)

            with st.container(border=True):
                st.markdown('**Info**',unsafe_allow_html=True)
            n_t=sum(1 for r in st.session_state.rois if r["name"]=="track_minimap")
            st.markdown(f"""
            <div style="font-family:'JetBrains Mono',monospace;font-size:.67rem;
                 color:#8892a4;line-height:2.0;">
            <b style="color:#e8eaf0">Video</b> {fw}×{fh} @ {fps:.1f}fps<br>
            <b style="color:#e8eaf0">Dauer</b> {dur:.2f}s<br>
            <b style="color:#e8eaf0">Bereich</b> {t_start:.2f}→{st.session_state.t_end:.2f}s<br>
            <b style="color:#e8eaf0">ROIs</b> {len(st.session_state.rois)} ({n_t} track)
            </div>""",unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 🗺 – TRACK-ANALYSE
# ═══════════════════════════════════════════════════════════════════════════════
with tab_track:
    has_ref   = st.session_state.ref_track_img is not None
    track_roi = next((r for r in st.session_state.rois if r["name"]=="track_minimap"),None)
    has_vid   = st.session_state.video_path is not None
    fw=st.session_state.vid_width; fh=st.session_state.vid_height

    if not has_ref:
        st.info("ℹ️  Referenz-Track fehlt → Tab ☁️  → Bild laden.")
    if not track_roi:
        st.info("ℹ️  Keine track_minimap ROI → Tab 🎬  → ROI anlegen.")

    col_a,col_b=st.columns(2,gap="medium")
    clrs=[(255,80,80),(255,160,0),(255,255,0),(80,255,80),
          (0,200,255),(100,100,255),(200,80,255),(255,80,200)]

    with col_a:
        with st.container(border=True):
            st.markdown('**Referenz-Track · 8 Kalibrierpunkte**',
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
            if st.button("💾 Referenzpunkte speichern",use_container_width=True):
                st.session_state.ref_track_pts=pt_data
                set_status("Referenzpunkte gespeichert.","ok"); st.rerun()
            vis=st.session_state.ref_track_img.copy()
            for pi,pt in enumerate(ref_pts):
                if pt and len(pt)==2:
                    cv2.circle(vis,(int(pt[0]),int(pt[1])),8,clrs[pi%8],-1)
                    cv2.putText(vis,f"P{pi+1}",(int(pt[0])+10,int(pt[1])),
                                cv2.FONT_HERSHEY_SIMPLEX,.5,clrs[pi%8],1)
            st.image(vis,use_container_width=True,caption="Referenz-Track")
        else:
            st.markdown('<div style="text-align:center;color:#2e3545;padding:2rem;">'
                        'Kein Referenzbild</div>',unsafe_allow_html=True)

    with col_b:
        with st.container(border=True):
            st.markdown('**Minimap · 8 Punkte + Bewegungserkennung**',
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
                if st.button("💾 Minimap-Punkte speichern",use_container_width=True):
                    st.session_state.minimap_pts=mm_data
                    set_status("Minimap-Punkte gespeichert.","ok"); st.rerun()
                vis_c=crop.copy()
                for pi,pt in enumerate(st.session_state.minimap_pts or []):
                    if pt and len(pt)==2:
                        cv2.circle(vis_c,(int(pt[0]),int(pt[1])),6,clrs[pi%8],-1)
                        cv2.putText(vis_c,f"P{pi+1}",(int(pt[0])+7,int(pt[1])),
                                    cv2.FONT_HERSHEY_SIMPLEX,.4,clrs[pi%8],1)
                st.image(vis_c,use_container_width=True,caption=f"Minimap ({cw}×{ch}px)")
        else:
            st.markdown('<div style="text-align:center;color:#2e3545;padding:2rem;">'
                        'Video + track_minimap ROI benötigt</div>',unsafe_allow_html=True)

    with st.container(border=True):
        st.markdown('**Vergleich · Überlagerung · Bewegende Punkte**',
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
        st.image(px,caption="Zielfarbe",use_container_width=True)

    can_cmp=(has_ref and track_roi and has_vid and
             st.session_state.ref_track_pts and st.session_state.minimap_pts)
    with cv1:
        if can_cmp and st.button("▶ Vergleich",type="primary",use_container_width=True):
            frame=get_frame(st.session_state.video_path,st.session_state.t_current)
            if frame is not None:
                crop=extract_minimap_crop(frame,track_roi,fw,fh)
                cmp=compare_minimap_to_reference(crop,st.session_state.ref_track_img,
                    st.session_state.minimap_pts,st.session_state.ref_track_pts)
                st.session_state.track_comparison=cmp
                mp=detect_moving_point(crop,st.session_state.moving_pt_color_range)
                if mp:
                    st.session_state.moving_pt_history.append(
                        {"t":st.session_state.t_current,"x":mp["x"],"y":mp["y"]})
                set_status("Vergleich durchgeführt.","ok"); st.rerun()
        cmp=st.session_state.track_comparison
        if cmp:
            m1,m2,m3=st.columns(3)
            for col,val,lbl in [(m1,cmp["mean_dist_px"],"Ø px"),
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
                st.image(overlay,use_container_width=True,
                         caption="Minimap (blau) vs. Referenz (grün)")

    if st.session_state.moving_pt_history:
        with st.container(border=True):
            st.markdown('**Verlauf bewegender Punkt**',
                    unsafe_allow_html=True)
        import pandas as pd
        c1,c2=st.columns([1,4])
        c1.metric("Positionen",len(st.session_state.moving_pt_history))
        if c1.button("Leeren",key="hist_clear"):
            st.session_state.moving_pt_history=[]; st.rerun()
        df=pd.DataFrame(st.session_state.moving_pt_history[-100:])
        c2.dataframe(df,use_container_width=True,height=180)
