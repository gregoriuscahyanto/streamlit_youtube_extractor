"""Renderer for the Streamlit tab extracted from app.py.

The renderer receives app.py globals so existing helper functions and
session-state conventions remain shared during the incremental split.
"""

def render(ns):
    globals().update(ns)
    mat_request_rerun = False
    filter_info_slot = st.empty()
    st.markdown('<div class="section-card mat-selection-no-scroll">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">JSON-Auswahl und Analyse</div>', unsafe_allow_html=True)
    st.markdown(
        """
        <div style="
            margin: .45rem 0 .75rem 0;
            padding: .55rem .75rem;
            border: 1px solid #2b4f77;
            border-radius: 6px;
            background: #0b1524;
            color: #cfeaff;
            font-family: 'JetBrains Mono', monospace;
            font-size: .68rem;
            line-height: 1.45;
        ">
          <b>JSON-only Auswahl aktiv:</b> Es werden nur <code>results_*.json</code> aus <code>results/</code> berücksichtigt.
          MAT-Dateien werden in diesem Tab nicht mehr berücksichtigt.
        </div>
        """,
        unsafe_allow_html=True,
    )

    connected = st.session_state.r2_connected and st.session_state.r2_client is not None
    if connected and st.session_state.mat_scan_prefix != st.session_state.r2_prefix:
        _refresh_mat_files()
        st.session_state.mat_auto_updated_prefix = None

    mat_targets = st.session_state.mat_targets if connected else []
    running = bool(st.session_state.mat_update_running)
    load_running = bool(st.session_state.mat_load_running)

    def _start_update_clicked():
        if not connected or load_running:
            return
        _refresh_mat_files()
        _targets = st.session_state.mat_targets
        st.session_state.mat_auto_updated_prefix = st.session_state.r2_prefix
        if _targets:
            _start_mat_update(_targets)
            st.session_state.mat_update_event_queue = queue.Queue()
            st.session_state.mat_update_stop_event = threading.Event()
            st.session_state.mat_update_future = _mat_update_executor().submit(
                _mat_update_worker,
                list(st.session_state.mat_update_keys or []),
                st.session_state.r2_client,
                st.session_state.r2_prefix.strip("/"),
                st.session_state.mat_update_stop_event,
                st.session_state.mat_update_event_queue,
            )
            set_status(f"Analyse gestartet ({len(_targets)} Eintraege).", "info")
        else:
            st.session_state.mat_run_state = "idle"
            set_status("Keine JSON-Dateien gefunden.", "warn")

    def _stop_update_clicked():
        st.session_state.mat_update_stop_requested = True
        _ev = st.session_state.get("mat_update_stop_event")
        if _ev is not None:
            try:
                _ev.set()
            except Exception:
                pass
        set_status("Stop angefordert: Aktualisierung wird beendet ...", "warn")

    progress_slot = st.empty()
    table_slot = st.empty()
    phase_slot = st.empty()

    c1, c2, c3, c4 = st.columns(4)
    update_clicked = c1.button(
        "Update",
        width="stretch",
        key="mat_update_tab",
        disabled=(not connected) or load_running or running,
    )
    stop_clicked = c2.button(
        "Stop",
        width="stretch",
        key="mat_stop_tab",
        disabled=not running,
    )
    if update_clicked:
        if connected and (not load_running):
            _refresh_mat_files()
            _targets = st.session_state.mat_targets
            st.session_state.mat_auto_updated_prefix = st.session_state.r2_prefix
            if _targets:
                st.session_state.mat_update_stop_requested = False
                set_status(f"Analyse gestartet ({len(_targets)} Eintraege).", "info")
                phase_slot.caption("Live-Update aktiv: Ampeln werden zeilenweise aktualisiert ...")
                _update_all_mat_overview_rows(_targets, live_table=table_slot, progress_slot=progress_slot)
                phase_slot.empty()
                set_status("Analyse abgeschlossen.", "ok")
            else:
                st.session_state.mat_run_state = "idle"
                set_status("Keine JSON-Dateien gefunden.", "warn")
        st.rerun()
    if stop_clicked:
        _stop_update_clicked()
        st.rerun()
    # Button soll nach Update/Filter nicht durch einen veralteten Selection-State
    # blockiert werden. Ob wirklich eine sichtbare JSON-Zeile gewaehlt ist, wird
    # beim Klick gegen die aktuell sichtbare Tabelle validiert.
    can_load = (
        connected
        and bool(st.session_state.mat_overview_rows)
        and not running
        and not load_running
    )
    load_clicked = c3.button(
        "JSON + Video laden",
        type="primary",
        width="stretch",
        key="mat_load_all_tab",
        disabled=not can_load,
    )
    excel_rows = list(st.session_state.get("mat_overview_rows") or [])
    try:
        title_excel_bytes = _build_youtube_title_excel_bytes(excel_rows) if excel_rows else b""
    except Exception:
        title_excel_bytes = b""
    c4.download_button(
        "YouTube-Titel Excel",
        data=title_excel_bytes,
        file_name=f"youtube_titles_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
        key="mat_youtube_title_excel_btn",
        disabled=not bool(title_excel_bytes),
        help="Laedt direkt eine Excel-Datei fuer den Match mit der Fahrzeugdatenbank herunter. Es wird nichts in die Cloud gespeichert.",
    )

    

    # Auto-Analyse deaktiviert: Analyse nur explizit per Update-Button starten.
    # Worker-Queue pollen und Tabelle fortlaufend aktualisieren.
    running_now = bool(st.session_state.get("mat_update_running"))
    has_active_future = st.session_state.get("mat_update_future") is not None
    has_pending_run = int(st.session_state.get("mat_update_total", 0) or 0) > 0 and int(st.session_state.get("mat_update_idx", 0) or 0) < int(st.session_state.get("mat_update_total", 0) or 0)
    show_live_run = bool(running_now or has_active_future or has_pending_run)

    if show_live_run:
        if (not st.session_state.get("mat_overview_rows")) and st.session_state.get("mat_update_keys"):
            st.session_state.mat_overview_rows = [
                _placeholder_overview_row(t) for t in list(st.session_state.get("mat_update_keys") or [])
            ]
        phase_slot.caption(
            f"Live-Update aktiv: {len(list(st.session_state.get('mat_overview_rows') or []))} Zeilen sichtbar, "
            f"{len(list(st.session_state.get('mat_update_keys') or []))} Ziele in Queue."
        )
        q_ev = st.session_state.get("mat_update_event_queue")
        if q_ev is not None:
            while True:
                try:
                    ev = q_ev.get_nowait()
                except Exception:
                    break
                et = str((ev or {}).get("type", ""))
                if et == "row":
                    idx = int(ev.get("idx", -1))
                    folder = str(ev.get("folder", "") or "")
                    summary = dict(ev.get("summary") or {})
                    if idx >= 0 and idx < len(st.session_state.mat_overview_rows):
                        st.session_state.mat_overview_rows[idx] = _summary_to_overview_row(summary, display_folder=folder)
                    st.session_state.mat_update_idx = max(int(st.session_state.get("mat_update_idx", 0) or 0), idx + 1)
                    mk = str(ev.get("mat_key", "") or "")
                    if mk:
                        cache = st.session_state.get("mat_summary_cache")
                        if not isinstance(cache, dict):
                            cache = {}
                        cache[mk] = summary
                        st.session_state.mat_summary_cache = cache
                elif et == "done":
                    st.session_state.mat_update_running = False
                    st.session_state.mat_run_state = "idle"
                    st.session_state.mat_update_future = None
                    st.session_state.mat_update_stop_event = None
                    st.session_state.mat_update_event_queue = None
                    set_status("Analyse abgeschlossen.", "ok")
                elif et == "stopped":
                    st.session_state.mat_update_running = False
                    st.session_state.mat_run_state = "idle"
                    st.session_state.mat_update_future = None
                    st.session_state.mat_update_stop_event = None
                    st.session_state.mat_update_event_queue = None
                    set_status("Aktualisierung gestoppt.", "warn")
                elif et == "error":
                    st.session_state.mat_update_running = False
                    st.session_state.mat_run_state = "idle"
                    st.session_state.mat_update_future = None
                    st.session_state.mat_update_stop_event = None
                    st.session_state.mat_update_event_queue = None
                    set_status(f"Analysefehler: {ev.get('error', 'unbekannt')}", "warn")
        done = int(st.session_state.get("mat_update_idx", 0) or 0)
        total = int(st.session_state.get("mat_update_total", 0) or 0)
        if total > 0:
            progress_slot.progress(
                min(1.0, done / total),
                text=f"Analysefortschritt: {done}/{total} ({int((done/max(1,total))*100)}%) · {max(0, total-done)} offen",
            )
        try:
            _run_df = pd.DataFrame(st.session_state.get("mat_overview_rows") or [])
            if not _run_df.empty:
                _run_df = _normalize_overview_lamps(_run_df)
                table_slot.dataframe(
                    _run_df.drop(columns=["remote_key"], errors="ignore"),
                    width="stretch",
                    hide_index=True,
                    height=MAT_TABLE_HEIGHT,
                    column_config=MAT_OVERVIEW_COLCFG,
                )
        except Exception:
            pass
        if bool(st.session_state.get("mat_update_running")):
            time.sleep(0.05)
            mat_request_rerun = True
    else:
        phase_slot.empty()

    json_created = int(st.session_state.get("mat_json_sidecar_created_count", 0) or 0)
    json_used = int(st.session_state.get("mat_json_sidecar_used_count", 0) or 0)
    if json_created:
        st.success(f"JSON-Cache aktualisiert: {json_created} JSON-Sidecar(s) automatisch erzeugt.")
    elif json_used:
        st.caption(f"JSON-Cache aktiv: {json_used} vorhandene JSON-Sidecar(s) fuer die schnelle Analyse verwendet.")

    if not connected:
        st.caption("Erst in Tab 'Verbindung & Root' verbinden und Projektroot waehlen.")

    current_selected_key = str(st.session_state.get("mat_pending_selected_key", "") or "")

    overview_rows = list(st.session_state.get("mat_overview_rows") or [])
    if (not overview_rows) and show_live_run and st.session_state.get("mat_update_keys"):
        overview_rows = [_placeholder_overview_row(t) for t in list(st.session_state.get("mat_update_keys") or [])]
        st.session_state.mat_overview_rows = list(overview_rows)

    if overview_rows:
        df_overview = pd.DataFrame(overview_rows)
        df_overview = _normalize_overview_lamps(df_overview)
        is_running_now = bool(show_live_run)
        filter_missing_roi = st.checkbox(
            "Nur Fälle anzeigen: ROI fehlt und Audio+Video vorhanden",
            value=False,
            key="mat_filter_missing_roi_with_media",
            disabled=is_running_now,
        )
        hide_no_roi_stamped = st.checkbox(
            "Fälle ausblenden, wo kein ROI vorhanden ist",
            value=True,
            key="mat_hide_no_roi_stamped",
            help="Wenn aktiv, werden als 'kein ROI vorhanden' markierte Videos in MAT Selection nicht angezeigt.",
            disabled=is_running_now,
        )
        display_df = df_overview.copy()
        if is_running_now:
            st.caption("Update läuft: Filter sind temporär pausiert, damit die Tabelle durchgehend sichtbar bleibt.")
        else:
            if "kein_roi_vorhanden" in display_df.columns and hide_no_roi_stamped:
                display_df = display_df[~display_df["kein_roi_vorhanden"].map(_overview_status_true)].copy()
            if filter_missing_roi:
                display_df = display_df[
                    (~display_df["roi_ausgewaehlt"].map(_overview_status_true))
                    & (display_df["audio_video_vorhanden"].map(_overview_status_true))
                ].copy()
                st.caption(f"Filter aktiv: {len(display_df)} von {len(df_overview)} Fällen angezeigt.")
            elif ("kein_roi_vorhanden" in df_overview.columns) and (hide_no_roi_stamped):
                hidden_no_roi = int(df_overview["kein_roi_vorhanden"].map(_overview_status_true).sum())
                if hidden_no_roi:
                    st.caption(f"{hidden_no_roi} als 'kein ROI vorhanden' markierte Fälle ausgeblendet.")
        styled_df = display_df
        visible_df = styled_df.drop(columns=["remote_key"], errors="ignore")
        allow_select = not is_running_now and not load_running
        if display_df.empty:
            table_slot.dataframe(
                visible_df,
                width="stretch",
                hide_index=True,
                height=MAT_TABLE_HEIGHT,
                column_config=MAT_OVERVIEW_COLCFG,
            )
            filter_info_slot.info("Keine Fälle passend zum aktuellen Filter.")
        elif allow_select:
            filter_info_slot.empty()
            sel_event = table_slot.dataframe(
                visible_df,
                width="stretch",
                hide_index=True,
                height=MAT_TABLE_HEIGHT,
                column_config=MAT_OVERVIEW_COLCFG,
                key="mat_single_table",
                on_select="rerun",
                selection_mode="single-row",
            )
            selected_rows = []
            if hasattr(sel_event, "selection"):
                selected_rows = list(getattr(sel_event.selection, "rows", []) or [])
            elif isinstance(sel_event, dict):
                selected_rows = list((((sel_event.get("selection") or {}).get("rows")) or []))
            if selected_rows:
                idx0 = int(selected_rows[0])
                if 0 <= idx0 < len(styled_df):
                    current_selected_key = str(styled_df.iloc[idx0].get("remote_key", "") or "")
                    st.session_state.mat_pending_selected_key = current_selected_key
                    st.session_state.mat_user_selected_key = current_selected_key
        else:
            filter_info_slot.empty()
            st.caption("JSON-Auswahl wird aktualisiert ... (Live-Status je Zeile sichtbar)")
            table_slot.dataframe(
                visible_df,
                width="stretch",
                hide_index=True,
                height=MAT_TABLE_HEIGHT,
                column_config=MAT_OVERVIEW_COLCFG,
            )
        _render_mat_selection_analysis(
            display_df,
            title_suffix=" (gefilterte Ansicht)" if filter_missing_roi else "",
        )
    else:
        st.caption("Noch keine JSON-Datei analysiert.")
        table_slot.dataframe(
            pd.DataFrame(
                columns=[
                    "mat_datei", "video_title", "audio_video_vorhanden", "kein_roi_vorhanden",
                    "video_fehlerhaft", "roi_ausgewaehlt", "track_ausgewaehlt",
                    "anfang_ende_ausgewaehlt", "audio_config", "ocr_durchgefuehrt",
                    "ocr_vollstaendig", "audioanalyse_spektrogramm", "validierung", "fehler",
                ]
            ),
            width="stretch",
            hide_index=True,
            height=MAT_TABLE_HEIGHT,
            column_config=MAT_OVERVIEW_COLCFG,
        )

    if load_clicked and can_load:
        selected_key = str(st.session_state.get("mat_user_selected_key", "") or "")
        visible_keys = set()
        try:
            visible_keys = {str(v or "") for v in display_df.get("remote_key", pd.Series(dtype=str)).tolist()}
        except Exception:
            visible_keys = set()
        if selected_key and selected_key in visible_keys:
            st.session_state.mat_selected_key = selected_key
            st.session_state.mat_pending_selected_key = selected_key
            st.session_state.mat_selected_summary = None
            st.session_state.mat_load_requested = True
        else:
            st.session_state.mat_selected_key = ""
            st.session_state.mat_selected_summary = None
            st.session_state.mat_user_selected_key = ""
            set_status("Bitte zuerst genau eine JSON-Zeile in der aktuell sichtbaren Tabelle anwaehlen.", "warn")

    if st.session_state.mat_load_requested and (not running) and connected:
        selected = st.session_state.mat_selected_key
        st.session_state.mat_load_requested = False
        if not selected:
            set_status("Bitte zuerst eine Zeile mit JSON-Datei waehlen.", "warn")
            st.rerun()
        st.session_state.mat_load_running = True
        st.rerun()

    if st.session_state.mat_load_running and (not running) and connected:
        selected = st.session_state.mat_selected_key
        st.markdown(
            """
            <style>
            .mat-load-overlay {
              position: fixed;
              inset: 0;
              background: rgba(15, 22, 36, 0.42);
              z-index: 9998;
              display: flex;
              align-items: center;
              justify-content: center;
            }
            .mat-load-overlay-box {
              background: rgba(7, 14, 26, 0.90);
              color: #d7e8ff;
              border: 1px solid rgba(74, 144, 164, 0.45);
              border-radius: 12px;
              padding: 14px 18px;
              font-weight: 700;
            }
            </style>
            <div class="mat-load-overlay"><div class="mat-load-overlay-box">JSON + Video wird geladen ...</div></div>
            """,
            unsafe_allow_html=True,
        )
        with st.spinner("Lade JSON + Video ..."):
            _analyze_mat_from_r2(selected)
            summary = st.session_state.mat_selected_summary or {}
            capture_folder = summary.get("capture_folder") or _mat_capture_guess_from_key(selected)
            json_doc = _r2_download_json_doc(_r2_json_sidecar_key(selected))
            video_ok = _try_load_video_for_capture_folder_with_fallback(capture_folder, json_doc)
            if video_ok:
                st.session_state.capture_folder = str(st.session_state.get("_mat_last_video_capture_folder") or capture_folder)
            mat_loaded = _load_mat_from_r2(selected, preloaded_doc=json_doc)
            if mat_loaded is None:
                set_status("JSON konnte nicht geladen werden.", "warn")
            elif not video_ok:
                set_status("JSON geladen, aber kein passendes Video gefunden.", "warn")
            if mat_loaded:
                st.session_state.audio_last_mat_path = mat_loaded
        st.session_state.tab_default = "ROI Setup"
        st.session_state.mat_load_running = False
        st.rerun()

    st.markdown('</div>', unsafe_allow_html=True)
    if mat_request_rerun and st.session_state.get("mat_update_running"):
        st.rerun()
