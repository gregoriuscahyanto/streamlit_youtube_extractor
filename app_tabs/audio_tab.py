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
        name = f"results_{safe_cf}.json"
        candidates = [_server_results_dir() / name]
        try:
            lb = st.session_state.get("local_base_path")
            if lb:
                candidates.append(Path(str(lb)).expanduser().resolve() / "results" / name)
        except Exception:
            pass
        try:
            cwd = Path.cwd().resolve()
            gh = cwd.parent if cwd.name == "streamlit_youtube_extractor" else cwd
            candidates.append(gh / "Youtube-Hotlap-Extractor" / "results" / name)
        except Exception:
            pass
        seen = set()
        for p in candidates:
            try:
                rp = p.resolve()
            except Exception:
                rp = p
            if str(rp).lower() in seen:
                continue
            seen.add(str(rp).lower())
            if rp.exists():
                return rp
        return None
    except Exception:
        return None


def _write_audio_rpm_json_only(res: dict) -> tuple[bool, str]:
    """Update recordResult.audio_rpm in the sidecar JSON without touching MAT."""
    try:
        jp = _result_json_path()
        build_fn = globals().get("_build_audio_rpm_struct_from_result")
        if jp is None or not callable(build_fn):
            return False, ""
        import json as _json
        from app_tabs.plausibility_filter import _atomic_write

        doc = _json.loads(jp.read_text(encoding="utf-8", errors="ignore"))
        rr = doc.get("recordResult")
        if not isinstance(rr, dict):
            return False, ""
        audio_rpm = build_fn(res)
        norm_fn = globals().get("_normalize_sidecar_json_payload")
        if callable(norm_fn):
            audio_rpm = norm_fn(audio_rpm)
        else:
            from app_tabs.audio_sweep import _json_safe
            audio_rpm = _json_safe(audio_rpm)
        rr["audio_rpm"] = audio_rpm
        doc["recordResult"] = rr
        _atomic_write(jp, doc)
        return True, str(jp)
    except Exception as exc:
        return False, str(exc)


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


def _std_ss() -> dict:
    """Read Standard-Analyse widget values from session state (for use outside fragments)."""
    ss = st.session_state
    stft_mode = ss.get("aud_stft_mode_new", "Fest auswählen")
    nfft  = int(ss.get("aud_nfft_new",  4096))
    ov    = float(ss.get("aud_ov_new",   75.0))
    fmax  = float(ss.get("aud_fmax_new", 1000.0))
    method = ss.get("aud_method_new", "Hybrid")
    ridge_smooth    = int(ss.get("aud_ridge_smooth",     7))
    ridge_jump_frac = float(ss.get("aud_ridge_jump_pct", 8.0)) / 100.0
    viterbi_jump_hz = float(ss.get("aud_viterbi_jump_hz", 25.0))
    viterbi_penalty = float(ss.get("aud_viterbi_penalty", 1.2))
    viterbi_smooth  = int(ss.get("aud_viterbi_smooth",    5))
    comb_harmonics  = int(ss.get("aud_comb_harmonics",    4))
    hybrid_smooth   = int(ss.get("aud_hybrid_smooth",     9))
    method_params = dict(
        ridge_smooth=ridge_smooth, ridge_jump_frac=ridge_jump_frac,
        viterbi_jump_hz=viterbi_jump_hz, viterbi_penalty=viterbi_penalty,
        viterbi_smooth=viterbi_smooth, comb_harmonics=comb_harmonics,
        hybrid_smooth=hybrid_smooth, always_run_cwt=True, fast_mode=False,
    )
    drive_type = ss.get("aud_drive_type", "Verbrenner/Hybrid")
    is_elekt   = "elekt" in str(drive_type).lower()
    cyl_sel    = str(ss.get("aud_cyl_sel",  "any"))
    takt_sel   = str(ss.get("aud_takt_sel", "4"))
    ord_sel    = str(ss.get("aud_order_sel", "any"))
    cyl_mode   = "Auto variieren" if cyl_sel  == "any" else "Fest auswählen"
    harm_mode  = "Auto variieren" if ord_sel  == "any" else "Fest auswählen"
    aud_cyl    = 4   if (cyl_sel  == "any" or is_elekt) else int(cyl_sel)
    aud_takt   = 4   if (takt_sel == "any" or is_elekt) else int(takt_sel)
    aud_order  = 1.0 if (ord_sel  == "any" or is_elekt) else float(ord_sel)
    rpm_min    = float(ss.get("aud_rpm_min_new", 800.0))
    rpm_max    = float(ss.get("aud_rpm_max_new", 7500.0))
    aud_offset  = float(ss.get("aud_offset_new",  0.0))
    use_ocr_v   = bool(ss.get("aud_use_v_new",    True))
    r_dyn       = float(ss.get("aud_rdyn_new",    0.35))
    tol_pct     = float(ss.get("aud_tol_new",     6.0))
    axle_ratio  = float(ss.get("aud_axle_ratio",  3.15))
    gear_text   = ss.get("aud_gears_text", "5.25, 3.36, 2.17, 1.72, 1.32, 1.00, 0.82, 0.64")
    prefer_low  = bool(ss.get("aud_prefer_low",   False))
    try:
        gear_ratios = [float(x.strip()) for x in str(gear_text).replace(";", ",").split(",") if x.strip()]
    except Exception:
        gear_ratios = []
    return dict(
        stft_mode=stft_mode, nfft=nfft, ov=ov, fmax=fmax, method=method,
        method_params=method_params,
        drive_type=drive_type, is_elekt=is_elekt, cyl_sel=cyl_sel, takt_sel=takt_sel,
        cyl_mode=cyl_mode, harm_mode=harm_mode,
        aud_cyl=aud_cyl, aud_takt=aud_takt, aud_order=aud_order,
        rpm_min=rpm_min, rpm_max=rpm_max,
        aud_offset=aud_offset, use_ocr_v=use_ocr_v, r_dyn=r_dyn,
        tol_pct=tol_pct, axle_ratio=axle_ratio, gear_ratios=gear_ratios, prefer_low=prefer_low,
    )


def _audio_current_result_json_path():
    """Return the active result JSON path, or None."""
    try:
        cf = _current_capture_folder()
        if not cf:
            return None
        safe_cf = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in cf).strip("._") or "output"
        name = f"results_{safe_cf}.json"
        candidates = [_server_results_dir() / name]
        try:
            lb = st.session_state.get("local_base_path")
            if lb:
                candidates.append(Path(str(lb)).expanduser().resolve() / "results" / name)
        except Exception:
            pass
        try:
            cwd = Path.cwd().resolve()
            gh = cwd.parent if cwd.name == "streamlit_youtube_extractor" else cwd
            candidates.append(gh / "Youtube-Hotlap-Extractor" / "results" / name)
        except Exception:
            pass
        seen = set()
        for p in candidates:
            try:
                rp = p.resolve()
            except Exception:
                rp = p
            low = str(rp).lower()
            if low in seen:
                continue
            seen.add(low)
            if rp.exists():
                return rp
    except Exception:
        pass
    return None


def _audio_load_current_result_doc() -> dict:
    """Load active result JSON for OCR-derived speed reuse."""
    import json as _json

    p = _audio_current_result_json_path()
    if p is None:
        return {}
    try:
        doc = _json.loads(p.read_text(encoding="utf-8", errors="ignore"))
        return doc if isinstance(doc, dict) else {}
    except Exception:
        return {}


def _audio_extract_v_from_doc(doc_dict) -> "tuple | None":
    """Extract t_s/time_s and v_Fzg_kmph from recordResult.ocr.cleaned/table."""
    try:
        _ob = (doc_dict.get("recordResult") or {}).get("ocr") or {}
        for _src in (_ob.get("cleaned"), _ob.get("table")):
            if not isinstance(_src, dict):
                continue
            _vv = _src.get("v_Fzg_kmph")
            _tv = _src.get("time_s") or _src.get("t_s")
            if _vv and _tv and len(_vv) == len(_tv):
                return (
                    np.array(_tv, dtype=float),
                    np.array([float(v) if v is not None else float("nan") for v in _vv], dtype=float),
                )
    except Exception:
        pass
    return None


