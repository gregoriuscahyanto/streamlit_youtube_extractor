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
    return "🟢" if ok else "🔴"


def _lamp3(status: str) -> str:
    """Green / yellow / red circle for three-state status fields."""
    if status == "vollständig":
        return "🟢"
    if status == "unvollständig":
        return "🟡"
    return "🔴"


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
    # video_faulty / no_roi_available: stamps set during ROI setup
    video_faulty = bool(ocr.get("video_faulty")) or bool(
        (meta.get("video_faulty") if isinstance(meta, dict) else False)
    )
    no_roi_available = bool(ocr.get("no_roi_available")) or bool(
        (meta.get("no_roi_available") if isinstance(meta, dict) else False)
    )

    # Determine if track_minimap ROI is present in roi_table.
    roi_table = ocr.get("roi_table") or ocr.get("roi_table_raw")
    has_track_minimap = False
    if isinstance(roi_table, list):
        for row in roi_table:
            if isinstance(row, dict):
                nm = str(row.get("name_roi") or row.get("name") or "").strip().lower()
            elif isinstance(row, str):
                # Legacy flat format: [name, [x,y,w,h], fmt, scale, ...]
                nm = row.strip().lower()
            else:
                continue
            if nm == "track_minimap":
                has_track_minimap = True
                break
    elif isinstance(roi_table, dict):
        names = roi_table.get("name_roi") or roi_table.get("name") or []
        if isinstance(names, list):
            has_track_minimap = any(str(n or "").strip().lower() == "track_minimap" for n in names)
        else:
            has_track_minimap = str(names or "").strip().lower() == "track_minimap"
    # Also check trkCalSlim.roi as a fallback indicator (OCRExtractor always writes it there).
    trk_slim = ocr.get("trkCalSlim") if isinstance(ocr.get("trkCalSlim"), dict) else {}
    if not has_track_minimap and isinstance(trk_slim, dict):
        trk_roi = trk_slim.get("roi")
        if isinstance(trk_roi, (list, tuple)) and len(trk_roi) >= 4:
            try:
                if float(trk_roi[2]) > 0 and float(trk_roi[3]) > 0:
                    has_track_minimap = True
            except Exception:
                pass

    # If track_minimap is present, check that all calibration params are saved.
    roi_incomplete_track = False
    if has_track_minimap:
        def _pts_ok(v) -> bool:
            return isinstance(v, list) and len(v) >= 4
        def _color_ok(v) -> bool:
            return isinstance(v, dict) and "h_lo" in v
        def _cl_ok(v) -> bool:
            if not isinstance(v, (list, tuple)) or len(v) < 2:
                return False
            try:
                import numpy as _np
                arr = _np.asarray(v, dtype=float)
                return arr.ndim == 2 and arr.shape[0] >= 2 and arr.shape[1] >= 2
            except Exception:
                return False
        missing = []
        if not _pts_ok(trk_slim.get("minimap_pts")):
            missing.append("minimap_pts")
        if not _pts_ok(trk_slim.get("ref_pts")):
            missing.append("ref_pts")
        if not _color_ok(trk_slim.get("moving_pt_color_range")):
            missing.append("color_range")
        if not _cl_ok(trk_slim.get("centerline_px")):
            missing.append("centerline_px")
        roi_incomplete_track = bool(missing)

    roi_exists = bool(ocr.get("roi_table"))
    if roi_exists and has_track_minimap and roi_incomplete_track:
        roi_status = "unvollständig"
    elif roi_exists:
        roi_status = "vollständig"
    else:
        roi_status = "nein"

    detail = {
        "title": str(meta.get("title") or meta.get("video_title") or ""),
        "youtube_link": str(meta.get("url") or meta.get("youtube_url") or meta.get("link") or ""),
        "upload_date": str(meta.get("pubDate") or meta.get("upload_date") or ""),
        "duration": float(meta.get("duration") or 0.0),
        "roi": roi_exists,
        "roi_status": roi_status,
        "ocr": ocr_st,
        "audio_config": bool(rr.get("audio_config")),
        "validierung": bool(rr.get("audio_validation")),
        "video_faulty": video_faulty,
        "no_roi_available": no_roi_available,
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
                "video_faulty": detail.get("video_faulty", False),
                "no_roi_available": detail.get("no_roi_available", False),
                "download_status": "",
                "downloaded_at": "",
                "last_error": "",
                "roi": detail.get("roi", False),
                "roi_status": detail.get("roi_status", "nein"),
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
            "video_faulty": False, "no_roi_available": False,
            "download_status": "", "downloaded_at": "", "last_error": "",
            "roi": False, "roi_status": "nein", "ocr": "nein",
            "audio_config": False, "validierung": False,
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
            "video_faulty": False, "no_roi_available": False,
            "download_status": str(db_row.get("download_status") or "pending"),
            "downloaded_at": str(db_row.get("downloaded_at") or ""),
            "last_error": str(db_row.get("last_error") or ""),
            "roi": False, "roi_status": "nein", "ocr": "nein",
            "audio_config": False, "validierung": False,
            "json_path": str(db_row.get("json_path") or ""),
            "mat_path": "",
        })

    return rows


