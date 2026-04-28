"""Renderer for the Streamlit tab extracted from app.py.

The renderer receives app.py globals so existing helper functions and
session-state conventions remain shared during the incremental split.
"""

def render(ns):
    globals().update(ns)
    st.divider()
    st.subheader("2 · Track Analysis")
    has_ref   = st.session_state.ref_track_img is not None
    track_roi = next((r for r in st.session_state.rois if r["name"]=="track_minimap"),None)
    has_vid   = _has_media_source()
    fw=st.session_state.vid_width; fh=st.session_state.vid_height
    can_cmp = (has_ref and track_roi and has_vid and
               _has_valid_8_points(st.session_state.ref_track_pts) and
               _has_valid_8_points(st.session_state.minimap_pts))

    if not track_roi:
        st.info("[i] Keine track_minimap ROI -> oben in ROI Setup -> ROI anlegen.")

    col_a,col_b=st.columns(2,gap="medium")
    clrs=[(255,80,80),(255,160,0),(255,255,0),(80,255,80),
          (0,200,255),(100,100,255),(200,80,255),(255,80,200)]

    with col_a:
        st.markdown('<div class="section-card">',unsafe_allow_html=True)
        _mat_name = st.session_state.get("ref_track_mat_name", "") or ""
        _ref_title = f"Referenz-Track | {_mat_name}" if _mat_name else "Referenz-Track | Centerline [m]"
        st.markdown(f'<div class="section-title">{_ref_title}</div>', unsafe_allow_html=True)
        if has_ref:
            # P1-P8 already baked into the rendered image by render_centerline_image(); height-limited in this tab.
            st.markdown('<div class="ref-track-fit">', unsafe_allow_html=True)
            st.image(st.session_state.ref_track_img, width=520,
                     caption="P1–P8 fest aus Streckendatei")
            st.markdown('</div>', unsafe_allow_html=True)
            _sl_c1, _sl_c2 = st.columns(2)
            if _sl_c1.button("Neu laden", width="stretch", key="reload_mat_btn"):
                st.session_state.ref_track_img = None
                st.session_state.ref_track_pts = None
                st.session_state.centerline = None
                st.session_state.ref_track_mat_name = ""
                st.rerun()
            _sl_c2.caption("Slim-Datei wird automatisch gespeichert, falls sie in der Cloud fehlt.")
        else:
            st.markdown('<div style="text-align:center;color:#2e3545;padding:.5rem 0;">'
                        'Keine Streckenkarte geladen</div>', unsafe_allow_html=True)
            if not track_roi:
                st.caption("Referenz-Track kann erst geladen werden, wenn eine ROI 'track_minimap' vorhanden ist.")
            # Cloud: list .mat files from reference_track_siesmann/
            if track_roi and st.session_state.r2_connected and st.session_state.r2_client is not None:
                pfx = st.session_state.r2_prefix.strip("/")
                ref_dir = (pfx + "/reference_track_siesmann").strip("/") if pfx else "reference_track_siesmann"
                ok_ls, ref_items = st.session_state.r2_client.list_files(ref_dir)
                if ok_ls and isinstance(ref_items, list):
                    mat_files = [f for f in ref_items if f.lower().endswith(".mat")]
                    mat_files = sorted(
                        mat_files,
                        key=lambda f: (0 if Path(f).stem.lower().endswith("_slim") else 1, Path(f).name.lower()),
                    )
                    if mat_files:
                        sel = st.selectbox(
                            "Streckendatei wählen",
                            mat_files,
                            key="ref_track_sel",
                            label_visibility="collapsed",
                        )
                        if st.button("Aus Cloud laden", width="stretch", key="ref_track_load_btn"):
                            _load_centerline_from_r2(f"{ref_dir}/{sel}", sel)
                            st.rerun()
                    else:
                        st.caption(f"Keine .mat-Dateien in Cloud-Ordner: {ref_dir}")
                else:
                    st.caption("Cloud-Ordner 'reference_track_siesmann' nicht gefunden.")
            elif track_roi:
                st.caption("Cloud nicht verbunden.")
        st.markdown('</div>', unsafe_allow_html=True)

    with col_b:
        st.markdown('<div class="section-card">',unsafe_allow_html=True)
        st.markdown('<div class="section-title">Minimap | Kalibrierung + Farberkennung</div>',
                    unsafe_allow_html=True)
        if has_vid and track_roi:
            _track_t = st.slider(
                "Zeit fuer Farberkennung / Track [s]",
                float(st.session_state.t_start),
                float(st.session_state.t_end),
                float(min(max(st.session_state.t_current, st.session_state.t_start), st.session_state.t_end)),
                step=round(1 / max(float(st.session_state.vid_fps or 25.0), 1.0), 4),
                format="%d s",
                key="track_color_time_slider",
            )
            st.session_state.t_current = float(_track_t)
            frame=_get_media_frame(st.session_state.t_current)
            if frame is not None:
                crop=extract_minimap_crop(frame,track_roi,fw,fh)
                ch,cw=crop.shape[:2]
                mm_pts=list(st.session_state.minimap_pts or [])
                # Sync counter forward if points already loaded from config/MAT
                if st.session_state.minimap_next_pt_idx < len(mm_pts):
                    st.session_state.minimap_next_pt_idx = len(mm_pts)
                next_idx = st.session_state.minimap_next_pt_idx

                # ── Iterativer Track-Overlay ──────────────────────────────────────
                # Ab 4 Punkten: Homographie berechnen und Centerline auf Minimap projizieren.
                # Ergebnis wird in Session-State gecacht; Neuberechnung nur wenn sich Punkte aendern.
                _cl_px   = st.session_state.get("centerline_px")
                _ref_pts = st.session_state.ref_track_pts
                vis_c = crop.copy()
                if _cl_px and _ref_pts and len(mm_pts) >= 4:
                    # Cache-Key: Anzahl und Werte der Punkte + Centerline-Laenge
                    _overlay_cache_key = (
                        tuple(tuple(p) for p in mm_pts),
                        tuple(tuple(p) for p in (_ref_pts or [])),
                        len(_cl_px),
                    )
                    _cached_overlay = st.session_state.get("_track_overlay_cache")
                    if (
                        isinstance(_cached_overlay, dict)
                        and _cached_overlay.get("key") == _overlay_cache_key
                    ):
                        _cl_int = _cached_overlay["cl_int"]
                        _overlay_pts = _cached_overlay["n_pts"]
                    else:
                        try:
                            n_use = min(len(mm_pts), len(_ref_pts))
                            H_fwd, _ = cv2.findHomography(
                                np.array(mm_pts[:n_use], dtype=np.float32),
                                np.array(_ref_pts[:n_use], dtype=np.float32),
                                cv2.RANSAC, 5.0,
                            )
                            if H_fwd is not None:
                                H_inv = np.linalg.inv(H_fwd)
                                cl_sub = np.array(_cl_px[::15], dtype=np.float32).reshape(-1, 1, 2)
                                cl_mm  = cv2.perspectiveTransform(cl_sub, H_inv).reshape(-1, 2)
                                _cl_int = np.round(cl_mm).astype(int)
                                _overlay_pts = n_use
                            else:
                                _cl_int = None
                                _overlay_pts = 0
                        except Exception:
                            _cl_int = None
                            _overlay_pts = 0
                        st.session_state["_track_overlay_cache"] = {
                            "key": _overlay_cache_key,
                            "cl_int": _cl_int,
                            "n_pts": _overlay_pts,
                        }
                    if _cl_int is not None and _overlay_pts > 0:
                        vis_overlay = vis_c.copy()
                        for i in range(len(_cl_int) - 1):
                            p1 = (int(_cl_int[i, 0]),   int(_cl_int[i, 1]))
                            p2 = (int(_cl_int[i+1, 0]), int(_cl_int[i+1, 1]))
                            if (0 <= p1[0] < cw and 0 <= p1[1] < ch and
                                    0 <= p2[0] < cw and 0 <= p2[1] < ch):
                                cv2.line(vis_overlay, p1, p2, (0, 220, 100), 1)
                        vis_c = cv2.addWeighted(vis_c, 0.70, vis_overlay, 0.30, 0)
                else:
                    _overlay_pts = 0

                # Draw set points on top of overlay (white ring + colored fill + shadow label)
                for pi, pt in enumerate(mm_pts):
                    if pt and len(pt) == 2:
                        px_i, py_i = int(pt[0]), int(pt[1])
                        cv2.circle(vis_c, (px_i, py_i), 9, (255,255,255), 2)
                        cv2.circle(vis_c, (px_i, py_i), 6, clrs[pi%8], -1)
                        cv2.putText(vis_c, f"P{pi+1}", (px_i+10, py_i+5),
                                    cv2.FONT_HERSHEY_SIMPLEX, .45, (0,0,0), 3)
                        cv2.putText(vis_c, f"P{pi+1}", (px_i+10, py_i+5),
                                    cv2.FONT_HERSHEY_SIMPLEX, .45, clrs[pi%8], 1)

                if streamlit_image_coordinates is None:
                    st.warning("Bitte installieren: pip install streamlit-image-coordinates")
                    st.image(vis_c, width="stretch", caption=f"Minimap ({cw}x{ch}px)")
                elif next_idx < 8:
                    # ── Kalibrierung: P1 … P8 anklicken ──
                    # Fixed widget key + dedup: avoids image disappearing when key changes.
                    # The widget returns the last click on every rerun; we only act on a NEW click.
                    _overlay_info = (f"  ·  Track-Overlay: {_overlay_pts} Punkte"
                                     if _overlay_pts >= 4 else "")
                    st.caption(
                        f"Klicke **P{next_idx+1}** auf der Minimap  ·  {next_idx}/8 gesetzt"
                        + _overlay_info
                    )
                    _last_cal = st.session_state.get("_mm_last_click")
                    click = streamlit_image_coordinates(vis_c, key="mm_calibrate")
                    if click and isinstance(click, dict) and click != _last_cal:
                        st.session_state["_mm_last_click"] = click
                        x = int(round(float(click.get("x", 0))))
                        y = int(round(float(click.get("y", 0))))
                        while len(mm_pts) <= next_idx:
                            mm_pts.append([0, 0])
                        mm_pts[next_idx] = [x, y]
                        st.session_state.minimap_pts = mm_pts
                        st.session_state.minimap_next_pt_idx = next_idx + 1
                        st.rerun()
                else:
                    # ── 8 Punkte fertig → Farberkennung per Klick ──
                    # Live detection with current color range (runs every render)
                    cr = st.session_state.moving_pt_color_range
                    mp_live = detect_moving_point(crop, cr)

                    # Overlay: detected blob (yellow) + last click position (cyan cross)
                    vis_detect = vis_c.copy()
                    if mp_live:
                        dx, dy = int(mp_live["x"]), int(mp_live["y"])
                        cv2.circle(vis_detect, (dx, dy), 12, (255, 255, 0), 2)
                        cv2.circle(vis_detect, (dx, dy),  3, (255, 255, 0), -1)
                    _clk_pos = st.session_state.get("_mm_color_click_px")
                    if _clk_pos and 0 <= _clk_pos[0] < cw and 0 <= _clk_pos[1] < ch:
                        cv2.drawMarker(
                            vis_detect, (int(_clk_pos[0]), int(_clk_pos[1])),
                            (0, 255, 255), cv2.MARKER_CROSS, 14, 2,
                        )

                    # Color swatch for current target color
                    h_m=(cr["h_lo"]+cr["h_hi"])//2
                    s_m=(cr["s_lo"]+cr["s_hi"])//2
                    v_m=(cr["v_lo"]+cr["v_hi"])//2
                    swatch=np.zeros((20,40,3),dtype=np.uint8)
                    swatch[:]=cv2.cvtColor(
                        np.array([[[h_m,s_m,v_m]]],dtype=np.uint8),
                        cv2.COLOR_HSV2RGB)[0,0]

                    detected_lbl = "✓ Erkannt" if mp_live else "✗ Nicht erkannt"
                    sc1, sc2 = st.columns([3,1])
                    sc2.image(swatch, caption="Zielfarbe", width="stretch")

                    _last_col = st.session_state.get("_mm_last_color_click")
                    color_click = streamlit_image_coordinates(vis_detect, key="mm_color_pick")
                    if color_click and isinstance(color_click, dict) and color_click != _last_col:
                        st.session_state["_mm_last_color_click"] = color_click
                        cx = max(0, min(cw-1, int(round(float(color_click.get("x",0))))))
                        cy = max(0, min(ch-1, int(round(float(color_click.get("y",0))))))
                        st.session_state["_mm_color_click_px"] = (cx, cy)
                        pixel_rgb = crop[cy, cx]
                        hsv_px = cv2.cvtColor(
                            np.array([[pixel_rgb]],dtype=np.uint8),
                            cv2.COLOR_RGB2HSV)[0,0]
                        h,s,v = int(hsv_px[0]),int(hsv_px[1]),int(hsv_px[2])
                        st.session_state.moving_pt_color_range = dict(
                            h_lo=max(0,h-15),   h_hi=min(179,h+15),
                            s_lo=max(0,s-60),   s_hi=min(255,s+60),
                            v_lo=max(0,v-60),   v_hi=min(255,v+60),
                        )
                        set_status(f"Farbe gesetzt: HSV({h},{s},{v})","ok")
                        st.rerun()

                # Reset / Undo buttons
                rb1, rb2 = st.columns(2)
                if rb1.button("Zurücksetzen", width="stretch", key="mm_pts_reset"):
                    st.session_state.minimap_pts = []
                    st.session_state.minimap_next_pt_idx = 0
                    st.session_state["_mm_last_click"] = None
                    st.session_state["_mm_last_color_click"] = None
                    st.rerun()
                if rb2.button("Letzten entfernen", width="stretch", key="mm_pts_undo"):
                    if next_idx > 0:
                        st.session_state.minimap_pts = mm_pts[:next_idx-1]
                        st.session_state.minimap_next_pt_idx = next_idx-1
                        st.rerun()
                if st.button("Vergleich 5 Zeiten", type="primary", width="stretch", key="cmp_5_times_btn", disabled=not can_cmp):
                    st.session_state["_run_compare_5_times"] = True
                if not can_cmp:
                    st.caption("Benötigt: Referenztrack, track_minimap ROI, Video und je 8 Punkte.")
        else:
            st.markdown('<div style="text-align:center;color:#2e3545;padding:2rem;">'
                        'Video + track_minimap ROI benötigt</div>',unsafe_allow_html=True)
        st.markdown('</div>',unsafe_allow_html=True)

    def _centerline_progress_percent(ref_pt, centerline_px) -> float | None:
        if ref_pt is None or not centerline_px:
            return None
        try:
            p = np.array(ref_pt, dtype=float).reshape(2)
            cl = np.asarray(centerline_px, dtype=float).reshape(-1, 2)
            if cl.shape[0] < 2:
                return None
            seg = cl[1:] - cl[:-1]
            seg_len = np.linalg.norm(seg, axis=1)
            total = float(np.sum(seg_len))
            if total <= 0:
                return None
            best_s = 0.0
            best_d2 = float("inf")
            cum = np.concatenate([[0.0], np.cumsum(seg_len)])
            for i, v in enumerate(seg):
                l2 = float(np.dot(v, v))
                if l2 <= 0:
                    continue
                u = float(np.clip(np.dot(p - cl[i], v) / l2, 0.0, 1.0))
                q = cl[i] + u * v
                d2 = float(np.sum((p - q) ** 2))
                if d2 < best_d2:
                    best_d2 = d2
                    best_s = float(cum[i] + u * seg_len[i])
            return float(np.clip(100.0 * best_s / total, 0.0, 100.0))
        except Exception:
            return None

    def _comparison_overlay_low_opacity(crop, cmp):
        overlay = draw_comparison_overlay(
            crop, st.session_state.ref_track_img,
            st.session_state.minimap_pts, st.session_state.ref_track_pts,
            cmp, st.session_state.moving_pt_color_range,
        )
        try:
            if overlay is not None and overlay.shape == crop.shape:
                return cv2.addWeighted(crop, 0.15, overlay, 0.85, 0)
        except Exception:
            pass
        return overlay

    if st.session_state.pop("_run_compare_5_times", False) and can_cmp:
        with st.spinner("Vergleich 5 Zeiten läuft ..."):
            rng = np.random.default_rng(12345)
            lo, hi = float(st.session_state.t_start), float(st.session_state.t_end)
            times = sorted(rng.uniform(lo, hi, size=5).tolist()) if hi > lo else [lo] * 5
            results = []
            for _t in times:
                _frame = _get_media_frame(float(_t))
                if _frame is None:
                    continue
                _crop = extract_minimap_crop(_frame, track_roi, fw, fh)
                _cmp = compare_minimap_to_reference(
                    _crop, st.session_state.ref_track_img,
                    st.session_state.minimap_pts, st.session_state.ref_track_pts,
                )
                if _cmp.get("error"):
                    continue
                _mp = detect_moving_point(_crop, st.session_state.moving_pt_color_range)
                _ref_pt = None
                _progress = None
                if _mp:
                    _ref_pt = project_point_with_homography((_mp["x"], _mp["y"]), _cmp.get("H"))
                    _progress = _centerline_progress_percent(_ref_pt, st.session_state.get("centerline_px"))
                _overlay = _comparison_overlay_low_opacity(_crop, _cmp)
                results.append({
                    "t": float(_t), "cmp": _cmp, "mp": _mp,
                    "ref_pt": _ref_pt, "progress_pct": _progress,
                    "overlay": _overlay,
                })
            st.session_state.track_comparison_samples = results
            set_status(f"Vergleich fuer {len(results)} Zeiten durchgefuehrt.", "ok")
        st.rerun()

    st.markdown('<div class="section-card">',unsafe_allow_html=True)
    st.markdown('<div class="section-title">Vergleich | Ueberlagerung | Bewegende Punkte</div>',
                unsafe_allow_html=True)
    _samples = st.session_state.get("track_comparison_samples") or []
    if _samples:
        st.markdown("**Test: 5 zufaellige Zeiten zwischen Start und Ende**")
        _cols = st.columns(5)
        for _col, _res in zip(_cols, _samples[:5]):
            _col.image(_res["overlay"], width="stretch", caption=f"t={_res['t']:.2f}s")
            _c = _res.get("cmp", {})
            _mp = _res.get("mp")
            _progress = _res.get("progress_pct")
            _pos_html = f"<div class='track-progress-big'>{_progress:.1f}%</div>" if _progress is not None else "<div class='track-progress-big'>n/a</div>"
            _col.markdown(_pos_html, unsafe_allow_html=True)
            _col.caption(
                f"ø={_c.get('mean_dist_px', 0.0):.1f}px · max={_c.get('max_dist_px', 0.0):.1f}px · "
                f"pt={'ja' if _mp else 'nein'}"
            )
    else:
        st.caption("Noch kein Vergleich durchgeführt. Button steht unter Zurücksetzen / Letzten entfernen.")
    st.markdown('</div>',unsafe_allow_html=True)



    st.divider()
    st.subheader("3 · Speicherung")
    st.caption("Speichert die aktuelle ROI-, Zeit- und Track-Konfiguration gemeinsam als JSON und MAT. Downloads sind nur optional nach dem Speichern.")
    _has_any_roi = len(st.session_state.get("rois") or []) > 0
    _save_busy = bool(st.session_state.get("roi_save_running", False))
    _ocr_probe_busy = bool(st.session_state.get("roi_ocr_probe_running", False))
    _ocr_ready_to_save = _roi_ocr_all_ok()

    if bool(st.session_state.get("roi_next_load_running", False)):
        st.session_state.tab_default = "ROI Setup"
        _render_blocking_overlay("Nächste Datei wird geladen ...")
        ok_next, msg_next = _load_next_roi_setup_file()
        st.session_state.roi_next_load_running = False
        st.session_state.tab_default = "ROI Setup"
        set_status(msg_next if isinstance(msg_next, str) else str(msg_next), "ok" if ok_next else "warn")
        st.rerun()

    # Alter/Stale Save-State darf die Seite nicht blockieren. Speichern laeuft
    # synchron im Button-Klick und verwendet keinen persistenten Fixed-Overlay.
    if _save_busy:
        st.session_state.roi_save_running = False
        _save_busy = False

    if st.button("Speichern", type="primary", width="stretch", key="roi_save_json_mat_btn_bottom", disabled=(_save_busy or _ocr_probe_busy or not _has_any_roi or not _ocr_ready_to_save), help="Erst aktiv, wenn der OCR-Test ROI grün ist."):
        st.session_state.tab_default = "ROI Setup"
        st.session_state.roi_save_running = True
        try:
            with st.spinner("Speichern läuft ..."):
                ok_save, msg_save, payload_save = _save_result_json_and_mat()
            st.session_state["_last_save_payload"] = payload_save
            st.session_state.roi_saved_once = bool(ok_save)
            set_status(msg_save, "ok" if ok_save else "warn")
        except Exception as e:
            st.session_state.roi_saved_once = False
            set_status(f"Speichern fehlgeschlagen: {e}", "warn")
        finally:
            st.session_state.roi_save_running = False
            _save_busy = False

    if st.button("Kein ROI vorhanden", width="stretch", key="roi_mark_no_roi_btn_bottom", disabled=(_save_busy or _ocr_probe_busy), help="Stempelt die aktuelle Datei als nicht OCR/ROI-verwertbar. Sie wird danach in MAT Selection standardmäßig ausgeblendet."):
        st.session_state.tab_default = "ROI Setup"
        st.session_state.roi_save_running = True
        try:
            with st.spinner("Kein-ROI-Stempel wird gespeichert ..."):
                ok_save, msg_save, payload_save = _save_result_json_and_mat(no_roi=True)
            st.session_state["_last_save_payload"] = payload_save
            st.session_state.roi_saved_once = bool(ok_save)
            set_status(msg_save, "ok" if ok_save else "warn")
        except Exception as e:
            st.session_state.roi_saved_once = False
            set_status(f"Kein-ROI-Stempel fehlgeschlagen: {e}", "warn")
        finally:
            st.session_state.roi_save_running = False
            _save_busy = False

    _next_disabled = _ocr_probe_busy or bool(st.session_state.get("roi_next_load_running", False)) or (not bool(st.session_state.get("roi_saved_once", False)))
    if st.button("Nächste Datei laden", width="stretch", key="roi_load_next_missing_btn_bottom", disabled=_next_disabled):
        st.session_state.roi_next_load_running = True
        st.session_state.tab_default = "ROI Setup"
        st.rerun()

    _last_save = st.session_state.get("_last_save_payload") or {}
    if _last_save:
        targets = " · ".join(str(x) for x in (_last_save.get("targets") or []))
        st.markdown(f'<div class="save-status-card">Zuletzt gespeichert: <b>{_last_save.get("json_name", "results.json")}</b> + <b>{_last_save.get("mat_name", "results.mat")}</b><br>{targets}</div>', unsafe_allow_html=True)
        with st.expander("Optionale Downloads anzeigen", expanded=False):
            st.caption("Die Dateien wurden bereits gespeichert. Diese Buttons sind nur für eine lokale Kopie.")
            _dl_json_col, _dl_mat_col = st.columns(2)
            _dl_json_col.download_button("JSON herunterladen", _last_save.get("json_bytes", b""), _last_save.get("json_name", "results.json"), "application/json", width="stretch", key="json_download_bottom")
            _dl_mat_col.download_button("MAT herunterladen", _last_save.get("mat_bytes", b""), _last_save.get("mat_name", "results.mat"), "application/octet-stream", width="stretch", key="mat_download_bottom")

    if False and st.session_state.moving_pt_history:
        st.markdown('<div class="section-card">',unsafe_allow_html=True)
        st.markdown('<div class="section-title">Verlauf bewegender Punkt</div>',
                    unsafe_allow_html=True)
        import pandas as pd
        c1,c2=st.columns([1,4])
        c1.metric("Positionen",len(st.session_state.moving_pt_history))
        if c1.button("Leeren",key="hist_clear"):
            st.session_state.moving_pt_history=[]; st.rerun()
        df=pd.DataFrame(st.session_state.moving_pt_history[-100:])
        c2.dataframe(df, width="stretch", height=180)
        st.markdown('</div>',unsafe_allow_html=True)
