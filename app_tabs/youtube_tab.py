"""YouTube download management tab using scripts/record_youtube_cfr.py."""


from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path

from core.watchdog_state import _YT_WATCHDOG, _YT_WATCHDOG_LOCK, _JSON_ROW_CACHE, get_path_lock


def watchdog_snapshot() -> dict:
    with _YT_WATCHDOG_LOCK:
        th = _YT_WATCHDOG.get("thread")
        running = bool(_YT_WATCHDOG.get("running")) and th is not None and th.is_alive()
        if not running:
            _YT_WATCHDOG["running"] = False
        ocr_live = dict(_YT_WATCHDOG.get("ocr_live") or {})
        return {
            "running": running,
            "interval_sec": int(_YT_WATCHDOG.get("interval_sec", 10) or 10),
            "last_tick": str(_YT_WATCHDOG.get("last_tick") or ""),
            "current": str(_YT_WATCHDOG.get("current") or ""),
            "downloads": int(_YT_WATCHDOG.get("downloads", 0) or 0),
            "ocr": int(_YT_WATCHDOG.get("ocr", 0) or 0),
            "mat_json": int(_YT_WATCHDOG.get("mat_json", 0) or 0),
            "errors": int(_YT_WATCHDOG.get("errors", 0) or 0),
            "tasks": dict(_YT_WATCHDOG.get("tasks") or {}),
            "logs": list(_YT_WATCHDOG.get("logs") or []),  # snapshot deque as list
            "ocr_live": ocr_live,
        }