def _build_df(rows: list[dict]):
    import pandas as pd
    OCR_MAP = {"vollständig": "🟢", "teilweise": "🟡", "nein": "🔴"}
    DL = {"downloaded": "🟢", "downloading": "🟡", "error": "🔴", "pending": "🟡", "": "-"}
    return pd.DataFrame([{
        "Ordner": r["folder"],
        "Titel": r["title"],
        "DL": DL.get(r["download_status"], r["download_status"] or "-"),
        "JSON": _lamp(r["json_exists"]),
        "MAT": _lamp(r["mat_exists"]),
        "Video": _lamp(r["video_exists"]),
        "Audio": _lamp(r["audio_exists"]),
        "ROI": _lamp3(r.get("roi_status", "nein" if not r["roi"] else "vollständig")),
        "ROI n.v.": _lamp(r.get("no_roi_available", False)),
        "Fehlerhaft": _lamp(r.get("video_faulty", False)),
        "OCR": OCR_MAP.get(r["ocr"], r["ocr"]),
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


def _delete_row(base: Path, folder: str, youtube_link: str) -> tuple[list[str], list[str]]:
    """
    Delete all files/folders for a row.
    Returns (deleted, errors) — lists of human-readable strings.
    """
    import shutil
    deleted: list[str] = []
    errors: list[str] = []

    def _rm_file(p: Path) -> None:
        try:
            if p.exists():
                p.unlink()
                deleted.append(p.name)
        except Exception as e:
            errors.append(f"{p.name}: {e}")

    def _rm_dir(p: Path) -> None:
        try:
            if p.exists() and p.is_dir():
                shutil.rmtree(p)
                deleted.append(str(p.relative_to(base)))
        except Exception as e:
            errors.append(f"{p.name}/: {e}")

    # JSON + MAT result files
    res_dir = base / "results"
    _rm_file(res_dir / f"results_{folder}.json")
    _rm_file(res_dir / f"results_{folder}.mat")

    # Capture folder (video + audio)
    _rm_dir(base / "captures" / folder)

    # Remove from YouTube DB
    db_path = Path("logs") / "youtube_download_table.json"
    try:
        if db_path.exists():
            entries = json.loads(db_path.read_text(encoding="utf-8")) or []
            before = len(entries)
            entries = [
                e for e in entries
                if not (
                    (folder and str(e.get("capture_folder") or "").strip() == folder)
                    or (youtube_link and str(e.get("youtube_link") or "").strip() == youtube_link)
                )
            ]
            if len(entries) < before:
                db_path.write_text(
                    json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                deleted.append("DB-Eintrag")
    except Exception as e:
        errors.append(f"DB: {e}")

    # Invalidate caches
    try:
        from core.watchdog_state import _JSON_ROW_CACHE, _DETAIL_CACHE
        _JSON_ROW_CACHE.pop(str(res_dir / f"results_{folder}.json"), None)
        _DETAIL_CACHE.pop(str(res_dir / f"results_{folder}.json"), None)
    except Exception:
        pass

    return deleted, errors


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


def _render_media_analysis(rows: list[dict]) -> None:
    """Horizontal progress bars summarising pipeline status across all entries."""
    import streamlit as _st
    total = len(rows)
    if total == 0:
        return

    def _pct(n: int) -> float:
        return 100.0 * n / total if total else 0.0

    n_av_ok    = sum(1 for r in rows if r.get("video_exists") and r.get("audio_exists"))
    n_av_part  = sum(1 for r in rows if bool(r.get("video_exists")) != bool(r.get("audio_exists")))
    n_av_miss  = total - n_av_ok - n_av_part
    # ROI — four exclusive buckets:
    #   green   = vollständig
    #   yellow  = unvollständig (track_minimap calibration incomplete)
    #   red     = manually stamped (kein_roi OR video_faulty) → always override
    #   gray    = anstehend (roi_status "nein", not yet checked/stamped)
    n_roi_ok   = sum(1 for r in rows
                     if r.get("roi_status") == "vollständig"
                     and not r.get("no_roi_available") and not r.get("video_faulty"))
    n_roi_inc  = sum(1 for r in rows
                     if r.get("roi_status") == "unvollständig"
                     and not r.get("no_roi_available") and not r.get("video_faulty"))
    n_roi_red  = sum(1 for r in rows
                     if r.get("no_roi_available") or r.get("video_faulty"))
    n_roi_pend = total - n_roi_ok - n_roi_inc - n_roi_red  # anstehend
    n_ocr_ok   = sum(1 for r in rows
                     if r.get("ocr") == "vollständig"
                     and not r.get("no_roi_available") and not r.get("video_faulty"))
    n_ocr_pt   = sum(1 for r in rows
                     if r.get("ocr") == "teilweise"
                     and not r.get("no_roi_available") and not r.get("video_faulty"))
    n_ocr_red  = n_roi_red  # same stamp: kein ROI / video fehlerhaft
    n_ocr_pend = total - n_ocr_ok - n_ocr_pt - n_ocr_red
    n_acfg     = sum(1 for r in rows if r.get("audio_config"))
    n_val      = sum(1 for r in rows if r.get("validierung"))

    _ROW_STYLE = 'style="grid-template-columns:160px 1fr auto;min-width:0;"'

    def _simple_bar(label: str, ok: int, color: str = "#4a90a4") -> str:
        p = _pct(ok)
        return (
            f'<div class="mat-analysis-bar-row" {_ROW_STYLE}>'
            f'<div>{label}</div>'
            f'<div class="mat-analysis-bar-track">'
            f'<div class="mat-analysis-bar-fill" style="width:{p:.1f}%;background:{color};"></div>'
            f'</div>'
            f'<div style="white-space:nowrap;padding-left:.4rem;">{ok}/{total} · {p:.0f}%</div>'
            f'</div>'
        )

    def _stacked_bar(label: str, segments: list[tuple[int, str]]) -> str:
        inner = "".join(
            f'<div style="width:{_pct(n):.1f}%;background:{c};height:100%;flex-shrink:0;"></div>'
            for n, c in segments if n > 0
        )
        legend = " · ".join(
            f'<span style="color:{c};">{n}</span>'
            for n, c in segments
        )
        return (
            f'<div class="mat-analysis-bar-row" {_ROW_STYLE}>'
            f'<div>{label}</div>'
            f'<div class="mat-analysis-bar-track" style="display:flex;overflow:hidden;">{inner}</div>'
            f'<div style="white-space:nowrap;padding-left:.4rem;">{legend} / {total}</div>'
            f'</div>'
        )

    bar_html = ['<div class="mat-analysis-bars">']
    bar_html.append(_stacked_bar("Audio + Video", [
        (n_av_ok,   "#3ddc84"),   # beides vorhanden
        (n_av_part, "#facc15"),   # nur audio oder nur video
        (n_av_miss, "#ef4444"),   # beides fehlt (nicht heruntergeladen)
    ]))
    bar_html.append(_stacked_bar("ROI", [
        (n_roi_ok,   "#3ddc84"),   # vollständig
        (n_roi_inc,  "#facc15"),   # unvollständig
        (n_roi_red,  "#ef4444"),   # kein ROI / video fehlerhaft (manuell gesetzt)
        (n_roi_pend, "#4a5060"),   # anstehend (noch nicht geprüft)
    ]))
    bar_html.append(_stacked_bar("OCR", [
        (n_ocr_ok,   "#3ddc84"),   # vollständig
        (n_ocr_pt,   "#facc15"),   # teilweise
        (n_ocr_red,  "#ef4444"),   # kein ROI / video fehlerhaft (manuell gesetzt)
        (n_ocr_pend, "#4a5060"),   # anstehend
    ]))
    bar_html.append(_simple_bar("Audio-Konfig",  n_acfg, "#4a90a4"))
    bar_html.append(_simple_bar("Validierung",   n_val,  "#4a90a4"))
    bar_html.append('</div>')

    legend = (
        '<div class="mat-analysis-note" style="margin-top:.6rem;">'
        '<span style="color:#3ddc84;">&#9632;</span> vollständig &nbsp;'
        '<span style="color:#facc15;">&#9632;</span> unvollständig &nbsp;'
        '<span style="color:#ef4444;">&#9632;</span> kein ROI / video fehlerhaft &nbsp;'
        '<span style="color:#4a5060;">&#9632;</span> anstehend'
        '</div>'
    )
    bar_html.append(legend)
    with _st.expander("Analyse-Übersicht", expanded=True):
        _st.markdown("".join(bar_html), unsafe_allow_html=True)


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
    col_mat, col_dl, col_link = st.columns([2, 3, 3])

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

    # Herunterladen: video fehlt, audio fehlt, oder als fehlerhaft markiert
    def _needs_download(r: dict) -> bool:
        if not r.get("youtube_link"):
            return False
        if r.get("download_status") == "downloading":
            return False
        if not r.get("video_exists") or not r.get("audio_exists"):
            return True
        if r.get("video_faulty") or r.get("download_status") == "error":
            return True
        return False

    pending_dl = [r for r in rows if _needs_download(r)]
    dl_label = f"Herunterladen / Wiederholen ({len(pending_dl)})"
    if col_dl.button(dl_label, disabled=not pending_dl,
                     use_container_width=True, key="lib_dl_btn"):
        for r in pending_dl:
            _update_db_status(r["folder"], r["youtube_link"], "pending", "")
        st.session_state.yt_watchdog_task_download = True
        st.session_state.yt_watchdog_cmd = "start"
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

    # ── Nachkorrektur / Nachfiltern ────────────────────────────────────────────
    _result_json_paths = sorted(
        str(p) for p in (base / "results").glob("results_*.json")
    ) if (base / "results").exists() else []

    with st.expander(f"Nachkorrektur ({len(_result_json_paths)} Dateien)", expanded=False):
        st.caption(
            "Kombinierte Nachkorrektur für bereits ausgewertete Dateien. "
            "Führt die Schritte aus die beim Auswerten fehlten oder durch Bugs fehlerhaft waren."
        )

        _nc1, _nc2 = st.columns(2)

        # ── Button 1: Vollständige Nachkorrektur ──────────────────────────────
        with _nc1:
            st.markdown("**Vollständige Nachkorrektur**")
            st.caption(
                "① Zeilen außerhalb start_s/end_s löschen  \n"
                "② Min/Max + Steigung aus ROI-Katalog filtern  \n"
                "③ track_minimap neu berechnen wenn track_minimap_found überall 0"
            )
            if st.button(
                f"Alle {len(_result_json_paths)} Dateien nachkorrigieren",
                disabled=not _result_json_paths,
                key="lib_retrofix_btn",
            ):
                try:
                    from app_tabs.plausibility_filter import retrofix_result_json, needs_track_rerun
                    from app_tabs.roi_catalog_tab import load_catalog as _lc_lib2
                    _rf_catalog = st.session_state.get("roi_catalog") or _lc_lib2()
                    _rf_ok, _rf_skip, _rf_err, _rf_track = 0, 0, 0, 0
                    _rf_needs_track: list[str] = []
                    _prog2 = st.progress(0.0, text="Nachkorrektur läuft…")
                    for _ri, _rp in enumerate(_result_json_paths):
                        _ok, _msg, _tn = retrofix_result_json(_rp, _rf_catalog)
                        if _ok:
                            _rf_ok += 1
                        elif any(x in _msg for x in ("keine Tabelle", "kein ocr", "kein recordResult", "keine Änderungen")):
                            _rf_skip += 1
                        else:
                            _rf_err += 1
                        if _tn:
                            _rf_needs_track.append(_rp)
                        _prog2.progress((_ri + 1) / len(_result_json_paths),
                                        text=f"Nachkorrektur… {_ri+1}/{len(_result_json_paths)}")
                    _prog2.empty()
                    st.success(
                        f"Trim+Filter: {_rf_ok} geändert, {_rf_skip} ohne Daten"
                        + (f", {_rf_err} Fehler" if _rf_err else "") + "."
                        + (f"  \n{len(_rf_needs_track)} Datei(en) benötigen Track-Nachkorrektur (siehe unten)." if _rf_needs_track else "")
                    )
                    if _rf_needs_track:
                        st.session_state["_retrofix_track_queue"] = _rf_needs_track
                    st.session_state.cmp_data = {}
                    st.session_state.pop("_detail_cache", None)
                except Exception as _rfe:
                    st.error(f"Nachkorrektur fehlgeschlagen: {_rfe}")

            # Track-Minimap re-run info (shown after retrofix identified candidates)
            _track_queue = list(st.session_state.get("_retrofix_track_queue") or [])
            if _track_queue:
                st.info(
                    f"**{len(_track_queue)} Datei(en)** benötigen Track-Minimap-Nachkorrektur "
                    f"(track_minimap_found war überall 0 → Bug behoben).  \n"
                    f"Da dies Video-Zugriff erfordert, bitte im **Watchdog-Tab** die Aufgabe "
                    f"**'Nachkorrektur'** aktivieren und den Watchdog starten."
                )

        # ── Button 2: Nur Plausibilität nachfiltern ───────────────────────────
        with _nc2:
            st.markdown("**Nur Plausibilität nachfiltern**")
            st.caption("Nur Min/Max + Steigung auf cleaned anwenden. Kein Trimmen, keine Track-Neuberechnung.")
            if st.button(
                f"Alle {len(_result_json_paths)} Dateien nachfiltern",
                disabled=not _result_json_paths,
                key="lib_reclean_btn",
            ):
                try:
                    from app_tabs.plausibility_filter import reclean_result_json
                    from app_tabs.roi_catalog_tab import load_catalog as _lc_lib
                    _rc_catalog = st.session_state.get("roi_catalog") or _lc_lib()
                    _rc_ok, _rc_skip, _rc_err = 0, 0, 0
                    _prog = st.progress(0.0, text="Nachfiltern läuft…")
                    for _ri, _rp in enumerate(_result_json_paths):
                        _ok, _msg = reclean_result_json(_rp, _rc_catalog)
                        if _ok:
                            _rc_ok += 1
                        elif any(x in _msg for x in ("keine Tabelle", "kein ocr", "kein recordResult")):
                            _rc_skip += 1
                        else:
                            _rc_err += 1
                        _prog.progress((_ri + 1) / len(_result_json_paths),
                                       text=f"Nachfiltern… {_ri+1}/{len(_result_json_paths)}")
                    _prog.empty()
                    st.success(
                        f"Fertig: {_rc_ok} gefiltert, {_rc_skip} ohne Daten übersprungen"
                        + (f", {_rc_err} Fehler" if _rc_err else "") + "."
                    )
                    st.session_state.cmp_data = {}
                    st.session_state.pop("_detail_cache", None)
                except Exception as _rce:
                    st.error(f"Nachfiltern fehlgeschlagen: {_rce}")

    # ── Analyse-Übersicht ─────────────────────────────────────────────────────
    _render_media_analysis(rows)

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
        "ROI n.v.":      st.column_config.TextColumn("ROI n.v.", width="small"),
        "Fehlerhaft":    st.column_config.TextColumn("Fehlerhaft", width="small"),
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

    _hdr_c1, _hdr_c2 = st.columns([6, 1])
    _hdr_c1.markdown(f"**Ausgewählt:** `{sel_row['folder']}` — {sel_row['title'] or '(kein Titel)'}")

    # ── Löschen ───────────────────────────────────────────────────────────────
    _del_key = f"lib_del_confirm_{sel_row['folder']}"
    if _hdr_c2.button("🗑 Löschen", key="lib_del_btn", type="secondary"):
        st.session_state[_del_key] = True

    if st.session_state.get(_del_key):
        _del_folder = sel_row["folder"]
        _del_items: list[str] = []
        if sel_row.get("json_exists"):
            _del_items.append(f"results_{_del_folder}.json")
        if sel_row.get("mat_exists"):
            _del_items.append(f"results_{_del_folder}.mat")
        if sel_row.get("video_exists") or sel_row.get("audio_exists"):
            _del_items.append(f"captures/{_del_folder}/ (Video + Audio)")
        _del_items.append("DB-Eintrag")
        with st.container(border=True):
            st.warning(
                "**Folgende Dateien werden unwiderruflich gelöscht:**  \n"
                + "  \n".join(f"• {x}" for x in _del_items)
            )
            _conf_c1, _conf_c2 = st.columns(2)
            if _conf_c1.button("✓ Ja, löschen", key="lib_del_confirm_btn", type="primary"):
                _deleted, _errors = _delete_row(base, _del_folder, sel_row.get("youtube_link", ""))
                st.session_state.pop(_del_key, None)
                st.session_state.pop("_detail_cache", None)
                st.session_state.cmp_data = {}
                if _errors:
                    st.error(f"Fehler: {'; '.join(_errors)}")
                else:
                    st.success(f"Gelöscht: {', '.join(_deleted)}")
                st.rerun()
            if _conf_c2.button("✗ Abbrechen", key="lib_del_cancel_btn"):
                st.session_state.pop(_del_key, None)
                st.rerun()

    def _scalar(v, default: float = 0.0) -> float:
        """Unwrap single-element list/array from MAT conversion, then convert to float."""
        if isinstance(v, (list, tuple)):
            v = v[0] if v else default
        try:
            return float(v) if v is not None else default
        except Exception:
            return default

    def _parse_roi_table(roi_table) -> list[dict]:
        """Convert roi_table (list-of-dicts OR columnar dict) to list of normalized dicts."""
        def _coords_from_any(v) -> list[float]:
            if isinstance(v, (list, tuple)) and len(v) >= 4:
                return [_scalar(v[0]), _scalar(v[1]), _scalar(v[2]), _scalar(v[3])]
            txt = str(v or "").strip()
            if not txt:
                return [0.0, 0.0, 0.0, 0.0]
            try:
                nums = [float(x) for x in txt.replace(",", " ").replace(";", " ").split()]
                if len(nums) >= 4:
                    return [float(nums[0]), float(nums[1]), float(nums[2]), float(nums[3])]
            except Exception:
                pass
            return [0.0, 0.0, 0.0, 0.0]

        out: list[dict] = []
        if isinstance(roi_table, list):
            for r in roi_table:
                if not isinstance(r, dict):
                    continue
                nr: dict = {}
                for k, v in r.items():
                    nr[k] = v[0] if isinstance(v, (list, tuple)) and len(v) == 1 else v
                if all(f in nr for f in ("x", "y", "w", "h")):
                    for field in ("x", "y", "w", "h"):
                        nr[field] = _scalar(nr.get(field), 0.0)
                else:
                    cx, cy, cw, ch = _coords_from_any(nr.get("roi"))
                    nr["x"], nr["y"], nr["w"], nr["h"] = cx, cy, cw, ch
                if str(nr.get("name", "")).strip() == "":
                    nr["name"] = str(nr.get("name_roi", "roi") or "roi")
                nr.setdefault("name", "roi")
                nr.setdefault("fmt", "any")
                nr.setdefault("max_scale", 1.2)
                out.append(nr)

        elif isinstance(roi_table, dict):
            names = roi_table.get("name_roi") or roi_table.get("name") or []
            coords_list = roi_table.get("roi") or []
            fmts = roi_table.get("fmt") or []
            scales = roi_table.get("max_scale") or []
            if isinstance(names, tuple):
                names = list(names)
            if isinstance(coords_list, tuple):
                coords_list = list(coords_list)
            if isinstance(fmts, tuple):
                fmts = list(fmts)
            if isinstance(scales, tuple):
                scales = list(scales)
            if not isinstance(names, list):
                names = [names] if names not in (None, "") else []
            if not isinstance(coords_list, list):
                coords_list = [coords_list] if coords_list not in (None, "") else []
            if not isinstance(fmts, list):
                fmts = [fmts] if fmts not in (None, "") else []
            if not isinstance(scales, list):
                scales = [scales] if scales not in (None, "") else []
            for i, name in enumerate(names):
                coords = coords_list[i] if i < len(coords_list) else []
                x, y, w, h = _coords_from_any(coords)
                fmt_val = fmts[i] if i < len(fmts) else "any"
                scale_val = _scalar(scales[i], 1.2) if i < len(scales) else 1.2
                out.append({
                    "name": str(name),
                    "x": x, "y": y, "w": w, "h": h,
                    "fmt": str(fmt_val),
                    "max_scale": scale_val,
                })
        return out
    def _load_folder(folder: str, json_path_str: str) -> list[str]:
        """Load folder into session state (JSON + ROIs + video). Returns warnings."""
        msgs: list[str] = []
        st.session_state.capture_folder = folder
        _pending_rois: list[dict] = []
        _pending_t_start = None
        _pending_t_end = None
        _pending_ref_pts = None
        _pending_minimap_pts = None
        _pending_color_range = None

        def _json_candidates_for_folder() -> list[Path]:
            cands: list[Path] = []
            seen: set[str] = set()

            def _add(p: Path | None) -> None:
                if p is None:
                    return
                sp = str(p)
                if sp in seen:
                    return
                seen.add(sp)
                cands.append(p)

            if json_path_str:
                _add(Path(json_path_str))
            _add(_base() / "results" / f"results_{folder}.json")
            return cands

        def _read_json_doc(path: Path) -> dict:
            try:
                raw_text = path.read_text(encoding="utf-8", errors="ignore")
                doc = json.loads(raw_text)
                return doc if isinstance(doc, dict) else {}
            except Exception:
                return {}

        def _extract_roi_info(doc: dict) -> tuple[list[dict], int, int]:
            rr = {}
            if isinstance(doc, dict):
                rr = doc.get("recordResult")
                if not isinstance(rr, dict):
                    rr = doc.get("recordresult")
            if not isinstance(rr, dict):
                rr = {}
            ocr = rr.get("ocr")
            if not isinstance(ocr, dict):
                ocr = rr.get("OCR")
            if not isinstance(ocr, dict):
                ocr = {}
            if not isinstance(ocr, dict):
                ocr = {}
            roi_src = ocr.get("roi_table")
            if not roi_src:
                roi_src = ocr.get("roi_table_raw")
            parsed_rois = _parse_roi_table(roi_src)
            n_all = len(parsed_rois)
            n_ocr = sum(
                1
                for r in parsed_rois
                if str(r.get("name", "")).strip().lower() != "track_minimap"
                and _scalar(r.get("w")) > 0
                and _scalar(r.get("h")) > 0
            )
            return parsed_rois, n_ocr, n_all

        def _parse_pts(v) -> list[list[float]]:
            if not isinstance(v, (list, tuple)):
                return []
            if v and isinstance(v[0], (list, tuple)) and len(v[0]) >= 2:
                out = []
                for p in v:
                    try:
                        out.append([float(p[0]), float(p[1])])
                    except Exception:
                        pass
                return out
            vals = []
            for x in v:
                try:
                    vals.append(float(x))
                except Exception:
                    pass
            out = []
            for i in range(0, len(vals) - 1, 2):
                out.append([vals[i], vals[i + 1]])
            return out

        best_doc: dict = {}
        best_rois: list[dict] = []
        best_path = ""
        best_n_ocr = -1
        best_n_all = -1
        for cand in _json_candidates_for_folder():
            if not cand.exists():
                continue
            doc = _read_json_doc(cand)
            rois, n_ocr, n_all = _extract_roi_info(doc)
            if (n_ocr > best_n_ocr) or (n_ocr == best_n_ocr and n_all > best_n_all):
                best_doc = doc
                best_rois = rois
                best_path = str(cand)
                best_n_ocr = n_ocr
                best_n_all = n_all
        doc = best_doc if isinstance(best_doc, dict) else {}
        if best_path:
            st.session_state["mat_selected_key"] = best_path
        elif json_path_str:
            msgs.append(f"JSON fehlt/nicht lesbar: {json_path_str}")

        try:
            rr = doc.get("recordResult") if isinstance(doc, dict) else {}
            if not isinstance(rr, dict) and isinstance(doc, dict):
                rr = doc.get("recordresult")
            if not isinstance(rr, dict):
                rr = {}
            ocr = rr.get("ocr")
            if not isinstance(ocr, dict):
                ocr = rr.get("OCR")
            if not isinstance(ocr, dict):
                ocr = {}
            if not isinstance(ocr, dict):
                ocr = {}

            if best_rois:
                _pending_rois = list(best_rois)
            elif best_path:
                roi_table = ocr.get("roi_table") or ocr.get("roi_table_raw")
                msgs.append(f"roi_table: kein ROI gefunden (type={type(roi_table).__name__}, val={str(roi_table)[:80]})")

            params = ocr.get("params") or {}
            if isinstance(params, dict):
                if "start_s" in params:
                    _pending_t_start = _scalar(params.get("start_s", 0.0))
                if "end_s" in params:
                    _pending_t_end = _scalar(params.get("end_s", 0.0))

            trk = ocr.get("trkCalSlim") if isinstance(ocr.get("trkCalSlim"), dict) else {}
            if isinstance(trk, dict):
                _rp = _parse_pts((trk.get("ref_pts") if isinstance(trk.get("ref_pts"), (list, tuple)) else None) or trk.get("ptsRef"))
                _mp = _parse_pts((trk.get("minimap_pts") if isinstance(trk.get("minimap_pts"), (list, tuple)) else None) or trk.get("ptsMini"))
                if _rp:
                    _pending_ref_pts = _rp
                if _mp:
                    _pending_minimap_pts = _mp
                if isinstance(trk.get("moving_pt_color_range"), dict):
                    _pending_color_range = dict(trk.get("moving_pt_color_range") or {})
                elif trk.get("marker") is not None:
                    marker_to_cr = globals().get("_marker_to_color_range")
                    if callable(marker_to_cr):
                        try:
                            _cr = marker_to_cr(trk.get("marker"))
                            if isinstance(_cr, dict) and _cr:
                                _pending_color_range = _cr
                        except Exception:
                            pass

        except Exception as e:
            msgs.append(f"JSON verarbeiten: {e}")

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

        # Important: apply loaded OCR config AFTER video load.
        # _apply_video() resets rois/t_start/t_end; writing here keeps loaded values.
        if _pending_rois:
            st.session_state.rois = _pending_rois
        if _pending_t_start is not None:
            st.session_state.t_start = float(_pending_t_start)
        if _pending_t_end is not None:
            st.session_state.t_end = float(_pending_t_end)
        if isinstance(_pending_ref_pts, list) and _pending_ref_pts:
            st.session_state.ref_track_pts = _pending_ref_pts
        if isinstance(_pending_minimap_pts, list) and _pending_minimap_pts:
            st.session_state.minimap_pts = _pending_minimap_pts
            st.session_state.minimap_next_pt_idx = len(_pending_minimap_pts)
        if isinstance(_pending_color_range, dict) and _pending_color_range:
            st.session_state.moving_pt_color_range = _pending_color_range

        return msgs

    can_load = sel_row["json_exists"] or sel_row["video_exists"] or sel_row["audio_exists"]
    ra1, ra2, ra3, ra4 = st.columns(4)

    # ── Laden (JSON + ROIs + Video) ────────────────────────────────────────────
    if ra1.button("Laden", disabled=not can_load,
                  use_container_width=True, key="lib_load_btn", type="primary"):
        msgs = _load_folder(sel_row["folder"], sel_row["json_path"])
        for m in msgs:
            st.warning(m)
        rois_now = st.session_state.get("rois") or []
        n_ocr = sum(1 for r in rois_now if str(r.get("name", "")).strip().lower() != "track_minimap"
                    and _scalar(r.get("w")) > 0 and _scalar(r.get("h")) > 0)
        st.success(
            f"Geladen: **{sel_row['folder']}** — "
            f"{n_ocr} OCR-ROI(s) geladen. Jetzt Tab **ROI Setup**, **Video OCR Full** oder **Audio Auswertung** öffnen."
        )

    # ── MAT→JSON (nur diese Zeile) ─────────────────────────────────────────────
    if ra2.button("MAT→JSON",
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
    if ra3.button("Video herunterladen",
                  disabled=not has_link or (sel_row["video_exists"] and sel_row["audio_exists"]
                                             and not sel_row["video_faulty"]),
                  use_container_width=True, key="lib_row_dl_btn"):
        _write_db_entry(sel_row["youtube_link"], sel_row["folder"], sel_row["title"])
        _update_db_status(sel_row["folder"], sel_row["youtube_link"], "pending", "")
        st.session_state.yt_watchdog_task_download = True
        st.session_state.yt_watchdog_cmd = "start"
        st.info("Download wird vom Watchdog gestartet.")

    # ── Details ────────────────────────────────────────────────────────────────
    with ra4:
        with st.expander("Details", expanded=False):
            display = {k: v for k, v in sel_row.items() if k not in ("duration",)}
            st.json(display)

