"""Renderer for the Streamlit tab extracted from app.py.

The renderer receives app.py globals so existing helper functions and
session-state conventions remain shared during the incremental split.
"""

def _result_json_path():
    """Return Path to current result JSON, or None."""
    try:
        cf = _current_capture_folder()
        if not cf:
            return None
        safe_cf = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in cf).strip("._") or "output"
        p = _server_results_dir() / f"results_{safe_cf}.json"
        return p if p.exists() else None
    except Exception:
        return None


def _apply_audio_config_to_state(cfg: dict) -> None:
    """Write saved audio config fields into session state so widgets pick them up."""
    _ss = {
        "drive_type":    ("aud_drive_type",   str),
        "stft_mode":     ("aud_stft_mode_new", str),
        "nfft":          ("aud_nfft_new",      int),
        "overlap_pct":   ("aud_ov_new",        float),
        "fmax":          ("aud_fmax_new",       float),
        "method":        ("aud_method_new",     str),
        "rpm_min":       ("aud_rpm_min_new",    float),
        "rpm_max":       ("aud_rpm_max_new",    float),
        "audio_offset_s":("aud_offset_new",     float),
    }
    for cfg_key, (ss_key, cast) in _ss.items():
        v = cfg.get(cfg_key)
        if v is not None:
            try:
                st.session_state[ss_key] = cast(v)
            except Exception:
                pass
    # Motor params need string conversion for selectbox keys
    if cfg.get("cyl") is not None:
        cyl_mode = str(cfg.get("cyl_mode") or "")
        st.session_state["aud_cyl_sel"] = "any" if "variieren" in cyl_mode.lower() else str(cfg["cyl"])
    if cfg.get("takt") is not None:
        st.session_state["aud_takt_sel"] = str(cfg["takt"])
    if cfg.get("order") is not None:
        harm_mode = str(cfg.get("harmonic_mode") or "")
        st.session_state["aud_order_sel"] = "any" if "variieren" in harm_mode.lower() else str(cfg["order"])
    # Method params
    mp = cfg.get("method_params") or {}
    _mp_map = {
        "ridge_smooth":    ("aud_ridge_smooth",   int),
        "viterbi_jump_hz": ("aud_viterbi_jump_hz", float),
        "viterbi_penalty": ("aud_viterbi_penalty", float),
        "viterbi_smooth":  ("aud_viterbi_smooth",  int),
        "comb_harmonics":  ("aud_comb_harmonics",  int),
        "hybrid_smooth":   ("aud_hybrid_smooth",   int),
    }
    for mp_key, (ss_key, cast) in _mp_map.items():
        v = mp.get(mp_key)
        if v is not None:
            try:
                st.session_state[ss_key] = cast(v)
            except Exception:
                pass
    if mp.get("ridge_jump_frac") is not None:
        try:
            st.session_state["aud_ridge_jump_pct"] = float(mp["ridge_jump_frac"]) * 100.0
        except Exception:
            pass


def _apply_sweep_config_to_state(cfg: dict) -> None:
    """Write saved sweep config fields into session state."""
    _map = {
        "fmax_headroom":   ("sw_fmax_headroom",  float),
        "tol_abs_rpm":     ("sw_tol_abs",        float),
        "tol_pct":         ("sw_tol_pct_sw",     float),
        "tol_logic":       ("sw_tol_logic",      str),
        "offset_range_s":  ("sw_off_range",      float),
        "offset_step_s":   ("sw_off_step",       float),
        "n_combinations":  (None,                None),  # informational only
    }
    for cfg_key, (ss_key, cast) in _map.items():
        if ss_key is None:
            continue
        v = cfg.get(cfg_key)
        if v is not None:
            try:
                st.session_state[ss_key] = cast(v)
            except Exception:
                pass
    if cfg.get("methods"):
        try:
            st.session_state["sw_methods"] = list(cfg["methods"])
        except Exception:
            pass
    if cfg.get("nfft_values"):
        try:
            st.session_state["sw_nfft"] = [int(v) for v in cfg["nfft_values"]]
        except Exception:
            pass
    if cfg.get("overlap_values"):
        try:
            st.session_state["sw_overlap"] = [float(v) for v in cfg["overlap_values"]]
        except Exception:
            pass
    if cfg.get("order_values"):
        try:
            st.session_state["sw_order"] = [float(v) for v in cfg["order_values"]]
        except Exception:
            pass