def render(ns):
    globals().update(ns)
    st.markdown('<div class="section-title">YouTube Download Manager</div>', unsafe_allow_html=True)
    st.caption("Rein Python: Download über scripts/record_youtube_cfr.py (kein MATLAB, kein yt-dlp im App-Flow).")
    st.session_state.setdefault("yt_open_new_window", True)
    st.session_state.setdefault("yt_move_other_display", False)
    w1, w2 = st.columns(2)
    st.session_state.yt_open_new_window = bool(
        w1.checkbox("YouTube in neuem Fenster öffnen", value=bool(st.session_state.get("yt_open_new_window", True)))
    )
    st.session_state.yt_move_other_display = bool(
        w2.checkbox("Fenster auf anderes Display verschieben", value=bool(st.session_state.get("yt_move_other_display", False)))
    )

    db_path = Path("logs") / "youtube_download_table.json"
    rec_script = Path("scripts") / "record_youtube_cfr.py"

    def _read_db() -> list[dict]:
        try:
            if not db_path.exists():
                return []
            raw = json.loads(db_path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                return [dict(x) for x in raw if isinstance(x, dict)]
        except Exception:
            pass
        return []

    def _write_db(rows: list[dict]) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    def _capture_base(base_override=None) -> Path:
        if base_override is not None:
            lp = str(base_override).strip()
        else:
            lp = str(st.session_state.get("local_base_path") or "").strip()
        if lp:
            return Path(lp).expanduser().resolve()
        return Path.cwd()

    st.caption(f"JSON-Zielpfad: {_capture_base() / 'results'}")
    st.caption(f"Video/Audio-Zielpfad: {_capture_base() / 'captures' / '<capture_folder>'}")
    st.session_state.setdefault("yt_last_meta_json_path", "")

    def _parse_result_lines(output: str) -> dict:
        out = {}
        pending_key = ""
        for line in (output or "").splitlines():
            t = line.strip()
            if t.startswith("RESULT_") and ":" in t:
                k, v = t.split(":", 1)
                key = k.strip()
                val = v.strip()
                if key == "RESULT_META_JSON":
                    try:
                        meta_payload = json.loads(val)
                        if isinstance(meta_payload, dict):
                            if str(meta_payload.get("title") or "").strip():
                                out["RESULT_TITLE"] = str(meta_payload.get("title") or "")
                            if str(meta_payload.get("pubDate") or "").strip():
                                out["RESULT_PUBDATE"] = str(meta_payload.get("pubDate") or "")
                            if str(meta_payload.get("desc") or "").strip():
                                out["RESULT_DESC"] = str(meta_payload.get("desc") or "")
                            if str(meta_payload.get("chanName") or "").strip():
                                out["RESULT_CHANNAME"] = str(meta_payload.get("chanName") or "")
                    except Exception:
                        pass
                out[key] = val
                pending_key = key if key in {"RESULT_DESC", "RESULT_TITLE", "RESULT_PUBDATE", "RESULT_CHANNAME"} else ""
                continue
            if pending_key and t and (not t.startswith("[")) and (not t.startswith("RESULT_")):
                out[pending_key] = str(out.get(pending_key) or "") + "\n" + t
                continue
            pending_key = ""
        return out

    def _fetch_metadata_for_url(url: str) -> dict:
        url = str(url or "").strip()
        if (not url) or (not rec_script.exists()):
            return {}
        cmd = [sys.executable, str(rec_script), "--url", url, "--duration", "1", "--metadata-only"]
        run_kwargs = {
            "capture_output": True,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
        }
        if os.name == "nt":
            run_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0
            run_kwargs["startupinfo"] = si
        try:
            p = subprocess.run(cmd, **run_kwargs)
            txt = (p.stdout or "") + "\n" + (p.stderr or "")
            parsed = _parse_result_lines(txt)
            return {
                "title": str(parsed.get("RESULT_TITLE") or "").strip(),
                "pubDate": str(parsed.get("RESULT_PUBDATE") or "").strip(),
                "desc": str(parsed.get("RESULT_DESC") or "").strip(),
                "chanName": str(parsed.get("RESULT_CHANNAME") or "").strip(),
            }
        except Exception:
            return {}

    def _default_capture_folder() -> str:
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    def _capture_media_paths(folder: str, base_override=None) -> tuple[Path, Path]:
        """Return (video_path, audio_path) for a capture folder.

        Canonical output paths for new downloads:
          screen_{folder}_video.avi  — video
          screen_{folder}_audio.wav  — audio

        For existence checks use _find_existing_media() which also recognises
        alternative extensions (mp4, mp3, etc.).
        """
        folder = str(folder or "").strip()
        cap_dir = _capture_base(base_override=base_override) / "captures" / folder
        return cap_dir / f"screen_{folder}_video.avi", cap_dir / f"screen_{folder}_audio.wav"

    def _find_existing_media(folder: str, base_override=None) -> tuple[Path | None, Path | None]:
        """Return (video, audio) paths for any existing media in the capture folder.

        Checks canonical names first, then falls back to any supported extension.
        Returns None for each component that is missing or empty.
        """
        folder = str(folder or "").strip()
        cap_dir = _capture_base(base_override=base_override) / "captures" / folder
        stem = f"screen_{folder}"

        video_exts = [".avi", ".mp4", ".mkv", ".mov"]
        audio_exts = [".wav", ".mp3", ".m4a", ".aac", ".flac"]

        def _pick(exts: list[str]) -> Path | None:
            # Prefer canonical stem, then any file with matching extension
            for ext in exts:
                p = cap_dir / f"{stem}_video{ext}" if ext in video_exts else cap_dir / f"{stem}_audio{ext}"
                if p.exists() and p.stat().st_size > 0:
                    return p
            # Fallback: any file in the folder with a matching extension
            if cap_dir.exists():
                for ext in exts:
                    for p in cap_dir.glob(f"*{ext}"):
                        if p.stat().st_size > 0:
                            return p
            return None

        def _pick_video() -> Path | None:
            for ext in video_exts:
                p = cap_dir / f"{stem}_video{ext}"
                if p.exists() and p.stat().st_size > 0:
                    return p
            if cap_dir.exists():
                for ext in video_exts:
                    for p in cap_dir.glob(f"*{ext}"):
                        if p.stat().st_size > 0:
                            return p
            return None

        def _pick_audio() -> Path | None:
            for ext in audio_exts:
                p = cap_dir / f"{stem}_audio{ext}"
                if p.exists() and p.stat().st_size > 0:
                    return p
            if cap_dir.exists():
                for ext in audio_exts:
                    for p in cap_dir.glob(f"*{ext}"):
                        if p.stat().st_size > 0:
                            return p
            return None

        return _pick_video(), _pick_audio()

    def _capture_media_stem(folder: str) -> str:
        """Base name passed as --out to the recording script.
        The script appends _video.avi and _audio.wav to this stem.
        """
        folder = str(folder or "").strip()
        return f"screen_{folder}"

    def _resolve_media_path_value(raw_path, *, base_override=None) -> Path | None:
        txt = str(raw_path or "").strip()
        if not txt:
            return None
        base = _capture_base(base_override=base_override)
        p = Path(txt)
        cands: list[Path] = []
        if p.is_absolute():
            cands.append(p)
        cands.append(base / p)
        for cp in cands:
            try:
                rp = cp.expanduser().resolve()
            except Exception:
                rp = cp
            try:
                if rp.exists() and rp.is_file() and rp.stat().st_size > 0:
                    return rp
            except Exception:
                continue
        return None

    def _detect_capture_media(folder: str, meta: dict | None = None, *, base_override=None) -> tuple[bool, bool, Path | None, Path | None]:
        folder = str(folder or "").strip()
        out_video, out_audio = _capture_media_paths(folder, base_override=base_override)
        cap_dir = out_video.parent

        found_video = out_video if out_video.exists() and out_video.stat().st_size > 0 else None
        found_audio = out_audio if out_audio.exists() and out_audio.stat().st_size > 0 else None

        if isinstance(meta, dict):
            if found_video is None:
                found_video = _resolve_media_path_value(meta.get("video") or meta.get("video_name"), base_override=base_override)
            if found_audio is None:
                found_audio = _resolve_media_path_value(meta.get("audio"), base_override=base_override)

        video_exts = tuple(globals().get("VIDEO_EXTS") or (".mp4", ".mov", ".avi", ".mkv"))
        audio_exts = tuple(globals().get("AUDIO_EXTS") or (".wav", ".mp3", ".m4a", ".aac", ".flac"))

        if cap_dir.exists() and cap_dir.is_dir():
            files = [p for p in cap_dir.iterdir() if p.is_file()]
            if found_video is None:
                vids = [p for p in files if p.suffix.lower() in video_exts and "_1fps" not in p.name.lower() and p.stat().st_size > 0]
                if vids:
                    found_video = max(vids, key=lambda p: p.stat().st_size)
            if found_audio is None:
                auds = [p for p in files if p.suffix.lower() in audio_exts and p.stat().st_size > 0]
                if auds:
                    found_audio = max(auds, key=lambda p: p.stat().st_size)

        return bool(found_video), bool(found_audio), found_video, found_audio

    def _rows_from_results_json() -> list[dict]:
        out: list[dict] = []
        res_dir = _capture_base() / "results"
        if not res_dir.exists():
            return out
        for jp in sorted(res_dir.glob("results_*.json")):
            try:
                mtime = jp.stat().st_mtime
                cache_key = str(jp)
                cached = _JSON_ROW_CACHE.get(cache_key)
                if cached is not None and cached[0] == mtime:
                    out.append(cached[1])
                    continue
                doc = json.loads(jp.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                continue
            rr = doc.get("recordResult") if isinstance(doc, dict) else {}
            meta = rr.get("metadata") if isinstance(rr, dict) and isinstance(rr.get("metadata"), dict) else {}
            if not isinstance(meta, dict):
                meta = {}
            cf = jp.stem.replace("results_", "", 1).strip()
            url = str(meta.get("url") or meta.get("youtube_url") or meta.get("link") or "").strip()
            title = str(meta.get("title") or meta.get("video_title") or "").strip()
            pub = str(meta.get("pubDate") or meta.get("upload_date") or "").strip()
            has_v, has_a, _fv, _fa = _detect_capture_media(cf, meta)
            dl_status = "downloaded" if (has_v and has_a) else "pending"
            if has_v and not has_a:
                dl_status = "error"
            row = {
                "youtube_link": url,
                "title": title,
                "upload_date": pub,
                "capture_folder": cf,
                "download_status": dl_status,
                "last_error": "" if dl_status != "error" else "audio fehlt",
                "downloaded_at": str(meta.get("created_at") or ""),
                "json_path": str(jp),
            }
            _JSON_ROW_CACHE[cache_key] = (mtime, row)
            out.append(row)
        return out

    def _merge_rows_with_results_json(rows: list[dict]) -> tuple[list[dict], bool]:
        rows_in = [dict(r) for r in (rows or []) if isinstance(r, dict)]
        merged = list(rows_in)
        changed = False
        by_cf = {str(r.get("capture_folder") or "").strip(): i for i, r in enumerate(merged) if str(r.get("capture_folder") or "").strip()}
        by_url = {str(r.get("youtube_link") or "").strip(): i for i, r in enumerate(merged) if str(r.get("youtube_link") or "").strip()}
        for jr in _rows_from_results_json():
            cf = str(jr.get("capture_folder") or "").strip()
            url = str(jr.get("youtube_link") or "").strip()
            idx = by_cf.get(cf, None) if cf else None
            if idx is None and url:
                idx = by_url.get(url, None)
            if idx is None:
                merged.append(dict(jr))
                idx = len(merged) - 1
                changed = True
            else:
                cur = dict(merged[idx])
                for k in ("youtube_link", "title", "upload_date", "capture_folder", "json_path", "download_status", "downloaded_at"):
                    nv = jr.get(k)
                    if str(nv or "").strip() and str(cur.get(k) or "").strip() != str(nv):
                        cur[k] = nv
                        changed = True
                if str(jr.get("download_status") or "") == "downloaded" and str(cur.get("download_status") or "") != "downloaded":
                    cur["download_status"] = "downloaded"
                    cur["last_error"] = ""
                    changed = True
                merged[idx] = cur
            by_cf[str(merged[idx].get("capture_folder") or "").strip()] = idx
            if str(merged[idx].get("youtube_link") or "").strip():
                by_url[str(merged[idx].get("youtube_link") or "").strip()] = idx
        return merged, changed

    def _write_capture_metadata_json(folder: str, meta: dict, *, base_override=None, quiet: bool = False) -> tuple[bool, str]:
        folder = str(folder or "").strip()
        if not folder:
            return False, "capture_folder fehlt"
        base = _capture_base(base_override=base_override)
        res_dir = base / "results"
        res_dir.mkdir(parents=True, exist_ok=True)
        out_video, out_audio = _capture_media_paths(folder, base_override=base_override)
        cap_dir = out_video.parent
        fps_v = float(meta.get("fps") or 0.0)
        duration_v = float(meta.get("duration") or 0.0)
        if out_video.exists():
            try:
                cap = cv2.VideoCapture(str(out_video))
                if cap.isOpened():
                    fps_probe = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
                    fc_probe = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
                    if fps_v <= 0 and fps_probe > 0:
                        fps_v = fps_probe
                    if duration_v <= 0 and fps_probe > 0 and fc_probe > 0:
                        duration_v = fc_probe / fps_probe
                cap.release()
            except Exception:
                pass
        if fps_v <= 0:
            fps_v = 30.0
        if duration_v <= 0:
            duration_v = 86400.0
        title_v = str(meta.get("title") or meta.get("video_title") or "")
        url_v = str(meta.get("url") or meta.get("youtube_url") or "")
        created_at_v = str(meta.get("created_at") or datetime.now().isoformat(timespec="seconds"))
        audio_v = str(meta.get("audio") or (str(out_audio) if out_audio.exists() else ""))
        video_v = str(meta.get("video") or meta.get("video_name") or out_video.name)
        outdir_v = str(meta.get("outdir") or cap_dir)
        pub_v = str(meta.get("pubDate") or meta.get("upload_date") or "")
        desc_v = str(meta.get("desc") or "")
        chan_v = str(meta.get("chanName") or meta.get("channel_name") or "")
        new_metadata = {
            "title": title_v,
            "video": video_v,
            "audio": audio_v,
            "url": url_v,
            "created_at": created_at_v,
            "outdir": outdir_v,
            "fps": float(fps_v),
            "duration": float(duration_v),
            "pubDate": pub_v,
            "desc": desc_v,
            "chanName": chan_v,
        }
        path = res_dir / f"results_{folder}.json"
        # Merge: preserve all existing data (OCR, ROI, etc.) — only update metadata section.
        existing: dict = {}
        if path.exists():
            try:
                raw_existing = path.read_text(encoding="utf-8", errors="replace")
                existing = json.loads(raw_existing)
                if not isinstance(existing, dict):
                    existing = {}
                else:
                    # Backup before overwriting — keeps the last known-good state.
                    try:
                        path.with_suffix(".json.bak").write_text(raw_existing, encoding="utf-8")
                    except Exception:
                        pass
            except Exception:
                existing = {}
        record = existing.get("recordResult") if isinstance(existing.get("recordResult"), dict) else {}
        record["metadata"] = new_metadata
        existing["recordResult"] = record
        path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
        if not path.exists():
            return False, f"JSON nicht geschrieben: {path}"
        if not quiet:
            st.session_state.yt_last_meta_json_path = str(path)
            set_status(f"JSON gespeichert: {path}", "ok")
        return True, str(path)

    def _ensure_audio_file(folder: str, base_override=None) -> tuple[bool, str]:
        from core.watchdog_state import _AUDIO_SILENCE_CACHE
        _, out_audio = _find_existing_media(folder, base_override=base_override)
        if out_audio is None:
            return False, "audio fehlt (wav/mp3/m4a)"
        key = str(out_audio)
        try:
            mtime = out_audio.stat().st_mtime
        except Exception:
            mtime = 0.0
        if key in _AUDIO_SILENCE_CACHE and _AUDIO_SILENCE_CACHE[key][0] == mtime:
            is_silent = _AUDIO_SILENCE_CACHE[key][1]
        else:
            try:
                import soundfile as sf
                import numpy as np
                peak = 0.0
                with sf.SoundFile(key) as wav:
                    sr = wav.samplerate
                    total = wav.frames
                    check_s = sr  # 1 s per sample point
                    for pos in [0, max(0, total // 2 - check_s // 2), max(0, total - check_s)]:
                        wav.seek(pos)
                        chunk = wav.read(frames=check_s, dtype="float32", always_2d=True)
                        if chunk.size:
                            peak = max(peak, float(np.abs(chunk).max()))
                is_silent = peak < 0.01
            except Exception as e:
                return False, f"audio.wav nicht lesbar: {e}"
            _AUDIO_SILENCE_CACHE[key] = (mtime, is_silent)
        if is_silent:
            return False, "audio.wav ist stumm – Loopback-Gerät prüfen"
        return True, str(out_audio)

    def _download_one(
        entry: dict,
        force: bool = False,
        *,
        base_override=None,
        open_new_window: bool | None = None,
        move_other_display: bool | None = None,
        stop_event=None,
    ) -> tuple[bool, str, dict]:
        url = str(entry.get("youtube_link") or "").strip()
        if not url:
            return False, "leerer link", {}
        if not rec_script.exists():
            return False, f"Script fehlt: {rec_script}", {}

        folder = str(entry.get("capture_folder") or "").strip()
        if not folder:
            folder = _default_capture_folder()
        out_video, out_audio = _capture_media_paths(folder, base_override=base_override)
        cap_dir = out_video.parent
        cap_dir.mkdir(parents=True, exist_ok=True)
        _ex_vid, _ex_aud = _find_existing_media(folder, base_override=base_override)
        _aud_already_ok, _ = _ensure_audio_file(folder, base_override=base_override)
        if (not force) and _ex_vid is not None and _aud_already_ok:
            return True, "bereits vorhanden", {"RESULT_VIDEO": str(_ex_vid), "RESULT_AUDIO": str(_ex_aud or out_audio)}

        for _stale in (out_video, out_audio):
            if _stale.exists():
                try:
                    _stale.unlink()
                except Exception:
                    pass

        cmd = [
            sys.executable,
            str(rec_script),
            "--url",
            url,
            "--duration",
            "86400",
            "--out",
            _capture_media_stem(folder),
            "--outdir",
            str(cap_dir),
        ]
        use_new_window = bool(st.session_state.get("yt_open_new_window", True)) if open_new_window is None else bool(open_new_window)
        use_other_display = bool(st.session_state.get("yt_move_other_display", False)) if move_other_display is None else bool(move_other_display)
        if use_new_window:
            cmd.append("--new-window")
        if use_other_display:
            cmd.append("--other-display")
        log_dir = Path("logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"yt_job_{folder}_{int(time.time())}.log"
        popen_kwargs: dict = {
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
        }
        if os.name == "nt":
            popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0
            popen_kwargs["startupinfo"] = si
        with log_file.open("w", encoding="utf-8") as lf:
            popen_kwargs["stdout"] = lf
            popen_kwargs["stderr"] = lf
            p = subprocess.Popen(cmd, **popen_kwargs)
        # Poll every 2 s so stop_event can interrupt a running download.
        while True:
            try:
                rc = p.wait(timeout=2)
                break
            except subprocess.TimeoutExpired:
                if stop_event is not None and stop_event.is_set():
                    p.terminate()
                    try:
                        p.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        p.kill()
                    return False, "Download abgebrochen (Watchdog gestoppt)", {}
        try:
            txt = log_file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            txt = ""
        parsed = _parse_result_lines(txt)
        if rc != 0:
            return False, txt.strip()[-500:], parsed

        src_v = str(parsed.get("RESULT_VIDEO") or "").strip()
        src_a = str(parsed.get("RESULT_AUDIO") or "").strip()
        if src_v and Path(src_v).exists():
            try:
                src_vp = Path(src_v).resolve()
                out_vp = out_video.resolve()
                if src_vp != out_vp:
                    Path(src_v).replace(out_video)
            except Exception:
                pass
        if src_a and Path(src_a).exists():
            try:
                src_ap = Path(src_a).resolve()
                out_ap = out_audio.resolve()
                if src_ap != out_ap:
                    Path(src_a).replace(out_audio)
            except Exception:
                pass
        if out_video.exists() and (not out_audio.exists() or out_audio.stat().st_size <= 0):
            ok_aud, msg_aud = _ensure_audio_file(folder, base_override=base_override)
            if not ok_aud:
                return False, f"audio fehlt: {msg_aud}", parsed
        if not out_video.exists() or not out_audio.exists():
            return False, "video/audio nicht vollständig erzeugt", parsed
        return True, "ok", parsed

    def _status_lamp(s: str) -> str:
        t = str(s or "").strip().lower()
        led_green = "\U0001F7E2"
        led_red = "\U0001F534"
        led_yellow = "\U0001F7E1"
        led_white = "\u26AA"
        if t == "downloaded":
            return f"{led_green} Ja"
        if t == "error":
            return f"{led_red} Fehler"
        if t == "downloading":
            return f"{led_yellow} L\u00e4uft"
        return f"{led_white} Nein"

    def _wd_log(msg: str) -> None:
        txt = str(msg or "").strip()
        if not txt:
            return
        line = f"{datetime.now().strftime('%H:%M:%S')} | {txt}"
        with _YT_WATCHDOG_LOCK:
            _YT_WATCHDOG["logs"].append(line)  # deque(maxlen=200) — kein manuelles Slicing
            _YT_WATCHDOG["last_tick"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            log_path = Path(str(st.session_state.get("local_base_path") or ".")).expanduser().resolve() / "logs" / "watchdog.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as _f:
                _f.write(line + "\n")
        except Exception:
            pass

    def _wd_set_current(step: str) -> None:
        with _YT_WATCHDOG_LOCK:
            _YT_WATCHDOG["current"] = str(step or "")
            _YT_WATCHDOG["last_tick"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _wd_inc(counter: str) -> None:
        with _YT_WATCHDOG_LOCK:
            _YT_WATCHDOG[counter] = int(_YT_WATCHDOG.get(counter, 0) or 0) + 1
            _YT_WATCHDOG["last_tick"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _wd_update_row(link: str, patch: dict) -> dict | None:
        link = str(link or "").strip()
        if not link:
            return None
        rows_now = _read_db()
        for i, row in enumerate(rows_now):
            if str(row.get("youtube_link") or "").strip() != link:
                continue
            row2 = dict(row)
            row2.update(dict(patch or {}))
            rows_now[i] = row2
            _write_db(rows_now)
            return row2
        return None

    def _wd_json_path(folder: str, base_override=None) -> Path:
        base = _capture_base(base_override=base_override)
        return base / "results" / f"results_{folder}.json"

    def _wd_load_json(path: Path) -> dict:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw
        except Exception:
            pass
        return {}

    def _wd_is_video_faulty(json_file: Path) -> bool:
        """Return True if the results JSON marks the video as fehlerhaft."""
        if not json_file.exists():
            return False
        try:
            doc = json.loads(json_file.read_text(encoding="utf-8", errors="replace"))
            rr = doc.get("recordResult") if isinstance(doc, dict) else None
            if not isinstance(rr, dict):
                return False
            meta = rr.get("metadata") if isinstance(rr.get("metadata"), dict) else {}
            ocr  = rr.get("ocr")      if isinstance(rr.get("ocr"),      dict) else {}
            def _truthy(v) -> bool:
                if isinstance(v, bool): return v
                return str(v).strip().lower() in ("true", "1", "ja", "yes")
            if _truthy(meta.get("video_faulty")) or _truthy(ocr.get("video_faulty")):
                return True
            if "video_fehlerhaft" in str(meta.get("video_status") or "").lower():
                return True
            if "video_fehlerhaft" in str(ocr.get("video_status") or "").lower():
                return True
        except Exception:
            pass
        return False

    def _wd_clear_video_faulty_in_json(json_file: Path) -> None:
        """Remove video_faulty / video_status flags from metadata and ocr sections."""
        if not json_file.exists():
            return
        try:
            doc = json.loads(json_file.read_text(encoding="utf-8", errors="replace"))
            if not isinstance(doc, dict):
                return
            rr = doc.get("recordResult")
            if not isinstance(rr, dict):
                return
            changed = False
            for section in ("metadata", "ocr"):
                s = rr.get(section)
                if isinstance(s, dict):
                    for field in ("video_faulty", "video_status", "video_note", "video_stamped_at"):
                        if field in s:
                            del s[field]
                            changed = True
            if changed:
                json_file.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _wd_extract_ocr_rois(doc: dict) -> tuple[list[dict], bool]:
        rr = doc.get("recordResult") if isinstance(doc, dict) else {}
        if not isinstance(rr, dict):
            return [], False
        ocr = rr.get("ocr") if isinstance(rr.get("ocr"), dict) else {}
        roi_table = ocr.get("roi_table") if isinstance(ocr, dict) else []

        def _parse_rect(v):
            if isinstance(v, (tuple, list)) and len(v) >= 4:
                try:
                    return [float(v[0]), float(v[1]), float(v[2]), float(v[3])]
                except Exception:
                    return None
            txt = str(v or "").strip()
            if not txt:
                return None
            try:
                nums = [float(x) for x in txt.replace(",", " ").replace(";", " ").split()]
                if len(nums) >= 4:
                    return [float(nums[0]), float(nums[1]), float(nums[2]), float(nums[3])]
            except Exception:
                return None
            return None

        if isinstance(roi_table, dict):
            cols = {str(k): v for k, v in roi_table.items() if isinstance(v, list)}
            if cols:
                n = max((len(v) for v in cols.values()), default=0)
                rows_tmp = []
                for i in range(n):
                    row = {}
                    for k, vv in cols.items():
                        row[k] = vv[i] if i < len(vv) else None
                    rows_tmp.append(row)
                roi_table = rows_tmp
            else:
                # single-row dict variant (scalar strings instead of list-columns)
                _nm = roi_table.get("name_roi", roi_table.get("name", ""))
                _rv = roi_table.get("roi", "")
                _fmt = roi_table.get("fmt", "any")
                _pat = roi_table.get("pattern", "")
                _msc = roi_table.get("max_scale", 1.2)
                roi_table = [{
                    "name_roi": _nm,
                    "roi": _rv,
                    "fmt": _fmt,
                    "pattern": _pat,
                    "max_scale": _msc,
                }]
        elif not isinstance(roi_table, list):
            roi_table = []

        rows = []
        has_track = False
        for row in roi_table:
            if not isinstance(row, dict):
                continue
            nm = str(row.get("name_roi") or row.get("name") or "").strip()
            rect = _parse_rect(row.get("roi"))
            if not rect:
                continue
            if nm.lower() == "track_minimap":
                has_track = True
                continue
            rows.append(
                {
                    "name": nm or f"roi_{len(rows)}",
                    "x": rect[0],
                    "y": rect[1],
                    "w": rect[2],
                    "h": rect[3],
                    "fmt": str(row.get("fmt") or "any"),
                    "pattern": str(row.get("pattern") or ""),
                    "max_scale": float(row.get("max_scale") or 1.2),
                }
            )
        return rows, bool(has_track)

    def _wd_extract_track_cfg(doc: dict) -> dict:
        rr = doc.get("recordResult") if isinstance(doc, dict) else {}
        if not isinstance(rr, dict):
            return {}
        ocr = rr.get("ocr") if isinstance(rr.get("ocr"), dict) else {}
        if not isinstance(ocr, dict):
            return {}

        def _parse_rect(v):
            if isinstance(v, (tuple, list)) and len(v) >= 4:
                try:
                    return [float(v[0]), float(v[1]), float(v[2]), float(v[3])]
                except Exception:
                    return None
            txt = str(v or "").strip()
            if not txt:
                return None
            try:
                nums = [float(x) for x in txt.replace(",", " ").replace(";", " ").split()]
                if len(nums) >= 4:
                    return [float(nums[0]), float(nums[1]), float(nums[2]), float(nums[3])]
            except Exception:
                return None
            return None

        def _pts(v):
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

        def _to_roi_dict(lst) -> dict | None:
            """Convert [x,y,w,h] list to the dict format extract_minimap_crop expects."""
            if isinstance(lst, dict) and all(k in lst for k in ("x", "y", "w", "h")):
                return lst
            if isinstance(lst, (list, tuple)) and len(lst) >= 4:
                try:
                    return {"x": float(lst[0]), "y": float(lst[1]),
                            "w": float(lst[2]), "h": float(lst[3])}
                except Exception:
                    return None
            return None

        track_roi = None
        roi_table = ocr.get("roi_table")
        if isinstance(roi_table, dict):
            names = roi_table.get("name_roi") or roi_table.get("name") or []
            rois = roi_table.get("roi") or []
            if isinstance(names, list) and isinstance(rois, list):
                for i, nm in enumerate(names):
                    if str(nm or "").strip().lower() != "track_minimap":
                        continue
                    if i < len(rois):
                        track_roi = _to_roi_dict(_parse_rect(rois[i]))
                        if track_roi:
                            break
            else:
                if str(names or "").strip().lower() == "track_minimap":
                    track_roi = _to_roi_dict(_parse_rect(rois))
        elif isinstance(roi_table, list):
            for row in roi_table:
                if not isinstance(row, dict):
                    continue
                if str(row.get("name_roi") or row.get("name") or "").strip().lower() != "track_minimap":
                    continue
                track_roi = _to_roi_dict(_parse_rect(row.get("roi")))
                if track_roi:
                    break

        trk = ocr.get("trkCalSlim") if isinstance(ocr.get("trkCalSlim"), dict) else {}
        if not track_roi and isinstance(trk, dict):
            track_roi = _to_roi_dict(_parse_rect(trk.get("roi")))
        mini_pts = _pts((trk.get("minimap_pts") if isinstance(trk, dict) else None) or (trk.get("ptsMini") if isinstance(trk, dict) else None))
        ref_pts = _pts((trk.get("ref_pts") if isinstance(trk, dict) else None) or (trk.get("ptsRef") if isinstance(trk, dict) else None))

        color_range = trk.get("moving_pt_color_range") if isinstance(trk.get("moving_pt_color_range"), dict) else None
        if not isinstance(color_range, dict):
            marker_to_cr = globals().get("_marker_to_color_range")
            if callable(marker_to_cr):
                try:
                    cr = marker_to_cr(trk.get("marker") if isinstance(trk, dict) else None)
                    if isinstance(cr, dict) and cr:
                        color_range = cr
                except Exception:
                    color_range = None
        if not isinstance(color_range, dict):
            color_range = dict(st.session_state.get("moving_pt_color_range") or {})

        # centerline_px: pixel coords of track centerline saved when user stores ROI settings.
        cl_px_raw = trk.get("centerline_px") if isinstance(trk, dict) else None
        centerline_px = None
        if isinstance(cl_px_raw, (list, tuple)) and cl_px_raw:
            try:
                _arr = np.asarray(cl_px_raw, dtype=float)
                if _arr.ndim == 2 and _arr.shape[0] >= 2 and _arr.shape[1] >= 2:
                    centerline_px = _arr
            except Exception:
                centerline_px = None

        return {
            "track_roi": track_roi,
            "minimap_pts": mini_pts,
            "ref_pts": ref_pts,
            "moving_pt_color_range": color_range,
            "centerline_px": centerline_px,
        }

    def _wd_expected_ocr_columns(doc: dict) -> tuple[list[str], list[str]]:
        """Return expected OCR column names (roi columns, track columns)."""
        rois, _has_track = _wd_extract_ocr_rois(doc)
        roi_cols = [str(r.get("name") or "").strip() or f"roi_{i}" for i, r in enumerate(rois)]
        track_cfg = _wd_extract_track_cfg(doc)
        track_cols = ["track_minimap_found", "track_minimap_x", "track_minimap_y", "track_xy_x", "track_xy_y", "track_pct"] if track_cfg.get("track_roi") else []
        return roi_cols, track_cols

    def _wd_roi_status(doc: dict) -> str:
        """Return 'vollständig' / 'unvollständig' / 'nein' — mirrors media_tab logic."""
        rr = doc.get("recordResult") if isinstance(doc, dict) else {}
        if not isinstance(rr, dict):
            return "nein"
        ocr = rr.get("ocr") if isinstance(rr.get("ocr"), dict) else {}
        if not isinstance(ocr, dict):
            return "nein"
        roi_table = ocr.get("roi_table") or ocr.get("roi_table_raw")
        if not roi_table:
            return "nein"
        # Detect track_minimap presence
        has_track = False
        if isinstance(roi_table, list):
            has_track = any(
                str((r or {}).get("name_roi") or (r or {}).get("name") or "").strip().lower() == "track_minimap"
                for r in roi_table if isinstance(r, dict)
            )
        elif isinstance(roi_table, dict):
            names = roi_table.get("name_roi") or roi_table.get("name") or []
            if isinstance(names, list):
                has_track = any(str(n or "").strip().lower() == "track_minimap" for n in names)
            else:
                has_track = str(names or "").strip().lower() == "track_minimap"
        trk = ocr.get("trkCalSlim") if isinstance(ocr.get("trkCalSlim"), dict) else {}
        if not has_track and isinstance(trk, dict):
            roi_raw = trk.get("roi")
            if isinstance(roi_raw, (list, tuple)) and len(roi_raw) >= 4:
                try:
                    if float(roi_raw[2]) > 0 and float(roi_raw[3]) > 0:
                        has_track = True
                except Exception:
                    pass
        if not has_track:
            return "vollständig"
        # Track present → check calibration params
        def _pts_ok(v) -> bool:
            return isinstance(v, list) and len(v) >= 4
        def _color_ok(v) -> bool:
            return isinstance(v, dict) and "h_lo" in v
        def _cl_ok(v) -> bool:
            if not isinstance(v, (list, tuple)) or len(v) < 2:
                return False
            try:
                arr = np.asarray(v, dtype=float)
                return arr.ndim == 2 and arr.shape[0] >= 2 and arr.shape[1] >= 2
            except Exception:
                return False
        if (
            _pts_ok(trk.get("minimap_pts"))
            and _pts_ok(trk.get("ref_pts"))
            and _color_ok(trk.get("moving_pt_color_range"))
            and _cl_ok(trk.get("centerline_px"))
        ):
            return "vollständig"
        return "unvollständig"

    def _wd_ocr_pending(path: Path) -> tuple[bool, str]:
        if not path.exists():
            return False, "json fehlt"
        doc = _wd_load_json(path)
        rr = doc.get("recordResult") if isinstance(doc, dict) else {}
        if not isinstance(rr, dict):
            return False, "recordResult fehlt"
        ocr = rr.get("ocr") if isinstance(rr.get("ocr"), dict) else {}
        rois, has_track = _wd_extract_ocr_rois(doc)
        if not rois and (not has_track):
            return False, "keine OCR-ROIs"
        roi_st = _wd_roi_status(doc)
        if roi_st != "vollständig":
            return False, f"ROI {roi_st} (track-Kalibrierung unvollständig)"
        cleaned = ocr.get("cleaned")
        table = ocr.get("table")
        # Columnar format: {"time_s": [...], "frame_idx": [...], ...}
        _tbl_ok = isinstance(table, dict) and len(table.get("time_s") or []) > 0
        _cln_ok = isinstance(cleaned, dict) and len(cleaned.get("time_s") or []) > 0
        if not (_tbl_ok and _cln_ok):
            return True, "ausstehend"
        exp_roi_cols, exp_track_cols = _wd_expected_ocr_columns(doc)
        exp_cols = list(exp_roi_cols) + list(exp_track_cols)
        miss_tbl = [k for k in exp_cols if k not in table]
        miss_cln = [k for k in exp_cols if k not in cleaned]
        if miss_tbl or miss_cln:
            miss_info = ", ".join((miss_tbl + miss_cln)[:8])
            return True, f"fehlende Spalten ({miss_info})"
        params = ocr.get("params") if isinstance(ocr.get("params"), dict) else {}
        # Partial flag: was interrupted mid-run
        if bool(params.get("partial")):
            try:
                last_time = float(table["time_s"][-1])
            except Exception:
                last_time = 0.0
            return True, f"unvollständig (abgebrochen bei {last_time:.1f}s)"
        # Completeness check: last time_s must reach end_s (with tolerance)
        end_s: float | None = None
        start_s: float = 0.0
        try:
            if "end_s" in params:
                end_s = float(params["end_s"])
            elif isinstance(rr.get("metadata"), dict):
                dur = rr["metadata"].get("duration")
                if dur is not None:
                    end_s = float(dur)
        except Exception:
            end_s = None
        try:
            if "start_s" in params:
                start_s = float(params["start_s"])
        except Exception:
            start_s = 0.0
        if end_s is not None and end_s > 0:
            try:
                last_time = float(table["time_s"][-1])
                tolerance = max(2.0, (end_s - start_s) * 0.05)
                if last_time < end_s - tolerance:
                    return True, f"unvollständig (bis {last_time:.1f}s von {end_s:.1f}s)"
            except Exception:
                pass
        return False, "bereits vorhanden"

    def _wd_run_ocr(folder: str, json_path: Path, base_override=None, target_fps_str: str = "2") -> tuple[bool, str]:
        diag = globals().get("diagnose_roi_ocr")
        if not callable(diag):
            try:
                from core.ocr_diagnostic import diagnose_roi_ocr as _diag
                diag = _diag
            except Exception:
                diag = None
        if not callable(diag):
            return False, "diagnose_roi_ocr fehlt"
        if not json_path.exists():
            return False, "json fehlt"
        tcmd = None
        finder = globals().get("find_tesseract_cmd")
        if callable(finder):
            try:
                tcmd = finder()
            except Exception:
                tcmd = None
        if not tcmd:
            return False, "Tesseract nicht gefunden"

        doc = _wd_load_json(json_path)
        rr = doc.get("recordResult") if isinstance(doc, dict) else {}
        if not isinstance(rr, dict):
            return False, "recordResult fehlt"
        ocr = rr.get("ocr") if isinstance(rr.get("ocr"), dict) else {}
        rois, has_track = _wd_extract_ocr_rois(doc)
        track_cfg = _wd_extract_track_cfg(doc)
        track_roi = track_cfg.get("track_roi")
        if not rois and (not track_roi):
            return False, "keine OCR-ROIs/track_minimap"

        out_video, _out_audio = _capture_media_paths(folder, base_override=base_override)
        if not out_video.exists() or out_video.stat().st_size <= 0:
            # Fallback: scan capture folder for any .avi or .mp4
            cap_dir = out_video.parent
            found = None
            if cap_dir.is_dir():
                for ext in ("*.avi", "*.mp4", "*.mkv"):
                    candidates = sorted(cap_dir.glob(ext))
                    if candidates:
                        found = candidates[0]
                        break
            if found is None or found.stat().st_size <= 0:
                return False, "video fehlt"
            out_video = found
        cap = cv2.VideoCapture(str(out_video))
        if not cap.isOpened():
            return False, "video kann nicht geoeffnet werden"
        try:
            fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
            fc = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
            if fps <= 0:
                fps = float(((rr.get("metadata") or {}).get("fps") or 25.0))
            if fps <= 0:
                fps = 25.0
            dur = (fc / fps) if (fc > 0 and fps > 0) else float(((rr.get("metadata") or {}).get("duration") or 0.0))
            if dur <= 0:
                dur = 1.0
            total_frames = int(fc) if fc > 0 else int(dur * fps)

            # Frame step based on target fps
            _tgt = str(target_fps_str or "2").strip().lower()
            if _tgt == "max":
                frame_step = 1
            else:
                try:
                    _tgt_fps = float(_tgt)
                except ValueError:
                    _tgt_fps = 2.0
                frame_step = max(1, int(round(fps / _tgt_fps))) if _tgt_fps > 0 else 1
            # Read start_s / end_s from ocr.params — these are the absolute boundaries
            # set by the user in ROI Setup (the time-range sliders).
            _ocr_params = ocr.get("params") if isinstance(ocr.get("params"), dict) else {}
            _start_s = float(_ocr_params.get("start_s") or 0.0)
            _end_s_cfg = _ocr_params.get("end_s")
            _end_s = float(_end_s_cfg) if _end_s_cfg is not None and float(_end_s_cfg) > 0 else dur
            # Clamp to actual video duration
            _start_s = max(0.0, min(_start_s, dur))
            _end_s = max(_start_s + 0.1, min(_end_s, dur))
            _start_frame = int(_start_s * fps)
            _end_frame = int(_end_s * fps)
            total_frames_range = max(1, _end_frame - _start_frame)
            total_processed = max(1, total_frames_range // frame_step)

            # Columnar format: {"time_s": [...], "frame_idx": [...], "roi_a": [...], ...}
            # Convert legacy array-of-objects to columnar if needed
            def _to_columnar(tbl):
                if not isinstance(tbl, list) or not tbl:
                    return None
                keys = list(tbl[0].keys()) if isinstance(tbl[0], dict) else []
                if not keys:
                    return None
                return {k: [row.get(k, "") for row in tbl if isinstance(row, dict)] for k in keys}

            existing_table = ocr.get("table")
            existing_cleaned = ocr.get("cleaned")
            if isinstance(existing_table, list) and existing_table:
                existing_table = _to_columnar(existing_table)
                existing_cleaned = _to_columnar(existing_cleaned)
            exp_roi_cols, exp_track_cols = _wd_expected_ocr_columns(doc)
            exp_cols = list(exp_roi_cols) + list(exp_track_cols)
            _resuming = (
                isinstance(existing_table, dict) and existing_table.get("frame_idx")
                and isinstance(existing_cleaned, dict) and existing_cleaned.get("frame_idx")
            )
            if _resuming:
                _miss_tbl = [k for k in exp_cols if k not in existing_table]
                _miss_cln = [k for k in exp_cols if k not in existing_cleaned]
                if _miss_tbl or _miss_cln:
                    _wd_log(
                        f"OCR {folder}: fehlende Spalten erkannt -> kompletter Rebuild "
                        f"(table:{','.join(_miss_tbl[:6])} cleaned:{','.join(_miss_cln[:6])})"
                    )
                    _resuming = False
            if _resuming:
                raw_cols = {k: list(v) for k, v in existing_table.items() if isinstance(v, list)}
                clean_cols = {k: list(v) for k, v in existing_cleaned.items() if isinstance(v, list)}
                # frame_idx stored as 1-based; last value = next 0-based index to process
                frame_idx = int(raw_cols["frame_idx"][-1])
                # Never resume before start_s boundary
                frame_idx = max(frame_idx, _start_frame)
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                _resume_start = frame_idx
            else:
                roi_names = list(exp_roi_cols)
                raw_cols: dict[str, list] = {"time_s": [], "frame_idx": [], **{nm: [] for nm in roi_names}}
                clean_cols: dict[str, list] = {"time_s": [], "frame_idx": [], **{nm: [] for nm in roi_names}}
                frame_idx = _start_frame
                cap.set(cv2.CAP_PROP_POS_FRAMES, _start_frame)
                _resume_start = _start_frame

            # Track/minimap columns (positions) are always kept in table/cleaned when track ROI exists.
            _track_cols = list(exp_track_cols)
            for _k in _track_cols:
                raw_cols.setdefault(_k, [])
                clean_cols.setdefault(_k, [])

            _extract_minimap_crop = globals().get("extract_minimap_crop")
            _detect_moving_point = globals().get("detect_moving_point")
            _compare_minimap = globals().get("compare_minimap_to_reference")
            _project_h = globals().get("project_point_with_homography")
            _has_track_tools = callable(_extract_minimap_crop) and callable(_detect_moving_point)
            _mini_pts = list(track_cfg.get("minimap_pts") or [])
            _ref_pts = list(track_cfg.get("ref_pts") or [])
            _color_range = dict(track_cfg.get("moving_pt_color_range") or {})
            # ref_track_img is not saved to JSON — session state access may return None in
            # background threads. H_fallback (computed from minimap_pts + ref_pts) is used
            # as the fallback projection method and does not require the reference image.
            _ref_img = st.session_state.get("ref_track_img")
            # centerline_px is now saved to trkCalSlim in JSON by _ensure_ocr_extractor_ocr_struct.
            _centerline_px_cfg = track_cfg.get("centerline_px")
            _centerline_px = _centerline_px_cfg if _centerline_px_cfg is not None else st.session_state.get("centerline_px")
            _H_fallback = None
            if len(_mini_pts) >= 4 and len(_ref_pts) >= 4:
                try:
                    _src = np.asarray(_mini_pts[:8], dtype=np.float32).reshape(-1, 2)
                    _dst = np.asarray(_ref_pts[:8], dtype=np.float32).reshape(-1, 2)
                    if _src.shape[0] >= 4 and _dst.shape[0] >= 4:
                        _H_fallback, _mask = cv2.findHomography(_src, _dst, method=0)
                except Exception:
                    _H_fallback = None

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

            with _YT_WATCHDOG_LOCK:
                _stop_event = _YT_WATCHDOG.get("stop_event")

            _json_path_lock = get_path_lock(str(json_path))

            def _save_ocr_progress(partial: bool = False) -> None:
                ocr["table"] = raw_cols
                ocr["cleaned"] = clean_cols
                ocr["created"] = datetime.now().isoformat(timespec="seconds")
                ocr["sample_rate_hz"] = round(fps, 6)
                _params = ocr.get("params") if isinstance(ocr.get("params"), dict) else {}
                _params["start_s"] = round(_start_s, 6)
                _params["end_s"] = round(_end_s, 6)
                if partial:
                    _params["partial"] = True
                else:
                    _params.pop("partial", None)
                ocr["params"] = _params
                rr["ocr"] = ocr
                doc["recordResult"] = rr
                with _json_path_lock:
                    json_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

            _n_rows = len(raw_cols.get("time_s", []))
            _pct_log_every = max(1, total_processed // 10)  # log + checkpoint every ~10%
            _processed_count = 0
            _stopped_early = False
            while True:
                if _stop_event is not None and _stop_event.is_set():
                    _stopped_early = True
                    break
                # Stop at end_s boundary
                if frame_idx >= _end_frame:
                    break
                ok, frame_bgr = cap.read()
                if (not ok) or frame_bgr is None:
                    break
                time_s = frame_idx / fps
                frame = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
                fh, fw = frame.shape[:2]
                raw_cols.setdefault("time_s", []).append(round(time_s, 6))
                raw_cols.setdefault("frame_idx", []).append(frame_idx + 1)
                clean_cols.setdefault("time_s", []).append(round(time_s, 6))
                clean_cols.setdefault("frame_idx", []).append(frame_idx + 1)
                for roi_cfg in rois:
                    nm = str(roi_cfg.get("name") or "").strip() or "roi"
                    probe = diag(frame, roi_cfg, (int(fw), int(fh)), tmp_root=Path("logs") / "ocr_tmp")
                    raw_cols.setdefault(nm, []).append(str(probe.get("raw", "") or ""))
                    clean_cols.setdefault(nm, []).append(str(probe.get("value", "") or "") if bool(probe.get("ok")) else "")

                if _track_cols:
                    for _k in _track_cols:
                        raw_cols[_k].append(0 if _k == "track_minimap_found" else "")
                        clean_cols[_k].append(0 if _k == "track_minimap_found" else "")
                    if _has_track_tools:
                        try:
                            _crop = _extract_minimap_crop(frame, track_roi, fw, fh)
                        except Exception:
                            _crop = None
                        if _crop is not None:
                            _mp = _detect_moving_point(_crop, _color_range)
                            if isinstance(_mp, dict):
                                raw_cols["track_minimap_found"][-1] = 1
                                clean_cols["track_minimap_found"][-1] = 1
                                try:
                                    _x = float(_mp.get("x", 0.0) or 0.0)
                                    _y = float(_mp.get("y", 0.0) or 0.0)
                                    raw_cols["track_minimap_x"][-1] = _x
                                    raw_cols["track_minimap_y"][-1] = _y
                                    clean_cols["track_minimap_x"][-1] = _x
                                    clean_cols["track_minimap_y"][-1] = _y
                                except Exception:
                                    _x = _y = None
                                _ref_pt = None
                                if (_x is not None) and (_y is not None):
                                    if callable(_compare_minimap) and (_ref_img is not None) and len(_mini_pts) >= 4 and len(_ref_pts) >= 4:
                                        try:
                                            _cmp = _compare_minimap(_crop, _ref_img, _mini_pts, _ref_pts)
                                            _H = _cmp.get("H") if isinstance(_cmp, dict) else None
                                            if callable(_project_h) and _H is not None:
                                                _ref_pt = _project_h((_x, _y), _H)
                                        except Exception:
                                            _ref_pt = None
                                    if _ref_pt is None and _H_fallback is not None:
                                        try:
                                            _p = np.array([[[float(_x), float(_y)]]], dtype=np.float32)
                                            _q = cv2.perspectiveTransform(_p, _H_fallback)
                                            _ref_pt = [float(_q[0, 0, 0]), float(_q[0, 0, 1])]
                                        except Exception:
                                            _ref_pt = None
                                if isinstance(_ref_pt, (list, tuple, np.ndarray)) and len(_ref_pt) >= 2:
                                    _rx = float(_ref_pt[0])
                                    _ry = float(_ref_pt[1])
                                    raw_cols["track_xy_x"][-1] = _rx
                                    raw_cols["track_xy_y"][-1] = _ry
                                    clean_cols["track_xy_x"][-1] = _rx
                                    clean_cols["track_xy_y"][-1] = _ry
                                    _pct = _centerline_progress_percent(_ref_pt, _centerline_px)
                                    if _pct is not None:
                                        raw_cols["track_pct"][-1] = float(_pct)
                                        clean_cols["track_pct"][-1] = float(_pct)
                frame_idx += frame_step
                _processed_count += 1
                _n_rows += 1
                # Skip frame_step-1 frames without decoding
                for _ in range(frame_step - 1):
                    if not cap.grab():
                        break
                pct = int(100 * frame_idx / max(1, total_frames))
                _wd_set_current(f"OCR: {folder} – Frame {frame_idx}/{total_frames} ({pct}%)")
                # Push live state for Video OCR Full tab (atomic dict swap, no lock needed).
                _live_row = {"time_s": round(time_s, 3), "frame_idx": frame_idx}
                for _k, _v in clean_cols.items():
                    if _k not in ("time_s", "frame_idx") and _v:
                        _live_row[_k] = _v[-1]
                _ocr_live = _YT_WATCHDOG.get("ocr_live") or {}
                _prev_rows = _ocr_live.get("rows") or []
                _new_rows = (_prev_rows + [_live_row])[-120:]
                _YT_WATCHDOG["ocr_live"] = {
                    "folder": folder,
                    "done": frame_idx,
                    "total": total_frames,
                    "t_s": round(time_s, 3),
                    "rows": _new_rows,
                    "active": True,
                }
                if _processed_count % _pct_log_every == 0:
                    _wd_log(f"OCR {folder}: {pct}% (Frame {frame_idx}/{total_frames})")
                    _save_ocr_progress(partial=True)
        finally:
            cap.release()

        _YT_WATCHDOG["ocr_live"] = {"folder": folder, "active": False}

        if _stopped_early:
            if _n_rows > 0:
                _save_ocr_progress(partial=True)
                pct = int(100 * frame_idx / max(1, total_frames))
                _wd_log(f"OCR {folder}: abgebrochen bei {pct}% – Zwischenstand gespeichert ({_n_rows} Zeilen)")
                return False, f"abgebrochen bei {pct}% ({_n_rows} Zeilen gespeichert)"
            return False, "abgebrochen (kein Fortschritt)"

        _save_ocr_progress(partial=False)
        new_frames = frame_idx - _resume_start
        if _resuming:
            return True, f"OCR fortgesetzt (+{new_frames} Frames, gesamt {_n_rows} Zeilen)"
        return True, f"OCR gespeichert ({_n_rows} Zeilen)"


    def _wd_convert_one_mat_to_json(base_override=None) -> tuple[bool, str]:
        base = _capture_base(base_override=base_override)
        res_dir = base / "results"
        if not res_dir.exists():
            return False, "results fehlt"
        with _YT_WATCHDOG_LOCK:
            skip_set: set = _YT_WATCHDOG.setdefault("mat_json_skip", set())
        mat_files = sorted(res_dir.glob("*.mat"))
        for mat_path in mat_files:
            json_path = mat_path.with_suffix(".json")
            if json_path.exists() and json_path.stat().st_size > 0:
                continue
            if mat_path.name in skip_set:
                continue
            try:
                raw = mat_path.read_bytes()
            except Exception as e:
                _wd_log(f"MAT read Fehler: {mat_path.name}: {e}")
                with _YT_WATCHDOG_LOCK:
                    _YT_WATCHDOG.setdefault("mat_json_skip", set()).add(mat_path.name)
                continue
            if not raw:
                with _YT_WATCHDOG_LOCK:
                    _YT_WATCHDOG.setdefault("mat_json_skip", set()).add(mat_path.name)
                continue
            out = None
            helper = globals().get("_mat_bytes_to_recordresult_json_bytes")
            if callable(helper):
                try:
                    out = helper(raw)
                except Exception:
                    out = None
            if not out:
                try:
                    from core.save_helpers import rr_from_mat_bytes
                    rr, _extra = rr_from_mat_bytes(raw)
                    if isinstance(rr, dict) and rr:
                        payload = {"recordResult": _mat_export_to_jsonable(rr)}
                        norm = globals().get("_normalize_sidecar_json_payload")
                        if callable(norm):
                            payload = norm(payload)
                        out = json.dumps(
                            payload,
                            ensure_ascii=False,
                            indent=2,
                            default=lambda o: _mat_export_to_jsonable(o),
                        ).encode("utf-8")
                except Exception:
                    out = None
            if not out:
                # Fallback: robust scipy/h5 loader path similar to MAT->JSON tab.
                try:
                    robust_loader = globals().get("_loadmat_audio_save_robust")
                    mat_to_plain = globals().get("_mat_struct_to_plain")
                    norm = globals().get("_normalize_sidecar_json_payload")
                    data = None
                    if callable(robust_loader):
                        data, _note = robust_loader(str(mat_path))
                    if isinstance(data, dict) and data:
                        rr_obj = data.get("recordResult")
                        if rr_obj is None:
                            for k, v in data.items():
                                if str(k).lower() == "recordresult":
                                    rr_obj = v
                                    break
                        if rr_obj is not None:
                            rr_plain = mat_to_plain(rr_obj) if callable(mat_to_plain) else rr_obj
                            if isinstance(rr_plain, dict) and rr_plain:
                                payload = {"recordResult": _mat_export_to_jsonable(rr_plain)}
                                if callable(norm):
                                    payload = norm(payload)
                                out = json.dumps(
                                    payload,
                                    ensure_ascii=False,
                                    indent=2,
                                    default=lambda o: _mat_export_to_jsonable(o),
                                ).encode("utf-8")
                except Exception:
                    out = None
            if not out:
                _wd_log(f"MAT->JSON übersprungen (nicht lesbar): {mat_path.name}")
                with _YT_WATCHDOG_LOCK:
                    _YT_WATCHDOG.setdefault("mat_json_skip", set()).add(mat_path.name)
                continue
            try:
                with get_path_lock(str(json_path)):
                    json_path.write_bytes(bytes(out))
            except Exception as e:
                _wd_log(f"MAT->JSON write Fehler: {json_path.name}: {e}")
                with _YT_WATCHDOG_LOCK:
                    _YT_WATCHDOG.setdefault("mat_json_skip", set()).add(mat_path.name)
                continue
            return True, f"{mat_path.name} -> {json_path.name}"
        return False, "nichts offen"

    def _wd_retrofix_one(base_override=None) -> tuple[bool, str, bool]:
        """Run retrofix (time-trim + plausibility filter) for one result JSON.
        Skip-set updated AFTER processing so an interrupted file is retried next pass.
        Returns (changed, message, needs_track_rerun)."""
        try:
            from app_tabs.plausibility_filter import retrofix_result_json
            from app_tabs.roi_catalog_tab import load_catalog as _lc_rf
        except Exception as e:
            return False, f"Import fehlgeschlagen: {e}", False

        base = _capture_base(base_override=base_override)
        res_dir = base / "results"
        if not res_dir.exists():
            return False, "nichts offen", False

        with _YT_WATCHDOG_LOCK:
            skip: set = set(_YT_WATCHDOG.get("retrofix_skip") or set())

        catalog = _lc_rf()

        for jp in sorted(res_dir.glob("results_*.json")):
            jp_str = str(jp)
            if jp_str in skip:
                continue
            ok, msg, track_needed = retrofix_result_json(jp_str, catalog)
            # Mark done AFTER processing — interrupted files will be retried
            with _YT_WATCHDOG_LOCK:
                _YT_WATCHDOG.setdefault("retrofix_skip", set()).add(jp_str)
            return ok, msg, track_needed

        return False, "nichts offen", False

    def _wd_retro_track_one(base_override=None) -> tuple[bool, str]:
        """Re-run track minimap detection for one JSON where track columns are empty/missing.
        Uses existing frame_idx list from table/cleaned — no full OCR re-run needed."""
        try:
            from app_tabs.plausibility_filter import needs_track_rerun as _ntr
            from app_tabs.roi_catalog_tab import load_catalog as _lc_tr
        except Exception as e:
            return False, f"Import fehlgeschlagen: {e}"

        base = _capture_base(base_override=base_override)
        res_dir = base / "results"
        if not res_dir.exists():
            return False, "nichts offen"

        with _YT_WATCHDOG_LOCK:
            skip: set = set(_YT_WATCHDOG.get("retro_track_skip") or set())

        for jp in sorted(res_dir.glob("results_*.json")):
            jp_str = str(jp)
            if jp_str in skip:
                continue
            try:
                doc = _wd_load_json(jp)
                if not _ntr(doc):
                    # No rerun needed — skip immediately
                    with _YT_WATCHDOG_LOCK:
                        _YT_WATCHDOG.setdefault("retro_track_skip", set()).add(jp_str)
                    continue
            except Exception:
                with _YT_WATCHDOG_LOCK:
                    _YT_WATCHDOG.setdefault("retro_track_skip", set()).add(jp_str)
                continue

            # Found a file that needs track re-run.
            # Mark done AFTER processing — if interrupted, partial state is saved
            # to JSON and needs_track_rerun will detect it on next pass.
            ok, msg = _wd_run_track_only(jp, base_override=base_override)
            with _YT_WATCHDOG_LOCK:
                _YT_WATCHDOG.setdefault("retro_track_skip", set()).add(jp_str)
            return ok, msg

        return False, "nichts offen"

    def _wd_run_track_only(json_path: Path, base_override=None) -> tuple[bool, str]:
        """Re-run only the track/minimap detection columns for an already-OCR'd JSON.
        Reads existing frame_idx from cleaned/table and processes those frames only."""
        folder = json_path.stem.replace("results_", "", 1)
        _wd_set_current(f"Track-Nachkorrektur: {folder}")

        _extract_minimap_crop = globals().get("extract_minimap_crop")
        _detect_moving_point = globals().get("detect_moving_point")
        if not callable(_extract_minimap_crop) or not callable(_detect_moving_point):
            return False, "track-Tools fehlen"

        doc = _wd_load_json(json_path)
        rr = doc.get("recordResult") if isinstance(doc, dict) else {}
        if not isinstance(rr, dict):
            return False, "recordResult fehlt"
        ocr = rr.get("ocr") if isinstance(rr.get("ocr"), dict) else {}

        track_cfg = _wd_extract_track_cfg(doc)
        track_roi = track_cfg.get("track_roi")
        if not track_roi:
            return False, "kein track_roi"

        # Load existing table to get frame_idx list
        src_tbl = None
        for k in ("cleaned", "table"):
            t = ocr.get(k)
            if isinstance(t, dict) and t.get("frame_idx"):
                src_tbl = t
                break
        if src_tbl is None:
            return False, "keine Tabelle mit frame_idx"

        frame_idxs = [int(v) for v in src_tbl["frame_idx"] if v not in ("", None)]
        from app_tabs.plausibility_filter import _to_float as _pf_to_float
        time_ss = [_pf_to_float(v) for v in src_tbl.get("time_s", [])]
        n = len(frame_idxs)
        if n == 0:
            return False, "keine Frames"

        out_video, _ = _capture_media_paths(folder, base_override=base_override)
        if not out_video.exists():
            # Fallback scan
            cap_dir = out_video.parent
            found = None
            if cap_dir.is_dir():
                for ext in ("*.avi", "*.mp4", "*.mkv"):
                    cands = sorted(cap_dir.glob(ext))
                    if cands:
                        found = cands[0]
                        break
            if found is None:
                return False, "video fehlt"
            out_video = found

        cap = cv2.VideoCapture(str(out_video))
        if not cap.isOpened():
            return False, "video kann nicht geöffnet werden"

        try:
            fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
            if fps <= 0:
                fps = 30.0
            total_vid = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            fw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1920)
            fh_v = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1080)

            _mini_pts = list(track_cfg.get("minimap_pts") or [])
            _ref_pts = list(track_cfg.get("ref_pts") or [])
            _color_range = dict(track_cfg.get("moving_pt_color_range") or {})
            _centerline_px = track_cfg.get("centerline_px")

            _H_fallback = None
            if len(_mini_pts) >= 4 and len(_ref_pts) >= 4:
                try:
                    _src = np.asarray(_mini_pts[:8], dtype=np.float32).reshape(-1, 2)
                    _dst = np.asarray(_ref_pts[:8], dtype=np.float32).reshape(-1, 2)
                    _H_fallback, _ = cv2.findHomography(_src, _dst, method=0)
                except Exception:
                    _H_fallback = None

            def _cl_pct(ref_pt, cl_px):
                if ref_pt is None or cl_px is None:
                    return None
                try:
                    cl = np.asarray(cl_px, dtype=float)
                    if cl.ndim != 2 or cl.shape[0] < 2:
                        return None
                    p = np.asarray(ref_pt, dtype=float).ravel()[:2]
                    d = np.diff(cl[:, :2], axis=0)
                    seg_len = np.sqrt(np.sum(d * d, axis=1))
                    cum = np.concatenate(([0.0], np.cumsum(seg_len)))
                    total = float(cum[-1])
                    if total <= 1e-9:
                        return None
                    best_d2, best_s = float("inf"), 0.0
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

            # ── Resume from partial save if watchdog was interrupted ─────────
            _partial = ocr.get("track_rerun_partial")
            _resume_idx = 0
            tmf_out = [0] * n
            tmx_out = [""] * n
            tmy_out = [""] * n
            txx_out = [""] * n
            txy_out = [""] * n
            tpc_out = [""] * n
            if isinstance(_partial, dict) and int(_partial.get("n", 0)) == n:
                try:
                    tmf_out = list(_partial["tmf"])
                    tmx_out = list(_partial["tmx"])
                    tmy_out = list(_partial["tmy"])
                    txx_out = list(_partial["txx"])
                    txy_out = list(_partial["txy"])
                    tpc_out = list(_partial["tpc"])
                    _resume_idx = int(_partial.get("last_idx", 0))
                    _wd_log(f"Track-Nachkorrektur: {folder} – Resume ab {_resume_idx}/{n}")
                except Exception:
                    _resume_idx = 0
                    tmf_out = [0] * n
                    tmx_out = tmx_out[:0] or [""] * n
                    tmy_out = [""] * n
                    txx_out = [""] * n
                    txy_out = [""] * n
                    tpc_out = [""] * n

            _save_every = max(10, n // 20)  # checkpoint every ~5%
            _json_path_lock = get_path_lock(str(json_path))

            def _save_partial(last_idx: int) -> None:
                ocr["track_rerun_partial"] = {
                    "n": n, "last_idx": last_idx,
                    "tmf": tmf_out, "tmx": tmx_out, "tmy": tmy_out,
                    "txx": txx_out, "txy": txy_out, "tpc": tpc_out,
                }
                rr["ocr"] = ocr
                doc["recordResult"] = rr
                from app_tabs.plausibility_filter import _atomic_write as _aw
                with _json_path_lock:
                    _aw(json_path, doc)

            _with_stop = _YT_WATCHDOG.get("stop_event")
            _stopped = False
            for i in range(_resume_idx, n):
                if _with_stop is not None and _with_stop.is_set():
                    _save_partial(i)
                    _stopped = True
                    _wd_log(f"Track-Nachkorrektur: {folder} – gestoppt bei {i}/{n}, Zwischenstand gespeichert")
                    break
                fidx = frame_idxs[i]
                if fidx < 1 or (total_vid > 0 and fidx > total_vid):
                    continue
                cap.set(cv2.CAP_PROP_POS_FRAMES, fidx - 1)
                ok_r, frame_bgr = cap.read()
                if not ok_r or frame_bgr is None:
                    continue
                frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
                try:
                    crop = _extract_minimap_crop(frame_rgb, track_roi, fw, fh_v)
                except Exception:
                    continue
                if crop is None:
                    continue
                mp = _detect_moving_point(crop, _color_range)
                if isinstance(mp, dict):
                    tmf_out[i] = 1
                    try:
                        _x = float(mp.get("x", 0.0) or 0.0)
                        _y = float(mp.get("y", 0.0) or 0.0)
                        tmx_out[i] = _x
                        tmy_out[i] = _y
                        _ref_pt = None
                        if _H_fallback is not None:
                            try:
                                _p = np.array([[[_x, _y]]], dtype=np.float32)
                                _q = cv2.perspectiveTransform(_p, _H_fallback)
                                _ref_pt = [float(_q[0, 0, 0]), float(_q[0, 0, 1])]
                            except Exception:
                                pass
                        if _ref_pt is not None:
                            txx_out[i] = float(_ref_pt[0])
                            txy_out[i] = float(_ref_pt[1])
                            pct = _cl_pct(_ref_pt, _centerline_px)
                            if pct is not None:
                                tpc_out[i] = float(pct)
                    except Exception:
                        pass

                if i % _save_every == 0:
                    _save_partial(i + 1)
                    _wd_set_current(f"Track-Nachkorrektur: {folder} {i+1}/{n}")
        finally:
            cap.release()

        if _stopped:
            return False, f"{folder}: bei {_resume_idx}/{n} gestoppt – Resume beim nächsten Start"

        # Completed — write final results and remove the partial marker
        found_count = sum(tmf_out)
        for key in ("table", "cleaned"):
            tbl = ocr.get(key)
            if not isinstance(tbl, dict) or not tbl.get("frame_idx"):
                continue
            if len(tbl["frame_idx"]) != n:
                continue
            tbl["track_minimap_found"] = tmf_out
            tbl["track_minimap_x"] = tmx_out
            tbl["track_minimap_y"] = tmy_out
            tbl["track_xy_x"] = txx_out
            tbl["track_xy_y"] = txy_out
            tbl["track_pct"] = tpc_out
            ocr[key] = tbl

        ocr.pop("track_rerun_partial", None)  # clean up partial marker
        rr["ocr"] = ocr
        doc["recordResult"] = rr
        from app_tabs.plausibility_filter import _atomic_write as _aw_final
        with get_path_lock(str(json_path)):
            _aw_final(json_path, doc)
        return True, f"{folder}: {found_count}/{n} Frames mit Track-Punkt"

    def _wd_reclean_one(base_override=None) -> tuple[bool, str]:
        """Filter one result JSON with current catalog plausibility + slope bounds.
        Tracks processed files in _YT_WATCHDOG['reclean_skip'] for this session."""
        try:
            from app_tabs.plausibility_filter import reclean_result_json
            from app_tabs.roi_catalog_tab import load_catalog as _lc_rc
        except Exception as e:
            return False, f"Import fehlgeschlagen: {e}"

        base = _capture_base(base_override=base_override)
        res_dir = base / "results"
        if not res_dir.exists():
            return False, "nichts offen"

        with _YT_WATCHDOG_LOCK:
            skip: set = set(_YT_WATCHDOG.get("reclean_skip") or set())

        catalog = _lc_rc()
        if not (catalog.get("plausibility")):
            return False, "kein Katalog"

        for jp in sorted(res_dir.glob("results_*.json")):
            jp_str = str(jp)
            if jp_str in skip:
                continue
            ok, msg = reclean_result_json(jp_str, catalog)
            # Mark done AFTER processing — interrupted files will be retried
            with _YT_WATCHDOG_LOCK:
                _YT_WATCHDOG.setdefault("reclean_skip", set()).add(jp_str)
            if ok:
                return True, msg
            # file had no usable table — not an error, continue to next
            if "keine Tabelle" in msg or "kein recordResult" in msg or "kein ocr" in msg:
                continue
            return False, msg

        return False, "nichts offen"

    def _wd_process_once(cfg: dict, stop_event=None) -> bool:
        base_override = cfg.get("local_base_path")
        # Always read from the live shared dict so UI changes take effect at the
        # next tick without stopping the watchdog mid-operation.
        with _YT_WATCHDOG_LOCK:
            tasks = dict(_YT_WATCHDOG.get("tasks") or cfg.get("tasks") or {})
        task_mat_json = bool(tasks.get("mat_json", False))
        task_download = bool(tasks.get("download", True))
        task_ocr = bool(tasks.get("ocr", True))
        task_reclean = bool(tasks.get("reclean", False))
        task_retrofix = bool(tasks.get("retrofix", False))

        _wd_log(f"Tick | Aufgaben: MAT-JSON={task_mat_json} Download={task_download} OCR={task_ocr} Nachfiltern={task_reclean} Nachkorrektur={task_retrofix}")

        if task_mat_json:
            _wd_set_current("MAT->JSON")
            ok_mj, msg_mj = _wd_convert_one_mat_to_json(base_override=base_override)
            if ok_mj:
                _wd_inc("mat_json")
                _wd_log(f"MAT->JSON: {msg_mj}")
                return True
            if "nichts offen" not in str(msg_mj).lower() and "results fehlt" not in str(msg_mj).lower():
                _wd_inc("errors")
                _wd_log(f"MAT->JSON Fehler: {msg_mj}")
                return True
            _wd_log(f"MAT->JSON: {msg_mj}")

        rows_now = _read_db()
        _wd_log(f"DB: {len(rows_now)} Einträge geladen")

        # Also scan results/*.json directly — picks up MAT-converted files not in YouTube DB.
        # Only needed when OCR is active; de-duplicated by capture_folder.
        if task_ocr:
            try:
                known_cf = {str(r.get("capture_folder") or "").strip() for r in rows_now if str(r.get("capture_folder") or "").strip()}
                for jr in _rows_from_results_json():
                    cf = str(jr.get("capture_folder") or "").strip()
                    if cf and cf not in known_cf:
                        rows_now = list(rows_now) + [jr]
                        known_cf.add(cf)
                _wd_log(f"Gesamt (DB + results/): {len(rows_now)} Ordner")
            except Exception as _e:
                _wd_log(f"results/-Scan Fehler: {_e}")

        with _YT_WATCHDOG_LOCK:
            ocr_skip_now: set = set(_YT_WATCHDOG.get("ocr_skip", set()))

        for row in rows_now:
            link = str(row.get("youtube_link") or "").strip()
            if not link:
                continue
            folder = str(row.get("capture_folder") or "").strip()
            if not folder:
                folder = _default_capture_folder()
                row = _wd_update_row(link, {"capture_folder": folder}) or {**row, "capture_folder": folder}
            out_video, out_audio = _capture_media_paths(folder, base_override=base_override)
            _ex_video, _ = _find_existing_media(folder, base_override=base_override)
            _aud_ok, _ = _ensure_audio_file(folder, base_override=base_override)
            media_ok = _ex_video is not None and _aud_ok
            status = str(row.get("download_status") or "pending").strip().lower()
            json_path = str(row.get("json_path") or "").strip()
            json_file = Path(json_path) if json_path else _wd_json_path(folder, base_override=base_override)

            if task_ocr and folder not in ocr_skip_now:
                need_ocr, reason = _wd_ocr_pending(json_file)
                if not need_ocr:
                    _wd_log(f"OCR {folder}: {reason} – skip")

            if task_download:
                video_faulty = _wd_is_video_faulty(json_file)
                with _YT_WATCHDOG_LOCK:
                    faulty_tried: set = _YT_WATCHDOG.setdefault("faulty_tried", set())
                    silent_skip: set = _YT_WATCHDOG.setdefault("silent_skip", set())

                # If audio exists but is silent and we already tried once this
                # session, skip → move to next folder instead of retrying forever.
                _, _aud_msg = _ensure_audio_file(folder, base_override=base_override)
                _audio_is_silent_result = "stumm" in str(_aud_msg).lower()
                if _audio_is_silent_result and folder in silent_skip:
                    _wd_log(f"Download skip (Audio stumm, bereits probiert): {folder}")
                    continue

                need_download = (not media_ok) or (video_faulty and folder not in faulty_tried)
                dl_force = video_faulty and media_ok  # files exist but marked faulty → force
                if need_download:
                    if video_faulty:
                        with _YT_WATCHDOG_LOCK:
                            _YT_WATCHDOG["faulty_tried"].add(folder)
                        _wd_log(f"Video fehlerhaft, erzwinge Re-Download: {folder}")
                    _wd_set_current(f"Download: {folder}")
                    _wd_log(f"Download gestartet: {folder}")
                    _wd_update_row(link, {"download_status": "downloading", "last_error": ""})
                    ok_dl, msg_dl, parsed = _download_one(
                        row,
                        force=dl_force,
                        base_override=base_override,
                        open_new_window=bool(cfg.get("open_new_window", True)),
                        move_other_display=bool(cfg.get("move_other_display", False)),
                        stop_event=stop_event,
                    )
                    if not ok_dl:
                        _wd_update_row(link, {"download_status": "error", "last_error": str(msg_dl or "Download-Fehler")})
                        _wd_inc("errors")
                        _wd_log(f"Download Fehler: {folder} -> {msg_dl}")
                        return True
                    meta_url = _fetch_metadata_for_url(link)
                    title_now = str(parsed.get("RESULT_TITLE") or meta_url.get("title") or row.get("title") or "")
                    pub_now = str(parsed.get("RESULT_PUBDATE") or meta_url.get("pubDate") or row.get("upload_date") or "")
                    ok_meta, msg_meta = _write_capture_metadata_json(
                        folder,
                        {
                            "youtube_url": link,
                            "video_title": title_now,
                            "video_name": str(folder),
                            "upload_date": pub_now,
                            "desc": str(parsed.get("RESULT_DESC") or meta_url.get("desc") or ""),
                            "channel_name": str(parsed.get("RESULT_CHANNAME") or meta_url.get("chanName") or ""),
                            "downloaded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        },
                        base_override=base_override,
                        quiet=True,
                    )
                    patch = {
                        "download_status": "downloaded",
                        "last_error": "" if ok_meta else f"metadata.json Fehler: {msg_meta}",
                        "downloaded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "title": title_now,
                        "upload_date": pub_now,
                    }
                    if ok_meta:
                        patch["json_path"] = msg_meta
                        json_file = Path(msg_meta)
                    _wd_update_row(link, patch)
                    _wd_inc("downloads")
                    _wd_log(f"Download abgeschlossen: {folder}")
                    _wd_clear_video_faulty_in_json(json_file)
                    with _YT_WATCHDOG_LOCK:
                        _YT_WATCHDOG.setdefault("clear_faulty_folders", set()).add(folder)
                    # Check if new audio is still silent → add to silent_skip so
                    # the watchdog moves on instead of retrying the same folder.
                    _aud_ok_post, _aud_msg_post = _ensure_audio_file(folder, base_override=base_override)
                    if not _aud_ok_post and "stumm" in str(_aud_msg_post).lower():
                        with _YT_WATCHDOG_LOCK:
                            _YT_WATCHDOG.setdefault("silent_skip", set()).add(folder)
                        _wd_log(f"Audio stumm nach Download – überspringe {folder} (Loopback prüfen)")
                    return True

            if status != "downloaded":
                _wd_update_row(link, {"download_status": "downloaded", "last_error": ""})

            need_ocr, reason = _wd_ocr_pending(json_file)
            if task_ocr and need_ocr and folder not in ocr_skip_now:
                _wd_set_current(f"OCR: {folder}")
                if "unvollständig" in reason:
                    _wd_log(f"OCR fortsetzen: {folder} ({reason})")
                else:
                    _wd_log(f"OCR startet: {folder}")
                ok_ocr, msg_ocr = _wd_run_ocr(folder, json_file, base_override=base_override, target_fps_str=str(cfg.get("ocr_fps", "2") or "2"))
                if ok_ocr:
                    _wd_inc("ocr")
                    _wd_update_row(link, {"last_error": "", "ocr_status": str(msg_ocr)})
                    _wd_log(f"OCR abgeschlossen: {folder} – {msg_ocr}")
                    return True
                elif "abgebrochen" in str(msg_ocr):
                    # Stopped by stop_event — partial progress already saved, resume next time
                    _wd_update_row(link, {"ocr_status": str(msg_ocr)})
                    return True
                else:
                    _wd_inc("errors")
                    _wd_update_row(link, {"last_error": f"OCR: {msg_ocr}"})
                    _wd_log(f"OCR Fehler: {folder} -> {msg_ocr}")
                    with _YT_WATCHDOG_LOCK:
                        _YT_WATCHDOG.setdefault("ocr_skip", set()).add(folder)
                    return True

        # ── Nachkorrektur (trim + filter + track re-run) ──────────────────────
        if task_retrofix:
            _wd_set_current("Nachkorrektur: retrofix")
            ok_rf, msg_rf, track_needed_rf = _wd_retrofix_one(base_override=base_override)
            if ok_rf:
                _wd_log(f"Nachkorrektur: {msg_rf}")
                return True
            if "nichts offen" not in str(msg_rf).lower():
                _wd_inc("errors")
                _wd_log(f"Nachkorrektur Fehler: {msg_rf}")
                return True
            # retrofix pass done — now do track re-run pass
            _wd_set_current("Nachkorrektur: track re-run")
            ok_tr, msg_tr = _wd_retro_track_one(base_override=base_override)
            if ok_tr:
                _wd_log(f"Track-Nachkorrektur: {msg_tr}")
                return True
            if "nichts offen" not in str(msg_tr).lower():
                _wd_inc("errors")
                _wd_log(f"Track-Nachkorrektur Fehler: {msg_tr}")
                return True

        # ── Nachfiltern ───────────────────────────────────────────────────────
        if task_reclean:
            _wd_set_current("Nachfiltern")
            ok_rc, msg_rc = _wd_reclean_one(base_override=base_override)
            if ok_rc:
                _wd_log(f"Nachfiltern: {msg_rc}")
                return True
            if "nichts offen" not in str(msg_rc).lower() and "kein katalog" not in str(msg_rc).lower():
                _wd_inc("errors")
                _wd_log(f"Nachfiltern Fehler: {msg_rc}")
                return True

        _wd_log("Tick abgeschlossen: nichts zu tun – starte Suche neu (ocr_skip zurückgesetzt)")
        _wd_set_current("")
        # Reset skip-sets so the next pass re-evaluates all folders from scratch.
        with _YT_WATCHDOG_LOCK:
            _YT_WATCHDOG["ocr_skip"] = set()
            _YT_WATCHDOG["reclean_skip"] = set()
            _YT_WATCHDOG["retrofix_skip"] = set()
            _YT_WATCHDOG["retro_track_skip"] = set()
        return False

    def _wd_loop(stop_event, cfg: dict) -> None:
        _wd_log("Watchdog gestartet")
        while not stop_event.is_set():
            try:
                progressed = _wd_process_once(cfg, stop_event=stop_event)
                with _YT_WATCHDOG_LOCK:
                    _YT_WATCHDOG["last_tick"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                sleep_s = 1 if progressed else max(2, int(cfg.get("interval_sec", 20) or 20))
                if not progressed:
                    next_ts = (datetime.now() + __import__("datetime").timedelta(seconds=sleep_s)).strftime("%H:%M:%S")
                    _wd_log(f"Warte {sleep_s}s – nächster Tick um {next_ts}")
                    _wd_set_current(f"Warte {sleep_s}s (nächster Tick: {next_ts})")
                stop_event.wait(float(sleep_s))
                if not progressed and not stop_event.is_set():
                    _wd_set_current("")
            except Exception as e:
                _wd_inc("errors")
                _wd_log(f"Watchdog Exception: {e.__class__.__name__}: {e}")
                stop_event.wait(3.0)
        with _YT_WATCHDOG_LOCK:
            _YT_WATCHDOG["running"] = False
        _wd_set_current("")
        _wd_log("Watchdog gestoppt")

    def _wd_start(interval_sec: int) -> None:
        with _YT_WATCHDOG_LOCK:
            th = _YT_WATCHDOG.get("thread")
            if bool(_YT_WATCHDOG.get("running")) and th is not None and th.is_alive():
                return
            stop_event = threading.Event()
            tasks_cfg = {
                "mat_json": bool(st.session_state.get("yt_watchdog_task_mat_json", False)),
                "download": bool(st.session_state.get("yt_watchdog_task_download", False)),
                "ocr": bool(st.session_state.get("yt_watchdog_task_ocr", True)),
            }
            cfg = {
                "interval_sec": int(interval_sec),
                "local_base_path": str(st.session_state.get("local_base_path") or "").strip(),
                "open_new_window": bool(st.session_state.get("yt_open_new_window", True)),
                "move_other_display": bool(st.session_state.get("yt_move_other_display", False)),
                "tasks": tasks_cfg,
                "ocr_fps": str(st.session_state.get("yt_watchdog_ocr_fps", "2") or "2").strip(),
            }
            th = threading.Thread(target=_wd_loop, args=(stop_event, cfg), daemon=True, name="yt-watchdog")
            _YT_WATCHDOG["running"] = True
            _YT_WATCHDOG["thread"] = th
            _YT_WATCHDOG["stop_event"] = stop_event
            _YT_WATCHDOG["interval_sec"] = int(interval_sec)
            _YT_WATCHDOG["current"] = ""
            _YT_WATCHDOG["tasks"] = dict(tasks_cfg)
            _YT_WATCHDOG["faulty_tried"] = set()   # reset per session
            _YT_WATCHDOG["silent_skip"] = set()    # reset per session
            th.start()

    def _wd_stop() -> None:
        with _YT_WATCHDOG_LOCK:
            ev = _YT_WATCHDOG.get("stop_event")
            th = _YT_WATCHDOG.get("thread")
            _YT_WATCHDOG["running"] = False
        if ev is not None:
            try:
                ev.set()
            except Exception:
                pass
        if th is not None:
            try:
                th.join(timeout=1.5)
            except Exception:
                pass
        with _YT_WATCHDOG_LOCK:
            _YT_WATCHDOG["thread"] = None
            _YT_WATCHDOG["stop_event"] = None
            _YT_WATCHDOG["current"] = ""

    st.session_state.setdefault("yt_bg_active", False)
    st.session_state.setdefault("yt_bg_queue", [])
    st.session_state.setdefault("yt_bg_done", 0)
    st.session_state.setdefault("yt_bg_total", 0)
    st.session_state.setdefault("yt_bg_current_idx", -1)
    st.session_state.setdefault("yt_bg_force", False)
    st.session_state.setdefault("yt_bg_mode", "")
    st.session_state.setdefault("yt_bg_proc", None)
    st.session_state.setdefault("yt_bg_log_file", "")

    rows = _read_db()
    rows, rows_changed = _merge_rows_with_results_json(rows)
    if rows_changed:
        _write_db(rows)
    st.session_state.yt_rows_cache = list(rows)
    rows = list(rows)

    add_c1, add_c2 = st.columns([6, 2])
    new_url = add_c1.text_input("Neuer YouTube-Link", key="yt_new_url_input", placeholder="https://www.youtube.com/watch?v=...")
    add_clicked = add_c2.button("Link hinzufügen", width="stretch", key="yt_add_link_btn")

    if add_clicked:
        u = str(new_url or "").strip()
        if not u:
            set_status("Bitte einen YouTube-Link eingeben.", "warn")
        elif any(str(r.get("youtube_link") or "").strip() == u for r in rows):
            set_status("Link bereits vorhanden.", "warn")
        else:
            rows.append(
                {
                    "youtube_link": u,
                    "title": "",
                    "upload_date": "",
                    "capture_folder": "",
                    "download_status": "pending",
                    "last_error": "",
                    "downloaded_at": "",
                }
            )
            st.session_state.yt_rows_cache = rows
            _write_db(rows)
            st.rerun()

    wd_running_pre = bool(watchdog_snapshot().get("running"))
    b1, b2, b3 = st.columns(3)
    dl_pending = b1.button(
        "Noch nicht heruntergeladene Videos herunterladen",
        width="stretch",
        key="yt_dl_pending_btn",
        disabled=wd_running_pre,
    )
    dl_faulty = b2.button(
        "Fehlerhafte Videos nochmal herunterladen",
        width="stretch",
        key="yt_dl_faulty_btn",
        disabled=wd_running_pre,
    )
    stop_bg = b3.button("Download-Queue stoppen", width="stretch", key="yt_dl_stop_btn", disabled=not bool(st.session_state.get("yt_bg_active")))

    st.session_state.setdefault("yt_watchdog_cmd", "")
    st.session_state.setdefault("yt_watchdog_interval_sec_cmd", 10)
    st.session_state.setdefault("yt_watchdog_task_mat_json", False)
    st.session_state.setdefault("yt_watchdog_task_download", False)
    st.session_state.setdefault("yt_watchdog_task_ocr", True)
    _wd_cmd = str(st.session_state.get("yt_watchdog_cmd") or "").strip().lower()
    if _wd_cmd == "start":
        _intv = int(st.session_state.get("yt_watchdog_interval_sec_cmd", 20) or 20)
        _wd_start(max(2, min(300, _intv)))
        st.session_state.yt_watchdog_cmd = ""
    elif _wd_cmd == "stop":
        _wd_stop()
        st.session_state.yt_watchdog_cmd = ""

    st.caption("Watchdog-Steuerung und Dashboard sind im separaten Tab `Watchdog`.")

    # Flush folders successfully re-downloaded by the watchdog thread.
    with _YT_WATCHDOG_LOCK:
        _wd_cleared = set(_YT_WATCHDOG.pop("clear_faulty_folders", set()))
    if _wd_cleared:
        ov_rows = list(st.session_state.get("mat_overview_rows") or [])
        _ov_changed = False
        for _i, _rr in enumerate(ov_rows):
            if str(_rr.get("mat_datei") or "").strip() in _wd_cleared:
                if _rr.get("video_fehlerhaft") not in ("", None, "Nein", "False", "false", "0"):
                    ov_rows[_i] = {**_rr, "video_fehlerhaft": ""}
                    _ov_changed = True
        if _ov_changed:
            st.session_state.mat_overview_rows = ov_rows

    faulty_folders = set()
    for rr in list(st.session_state.get("mat_overview_rows") or []):
        try:
            if _overview_status_true(rr.get("video_fehlerhaft")):
                cf = str(rr.get("mat_datei") or "").strip()
                if cf:
                    faulty_folders.add(cf)
        except Exception:
            pass

    progress_slot = st.empty()
    state_slot = st.empty()

    def _clear_mat_overview_faulty(folder: str) -> None:
        """Clear video_fehlerhaft in session-state mat_overview_rows for a given folder."""
        folder = str(folder or "").strip()
        if not folder:
            return
        ov_rows = list(st.session_state.get("mat_overview_rows") or [])
        changed = False
        for i, rr in enumerate(ov_rows):
            if str(rr.get("mat_datei") or "").strip() == folder:
                if rr.get("video_fehlerhaft") not in ("", None, "Nein", "False", "false", "0"):
                    ov_rows[i] = {**rr, "video_fehlerhaft": ""}
                    changed = True
        if changed:
            st.session_state.mat_overview_rows = ov_rows

    def _bg_pick_indices(select_fn) -> list[int]:
        out = []
        for i, r in enumerate(rows):
            try:
                if select_fn(r):
                    out.append(i)
            except Exception:
                pass
        return out

    def _bg_start(indices: list[int], *, force: bool, mode: str):
        if not indices:
            set_status("Keine passenden Einträge gefunden.", "warn")
            return
        st.session_state.yt_bg_active = True
        st.session_state.yt_bg_queue = list(indices)
        st.session_state.yt_bg_done = 0
        st.session_state.yt_bg_total = len(indices)
        st.session_state.yt_bg_current_idx = -1
        st.session_state.yt_bg_force = bool(force)
        st.session_state.yt_bg_mode = str(mode or "")
        st.session_state.yt_bg_proc = None
        st.session_state.yt_bg_log_file = ""
        for i in indices:
            rows[i]["download_status"] = "downloading"
        st.session_state.yt_rows_cache = rows
        _write_db(rows)

    def _bg_stop():
        proc = st.session_state.get("yt_bg_proc")
        if proc is not None:
            try:
                if proc.poll() is None:
                    proc.terminate()
            except Exception:
                pass
        st.session_state.yt_bg_active = False
        st.session_state.yt_bg_queue = []
        st.session_state.yt_bg_proc = None
        st.session_state.yt_bg_log_file = ""
        set_status("Download-Queue gestoppt.", "warn")

    def _parse_log(path: Path) -> dict:
        try:
            txt = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            txt = ""
        return _parse_result_lines(txt)

    def _bg_step():
        if not bool(st.session_state.get("yt_bg_active")):
            return
        q = list(st.session_state.get("yt_bg_queue") or [])
        proc = st.session_state.get("yt_bg_proc")
        if proc is None:
            if not q:
                st.session_state.yt_bg_active = False
                st.session_state.yt_bg_current_idx = -1
                set_status("Download-Queue abgeschlossen.", "ok")
                return
            idx = int(q[0])
            st.session_state.yt_bg_current_idx = idx
            entry = rows[idx]
            url = str(entry.get("youtube_link") or "").strip()
            folder = str(entry.get("capture_folder") or "").strip() or _default_capture_folder()
            rows[idx]["capture_folder"] = folder
            out_video, out_audio = _capture_media_paths(folder)
            cap_dir = out_video.parent
            cap_dir.mkdir(parents=True, exist_ok=True)
            force = bool(st.session_state.get("yt_bg_force"))
            _ex_vid2, _ = _find_existing_media(folder)
            _aud_ok, _ = _ensure_audio_file(folder)
            if (not force) and _ex_vid2 is not None and _aud_ok:
                meta_url = _fetch_metadata_for_url(url)
                rows[idx]["title"] = str(rows[idx].get("title") or meta_url.get("title") or "")
                rows[idx]["upload_date"] = str(rows[idx].get("upload_date") or meta_url.get("pubDate") or "")
                rows[idx]["download_status"] = "downloaded"
                rows[idx]["last_error"] = ""
                rows[idx]["downloaded_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                _ok_meta, _meta_msg = _write_capture_metadata_json(
                    folder,
                    {
                        "youtube_url": str(rows[idx].get("youtube_link") or ""),
                        "video_title": str(rows[idx].get("title") or ""),
                        "video_name": str(folder),
                        "upload_date": str(rows[idx].get("upload_date") or ""),
                        "desc": str(meta_url.get("desc") or ""),
                        "channel_name": str(meta_url.get("chanName") or ""),
                        "downloaded_at": str(rows[idx].get("downloaded_at") or ""),
                    },
                )
                if _ok_meta:
                    rows[idx]["json_path"] = _meta_msg
                else:
                    rows[idx]["last_error"] = f"metadata.json Fehler: {_meta_msg}"
                _clear_mat_overview_faulty(folder)
                q.pop(0)
                st.session_state.yt_bg_queue = q
                st.session_state.yt_bg_done = int(st.session_state.get("yt_bg_done", 0) or 0) + 1
                st.session_state.yt_rows_cache = rows
                _write_db(rows)
                return
            if (not force) and out_video.exists() and (not out_audio.exists() or out_audio.stat().st_size <= 0):
                ok_aud, msg_aud = _ensure_audio_file(folder)
                if ok_aud and out_audio.exists() and out_audio.stat().st_size > 0:
                    meta_url = _fetch_metadata_for_url(url)
                    rows[idx]["title"] = str(rows[idx].get("title") or meta_url.get("title") or "")
                    rows[idx]["upload_date"] = str(rows[idx].get("upload_date") or meta_url.get("pubDate") or "")
                    rows[idx]["download_status"] = "downloaded"
                    rows[idx]["last_error"] = ""
                    rows[idx]["downloaded_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    _ok_meta, _meta_msg = _write_capture_metadata_json(
                        folder,
                        {
                            "youtube_url": str(rows[idx].get("youtube_link") or ""),
                            "video_title": str(rows[idx].get("title") or ""),
                            "video_name": str(folder),
                            "upload_date": str(rows[idx].get("upload_date") or ""),
                            "desc": str(meta_url.get("desc") or ""),
                            "channel_name": str(meta_url.get("chanName") or ""),
                            "downloaded_at": str(rows[idx].get("downloaded_at") or ""),
                            "download_status": "downloaded",
                            "last_error": "",
                        },
                    )
                    if _ok_meta:
                        rows[idx]["json_path"] = _meta_msg
                    _clear_mat_overview_faulty(folder)
                    q.pop(0)
                    st.session_state.yt_bg_queue = q
                    st.session_state.yt_bg_done = int(st.session_state.get("yt_bg_done", 0) or 0) + 1
                    st.session_state.yt_rows_cache = rows
                    _write_db(rows)
                    return
                rows[idx]["download_status"] = "error"
                rows[idx]["last_error"] = f"audio fehlt: {msg_aud}"
                _write_db(rows)
                q.pop(0)
                st.session_state.yt_bg_queue = q
                st.session_state.yt_bg_done = int(st.session_state.get("yt_bg_done", 0) or 0) + 1
                st.session_state.yt_rows_cache = rows
                return
            log_file = Path("logs") / f"yt_job_{folder}_{int(time.time())}.log"
            meta_url_init = _fetch_metadata_for_url(url)
            rows[idx]["title"] = str(rows[idx].get("title") or meta_url_init.get("title") or "")
            rows[idx]["upload_date"] = str(rows[idx].get("upload_date") or meta_url_init.get("pubDate") or "")
            cmd = [
                sys.executable,
                str(rec_script),
                "--url",
                url,
                "--duration",
                "86400",
                "--out",
                _capture_media_stem(folder),
                "--outdir",
                str(cap_dir),
            ]
            if bool(st.session_state.get("yt_open_new_window", True)):
                cmd.append("--new-window")
            if bool(st.session_state.get("yt_move_other_display", False)):
                cmd.append("--other-display")
            with log_file.open("w", encoding="utf-8") as lf:
                popen_kwargs = {
                    "stdout": lf,
                    "stderr": lf,
                    "text": True,
                    "encoding": "utf-8",
                    "errors": "replace",
                }
                if os.name == "nt":
                    popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
                    si = subprocess.STARTUPINFO()
                    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    si.wShowWindow = 0
                    popen_kwargs["startupinfo"] = si
                p = subprocess.Popen(cmd, **popen_kwargs)
            st.session_state.yt_bg_proc = p
            st.session_state.yt_bg_log_file = str(log_file)
            _ok_init_json, _init_json_msg = _write_capture_metadata_json(
                folder,
                {
                    "youtube_url": str(rows[idx].get("youtube_link") or ""),
                    "video_title": str(rows[idx].get("title") or ""),
                    "video_name": str(folder),
                    "upload_date": str(rows[idx].get("upload_date") or ""),
                    "desc": str(meta_url_init.get("desc") or ""),
                    "channel_name": str(meta_url_init.get("chanName") or ""),
                    "downloaded_at": "",
                    "download_status": "downloading",
                    "last_error": "",
                },
            )
            if _ok_init_json:
                rows[idx]["json_path"] = _init_json_msg
            st.session_state.yt_rows_cache = rows
            _write_db(rows)
            return

        rc = proc.poll()
        if rc is None:
            return
        idx = int(st.session_state.get("yt_bg_current_idx") or -1)
        meta = _parse_log(Path(str(st.session_state.get("yt_bg_log_file") or "")))
        if 0 <= idx < len(rows):
            folder_now = str(rows[idx].get("capture_folder") or "").strip()
            url_now = str(rows[idx].get("youtube_link") or "").strip()
            meta_url = _fetch_metadata_for_url(url_now) if url_now else {}
            if rc == 0:
                ok_aud, msg_aud = _ensure_audio_file(folder_now)
                if not ok_aud:
                    rows[idx]["download_status"] = "error"
                    rows[idx]["last_error"] = f"audio fehlt: {msg_aud}"
                    rc = 99
            if rc == 0:
                rows[idx]["download_status"] = "downloaded"
                rows[idx]["last_error"] = ""
                rows[idx]["downloaded_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                rows[idx]["title"] = str(meta.get("RESULT_TITLE") or meta_url.get("title") or rows[idx].get("title") or "")
                rows[idx]["upload_date"] = str(meta.get("RESULT_PUBDATE") or meta_url.get("pubDate") or rows[idx].get("upload_date") or "")
                _ok_meta, _meta_msg = _write_capture_metadata_json(
                    folder_now,
                    {
                        "youtube_url": str(rows[idx].get("youtube_link") or ""),
                        "video_title": str(rows[idx].get("title") or ""),
                        "video_name": str(folder_now),
                        "upload_date": str(rows[idx].get("upload_date") or ""),
                        "desc": str(meta.get("RESULT_DESC") or meta_url.get("desc") or ""),
                        "channel_name": str(meta.get("RESULT_CHANNAME") or meta_url.get("chanName") or ""),
                        "downloaded_at": str(rows[idx].get("downloaded_at") or ""),
                    },
                )
                if _ok_meta:
                    rows[idx]["json_path"] = _meta_msg
                else:
                    rows[idx]["last_error"] = f"metadata.json Fehler: {_meta_msg}"
                _clear_mat_overview_faulty(folder_now)
            else:
                rows[idx]["download_status"] = "error"
                rows[idx]["last_error"] = "record_youtube_cfr.py failed (siehe Logdatei)"
                rows[idx]["title"] = str(meta.get("RESULT_TITLE") or meta_url.get("title") or rows[idx].get("title") or "")
                rows[idx]["upload_date"] = str(meta.get("RESULT_PUBDATE") or meta_url.get("pubDate") or rows[idx].get("upload_date") or "")
                _ok_meta_err, _meta_err_msg = _write_capture_metadata_json(
                    folder_now,
                    {
                        "youtube_url": str(rows[idx].get("youtube_link") or ""),
                        "video_title": str(rows[idx].get("title") or ""),
                        "video_name": str(folder_now),
                        "upload_date": str(rows[idx].get("upload_date") or ""),
                        "desc": str(meta.get("RESULT_DESC") or meta_url.get("desc") or ""),
                        "channel_name": str(meta.get("RESULT_CHANNAME") or meta_url.get("chanName") or ""),
                        "downloaded_at": str(rows[idx].get("downloaded_at") or ""),
                        "download_status": "error",
                        "last_error": str(rows[idx].get("last_error") or ""),
                    },
                )
                if _ok_meta_err:
                    rows[idx]["json_path"] = _meta_err_msg
        q = list(st.session_state.get("yt_bg_queue") or [])
        if q:
            q.pop(0)
        st.session_state.yt_bg_queue = q
        st.session_state.yt_bg_done = int(st.session_state.get("yt_bg_done", 0) or 0) + 1
        st.session_state.yt_bg_proc = None
        st.session_state.yt_bg_log_file = ""
        st.session_state.yt_rows_cache = rows
        _write_db(rows)

    if dl_pending:
        _bg_start(
            _bg_pick_indices(lambda r: str(r.get("download_status") or "pending").lower() != "downloaded"),
            force=False,
            mode="pending",
        )
        st.rerun()
    if dl_faulty:
        _bg_start(
            _bg_pick_indices(lambda r: str(r.get("capture_folder") or "").strip() in faulty_folders),
            force=True,
            mode="faulty",
        )
        st.rerun()
    if stop_bg:
        _bg_stop()
        st.rerun()

    _bg_step()
    if bool(st.session_state.get("yt_bg_active")):
        done = int(st.session_state.get("yt_bg_done", 0) or 0)
        total = int(st.session_state.get("yt_bg_total", 0) or 0)
        cur = int(st.session_state.get("yt_bg_current_idx", -1) or -1)
        cur_url = ""
        if 0 <= cur < len(rows):
            cur_url = str(rows[cur].get("youtube_link") or "")
        state_slot.caption(f"Hintergrund-Queue aktiv ({done}/{total}){': ' + cur_url[:95] if cur_url else ''}")
        st.caption(
            "Hinweis: Der Job-Prozess läuft im Hintergrund ohne Konsolenfenster. "
            "Die Aufnahme selbst benötigt aber weiterhin ein sichtbares/fokussiertes Browser-Fenster "
            "(bedingt durch `pyautogui` + Screen-Capture)."
        )
        if total > 0:
            progress_slot.progress(min(1.0, done / total), text=f"Download-Fortschritt: {done}/{total}")
        time.sleep(0.3)
        st.rerun()
    else:
        state_slot.empty()
        progress_slot.empty()

    if rows:
        df = pd.DataFrame(rows)
        if "download_status" not in df.columns:
            df["download_status"] = "pending"
        df_view = pd.DataFrame(
            {
                "youtube link": df["youtube_link"].astype(str),
                "titel": df.get("title", "").astype(str),
                "datum des uploads": df.get("upload_date", "").astype(str),
                "status heruntergeladen": df["download_status"].map(_status_lamp),
                "capture_folder": df.get("capture_folder", "").astype(str),
                "json path": (df["json_path"] if "json_path" in df.columns else pd.Series([""] * len(df), index=df.index)).astype(str),
                "letzter fehler": df.get("last_error", "").astype(str),
            }
        )
        selected = st.dataframe(
            df_view,
            width="stretch",
            hide_index=True,
            height=360,
            on_select="rerun",
            selection_mode="multi-row",
        )
        selected_rows = []
        try:
            selected_rows = list((selected or {}).get("selection", {}).get("rows", []))
        except Exception:
            selected_rows = []

        st.caption("Zum Löschen: gewünschte Zeilen in der Tabelle anklicken, dann auf `Ausgewählte löschen` klicken.")
        do_delete = st.button(
            "Ausgewählte löschen",
            width="stretch",
            key="yt_delete_links_btn",
            disabled=bool(st.session_state.get("yt_bg_active")) or not bool(selected_rows),
        )
        if do_delete:
            drop_idx = set(int(i) for i in selected_rows if isinstance(i, int))
            keep = [r for i, r in enumerate(rows) if i not in drop_idx]
            st.session_state.yt_rows_cache = keep
            _write_db(keep)
            set_status(f"{len(rows) - len(keep)} Link(s) gelöscht.", "ok")
            st.rerun()
    else:
        st.dataframe(
            pd.DataFrame(columns=["youtube link", "titel", "datum des uploads", "status heruntergeladen", "capture_folder", "json path", "letzter fehler"]),
            width="stretch",
            hide_index=True,
            height=260,
        )

    _last_meta_json_path = str(st.session_state.get("yt_last_meta_json_path") or "").strip()
    if _last_meta_json_path:
        st.caption(f"Zuletzt geschriebene JSON: {_last_meta_json_path}")
