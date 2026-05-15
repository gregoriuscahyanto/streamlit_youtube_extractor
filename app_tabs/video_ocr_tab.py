"""Renderer for full-video frame-by-frame OCR evaluation."""


def render(ns):
    globals().update(ns)
    st.markdown('<div class="section-title">Video OCR Full</div>', unsafe_allow_html=True)
    st.caption("Wertet das Vollvideo frame-by-frame aus (nicht Lite/1fps) und nutzt dieselbe OCR-Methode wie ROI Setup.")

    rois = list(st.session_state.get("rois") or [])
    ocr_rois = [
        r for r in rois
        if str(r.get("name", "")).strip().lower() != "track_minimap"
        and float(r.get("w", 0.0) or 0.0) > 0.0
        and float(r.get("h", 0.0) or 0.0) > 0.0
    ]
    capture_folder = _current_capture_folder() or str(st.session_state.get("capture_folder") or "").strip()
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

    can_run = bool(ocr_rois) and bool(capture_folder) and (full_video is not None)
    progress_slot = st.empty()
    info_slot = st.empty()
    run_clicked = st.button(
        "Video OCR (voll, frame-by-frame) starten",
        type="primary",
        width="stretch",
        key="video_ocr_full_run_btn",
        disabled=not can_run,
    )

    if run_clicked:
        st.session_state.video_ocr_full_running = True
        st.session_state.roi_ocr_full_running = True
        try:
            with st.spinner("Video OCR läuft über alle Frames ..."):
                def _on_progress(done: int, total: int, t_s: float) -> None:
                    total_n = max(1, int(total or 0))
                    done_n = int(done or 0)
                    progress_slot.progress(
                        min(1.0, done_n / total_n),
                        text=f"{done_n}/{total_n} Frames | t={float(t_s):.2f}s",
                    )
                    info_slot.caption(f"Aktueller Frame: {done_n}")

                ok, msg, res = _run_video_ocr_fullvideo_framewise_now(progress_cb=_on_progress)
            st.session_state.video_ocr_full_result = res
            set_status(msg, "ok" if ok else "warn")
        finally:
            st.session_state.video_ocr_full_running = False
            st.session_state.roi_ocr_full_running = False

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