def render(ns):
    globals().update(ns)
    _legacy_status_token = "Start bestätigt: Audioanalyse läuft im Hintergrund"

    # Jeder volle Page-Rerun (auch Tab-Wechsel) aktualisiert diesen Timestamp.
    # Fragments prüfen ihn um live updates nur anzuzeigen wenn der User auf diesem Tab ist.
    import time as _time
    st.session_state["audio_tab_last_seen"] = _time.time()

    # ── Auto-load audio config + sweep config when file changes ───────────────
    _cur_cf = _current_capture_folder() if callable(globals().get("_current_capture_folder")) else ""
    if _cur_cf and st.session_state.get("_audio_cfg_loaded_for") != _cur_cf:
        _jp = _result_json_path()
        if _jp is not None:
            try:
                import json as _jcfg_ld
                _doc_ld = _jcfg_ld.loads(_jp.read_text(encoding="utf-8", errors="ignore"))
                _rr_ld  = (_doc_ld.get("recordResult") or {})
                _acfg   = _rr_ld.get("audio_config")
                if isinstance(_acfg, dict):
                    _apply_audio_config_to_state(_acfg)
                _swcfg  = (_rr_ld.get("audio_sweep") or {}).get("config")
                if isinstance(_swcfg, dict):
                    _apply_sweep_config_to_state(_swcfg)
            except Exception:
                pass
        st.session_state["_audio_cfg_loaded_for"] = _cur_cf

    st.divider()
    st.subheader("Audio Auswertung · robuste RPM-Extraktion")
    title_txt = _audio_get_vehicle_title()
    if title_txt:
        # Clean up raw filenames used as titles
        import re as _re
        _t = _re.sub(r'\.(avi|mp4|mkv|mov|wmv|flv|m4v)$', '', title_txt, flags=_re.IGNORECASE)
        _t = _re.sub(r'^screen_', '', _t)
        _m = _re.match(r'^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})(.*)', _t)
        if _m:
            _t = f"{_m[1]}-{_m[2]}-{_m[3]} {_m[4]}:{_m[5]}:{_m[6]}"
            if _m[7].strip('_- '):
                _t += f" · {_m[7].strip('_- ')}"
        title_txt = _t
        st.info(f"Datensatz: {title_txt}")
    st.caption("Mehrere echte RPM-Methoden direkt aus der Video-/Audiospur: STFT/Ridge, Viterbi, Peak, Autokorrelation/YIN, Cepstrum, Harmonic Comb/HPS, CWT/Wavelet und Hybrid. Cloud audio_proxy_1k.wav wird bevorzugt; lokale Videos werden bei Bedarf per ffmpeg gelesen.")
    if not _has_media_source():
        st.caption("Kein Video/Audio geladen. Alle Audio-Komponenten sind als Platzhalter vorbereitet.")
        with st.expander("Signal / STFT", expanded=True):
            c0 = st.columns(4)
            c0[0].selectbox("NFFT/Overlap", ["Fest auswaehlen"], index=0, key="aud_ph_stft_mode", disabled=True)
            c0[1].number_input("NFFT", 64, 65536, 4096, step=64, key="aud_ph_nfft", disabled=True)
            c0[2].number_input("Overlap [%]", 0.0, 98.0, 75.0, step=1.0, key="aud_ph_ov", disabled=True)
            c0[3].number_input("f max [Hz]", 20.0, 5000.0, 1000.0, step=25.0, key="aud_ph_fmax", disabled=True)
            st.selectbox("Drehzahl Methode", ["Hybrid"], index=0, key="aud_ph_method", disabled=True)
        with st.expander("Motor / Kandidaten", expanded=True):
            c1 = st.columns(3)
            c1[0].selectbox("Antrieb", ["Verbrenner/Hybrid"], key="aud_ph_drive", disabled=True)
            c1[1].selectbox("Zylinder", ["Auto variieren"], key="aud_ph_cyl_mode", disabled=True)
            c1[2].selectbox("Harmonische/Ordnung", ["Auto variieren"], key="aud_ph_harm_mode", disabled=True)
            st.button("Audioanalyse starten", type="primary", width="stretch", key="aud_ph_start", disabled=True)
        st.info("Lade zuerst eine MAT+Video-Datei im Tab 'MAT-Auswahl und Analyse'.")
        return

    # ── Modus-Auswahl (ganz oben) ──────────────────────────────────────────────
    _aud_mode = st.radio(
        "Analyse-Modus",
        ["Standard-Analyse", "Sweep mit Messdatei"],
        index=int(st.session_state.get("aud_mode_idx", 0)),
        horizontal=True,
        key="aud_mode_radio",
        help="Standard: mehrere Methoden, beste interne Bewertung. "
             "Sweep: Parameter systematisch variieren bis beste Übereinstimmung mit Referenz-RPM.",
    )
    st.session_state.aud_mode_idx = 0 if _aud_mode == "Standard-Analyse" else 1
    _mode_standard = (_aud_mode == "Standard-Analyse")
    _mode_sweep    = not _mode_standard

    # ── Signal / STFT und Methoden-Parameter: nur in Standard-Analyse relevant ──
    # Standardwerte für Sweep-Modus (nicht angezeigt, werden im Sweep variiert)
    aud_stft_mode = "Fest auswählen"
    aud_nfft = 2048
    aud_ov   = 75.0
    aud_fmax = 1000.0
    aud_method = "Hybrid"
    method_params = dict(
        ridge_smooth=7, ridge_jump_frac=0.08,
        viterbi_jump_hz=25.0, viterbi_penalty=1.2, viterbi_smooth=5,
        comb_harmonics=4, hybrid_smooth=9,
        always_run_cwt=True, fast_mode=False,
    )

    if _mode_standard:
        with st.expander("Signal / STFT", expanded=True):
            c0 = st.columns(4)
            aud_stft_mode = c0[0].selectbox("NFFT/Overlap", ["Fest auswählen", "Auto Schnell", "Auto Breit"], key="aud_stft_mode_new")
            stft_auto = str(aud_stft_mode).startswith("Auto")
            aud_nfft = int(c0[1].number_input("NFFT", 64, 65536, 4096, step=64, key="aud_nfft_new", disabled=stft_auto))
            aud_ov   = float(c0[2].number_input("Overlap [%]", 0.0, 98.0, 75.0, step=1.0, key="aud_ov_new", disabled=stft_auto))
            aud_fmax = float(c0[3].number_input("f max [Hz]", 20.0, 5000.0, 1000.0, step=25.0, key="aud_fmax_new"))
            aud_method = st.selectbox(
                "Drehzahl Methode",
                ["Hybrid", "STFT Ridge", "STFT Viterbi", "Original Peak",
                 "Autokorrelation/YIN", "Cepstrum", "Harmonic Comb/HPS", "CWT/Wavelet",
                 "pYIN", "CQT/Constant-Q", "Harmonische Summe", "Bandpass/Autokorr"],
                key="aud_method_new",
            )
            if stft_auto:
                st.caption("Auto Schnell testet eine reduzierte, sinnvolle STFT-Auswahl. Auto Breit testet den grossen Suchraum 64..16384 und viele Overlaps, ist aber deutlich langsamer.")

        with st.expander("Methoden-Parameter", expanded=True):
            st.caption("Diese Parameter wirken nur auf die passenden Methoden; Hybrid nutzt sie beim Fusionieren der Teilmethoden.")
            m0 = st.columns(4)
            ridge_smooth     = int(m0[0].number_input("Ridge Glättung", 3, 51, 7, step=2, key="aud_ridge_smooth"))
            ridge_jump_frac  = float(m0[1].number_input("Ridge max Sprung [% Band]", 1.0, 50.0, 8.0, step=1.0, key="aud_ridge_jump_pct")) / 100.0
            viterbi_jump_hz  = float(m0[2].number_input("Viterbi max Sprung [Hz/Frame]", 1.0, 300.0, 25.0, step=1.0, key="aud_viterbi_jump_hz"))
            viterbi_penalty  = float(m0[3].number_input("Viterbi Sprung-Strafe", 0.0, 10.0, 1.2, step=0.1, key="aud_viterbi_penalty"))
            m1 = st.columns(3)
            viterbi_smooth   = int(m1[0].number_input("Viterbi Glättung", 3, 51, 5, step=2, key="aud_viterbi_smooth"))
            comb_harmonics   = int(m1[1].number_input("Comb/HPS Anzahl Harmonische", 1, 10, 4, step=1, key="aud_comb_harmonics"))
            hybrid_smooth    = int(m1[2].number_input("Hybrid Glättung", 3, 51, 9, step=2, key="aud_hybrid_smooth"))
            method_params = dict(
                ridge_smooth=ridge_smooth, ridge_jump_frac=ridge_jump_frac,
                viterbi_jump_hz=viterbi_jump_hz, viterbi_penalty=viterbi_penalty,
                viterbi_smooth=viterbi_smooth, comb_harmonics=comb_harmonics,
                hybrid_smooth=hybrid_smooth,
                always_run_cwt=True, fast_mode=False,
            )

    with st.expander("Motor / Kandidaten", expanded=True):
        _is_elekt = "elekt" in str(st.session_state.get("aud_drive_type", "") or "").lower()
        c0 = st.columns(4)
        drive_type = c0[0].selectbox("Antrieb", ["Verbrenner/Hybrid", "Hybrid elektrisch dominant", "Elektro"], key="aud_drive_type")
        _is_elekt = "elekt" in str(drive_type).lower()

        from app_tabs.audio_sweep import CYL_OPTIONS
        _cyl_sel = c0[1].selectbox(
            "Zylinder", [str(v) for v in CYL_OPTIONS],
            index=4,
            key="aud_cyl_sel",
            disabled=_is_elekt,
            help="'any' = im Parameter-Sweep variieren. Sonst fixer Wert für Analyse.",
        )
        cyl_mode = "Auto variieren" if _cyl_sel == "any" else "Fest auswählen"
        aud_cyl = 4 if (_cyl_sel == "any" or _is_elekt) else int(_cyl_sel)

        _takt_sel = c0[2].selectbox(
            "Takt", ["any", "2", "4"],
            index=2,
            key="aud_takt_sel",
            disabled=_is_elekt,
            help="'any' = im Parameter-Sweep variieren.",
        )
        aud_takt = 4 if (_takt_sel == "any" or _is_elekt) else int(_takt_sel)

        _ord_sel = c0[3].selectbox(
            "Ordnung", ["any", "0.5", "1", "2", "3"],
            index=0,  # default "any"
            key="aud_order_sel",
            disabled=_is_elekt,
            help="'any' = im Sweep variieren. 0.5 = halbe Grundordnung (4-Takt-Grundton).",
        )
        harm_mode = "Auto variieren" if _ord_sel == "any" else "Fest auswählen"
        aud_order = 1.0 if (_ord_sel == "any" or _is_elekt) else float(_ord_sel)
        c1 = st.columns(2)
        aud_rpm_min = float(c1[0].number_input("RPM min", 100.0, 30000.0, 800.0, step=100.0, key="aud_rpm_min_new"))
        aud_rpm_max = float(c1[1].number_input("RPM max", 500.0, 30000.0, 7500.0, step=100.0, key="aud_rpm_max_new"))
        st.caption(
            "'any' Zylinder / Takt / Ordnung → im Sweep variiert; Standard-Analyse nutzt Fallback-Werte. "
            "Bei Elektro: Frequenz direkt als Motor-Frequenz."
        )

    # ── Getriebe / Offset: nur Standard-Analyse ────────────────────────────────
    aud_offset = 0.0
    use_ocr_v  = False
    r_dyn      = 0.35
    tol_pct    = 6.0
    axle_ratio = 3.15
    gear_ratios: list = []
    prefer_low  = False

    if _mode_standard:
        with st.expander("Getriebe / Geschwindigkeit / Fahrzeug", expanded=False):
            c = st.columns(4)
            aud_offset  = float(c[0].slider("Audio Offset [s]", -5.0, 5.0, 0.0, step=0.01, key="aud_offset_new"))
            use_ocr_v   = bool(c[1].checkbox("OCR v verwenden", value=True, key="aud_use_v_new"))
            r_dyn       = float(c[2].number_input("r dyn [m]", 0.05, 2.0, 0.35, step=0.01, key="aud_rdyn_new"))
            tol_pct     = float(c[3].number_input("Toleranz [%]", 0.0, 100.0, 6.0, step=0.5, key="aud_tol_new"))
            c2 = st.columns(3)
            axle_ratio  = float(c2[0].number_input("Achsübersetzung i", 0.1, 20.0, 3.15, step=0.01, key="aud_axle_ratio"))
            gear_text   = c2[1].text_input("Gänge i (Komma-getrennt)", value="5.25, 3.36, 2.17, 1.72, 1.32, 1.00, 0.82, 0.64", key="aud_gears_text")
            prefer_low  = bool(c2[2].checkbox("niedrigster Gang bevorzugt", value=False, key="aud_prefer_low"))
            try:
                gear_ratios = [float(x.strip()) for x in str(gear_text).replace(";", ",").split(",") if x.strip()]
            except Exception:
                gear_ratios = []
            st.caption("Getriebe wird nur genutzt, wenn nutzbare Geschwindigkeit/OCR-v vorhanden ist.")

    # ── Mode A: Standard-Analyse ───────────────────────────────────────────────
    if _mode_standard:
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
            elif msg_cfg == _SAVE_NEEDS_CONFIRM:
                st.session_state["_audio_config_overwrite_pending"] = dict(current_audio_config)
            else:
                st.error(msg_cfg)
                set_status(msg_cfg, "warn")

        _cfg_pending = st.session_state.get("_audio_config_overwrite_pending")
        if _cfg_pending is not None:
            st.warning("Audio Config ist bereits in der Datei vorhanden. Soll sie ueberschrieben werden?")
            _ow_c1, _ow_c2 = st.columns(2)
            if _ow_c1.button("Ja, ueberschreiben", width="stretch", key="aud_cfg_overwrite_yes"):
                with st.spinner("Audio Config wird ueberschrieben ..."):
                    ok2, msg2 = _save_audio_config_to_selected_mat(_cfg_pending, force=True)
                st.session_state["_audio_config_overwrite_pending"] = None
                if ok2:
                    st.success(msg2)
                    set_status("Audio Config ueberschrieben.", "ok")
                else:
                    st.error(msg2)
                    set_status(msg2, "warn")
                st.rerun()
            if _ow_c2.button("Nein, abbrechen", width="stretch", key="aud_cfg_overwrite_no"):
                st.session_state["_audio_config_overwrite_pending"] = None
                st.rerun()

        if cfg_c2.button("Hole naechste Datei", width="stretch", key="aud_load_next_config_target"):
            with st.spinner("Naechste Datei wird geladen ..."):
                ok_next, msg_next = _load_next_audio_config_file()
            set_status(msg_next, "ok" if ok_next else "warn")
            if ok_next:
                st.rerun()
        if save_cfg_disabled:
            st.caption("Audio Config kann gespeichert werden, sobald eine MAT-Datei ueber MAT Selection geladen ist.")

        _live_log_ref = st.session_state.get("audio_bg_log_ref")
        if isinstance(_live_log_ref, list) and _live_log_ref:
            st.session_state.audio_debug_lines = list(_live_log_ref[-200:])
        _live_progress_ref = st.session_state.get("audio_bg_progress_ref")
        if isinstance(_live_progress_ref, dict) and _live_progress_ref:
            st.session_state.audio_bg_progress = dict(_live_progress_ref)

        main_progress_box = st.empty()
        main_prog_state = st.session_state.get("audio_bg_progress") or {}
        if isinstance(main_prog_state, dict) and (main_prog_state or st.session_state.get("audio_bg_future") is not None):
            done  = int(main_prog_state.get("done", 0) or 0)
            total = max(1, int(main_prog_state.get("total", 1) or 1))
            frac  = max(0.0, min(1.0, float(main_prog_state.get("fraction", done / total) or 0.0)))
            txt   = str(main_prog_state.get("text", "") or "")
            label = f"Audioanalyse: {done}/{total} Jobs ({frac*100:.0f}%)"
            if txt:
                label += f" - {txt}"
            main_progress_box.progress(frac, text=label)

        def _render_audio_live_panel(expanded: bool = True):
            live_id  = str(st.session_state.get("audio_bg_live_id", "") or "")
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
                st.caption("Quelle, Segment, STFT-Kandidaten, Job-Fortschritt, Laufzeit und finale Auswahl.")
                if fut_live is not None:
                    st.info("Audioanalyse wurde gestartet und läuft im Hintergrund.")

                if isinstance(prog_state, dict) and prog_state:
                    done  = int(prog_state.get("done", 0) or 0)
                    total = max(1, int(prog_state.get("total", 1) or 1))
                    frac  = max(0.0, min(1.0, float(prog_state.get("fraction", done / total) or 0.0)))
                    txt   = str(prog_state.get("text", "") or "")
                    label = f"Audioanalyse: {done}/{total} Jobs ({frac*100:.0f}%)"
                    if txt:
                        label += f" - {txt}"
                    st.progress(frac, text=label)
                elif fut_live is not None:
                    st.progress(0.0, text="Audioanalyse gestartet - warte auf ersten Fortschritt ...")

                log_text = "\n".join([str(x) for x in log_lines[-80:]]) if log_lines else "[   0.00s] Audioanalyse noch nicht gestartet oder noch kein Debug vorhanden."
                st.markdown(
                    "<style>.audio-native-log pre{max-height:260px!important;overflow-y:auto!important;"
                    "font-size:11px!important;line-height:1.35!important;}</style>",
                    unsafe_allow_html=True,
                )
                st.markdown('<div class="audio-native-log">', unsafe_allow_html=True)
                st.code(log_text, language="text")
                st.markdown('</div>', unsafe_allow_html=True)

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
                except Exception as e:
                    st.session_state.audio_analysis_result = None
                    live_err  = st.session_state.get("audio_bg_log_ref")
                    base_err  = list(live_err[-190:]) if isinstance(live_err, list) else list(st.session_state.get("audio_debug_lines", []) or [])[-190:]
                    st.session_state.audio_debug_lines = [*base_err, f"FEHLER: {e}"]
                    st.session_state.audio_bg_log_ref  = None
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
        manual_start_clicked = st.button(
            "Audioanalyse starten",
            type="primary",
            width="stretch",
            key="aud_run_new",
            disabled=running_bg,
        )
        if manual_start_clicked:
            ok, msg, fs, y, source = _audio_load_current_capture()
            if not ok:
                st.error(msg); set_status(msg, "warn")
            else:
                params_bg = dict(
                    start_s=float(st.session_state.get('t_start', 0.0)),
                    end_s=float(st.session_state.get('t_end', len(y) / max(fs, 1))),
                    offset_s=aud_offset,
                    nfft=aud_nfft, overlap_pct=aud_ov, fmax=aud_fmax,
                    cyl=aud_cyl, takt=aud_takt, order=aud_order,
                    rpm_min=aud_rpm_min, rpm_max=aud_rpm_max,
                    method=aud_method, cyl_mode=cyl_mode, harmonic_mode=harm_mode,
                    drive_type=drive_type, stft_mode=aud_stft_mode,
                    method_params=method_params,
                )
                ui_bg = dict(use_ocr_v=use_ocr_v, r_dyn=r_dyn, tol_pct=tol_pct,
                             axle_ratio=axle_ratio, gears=gear_ratios, prefer_low=prefer_low,
                             vehicle_title=title_txt)
                live_job_id  = f"audio-{int(time.time()*1000)}"
                st.session_state.audio_bg_live_id = live_job_id
                live_log     = [f"[   0.00s] Quelle={source}, fs={fs}, Samples={len(y):,}", "[   0.00s] Hintergrundanalyse gestartet."]
                live_progress = {"done": 0, "total": 1, "fraction": 0.0, "text": "Hintergrundanalyse gestartet."}
                _audio_live_update(live_job_id, log_line=live_log[0], progress=live_progress, status="running")
                _audio_live_update(live_job_id, log_line=live_log[1], progress=live_progress, status="running")
                st.session_state.audio_bg_log_ref      = live_log
                st.session_state.audio_bg_progress_ref = live_progress
                st.session_state.audio_debug_lines      = live_log
                st.session_state.audio_bg_progress      = dict(live_progress)
                st.session_state.audio_bg_params        = params_bg
                st.session_state.audio_bg_source        = source
                st.session_state.audio_bg_started       = time.perf_counter()
                st.session_state.audio_bg_future = _audio_executor().submit(
                    _audio_background_worker, y, fs, source, params_bg, ui_bg,
                    live_log, live_progress, live_job_id,
                )
                # Keep raw audio in session for sweep use
                st.session_state.audio_y_raw  = y
                st.session_state.audio_fs_raw = float(fs)
                audio_started_this_run = True
                set_status("Audioanalyse im Hintergrund gestartet.", "info")
                st.success("Start bestätigt: Audioanalyse läuft im Hintergrund. Live-Debug und Progressbar erscheinen direkt darunter.")
                st.toast("Audioanalyse gestartet. Live-Debug aktiv.")

        # Live-Fragment: rendert NUR Progressbar + Log (partial rerun = kein Grau).
        # st.rerun() ausschliesslich wenn Analyse FERTIG → einmaliges Grau um Ergebnisse zu laden.
        def _audio_live_fragment():
            fut     = st.session_state.get("audio_bg_future")
            log_ref = st.session_state.get("audio_bg_log_ref")
            prog    = st.session_state.get("audio_bg_progress_ref") or st.session_state.get("audio_bg_progress") or {}
            if fut is None and not (isinstance(log_ref, list) and log_ref):
                return
            if fut is not None and hasattr(fut, "done") and fut.done():
                st.rerun()  # einmaliger Full-Rerun um Ergebnis zu verarbeiten
                return
            done  = int(prog.get("done", 0) or 0)
            total = max(1, int(prog.get("total", 1) or 1))
            frac  = max(0.0, min(1.0, float(prog.get("fraction", done / total) or 0.0)))
            txt   = str(prog.get("text", "") or "")
            label = f"Audioanalyse: {done}/{total} ({frac*100:.0f}%)"
            if txt:
                label += f" — {txt}"
            st.progress(frac, text=label)
            if isinstance(log_ref, list) and log_ref:
                st.code("\n".join(str(x) for x in list(log_ref)[-10:]), language="text")
        try:
            _audio_live_fragment = st.fragment(run_every=3.0)(_audio_live_fragment)
        except Exception:
            pass
        _audio_live_fragment()

        res = st.session_state.get("audio_analysis_result")
        if not (isinstance(res, dict) and res.get("t") is not None):
            st.markdown("**Analyse-Ergebnis (Platzhalter)**")
            st.caption("Noch kein Ergebnis vorhanden. Nach 'Audioanalyse starten' werden Spektrogramm, RPM-Plot und Exportoptionen hier befuellt.")
            st.dataframe(pd.DataFrame(columns=["Methode", "Score", "Hinweis"]), width="stretch", hide_index=True, height=120)
            st.button("Debug ZIP herunterladen", width="stretch", key="aud_debug_zip_ph", disabled=True)
            st.button("Audioanalyse in MAT + JSON speichern", type="primary", width="stretch", key="aud_save_to_mat_ph", disabled=True)

        if isinstance(res, dict) and res.get("t") is not None:
            p = res.get('params', {})
            zyl_txt = "EV" if p.get('cyl') == 0 else p.get('cyl')
            st.caption(f"Quelle: {res.get('source','')} · Methode: {res.get('selected_method','')} · Kandidat: {zyl_txt} Zyl / H{p.get('harmonic')} · Suchband: {p.get('f_search_lo',0):.1f}-{p.get('f_search_hi',0):.1f} Hz · NFFT: {p.get('nfft')} · Overlap: {p.get('overlap_pct')}%")
            if res.get('candidate_table'):
                with st.expander("Kandidatenbewertung", expanded=False):
                    st.dataframe(pd.DataFrame(res['candidate_table']), width="stretch", hide_index=True)
            try:
                import plotly.graph_objects as go
                t  = np.asarray(res['t'],    dtype=float)
                f  = np.asarray(res['freqs'], dtype=float)
                db = np.asarray(res['db'],    dtype=float)
                step_t = max(1, int(np.ceil(db.shape[1] / 1800))) if db.ndim == 2 else 1
                step_f = max(1, int(np.ceil(db.shape[0] / 900)))  if db.ndim == 2 else 1
                fig = go.Figure(data=go.Heatmap(x=t[::step_t], y=f[::step_f], z=db[::step_f, ::step_t], colorscale="Viridis", colorbar=dict(title="dB")))
                show = st.multiselect("Frequenzlinien im Spektrogramm anzeigen", list((res.get('freq_lines') or {}).keys()), default=[res.get('selected_method', 'Auto robust')], key="aud_lines_new")
                for nm in show:
                    a = np.asarray(res.get('freq_lines', {}).get(nm, []), dtype=float)
                    if a.size == t.size:
                        fig.add_trace(go.Scatter(x=t, y=a, mode="lines", name=nm, line=dict(width=2)))
                fig.update_layout(title="Spektrogramm f [Hz] über t [s]", xaxis_title="t [s]", yaxis_title="f [Hz]", height=520, template="plotly_dark")
                st.plotly_chart(fig, width="stretch")
                fig2 = go.Figure()
                fig2.add_trace(go.Scatter(x=t, y=np.asarray(res['rpm'], dtype=float), mode="lines", name="RPM"))
                fig2.update_layout(title="RPM", xaxis_title="t [s]", yaxis_title="1/min", height=330, template="plotly_dark")
                st.plotly_chart(fig2, width="stretch")
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
                elif msg_aud_save == _SAVE_NEEDS_CONFIRM:
                    st.session_state["_audio_result_overwrite_pending"] = dict(res)
                else:
                    st.error(msg_aud_save)
                    set_status(msg_aud_save, "warn")

            _res_pending = st.session_state.get("_audio_result_overwrite_pending")
            if _res_pending is not None:
                st.warning("Audioanalyse ist bereits in der Datei gespeichert. Soll sie ueberschrieben werden?")
                _row_c1, _row_c2 = st.columns(2)
                if _row_c1.button("Ja, ueberschreiben", width="stretch", key="aud_res_overwrite_yes"):
                    with st.spinner("Audioanalyse wird ueberschrieben ..."):
                        ok3, msg3 = _save_audio_result_to_selected_mat(_res_pending, force=True)
                    st.session_state["_audio_result_overwrite_pending"] = None
                    if ok3:
                        st.success(msg3)
                        set_status("Audioanalyse ueberschrieben.", "ok")
                    else:
                        st.error(msg3)
                        set_status(msg3, "warn")
                    st.rerun()
                if _row_c2.button("Nein, abbrechen", width="stretch", key="aud_res_overwrite_no"):
                    st.session_state["_audio_result_overwrite_pending"] = None
                    st.rerun()

            if save_mat_disabled:
                st.caption("Zum Speichern zuerst in MAT Selection eine MAT-Datei mit MAT + Video laden.")

    # ── Mode B: Sweep mit Messdatei ────────────────────────────────────────────
    if _mode_sweep:
        st.divider()
        st.subheader("Sweep mit Messdatei")
        st.caption(
            "Was muss festgelegt werden: **Messdatei** (Excel/CSV/MAT, Zeit- und RPM-Spalte auswählen) "
            "und optional **Motor-Parameter** oben (Zylinder, Takt, Ordnung — 'any' = alle variieren). "
            "Alles andere (Methoden, NFFT, Overlap, Fmax, Offset) wird automatisch durchsucht."
        )

        # ── Helpers ───────────────────────────────────────────────────────────
        import numpy as np
        from app_tabs.audio_sweep import parse_ref_file, embed_ref_in_doc, load_ref_from_doc

        def _cur_result_json() -> "Path | None":
            cf = _current_capture_folder()
            if not cf:
                return None
            safe_cf = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in cf).strip("._") or "output"
            p = _server_results_dir() / f"results_{safe_cf}.json"
            return p if p.exists() else None

        def _load_cur_doc() -> "dict | None":
            import json as _j
            p = _cur_result_json()
            if p is None:
                return None
            try:
                return _j.loads(p.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                return None

        _linked_ref = None
        _cur_doc    = _load_cur_doc()
        if _cur_doc is not None:
            _linked_ref = load_ref_from_doc(_cur_doc)

        # ── Referenzdatei ─────────────────────────────────────────────────────
        st.markdown("#### Referenzdatei / Messdatei")
        _ref_col1, _ref_col2 = st.columns([3, 1])
        with _ref_col1:
            if _linked_ref is not None:
                st.success(
                    f"Verknüpft: **{_linked_ref['source_file']}** "
                    f"({len(_linked_ref['t_s'])} Punkte, seit {_linked_ref['linked_at'][:10]})"
                )
            val_file = st.file_uploader(
                "Messdatei laden (Excel, CSV, MAT)",
                type=["mat", "csv", "xlsx", "xls"],
                key="aud_validation_file",
                help="Datei hochladen, dann Zeit- und RPM-Spalte wählen, dann 'Verknüpfen' klicken. "
                     "Die Referenz wird in der result-JSON gespeichert und beim nächsten Laden auto-geladen.",
            )
        with _ref_col2:
            if _linked_ref is not None:
                if st.button("Verknüpfung aufheben", key="aud_unlink_ref"):
                    import json as _j
                    _p = _cur_result_json()
                    if _p is not None:
                        try:
                            _d = _j.loads(_p.read_text(encoding="utf-8", errors="ignore"))
                            _d.get("recordResult", {}).pop("audio_ref", None)
                            from app_tabs.plausibility_filter import _atomic_write
                            _atomic_write(_p, _d)
                            st.success("Verknüpfung entfernt.")
                            st.rerun()
                        except Exception as _ue:
                            st.error(f"Fehler: {_ue}")

        val_df      = pd.DataFrame()
        _val_source = "linked" if _linked_ref is not None else "none"
        time_col    = "t_s"
        rpm_col     = "rpm"

        if val_file is not None:
            try:
                _prf = parse_ref_file(val_file.getvalue(), val_file.name)
                if _prf.get("error"):
                    st.warning(f"Referenzdatei: {_prf['error']}")
                elif _prf.get("df") is not None:
                    val_df      = _prf["df"]
                    _val_source = "upload"
            except Exception as _pe:
                try:
                    from core.audio_validation import dataframe_from_upload
                    val_df      = dataframe_from_upload(val_file.getvalue(), val_file.name)
                    _val_source = "upload"
                except Exception as _pe2:
                    st.warning(f"Referenzdatei konnte nicht gelesen werden: {_pe2}")
        elif _linked_ref is not None:
            val_df      = pd.DataFrame({"t_s": _linked_ref["t_s"], "rpm": _linked_ref["rpm"]})
            _val_source = "linked"

        if not val_df.empty:
            numeric_cols = [c for c in val_df.columns if pd.api.types.is_numeric_dtype(val_df[c])]
            if not numeric_cols:
                numeric_cols = list(val_df.columns)
            if len(numeric_cols) >= 2:
                _t_def   = numeric_cols.index("t_s")  if "t_s"  in numeric_cols else 0
                _r_def   = numeric_cols.index("rpm")  if "rpm"  in numeric_cols else min(1, len(numeric_cols) - 1)
                _col_c1, _col_c2, _col_c3 = st.columns([2, 2, 2])
                time_col = _col_c1.selectbox("Zeitspalte [s]", numeric_cols, index=_t_def, key="aud_val_time_col")
                rpm_col  = _col_c2.selectbox("RPM-Spalte", numeric_cols, index=_r_def, key="aud_val_rpm_col")
                if _val_source == "upload" and val_file is not None:
                    if _col_c3.button("Mit aktueller Datei verknüpfen", key="aud_link_ref"):
                        _p = _cur_result_json()
                        if _p is None:
                            st.warning("Keine result-JSON geladen — zuerst eine MAT/Video-Datei auswählen.")
                        else:
                            try:
                                import json as _j
                                _d     = _j.loads(_p.read_text(encoding="utf-8", errors="ignore"))
                                _t_arr = val_df[time_col].dropna().to_numpy()
                                _r_arr = val_df[rpm_col].dropna().to_numpy()
                                embed_ref_in_doc(_d, _t_arr, _r_arr, val_file.name, time_col, rpm_col)
                                from app_tabs.plausibility_filter import _atomic_write
                                _atomic_write(_p, _d)
                                st.success(f"Referenz '{val_file.name}' verknüpft.")
                                st.rerun()
                            except Exception as _le:
                                st.error(f"Verknüpfen fehlgeschlagen: {_le}")
            else:
                st.info("Die Referenzdatei braucht mindestens zwei numerische Spalten.")
        else:
            st.caption("Noch keine Referenzdatei geladen oder verknüpft.")

        # ── Parameter-Sweep ───────────────────────────────────────────────────
        st.divider()
        st.markdown("#### Parameter-Sweep")

        # These must be defined before if/else so the results section (outside else) can use them
        from app_tabs.audio_sweep import build_param_grid, load_sweep_results
        _sw_running = bool(st.session_state.get("audio_sweep_running"))

        _ref_for_sweep = None
        if not val_df.empty:
            _tc = time_col if time_col in val_df.columns else val_df.columns[0]
            _rc = rpm_col  if rpm_col  in val_df.columns else val_df.columns[1]
            _ref_for_sweep = val_df[[_tc, _rc]].rename(columns={_tc: "t_s", _rc: "rpm"})
        elif _linked_ref is not None:
            _ref_for_sweep = pd.DataFrame({"t_s": _linked_ref["t_s"], "rpm": _linked_ref["rpm"]})

        if _ref_for_sweep is None:
            st.info("Messdatei laden und verknüpfen um den Sweep zu aktivieren.")
        else:
            # ── Sweep-Einstellungen ───────────────────────────────────────────
            _sw1, _sw2 = st.columns(2)
            with _sw1:
                st.markdown("**Audio-Parameter (werden variiert)**")
                from app_tabs.audio_sweep import METHOD_OPTIONS as _ALL_METHODS
                _default_methods = ["STFT/Ridge", "Viterbi", "Peak", "Autokorrelation/YIN",
                                    "Cepstrum", "Harmonic Comb/HPS", "Hybrid",
                                    "Harmonische Summe", "Bandpass/Autokorr"]
                _sw_methods = st.multiselect(
                    "Methoden",
                    options=_ALL_METHODS,
                    default=[m for m in _default_methods if m in _ALL_METHODS],
                    key="sw_methods",
                    help="pYIN und CQT/Constant-Q benötigen: pip install librosa",
                )
                _sw_nfft = st.multiselect(
                    "NFFT",
                    options=[128, 256, 512, 1024, 2048, 4096, 8192, 16384],
                    default=[512, 1024, 2048, 4096, 8192],
                    key="sw_nfft",
                    help="Fensterbreite für STFT. Kleinere Werte = bessere Zeitauflösung, größere = bessere Frequenzauflösung.",
                )
                _sw_overlap = st.multiselect(
                    "Overlap [%]",
                    options=[0.0, 25.0, 50.0, 62.5, 75.0, 87.5, 93.75],
                    default=[50.0, 75.0, 87.5],
                    key="sw_overlap",
                    help="Überlappung der STFT-Fenster. Höhere Werte = feinere Zeitschritte, mehr Rechenaufwand.",
                )
                _sw_order = st.multiselect(
                    "Ordnung", options=[0.5, 1.0, 2.0, 3.0],
                    default=[0.5, 1.0, 2.0, 3.0], key="sw_order",
                )

            with _sw2:
                st.markdown("**Suchmethode**")
                _sw_strategy = st.selectbox(
                    "Strategie",
                    ["Optuna (Bayesian)", "Zufällige Suche", "Vollfaktoriell"],
                    index=0, key="sw_strategy",
                    help="Optuna (TPE): lernt aus bisherigen Ergebnissen — am effizientesten. "
                         "Zufällige Suche: schnelle Stichproben aus dem Grid. "
                         "Vollfaktoriell: alle Kombinationen systematisch.",
                )
                _sw_use_optuna   = _sw_strategy == "Optuna (Bayesian)"
                _sw_use_random   = _sw_strategy == "Zufällige Suche"
                _sw_use_factorial = _sw_strategy == "Vollfaktoriell"
                if not _sw_use_factorial:
                    _sw_n_trials = int(st.number_input(
                        "Anzahl Trials",
                        min_value=10, max_value=2000,
                        value=80 if _sw_use_optuna else 200,
                        step=10, key="sw_n_trials",
                        help="Optuna: 50–100 reichen meist. Zufällige Suche: 150–300 empfohlen.",
                    ))
                else:
                    _sw_n_trials = 0
                st.markdown("**Fmax (automatisch aus Motorparametern)**")
                _sw_fmax_headroom = float(st.number_input(
                    "Headroom-Faktor", 1.0, 5.0, 1.5, step=0.1, format="%.1f",
                    key="sw_fmax_headroom",
                    help="fmax = rpm_max × cyl × order / (takt × 60) × Faktor. "
                         "1.5 = 50% Puffer über der Grundfrequenz.",
                ))
                st.markdown("**Offset-Suche (Kreuzkorrelation automatisch)**")
                _sw_off_range = float(st.number_input(
                    "Suchbereich +/-Delta [s]", 0.0, 300.0, 10.0, step=1.0, key="sw_off_range",
                    help="Kreuzkorrelation sucht automatisch das beste Offset in diesem Bereich um 0s.",
                ))
                _sw_off_step = float(st.number_input(
                    "Suchschritt [s]", 0.05, 5.0, 0.5, step=0.05, format="%.2f", key="sw_off_step",
                ))
                st.markdown("**Toleranz (Scoring)**")
                _sw_tol_abs = float(st.number_input(
                    "Toleranz absolut [RPM]", 0.0, 5000.0, 300.0, step=50.0, key="sw_tol_abs",
                ))
                _sw_tol_pct = float(st.number_input(
                    "Toleranz [%]", 0.0, 50.0, 5.0, step=0.5, key="sw_tol_pct_sw",
                ))
                _sw_tol_logic = st.selectbox("Toleranz-Logik", ["ODER", "UND"], key="sw_tol_logic")
                _sw_top_n = int(st.number_input("Top-N Ergebnisse", 5, 50, 20, step=5, key="sw_top_n"))

            # ── Methoden-spezifische Parameter (optional) ─────────────────────
            with st.expander("Methoden-spezifische Parameter (optional)", expanded=False):
                _ms1, _ms2 = st.columns(2)
                with _ms1:
                    _sw_ridge = st.checkbox("Ridge-Parameter variieren", key="sw_ridge")
                    if _sw_ridge:
                        _sw_ridge_smooth = st.multiselect("Ridge Glättung", [3, 7, 11, 21], default=[7], key="sw_rs")
                        _sw_ridge_jump   = st.multiselect("Ridge max Sprung [%]", [4, 8, 15], default=[8], key="sw_rj")
                    else:
                        _sw_ridge_smooth = [7]; _sw_ridge_jump = [8]
                    _sw_comb = st.checkbox("Comb/HPS-Harmonische variieren", key="sw_comb")
                    if _sw_comb:
                        _sw_comb_h = st.multiselect("Comb Harmonische", [2, 3, 4, 5], default=[4], key="sw_ch")
                    else:
                        _sw_comb_h = [4]
                with _ms2:
                    _sw_viterbi = st.checkbox("Viterbi-Parameter variieren", key="sw_viterbi")
                    if _sw_viterbi:
                        _sw_vj = st.multiselect("Viterbi max Sprung [Hz]", [10.0, 25.0, 50.0], default=[25.0], key="sw_vj")
                        _sw_vp = st.multiselect("Viterbi Strafe", [0.5, 1.2, 2.5], default=[1.2], key="sw_vp")
                        _sw_vs = st.multiselect("Viterbi Glättung", [3, 5, 11], default=[5], key="sw_vs")
                    else:
                        _sw_vj = [25.0]; _sw_vp = [1.2]; _sw_vs = [5]
                    _sw_hybrid = st.checkbox("Hybrid-Glättung variieren", key="sw_hybrid")
                    if _sw_hybrid:
                        _sw_hs = st.multiselect("Hybrid Glättung", [5, 9, 15, 25], default=[9], key="sw_hs")
                    else:
                        _sw_hs = [9]

            # ── Kombinationen schätzen ────────────────────────────────────────
            _sw_cfg_preview = {
                "sweep_method": True, "method": None,
                "nfft_values": _sw_nfft or [2048],
                "overlap_values": _sw_overlap or [75.0],
                "fmax_headroom": _sw_fmax_headroom,
                "order_values": _sw_order or [1.0],
                "cyl": _cyl_sel, "takt": _takt_sel,
                "rpm_min": float(st.session_state.get("aud_rpm_min_new") or 800.0),
                "rpm_max": float(st.session_state.get("aud_rpm_max_new") or 7500.0),
                "sweep_ridge": _sw_ridge, "ridge_smooth_values": _sw_ridge_smooth,
                "ridge_jump_frac_values": [v / 100.0 for v in _sw_ridge_jump],
                "sweep_viterbi": _sw_viterbi, "viterbi_jump_hz_values": _sw_vj,
                "viterbi_penalty_values": _sw_vp, "viterbi_smooth_values": _sw_vs,
                "sweep_comb": _sw_comb, "comb_harmonics_values": _sw_comb_h,
                "sweep_hybrid": _sw_hybrid, "hybrid_smooth_values": _sw_hs,
            }
            _est_factorial = sum(
                len(build_param_grid({**_sw_cfg_preview, "method": _m, "sweep_method": False}))
                for _m in (_sw_methods or ["Hybrid"])
            )
            if _sw_use_factorial:
                _est_total = _est_factorial
                st.caption(f"Geschätzte Kombinationen: **{_est_total}** (Vollfaktoriell)")
            else:
                _est_total = _sw_n_trials
                st.caption(
                    f"Trials: **{_sw_n_trials}** · Gesamtgrid wäre: {_est_factorial} "
                    f"({'Optuna lernt aus Ergebnissen' if _sw_use_optuna else 'zufällige Stichprobe'})"
                )

            # ── Start / Stop / Status ─────────────────────────────────────────
            _sw_running = bool(st.session_state.get("audio_sweep_running"))  # refreshed here inside else
            _sw_fut = st.session_state.get("audio_sweep_future")
            if _sw_fut is not None and hasattr(_sw_fut, "done") and _sw_fut.done():
                try:
                    _sw_res = _sw_fut.result()
                    st.session_state.audio_sweep_results = _sw_res
                    _cur_jp = _cur_result_json()
                    if _cur_jp and _sw_res:
                        from app_tabs.audio_sweep import save_sweep_results
                        save_sweep_results(str(_cur_jp), _sw_res)
                except Exception as _swe:
                    st.session_state.audio_sweep_error = str(_swe)
                st.session_state.audio_sweep_running    = False
                st.session_state.audio_sweep_future     = None
                # Free large audio array — sweep is done, no longer needed in RAM
                st.session_state.audio_y_raw             = None
                st.session_state.audio_fs_raw            = None
                # Trim log to last 50 lines (keep for inspection, discard bulk)
                _log_done = st.session_state.get("audio_sweep_log_ref")
                if isinstance(_log_done, list) and len(_log_done) > 50:
                    st.session_state.audio_sweep_log_ref = _log_done[-50:]
                st.rerun()

            _sw_c1, _sw_c2 = st.columns(2)
            _sw_start_clicked = _sw_c1.button(
                "Sweep starten", key="sw_start_btn",
                disabled=_sw_running or not _sw_methods or not _sw_nfft,
                type="primary",
            )
            if _sw_running:
                if _sw_c2.button("Stopp", key="sw_stop_btn", type="secondary"):
                    _ev = st.session_state.get("audio_sweep_stop_event")
                    if _ev is not None:
                        _ev.set()
                    st.session_state.audio_sweep_running = False
                    st.rerun()
            if _sw_start_clicked:
                import threading as _thr2
                # Clear previous results
                st.session_state.audio_sweep_results    = None
                st.session_state.audio_sweep_errors_ref = []
                st.session_state.audio_sweep_log_ref    = []
                st.session_state.audio_sweep_error      = None

                _y   = st.session_state.get("audio_y_raw")
                _fs  = float(st.session_state.get("audio_fs_raw") or 0.0)
                _seg_start = float(st.session_state.get("t_start") or 0.0)
                _seg_end   = float(st.session_state.get("t_end")   or 0.0)

                if _y is None or _fs <= 0:
                    # Audio noch nicht geladen — jetzt direkt laden
                    _ok_ld, _msg_ld, _fs_ld, _y_ld, _src_ld = _audio_load_current_capture()
                    if _ok_ld and len(_y_ld) > 0:
                        st.session_state.audio_y_raw  = _y_ld
                        st.session_state.audio_fs_raw = float(_fs_ld)
                        _y  = _y_ld
                        _fs = float(_fs_ld)
                    else:
                        st.error(f"Audio konnte nicht geladen werden: {_msg_ld}")

                # ── Downsample für Sweep ──────────────────────────────────────
                # RPM-Extraktion braucht max ~fmax×4 Hz. Obergrenze 8000 Hz deckt
                # alle Motorfrequenzen bis 4 kHz ab und hält die STFT-Matrix klein.
                _SWEEP_TARGET_FS = 8000
                if _y is not None and _fs > _SWEEP_TARGET_FS * 1.05:
                    try:
                        import numpy as _np_rs
                        _n_new = int(round(len(_y) * _SWEEP_TARGET_FS / _fs))
                        _t_old = _np_rs.linspace(0.0, len(_y) / _fs, len(_y), endpoint=False)
                        _t_new = _np_rs.linspace(0.0, len(_y) / _fs, _n_new, endpoint=False)
                        _y_ds  = _np_rs.interp(_t_new, _t_old, _y).astype(_np_rs.float32)
                        # Scale segment times
                        _seg_start = float(_seg_start)
                        _seg_end   = float(_seg_end) if _seg_end > 0 else float(len(_y_ds) / _SWEEP_TARGET_FS)
                        _y  = _y_ds
                        _fs = float(_SWEEP_TARGET_FS)
                        st.info(f"Audio für Sweep auf {_SWEEP_TARGET_FS} Hz downsampled ({len(_y):,} Samples). Spart Speicher bei STFT.")
                    except Exception as _ds_e:
                        st.warning(f"Downsampling fehlgeschlagen ({_ds_e}), fahre mit originaler Samplerate fort.")

                if _y is not None and _fs > 0:
                    _t_ref_arr   = _ref_for_sweep["t_s"].to_numpy()
                    _rpm_ref_arr = _ref_for_sweep["rpm"].to_numpy()

                    # Factorial grid needed only for vollfaktoriell; others use cfg directly
                    _full_grid = []
                    if _sw_strategy == "Vollfaktoriell":
                        for _m in _sw_methods:
                            _g = build_param_grid({**_sw_cfg_preview, "method": _m, "sweep_method": False})
                            _full_grid.extend(_g)

                    _stop_ev  = _thr2.Event()
                    # For Optuna/Random the grid is empty; use n_trials as initial total
                    _initial_total = len(_full_grid) if _sw_use_factorial else _sw_n_trials
                    _prog_ref = {"done": 0, "total": _initial_total, "current": ""}
                    _n_label = f"{_sw_n_trials} Trials" if not _sw_use_factorial else f"{len(_full_grid)} Kombinationen"
                    _sweep_log = [
                        f"Sweep gestartet [{_sw_strategy}]: {_n_label}, Methoden: {', '.join(_sw_methods)}",
                        f"NFFT: {_sw_nfft} · Overlap: {_sw_overlap}% · Fmax-Headroom: ×{_sw_fmax_headroom} · Ordnung: {_sw_order}",
                        f"Cyl: {_cyl_sel} · Takt: {_takt_sel} · Offset +/-{_sw_off_range}s Schritt {_sw_off_step}s",
                    ]
                    _sweep_errors: list = []
                    _sweep_history: list = []
                    st.session_state.audio_sweep_stop_event = _stop_ev
                    st.session_state.audio_sweep_progress   = _prog_ref
                    st.session_state.audio_sweep_log_ref    = _sweep_log
                    st.session_state.audio_sweep_errors_ref = _sweep_errors
                    st.session_state.audio_sweep_history_ref = _sweep_history
                    st.session_state.audio_sweep_running    = True
                    st.session_state.audio_sweep_error      = None

                    # Save sweep config to result JSON
                    _cur_jp_cfg = _cur_result_json()
                    if _cur_jp_cfg:
                        try:
                            import json as _jcfg
                            from datetime import datetime as _dt
                            from app_tabs.plausibility_filter import _atomic_write as _aw
                            _dcfg = _jcfg.loads(_cur_jp_cfg.read_text(encoding="utf-8", errors="ignore"))
                            _rrcfg = _dcfg.get("recordResult")
                            if isinstance(_rrcfg, dict):
                                _rrcfg.setdefault("audio_sweep", {})["config"] = {
                                    "started": _dt.now().isoformat(timespec="seconds"),
                                    "methods": _sw_methods,
                                    "nfft_values": _sw_nfft,
                                    "overlap_values": _sw_overlap,
                                    "fmax_headroom": _sw_fmax_headroom,
                                    "order_values": _sw_order,
                                    "cyl_sel": _cyl_sel,
                                    "takt_sel": _takt_sel,
                                    "offset_range_s": _sw_off_range,
                                    "offset_step_s": _sw_off_step,
                                    "tol_abs_rpm": _sw_tol_abs,
                                    "tol_pct": _sw_tol_pct,
                                    "tol_logic": _sw_tol_logic,
                                    "n_combinations": len(_full_grid),
                                }
                                _aw(_cur_jp_cfg, _dcfg)
                        except Exception:
                            pass

                    _extract_fn    = globals().get("_audio_extract_rpm_robust")
                    _strategy_snap = _sw_strategy
                    _n_trials_snap = _sw_n_trials
                    _cfg_snap      = dict(_sw_cfg_preview)
                    _cfg_snap["methods"] = list(_sw_methods)
                    def _sweep_worker():
                        from app_tabs.audio_sweep import (
                            run_sweep as _rs,
                            run_sweep_random as _rr,
                            run_sweep_optuna as _ro,
                        )
                        _best_seen = {"score": float("-inf"), "within": 0.0, "rmse": float("inf")}

                        def _pcb(i, total, params, result=None):
                            _prog_ref["done"]    = i
                            _prog_ref["total"]   = total
                            _cfg_str = (
                                f"{params.get('method','')} "
                                f"NFFT={params.get('nfft','')} "
                                f"Fmax={params.get('fmax','')} "
                                f"Cyl={params.get('cyl','')} "
                                f"Ord={params.get('order','')}"
                            )
                            _prog_ref["current"] = _cfg_str
                            _score = float("nan")
                            _within = float("nan")
                            _rmse = float("inf")
                            _err = ""
                            if result is not None:
                                _score = result.get("combined_score", 0.0)
                                _within = result.get("within_pct", 0.0)
                                _rmse = result.get("rmse", float("inf"))
                                _rmse_str = "-" if _rmse == float("inf") else f"{_rmse:.0f}"
                                _err = result.get("score_error", "")
                                if (not _err) and isinstance(_score, (int, float)) and _score > _best_seen["score"]:
                                    _best_seen["score"] = float(_score)
                                    _best_seen["within"] = float(_within if isinstance(_within, (int, float)) else 0.0)
                                    _best_seen["rmse"] = float(_rmse if isinstance(_rmse, (int, float)) else float("inf"))
                                _best_rmse_str = "-" if _best_seen["rmse"] == float("inf") else f"{_best_seen['rmse']:.0f}"
                                _best_str = (
                                    f"Best bisher: Score={_best_seen['score']:.1f} "
                                    f"Within={_best_seen['within']:.1f}% RMSE={_best_rmse_str}"
                                    if _best_seen["score"] > float("-inf")
                                    else "Best bisher: -"
                                )
                                _score_str = (
                                    f"Score={_score:.1f} Within={_within:.1f}% RMSE={_rmse_str} | {_best_str}"
                                    if not _err else f"WARN {_err} | {_best_str}"
                                )
                            else:
                                _score_str = ""
                            _sweep_log.append(
                                f"[{i}/{total}] {_cfg_str}"
                                + (f" -> {_score_str}" if _score_str else "")
                            )
                            if len(_sweep_log) > 200:
                                del _sweep_log[:100]
                            _sweep_history.append({
                                "trial": int(i),
                                "combined_score": float(_score) if isinstance(_score, (int, float)) else float("nan"),
                                "within_pct": float(_within) if isinstance(_within, (int, float)) else float("nan"),
                                "rmse": float(_rmse) if isinstance(_rmse, (int, float)) else float("nan"),
                                "ok": 0 if _err else 1,
                                "best_score": float(_best_seen["score"]) if _best_seen["score"] > float("-inf") else float("nan"),
                                "best_rmse": float(_best_seen["rmse"]) if _best_seen["rmse"] != float("inf") else float("nan"),
                            })

                        def _do_extract(y, fs, start_s, end_s, offset_s, nfft, overlap_pct, fmax, cyl, takt, order, rpm_min, rpm_max, method, cyl_mode, harmonic_mode, drive_type, stft_mode, method_params):
                            return _extract_fn(y, fs, start_s, end_s, offset_s, nfft, overlap_pct, fmax, cyl, takt, order, rpm_min, rpm_max, method, cyl_mode, harmonic_mode, drive_type, stft_mode=stft_mode, method_params=method_params)

                        def _pre_pcb(i, total, params):
                            """Called BEFORE each trial starts — shows what's being computed."""
                            _cfg = (
                                f"{params.get('method','')} "
                                f"NFFT={params.get('nfft','')} "
                                f"Fmax={params.get('fmax','')} "
                                f"Cyl={params.get('cyl','')} "
                                f"Ord={params.get('order','')}"
                            )
                            _prog_ref["current"] = f"Berechne: {_cfg}"
                            _sweep_log.append(f"  → Starte [{i+1}/{total}]: {_cfg}")
                            if len(_sweep_log) > 200:
                                del _sweep_log[:100]

                        _shared = dict(
                            y=_y, fs=_fs, start_s=_seg_start, end_s=_seg_end,
                            t_ref=_t_ref_arr, rpm_ref=_rpm_ref_arr,
                            tol_abs_rpm=_sw_tol_abs if _sw_tol_abs > 0 else None,
                            tol_pct=_sw_tol_pct    if _sw_tol_pct  > 0 else None,
                            tol_logic=_sw_tol_logic,
                            offset_base=0.0,
                            offset_range=_sw_off_range, offset_step=_sw_off_step,
                            progress_cb=_pcb, stop_event=_stop_ev,
                            extract_rpm_fn=_do_extract,
                            top_n=_sw_top_n, errors_out=_sweep_errors,
                            pre_trial_cb=_pre_pcb,
                        )

                        try:
                            if _strategy_snap == "Optuna (Bayesian)":
                                res = _ro(cfg=_cfg_snap, n_trials=_n_trials_snap, **_shared)
                            elif _strategy_snap == "Zufällige Suche":
                                res = _rr(cfg=_cfg_snap, n_trials=_n_trials_snap, **_shared)
                            else:  # Vollfaktoriell
                                res = _rs(grid=_full_grid, **_shared)
                            _sweep_log.append(
                                f"Sweep abgeschlossen ({_strategy_snap}): "
                                f"{len(res)} Ergebnisse, {len(_sweep_errors)} übersprungen."
                            )
                            return res
                        except Exception as _e:
                            _sweep_log.append(f"FEHLER: {_e}")
                            raise

                    _pool = globals().get("_audio_executor")
                    if callable(_pool):
                        _pool = _pool()
                    else:
                        import concurrent.futures as _cf3
                        _pool = _cf3.ThreadPoolExecutor(max_workers=1)
                    st.session_state.audio_sweep_future = _pool.submit(_sweep_worker)
                    st.rerun()

            # Sweep Live-Fragment: partial rerun alle 3s → Progress + Log + Chart (kein Seitengrau).
            # st.rerun() NUR wenn Sweep FERTIG → einmaliges Grau um Ergebnisse zu laden.
            def _sweep_live_fragment():
                running = bool(st.session_state.get("audio_sweep_running"))
                fut     = st.session_state.get("audio_sweep_future")
                log_ref = st.session_state.get("audio_sweep_log_ref")
                prog    = st.session_state.get("audio_sweep_progress") or {}
                if not running and not (isinstance(log_ref, list) and log_ref):
                    return
                # Wenn Future fertig: einmaliger Full-Rerun um Ergebnisse zu laden
                if fut is not None and hasattr(fut, "done") and fut.done():
                    st.rerun()
                    return
                # Läuft noch: Progress + Log + Chart rendern (partial rerun, kein Grau)
                done    = int(prog.get("done", 0))
                total   = max(1, int(prog.get("total", 1)))
                current = str(prog.get("current", ""))
                st.progress(min(1.0, done / total), text=f"Sweep: {done}/{total} — {current}")
                if isinstance(log_ref, list) and log_ref:
                    st.code("\n".join(str(x) for x in list(log_ref)[-15:]), language="text")
                hist_ref = st.session_state.get("audio_sweep_history_ref")
                if isinstance(hist_ref, list) and hist_ref:
                    try:
                        _hdf = pd.DataFrame(hist_ref)[["trial", "combined_score"]].dropna().copy()
                        _hdf["best_score"] = _hdf["combined_score"].cummax()
                        _hdf = _hdf.set_index("trial").rename(columns={
                            "combined_score": "Score (Trial)", "best_score": "Bestes bisher"})
                        st.caption("Optuna: **'Bestes bisher'** steigt monoton.")
                        st.line_chart(_hdf, height=180)
                    except Exception:
                        pass
            try:
                _sweep_live_fragment = st.fragment(run_every=3.0)(_sweep_live_fragment)
            except Exception:
                pass
            _sweep_live_fragment()

        # ── Ergebnisse immer zeigen (auch ohne Referenzdatei geladen) ─────────────
        # Load previously saved results
        if not _sw_running and st.session_state.get("audio_sweep_results") is None:
            _cur_jp2 = _cur_result_json()
            if _cur_jp2:
                _prev = load_sweep_results(str(_cur_jp2))
                if _prev:
                    st.session_state.audio_sweep_results = _prev

        if st.session_state.get("audio_sweep_error"):
            st.error(f"Sweep-Fehler: {st.session_state.audio_sweep_error}")

        # ── Ergebnis-Tabelle ──────────────────────────────────────────────────
        _sw_results = st.session_state.get("audio_sweep_results") or []
        _sw_errs    = st.session_state.get("audio_sweep_errors_ref") or []
        if not _sw_results and _sw_errs and not _sw_running:
            st.warning(f"Kein Ergebnis — alle {len(_sw_errs)} Kombinationen übersprungen.")
            _err_df = pd.DataFrame(_sw_errs)
            _reason_counts = _err_df["reason"].value_counts().to_dict() if "reason" in _err_df.columns else {}
            st.caption("Häufigste Fehlerursachen: " + ", ".join(f"{r}: {n}×" for r, n in _reason_counts.items()))
            with st.expander("Details (letzte 20 Fehler)", expanded=True):
                _show_cols = [c for c in ["method", "nfft", "fmax", "cyl", "takt", "order", "reason", "detail"] if c in _err_df.columns]
                st.dataframe(_err_df.tail(20)[_show_cols], use_container_width=True, hide_index=True)
        if _sw_results:
            st.markdown(f"#### Top-{len(_sw_results)} Ergebnisse")
            _res_df = pd.DataFrame(_sw_results)
            if "rmse" in _res_df.columns:
                import math as _math
                _res_df["rmse"] = _res_df["rmse"].apply(
                    lambda v: "—" if (v is None or (isinstance(v, float) and not _math.isfinite(v))) else round(float(v), 1)
                )
            _display_cols = ["rank", "combined_score", "within_pct", "rmse", "pearson_r",
                             "method", "nfft", "overlap_pct", "fmax", "cyl", "takt", "order", "offset_s", "score_error"]
            _display_cols = [c for c in _display_cols if c in _res_df.columns]
            _col_labels   = {
                "rank": "#", "combined_score": "Score", "within_pct": "Innerhalb%",
                "rmse": "RMSE [RPM]", "pearson_r": "r", "method": "Methode",
                "nfft": "NFFT", "overlap_pct": "Overlap%", "fmax": "Fmax Hz",
                "cyl": "Zyl", "takt": "Takt", "order": "Ord", "offset_s": "Offset s",
                "score_error": "Fehler",
            }
            st.dataframe(
                _res_df[_display_cols].rename(columns=_col_labels),
                use_container_width=True, hide_index=True,
                column_config={
                    "Score":      st.column_config.ProgressColumn("Score",      min_value=0, max_value=100, format="%.1f"),
                    "Innerhalb%": st.column_config.ProgressColumn("Innerhalb%", min_value=0, max_value=100, format="%.1f%%"),
                    "Fehler":     st.column_config.TextColumn("Fehler", width="medium"),
                },
            )

            st.markdown("**Top-1 RPM-Verlauf (gegen Referenz)**")
            _top = _sw_results[0]
            try:
                import plotly.graph_objects as go
                def _to_int(v, default):
                    try:
                        return int(v)
                    except Exception:
                        try:
                            return int(float(v))
                        except Exception:
                            return int(default)
                def _to_float(v, default):
                    try:
                        return float(v)
                    except Exception:
                        return float(default)

                _top1_refresh = st.button("Top-1 Verlauf neu berechnen", key="sw_top1_plot_refresh")
                _top1_key = (
                    f"{_current_capture_folder()}|{_top.get('method')}|{_top.get('nfft')}|"
                    f"{_top.get('overlap_pct')}|{_top.get('fmax')}|{_top.get('cyl')}|"
                    f"{_top.get('takt')}|{_top.get('order')}|{_top.get('offset_s')}"
                )
                if _top1_refresh:
                    st.session_state.pop("audio_sweep_top1_plot", None)
                _top1_cache = st.session_state.get("audio_sweep_top1_plot")
                if not isinstance(_top1_cache, dict) or _top1_cache.get("key") != _top1_key:
                    _top1_cache = None

                if _top1_cache is None:
                    _y_plot = st.session_state.get("audio_y_raw")
                    _fs_plot = float(st.session_state.get("audio_fs_raw") or 0.0)
                    _seg_start_plot = float(st.session_state.get("t_start") or 0.0)
                    _seg_end_plot   = float(st.session_state.get("t_end")   or 0.0)
                    if _y_plot is None or _fs_plot <= 0:
                        _ok_ld, _msg_ld, _fs_ld, _y_ld, _src_ld = _audio_load_current_capture()
                        if _ok_ld and _y_ld is not None and np.asarray(_y_ld).size > 0:
                            st.session_state.audio_y_raw  = _y_ld
                            st.session_state.audio_fs_raw = float(_fs_ld)
                            _y_plot  = _y_ld
                            _fs_plot = float(_fs_ld)
                        else:
                            st.warning(f"Top-1 Verlauf: Audio konnte nicht geladen werden ({_msg_ld}).")

                    if _y_plot is not None and _fs_plot > 0:
                        _extract_plot_fn = globals().get("_audio_extract_rpm_robust")
                        if callable(_extract_plot_fn):
                            _mp_plot = {
                                "ridge_smooth":    _to_int(_top.get("ridge_smooth",   7),   7),
                                "ridge_jump_frac": _to_float(_top.get("ridge_jump_frac", 0.08), 0.08),
                                "viterbi_jump_hz": _to_float(_top.get("viterbi_jump_hz", 25.0), 25.0),
                                "viterbi_penalty": _to_float(_top.get("viterbi_penalty", 1.2), 1.2),
                                "viterbi_smooth":  _to_int(_top.get("viterbi_smooth",   5),   5),
                                "comb_harmonics":  _to_int(_top.get("comb_harmonics",   4),   4),
                                "hybrid_smooth":   _to_int(_top.get("hybrid_smooth",    9),   9),
                                "always_run_cwt": True, "fast_mode": False,
                            }
                            with st.spinner("Top-1 Verlauf wird berechnet..."):
                                _ret = _extract_plot_fn(
                                    _y_plot, _fs_plot,
                                    _seg_start_plot, _seg_end_plot, 0.0,
                                    _to_int(_top.get("nfft", 2048), 2048),
                                    _to_float(_top.get("overlap_pct", 75.0), 75.0),
                                    _to_float(_top.get("fmax", 500.0), 500.0),
                                    _to_int(_top.get("cyl", 4), 4),
                                    _to_int(_top.get("takt", 4), 4),
                                    _to_float(_top.get("order", 1.0), 1.0),
                                    float(st.session_state.get("aud_rpm_min_new") or 800.0),
                                    float(st.session_state.get("aud_rpm_max_new") or 7500.0),
                                    str(_top.get("method", "Hybrid") or "Hybrid"),
                                    "Fest auswählen", "Fest auswählen",
                                    str(st.session_state.get("aud_drive_type", "Verbrenner/Hybrid") or "Verbrenner/Hybrid"),
                                    stft_mode="Fest auswählen", method_params=_mp_plot,
                                )
                            if isinstance(_ret, dict):
                                _t_audio  = np.asarray(_ret.get("t",   []), dtype=float).ravel()
                                _rpm_audio = np.asarray(_ret.get("rpm", []), dtype=float).ravel()
                            elif isinstance(_ret, (tuple, list)) and len(_ret) >= 2:
                                _t_audio  = np.asarray(_ret[0], dtype=float).ravel()
                                _rpm_audio = np.asarray(_ret[1], dtype=float).ravel()
                            else:
                                _t_audio = _rpm_audio = np.asarray([], dtype=float)

                            # Reference — use linked ref if available, otherwise skip ref line
                            _ref_src = st.session_state.get("audio_sweep_top1_ref") or {}
                            if _ref_for_sweep is not None:
                                _t_ref   = np.asarray(_ref_for_sweep["t_s"], dtype=float).ravel()
                                _rpm_ref = np.asarray(_ref_for_sweep["rpm"],  dtype=float).ravel()
                            else:
                                _t_ref = _rpm_ref = None
                            _off = _to_float(_top.get("offset_s", 0.0), 0.0)
                            _plot_df = pd.DataFrame()
                            if _t_audio.size >= 2:
                                _ma = np.isfinite(_t_audio) & np.isfinite(_rpm_audio)
                                _ta = _t_audio[_ma]; _ra = _rpm_audio[_ma]
                                if _t_ref is not None and _t_ref.size >= 2:
                                    _tr = _t_ref[np.isfinite(_t_ref) & np.isfinite(_rpm_ref)] + _off
                                    _rr = _rpm_ref[np.isfinite(_t_ref) & np.isfinite(_rpm_ref)]
                                    _lo = max(float(_ta.min()), float(_tr.min()))
                                    _hi = min(float(_ta.max()), float(_tr.max()))
                                    if _hi > _lo:
                                        _tc = np.linspace(_lo, _hi, int(max(200, min(3000, (_hi-_lo)*5))))
                                        _plot_df = pd.DataFrame({
                                            "time_s":   _tc,
                                            "rpm_top1": np.interp(_tc, _ta, _ra),
                                            "rpm_ref":  np.interp(_tc, _tr, _rr),
                                        })
                                else:
                                    _plot_df = pd.DataFrame({"time_s": _ta, "rpm_top1": _ra})
                            st.session_state.audio_sweep_top1_plot = {"key": _top1_key, "df": _plot_df}
                            _top1_cache = st.session_state.audio_sweep_top1_plot
                        else:
                            st.warning("Top-1 Verlauf: Audio-Extractor nicht verfügbar.")

                if isinstance(_top1_cache, dict):
                    _plot_df = _top1_cache.get("df")
                    if isinstance(_plot_df, pd.DataFrame) and not _plot_df.empty:
                        _fig_top1 = go.Figure()
                        if "rpm_top1" in _plot_df.columns:
                            _fig_top1.add_trace(go.Scatter(x=_plot_df["time_s"], y=_plot_df["rpm_top1"],
                                                           mode="lines", name="Top-1 RPM (Audio)"))
                        if "rpm_ref" in _plot_df.columns:
                            _fig_top1.add_trace(go.Scatter(x=_plot_df["time_s"], y=_plot_df["rpm_ref"],
                                                           mode="lines", name="Referenz RPM",
                                                           line=dict(dash="dash")))
                        _fig_top1.update_layout(title="Top-1 RPM über Zeit", xaxis_title="t [s]",
                                                yaxis_title="RPM", height=350, template="plotly_dark")
                        st.plotly_chart(_fig_top1, use_container_width=True)
                    else:
                        st.caption("Noch kein gültiger Top-1 Verlauf verfügbar.")
            except Exception as _top1_e:
                st.warning(f"Top-1 Verlauf (Fehler): {_top1_e}")

            st.markdown("**Bestes Ergebnis übernehmen:**")
            _top = _sw_results[0]
            st.caption(
                f"Rang 1: **{_top.get('method','')}** | "
                f"NFFT={_top.get('nfft','')} | Overlap={_top.get('overlap_pct','')}% | "
                f"Fmax={_top.get('fmax','')} Hz | Cyl={_top.get('cyl','')} | "
                f"Takt={_top.get('takt','')} | Ord={_top.get('order','')} | "
                f"Offset={_top.get('offset_s', 0.0):+.2f}s | "
                f"Innerhalb={_top.get('within_pct', 0.0):.1f}% | RMSE={_top.get('rmse', 0.0):.0f}"
            )
            if st.button("Top-1 Parameter in Standard-Analyse übernehmen", key="sw_apply_top"):
                def _to_int(v, default):
                    try: return int(v)
                    except Exception:
                        try: return int(float(v))
                        except Exception: return int(default)
                def _to_float(v, default):
                    try: return float(v)
                    except Exception: return float(default)
                _ks = {
                    "aud_stft_mode_new":  "Fest auswählen",
                    "aud_nfft_new":        _to_int(_top.get("nfft",        2048), 2048),
                    "aud_overlap_new":     _to_float(_top.get("overlap_pct", 75.0), 75.0),
                    "aud_fmax_new":        _to_float(_top.get("fmax",        500.0), 500.0),
                    "aud_cyl_sel":         str(_to_int(_top.get("cyl",       4), 4)),
                    "aud_takt_sel":        str(_to_int(_top.get("takt",      4), 4)),
                    "aud_order_new":       _to_int(_top.get("order",         1), 1),
                    "aud_offset_new":      _to_float(_top.get("offset_s",    0.0), 0.0),
                    "aud_ridge_smooth":    _to_int(_top.get("ridge_smooth",   7), 7),
                    "aud_viterbi_jump_hz": _to_float(_top.get("viterbi_jump_hz", 25.0), 25.0),
                    "aud_viterbi_penalty": _to_float(_top.get("viterbi_penalty", 1.2), 1.2),
                    "aud_viterbi_smooth":  _to_int(_top.get("viterbi_smooth",    5), 5),
                    "aud_comb_harmonics":  _to_int(_top.get("comb_harmonics",    4), 4),
                    "aud_hybrid_smooth":   _to_int(_top.get("hybrid_smooth",     9), 9),
                }
                for _k, _v in _ks.items():
                    st.session_state[_k] = _v
                st.session_state["aud_cyl_mode"]  = "Fest auswählen"
                st.session_state["aud_harm_mode"] = "Fest auswählen"
                st.session_state["aud_mode_idx"]  = 0
                st.success("Parameter übernommen — wechsle zu Standard-Analyse und starte eine neue Audioanalyse.")
                st.rerun()