def _audio_find_ocr_speed_series() -> "tuple | None":
    """Find OCR speed in the active JSON or matching sibling JSONs."""
    import json as _json

    doc = _audio_load_current_result_doc()
    if doc:
        res = _audio_extract_v_from_doc(doc)
        if res:
            return res
    jp = _audio_current_result_json_path()
    if jp is None:
        return None
    try:
        for sib in sorted(jp.parent.glob(f"{jp.stem}*.json")):
            if sib == jp:
                continue
            try:
                sdoc = _json.loads(sib.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                continue
            res = _audio_extract_v_from_doc(sdoc)
            if res:
                return res
    except Exception:
        pass
    return None


def _audio_build_standard_gear_band_cfg(std_params: dict) -> "dict | None":
    """Build gear-band guidance for Standard-Analyse from OCR v_Fzg_kmph."""
    if not bool(std_params.get("use_ocr_v")):
        return None
    gears = [float(g) for g in (std_params.get("gear_ratios") or []) if float(g) > 0]
    if not gears:
        return None
    res = _audio_find_ocr_speed_series()
    if not res:
        return None
    t_ocr, v_ocr = res
    valid = np.isfinite(t_ocr) & np.isfinite(v_ocr)
    if int(valid.sum()) < 2:
        return None
    return {
        "t_ocr": list(np.asarray(t_ocr[valid], dtype=float)),
        "v_kmph_ocr": list(np.asarray(v_ocr[valid], dtype=float)),
        "gear_ratios": gears,
        "axle_ratio": float(std_params.get("axle_ratio", 3.15) or 3.15),
        "r_dyn": float(std_params.get("r_dyn", 0.35) or 0.35),
        "rpm_min": float(std_params.get("rpm_min", 800.0) or 800.0),
        "rpm_max": float(std_params.get("rpm_max", 7500.0) or 7500.0),
        "band_tol_pct": max(3.0, float(std_params.get("tol_pct", 6.0) or 6.0)),
        "band_smooth_n": 7,
        "band_center_weight": 0.65,
        "higher_gear_bias": 0.08,
        "gear_shift_penalty": 0.35,
        "guide_strength": 0.45,
        "use_gear_path_viterbi": True,
        "mode": "guide_and_clamp",
        "source": "standard_ocr_v_fzg_kmph",
    }


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

    # ── Parameter-Expander als Fragments ─────────────────────────────────────────
    # Jeder Expander ist ein eigenes Fragment → Parameteränderungen lösen nur einen
    # Partial-Rerun des jeweiligen Fragments aus, keine Seiten-Aktualisierung.
    # Alle Widgets haben key= → Werte stehen in st.session_state.
    # Downstream-Code liest via _std_ss() aus Session State (nicht aus lokalen Vars).

    def _std_stft_frag():
        with st.expander("Signal / STFT", expanded=True):
            c0 = st.columns(4)
            _sm = c0[0].selectbox("NFFT/Overlap", ["Fest auswählen", "Auto Schnell", "Auto Breit"], key="aud_stft_mode_new")
            _sa = str(_sm).startswith("Auto")
            c0[1].number_input("NFFT", 64, 65536, 4096, step=64, key="aud_nfft_new", disabled=_sa)
            c0[2].number_input("Overlap [%]", 0.0, 98.0, 75.0, step=1.0, key="aud_ov_new", disabled=_sa)
            c0[3].number_input("f max [Hz]", 20.0, 5000.0, 1000.0, step=25.0, key="aud_fmax_new")
            st.selectbox(
                "Drehzahl Methode",
                ["Hybrid", "STFT Ridge", "STFT Viterbi", "Original Peak",
                 "Autokorrelation/YIN", "Cepstrum", "Harmonic Comb/HPS", "CWT/Wavelet",
                 "pYIN", "CQT/Constant-Q", "Harmonische Summe", "Bandpass/Autokorr"],
                key="aud_method_new",
            )
            if _sa:
                st.caption("Auto Schnell testet eine reduzierte, sinnvolle STFT-Auswahl. Auto Breit testet den grossen Suchraum 64..16384 und viele Overlaps, ist aber deutlich langsamer.")

    def _meth_params_frag():
        _mode_sw = st.session_state.get("aud_mode_idx", 0) == 1
        with st.expander("Methoden-Parameter", expanded=not _mode_sw):
            if _mode_sw:
                st.caption(
                    "Fixe Basiswerte für Methoden-Parameter — wirken wenn der jeweilige Parameter im Sweep **nicht** variiert wird."
                )
            else:
                st.caption("Diese Parameter wirken nur auf die passenden Methoden; Hybrid nutzt sie beim Fusionieren der Teilmethoden.")
            m0 = st.columns(4)
            m0[0].number_input("Ridge Glättung", 3, 51, 7, step=2, key="aud_ridge_smooth")
            m0[1].number_input("Ridge max Sprung [% Band]", 1.0, 50.0, 8.0, step=1.0, key="aud_ridge_jump_pct")
            m0[2].number_input("Viterbi max Sprung [Hz/Frame]", 1.0, 300.0, 25.0, step=1.0, key="aud_viterbi_jump_hz")
            m0[3].number_input("Viterbi Sprung-Strafe", 0.0, 10.0, 1.2, step=0.1, key="aud_viterbi_penalty")
            m1 = st.columns(3)
            m1[0].number_input("Viterbi Glättung", 3, 51, 5, step=2, key="aud_viterbi_smooth")
            m1[1].number_input("Comb/HPS Anzahl Harmonische", 1, 10, 4, step=1, key="aud_comb_harmonics")
            m1[2].number_input("Hybrid Glättung", 3, 51, 9, step=2, key="aud_hybrid_smooth")

    def _motor_cand_frag():
        with st.expander("Motor / Kandidaten", expanded=True):
            _is_elekt_fc = "elekt" in str(st.session_state.get("aud_drive_type", "") or "").lower()
            c0 = st.columns(4)
            _dt = c0[0].selectbox("Antrieb", ["Verbrenner/Hybrid", "Hybrid elektrisch dominant", "Elektro"], key="aud_drive_type")
            _is_elekt_fc = "elekt" in str(_dt).lower()
            from app_tabs.audio_sweep import CYL_OPTIONS
            c0[1].selectbox(
                "Zylinder", [str(v) for v in CYL_OPTIONS], index=4, key="aud_cyl_sel",
                disabled=_is_elekt_fc,
                help="'any' = im Parameter-Sweep variieren. Sonst fixer Wert für Analyse.",
            )
            c0[2].selectbox(
                "Takt", ["any", "2", "4"], index=2, key="aud_takt_sel",
                disabled=_is_elekt_fc,
                help="'any' = im Parameter-Sweep variieren.",
            )
            c0[3].selectbox(
                "Ordnung", ["any", "0.5", "1", "2", "3"], index=0, key="aud_order_sel",
                disabled=_is_elekt_fc,
                help="'any' = im Sweep variieren. 0.5 = halbe Grundordnung (4-Takt-Grundton).",
            )
            c1 = st.columns(2)
            c1[0].number_input("RPM min", 100.0, 30000.0, 800.0, step=100.0, key="aud_rpm_min_new")
            c1[1].number_input("RPM max", 500.0, 30000.0, 7500.0, step=100.0, key="aud_rpm_max_new")
            st.caption(
                "'any' Zylinder / Takt / Ordnung → im Sweep variiert; Standard-Analyse nutzt Fallback-Werte. "
                "Bei Elektro: Frequenz direkt als Motor-Frequenz."
            )

    def _getriebe_frag():
        with st.expander("Getriebe / Geschwindigkeit / Fahrzeug", expanded=False):
            c = st.columns(4)
            c[0].slider("Audio Offset [s]", -5.0, 5.0, 0.0, step=0.01, key="aud_offset_new")
            c[1].checkbox("OCR v verwenden", value=True, key="aud_use_v_new")
            c[2].number_input("r dyn [m]", 0.05, 2.0, 0.35, step=0.01, key="aud_rdyn_new")
            c[3].number_input("Toleranz [%]", 0.0, 100.0, 6.0, step=0.5, key="aud_tol_new")
            c2 = st.columns(3)
            c2[0].number_input("Achsübersetzung i", 0.1, 20.0, 3.15, step=0.01, key="aud_axle_ratio")
            c2[1].text_input("Gänge i (Komma-getrennt)", value="5.25, 3.36, 2.17, 1.72, 1.32, 1.00, 0.82, 0.64", key="aud_gears_text")
            c2[2].checkbox("niedrigster Gang bevorzugt", value=False, key="aud_prefer_low")
            st.caption("Getriebe wird nur genutzt, wenn nutzbare Geschwindigkeit/OCR-v vorhanden ist.")

    try:
        _std_stft_frag   = st.fragment()(_std_stft_frag)
        _meth_params_frag = st.fragment()(_meth_params_frag)
        _motor_cand_frag  = st.fragment()(_motor_cand_frag)
        _getriebe_frag    = st.fragment()(_getriebe_frag)
    except Exception:
        pass

    if _mode_standard:
        _std_stft_frag()
        _motor_cand_frag()
        _meth_params_frag()
        _getriebe_frag()

    # ── Mode A: Standard-Analyse ───────────────────────────────────────────────
    if _mode_standard:
        _sp = _std_ss()
        current_audio_config = _build_audio_config_from_values({
            "stft_mode": _sp["stft_mode"],
            "nfft": _sp["nfft"],
            "overlap_pct": _sp["ov"],
            "fmax": _sp["fmax"],
            "method": _sp["method"],
            "drive_type": _sp["drive_type"],
            "cyl_mode": _sp["cyl_mode"],
            "harmonic_mode": _sp["harm_mode"],
            "cyl": _sp["aud_cyl"],
            "order": _sp["aud_order"],
            "takt": _sp["aud_takt"],
            "rpm_min": _sp["rpm_min"],
            "rpm_max": _sp["rpm_max"],
            "audio_offset_s": _sp["aud_offset"],
            "use_ocr_v": _sp["use_ocr_v"],
            "r_dyn_m": _sp["r_dyn"],
            "tol_pct": _sp["tol_pct"],
            "axle_ratio": _sp["axle_ratio"],
            "gear_ratios": _sp["gear_ratios"],
            "prefer_low": _sp["prefer_low"],
            "method_params": _sp["method_params"],
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
                    _json_ok, _json_msg = _write_audio_rpm_json_only(res_bg)
                    if _json_ok:
                        st.session_state.audio_rpm_json_autosaved = _json_msg
                    elif _json_msg:
                        st.session_state.audio_debug_lines = [
                            *list(st.session_state.get("audio_debug_lines", []) or [])[-199:],
                            f"Audio-RPM JSON Auto-Save fehlgeschlagen: {_json_msg}",
                        ]
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
                _sp = _std_ss()
                _std_gear_band_cfg = _audio_build_standard_gear_band_cfg(_sp)
                params_bg = dict(
                    start_s=float(st.session_state.get('t_start', 0.0)),
                    end_s=float(st.session_state.get('t_end', len(y) / max(fs, 1))),
                    offset_s=_sp["aud_offset"],
                    nfft=_sp["nfft"], overlap_pct=_sp["ov"], fmax=_sp["fmax"],
                    cyl=_sp["aud_cyl"], takt=_sp["aud_takt"], order=_sp["aud_order"],
                    rpm_min=_sp["rpm_min"], rpm_max=_sp["rpm_max"],
                    method=_sp["method"], cyl_mode=_sp["cyl_mode"], harmonic_mode=_sp["harm_mode"],
                    drive_type=_sp["drive_type"], stft_mode=_sp["stft_mode"],
                    method_params=_sp["method_params"],
                    gear_band_cfg=_std_gear_band_cfg,
                )
                ui_bg = dict(use_ocr_v=_sp["use_ocr_v"], r_dyn=_sp["r_dyn"], tol_pct=_sp["tol_pct"],
                             axle_ratio=_sp["axle_ratio"], gears=_sp["gear_ratios"], prefer_low=_sp["prefer_low"],
                             vehicle_title=title_txt)
                live_job_id  = f"audio-{int(time.time()*1000)}"
                st.session_state.audio_bg_live_id = live_job_id
                live_log     = [f"[   0.00s] Quelle={source}, fs={fs}, Samples={len(y):,}", "[   0.00s] Hintergrundanalyse gestartet."]
                if _std_gear_band_cfg:
                    live_log.append(
                        "[   0.00s] OCR-Speed Gear-Band aktiv: "
                        f"{len(_std_gear_band_cfg.get('t_ocr') or [])} Punkte, "
                        f"{len(_std_gear_band_cfg.get('gear_ratios') or [])} Gaenge, "
                        f"Modus={_std_gear_band_cfg.get('mode')}, "
                        f"Band +/-{float(_std_gear_band_cfg.get('band_tol_pct', 0.0)):.1f}%"
                    )
                else:
                    live_log.append("[   0.00s] OCR-Speed Gear-Band inaktiv: keine nutzbare v_Fzg_kmph/Getriebe-Konfiguration.")
                live_progress = {"done": 0, "total": 1, "fraction": 0.0, "text": "Hintergrundanalyse gestartet."}
                for _ll in live_log:
                    _audio_live_update(live_job_id, log_line=_ll, progress=live_progress, status="running")
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
            st.button("Audioanalyse in JSON speichern", type="primary", width="stretch", key="aud_save_to_json_ph", disabled=True)

        if isinstance(res, dict) and res.get("t") is not None:
            p = res.get('params', {})
            zyl_txt = "EV" if p.get('cyl') == 0 else p.get('cyl')
            st.caption(f"Quelle: {res.get('source','')} · Methode: {res.get('selected_method','')} · Kandidat: {zyl_txt} Zyl / H{p.get('harmonic')} · Suchband: {p.get('f_search_lo',0):.1f}-{p.get('f_search_hi',0):.1f} Hz · NFFT: {p.get('nfft')} · Overlap: {p.get('overlap_pct')}%")
            try:
                from app_tabs.audio_sweep import audio_candidate_options_from_result, apply_audio_candidate_selection
                _cand_opts = audio_candidate_options_from_result(res)
                _cand_default = str(res.get("selected_candidate_line") or p.get("selected_candidate_line") or "Extractor-Auswahl")
                if _cand_default not in _cand_opts:
                    _cand_default = "Extractor-Auswahl"
                if st.session_state.get("aud_standard_candidate_choice") not in _cand_opts:
                    st.session_state["aud_standard_candidate_choice"] = _cand_default
                _cand_choice = st.selectbox(
                    "RPM-Kandidat auswaehlen",
                    options=_cand_opts,
                    key="aud_standard_candidate_choice",
                    help="Referenzfreie Auswahl aus Extractor-Linien und Anti-Spike-Varianten; Referenz-RPM wird hier nicht verwendet.",
                )
                res = apply_audio_candidate_selection(res, _cand_choice)
                st.session_state.audio_analysis_result_selected = res
                if res.get("selected_candidate_line"):
                    st.caption(f"Gewaehlter RPM-Kandidat: {res.get('selected_candidate_line')}")
            except Exception as _cand_e:
                st.caption(f"Kandidatenauswahl nicht verfuegbar: {_cand_e}")
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
            save_json_disabled = not bool(_result_json_path())
            if st.button("Audioanalyse in JSON speichern", type="primary", width="stretch", key="aud_save_to_json", disabled=save_json_disabled):
                with st.spinner("Audioanalyse wird in JSON gespeichert ..."):
                    ok_aud_save, msg_aud_save = _write_audio_rpm_json_only(res)
                if ok_aud_save:
                    st.success("Audio-RPM und Gangverlauf wurden in die JSON geschrieben.")
                    set_status("Audioanalyse in JSON gespeichert.", "ok")
                else:
                    st.error(msg_aud_save or "Keine Ergebnis-JSON gefunden.")
                    set_status(msg_aud_save or "Keine Ergebnis-JSON gefunden.", "warn")

            if save_json_disabled:
                st.caption("Zum Speichern muss eine Ergebnis-JSON fuer den aktuellen Datensatz vorhanden sein.")

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
            name = f"results_{safe_cf}.json"
            candidates = [_server_results_dir() / name]
            try:
                lb = st.session_state.get("local_base_path")
                if lb:
                    candidates.append(Path(str(lb)).expanduser().resolve() / "results" / name)
            except Exception:
                pass
            try:
                cwd = Path.cwd().resolve()
                gh = cwd.parent if cwd.name == "streamlit_youtube_extractor" else cwd
                candidates.append(gh / "Youtube-Hotlap-Extractor" / "results" / name)
            except Exception:
                pass
            seen = set()
            for p in candidates:
                try:
                    rp = p.resolve()
                except Exception:
                    rp = p
                if str(rp).lower() in seen:
                    continue
                seen.add(str(rp).lower())
                if rp.exists():
                    return rp
            return None

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
        _precheck_ref = {"source": "none", "t_s": None, "rpm": None}
        if _linked_ref is not None:
            _precheck_ref = {
                "source": f"linked:{_linked_ref.get('source_file', '')}",
                "t_s": _linked_ref["t_s"],
                "rpm": _linked_ref["rpm"],
            }
        else:
            _early_file = st.session_state.get("aud_validation_file")
            if _early_file is not None:
                try:
                    _prf_early = parse_ref_file(_early_file.getvalue(), getattr(_early_file, "name", "upload"))
                    _df_early = _prf_early.get("df")
                    if _df_early is not None and not _df_early.empty:
                        _num_cols_early = [
                            c for c in _df_early.columns
                            if pd.api.types.is_numeric_dtype(_df_early[c])
                        ] or list(_df_early.columns)
                        _tc_early = st.session_state.get("aud_val_time_col")
                        _rc_early = st.session_state.get("aud_val_rpm_col")
                        if _tc_early not in _df_early.columns:
                            _tc_early = "t_s" if "t_s" in _df_early.columns else _num_cols_early[0]
                        if _rc_early not in _df_early.columns:
                            _rc_early = "rpm" if "rpm" in _df_early.columns else _num_cols_early[min(1, len(_num_cols_early) - 1)]
                        _precheck_ref = {
                            "source": f"upload:{getattr(_early_file, 'name', '')}",
                            "t_s": pd.to_numeric(_df_early[_tc_early], errors="coerce").to_numpy(dtype=float),
                            "rpm": pd.to_numeric(_df_early[_rc_early], errors="coerce").to_numpy(dtype=float),
                        }
                except Exception:
                    _precheck_ref = {"source": "none", "t_s": None, "rpm": None}

        # ── v_Fzg_kmph aus OCR-JSON laden ────────────────────────────────────
        # Tries ocr.cleaned/table in the current doc first, then sibling result
        # JSONs in the same results directory (e.g. "*_fertig.json").
        _v_ocr_t    = None
        _v_ocr_kmph = None

        def _extract_v_from_doc(doc_dict) -> "tuple | None":
            _ob = (doc_dict.get("recordResult") or {}).get("ocr") or {}
            for _src in (_ob.get("cleaned"), _ob.get("table")):
                if not isinstance(_src, dict):
                    continue
                _vv = _src.get("v_Fzg_kmph")
                _tv = _src.get("time_s") or _src.get("t_s")
                if _vv and _tv and len(_vv) == len(_tv):
                    return (
                        np.array(_tv, dtype=float),
                        np.array([float(v) if v is not None else float("nan") for v in _vv]),
                    )
            return None

        try:
            if _cur_doc:
                _res = _extract_v_from_doc(_cur_doc)
                if _res:
                    _v_ocr_t, _v_ocr_kmph = _res

            if _v_ocr_t is None:
                import json as _jv, glob as _gv
                _jp = _cur_result_json()
                if _jp is not None:
                    _stem = _jp.stem  # e.g. "results_20251104_202910"
                    _sibs = sorted(_jp.parent.glob(f"{_stem}*.json"))
                    for _sib in _sibs:
                        if _sib == _jp:
                            continue
                        try:
                            _sdoc = _jv.loads(_sib.read_text(encoding="utf-8", errors="ignore"))
                            _res = _extract_v_from_doc(_sdoc)
                            if _res:
                                _v_ocr_t, _v_ocr_kmph = _res
                                break
                        except Exception:
                            continue
        except Exception:
            pass

        _has_v_ocr = (
            _v_ocr_t is not None
            and _v_ocr_kmph is not None
            and np.isfinite(_v_ocr_kmph).any()
        )

        # ── Sweep-Konfiguration (vor Messdatei) ───────────────────────────────
        def _render_sweep_preconfig(_has_v, _ocr_t, _ocr_v, _ref_precheck):
            import pandas as _pd_db

            # Apply pending DB values BEFORE any widget is instantiated
            _pending_veh = st.session_state.pop("_sw_pending_veh_data", None)
            if isinstance(_pending_veh, dict):
                for _pk, _pv in _pending_veh.items():
                    st.session_state[_pk] = _pv
            _pending_scale = st.session_state.pop("_sw_pending_gear_scale", None)
            if _pending_scale is not None:
                try:
                    st.session_state["sw_gear_scale"] = float(_pending_scale)
                except Exception:
                    pass
            _pending_tol = st.session_state.pop("_sw_pending_band_tol_pct", None)
            if _pending_tol is not None:
                try:
                    st.session_state["sw_band_tol_pct"] = float(_pending_tol)
                except Exception:
                    pass

            # ── 1. Audio-Parameter + Suchmethode ──────────────────────────────
            with st.expander("Audio-Parameter / Suchmethode", expanded=True):
                _sw1_f, _sw2_f = st.columns(2)
                with _sw1_f:
                    st.markdown("**Audio-Parameter (werden variiert)**")
                    from app_tabs.audio_sweep import (
                        CANDIDATE_FILTER_OPTIONS as _CANDIDATE_FILTER_OPTIONS_F,
                        METHOD_OPTIONS as _ALL_METHODS_F,
                    )
                    _default_methods_f = ["STFT/Ridge", "Viterbi", "Peak", "Autokorrelation/YIN",
                                          "Cepstrum", "Harmonic Comb/HPS", "Hybrid",
                                          "Harmonische Summe", "Bandpass/Autokorr"]
                    st.multiselect("Methoden", options=_ALL_METHODS_F,
                                   default=[m for m in _default_methods_f if m in _ALL_METHODS_F],
                                   key="sw_methods")
                    st.multiselect("NFFT", options=[128, 256, 512, 1024, 2048, 4096, 8192, 16384],
                                   default=[512, 1024, 2048, 4096, 8192], key="sw_nfft")
                    st.multiselect("Overlap [%]", options=[0.0, 25.0, 50.0, 62.5, 75.0, 87.5, 93.75],
                                   default=[50.0, 75.0, 87.5], key="sw_overlap")
                    st.multiselect("Ordnung", options=[0.5, 1.0, 2.0, 3.0],
                                   default=[0.5, 1.0, 2.0, 3.0], key="sw_order")
                    st.multiselect(
                        "Zugelassene RPM-Kandidatentypen",
                        options=_CANDIDATE_FILTER_OPTIONS_F,
                        default=list(_CANDIDATE_FILTER_OPTIONS_F),
                        key="sw_candidate_filter",
                        help=(
                            "Begrenzt, welche generierten RPM-Linien der Sweep bewertet. "
                            "Die konkrete Kandidatenauswahl am Ende bleibt erhalten."
                        ),
                    )
                with _sw2_f:
                    st.markdown("**Suchmethode / Bewertung**")
                    _strat = st.selectbox("Strategie",
                                          ["Optuna (Bayesian)", "Zufällige Suche", "Vollfaktoriell"],
                                          index=0, key="sw_strategy")
                    if _strat != "Vollfaktoriell":
                        st.number_input("Anzahl Trials", min_value=10, max_value=2000,
                                        value=80 if _strat == "Optuna (Bayesian)" else 200,
                                        step=10, key="sw_n_trials")
                    st.number_input("Headroom-Faktor", 1.0, 5.0, 1.5, step=0.1, format="%.1f",
                                    key="sw_fmax_headroom",
                                    help="fmax = f_fundamental_max × Faktor. 1.5 = 50 % Puffer.")
                    st.number_input("Suchbereich +/-Delta [s]", 0.0, 300.0, 10.0, step=1.0,
                                    key="sw_off_range")
                    st.number_input("Suchschritt [s]", 0.05, 5.0, 0.5, step=0.05, format="%.2f",
                                    key="sw_off_step")
                    st.number_input("Toleranz absolut [RPM]", 0.0, 5000.0, 300.0, step=50.0,
                                    key="sw_tol_abs")
                    st.number_input("Toleranz [%]", 0.0, 50.0, 5.0, step=0.5, key="sw_tol_pct_sw")
                    st.selectbox("Toleranz-Logik", ["ODER", "UND"], key="sw_tol_logic")
                    st.number_input("Top-N Ergebnisse", 5, 50, 20, step=5, key="sw_top_n")

            # ── 2. Fahrzeug / Getriebe / RPM-Begrenzung ───────────────────────
            with st.expander(
                "Fahrzeug / Getriebe / RPM-Begrenzung"
                + (" · v_Fzg_kmph aus OCR ✓" if _has_v else ""),
                expanded=True,
            ):
                # ── Fahrzeugdatenbank ──────────────────────────────────────────
                _db_path_str = st.text_input(
                    "Fahrzeugdatenbank (Pfad zur Excel-Datei)",
                    value=st.session_state.get(
                        "sw_db_path",
                        r"C:\Users\Cahyanto\Documents\GitHub\KNIME_DoE\DoE\data\export\db_ocr_tool.xlsx",
                    ),
                    key="sw_db_path",
                    placeholder=r"C:\Pfad\zur\datei.xlsx",
                )
                _DB_PATH = Path(_db_path_str.strip()) if _db_path_str.strip() else Path("")
                if st.session_state.get("_sw_db_path_loaded") != _db_path_str:
                    st.session_state.pop("_sw_veh_db_df", None)
                if _DB_PATH.exists():
                    _db_df = st.session_state.get("_sw_veh_db_df")
                    if _db_df is None:
                        try:
                            _db_df = _pd_db.read_excel(str(_DB_PATH), engine="openpyxl")
                            st.session_state["_sw_veh_db_df"] = _db_df
                            st.session_state["_sw_db_path_loaded"] = _db_path_str
                        except Exception as _dbe:
                            st.caption(f"Fahrzeugdatenbank nicht ladbar: {_dbe}")
                            _db_df = None
                    if _db_df is not None:
                        _search = st.text_input(
                            "Fahrzeug suchen (Marke / Modell / Generation)",
                            key="sw_veh_search",
                            placeholder="z.B. BMW 320d E90",
                        )
                        _db_filtered = _db_df.copy()
                        if _search.strip():
                            _str_cols = [c for c in ["Marke", "Generation", "Variant"] if c in _db_df.columns]
                            _mask = _db_df[_str_cols].apply(
                                lambda col: col.fillna("").astype(str).str.contains(
                                    _search.strip(), case=False, regex=False)
                            ).any(axis=1)
                            _db_filtered = _db_df[_mask].copy()
                        if not _db_filtered.empty:
                            _db_labels = [
                                f"{str(r.get('Marke',''))} {str(r.get('Generation',''))} · "
                                f"{str(r.get('Variant',''))[:55]} "
                                f"({int(r['Jahr']) if _pd_db.notna(r.get('Jahr')) else '?'})"
                                for _, r in _db_filtered.iterrows()
                            ]
                            _db_sel = st.selectbox(
                                f"Fahrzeug ({len(_db_filtered)} Treffer)",
                                range(len(_db_labels)),
                                format_func=lambda i: _db_labels[i],
                                key="sw_veh_sel_idx",
                            )
                            if st.button("Übernehmen", key="sw_veh_apply", type="primary"):
                                _vr = _db_filtered.iloc[int(_db_sel)]
                                _gcols = sorted(
                                    [c for c in _vr.index
                                     if "bersetzung" in c and not c.endswith(".R")],
                                    key=lambda c: int("".join(filter(str.isdigit, c.split(".")[-1])) or "0"),
                                )
                                _gears = [float(_vr[c]) for c in _gcols
                                          if _pd_db.notna(_vr[c]) and float(_vr[c]) > 0]
                                _pending: dict = {}
                                if _gears:
                                    _pending["sw_gear_ratios_text"] = ", ".join(
                                        f"{g:.4g}" for g in _gears)
                                _axle_cols = [c for c in _vr.index
                                              if "Achsantrieb" in c and "Ratio" in c]
                                if _axle_cols and _pd_db.notna(_vr[_axle_cols[0]]):
                                    _pending["sw_axle_ratio"] = float(_vr[_axle_cols[0]])
                                _zcols = [c for c in _vr.index if "Zylinderzahl" in c]
                                if _zcols and _pd_db.notna(_vr[_zcols[0]]):
                                    try:
                                        _pending["aud_cyl_sel"] = str(int(_vr[_zcols[0]]))
                                    except Exception:
                                        pass
                                _verb_cols = [c for c in _vr.index if "Verbrennungsverfahren" in c]
                                if _verb_cols and _pd_db.notna(_vr[_verb_cols[0]]):
                                    _verb = str(_vr[_verb_cols[0]]).lower()
                                    if "elektro" in _verb:
                                        _pending["aud_drive_type"] = "Elektro"
                                    elif "plugin" in _verb or "phev" in _verb:
                                        _pending["aud_drive_type"] = "Hybrid elektrisch dominant"
                                    else:
                                        _pending["aud_drive_type"] = "Verbrenner/Hybrid"
                                st.session_state["_sw_pending_veh_data"] = _pending
                                st.rerun()
                        else:
                            st.caption("Keine Treffer — Suchbegriff anpassen.")
                elif _db_path_str.strip():
                    st.caption(f"Datei nicht gefunden: {_db_path_str.strip()}")

                st.divider()
                # ── Motor / Kandidaten ─────────────────────────────────────────
                _motor_cand_frag()

                st.divider()
                # ── Getriebe / Drehzahlbänder ──────────────────────────────────
                if not _has_v:
                    st.info("v_Fzg_kmph nicht in OCR-Daten gefunden. "
                            "Getriebedaten können trotzdem gesetzt werden.")
                else:
                    st.caption(
                        f"v_Fzg_kmph aus OCR: {len(_ocr_t)} Punkte, "
                        f"{float(_ocr_t[0]):.1f}–{float(_ocr_t[-1]):.1f} s."
                    )

                _use_gb_col, _smooth_col = st.columns([2, 1])
                _use_gb = _use_gb_col.checkbox(
                    "Drehzahlbänder aus v_Fzg_kmph zur RPM-Begrenzung verwenden",
                    key="sw_use_gear_bands", value=True,
                )
                _legacy_ascii_gear_band_label = "Drehzahlbaender aus v_Fzg_kmph zur RPM-Begrenzung verwenden"
                _band_mode_label = _use_gb_col.selectbox("Bandmodus", [
                    "Hard: nur Kandidaten im Band",
                    "Guide: Kandidaten im Band bevorzugen",
                    "Off: keine Bandfuehrung",
                ], key="sw_band_mode")
                _band_mode = {
                    "Hard: nur Kandidaten im Band": "hard",
                    "Guide: Kandidaten im Band bevorzugen": "guide",
                    "Off: keine Bandfuehrung": "off",
                }.get(str(_band_mode_label), "hard")
                _auto_scale = _use_gb_col.checkbox(
                    "Auto-Skalierung der effektiven Uebersetzung",
                    key="sw_auto_gear_scale", value=False,
                    help="Sucht eine globale Skalierung der Gang-/Achsuebersetzung, damit die Referenz-RPM besser in die berechneten Baender faellt.",
                )
                _auto_band_tol = _use_gb_col.checkbox(
                    "Bandbreite automatisch uebernehmen",
                    key="sw_auto_band_tol", value=False,
                    help="Setzt die Bandbreite auf die kleinste Toleranz, bei der mindestens 75% der Referenz-RPM im Band liegen.",
                )
                _use_band_smooth = _smooth_col.checkbox(
                    "Bandwechsel glätten",
                    key="sw_use_band_smooth", value=True,
                    help="Mode-Filter auf Gangzuordnung: verhindert schnelle Hin-und-Her-Sprünge zwischen Bändern.",
                )
                _band_smooth_n = 0
                if _use_gb and _use_band_smooth:
                    _band_smooth_n = st.number_input(
                        "Glättungsfenster [Punkte]", min_value=2, max_value=51,
                        value=int(st.session_state.get("sw_band_smooth_n", 7)),
                        step=2, key="sw_band_smooth_n",
                        help="Anzahl aufeinanderfolgender Punkte im Mode-Filter. "
                             "Höherer Wert = weniger Gangwechsel, mehr Latenz.",
                    )
                _gb_c1_f, _gb_c2_f = st.columns(2)
                with _gb_c1_f:
                    _gears_txt = st.text_input(
                        "Getriebeübersetzungen i_G (kommagetrennt)",
                        value=st.session_state.get(
                            "sw_gear_ratios_text",
                            "5.25, 3.36, 2.17, 1.72, 1.32, 1.00, 0.82, 0.64"),
                        key="sw_gear_ratios_text",
                        help="Übersetzungsverhältnisse je Gang, z.B. '5.25, 3.36, 2.17, …'",
                    )
                    _axle_v = st.number_input(
                        "Achsübersetzung i_A", min_value=0.1, max_value=20.0,
                        value=float(st.session_state.get("sw_axle_ratio", 3.15)),
                        step=0.05, format="%.3f", key="sw_axle_ratio",
                    )
                    _rdyn_v = st.number_input(
                        "r dyn [m]", min_value=0.05, max_value=2.0,
                        value=float(st.session_state.get(
                            "sw_rdyn", st.session_state.get("aud_rdyn_new", 0.35))),
                        step=0.01, format="%.3f", key="sw_rdyn",
                    )
                    _gear_scale_v = st.number_input(
                        "Effektive Uebersetzung Skalierung",
                        min_value=0.50, max_value=1.80,
                        value=float(st.session_state.get("sw_gear_scale", 1.0)),
                        step=0.005, format="%.3f", key="sw_gear_scale",
                        help="Multipliziert alle Ganguebersetzungen. Nuetzlich, wenn Radumfang oder reale Uebersetzung abweichen.",
                    )
                with _gb_c2_f:
                    _btol_v = st.number_input(
                        "Bandbreite ± [%]", min_value=1.0, max_value=30.0,
                        value=float(st.session_state.get("sw_band_tol_pct", 25.0)),
                        step=0.5, format="%.1f", key="sw_band_tol_pct",
                        help="Toleranzband um die berechnete Solldrehzahl je Gang. "
                             "RPM-Werte außerhalb aller Bänder werden hart auf die nächste Bandgrenze geklemmt.",
                    )
                    _band_center_w = st.number_input(
                        "Bandzentrum-Gewichtung", min_value=0.0, max_value=1.0,
                        value=float(st.session_state.get("sw_band_center_weight", 0.65)),
                        step=0.05, format="%.2f", key="sw_band_center_weight",
                        help="0 = nur im Band, 1 = stark zum Bandzentrum ziehen.",
                    )
                    _higher_gear_bias_v = st.number_input(
                        "Hoehere Gaenge bevorzugen", min_value=0.0, max_value=0.5,
                        value=float(st.session_state.get("sw_higher_gear_bias", 0.08)),
                        step=0.01, format="%.2f", key="sw_higher_gear_bias",
                        help="Kleiner Bonus fuer hoehere Gaenge, wenn mehrere Baender passen.",
                    )
                    _gear_shift_penalty_v = st.number_input(
                        "Gangwechsel-Strafe", min_value=0.0, max_value=5.0,
                        value=float(st.session_state.get("sw_gear_shift_penalty", 0.35)),
                        step=0.05, format="%.2f", key="sw_gear_shift_penalty",
                        help="Hoeherer Wert = weniger schnelle Gangwechsel im geglaetteten Gangpfad.",
                    )
                _run_band_precheck = st.button(
                    "Band-Precheck / Korrekturfaktor berechnen",
                    key="sw_run_band_precheck",
                    type="secondary",
                    disabled=not (_use_gb and _has_v and _band_mode != "off"),
                )
                _gb_cfg = None
                if _use_gb and _has_v and _band_mode != "off":
                    try:
                        _gp = [float(x.strip()) for x in
                               str(_gears_txt).replace(";", ",").split(",") if x.strip()]
                    except Exception:
                        _gp = []
                        st.warning("Getriebeübersetzungen konnten nicht geparst werden. "
                                   "Beispiel: 5.25, 3.36, 2.17")
                    if _gp:
                        _ref_band_t = None
                        _ref_band_rpm = None
                        _ref_band_source = str((_ref_precheck or {}).get("source") or "none")
                        try:
                            if (
                                _ref_precheck
                                and _ref_precheck.get("t_s") is not None
                                and _ref_precheck.get("rpm") is not None
                            ):
                                _ref_band_t = np.asarray(
                                    pd.to_numeric(_ref_precheck["t_s"], errors="coerce"),
                                    dtype=float,
                                )
                                _ref_band_rpm = np.asarray(
                                    pd.to_numeric(_ref_precheck["rpm"], errors="coerce"),
                                    dtype=float,
                                )
                        except Exception:
                            _ref_band_t = None
                            _ref_band_rpm = None

                        _base_gb_cfg = {
                            "t_ocr":        list(_ocr_t),
                            "v_kmph_ocr":   list(_ocr_v),
                            "gear_ratios":  _gp,
                            "axle_ratio":   float(_axle_v),
                            "r_dyn":        float(_rdyn_v),
                            "rpm_min":      float(st.session_state.get("aud_rpm_min_new") or 800.0),
                            "rpm_max":      float(st.session_state.get("aud_rpm_max_new") or 7500.0),
                            "band_tol_pct": float(_btol_v),
                            "band_smooth_n": int(_band_smooth_n),
                            "band_center_weight": float(_band_center_w),
                            "higher_gear_bias": float(_higher_gear_bias_v),
                            "gear_shift_penalty": float(_gear_shift_penalty_v),
                            "mode": str(_band_mode),
                        }
                        _band_diag = None
                        _diag_key = (
                            f"{_ref_band_source}|{len(_ref_band_t) if _ref_band_t is not None else 0}|"
                            f"{','.join(f'{float(g):.6g}' for g in _gp)}|{float(_axle_v):.6g}|"
                            f"{float(_rdyn_v):.6g}|{float(_btol_v):.6g}|{len(_ocr_t)}"
                        )
                        _cached_diag = st.session_state.get("_sw_band_diag_cache")
                        if isinstance(_cached_diag, dict) and _cached_diag.get("key") == _diag_key:
                            _band_diag = _cached_diag.get("diag")
                        if _run_band_precheck and _ref_band_t is None:
                            st.warning(
                                "Band-Precheck: keine Referenz-RPM verfuegbar. "
                                "Referenzdatei unten laden oder mit der result-JSON verknuepfen."
                            )
                        if _run_band_precheck and _ref_band_t is not None and _ref_band_rpm is not None:
                            try:
                                from app_tabs.audio_sweep import gear_band_reference_diagnostics
                                _band_diag = gear_band_reference_diagnostics(
                                    _ref_band_t, _ref_band_rpm, _base_gb_cfg,
                                    tolerances=(5, 8, 10, 15, 20, 30),
                                )
                                st.session_state["_sw_band_diag_cache"] = {
                                    "key": _diag_key,
                                    "diag": _band_diag,
                                }
                                _needs_precheck_rerun = False
                                if _auto_scale and bool(_band_diag.get("ok")):
                                    _best_scale_v = float(_band_diag.get("best_scale") or _gear_scale_v)
                                    st.session_state["_sw_pending_gear_scale"] = _best_scale_v
                                    st.success(f"Korrekturfaktor {_best_scale_v:.3f} uebernommen.")
                                    _needs_precheck_rerun = True
                                if _auto_band_tol and bool(_band_diag.get("ok")):
                                    _rec_tol_v = float(_band_diag.get("recommended_tol_pct") or _btol_v)
                                    st.session_state["_sw_pending_band_tol_pct"] = _rec_tol_v
                                    st.success(f"Bandbreite +/-{_rec_tol_v:.1f}% uebernommen.")
                                    _needs_precheck_rerun = True
                                if _needs_precheck_rerun:
                                    st.rerun()
                            except Exception as _bde:
                                st.caption(f"Band-Precheck nicht verfuegbar: {_bde}")

                        _gb_cfg = {
                            "t_ocr":        list(_ocr_t),
                            "v_kmph_ocr":   list(_ocr_v),
                            "gear_ratios":  [float(g) * float(_gear_scale_v) for g in _gp],
                            "axle_ratio":   float(_axle_v),
                            "r_dyn":        float(_rdyn_v),
                            "rpm_min":      float(st.session_state.get("aud_rpm_min_new") or 800.0),
                            "rpm_max":      float(st.session_state.get("aud_rpm_max_new") or 7500.0),
                            "band_tol_pct": float(_btol_v),
                            "band_smooth_n": max(int(_band_smooth_n), 21) if str(_band_mode) == "hard" else int(_band_smooth_n),
                            "band_center_weight": float(_band_center_w),
                            "higher_gear_bias": float(_higher_gear_bias_v),
                            "gear_shift_penalty": max(float(_gear_shift_penalty_v), 1.2) if str(_band_mode) == "hard" else float(_gear_shift_penalty_v),
                            "use_gear_path_viterbi": True,
                            "snap_to_band_center": str(_band_mode) == "hard",
                            "center_blend": 1.0 if str(_band_mode) == "hard" else 0.0,
                            "mode": str(_band_mode),
                            "gear_scale": float(_gear_scale_v),
                        }
                        st.caption(
                            f"Nur Kandidaten im Band zulässig: {len(_gp)} Gänge · "
                            f"i_A={float(_axle_v):.3f} · r_dyn={float(_rdyn_v):.3f} m · ±{float(_btol_v):.1f}%"
                        )
                        st.caption(
                            f"Bandmodus: {_band_mode} | Scale={float(_gear_scale_v):.3f} | "
                            f"Bandbreite +/-{float(_btol_v):.1f}%"
                        )
                        if _band_diag and bool(_band_diag.get("ok")):
                            st.markdown("**Band-Precheck**")
                            _tol_txt = ", ".join(
                                f"+/-{float(k):.0f}%: {float(v):.1f}%"
                                for k, v in (_band_diag.get("ref_band_pct_by_tol") or {}).items()
                            )
                            st.caption(
                                f"Referenz im Band: {_tol_txt} | "
                                f"beste Skalierung: {float(_band_diag.get('best_scale') or 1.0):.3f} "
                                f"({float(_band_diag.get('best_within_pct') or 0.0):.1f}% bei +/-{float(_btol_v):.1f}%)"
                            )
                            try:
                                import plotly.graph_objects as _go_band
                                from app_tabs.audio_sweep import compute_gear_bands
                                _bands_plot = compute_gear_bands(
                                    _ref_band_t,
                                    _gb_cfg["t_ocr"],
                                    _gb_cfg["v_kmph_ocr"],
                                    _gb_cfg["gear_ratios"],
                                    float(_gb_cfg.get("axle_ratio", 3.15)),
                                    float(_gb_cfg.get("r_dyn", 0.35)),
                                    float(_gb_cfg.get("rpm_min", 500.0)),
                                    float(_gb_cfg.get("rpm_max", 8000.0)),
                                    float(_gb_cfg.get("band_tol_pct", 5.0)),
                                )
                                _mask_plot = np.isfinite(_ref_band_t) & np.isfinite(_ref_band_rpm)
                                _idx_plot = np.where(_mask_plot)[0]
                                if len(_idx_plot) > 1200:
                                    _idx_plot = _idx_plot[np.linspace(0, len(_idx_plot) - 1, 1200).astype(int)]
                                _fig_band = _go_band.Figure()
                                _fig_band.add_trace(_go_band.Scatter(
                                    x=_ref_band_t[_idx_plot], y=_ref_band_rpm[_idx_plot],
                                    mode="lines", name="Referenz RPM",
                                ))
                                for _gi in range(min(int(_bands_plot.shape[1]), 8)):
                                    _lo_b = np.asarray(_bands_plot[:, _gi, 0], dtype=float)
                                    _hi_b = np.asarray(_bands_plot[:, _gi, 1], dtype=float)
                                    _fig_band.add_trace(_go_band.Scatter(
                                        x=np.concatenate([_ref_band_t[_idx_plot], _ref_band_t[_idx_plot][::-1]]),
                                        y=np.concatenate([_hi_b[_idx_plot], _lo_b[_idx_plot][::-1]]),
                                        fill="toself", mode="lines", line=dict(width=0),
                                        opacity=0.18, name=f"Band Gang {_gi + 1}",
                                    ))
                                _fig_band.update_layout(
                                    title="Band-Diagnoseplot",
                                    xaxis_title="t [s]", yaxis_title="rpm",
                                    height=360, margin=dict(l=20, r=20, t=40, b=30),
                                )
                                st.plotly_chart(_fig_band, use_container_width=True)
                            except Exception as _bpe:
                                st.caption(f"Band-Diagnoseplot nicht verfuegbar: {_bpe}")
                        else:
                            st.caption(
                                "Band-Precheck noch nicht ausgefuehrt. Button "
                                "'Band-Precheck / Korrekturfaktor berechnen' verwenden."
                            )
                st.session_state["_sw_gear_band_cfg_computed"] = _gb_cfg

            # ── 3. Methoden-Parameter (Basis + Sweep-Variation) ───────────────
            with st.expander("Methoden-Parameter (Basis + Sweep-Variation)", expanded=False):
                st.caption(
                    "Basiswerte: wirken, wenn ein Parameter im Sweep **nicht** variiert wird."
                )
                _m0 = st.columns(4)
                _m0[0].number_input("Ridge Glättung", 3, 51, 7, step=2,
                                    key="aud_ridge_smooth")
                _m0[1].number_input("Ridge max Sprung [% Band]", 1.0, 50.0, 8.0, step=1.0,
                                    key="aud_ridge_jump_pct")
                _m0[2].number_input("Viterbi max Sprung [Hz/Frame]", 1.0, 300.0, 25.0,
                                    step=1.0, key="aud_viterbi_jump_hz")
                _m0[3].number_input("Viterbi Sprung-Strafe", 0.0, 10.0, 1.2, step=0.1,
                                    key="aud_viterbi_penalty")
                _m1 = st.columns(3)
                _m1[0].number_input("Viterbi Glättung", 3, 51, 5, step=2,
                                    key="aud_viterbi_smooth")
                _m1[1].number_input("Comb/HPS Anzahl Harmonische", 1, 10, 4, step=1,
                                    key="aud_comb_harmonics")
                _m1[2].number_input("Hybrid Glättung", 3, 51, 9, step=2,
                                    key="aud_hybrid_smooth")
                st.divider()
                st.markdown("**Optionale Variation im Sweep**")
                _ms1_f, _ms2_f = st.columns(2)
                with _ms1_f:
                    _r = st.checkbox("Ridge-Parameter variieren", key="sw_ridge")
                    if _r:
                        st.multiselect("Ridge Glättung (Sweep)", [3, 7, 11, 21],
                                       default=[7], key="sw_rs")
                        st.multiselect("Ridge max Sprung % (Sweep)", [4, 8, 15],
                                       default=[8], key="sw_rj")
                    _c = st.checkbox("Comb/HPS-Harmonische variieren", key="sw_comb")
                    if _c:
                        st.multiselect("Comb Harmonische (Sweep)", [2, 3, 4, 5],
                                       default=[4], key="sw_ch")
                with _ms2_f:
                    _v = st.checkbox("Viterbi-Parameter variieren", key="sw_viterbi")
                    if _v:
                        st.multiselect("Viterbi max Sprung Hz (Sweep)", [10.0, 25.0, 50.0],
                                       default=[25.0], key="sw_vj")
                        st.multiselect("Viterbi Strafe (Sweep)", [0.5, 1.2, 2.5],
                                       default=[1.2], key="sw_vp")
                        st.multiselect("Viterbi Glättung (Sweep)", [3, 5, 11],
                                       default=[5], key="sw_vs")
                    _h = st.checkbox("Hybrid-Glättung variieren", key="sw_hybrid")
                    if _h:
                        st.multiselect("Hybrid Glättung (Sweep)", [5, 9, 15, 25],
                                       default=[9], key="sw_hs")

            # ── 4. Kombinationen-Schätzung ────────────────────────────────────
            from app_tabs.audio_sweep import build_param_grid as _bpg
            _ss2 = st.session_state
            _pr_est = {
                "sweep_method": True, "method": None,
                "nfft_values":    _ss2.get("sw_nfft",    [2048]),
                "overlap_values": _ss2.get("sw_overlap", [75.0]),
                "fmax_headroom":  float(_ss2.get("sw_fmax_headroom", 1.5)),
                "order_values":   _ss2.get("sw_order",   [1.0]),
                "cyl":            str(_ss2.get("aud_cyl_sel",  "any")),
                "takt":           str(_ss2.get("aud_takt_sel", "4")),
                "rpm_min":        float(_ss2.get("aud_rpm_min_new") or 800.0),
                "rpm_max":        float(_ss2.get("aud_rpm_max_new") or 7500.0),
                "sweep_ridge":    bool(_ss2.get("sw_ridge", False)),
                "ridge_smooth_values":    _ss2.get("sw_rs", None) or [int(_ss2.get("aud_ridge_smooth", 7))],
                "ridge_jump_frac_values": [v / 100.0 for v in (_ss2.get("sw_rj", None) or [int(_ss2.get("aud_ridge_jump_pct", 8))])],
                "sweep_viterbi":  bool(_ss2.get("sw_viterbi", False)),
                "viterbi_jump_hz_values":  _ss2.get("sw_vj", None) or [float(_ss2.get("aud_viterbi_jump_hz", 25.0))],
                "viterbi_penalty_values":  _ss2.get("sw_vp", None) or [float(_ss2.get("aud_viterbi_penalty", 1.2))],
                "viterbi_smooth_values":   _ss2.get("sw_vs", None) or [int(_ss2.get("aud_viterbi_smooth", 5))],
                "sweep_comb":     bool(_ss2.get("sw_comb", False)),
                "comb_harmonics_values":   _ss2.get("sw_ch", None) or [int(_ss2.get("aud_comb_harmonics", 4))],
                "sweep_hybrid":   bool(_ss2.get("sw_hybrid", False)),
                "hybrid_smooth_values":    _ss2.get("sw_hs", None) or [int(_ss2.get("aud_hybrid_smooth", 9))],
            }
            _strat_e  = str(_ss2.get("sw_strategy", "Optuna (Bayesian)"))
            _fact_e   = _strat_e == "Vollfaktoriell"
            _ntr_e    = int(_ss2.get("sw_n_trials", 80)) if not _fact_e else 0
            _meth_e   = _ss2.get("sw_methods") or ["Hybrid"]
            try:
                _est_fact_e = sum(
                    len(_bpg({**_pr_est, "method": _m, "sweep_method": False}))
                    for _m in _meth_e
                )
            except Exception:
                _est_fact_e = 0
            if _fact_e:
                st.caption(f"Geschätzte Kombinationen: **{_est_fact_e}** (Vollfaktoriell)")
            else:
                st.caption(
                    f"Trials: **{_ntr_e}** · Gesamtgrid wäre: {_est_fact_e} "
                    f"({'Optuna lernt aus Ergebnissen' if _strat_e == 'Optuna (Bayesian)' else 'zufällige Stichprobe'})"
                )

            st.session_state["_sw_params_rendered_top"] = True

        # Sweep-Parameter vor Messdatei
        # _render_sweep_preconfig(_has_v_ocr, _v_ocr_t, _v_ocr_kmph)
        _render_sweep_preconfig(_has_v_ocr, _v_ocr_t, _v_ocr_kmph, _precheck_ref)

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

        _sw_gear_band_cfg = st.session_state.get("_sw_gear_band_cfg_computed")
        if _ref_for_sweep is None:
            st.info("Messdatei laden und verknüpfen um den Sweep zu aktivieren.")
        else:
            # Sweep-Parameter wurden oben in _render_sweep_preconfig eingestellt.
            # Session-State lesen und Start/Stop rendern.

            # Derive sweep config preview from session state (for start handler)
            _ss_sw = st.session_state
            _sw_methods      = _ss_sw.get("sw_methods") or []
            from app_tabs.audio_sweep import CANDIDATE_FILTER_OPTIONS as _CANDIDATE_FILTER_OPTIONS_RUN
            _sw_candidate_filter = _ss_sw.get("sw_candidate_filter")
            if _sw_candidate_filter is None:
                _sw_candidate_filter = list(_CANDIDATE_FILTER_OPTIONS_RUN)
            _sw_nfft         = _ss_sw.get("sw_nfft")    or [2048]
            _sw_overlap      = _ss_sw.get("sw_overlap") or [75.0]
            _sw_order        = _ss_sw.get("sw_order")   or [1.0]
            _sw_strategy     = str(_ss_sw.get("sw_strategy", "Optuna (Bayesian)"))
            _sw_use_factorial = _sw_strategy == "Vollfaktoriell"
            _sw_use_optuna   = _sw_strategy == "Optuna (Bayesian)"
            _sw_use_random   = _sw_strategy == "Zufällige Suche"
            _sw_n_trials     = int(_ss_sw.get("sw_n_trials", 80)) if not _sw_use_factorial else 0
            _sw_fmax_headroom = float(_ss_sw.get("sw_fmax_headroom", 1.5))
            _sw_off_range    = float(_ss_sw.get("sw_off_range", 10.0))
            _sw_off_step     = float(_ss_sw.get("sw_off_step", 0.5))
            _sw_tol_abs      = float(_ss_sw.get("sw_tol_abs", 300.0))
            _sw_tol_pct      = float(_ss_sw.get("sw_tol_pct_sw", 5.0))
            _sw_tol_logic    = str(_ss_sw.get("sw_tol_logic", "ODER"))
            _sw_top_n        = int(_ss_sw.get("sw_top_n", 20))
            _sw_ridge        = bool(_ss_sw.get("sw_ridge", False))
            # When not sweeping a method param, use the value from Methoden-Parameter expander
            _sw_ridge_smooth = _ss_sw.get("sw_rs", None) or [int(_ss_sw.get("aud_ridge_smooth", 7))]
            _sw_ridge_jump   = _ss_sw.get("sw_rj", None) or [int(_ss_sw.get("aud_ridge_jump_pct", 8))]
            _sw_comb         = bool(_ss_sw.get("sw_comb", False))
            _sw_comb_h       = _ss_sw.get("sw_ch", None) or [int(_ss_sw.get("aud_comb_harmonics", 4))]
            _sw_viterbi      = bool(_ss_sw.get("sw_viterbi", False))
            _sw_vj           = _ss_sw.get("sw_vj", None) or [float(_ss_sw.get("aud_viterbi_jump_hz", 25.0))]
            _sw_vp           = _ss_sw.get("sw_vp", None) or [float(_ss_sw.get("aud_viterbi_penalty", 1.2))]
            _sw_vs           = _ss_sw.get("sw_vs", None) or [int(_ss_sw.get("aud_viterbi_smooth", 5))]
            _sw_hybrid       = bool(_ss_sw.get("sw_hybrid", False))
            _sw_hs           = _ss_sw.get("sw_hs", None) or [int(_ss_sw.get("aud_hybrid_smooth", 9))]
            _cyl_sel         = str(_ss_sw.get("aud_cyl_sel",  "any"))
            _takt_sel        = str(_ss_sw.get("aud_takt_sel", "4"))
            _sw_cfg_preview = {
                "sweep_method": True, "method": None,
                "nfft_values": _sw_nfft,
                "overlap_values": _sw_overlap,
                "fmax_headroom": _sw_fmax_headroom,
                "order_values": _sw_order,
                "candidate_filter": list(_sw_candidate_filter or []),
                "cyl": _cyl_sel, "takt": _takt_sel,
                "rpm_min": float(_ss_sw.get("aud_rpm_min_new") or 800.0),
                "rpm_max": float(_ss_sw.get("aud_rpm_max_new") or 7500.0),
                "sweep_ridge": _sw_ridge, "ridge_smooth_values": _sw_ridge_smooth,
                "ridge_jump_frac_values": [v / 100.0 for v in _sw_ridge_jump],
                "sweep_viterbi": _sw_viterbi, "viterbi_jump_hz_values": _sw_vj,
                "viterbi_penalty_values": _sw_vp, "viterbi_smooth_values": _sw_vs,
                "sweep_comb": _sw_comb, "comb_harmonics_values": _sw_comb_h,
                "sweep_hybrid": _sw_hybrid, "hybrid_smooth_values": _sw_hs,
            }

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
                        save_sweep_results(str(_cur_jp), _sw_res, gear_band_cfg=_sw_gear_band_cfg)
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
                disabled=_sw_running or not _sw_methods or not _sw_nfft or not _sw_candidate_filter,
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
                                    "candidate_filter": list(_sw_cfg_preview.get("candidate_filter") or []),
                                    "n_combinations": len(_full_grid),
                                    "gear_band_cfg": {
                                        k: v for k, v in (_sw_gear_band_cfg or {}).items()
                                        if k not in ("t_ocr", "v_kmph_ocr")
                                    } if _sw_gear_band_cfg else None,
                                }
                                _aw(_cur_jp_cfg, _dcfg)
                        except Exception:
                            pass

                    _extract_fn       = globals().get("_audio_extract_rpm_robust")
                    _strategy_snap    = _sw_strategy
                    _n_trials_snap    = _sw_n_trials
                    _cfg_snap         = dict(_sw_cfg_preview)
                    _cfg_snap["methods"] = list(_sw_methods)
                    _gear_band_cfg_snap = _sw_gear_band_cfg
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
                                _cand = str(result.get("selected_candidate_line") or "")
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
                                    f"Score={_score:.1f} Within={_within:.1f}% RMSE={_rmse_str}"
                                    f"{(' | Kandidat=' + _cand[:80]) if _cand else ''} | {_best_str}"
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

                        def _do_extract(y, fs, start_s, end_s, offset_s, nfft, overlap_pct, fmax, cyl, takt, order, rpm_min, rpm_max, method, cyl_mode, harmonic_mode, drive_type, stft_mode, method_params, gear_band_cfg=None):
                            return _extract_fn(y, fs, start_s, end_s, offset_s, nfft, overlap_pct, fmax, cyl, takt, order, rpm_min, rpm_max, method, cyl_mode, harmonic_mode, drive_type, stft_mode=stft_mode, method_params=method_params, gear_band_cfg=gear_band_cfg)

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
                            gear_band_cfg=_gear_band_cfg_snap,
                            candidate_filter=_cfg_snap.get("candidate_filter") or None,
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
                        _hdf = pd.DataFrame(hist_ref).copy()
                        _metric = st.selectbox(
                            "Verlauf-Metrik",
                            ["Score", "Within %", "RMSE"],
                            key="audio_sweep_history_metric",
                        )
                        if _metric == "RMSE":
                            _plot_df = _hdf[["trial", "rmse", "best_rmse"]].dropna().rename(columns={
                                "rmse": "RMSE (Trial)", "best_rmse": "Bestes bisher"})
                        elif _metric == "Within %":
                            _plot_df = _hdf[["trial", "within_pct"]].dropna().rename(columns={
                                "within_pct": "Within %"})
                        else:
                            _plot_df = _hdf[["trial", "combined_score"]].dropna().copy()
                            _plot_df["best_score"] = _plot_df["combined_score"].cummax()
                            _plot_df = _plot_df.rename(columns={
                                "combined_score": "Score (Trial)", "best_score": "Bestes bisher"})
                        st.caption("Optuna: **'Bestes bisher'** steigt monoton.")
                        st.line_chart(_plot_df.set_index("trial"), height=220)
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
        _sw_results_raw = st.session_state.get("audio_sweep_results") or []
        _sw_results = [r for r in _sw_results_raw if isinstance(r, dict)]
        if _sw_results != _sw_results_raw:
            st.session_state.audio_sweep_results = _sw_results
        if _sw_results_raw and not _sw_results:
            st.warning("Sweep-Ergebnisse enthalten kein gueltiges Ranking-Format.")
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
            _display_cols = [
                "rank", "combined_score", "within_pct", "rmse", "pearson_r",
                "band_compliance_pct", "jump_in_band_pct",
                "selected_candidate_line",
                "method", "nfft", "overlap_pct", "fmax", "cyl", "takt", "order", "offset_s", "score_error",
            ]
            _display_cols = [c for c in _display_cols if c in _res_df.columns]
            _col_labels   = {
                "rank": "#", "combined_score": "Score", "within_pct": "Innerhalb%",
                "rmse": "RMSE [RPM]", "pearson_r": "r",
                "band_compliance_pct": "Band%", "jump_in_band_pct": "Sprung%",
                "selected_candidate_line": "Kandidat",
                "method": "Methode", "nfft": "NFFT", "overlap_pct": "Overlap%", "fmax": "Fmax Hz",
                "cyl": "Zyl", "takt": "Takt", "order": "Ord", "offset_s": "Offset s",
                "score_error": "Fehler",
            }
            _band_active = "band_compliance_pct" in _res_df.columns and _res_df["band_compliance_pct"].gt(0).any()
            _ccfg = {
                "Score":      st.column_config.ProgressColumn("Score",      min_value=0, max_value=100, format="%.1f"),
                "Innerhalb%": st.column_config.ProgressColumn("Innerhalb%", min_value=0, max_value=100, format="%.1f%%"),
                "Fehler":     st.column_config.TextColumn("Fehler", width="medium"),
            }
            if _band_active:
                _ccfg["Band%"]   = st.column_config.ProgressColumn("Band%",   min_value=0, max_value=100, format="%.1f%%", help="Anteil Zeitpunkte, an denen RPM in einem Getriebeband liegt")
                _ccfg["Sprung%"] = st.column_config.ProgressColumn("Sprung%", min_value=0, max_value=100, format="%.1f%%", help="Anteil Drehzahlsprünge, die zwischen zwei Bändern stattfinden")
            st.dataframe(
                _res_df[_display_cols].rename(columns=_col_labels),
                use_container_width=True, hide_index=True,
                column_config=_ccfg,
            )
            _sw_candidate_labels = [
                f"#{r.get('rank', i+1)} {r.get('selected_candidate_line') or r.get('method','?')} | "
                f"{r.get('method','?')} NFFT={r.get('nfft','?')} Ovl={r.get('overlap_pct','?')}% "
                f"Ord={r.get('order','?')} Score={r.get('combined_score', 0):.1f} "
                f"Innerhalb={r.get('within_pct', 0):.1f}%"
                for i, r in enumerate(_sw_results)
            ]
            try:
                _sw_sel_default = int(st.session_state.get("audio_sweep_candidate_select_idx", 0) or 0)
            except Exception:
                _sw_sel_default = 0
            _sw_sel_default = max(0, min(_sw_sel_default, len(_sw_results) - 1))
            _sw_selected_idx = int(st.selectbox(
                "Sweep-Kandidat auswaehlen",
                options=list(range(len(_sw_results))),
                index=_sw_sel_default,
                format_func=lambda i: _sw_candidate_labels[i],
                key="audio_sweep_candidate_select_idx",
                help="Auswahl eines bewerteten Sweep-Kandidaten fuer Plot und JSON-Export.",
            ))
            if st.session_state.get("_audio_sweep_last_selected_idx") != _sw_selected_idx:
                st.session_state["sw_plot_sel_ranks"] = [_sw_selected_idx]
                st.session_state["_audio_sweep_last_selected_idx"] = _sw_selected_idx

            st.markdown("**RPM-Verläufe vergleichen**")
            st.markdown("**Top-1 RPM-Verlauf (gegen Referenz)**")
            try:
                import plotly.graph_objects as go
                def _to_int(v, default):
                    try: return int(v)
                    except Exception:
                        try: return int(float(v))
                        except Exception: return int(default)
                def _to_float(v, default):
                    try: return float(v)
                    except Exception: return float(default)

                # Rank selection
                _rank_options = [r.get("rank", i+1) for i, r in enumerate(_sw_results)]
                _rank_labels  = _sw_candidate_labels
                _sel_ranks = st.multiselect(
                    "Ränge zum Anzeigen auswählen",
                    options=list(range(len(_sw_results))),
                    default=[_sw_selected_idx],
                    format_func=lambda i: _rank_labels[i],
                    key="sw_plot_sel_ranks",
                )
                _plot_refresh = st.button("Verläufe berechnen", key="sw_multi_plot_refresh", type="primary")

                if _plot_refresh:
                    st.session_state.pop("audio_sw_multi_plot_cache", None)

                _plot_cache: dict = st.session_state.get("audio_sw_multi_plot_cache") or {}
                _extract_plot_fn = globals().get("_audio_extract_rpm_robust")
                if _sel_ranks and not _plot_refresh:
                    _preview_cache: dict = {}
                    for _si in _sel_ranks:
                        _tr_cfg = _sw_results[_si]
                        _pt = np.asarray(_tr_cfg.get("plot_t_s") or [], dtype=float).ravel()
                        _pr = np.asarray(_tr_cfg.get("plot_rpm") or [], dtype=float).ravel()
                        if _pt.size >= 2 and _pt.size == _pr.size:
                            _ck = f"preview|{_si}|{_tr_cfg.get('rank', _si + 1)}"
                            _preview_cache[_ck] = {
                                "idx": _si,
                                "t": _pt,
                                "rpm": _pr,
                                "label": _rank_labels[_si],
                                "offset_s": _to_float(_tr_cfg.get("offset_s", 0.0), 0.0),
                            }
                    if _preview_cache:
                        _plot_cache = _preview_cache
                        st.session_state["audio_sw_multi_plot_cache"] = _preview_cache

                if _sel_ranks and _plot_refresh and callable(_extract_plot_fn):
                    _y_plot  = st.session_state.get("audio_y_raw")
                    _fs_plot = float(st.session_state.get("audio_fs_raw") or 0.0)
                    _seg_s   = float(st.session_state.get("t_start") or 0.0)
                    _seg_e   = float(st.session_state.get("t_end")   or 0.0)
                    if _y_plot is None or _fs_plot <= 0:
                        _ok_ld, _msg_ld, _fs_ld, _y_ld, _ = _audio_load_current_capture()
                        if _ok_ld and _y_ld is not None and np.asarray(_y_ld).size > 0:
                            st.session_state.audio_y_raw  = _y_ld
                            st.session_state.audio_fs_raw = float(_fs_ld)
                            _y_plot  = _y_ld
                            _fs_plot = float(_fs_ld)
                        else:
                            st.warning(f"Audio nicht ladbar: {_msg_ld}")
                    if _y_plot is not None and _fs_plot > 0:
                        _new_cache: dict = {}
                        _spinner_msg = "Top-1 Verlauf wird berechnet..." if _sel_ranks == [0] else f"{len(_sel_ranks)} Verläufe werden berechnet..."
                        with st.spinner(_spinner_msg):
                            for _si in _sel_ranks:
                                _tr_cfg = _sw_results[_si]
                                _ck = (
                                    f"{_current_capture_folder()}|{_tr_cfg.get('method')}|"
                                    f"{_tr_cfg.get('nfft')}|{_tr_cfg.get('overlap_pct')}|"
                                    f"{_tr_cfg.get('fmax')}|{_tr_cfg.get('cyl')}|"
                                    f"{_tr_cfg.get('takt')}|{_tr_cfg.get('order')}|"
                                    f"{_tr_cfg.get('offset_s')}"
                                )
                                _mp = {
                                    "ridge_smooth":    _to_int(_tr_cfg.get("ridge_smooth",   7),   7),
                                    "ridge_jump_frac": _to_float(_tr_cfg.get("ridge_jump_frac", 0.08), 0.08),
                                    "viterbi_jump_hz": _to_float(_tr_cfg.get("viterbi_jump_hz", 25.0), 25.0),
                                    "viterbi_penalty": _to_float(_tr_cfg.get("viterbi_penalty", 1.2), 1.2),
                                    "viterbi_smooth":  _to_int(_tr_cfg.get("viterbi_smooth",   5),   5),
                                    "comb_harmonics":  _to_int(_tr_cfg.get("comb_harmonics",   4),   4),
                                    "hybrid_smooth":   _to_int(_tr_cfg.get("hybrid_smooth",    9),   9),
                                    "always_run_cwt": False, "fast_mode": True,
                                }
                                try:
                                    _ret = _extract_plot_fn(
                                        _y_plot, _fs_plot, _seg_s, _seg_e, 0.0,
                                        _to_int(_tr_cfg.get("nfft", 2048), 2048),
                                        _to_float(_tr_cfg.get("overlap_pct", 75.0), 75.0),
                                        _to_float(_tr_cfg.get("fmax", 500.0), 500.0),
                                        _to_int(_tr_cfg.get("cyl", 4), 4),
                                        _to_int(_tr_cfg.get("takt", 4), 4),
                                        _to_float(_tr_cfg.get("order", 1.0), 1.0),
                                        float(st.session_state.get("aud_rpm_min_new") or 800.0),
                                        float(st.session_state.get("aud_rpm_max_new") or 7500.0),
                                        str(_tr_cfg.get("method", "Hybrid") or "Hybrid"),
                                        "Fest auswählen", "Fest auswählen",
                                        str(st.session_state.get("aud_drive_type", "Verbrenner/Hybrid") or "Verbrenner/Hybrid"),
                                        stft_mode="Fest auswählen", method_params=_mp,
                                    )
                                    if isinstance(_ret, dict):
                                        _ta = np.asarray(_ret.get("t",   []), dtype=float).ravel()
                                        _rpm_lines = _ret.get("rpm_lines") or {}
                                        _cand_name = str(_tr_cfg.get("selected_candidate_line") or "")
                                        if _cand_name and isinstance(_rpm_lines, dict) and _cand_name in _rpm_lines:
                                            _ra = np.asarray(_rpm_lines[_cand_name], dtype=float).ravel()
                                        else:
                                            _ra = np.asarray(_ret.get("rpm", []), dtype=float).ravel()
                                    elif isinstance(_ret, (tuple, list)) and len(_ret) >= 2:
                                        _ta = np.asarray(_ret[0], dtype=float).ravel()
                                        _ra = np.asarray(_ret[1], dtype=float).ravel()
                                    else:
                                        _ta = _ra = np.asarray([], dtype=float)
                                    _new_cache[_ck] = {"idx": _si, "t": _ta, "rpm": _ra,
                                                       "label": _rank_labels[_si],
                                                       "offset_s": _to_float(_tr_cfg.get("offset_s", 0.0), 0.0)}
                                except Exception as _ee:
                                    st.caption(f"Rang {_si+1}: Fehler — {_ee}")
                        st.session_state["audio_sw_multi_plot_cache"] = _new_cache
                        _plot_cache = _new_cache

                # Plot
                if _plot_cache:
                    if _ref_for_sweep is not None:
                        _t_ref_p  = np.asarray(_ref_for_sweep["t_s"], dtype=float).ravel()
                        _rpm_ref_p = np.asarray(_ref_for_sweep["rpm"],  dtype=float).ravel()
                    else:
                        _t_ref_p = _rpm_ref_p = None

                    _fig = go.Figure()
                    if _t_ref_p is not None and _t_ref_p.size >= 2:
                        _mk = np.isfinite(_t_ref_p) & np.isfinite(_rpm_ref_p)
                        _fig.add_trace(go.Scatter(
                            x=_t_ref_p[_mk], y=_rpm_ref_p[_mk],
                            mode="lines", name="Referenz RPM",
                            line=dict(dash="dash", color="white", width=2),
                        ))
                    _colors = ["#00b4d8", "#f77f00", "#06d6a0", "#e63946",
                               "#a8dadc", "#ffd166", "#8ecae6", "#bc6c25"]
                    for _ci, (_ck, _cd) in enumerate(_plot_cache.items()):
                        _ta = _cd["t"]; _ra = _cd["rpm"]
                        if _ta.size < 2:
                            continue
                        _mk2 = np.isfinite(_ta) & np.isfinite(_ra)
                        _off = _cd.get("offset_s", 0.0)
                        _fig.add_trace(go.Scatter(
                            x=_ta[_mk2] + _off, y=_ra[_mk2],
                            mode="lines", name="Top-1 RPM" if int(_cd.get("idx", -1)) == 0 else _cd["label"],
                            line=dict(color=_colors[_ci % len(_colors)]),
                        ))
                    _fig.update_layout(
                        title="Top-1 RPM ueber Zeit",
                        xaxis_title="t [s]", yaxis_title="RPM",
                        height=400, template="plotly_dark",
                        legend=dict(orientation="h", y=-0.25),
                    )
                    st.plotly_chart(_fig, use_container_width=True, key="audio_sweep_top1_plot")
                elif _sel_ranks:
                    st.caption("Ränge auswählen und 'Verläufe berechnen' klicken.")
            except Exception as _top1_e:
                st.warning(f"Verlauf-Plot (Fehler): {_top1_e}")
            _cur_jp_sel = _cur_result_json()
            if st.button(
                "Ausgewaehlten RPM-Verlauf in JSON speichern",
                key="sw_save_selected_audio_rpm",
                disabled=not bool(_cur_jp_sel),
                type="secondary",
            ):
                try:
                    from app_tabs.audio_sweep import save_sweep_results
                    save_sweep_results(
                        str(_cur_jp_sel),
                        _sw_results,
                        gear_band_cfg=_sw_gear_band_cfg,
                        selected_index=_sw_selected_idx,
                    )
                    st.success("Ausgewaehlter RPM- und Gangverlauf wurde in die JSON geschrieben.")
                except Exception as _save_sel_e:
                    st.error(f"JSON-Speichern fehlgeschlagen: {_save_sel_e}")




