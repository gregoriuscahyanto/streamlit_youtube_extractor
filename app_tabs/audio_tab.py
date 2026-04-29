"""Renderer for the Streamlit tab extracted from app.py.

The renderer receives app.py globals so existing helper functions and
session-state conventions remain shared during the incremental split.
"""

def render(ns):
    globals().update(ns)
    st.divider()
    st.subheader("Audio Auswertung · robuste RPM-Extraktion")
    title_txt = _audio_get_vehicle_title()
    if title_txt:
        st.info(f"Datensatz / Fahrzeug aus Metadata: {title_txt}")
    st.caption("Mehrere echte RPM-Methoden direkt aus der Video-/Audiospur: STFT/Ridge, Viterbi, Peak, Autokorrelation/YIN, Cepstrum, Harmonic Comb/HPS, CWT/Wavelet und Hybrid. Cloud audio_proxy_1k.wav wird bevorzugt; lokale Videos werden bei Bedarf per ffmpeg gelesen.")

    with st.expander("Signal / STFT", expanded=True):
        c0 = st.columns(4)
        aud_stft_mode = c0[0].selectbox("NFFT/Overlap", ["Fest auswählen", "Auto Schnell", "Auto Breit"], key="aud_stft_mode_new")
        stft_auto = str(aud_stft_mode).startswith("Auto")
        aud_nfft = int(c0[1].number_input("NFFT", 64, 65536, 4096, step=64, key="aud_nfft_new", disabled=stft_auto))
        aud_ov = float(c0[2].number_input("Overlap [%]", 0.0, 98.0, 75.0, step=1.0, key="aud_ov_new", disabled=stft_auto))
        aud_fmax = float(c0[3].number_input("f max [Hz]", 20.0, 5000.0, 1000.0, step=25.0, key="aud_fmax_new"))
        aud_method = st.selectbox("Drehzahl Methode", ["Hybrid", "STFT Ridge", "STFT Viterbi", "Original Peak", "Autokorrelation/YIN", "Cepstrum", "Harmonic Comb/HPS", "CWT/Wavelet"], key="aud_method_new")
        if stft_auto:
            st.caption("Auto Schnell testet eine reduzierte, sinnvolle STFT-Auswahl. Auto Breit testet den grossen Suchraum 64..16384 und viele Overlaps, ist aber deutlich langsamer.")

    with st.expander("Methoden-Parameter", expanded=False):
        st.caption("Diese Parameter wirken nur auf die passenden Methoden; Hybrid nutzt sie beim Fusionieren der Teilmethoden.")
        m0 = st.columns(4)
        ridge_smooth = int(m0[0].number_input("Ridge Glättung", 3, 51, 7, step=2, key="aud_ridge_smooth"))
        ridge_jump_frac = float(m0[1].number_input("Ridge max Sprung [% Band]", 1.0, 50.0, 8.0, step=1.0, key="aud_ridge_jump_pct")) / 100.0
        viterbi_jump_hz = float(m0[2].number_input("Viterbi max Sprung [Hz/Frame]", 1.0, 300.0, 25.0, step=1.0, key="aud_viterbi_jump_hz"))
        viterbi_penalty = float(m0[3].number_input("Viterbi Sprung-Strafe", 0.0, 10.0, 1.2, step=0.1, key="aud_viterbi_penalty"))
        m1 = st.columns(4)
        viterbi_smooth = int(m1[0].number_input("Viterbi Glättung", 3, 51, 5, step=2, key="aud_viterbi_smooth"))
        comb_harmonics = int(m1[1].number_input("Comb/HPS Anzahl Harmonische", 1, 10, 4, step=1, key="aud_comb_harmonics"))
        hybrid_smooth = int(m1[2].number_input("Hybrid Glättung", 3, 51, 9, step=2, key="aud_hybrid_smooth"))
        always_run_cwt = bool(m1[3].checkbox("CWT auch in Kandidatenliste berechnen", value=False, key="aud_run_cwt_all"))
        fast_mode = bool(st.checkbox("Schnellmodus: teure Methoden nur bei expliziter Auswahl berechnen", value=True, key="aud_fast_mode"))
        method_params = dict(ridge_smooth=ridge_smooth, ridge_jump_frac=ridge_jump_frac, viterbi_jump_hz=viterbi_jump_hz, viterbi_penalty=viterbi_penalty, viterbi_smooth=viterbi_smooth, comb_harmonics=comb_harmonics, hybrid_smooth=hybrid_smooth, always_run_cwt=always_run_cwt, fast_mode=fast_mode)

    with st.expander("Motor / Kandidaten", expanded=True):
        c0 = st.columns(3)
        drive_type = c0[0].selectbox("Antrieb", ["Verbrenner/Hybrid", "Hybrid elektrisch dominant", "Elektro"], key="aud_drive_type")
        cyl_mode = c0[1].selectbox("Zylinder", ["Auto variieren", "Fest auswählen"], key="aud_cyl_mode")
        harm_mode = c0[2].selectbox("Harmonische/Ordnung", ["Auto variieren", "Fest auswählen"], key="aud_harm_mode")
        cyl_disabled = str(cyl_mode).startswith("Auto") or ("elekt" in str(drive_type).lower())
        harm_disabled = str(harm_mode).startswith("Auto")
        c1 = st.columns(5)
        aud_cyl = int(c1[0].number_input("Zyl fest", 1, 16, 4, step=1, key="aud_cyl_new", disabled=cyl_disabled))
        aud_order = int(c1[1].number_input("Ordnung fest", 1, 12, 1, step=1, key="aud_order_new", disabled=harm_disabled))
        aud_takt = int(c1[2].number_input("Takt", 2, 4, 4, step=2, key="aud_takt_new", disabled=("elekt" in str(drive_type).lower())))
        aud_rpm_min = float(c1[3].number_input("RPM min", 100.0, 30000.0, 800.0, step=100.0, key="aud_rpm_min_new"))
        aud_rpm_max = float(c1[4].number_input("RPM max", 500.0, 30000.0, 7500.0, step=100.0, key="aud_rpm_max_new"))
        st.caption("Auto Zylinder testet 3/4/5/6/8/10/12. Auto Harmonische testet 1x/2x/3x. Bei Elektro wird die Frequenz direkt als Motor-/Order-Frequenz behandelt.")

    with st.expander("Getriebe / Geschwindigkeit / Fahrzeug", expanded=False):
        c = st.columns(4)
        aud_offset = float(c[0].slider("Audio Offset [s]", -5.0, 5.0, 0.0, step=0.01, key="aud_offset_new"))
        use_ocr_v = bool(c[1].checkbox("OCR v verwenden", value=True, key="aud_use_v_new"))
        r_dyn = float(c[2].number_input("r dyn [m]", 0.05, 2.0, 0.35, step=0.01, key="aud_rdyn_new"))
        tol_pct = float(c[3].number_input("Toleranz [%]", 0.0, 100.0, 6.0, step=0.5, key="aud_tol_new"))
        c2 = st.columns(3)
        axle_ratio = float(c2[0].number_input("Achsübersetzung i", 0.1, 20.0, 3.15, step=0.01, key="aud_axle_ratio"))
        gear_text = c2[1].text_input("Gänge i (Komma-getrennt)", value="5.25, 3.36, 2.17, 1.72, 1.32, 1.00, 0.82, 0.64", key="aud_gears_text")
        prefer_low = bool(c2[2].checkbox("niedrigster Gang bevorzugt", value=False, key="aud_prefer_low"))
        try:
            gear_ratios = [float(x.strip()) for x in str(gear_text).replace(";", ",").split(",") if x.strip()]
        except Exception:
            gear_ratios = []
        st.caption("Getriebe wird nur genutzt, wenn nutzbare Geschwindigkeit/OCR-v vorhanden ist. Ohne v bleibt die RPM-Erkennung rein audio-basiert.")

    current_audio_config = _build_audio_config_from_values({
        "stft_mode": aud_stft_mode,
        "nfft": aud_nfft,
        "overlap_pct": aud_ov,
        "fmax": aud_fmax,
        "method": aud_method,
        "drive_type": drive_type,
        "cyl_mode": cyl_mode,
        "harmonic_mode": harm_mode,
        "cyl": aud_cyl,
        "order": aud_order,
        "takt": aud_takt,
        "rpm_min": aud_rpm_min,
        "rpm_max": aud_rpm_max,
        "audio_offset_s": aud_offset,
        "use_ocr_v": use_ocr_v,
        "r_dyn_m": r_dyn,
        "tol_pct": tol_pct,
        "axle_ratio": axle_ratio,
        "gear_ratios": gear_ratios,
        "prefer_low": prefer_low,
        "method_params": method_params,
    })

    cfg_c1, cfg_c2 = st.columns(2)
    save_cfg_disabled = not bool(st.session_state.get("mat_selected_key") or st.session_state.get("mat_pending_selected_key") or st.session_state.get("audio_last_mat_path"))
    if cfg_c1.button("Audio Config speichern", width="stretch", key="aud_save_config", disabled=save_cfg_disabled):
        with st.spinner("Audio Config wird gespeichert ..."):
            ok_cfg, msg_cfg = _save_audio_config_to_selected_mat(current_audio_config)
        if ok_cfg:
            st.success(msg_cfg)
            set_status("Audio Config gespeichert.", "ok")
        else:
            st.error(msg_cfg)
            set_status(msg_cfg, "warn")
    if cfg_c2.button("Hole naechste Datei", width="stretch", key="aud_load_next_config_target"):
        with st.spinner("Naechste Datei wird geladen ..."):
            ok_next, msg_next = _load_next_audio_config_file()
        set_status(msg_next, "ok" if ok_next else "warn")
        if ok_next:
            st.rerun()
    if save_cfg_disabled:
        st.caption("Audio Config kann gespeichert werden, sobald eine MAT-Datei ueber MAT Selection geladen ist.")
    _cur_summary = st.session_state.get("mat_selected_summary") or {}
    _automation_ready = bool(
        _cur_summary.get("start_end_selected")
        and _cur_summary.get("audio_config_done")
    )
    st.caption(
        "Automatisierung bereit: Start/Ende und Audio Config vorhanden."
        if _automation_ready
        else "Automatisierung gesperrt: benoetigt mindestens Start/Ende und gespeicherte Audio Config."
    )

    _live_log_ref = st.session_state.get("audio_bg_log_ref")
    if isinstance(_live_log_ref, list) and _live_log_ref:
        st.session_state.audio_debug_lines = list(_live_log_ref[-200:])
    _live_progress_ref = st.session_state.get("audio_bg_progress_ref")
    if isinstance(_live_progress_ref, dict) and _live_progress_ref:
        st.session_state.audio_bg_progress = dict(_live_progress_ref)

    main_progress_box = st.empty()
    main_prog_state = st.session_state.get("audio_bg_progress") or {}
    if isinstance(main_prog_state, dict) and (main_prog_state or st.session_state.get("audio_bg_future") is not None):
        done = int(main_prog_state.get("done", 0) or 0)
        total = max(1, int(main_prog_state.get("total", 1) or 1))
        frac = max(0.0, min(1.0, float(main_prog_state.get("fraction", done / total) or 0.0)))
        txt = str(main_prog_state.get("text", "") or "")
        label = f"Audioanalyse: {done}/{total} Jobs ({frac*100:.0f}%)"
        if txt:
            label += f" - {txt}"
        main_progress_box.progress(frac, text=label)

    # Live-Debug darf nicht per Checkbox verschwinden: genau dieser Block ist das
    # sichtbare Feedback, dass die Audioanalyse wirklich gestartet wurde.
    # Der native Streamlit-Log wird immer gerendert; das kleine HTML-Live-Widget
    # bleibt nur Zusatz und ist nicht mehr die einzige Log-Anzeige.
    show_live_debug = True

    def _render_audio_live_panel(expanded: bool = True):
        """Render the visible audio start/running feedback, progressbar and live log."""
        live_id = str(st.session_state.get("audio_bg_live_id", "") or "")
        fut_live = st.session_state.get("audio_bg_future")

        live_ref = st.session_state.get("audio_bg_log_ref")
        if isinstance(live_ref, list) and live_ref:
            log_lines = list(live_ref[-200:])
            st.session_state.audio_debug_lines = log_lines
        else:
            log_lines = list(st.session_state.get("audio_debug_lines", []) or [])

        prog_ref = st.session_state.get("audio_bg_progress_ref")
        if isinstance(prog_ref, dict) and prog_ref:
            prog_state = dict(prog_ref)
            st.session_state.audio_bg_progress = prog_state
        else:
            prog_state = dict(st.session_state.get("audio_bg_progress") or {})

        has_content = bool(live_id or fut_live is not None or log_lines or prog_state)
        if not has_content:
            return
        if fut_live is not None and fut_live.done() and st.session_state.get("audio_analysis_result") is None:
            st.rerun()

        with st.expander("Live-Debug Audioanalyse", expanded=expanded):
            st.caption("Quelle, Segment, STFT-Kandidaten, Job-Fortschritt, Laufzeit und finale Auswahl. Dieser Log bleibt sichtbar, auch wenn das HTML-Live-Widget nicht pollt.")
            if fut_live is not None:
                st.info("Audioanalyse wurde gestartet und läuft im Hintergrund.")

            if isinstance(prog_state, dict) and prog_state:
                done = int(prog_state.get("done", 0) or 0)
                total = max(1, int(prog_state.get("total", 1) or 1))
                frac = max(0.0, min(1.0, float(prog_state.get("fraction", done / total) or 0.0)))
                txt = str(prog_state.get("text", "") or "")
                label = f"Audioanalyse: {done}/{total} Jobs ({frac*100:.0f}%)"
                if txt:
                    label += f" - {txt}"
                st.progress(frac, text=label)
            elif fut_live is not None:
                st.progress(0.0, text="Audioanalyse gestartet - warte auf ersten Fortschritt ...")

            log_text = "\n".join([str(x) for x in log_lines[-80:]]) if log_lines else "[   0.00s] Audioanalyse noch nicht gestartet oder noch kein Debug vorhanden."
            st.markdown(
                """
                <style>
                .audio-native-log pre {
                    max-height: 260px !important;
                    overflow-y: auto !important;
                    font-size: 11px !important;
                    line-height: 1.35 !important;
                }
                </style>
                """,
                unsafe_allow_html=True,
            )
            st.markdown('<div class="audio-native-log">', unsafe_allow_html=True)
            st.code(log_text, language="text")
            st.markdown('</div>', unsafe_allow_html=True)

            # Streamlit-native: kein localhost/iframe-Widget mehr.
            # Dieser Block wird ueber st.fragment(run_every=...) aktualisiert.

    # Hintergrundlauf: Der Future bleibt in st.session_state erhalten. Ein Tab-Wechsel
    # triggert nur einen Streamlit-Rerun, bricht aber den Thread nicht mehr ab.
    fut = st.session_state.get("audio_bg_future")
    if fut is not None:
        if fut.done():
            try:
                res_bg = fut.result()
                st.session_state.audio_analysis_result = res_bg
                live_done = st.session_state.get("audio_bg_log_ref")
                if isinstance(live_done, list) and live_done:
                    st.session_state.audio_debug_lines = list(live_done[-200:])
                else:
                    st.session_state.audio_debug_lines = list(res_bg.get("debug_lines", []))[-200:]
                st.session_state.audio_bg_log_ref = None
                live_prog_done = st.session_state.get("audio_bg_progress_ref")
                if isinstance(live_prog_done, dict) and live_prog_done:
                    st.session_state.audio_bg_progress = dict(live_prog_done)
                st.session_state.audio_bg_progress_ref = None
                _audio_live_update(str(st.session_state.get("audio_bg_live_id", "")), progress=st.session_state.get("audio_bg_progress") or {}, status="done")
                set_status("Audioanalyse abgeschlossen.", "ok")
                # Ergebnis wird unten angezeigt; keine zusätzliche permanente Meldung.
            except Exception as e:
                st.session_state.audio_analysis_result = None
                live_err = st.session_state.get("audio_bg_log_ref")
                base_err = list(live_err[-190:]) if isinstance(live_err, list) else list(st.session_state.get("audio_debug_lines", []) or [])[-190:]
                st.session_state.audio_debug_lines = [*base_err, f"FEHLER: {e}"]
                st.session_state.audio_bg_log_ref = None
                st.session_state.audio_bg_progress_ref = None
                st.session_state.audio_bg_progress = {"done": 0, "total": 1, "fraction": 0.0, "text": f"Fehler: {e}"}
                _audio_live_update(str(st.session_state.get("audio_bg_live_id", "")), progress=st.session_state.audio_bg_progress, log_line=f"FEHLER: {e}", status="error")
                st.error(f"Audioanalyse fehlgeschlagen: {e}")
                set_status(f"Audioanalyse fehlgeschlagen: {e}", "warn")
            finally:
                st.session_state.audio_bg_future = None
        else:
            live_run = st.session_state.get("audio_bg_log_ref")
            if isinstance(live_run, list) and live_run:
                st.session_state.audio_debug_lines = list(live_run[-200:])
            live_prog_run = st.session_state.get("audio_bg_progress_ref")
            if isinstance(live_prog_run, dict) and live_prog_run:
                st.session_state.audio_bg_progress = dict(live_prog_run)
            elapsed = time.perf_counter() - float(st.session_state.get("audio_bg_started", time.perf_counter()) or time.perf_counter())
            st.caption(f"Audioanalyse läuft seit {elapsed:.1f}s. Live-Status ist im Expander sichtbar.")

    running_bg = st.session_state.get("audio_bg_future") is not None
    audio_started_this_run = False
    if st.button("Audioanalyse starten", type="primary", width="stretch", key="aud_run_new", disabled=running_bg):
        ok,msg,fs,y,source=_audio_load_current_capture()
        if not ok:
            st.error(msg); set_status(msg,"warn")
        else:
            params_bg = dict(
                start_s=float(st.session_state.get('t_start',0.0)),
                end_s=float(st.session_state.get('t_end',len(y)/max(fs,1))),
                offset_s=aud_offset,
                nfft=aud_nfft,
                overlap_pct=aud_ov,
                fmax=aud_fmax,
                cyl=aud_cyl,
                takt=aud_takt,
                order=aud_order,
                rpm_min=aud_rpm_min,
                rpm_max=aud_rpm_max,
                method=aud_method,
                cyl_mode=cyl_mode,
                harmonic_mode=harm_mode,
                drive_type=drive_type,
                stft_mode=aud_stft_mode,
                method_params=method_params,
            )
            ui_bg = dict(use_ocr_v=use_ocr_v,r_dyn=r_dyn,tol_pct=tol_pct,axle_ratio=axle_ratio,gears=gear_ratios,prefer_low=prefer_low,vehicle_title=title_txt)
            live_job_id = f"audio-{int(time.time()*1000)}"
            st.session_state.audio_bg_live_id = live_job_id
            live_log = [f"[   0.00s] Quelle={source}, fs={fs}, Samples={len(y):,}", "[   0.00s] Hintergrundanalyse gestartet."]
            live_progress = {"done": 0, "total": 1, "fraction": 0.0, "text": "Hintergrundanalyse gestartet."}
            _audio_live_update(live_job_id, log_line=live_log[0], progress=live_progress, status="running")
            _audio_live_update(live_job_id, log_line=live_log[1], progress=live_progress, status="running")
            st.session_state.audio_bg_log_ref = live_log
            st.session_state.audio_bg_progress_ref = live_progress
            st.session_state.audio_debug_lines = live_log
            st.session_state.audio_bg_progress = dict(live_progress)
            st.session_state.audio_bg_params = params_bg
            st.session_state.audio_bg_source = source
            st.session_state.audio_bg_started = time.perf_counter()
            st.session_state.audio_bg_future = _audio_executor().submit(_audio_background_worker, y, fs, source, params_bg, ui_bg, live_log, live_progress, live_job_id)
            audio_started_this_run = True
            set_status("Audioanalyse im Hintergrund gestartet.", "info")
            st.success("Start bestätigt: Audioanalyse läuft im Hintergrund. Live-Debug und Progressbar erscheinen direkt darunter.")
            st.toast("Audioanalyse gestartet. Live-Debug aktiv.")

    # Wichtig: erst nach dem Start-Button rendern. So gibt es genau einen
    # Live-Debug-Block und der Klick bekommt im gleichen Run sichtbares Feedback.
    def _audio_native_live_refresh_panel():
        _render_audio_live_panel(expanded=True)

    try:
        _audio_native_live_refresh_panel = st.fragment(run_every=1.0)(_audio_native_live_refresh_panel)
    except Exception:
        pass
    _audio_native_live_refresh_panel()

    res=st.session_state.get("audio_analysis_result")
    if isinstance(res,dict) and res.get("t") is not None:
        p=res.get('params',{})
        zyl_txt = "EV" if p.get('cyl') == 0 else p.get('cyl')
        st.caption(f"Quelle: {res.get('source','')} · Methode: {res.get('selected_method','')} · Kandidat: {zyl_txt} Zyl / H{p.get('harmonic')} · Suchband: {p.get('f_search_lo',0):.1f}-{p.get('f_search_hi',0):.1f} Hz · NFFT: {p.get('nfft')} · Overlap: {p.get('overlap_pct')}%")
        if res.get('candidate_table'):
            with st.expander("Kandidatenbewertung", expanded=False):
                st.dataframe(pd.DataFrame(res['candidate_table']), width="stretch", hide_index=True)
        try:
            import plotly.graph_objects as go
            t=np.asarray(res['t'],dtype=float); f=np.asarray(res['freqs'],dtype=float); db=np.asarray(res['db'],dtype=float)
            step_t=max(1,int(np.ceil(db.shape[1]/1800))) if db.ndim==2 else 1; step_f=max(1,int(np.ceil(db.shape[0]/900))) if db.ndim==2 else 1
            fig=go.Figure(data=go.Heatmap(x=t[::step_t], y=f[::step_f], z=db[::step_f,::step_t], colorscale="Viridis", colorbar=dict(title="dB")))
            show=st.multiselect("Frequenzlinien im Spektrogramm anzeigen", list((res.get('freq_lines') or {}).keys()), default=[res.get('selected_method','Auto robust')], key="aud_lines_new")
            for nm in show:
                a=np.asarray(res.get('freq_lines',{}).get(nm,[]),dtype=float)
                if a.size==t.size: fig.add_trace(go.Scatter(x=t,y=a,mode="lines",name=nm,line=dict(width=2)))
            fig.update_layout(title="Spektrogramm f [Hz] über t [s]", xaxis_title="t [s]", yaxis_title="f [Hz]", height=520, template="plotly_dark")
            st.plotly_chart(fig, width="stretch")
            fig2=go.Figure(); fig2.add_trace(go.Scatter(x=t,y=np.asarray(res['rpm'],dtype=float),mode="lines",name="RPM")); fig2.update_layout(title="RPM", xaxis_title="t [s]", yaxis_title="1/min", height=330, template="plotly_dark"); st.plotly_chart(fig2,width="stretch")
        except Exception as e:
            st.warning(f"Plots konnten nicht erstellt werden: {e}")
        st.download_button("Debug ZIP herunterladen", data=_audio_make_debug_zip(res, shown_lines=st.session_state.get('aud_lines_new', [])), file_name=f"audio_debug_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip", mime="application/zip", width="stretch", key="aud_debug_zip_new")
        save_mat_disabled = not bool(st.session_state.get("mat_selected_key") or st.session_state.get("mat_pending_selected_key") or st.session_state.get("audio_last_mat_path"))
        if st.button("Audioanalyse in MAT + JSON speichern", type="primary", width="stretch", key="aud_save_to_mat", disabled=save_mat_disabled):
            with st.spinner("Audioanalyse wird in MAT gespeichert ..."):
                ok_aud_save, msg_aud_save = _save_audio_result_to_selected_mat(res)
            if ok_aud_save:
                st.success(msg_aud_save)
                set_status("Audioanalyse in MAT gespeichert.", "ok")
            else:
                st.error(msg_aud_save)
                set_status(msg_aud_save, "warn")
        if save_mat_disabled:
            st.caption("Zum Speichern zuerst in MAT Selection eine MAT-Datei mit MAT + Video laden.")

    st.divider()
    st.subheader("RPM Validierung")

    val_file = st.file_uploader(
        "Referenzdatei laden (MAT, CSV, XLSX)",
        type=["mat", "csv", "xlsx", "xls"],
        key="aud_validation_file",
        help="MAT-Dateien werden vollstaendig traversiert (auch verschachtelte Strukturen wie recordResult.audio_rpm.processed.t_s).",
    )
    val_df = pd.DataFrame()
    if val_file is not None:
        try:
            from audio_validation import dataframe_from_upload
            val_df = dataframe_from_upload(val_file.getvalue(), val_file.name)
        except Exception as e:
            st.warning(f"Referenzdatei konnte nicht gelesen werden: {e}")

    if not val_df.empty:
        numeric_cols = [c for c in val_df.columns if pd.api.types.is_numeric_dtype(val_df[c])]
        if len(numeric_cols) >= 2:
            vc = st.columns(5)
            time_col    = vc[0].selectbox("Zeitspalte", numeric_cols, key="aud_val_time_col")
            rpm_col     = vc[1].selectbox("Parameter/RPM", numeric_cols,
                                          index=min(1, len(numeric_cols) - 1),
                                          key="aud_val_rpm_col")
            metric_mode = vc[2].selectbox("Genauigkeit", ["Absolutwert", "Prozentual"],
                                          key="aud_val_metric_mode")
            time_shift  = float(vc[3].number_input("Zeitversatz [s]", -3600.0, 3600.0, 0.0,
                                                    step=0.01, key="aud_val_shift_s"))
            shift_step  = float(vc[4].number_input("Suchschrittweite [s]", 0.001, 10.0, 0.05,
                                                    step=0.001, format="%.3f",
                                                    key="aud_val_shift_step",
                                                    help="Zeitschritt fuer 'Find best match'"))

            res_now = st.session_state.get("audio_analysis_result") or {}
            has_rpm = (isinstance(res_now, dict)
                       and res_now.get("t") is not None
                       and res_now.get("rpm") is not None)

            # Search range for Find best match — must be outside the button handler
            # so the user can configure them before clicking.
            bm_c = st.columns(2)
            bm_min = float(bm_c[0].number_input("Suche von [s]", -3600.0, 0.0, -5.0,
                                                 step=0.5, key="aud_val_bm_min"))
            bm_max = float(bm_c[1].number_input("Suche bis [s]", 0.0, 3600.0, 5.0,
                                                 step=0.5, key="aud_val_bm_max"))

            run_c1, run_c2 = st.columns(2)
            if run_c1.button("Validierung berechnen", width="stretch",
                             key="aud_val_calc", disabled=not has_rpm):
                st.session_state.audio_validation_result = _audio_validation_metrics(
                    res_now.get("t"), res_now.get("rpm"),
                    val_df[time_col].dropna().to_numpy(),
                    val_df[rpm_col].dropna().to_numpy(),
                    time_shift, metric_mode,
                )

            if run_c2.button("Find best match", width="stretch",
                             key="aud_val_find_best", disabled=not has_rpm):
                prog = st.progress(0.0, text="Best Match startet ...")
                best, dbg = _audio_find_best_validation_shift(
                    res_now.get("t"), res_now.get("rpm"),
                    val_df[time_col].dropna().to_numpy(),
                    val_df[rpm_col].dropna().to_numpy(),
                    metric_mode, bm_min, bm_max, shift_step,
                    progress_cb=lambda frac, msg: prog.progress(float(frac), text=msg),
                )
                st.session_state.audio_validation_result = best
                st.session_state.audio_validation_debug = dbg
                prog.empty()

            if not has_rpm:
                st.caption("Bitte zuerst eine Audioanalyse starten.")

            vr = st.session_state.get("audio_validation_result")
            if isinstance(vr, dict):
                if vr.get("ok"):
                    vc2 = st.columns(4)
                    vc2[0].metric("MAE [RPM]",   f"{vr.get('mae', 0.0):.1f}")
                    vc2[1].metric("RMSE [RPM]",  f"{vr.get('rmse', 0.0):.1f}")
                    vc2[2].metric("MAPE [%]",    f"{vr.get('mape_pct', 0.0):.2f}")
                    vc2[3].metric("Zeitversatz", f"{vr.get('shift_s', 0.0):+.3f}s")
                    st.caption(
                        f"Summe |Fehler|={vr.get('sum_abs_err', 0.0):.1f} RPM·n  ·  "
                        f"Median={vr.get('median_abs', 0.0):.1f} RPM  ·  "
                        f"n={vr.get('n', 0)}  ·  Modus={vr.get('mode', '')}"
                    )
                    # Validation plot: both curves + error panel
                    from audio_validation import build_validation_figure
                    _val_fig = build_validation_figure(
                        res_now.get("t"),
                        res_now.get("rpm"),
                        val_df[time_col].dropna().to_numpy(),
                        val_df[rpm_col].dropna().to_numpy(),
                        shift_s=float(vr.get("shift_s", 0.0)),
                        label_audio="RPM Analyse",
                        label_ref=f"RPM Messung ({rpm_col})",
                    )
                    if _val_fig is not None:
                        st.plotly_chart(_val_fig, use_container_width=True)
                elif vr.get("error"):
                    st.warning(str(vr["error"]))

            if st.session_state.get("audio_validation_debug"):
                with st.expander("Debug Logs Best Match", expanded=False):
                    st.code("\n".join(str(x) for x in st.session_state.audio_validation_debug[-120:]),
                            language="text")
        else:
            st.info("Die Referenzdatei braucht mindestens zwei numerische Spalten.")
    else:
        st.caption("Optional: MAT, Excel oder CSV laden, um die erkannte RPM-Kurve gegen eine Referenz zu validieren.")
