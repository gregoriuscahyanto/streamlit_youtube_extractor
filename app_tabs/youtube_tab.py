"""YouTube download management tab using scripts/record_youtube_cfr.py."""


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

    def _capture_base() -> Path:
        lp = str(st.session_state.get("local_base_path") or "").strip()
        if lp:
            return Path(lp).expanduser().resolve()
        return Path.cwd()

    st.caption(f"JSON-Zielpfad: {_capture_base() / 'results'}")
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

    def _capture_media_paths(folder: str) -> tuple[Path, Path]:
        folder = str(folder or "").strip()
        cap_dir = _capture_base() / "captures" / folder
        stem = f"screen_{folder}_audio"
        return cap_dir / f"{stem}.avi", cap_dir / f"{stem}.wav"

    def _capture_media_stem(folder: str) -> str:
        folder = str(folder or "").strip()
        return f"screen_{folder}_audio"

    def _write_capture_metadata_json(folder: str, meta: dict) -> tuple[bool, str]:
        folder = str(folder or "").strip()
        if not folder:
            return False, "capture_folder fehlt"
        base = _capture_base()
        res_dir = base / "results"
        res_dir.mkdir(parents=True, exist_ok=True)
        out_video, out_audio = _capture_media_paths(folder)
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
        payload = {
            "recordResult": {
                "metadata": {
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
            }
        }
        path = res_dir / f"results_{folder}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        if not path.exists():
            return False, f"JSON nicht geschrieben: {path}"
        st.session_state.yt_last_meta_json_path = str(path)
        set_status(f"JSON gespeichert: {path}", "ok")
        return True, str(path)

    def _ensure_audio_file(folder: str) -> tuple[bool, str]:
        out_video, out_audio = _capture_media_paths(folder)
        if out_audio.exists() and out_audio.stat().st_size > 0:
            return True, str(out_audio)
        if not out_video.exists() or out_video.stat().st_size <= 0:
            return False, "video fehlt"
        try:
            ffmpeg_exe = __import__("shutil").which("ffmpeg")
        except Exception:
            ffmpeg_exe = None
        if ffmpeg_exe:
            try:
                cmd = [ffmpeg_exe, "-y", "-i", str(out_video), "-vn", "-ac", "1", "-ar", "48000", str(out_audio)]
                p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
                if p.returncode == 0 and out_audio.exists() and out_audio.stat().st_size > 0:
                    return True, str(out_audio)
                return False, "ffmpeg konnte kein Audio extrahieren"
            except Exception:
                return False, "ffmpeg-Aufruf fehlgeschlagen"
        return False, "kein echtes Audio gefunden (kein Platzhalter erzeugt)"

    def _download_one(entry: dict, force: bool = False) -> tuple[bool, str, dict]:
        url = str(entry.get("youtube_link") or "").strip()
        if not url:
            return False, "leerer link", {}
        if not rec_script.exists():
            return False, f"Script fehlt: {rec_script}", {}

        folder = str(entry.get("capture_folder") or "").strip()
        if not folder:
            folder = _default_capture_folder()
        out_video, out_audio = _capture_media_paths(folder)
        cap_dir = out_video.parent
        cap_dir.mkdir(parents=True, exist_ok=True)
        if (not force) and out_video.exists() and out_audio.exists() and out_video.stat().st_size > 0 and out_audio.stat().st_size > 0:
            return True, "bereits vorhanden", {"RESULT_VIDEO": str(out_video), "RESULT_AUDIO": str(out_audio)}

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
        p = subprocess.run(cmd, **run_kwargs)
        txt = (p.stdout or "") + "\n" + (p.stderr or "")
        parsed = _parse_result_lines(txt)
        if p.returncode != 0:
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
            ok_aud, msg_aud = _ensure_audio_file(folder)
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
    if "yt_rows_cache" not in st.session_state:
        st.session_state.yt_rows_cache = rows
    rows = list(st.session_state.get("yt_rows_cache") or [])

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

    b1, b2, b3 = st.columns(3)
    dl_pending = b1.button("Noch nicht heruntergeladene Videos herunterladen", width="stretch", key="yt_dl_pending_btn")
    dl_faulty = b2.button("Fehlerhafte Videos nochmal herunterladen", width="stretch", key="yt_dl_faulty_btn")
    stop_bg = b3.button("Download-Queue stoppen", width="stretch", key="yt_dl_stop_btn", disabled=not bool(st.session_state.get("yt_bg_active")))

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
            if (not force) and out_video.exists() and out_audio.exists() and out_video.stat().st_size > 0 and out_audio.stat().st_size > 0:
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
            pd.DataFrame(columns=["youtube link", "titel", "datum des uploads", "status heruntergeladen", "capture_folder", "letzter fehler"]),
            width="stretch",
            hide_index=True,
            height=260,
        )

    _last_meta_json_path = str(st.session_state.get("yt_last_meta_json_path") or "").strip()
    if _last_meta_json_path:
        st.caption(f"Zuletzt geschriebene JSON: {_last_meta_json_path}")

