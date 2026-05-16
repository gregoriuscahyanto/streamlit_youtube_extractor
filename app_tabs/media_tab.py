"""Unified media library — replaces MAT Selection, MAT→JSON, YouTube Download tabs.

Data source: local results/*.json + results/*.mat + captures/ + logs/youtube_download_table.json
No R2, no framepack, no audio proxy.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path

from core.watchdog_state import _JSON_ROW_CACHE, get_path_lock

# ── Background conversion state (module-level, survives render calls) ─────────
_CONV_LOCK = threading.Lock()
_CONV: dict = {
    "running": False, "kind": "", "done": 0, "total": 0,
    "current": "", "log": [], "stop_requested": False,
}

# Per-JSON detail cache: str(path) -> (mtime, detail_dict)
_DETAIL_CACHE: dict[str, tuple[float, dict]] = {}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _conv_log(msg: str) -> None:
    with _CONV_LOCK:
        _CONV["log"].append(f"{datetime.now().strftime('%H:%M:%S')} | {msg}")
        _CONV["log"] = _CONV["log"][-100:]


def _base() -> Path:
    import streamlit as _st
    lp = str(_st.session_state.get("local_base_path") or "").strip()
    return Path(lp).expanduser().resolve() if lp else Path.cwd()


def _lamp(ok: bool) -> str:
    return "✅" if ok else "❌"


def _read_json_detail(jp: Path) -> dict:
    """Read only the fields needed for the table row; cache by mtime."""
    cache_key = str(jp)
    try:
        mtime = jp.stat().st_mtime
    except Exception:
        return {}
    cached = _DETAIL_CACHE.get(cache_key)
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        doc = json.loads(jp.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return {}
    rr = doc.get("recordResult") if isinstance(doc, dict) else {}
    if not isinstance(rr, dict):
        rr = {}
    meta = rr.get("metadata") or {}
    if not isinstance(meta, dict):
        meta = {}
    ocr = rr.get("ocr") or {}
    if not isinstance(ocr, dict):
        ocr = {}
    ocr_tbl = ocr.get("table")
    ocr_params = ocr.get("params") or {}
    if not isinstance(ocr_params, dict):
        ocr_params = {}
    if isinstance(ocr_tbl, dict) and ocr_tbl.get("time_s"):
        ocr_st = "teilweise" if ocr_params.get("partial") else "vollständig"
    elif isinstance(ocr_tbl, list) and ocr_tbl:
        ocr_st = "teilweise"
    else:
        ocr_st = "nein"
    detail = {
        "title": str(meta.get("title") or meta.get("video_title") or ""),
        "youtube_link": str(meta.get("url") or meta.get("youtube_url") or meta.get("link") or ""),
        "upload_date": str(meta.get("pubDate") or meta.get("upload_date") or ""),
        "duration": float(meta.get("duration") or 0.0),
        "roi": bool(ocr.get("roi_table")),
        "ocr": ocr_st,
        "audio_config": bool(rr.get("audio_config")),
        "validierung": bool(rr.get("audio_validation")),
    }
    _DETAIL_CACHE[cache_key] = (mtime, detail)
    return detail


def _scan_rows(base: Path) -> list[dict]:
    """Build unified table rows from local files + YouTube DB."""
    res_dir = base / "results"
    cap_root = base / "captures"
    audio_exts = {".wav", ".mp3", ".m4a", ".aac", ".flac"}
    video_exts = {".mp4", ".mov", ".avi", ".mkv"}
    proxy_name = "audio_proxy_1k.wav"

    # Index MAT files
    mat_by_stem: dict[str, Path] = {}
    if res_dir.exists():
        for mp in res_dir.glob("results_*.mat"):
            mat_by_stem[mp.stem] = mp

    rows: list[dict] = []
    seen_stems: set[str] = set()

    # Primary: JSON files
    if res_dir.exists():
        for jp in sorted(res_dir.glob("results_*.json"), reverse=True):
            stem = jp.stem
            folder = stem.replace("results_", "", 1)
            seen_stems.add(stem)
            detail = _read_json_detail(jp)

            cap_dir = cap_root / folder
            has_video = has_audio = False
            if cap_dir.exists():
                for f in cap_dir.iterdir():
                    if not f.is_file() or f.stat().st_size <= 0:
                        continue
                    ext = f.suffix.lower()
                    if ext in video_exts:
                        has_video = True
                    elif ext in audio_exts and f.name.lower() != proxy_name:
                        has_audio = True

            rows.append({
                "folder": folder,
                "title": detail.get("title", ""),
                "youtube_link": detail.get("youtube_link", ""),
                "upload_date": detail.get("upload_date", ""),
                "duration": detail.get("duration", 0.0),
                "json_exists": True,
                "mat_exists": stem in mat_by_stem,
                "video_exists": has_video,
                "audio_exists": has_audio,
                "download_status": "",
                "downloaded_at": "",
                "last_error": "",
                "roi": detail.get("roi", False),
                "ocr": detail.get("ocr", "nein"),
                "audio_config": detail.get("audio_config", False),
                "validierung": detail.get("validierung", False),
                "json_path": str(jp),
                "mat_path": str(mat_by_stem[stem]) if stem in mat_by_stem else "",
            })

    # MAT-only (no JSON yet)
    for stem, mp in sorted(mat_by_stem.items(), reverse=True):
        if stem in seen_stems:
            continue
        folder = stem.replace("results_", "", 1)
        rows.append({
            "folder": folder, "title": "", "youtube_link": "", "upload_date": "",
            "duration": 0.0, "json_exists": False, "mat_exists": True,
            "video_exists": False, "audio_exists": False,
            "download_status": "", "downloaded_at": "", "last_error": "",
            "roi": False, "ocr": "nein", "audio_config": False, "validierung": False,
            "json_path": "", "mat_path": str(mp),
        })

    # Merge YouTube DB
    db_path = Path("logs") / "youtube_download_table.json"
    db_rows: list[dict] = []
    try:
        if db_path.exists():
            db_rows = json.loads(db_path.read_text(encoding="utf-8")) or []
    except Exception:
        pass

    row_by_folder = {r["folder"]: r for r in rows}
    row_by_link = {r["youtube_link"]: r for r in rows if r["youtube_link"]}
    db_by_folder = {str(d.get("capture_folder") or "").strip(): d for d in db_rows if isinstance(d, dict)}
    db_by_link = {str(d.get("youtube_link") or "").strip(): d for d in db_rows if isinstance(d, dict)}

    for row in rows:
        db = db_by_folder.get(row["folder"]) or db_by_link.get(row["youtube_link"]) or {}
        if db:
            row["download_status"] = str(db.get("download_status") or row["download_status"] or "")
            row["downloaded_at"] = str(db.get("downloaded_at") or row["downloaded_at"] or "")
            row["last_error"] = str(db.get("last_error") or row["last_error"] or "")
            if not row["youtube_link"]:
                row["youtube_link"] = str(db.get("youtube_link") or "")
            if not row["title"]:
                row["title"] = str(db.get("title") or "")

    # DB-only entries (link added, no captures yet)
    for db_row in db_rows:
        if not isinstance(db_row, dict):
            continue
        folder = str(db_row.get("capture_folder") or "").strip()
        link = str(db_row.get("youtube_link") or "").strip()
        if not link:
            continue
        if (folder and folder in row_by_folder) or (link and link in row_by_link):
            continue
        rows.append({
            "folder": folder or "(ausstehend)",
            "title": str(db_row.get("title") or ""),
            "youtube_link": link,
            "upload_date": str(db_row.get("upload_date") or ""),
            "duration": 0.0,
            "json_exists": False, "mat_exists": False,
            "video_exists": False, "audio_exists": False,
            "download_status": str(db_row.get("download_status") or "pending"),
            "downloaded_at": str(db_row.get("downloaded_at") or ""),
            "last_error": str(db_row.get("last_error") or ""),
            "roi": False, "ocr": "nein", "audio_config": False, "validierung": False,
            "json_path": str(db_row.get("json_path") or ""),
            "mat_path": "",
        })

    return rows


def _build_df(rows: list[dict]):
    import pandas as pd
    OCR = {"vollständig": "✅", "teilweise": "⚠️", "nein": "❌"}
    DL = {"downloaded": "✅", "downloading": "⏳", "error": "❌", "pending": "⏳", "": "-"}
    return pd.DataFrame([{
        "Ordner": r["folder"],
        "Titel": r["title"],
        "DL": DL.get(r["download_status"], r["download_status"] or "-"),
        "JSON": _lamp(r["json_exists"]),
        "MAT": _lamp(r["mat_exists"]),
        "Video": _lamp(r["video_exists"]),
        "Audio": _lamp(r["audio_exists"]),
        "ROI": _lamp(r["roi"]),
        "OCR": OCR.get(r["ocr"], r["ocr"]),
        "Audio-Konfig": _lamp(r["audio_config"]),
        "Validierung": _lamp(r["validierung"]),
        "Hochgeladen": r["upload_date"],
        "Heruntergeladen": r["downloaded_at"],
        "Fehler": r["last_error"][:80] if r["last_error"] else "",
        "YouTube-Link": r["youtube_link"],
    } for r in rows])


def _write_db_entry(link: str, folder: str = "", title: str = "", status: str = "pending") -> None:
    db_path = Path("logs") / "youtube_download_table.json"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    entries: list[dict] = []
    try:
        if db_path.exists():
            entries = json.loads(db_path.read_text(encoding="utf-8")) or []
    except Exception:
        pass
    # Check if already exists
    for e in entries:
        if str(e.get("youtube_link") or "") == link:
            return
    entries.append({
        "youtube_link": link, "title": title, "upload_date": "",
        "capture_folder": folder, "download_status": status,
        "last_error": "", "downloaded_at": "", "json_path": "",
    })
    db_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")


def _update_db_status(folder: str, link: str, status: str, error: str = "") -> None:
    db_path = Path("logs") / "youtube_download_table.json"
    entries: list[dict] = []
    try:
        if db_path.exists():
            entries = json.loads(db_path.read_text(encoding="utf-8")) or []
    except Exception:
        return
    changed = False
    for e in entries:
        cf = str(e.get("capture_folder") or "").strip()
        lk = str(e.get("youtube_link") or "").strip()
        if (folder and cf == folder) or (link and lk == link):
            e["download_status"] = status
            if error:
                e["last_error"] = error
            changed = True
    if changed:
        db_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Background: MAT→JSON conversion ──────────────────────────────────────────

def _inline_convert_one_mat(mat_path: Path) -> dict:
    """Standalone MAT→JSON conversion using app helpers from globals()."""
    json_path = mat_path.with_suffix(".json")
    mat_name = mat_path.name
    if json_path.exists() and json_path.stat().st_size > 0:
        return {"ok": False, "mat_name": mat_name, "status": "bereits vorhanden"}
    try:
        raw = mat_path.read_bytes()
    except Exception as e:
        return {"ok": False, "mat_name": mat_name, "status": f"Lesen: {e}"}

    out: bytes | None = None
    helper = globals().get("_mat_bytes_to_recordresult_json_bytes")
    if callable(helper):
        try:
            result = helper(raw)
            out = bytes(result) if result else None
        except Exception:
            out = None

    if not out:
        try:
            from core.save_helpers import rr_from_mat_bytes
            rr, _ = rr_from_mat_bytes(raw)
            if isinstance(rr, dict) and rr:
                out = json.dumps(
                    {"recordResult": rr}, ensure_ascii=False, indent=2, default=str
                ).encode("utf-8")
        except Exception:
            pass

    if not out:
        return {"ok": False, "mat_name": mat_name, "status": "Konvertierung fehlgeschlagen"}

    try:
        with get_path_lock(str(json_path)):
            json_path.write_bytes(out)
    except Exception as e:
        return {"ok": False, "mat_name": mat_name, "status": f"Schreiben: {e}"}

    _DETAIL_CACHE.pop(str(json_path), None)
    _JSON_ROW_CACHE.pop(str(json_path), None)
    return {"ok": True, "mat_name": mat_name, "status": f"konvertiert ({len(out):,} Bytes)"}


def _run_conv_thread(pending: list[Path], convert_fn) -> None:
    with _CONV_LOCK:
        _CONV.update({"running": True, "done": 0, "total": len(pending),
                      "current": "", "stop_requested": False})
    for mp in pending:
        with _CONV_LOCK:
            if _CONV["stop_requested"]:
                _conv_log("Abgebrochen.")
                break
            _CONV["current"] = mp.name
        try:
            result = convert_fn(mp)
            ok = result.get("ok", False) if isinstance(result, dict) else bool(result)
            status = result.get("status", "") if isinstance(result, dict) else str(result)
            _conv_log(("✅" if ok else "❌") + f" {mp.name}: {status}")
            # Invalidate caches
            jp = mp.with_suffix(".json")
            _DETAIL_CACHE.pop(str(jp), None)
            _JSON_ROW_CACHE.pop(str(jp), None)
        except Exception as e:
            _conv_log(f"❌ {mp.name}: {e}")
        with _CONV_LOCK:
            _CONV["done"] += 1
    with _CONV_LOCK:
        _CONV["running"] = False
        _CONV["current"] = ""
    _conv_log("MAT→JSON fertig.")


# ── Render ────────────────────────────────────────────────────────────────────

def render(ns: dict) -> None:
    globals().update(ns)
    import pandas as pd

    st.markdown('<div class="section-title">Medienbibliothek</div>', unsafe_allow_html=True)
    st.caption("Gemeinsame Datenbasis: JSON-Dateien in results/. Kein R2, kein Proxy.")

    base = _base()
    rows = _scan_rows(base)
    df = _build_df(rows)

    # ── Background task progress ───────────────────────────────────────────────
    with _CONV_LOCK:
        running = _CONV["running"]
        done = _CONV["done"]
        total = _CONV["total"]
        current = _CONV["current"]
        log_lines = list(_CONV["log"])

    if running:
        st.progress(done / max(1, total), text=f"MAT→JSON: {current} ({done}/{total})")
        if st.button("Abbrechen", key="lib_conv_stop"):
            with _CONV_LOCK:
                _CONV["stop_requested"] = True
        with st.expander("Konvertierungs-Log", expanded=False):
            st.code("\n".join(log_lines[-30:]), language="text")
        st.rerun()
    elif log_lines:
        with st.expander("Letzter Konvertierungs-Log", expanded=False):
            st.code("\n".join(log_lines[-30:]), language="text")

    # ── Action bar ─────────────────────────────────────────────────────────────
    col_mat, col_dl, col_retry, col_link = st.columns([2, 2, 2, 3])

    # MAT → JSON (alle ausstehenden)
    pending_mats = [
        Path(r["mat_path"]) for r in rows
        if r["mat_exists"] and not r["json_exists"] and r["mat_path"]
    ]
    convert_fn = globals().get("_convert_one_mat") or _inline_convert_one_mat
    mat_btn_label = f"MAT→JSON ({len(pending_mats)})"
    if col_mat.button(mat_btn_label, disabled=running or not pending_mats,
                      use_container_width=True, key="lib_mat_all_btn"):
        t = threading.Thread(target=_run_conv_thread, args=(pending_mats, convert_fn), daemon=True)
        t.start()
        st.rerun()

    # Download ausstehend
    pending_dl = [r for r in rows if r["youtube_link"] and not r["video_exists"]
                  and r["download_status"] not in ("downloading",)]
    if col_dl.button(f"Herunterladen ({len(pending_dl)})",
                     disabled=not pending_dl, use_container_width=True, key="lib_dl_btn"):
        st.session_state.yt_watchdog_task_download = True
        st.session_state.yt_watchdog_cmd = "start"
        st.info("Watchdog-Download für ausstehende Videos aktiviert.")

    # Fehlerhafte neu laden
    faulty = [r for r in rows if r["youtube_link"] and r["download_status"] == "error"]
    if col_retry.button(f"Neu laden ({len(faulty)})",
                        disabled=not faulty, use_container_width=True, key="lib_retry_btn"):
        for r in faulty:
            _update_db_status(r["folder"], r["youtube_link"], "pending", "")
        st.rerun()

    # Neuer YouTube-Link
    with col_link:
        new_link = st.text_input("Neuer YouTube-Link", key="lib_new_link",
                                 placeholder="https://www.youtube.com/watch?v=...", label_visibility="collapsed")
        if st.button("+ Link", key="lib_add_btn", disabled=not str(new_link or "").strip()):
            link = str(new_link).strip()
            existing = {r["youtube_link"] for r in rows}
            if link in existing:
                st.warning("Link bereits vorhanden.")
            else:
                _write_db_entry(link)
                st.success("Link hinzugefügt.")
                st.rerun()

    # ── Tabelle ────────────────────────────────────────────────────────────────
    st.markdown(f"**{len(rows)} Einträge** | Basis: `{base}`")

    COL_CFG = {
        "Ordner":        st.column_config.TextColumn("Ordner", width="medium"),
        "Titel":         st.column_config.TextColumn("Titel", width="large"),
        "DL":            st.column_config.TextColumn("DL", width="small"),
        "JSON":          st.column_config.TextColumn("JSON", width="small"),
        "MAT":           st.column_config.TextColumn("MAT", width="small"),
        "Video":         st.column_config.TextColumn("Video", width="small"),
        "Audio":         st.column_config.TextColumn("Audio", width="small"),
        "ROI":           st.column_config.TextColumn("ROI", width="small"),
        "OCR":           st.column_config.TextColumn("OCR", width="small"),
        "Audio-Konfig":  st.column_config.TextColumn("Audio-Konfig", width="small"),
        "Validierung":   st.column_config.TextColumn("Validierung", width="small"),
        "Hochgeladen":   st.column_config.TextColumn("Hochgeladen", width="small"),
        "Heruntergeladen": st.column_config.TextColumn("Heruntergeladen", width="small"),
        "Fehler":        st.column_config.TextColumn("Fehler", width="medium"),
        "YouTube-Link":  st.column_config.LinkColumn("YouTube-Link", width="medium"),
    }

    selection = st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        height=420,
        on_select="rerun",
        selection_mode="single-row",
        column_config=COL_CFG,
        key="lib_table",
    )

    # ── Ausgewählte Zeile: Aktionen ────────────────────────────────────────────
    sel_indices = (selection.selection.rows
                   if hasattr(selection, "selection") and selection.selection else [])
    if not sel_indices:
        return

    sel_row = rows[sel_indices[0]]
    st.divider()
    st.markdown(f"**Ausgewählt:** `{sel_row['folder']}` — {sel_row['title'] or '(kein Titel)'}")

    def _load_folder(folder: str, json_path_str: str, load_video: bool = True) -> list[str]:
        """Load folder into session state. Returns list of warning messages."""
        msgs: list[str] = []
        st.session_state.capture_folder = folder

        # Load JSON: extract ROIs and t_start/t_end into session state
        if json_path_str:
            try:
                doc = json.loads(Path(json_path_str).read_text(encoding="utf-8", errors="ignore"))
                rr = doc.get("recordResult") if isinstance(doc, dict) else {}
                if isinstance(rr, dict):
                    ocr = rr.get("ocr") or {}
                    if isinstance(ocr, dict):
                        roi_table = ocr.get("roi_table") or []
                        if isinstance(roi_table, list) and roi_table:
                            st.session_state.rois = [
                                dict(r) for r in roi_table if isinstance(r, dict)
                            ]
                        params = ocr.get("params") or {}
                        if isinstance(params, dict):
                            if "start_s" in params:
                                st.session_state.t_start = float(params["start_s"])
                            if "end_s" in params:
                                st.session_state.t_end = float(params["end_s"])
                st.session_state["mat_selected_key"] = json_path_str
            except Exception as e:
                msgs.append(f"JSON: {e}")

        # Load video
        if load_video:
            try:
                load_vid = globals().get("_try_load_video_for_capture_folder_with_fallback")
                if callable(load_vid):
                    load_vid(folder)
                else:
                    find_vid = globals().get("_find_local_fullfps_video")
                    apply_vid = globals().get("_apply_video")
                    if callable(find_vid) and callable(apply_vid):
                        vp = find_vid(folder)
                        if vp and vp.exists():
                            apply_vid(str(vp), vp.name)
            except Exception as e:
                msgs.append(f"Video: {e}")

        return msgs

    can_load = sel_row["json_exists"] or sel_row["video_exists"] or sel_row["audio_exists"]
    ra1, ra2, ra3, ra4, ra5 = st.columns(5)

    # ── Für ROI Setup laden ────────────────────────────────────────────────────
    if ra1.button("→ ROI Setup laden", disabled=not can_load,
                  use_container_width=True, key="lib_load_roi_btn"):
        msgs = _load_folder(sel_row["folder"], sel_row["json_path"])
        for m in msgs:
            st.warning(m)
        st.success(f"Geladen: {sel_row['folder']} — jetzt Tab **ROI Setup** öffnen.")

    # ── Für Audio Setup laden ──────────────────────────────────────────────────
    if ra2.button("→ Audio Setup laden", disabled=not can_load,
                  use_container_width=True, key="lib_load_audio_btn"):
        msgs = _load_folder(sel_row["folder"], sel_row["json_path"], load_video=False)
        for m in msgs:
            st.warning(m)
        st.success(f"Geladen: {sel_row['folder']} — jetzt Tab **Audio Auswertung** öffnen.")

    # ── MAT→JSON (nur diese Zeile) ─────────────────────────────────────────────
    if ra3.button("MAT→JSON",
                  disabled=not sel_row["mat_exists"] or sel_row["json_exists"] or running,
                  use_container_width=True, key="lib_row_mat_btn"):
        t = threading.Thread(
            target=_run_conv_thread,
            args=([Path(sel_row["mat_path"])], convert_fn),
            daemon=True,
        )
        t.start()
        st.rerun()

    # ── Video herunterladen (diese Zeile) ──────────────────────────────────────
    has_link = bool(sel_row["youtube_link"])
    if ra4.button("Video herunterladen",
                  disabled=not has_link or sel_row["video_exists"],
                  use_container_width=True, key="lib_row_dl_btn"):
        _write_db_entry(sel_row["youtube_link"], sel_row["folder"], sel_row["title"])
        st.session_state.yt_watchdog_task_download = True
        st.session_state.yt_watchdog_cmd = "start"
        st.info("Download wird vom Watchdog gestartet.")

    # ── Details ────────────────────────────────────────────────────────────────
    with ra5:
        with st.expander("Details", expanded=False):
            display = {k: v for k, v in sel_row.items() if k not in ("duration",)}
            st.json(display)
