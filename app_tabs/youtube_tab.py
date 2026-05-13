"""YouTube download management tab using scripts/record_youtube_cfr.py."""


def render(ns):
    globals().update(ns)
    st.markdown('<div class="section-title">YouTube Download Manager</div>', unsafe_allow_html=True)
    st.caption("Rein Python: Download über scripts/record_youtube_cfr.py (kein MATLAB, kein yt-dlp im App-Flow).")

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

    def _parse_result_lines(output: str) -> dict:
        out = {}
        for line in (output or "").splitlines():
            t = line.strip()
            if t.startswith("RESULT_") and ":" in t:
                k, v = t.split(":", 1)
                out[k.strip()] = v.strip()
        return out

    def _download_one(entry: dict, force: bool = False) -> tuple[bool, str, dict]:
        url = str(entry.get("youtube_link") or "").strip()
        if not url:
            return False, "leerer link", {}
        if not rec_script.exists():
            return False, f"Script fehlt: {rec_script}", {}

        folder = str(entry.get("capture_folder") or "").strip()
        if not folder:
            folder = f"yt_{int(time.time())}"
        cap_dir = _capture_base() / "captures" / folder
        cap_dir.mkdir(parents=True, exist_ok=True)
        out_video = cap_dir / "video.avi"
        out_audio = cap_dir / "audio.wav"
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
            "capture",
            "--outdir",
            str(cap_dir),
        ]
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        txt = (p.stdout or "") + "\n" + (p.stderr or "")
        parsed = _parse_result_lines(txt)
        if p.returncode != 0:
            return False, txt.strip()[-500:], parsed

        src_v = str(parsed.get("RESULT_VIDEO") or "").strip()
        src_a = str(parsed.get("RESULT_AUDIO") or "").strip()
        if src_v and Path(src_v).exists():
            try:
                Path(src_v).replace(out_video)
            except Exception:
                pass
        if src_a and Path(src_a).exists():
            try:
                Path(src_a).replace(out_audio)
            except Exception:
                pass
        if not out_video.exists() or not out_audio.exists():
            return False, "video/audio nicht vollständig erzeugt", parsed
        return True, "ok", parsed

    def _status_lamp(s: str) -> str:
        t = str(s or "").strip().lower()
        if t == "downloaded":
            return "🟢 Ja"
        if t == "error":
            return "🔴 Fehler"
        if t == "downloading":
            return "🟡 Läuft"
        return "⚪ Nein"

    rows = _read_db()
    if "yt_rows_cache" not in st.session_state:
        st.session_state.yt_rows_cache = rows
    rows = list(st.session_state.get("yt_rows_cache") or [])

    add_c1, add_c2, add_c3 = st.columns([4, 2, 2])
    new_url = add_c1.text_input("Neuer YouTube-Link", key="yt_new_url_input", placeholder="https://www.youtube.com/watch?v=...")
    new_folder = add_c2.text_input("Capture Folder (optional)", key="yt_new_folder_input", placeholder="z.B. abc123")
    add_clicked = add_c3.button("Link hinzufügen", width="stretch", key="yt_add_link_btn")

    if add_clicked:
        u = str(new_url or "").strip()
        cf = str(new_folder or "").strip()
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
                    "capture_folder": cf,
                    "download_status": "pending",
                    "last_error": "",
                    "downloaded_at": "",
                }
            )
            st.session_state.yt_rows_cache = rows
            _write_db(rows)
            st.rerun()

    b1, b2 = st.columns(2)
    dl_pending = b1.button("Noch nicht heruntergeladene Videos herunterladen", width="stretch", key="yt_dl_pending_btn")
    dl_faulty = b2.button("Fehlerhafte Videos nochmal herunterladen", width="stretch", key="yt_dl_faulty_btn")

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

    def _run_batch(select_fn, force: bool):
        selected = [r for r in rows if select_fn(r)]
        if not selected:
            set_status("Keine passenden Einträge gefunden.", "warn")
            return
        total = len(selected)
        ok_n = 0
        err_n = 0
        for i, r in enumerate(rows):
            if r in selected:
                rows[i]["download_status"] = "downloading"
        st.session_state.yt_rows_cache = rows
        _write_db(rows)

        for idx, s in enumerate(selected, 1):
            u = str(s.get("youtube_link") or "")
            state_slot.caption(f"Download {idx}/{total}: {u[:95]}")
            okd, msgd, meta = _download_one(s, force=force)
            for i, r in enumerate(rows):
                if r is s:
                    if okd:
                        ok_n += 1
                        rows[i]["download_status"] = "downloaded"
                        rows[i]["last_error"] = ""
                        rows[i]["downloaded_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        if meta:
                            rows[i]["title"] = str(meta.get("RESULT_TITLE") or rows[i].get("title") or "")
                            rows[i]["upload_date"] = str(meta.get("RESULT_PUBDATE") or rows[i].get("upload_date") or "")
                            rows[i]["capture_folder"] = str(rows[i].get("capture_folder") or Path(str(meta.get("RESULT_VIDEO") or "")).parent.name)
                    else:
                        err_n += 1
                        rows[i]["download_status"] = "error"
                        rows[i]["last_error"] = str(msgd)
                    break
            progress_slot.progress(idx / max(total, 1), text=f"Download-Fortschritt: {idx}/{total}")
            st.session_state.yt_rows_cache = rows
            _write_db(rows)
        state_slot.empty()
        progress_slot.empty()
        set_status(f"Download fertig: {ok_n} OK, {err_n} Fehler.", "warn" if err_n else "ok")
        st.rerun()

    if dl_pending:
        _run_batch(lambda r: str(r.get("download_status") or "pending").lower() != "downloaded", force=False)
    if dl_faulty:
        _run_batch(lambda r: str(r.get("capture_folder") or "").strip() in faulty_folders, force=True)

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
                "letzter fehler": df.get("last_error", "").astype(str),
            }
        )
        st.dataframe(df_view, width="stretch", hide_index=True, height=360)
    else:
        st.dataframe(
            pd.DataFrame(columns=["youtube link", "titel", "datum des uploads", "status heruntergeladen", "capture_folder", "letzter fehler"]),
            width="stretch",
            hide_index=True,
            height=260,
        )
