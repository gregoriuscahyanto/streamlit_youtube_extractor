"""Renderer for the Streamlit tab extracted from app.py.

The renderer receives app.py globals so existing helper functions and
session-state conventions remain shared during the incremental split.
"""

def render(ns):
    globals().update(ns)
    st.markdown('<div class="section-title">Sync Uebersicht (Lokal vs. Cloud)</div>', unsafe_allow_html=True)

    can_sync_compare = bool(st.session_state.r2_connected and st.session_state.local_connected)
    sync_refresh_clicked = False
    sync_start_clicked = False
    sync_stop_clicked = False
    edited = None

    def _render_sync_table(df_table: pd.DataFrame):
        table_slot.dataframe(
            df_table[["auswaehlen", "capture_folder", "reduziert_in_cloud", "status"]],
            width="stretch",
            hide_index=True,
            height=340,
            column_config={
                "auswaehlen": st.column_config.CheckboxColumn("Auswaehlen", default=False),
                "capture_folder": st.column_config.TextColumn("MAT/Folder", width="large"),
                "reduziert_in_cloud": st.column_config.TextColumn("Reduzierte Version in Cloud", width="large"),
                "status": st.column_config.TextColumn("Status", width="medium"),
            },
        )

    def _sync_dataframe_from_state() -> pd.DataFrame:
        cached_df = st.session_state.get("sync_editor_value")
        if not isinstance(cached_df, pd.DataFrame) or cached_df.empty:
            rows = list(st.session_state.get("sync_overview_rows") or [])
            if rows:
                cached_df = pd.DataFrame(rows)
            else:
                cached_df = pd.DataFrame(columns=["auswaehlen", "capture_folder", "reduziert_in_cloud", "status"])
        out = cached_df.copy()
        for c in ["auswaehlen", "capture_folder", "reduziert_in_cloud", "status"]:
            if c not in out.columns:
                out[c] = False if c == "auswaehlen" else ""
        out = out[["auswaehlen", "capture_folder", "reduziert_in_cloud", "status"]].copy()
        out["auswaehlen"] = out["auswaehlen"].astype(bool) if len(out) else out["auswaehlen"]
        return out

    def _select_missing_cloud_rows(df_table: pd.DataFrame) -> pd.DataFrame:
        out = df_table.copy()
        if out.empty:
            return out
        missing_mask = out["reduziert_in_cloud"].astype(str).str.strip().str.startswith("Nein")
        out["auswaehlen"] = missing_mask
        return out

    if not can_sync_compare:
        st.caption("Cloud DB und lokale DB muessen beide verbunden sein.")
    else:
        st.caption("Vergleich: lokale Full-FPS Videos vs. Cloud Frame-Packs (1 fps). Sync extrahiert lokal und laedt Frames hoch. Die erwartete Frame-Anzahl wird aus der Dauer des lokalen Originalvideos berechnet.")

    sync_running = bool(st.session_state.sync_running)
    sync_refresh_clicked = st.button(
        "Sync Uebersicht aktualisieren",
        width="stretch",
        disabled=(not can_sync_compare) or sync_running,
        key="sync_refresh_btn",
    )
    sync_start_clicked = st.button(
        "Auswahl uebernehmen + Sync starten",
        width="stretch",
        type="primary",
        disabled=(not can_sync_compare) or sync_running,
        key="sync_start_btn",
    )
    sync_stop_clicked = st.button(
        "Stop",
        width="stretch",
        disabled=not sync_running,
        key="sync_stop_btn",
    )

    select_missing_cloud = st.checkbox(
        "Alle ohne reduzierte Cloud-Version auswaehlen",
        value=False,
        disabled=(not can_sync_compare) or sync_running,
        key="sync_select_missing_cloud",
        help="Markiert alle Zeilen, deren Status mit 'Nein' beginnt.",
    )

    overall_progress_slot = st.empty()
    stage_slot = st.empty()
    table_slot = st.empty()

    df_sync_editor = _sync_dataframe_from_state()
    if select_missing_cloud and not sync_running:
        df_sync_editor = _select_missing_cloud_rows(df_sync_editor)
        st.session_state.sync_editor_value = df_sync_editor.copy()

    if sync_running:
        _render_sync_table(df_sync_editor)
        edited = df_sync_editor
    else:
        edited = table_slot.data_editor(
            df_sync_editor[["auswaehlen", "capture_folder", "reduziert_in_cloud", "status"]],
            width="stretch",
            hide_index=True,
            height=340,
            disabled=False,
            column_config={
                "auswaehlen": st.column_config.CheckboxColumn("Auswaehlen", default=False),
                "capture_folder": st.column_config.TextColumn("MAT/Folder", width="large"),
                "reduziert_in_cloud": st.column_config.TextColumn("Reduzierte Version in Cloud", width="large"),
                "status": st.column_config.TextColumn("Status", width="medium"),
            },
            key="sync_single_table",
        )
        if isinstance(edited, pd.DataFrame):
            st.session_state.sync_editor_value = edited.copy()

    if sync_refresh_clicked:
        try:
            _refresh_sync_overview_live(table_slot=table_slot, progress_slot=overall_progress_slot)
            st.rerun()
        except Exception as e:
            set_status(f"Sync-Uebersicht Fehler: {e}", "warn")

    if sync_stop_clicked:
        st.session_state.sync_stop_requested = True
        set_status("Stop angefordert: Sync stoppt nach aktueller Datei.", "warn")

    if sync_start_clicked:
        selected_from_editor = []
        edited_df = edited if isinstance(edited, pd.DataFrame) else st.session_state.get("sync_single_table")
        if not isinstance(edited_df, pd.DataFrame):
            edited_df = st.session_state.get("sync_editor_value")
        if isinstance(edited_df, pd.DataFrame) and (not edited_df.empty):
            selected_from_editor = [
                str(row["capture_folder"])
                for _, row in edited_df.iterrows()
                if bool(row.get("auswaehlen"))
            ]
        st.session_state.sync_selected_folders = selected_from_editor

        if (not selected_from_editor) and (not st.session_state.sync_queue_rows):
            set_status("Sync-Queue ist leer.", "warn")
        else:
            target_folders = selected_from_editor if selected_from_editor else [
                str(r.get("capture_folder", ""))
                for r in (st.session_state.sync_queue_rows or [])
            ]
            for f in target_folders:
                _set_sync_row_status(f, "Queue")

            _start_sync_run(target_folders)
            if st.session_state.sync_running:
                set_status(f"Sync gestartet ({st.session_state.sync_run_total} Datei(en)).", "info")
                st.rerun()
            else:
                set_status("Keine gueltigen Queue-Dateien fuer Sync ausgewaehlt.", "warn")

    if st.session_state.sync_running:
        idx = int(st.session_state.sync_run_idx)
        total = int(st.session_state.sync_run_total)
        run_queue = st.session_state.sync_run_queue or []
        status_map = dict(st.session_state.sync_status_map or {})

        completed = max(0, idx)
        elapsed = max(0.0, time.time() - float(st.session_state.sync_run_started_ts or time.time()))
        eta = ((elapsed / completed) * (total - completed)) if completed > 0 else 0.0
        overall_progress_slot.progress(
            min(1.0, completed / max(1, total)),
            text=f"Gesamt: {completed}/{total} ({int((completed/max(1,total))*100)}%) | ETA { _format_eta_seconds(eta) }",
        )

        if st.session_state.sync_stop_requested:
            _finish_sync_run("Sync gestoppt.", "warn")
            st.rerun()

        if idx >= total:
            ok_count = sum(1 for v in status_map.values() if str(v).startswith("OK"))
            err_count = sum(1 for v in status_map.values() if str(v).startswith("Fehler"))
            st.session_state.sync_status_map = status_map
            overview_rows, queue_rows = _build_sync_overview_rows()
            st.session_state.sync_overview_rows = overview_rows
            st.session_state.sync_queue_rows = queue_rows
            st.session_state.sync_editor_value = None
            stage_slot.success(f"Sync abgeschlossen: {ok_count} erfolgreich, {err_count} Fehler.")
            _finish_sync_run(
                f"Sync abgeschlossen ({ok_count} OK / {err_count} Fehler).",
                "warn" if err_count > 0 else "ok",
            )
            st.rerun()

        qrow = run_queue[idx]
        folder = str(qrow.get("capture_folder", "")).strip()
        if not folder:
            st.session_state.sync_run_idx = idx + 1
            st.rerun()

        status_map[folder] = "Konvertierung gestartet"
        st.session_state.sync_status_map = status_map
        _set_sync_row_status(folder, "0%")
        src_video = _find_local_fullfps_video(folder)
        if src_video is None:
            status_map[folder] = "Fehler: keine lokale Full-FPS Datei"
            st.session_state.sync_status_map = status_map
            _set_sync_row_status(folder, "Fehler")
            st.session_state.sync_run_idx = idx + 1
            st.rerun()

        stage_slot.empty()

        def _cb(pct: float, txt: str):
            pct = max(0.0, min(1.0, float(pct)))
            _set_sync_row_status(folder, f"{int(pct * 100)}%")
            df_live_cb = st.session_state.get("sync_editor_value")
            if isinstance(df_live_cb, pd.DataFrame) and not df_live_cb.empty:
                _render_sync_table(df_live_cb)
            overall_pct = (idx + (pct * 0.8)) / max(1, total)
            done = int(overall_pct * 100)
            elapsed_l = max(0.0, time.time() - float(st.session_state.sync_run_started_ts or time.time()))
            completed_l = idx + max(0.01, pct)
            eta_l = (elapsed_l / completed_l) * max(0.0, total - completed_l)
            overall_progress_slot.progress(overall_pct, text=f"Gesamt: {idx}/{total} ({done}%) | ETA { _format_eta_seconds(eta_l) }")

        ok_pack, msg_pack, n_frames, audio_note = _upload_framepack_1fps(src_video, folder, progress_cb=_cb)
        if not ok_pack:
            status_map[folder] = f"Fehler Frame-Pack: {msg_pack}"
            st.session_state.sync_status_map = status_map
            _set_sync_row_status(folder, "Fehler")
            st.session_state.sync_run_idx = idx + 1
            st.rerun()
        status_map[folder] = f"OK ({n_frames} Frames{audio_note})"
        _set_sync_row_status(folder, "OK")

        st.session_state.sync_status_map = status_map
        st.session_state.sync_run_idx = idx + 1
        st.rerun()

    st.markdown("---")
    st.caption("Hinweis: Stop wirkt zwischen Dateien (nicht mitten in einer laufenden Konvertierung).")


