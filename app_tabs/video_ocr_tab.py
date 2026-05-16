"""Renderer for full-video frame-by-frame OCR evaluation."""


def render(ns):
    globals().update(ns)
    st.markdown('<div class="section-title">Video OCR Full</div>', unsafe_allow_html=True)
    st.caption("Wertet das Vollvideo frame-by-frame aus (nicht Lite/1fps) und nutzt dieselbe OCR-Methode wie ROI Setup.")

    st.session_state.setdefault("video_ocr_full_future", None)
    st.session_state.setdefault("video_ocr_full_stop_event", None)
    st.session_state.setdefault("video_ocr_full_stop_requested", False)
    st.session_state.setdefault("video_ocr_full_progress", {})
    st.session_state.setdefault("video_ocr_full_live_rows", [])

    def _is_running() -> bool:
        fut = st.session_state.get("video_ocr_full_future")
        return fut is not None and (not fut.done())

    fut = st.session_state.get("video_ocr_full_future")
    if fut is not None and fut.done():
        try:
            out = fut.result()
            ok = bool((out or {}).get("ok"))
            msg = str((out or {}).get("msg") or "")
            res = (out or {}).get("res") or {}
            st.session_state.video_ocr_full_result = res
            set_status(msg or ("OCR beendet." if ok else "OCR fehlgeschlagen."), "ok" if ok else "warn")
        except Exception as e:
            set_status(f"OCR Hintergrundfehler: {e}", "warn")
        finally:
            st.session_state.video_ocr_full_future = None
            st.session_state.video_ocr_full_stop_event = None
            st.session_state.video_ocr_full_stop_requested = False
            st.session_state.video_ocr_full_running = False
            st.session_state.roi_ocr_full_running = False

    # ── Watchdog OCR live indicator ───────────────────────────────────────────
    try:
        from app_tabs.youtube_tab import watchdog_snapshot
        wd_snap = watchdog_snapshot()
        wd_running = bool(wd_snap.get("running"))
        wd_current = str(wd_snap.get("current") or "")
        capture_folder_now = _current_capture_folder() or str(st.session_state.get("capture_folder") or "").strip()
        wd_ocr_active = wd_running and "OCR" in wd_current and capture_folder_now and capture_folder_now in wd_current
    except Exception:
        wd_running = False
        wd_current = ""
        wd_ocr_active = False

    if wd_ocr_active:
        st.info(
            f"**Watchdog läuft automatisiert:** {wd_current}\n\n"
            "OCR wird im Hintergrund durchgeführt. Manuelle Auswertung ist währenddessen deaktiviert.",
            icon="🤖",
        )
    elif wd_running:
        st.caption(f"Watchdog aktiv (anderer Task): {wd_current or '—'}")

    def _scalar(v, default: float = 0.0) -> float:
        if isinstance(v, (list, tuple)):
            v = v[0] if v else default
        try:
            return float(v) if v is not None else default
        except Exception:
            return default

    rois = list(st.session_state.get("rois") or [])
    ocr_rois = [
        r for r in rois
        if str(r.get("name", "")).strip().lower() != "track_minimap"
        and _scalar(r.get("w")) > 0.0
        and _scalar(r.get("h")) > 0.0
    ]
    capture_folder = capture_folder_now if "capture_folder_now" in dir() else (
        _current_capture_folder() or str(st.session_state.get("capture_folder") or "").strip()
    )
    full_video = _find_local_fullfps_video(capture_folder) if capture_folder else None

    if not ocr_rois:
        st.warning("Keine OCR-ROI vorhanden. Bitte zuerst im Tab ROI Setup ROI definieren/speichern.")
    if not capture_folder:
        st.warning("Kein capture_folder aktiv. Bitte zuerst MAT/JSON auswählen.")
    if capture_folder and full_video is None:
        st.warning("Kein Vollvideo gefunden. Bitte zuerst Originalvideo lokal herunterladen/laden.")

    st.caption(f"Capture Folder: {capture_folder or '-'}")
    st.caption(f"Vollvideo: {str(full_video) if full_video is not None else '-'}")
    st.caption(f"OCR-ROI (ohne track_minimap): {len(ocr_rois)}")

    can_run = bool(ocr_rois) and bool(capture_folder) and (full_video is not None) and not wd_ocr_active
    running = _is_running()
    stop_requested = bool(st.session_state.get("video_ocr_full_stop_requested"))

    c1, c2 = st.columns(2)
    run_clicked = c1.button(
        "Video OCR (voll, frame-by-frame) starten",
        type="primary",
        width="stretch",
        key="video_ocr_full_run_btn",
        disabled=(not can_run) or running or stop_requested or wd_ocr_active,
    )
    stop_clicked = c2.button(
        "OCR stoppen",
        width="stretch",
        key="video_ocr_full_stop_btn",
        disabled=not running,
    )

    if run_clicked and can_run and (not running):
        st.session_state.video_ocr_full_running = True
        st.session_state.roi_ocr_full_running = True
        st.session_state.video_ocr_full_stop_requested = False
        st.session_state.video_ocr_full_progress = {"done": 0, "total": 1, "t_s": 0.0}
        st.session_state.video_ocr_full_live_rows = []
        stop_event = threading.Event()

        progress_ref = st.session_state.video_ocr_full_progress
        rows_ref = st.session_state.video_ocr_full_live_rows

        def _worker():
            def _on_progress(done: int, total: int, t_s: float, snapshot: dict | None = None) -> None:
                progress_ref.update({
                    "done": int(done or 0),
                    "total": int(max(1, int(total or 0))),
                    "t_s": float(t_s or 0.0),
                })
                if isinstance(snapshot, dict) and snapshot:
                    rows_ref.append(dict(snapshot))
                    if len(rows_ref) > 120:
                        del rows_ref[:-120]

            def _stop_cb() -> bool:
                return bool(stop_event.is_set())

            ok, msg, res = _run_video_ocr_fullvideo_framewise_now(progress_cb=_on_progress, stop_cb=_stop_cb)
            return {"ok": bool(ok), "msg": str(msg or ""), "res": res}

        st.session_state.video_ocr_full_stop_event = stop_event
        st.session_state.video_ocr_full_future = _video_ocr_executor().submit(_worker)
        running = True

    if stop_clicked and running:
        st.session_state.video_ocr_full_stop_requested = True
        ev = st.session_state.get("video_ocr_full_stop_event")
        if ev is not None:
            try:
                ev.set()
            except Exception:
                pass
        set_status("OCR-Stop angefordert ...", "warn")

    prog = dict(st.session_state.get("video_ocr_full_progress") or {})
    done_n = int(prog.get("done", 0) or 0)
    total_n = int(max(1, int(prog.get("total", 1) or 1)))
    t_s = float(prog.get("t_s", 0.0) or 0.0)
    st.progress(min(1.0, done_n / total_n), text=f"{done_n}/{total_n} Frames | t={t_s:.2f}s")

    st.caption("Live-Progress (OCR-Werte je Update, inkl. Track-Minimap wenn vorhanden):")
    live_rows = list(st.session_state.get("video_ocr_full_live_rows") or [])
    if live_rows:
        st.dataframe(pd.DataFrame(live_rows), width="stretch", hide_index=True, height=320)
    else:
        st.dataframe(pd.DataFrame(columns=["frame_idx", "time_s"]), width="stretch", hide_index=True, height=220)

    last = st.session_state.get("video_ocr_full_result") or {}
    if isinstance(last, dict) and last:
        if bool(last.get("ok")):
            st.caption(
                f"Zuletzt: rows={int(last.get('rows', 0) or 0)} | "
                f"frames={int(last.get('frames_processed', 0) or 0)}/{int(last.get('frames_total', 0) or 0)} | "
                f"json={str(last.get('json_key', '') or '-')}"
            )
        else:
            st.caption(f"Letzter Lauf fehlgeschlagen: {str(last.get('error', ''))}")

    if running or _is_running():
        time.sleep(0.25)
        st.rerun()
