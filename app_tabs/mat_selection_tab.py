"""Renderer for the Streamlit tab extracted from app.py.

The renderer receives app.py globals so existing helper functions and
session-state conventions remain shared during the incremental split.
"""

def render(ns):
    globals().update(ns)
    st.markdown('<div class="section-card mat-selection-no-scroll">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">MAT-Auswahl und Analyse</div>', unsafe_allow_html=True)
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
          <b>MAT -> JSON Auto-Cache aktiv:</b> Vorhandene JSON-Sidecars werden automatisch genutzt.
          Fehlt die JSON, liest das Update die MAT-Datei und erzeugt automatisch
          eine gleichnamige JSON-Datei in R2/results.
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

    c1, c2, c3 = st.columns(3)
    update_label = "Stop" if running else "Update"
    update_clicked = c1.button(
        update_label,
        width="stretch",
        key="mat_update_tab",
        disabled=(not connected) or load_running,
    )
    # Button soll nach Update/Filter nicht durch einen veralteten Selection-State
    # blockiert werden. Ob wirklich eine sichtbare MAT-Zeile gewaehlt ist, wird
    # beim Klick gegen die aktuell sichtbare Tabelle validiert.
    can_load = (
        connected
        and bool(st.session_state.mat_overview_rows)
        and not running
        and not load_running
    )
    load_clicked = c2.button(
        "MAT + Video laden",
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
    c3.download_button(
        "YouTube-Titel Excel",
        data=title_excel_bytes,
        file_name=f"youtube_titles_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
        key="mat_youtube_title_excel_btn",
        disabled=not bool(title_excel_bytes),
        help="Laedt direkt eine Excel-Datei fuer den Match mit der Fahrzeugdatenbank herunter. Es wird nichts in die Cloud gespeichert.",
    )

    progress_slot = st.empty()
    table_slot = st.empty()

    if update_clicked:
        if running:
            st.session_state.mat_update_running = False
            st.session_state.mat_run_state = "idle"
            set_status("Analyse abgebrochen.", "warn")
        else:
            _refresh_mat_files()
            mat_targets = st.session_state.mat_targets
            st.session_state.mat_auto_updated_prefix = st.session_state.r2_prefix
            if mat_targets:
                st.session_state.mat_update_running = True
                st.session_state.mat_run_state = "running"
                set_status(f"Analyse gestartet ({len(mat_targets)} Eintraege).", "info")
                _update_all_mat_overview_rows(mat_targets, live_table=table_slot, progress_slot=progress_slot)
                st.session_state.mat_update_running = False
                st.session_state.mat_run_state = "idle"
                set_status(f"Analyse fuer {len(mat_targets)} Eintraege abgeschlossen.", "ok")
            else:
                st.session_state.mat_run_state = "idle"
                set_status("Keine MAT-Dateien gefunden.", "warn")

    if connected and mat_targets and st.session_state.mat_auto_updated_prefix != st.session_state.r2_prefix and not running:
        st.session_state.mat_auto_updated_prefix = st.session_state.r2_prefix
        st.session_state.mat_update_running = True
        st.session_state.mat_run_state = "running"
        _update_all_mat_overview_rows(mat_targets, live_table=table_slot, progress_slot=progress_slot)
        st.session_state.mat_update_running = False
        st.session_state.mat_run_state = "idle"
        set_status(f"Analyse fuer {len(mat_targets)} Eintraege abgeschlossen.", "ok")

    json_created = int(st.session_state.get("mat_json_sidecar_created_count", 0) or 0)
    json_used = int(st.session_state.get("mat_json_sidecar_used_count", 0) or 0)
    if json_created:
        st.success(f"MAT->JSON Cache aktualisiert: {json_created} JSON-Sidecar(s) automatisch erzeugt.")
    elif json_used:
        st.caption(f"JSON-Cache aktiv: {json_used} vorhandene JSON-Sidecar(s) fuer die schnelle Analyse verwendet.")

    if not connected:
        st.caption("Erst in Tab 'Verbindung & Root' verbinden und Projektroot waehlen.")

    current_selected_key = str(st.session_state.get("mat_pending_selected_key", "") or "")

    if st.session_state.mat_overview_rows:
        df_overview = pd.DataFrame(st.session_state.mat_overview_rows)
        df_overview = _normalize_overview_lamps(df_overview)
        filter_missing_roi = st.checkbox(
            "Nur Fälle anzeigen: ROI fehlt und Audio+Video vorhanden",
            value=False,
            key="mat_filter_missing_roi_with_media",
        )
        hide_no_roi_stamped = st.checkbox(
            "Fälle ausblenden, wo kein ROI vorhanden ist",
            value=True,
            key="mat_hide_no_roi_stamped",
            help="Wenn aktiv, werden als 'kein ROI vorhanden' markierte Videos in MAT Selection nicht angezeigt.",
        )
        display_df = df_overview.copy()
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
        is_running_now = bool(st.session_state.mat_update_running)
        styled_df = display_df
        visible_df = styled_df.drop(columns=["remote_key"], errors="ignore")
        allow_select = not is_running_now and not load_running
        if display_df.empty:
            table_slot.empty()
            st.info("Keine Fälle passend zum aktuellen Filter.")
        elif allow_select:
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
            with table_slot.container():
                st.markdown('<div class="mat-selection-disabled">MAT-Auswahl wird aktualisiert ...</div>', unsafe_allow_html=True)
                try:
                    disabled_view = visible_df.style.set_properties(**{
                        "background-color": "#20232b",
                        "color": "#7d8491",
                    })
                except Exception:
                    disabled_view = visible_df
                st.dataframe(
                    disabled_view,
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
        table_slot.empty()
        st.caption("Noch keine MAT analysiert.")

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
            set_status("Bitte zuerst genau eine MAT-Zeile in der aktuell sichtbaren Tabelle anwaehlen.", "warn")

    if st.session_state.mat_load_requested and (not running) and connected:
        selected = st.session_state.mat_selected_key
        st.session_state.mat_load_requested = False
        if not selected:
            set_status("Bitte zuerst eine Zeile mit MAT-Datei waehlen.", "warn")
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
            <div class="mat-load-overlay"><div class="mat-load-overlay-box">MAT + Video wird geladen ...</div></div>
            """,
            unsafe_allow_html=True,
        )
        with st.spinner("Lade MAT + Video ..."):
            _analyze_mat_from_r2(selected)
            summary = st.session_state.mat_selected_summary or {}
            capture_folder = summary.get("capture_folder") or _mat_capture_guess_from_key(selected)
            video_ok = _try_load_video_for_capture_folder(capture_folder)
            if video_ok:
                st.session_state.capture_folder = capture_folder
            mat_loaded = _load_mat_from_r2(selected)
            if mat_loaded is None:
                set_status("MAT konnte nicht geladen werden.", "warn")
            elif not video_ok:
                set_status("MAT geladen, aber kein passendes Video gefunden.", "warn")
            if mat_loaded:
                st.session_state.audio_last_mat_path = mat_loaded
        st.session_state.tab_default = "ROI Setup"
        st.session_state.mat_load_running = False
        st.rerun()

    st.markdown('</div>', unsafe_allow_html=True)



