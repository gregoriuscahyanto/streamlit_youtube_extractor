"""Renderer for the Streamlit tab extracted from app.py.

The renderer receives app.py globals so existing helper functions and
session-state conventions remain shared during the incremental split.
"""

def render(ns):
    globals().update(ns)
    _scroll_to_top_once()
    if not _has_media_source():
        st.markdown("""
        <div style="text-align:center;padding:3rem 2rem;color:#4a5060;">
          <div style="font-size:2.5rem;margin-bottom:.8rem">VIDEO</div>
          <div style="font-family:'Syne',sans-serif;font-size:1rem;font-weight:600">
            Kein Video geladen</div>
          <div style="font-family:'JetBrains Mono',monospace;font-size:.72rem;
               margin-top:.4rem;color:#2e3545">
            -> Tab CLOUD oeffnen -> Video laden oder von R2 laden</div>
        </div>""", unsafe_allow_html=True)
    else:
        st.markdown(
            """
            <style>
            .roi-compact .section-card { margin-bottom: .4rem !important; padding: .5rem .7rem !important; }
            [data-testid="stTabContent"] { overflow: visible !important; }
            </style>
            """,
            unsafe_allow_html=True,
        )
        st.markdown('<div class="roi-compact">', unsafe_allow_html=True)
        st.subheader("1 · ROI Setup")

        dur = st.session_state.vid_duration
        fps = st.session_state.vid_fps
        fw = st.session_state.vid_width
        fh = st.session_state.vid_height
        step_s = round(1 / max(fps, 1.0), 4)

        prev_start = float(st.session_state.get("_roi_prev_start", st.session_state.t_start))
        prev_end = float(st.session_state.get("_roi_prev_end", st.session_state.t_end))
        prev_tcur = float(st.session_state.get("_roi_prev_tcur", st.session_state.t_current))

        col_v, col_r = st.columns([1, 1], gap="medium")
        with col_v:
            st.markdown('<div class="section-card">', unsafe_allow_html=True)
            st.markdown('<div id="roi-left-width-probe"></div>', unsafe_allow_html=True)
            _sc1, _sc2 = st.columns(2)
            _min_gap = 1.0 / max(fps, 1.0)
            _start_max = max(0.0, float(st.session_state.t_end) - _min_gap)
            t_start = _sc1.slider(
                "Start [s]",
                0.0,
                float(_start_max),
                float(min(max(st.session_state.t_start, 0.0), _start_max)),
                step=step_s,
                format="%d s",
                key="sl_start",
            )
            _end_min = min(float(dur), float(t_start) + _min_gap)
            t_end_raw = _sc2.slider(
                "Ende [s]",
                float(_end_min),
                float(dur),
                float(min(max(st.session_state.t_end, _end_min), float(dur))),
                step=step_s,
                format="%d s",
                key="sl_end",
            )
            t_start, t_end = normalize_time_range(
                start_s=float(t_start),
                end_s=float(t_end_raw),
                duration_s=float(dur),
                fps=float(fps),
            )
            st.session_state.t_start = float(t_start)
            st.session_state.t_end = float(min(t_end, dur))

            start_changed = abs(t_start - prev_start) > 1e-9
            end_changed = abs(st.session_state.t_end - prev_end) > 1e-9
            if start_changed and not end_changed:
                st.session_state.t_current = float(st.session_state.t_start)
            elif end_changed and not start_changed:
                st.session_state.t_current = float(st.session_state.t_end)
            elif start_changed and end_changed:
                st.session_state.t_current = float(st.session_state.t_start)
            st.session_state._roi_prev_start = float(st.session_state.t_start)
            st.session_state._roi_prev_end = float(st.session_state.t_end)

            t_cur = st.slider(
                "Position [s]",
                float(st.session_state.t_start),
                float(st.session_state.t_end),
                float(min(max(st.session_state.t_current, st.session_state.t_start), st.session_state.t_end)),
                step=step_s,
                format="%d s",
                key="sl_cur",
            )
            st.session_state.t_current = float(t_cur)
            frame_idx = int(round(float(t_cur) * max(float(fps), 1.0)))
            prev_frame_idx = st.session_state.get("roi_prev_frame_idx")
            t_changed = (prev_frame_idx is None) or (int(prev_frame_idx) != frame_idx)
            st.session_state._roi_prev_tcur = float(t_cur)
            st.session_state.roi_prev_frame_idx = frame_idx
            if t_changed and isinstance(st.session_state.selected_roi, int) and 0 <= st.session_state.selected_roi < len(st.session_state.rois):
                _ar = st.session_state.rois[st.session_state.selected_roi]
                st.session_state.roi_anchor_box = {
                    "x": int(round(float(_ar.get("x", 0)))),
                    "y": int(round(float(_ar.get("y", 0)))),
                    "w": int(round(float(_ar.get("w", 0)))),
                    "h": int(round(float(_ar.get("h", 0)))),
                }
                st.session_state.roi_wait_user_move = True
                st.session_state.roi_reject_anchor_events = 0

            frame = _get_media_frame(t_cur)
            drag_roi = None
            _editing_idx = st.session_state.selected_roi
            show_draw_box = bool(st.session_state.get("roi_draw_armed", False))
            # Keep all existing ROIs visible; active ROI is still shown by cropper box.
            _skip_bg = None
            if frame is not None:
                vis_rgb = draw_rois(frame, st.session_state.rois, _editing_idx, fw, fh, skip_idx=_skip_bg)
            if frame is not None:
                st.caption(f"t={t_cur:.3f}s  |  {fw}x{fh}  |  {fps:.1f}fps")
                # Hard no-clipping mode: full frame is resized to a fixed fit size (constant per video).
                src_w = int(fw) if int(fw) > 0 else int(vis_rgb.shape[1])
                src_h = int(fh) if int(fh) > 0 else int(vis_rgb.shape[0])
                disp_meta = st.session_state.get("roi_display_meta", {})
                dims_key = (int(src_w), int(src_h))
                if not isinstance(disp_meta, dict) or tuple(disp_meta.get("dims", ())) != dims_key:
                    # Stable width in ROI column, height follows source aspect ratio.
                    target_w = _get_dynamic_roi_target_width(620, "roi-left-width-probe")
                    target_w = min(target_w, max(1, src_w))
                    fit_w = int(target_w)
                    fit_h = max(1, int(round(fit_w * (src_h / float(max(1, src_w))))))
                    disp_meta = {"dims": dims_key, "w": int(fit_w), "h": int(fit_h)}
                    st.session_state.roi_display_meta = disp_meta
                else:
                    target_w_now = _get_dynamic_roi_target_width(int(disp_meta.get("w", 620)), "roi-left-width-probe")
                    target_w_now = min(target_w_now, max(1, src_w))
                    fit_w = int(target_w_now)
                    fit_h = max(1, int(round(fit_w * (src_h / float(max(1, src_w))))))
                    disp_meta = {"dims": dims_key, "w": int(fit_w), "h": int(fit_h)}
                    st.session_state.roi_display_meta = disp_meta
                off_x = 0
                off_y = 0
                if fit_w != src_w or fit_h != src_h:
                    disp_rgb = cv2.resize(vis_rgb, (fit_w, fit_h), interpolation=cv2.INTER_AREA)
                else:
                    disp_rgb = vis_rgb
                scale_x = src_w / float(max(1, fit_w))
                scale_y = src_h / float(max(1, fit_h))

                sel_idx_now = st.session_state.selected_roi
                has_active_roi = (
                    isinstance(sel_idx_now, int)
                    and 0 <= sel_idx_now < len(st.session_state.rois)
                )
                if st_cropper is not None and has_active_roi:
                    src = st.session_state.rois[sel_idx_now]
                    sx = int(round(float(src.get("x", 0))))
                    sy = int(round(float(src.get("y", 0))))
                    sw = int(round(float(src.get("w", 0))))
                    sh = int(round(float(src.get("h", 0))))
                    sx, sy, sw, sh = _clamp_roi_to_video(sx, sy, sw, sh, fw, fh)
                    sx_d = int(round(float(sx) / max(scale_x, 1e-9))) + off_x
                    sy_d = int(round(float(sy) / max(scale_y, 1e-9))) + off_y
                    sw_d = int(round(float(sw) / max(scale_x, 1e-9)))
                    sh_d = int(round(float(sh) / max(scale_y, 1e-9)))
                    sx_d = max(off_x, min(off_x + fit_w - 1, sx_d))
                    sy_d = max(off_y, min(off_y + fit_h - 1, sy_d))
                    sw_d = max(1, min(off_x + fit_w - sx_d, sw_d))
                    sh_d = max(1, min(off_y + fit_h - sy_d, sh_d))

                    crop_box = None
                    pil_vis = Image.fromarray(disp_rgb)
                    cropper_key = (
                        f"roi_cropper_main_{frame_idx}_"
                        f"{int(sel_idx_now) if isinstance(sel_idx_now, int) else -1}_"
                        f"{int(fit_w)}x{int(fit_h)}"
                    )
                    try:
                        crop_box = st_cropper(
                            pil_vis,
                            realtime_update=True,
                            box_color="#4a90a4",
                            aspect_ratio=None,
                            return_type="box",
                            should_resize_image=False,
                            default_coords=(int(sx_d), int(sx_d + sw_d), int(sy_d), int(sy_d + sh_d)),
                            key=cropper_key,
                        )
                    except TypeError:
                        crop_box = st_cropper(
                            pil_vis,
                            realtime_update=True,
                            box_color="#4a90a4",
                            aspect_ratio=None,
                            return_type="box",
                            key=cropper_key,
                        )

                    if isinstance(crop_box, dict):
                        dx_d = int(round(float(crop_box.get("left", sx_d))))
                        dy_d = int(round(float(crop_box.get("top", sy_d))))
                        dw_d = int(round(float(crop_box.get("width", sw_d))))
                        dh_d = int(round(float(crop_box.get("height", sh_d))))
                        x1_d = dx_d
                        y1_d = dy_d
                        x2_d = dx_d + dw_d
                        y2_d = dy_d + dh_d
                        # Intersect with actual image area (exclude black letterbox bars).
                        x1_fit = max(0, min(fit_w, x1_d - off_x))
                        y1_fit = max(0, min(fit_h, y1_d - off_y))
                        x2_fit = max(0, min(fit_w, x2_d - off_x))
                        y2_fit = max(0, min(fit_h, y2_d - off_y))
                        if x2_fit < x1_fit:
                            x1_fit, x2_fit = x2_fit, x1_fit
                        if y2_fit < y1_fit:
                            y1_fit, y2_fit = y2_fit, y1_fit
                        dx = int(round(x1_fit * scale_x))
                        dy = int(round(y1_fit * scale_y))
                        dw = int(round((x2_fit - x1_fit) * scale_x))
                        dh = int(round((y2_fit - y1_fit) * scale_y))
                        if dw > 0 and dh > 0:
                            cx, cy, cw_roi, ch_roi = _clamp_roi_to_video(dx, dy, dw, dh, fw, fh)
                            drag_roi = {"x": int(cx), "y": int(cy), "w": int(cw_roi), "h": int(ch_roi)}
                            st.session_state.drag_roi = drag_roi
                    st.caption("ROI direkt mit der Maus ziehen/skalieren.")
                elif st_cropper is not None:
                    # No active ROI selected: show frame only (no default blue box).
                    st.image(disp_rgb, width="stretch")
                elif streamlit_image_coordinates is not None:
                    st.warning("Drag fehlt: installiere 'streamlit-cropper-fix' fuer Ziehen mit der Maus.")
                    click = streamlit_image_coordinates(disp_rgb, key=f"roi_img_click_{frame_idx}")
                    if click and isinstance(click, dict):
                        cx_d = int(round(float(click.get("x", 0))))
                        cy_d = int(round(float(click.get("y", 0))))
                        cx = int(round(max(0, min(fit_w - 1, cx_d - off_x)) * scale_x))
                        cy = int(round(max(0, min(fit_h - 1, cy_d - off_y)) * scale_y))
                        st.session_state.drag_roi = {"x": cx, "y": cy, "w": 4, "h": 4}
                else:
                    st.image(disp_rgb, width="stretch")
                    st.warning(
                        "Fuer ROI-Drag bitte installieren: pip install streamlit-cropper-fix"
                    )
            else:
                st.warning("Frame nicht verfuegbar.")

            drag_state = st.session_state.get("drag_roi", {})
            if not isinstance(drag_state, dict):
                drag_state = {}
            sel_idx = st.session_state.selected_roi
            _is_active = isinstance(sel_idx, int) and 0 <= sel_idx < len(st.session_state.rois)
            if _is_active:
                cur_sel = st.session_state.rois[sel_idx]
                # Prefer live cropper data; fall back to stored ROI position
                if drag_roi is not None:
                    dx = int(drag_state.get("x", 0))
                    dy = int(drag_state.get("y", 0))
                    dw = int(drag_state.get("w", 0))
                    dh = int(drag_state.get("h", 0))
                else:
                    dx = int(round(float(cur_sel.get("x", 0))))
                    dy = int(round(float(cur_sel.get("y", 0))))
                    dw = int(round(float(cur_sel.get("w", 0))))
                    dh = int(round(float(cur_sel.get("h", 0))))
            else:
                dx = int(drag_state.get("x", 0))
                dy = int(drag_state.get("y", 0))
                dw = int(drag_state.get("w", 0))
                dh = int(drag_state.get("h", 0))

            # Live-sync position: cropper drag updates active ROI x/y/w/h.
            sel_idx = st.session_state.selected_roi
            if (
                drag_roi is not None
                and isinstance(sel_idx, int)
                and 0 <= sel_idx < len(st.session_state.rois)
            ):
                ok_drag, _ = can_add_roi_from_drag({"x": dx, "y": dy, "w": dw, "h": dh})
                if ok_drag:
                    cx, cy, cw_roi, ch_roi = _clamp_roi_to_video(dx, dy, dw, dh, fw, fh)
                    cur = st.session_state.rois[sel_idx]
                    if (
                        int(round(float(cur.get("x", 0)))) != int(cx)
                        or int(round(float(cur.get("y", 0)))) != int(cy)
                        or int(round(float(cur.get("w", 0)))) != int(cw_roi)
                        or int(round(float(cur.get("h", 0)))) != int(ch_roi)
                    ):
                        st.session_state.rois[sel_idx] = {
                            **st.session_state.rois[sel_idx],
                            "x": float(cx), "y": float(cy), "w": float(cw_roi), "h": float(ch_roi),
                        }

            st.markdown('</div>', unsafe_allow_html=True)

        with col_r:
            st.markdown('<div class="section-card">', unsafe_allow_html=True)
            st.markdown('<div class="section-title">ROI-Liste</div>', unsafe_allow_html=True)

            if st.button("ROI hinzuf\u00fcgen", type="primary", width="stretch", key="roi_add_btn"):
                # New ROI starts from a fresh default rectangle (independent from existing ROI).
                _d = seed_drag_roi(fw, fh)
                _cx, _cy, _cw, _ch = _clamp_roi_to_video(
                    int(_d["x"]), int(_d["y"]), int(_d["w"]), int(_d["h"]), fw, fh
                )
                st.session_state.rois.append(dict(
                    name="_", x=float(_cx), y=float(_cy),
                    w=float(_cw), h=float(_ch), fmt="any", max_scale=float(st.session_state.get("roi_global_scale", 1.2)),
                ))
                _ni = len(st.session_state.rois) - 1
                st.session_state.selected_roi = _ni
                st.session_state.roi_draw_armed = True
                st.session_state.drag_roi = {"x": int(_cx), "y": int(_cy), "w": int(_cw), "h": int(_ch)}
                st.session_state.roi_anchor_box = {"x": int(_cx), "y": int(_cy), "w": int(_cw), "h": int(_ch)}
                st.session_state.roi_wait_user_move = True
                st.session_state.roi_reject_anchor_events = 0
                st.session_state.roi_editor_df = None
                set_status("ROI hinzugef\u00fcgt. Name in Tabelle setzen und Position mit K\u00e4stchen anpassen.", "ok")
                st.rerun()

            _rois = st.session_state.rois
            _sel = st.session_state.selected_roi
            _tbl_h = min(220, 38 * (len(_rois) + 1) + 4) if _rois else 80
            _sel_col = "__sel__"
            _base_rows = [
                {
                    _sel_col: bool(i == _sel),
                    "Name": str(r.get("name", "_")),
                    "Format": str(r.get("fmt", "any")) if str(r.get("fmt", "any")) != "custom" else "any",
                    "Pattern": str(r.get("pattern", "")),
                    "Scale": float(r.get("max_scale", st.session_state.get("roi_global_scale", 1.2)) or 1.2),
                    "OCR OK": bool(r.get("ocr_test_ok", False)),
                    "OCR Wert": str(r.get("ocr_test_value", "")),
                    "OCR Details": str(r.get("ocr_test_details", "")),
                }
                for i, r in enumerate(_rois)
            ]
            _roi_cols = [_sel_col, "Name", "Format", "Pattern", "Scale", "OCR OK", "OCR Wert", "OCR Details"]
            _base_df = pd.DataFrame(_base_rows, columns=_roi_cols)
            if _base_df.empty:
                _base_df = pd.DataFrame(
                    {
                        _sel_col: pd.Series(dtype="bool"),
                        "Name": pd.Series(dtype="object"),
                        "Format": pd.Series(dtype="object"),
                        "Pattern": pd.Series(dtype="object"),
                        "Scale": pd.Series(dtype="float"),
                        "OCR OK": pd.Series(dtype="bool"),
                        "OCR Wert": pd.Series(dtype="object"),
                        "OCR Details": pd.Series(dtype="object"),
                    }
                )
            else:
                _base_df[_sel_col] = _base_df[_sel_col].fillna(False).astype(bool)
            _cached_df = st.session_state.get("roi_editor_df")
            if (
                isinstance(_cached_df, pd.DataFrame)
                and list(_cached_df.columns) == list(_base_df.columns)
                and len(_cached_df) == len(_base_df)
            ):
                df_edit = _cached_df.copy().reindex(columns=_roi_cols)
                df_edit[_sel_col] = df_edit[_sel_col].fillna(False).astype(bool)
                df_edit[_sel_col] = [(i == _sel) for i in range(len(df_edit))]
            else:
                df_edit = _base_df.copy()

            if _sel_col not in df_edit.columns:
                df_edit[_sel_col] = False
            df_edit = pd.DataFrame(
                {
                    _sel_col: pd.Series([bool(v) for v in df_edit[_sel_col].tolist()], dtype="bool"),
                    "Name": pd.Series([str(v) for v in df_edit["Name"].tolist()], dtype="object"),
                    "Format": pd.Series([str(v) if str(v) != "custom" else "any" for v in df_edit["Format"].tolist()], dtype="object"),
                    "Pattern": pd.Series([str(v) for v in df_edit.get("Pattern", pd.Series([""] * len(df_edit))).tolist()], dtype="object"),
                    "Scale": pd.Series([float(v or 1.2) for v in df_edit.get("Scale", pd.Series([float(st.session_state.get("roi_global_scale", 1.2))] * len(df_edit))).tolist()], dtype="float"),
                    "OCR OK": pd.Series([bool(v) for v in df_edit.get("OCR OK", pd.Series([False] * len(df_edit))).tolist()], dtype="bool"),
                    "OCR Wert": pd.Series([str(v) for v in df_edit.get("OCR Wert", pd.Series([""] * len(df_edit))).tolist()], dtype="object"),
                    "OCR Details": pd.Series([str(v) for v in df_edit.get("OCR Details", pd.Series([""] * len(df_edit))).tolist()], dtype="object"),
                },
                columns=_roi_cols,
            )

            edited_df = st.data_editor(
                df_edit,
                column_config={
                    _sel_col: st.column_config.CheckboxColumn("", width=42),
                    "Name": st.column_config.SelectboxColumn("Name", options=ROI_NAMES, width=150),
                    "Format": st.column_config.SelectboxColumn("Format", options=FMT_OPTIONS, width=170),
                    "Pattern": st.column_config.TextColumn("Pat.", width=56, disabled=True),
                    "Scale": st.column_config.NumberColumn("Sc.", width=52, disabled=True),
                    "OCR OK": st.column_config.CheckboxColumn("OCR OK", width=70, disabled=True),
                    "OCR Wert": st.column_config.TextColumn("OCR Wert", width=110, disabled=True, help="OCR-Testwert; Details stehen in der Spalte OCR Details."),
                    "OCR Details": st.column_config.TextColumn("OCR Details", width=210, disabled=True, help="raw, conf, scale und frUp aus dem letzten OCR-Test."),
                },
                num_rows="fixed",
                width="stretch",
                hide_index=True,
                height=_tbl_h,
                key=str(st.session_state.get("roi_editor_widget_key", "roi_data_editor_v3")),
            )

            if edited_df is not None and len(edited_df) == len(_rois):
                if _sel_col in edited_df.columns:
                    edited_df[_sel_col] = edited_df[_sel_col].fillna(False).astype(bool)
                st.session_state.roi_editor_df = edited_df.copy()
                _checked_rows = [
                    _i for _i, _row in edited_df.iterrows()
                    if bool(_row.get(_sel_col, False))
                ]
                _newly_sel = int(_checked_rows[0]) if _checked_rows else _sel
                _meta_changed = False
                for _i, _row in edited_df.iterrows():
                    _r = _rois[_i]
                    _nn = str(_row["Name"]) if pd.notna(_row["Name"]) else _r.get("name", "_")
                    _nf = str(_row["Format"]) if pd.notna(_row["Format"]) else _r.get("fmt", "any")
                    if _nf == "custom":
                        _nf = "any"
                    if (_r.get("name") != _nn or _r.get("fmt") != _nf):
                        st.session_state.rois[_i] = {**_r, "name": _nn, "fmt": _nf}
                        st.session_state.rois[_i].pop("pattern", None)
                        _meta_changed = True
                if isinstance(_newly_sel, int) and _newly_sel != _sel and 0 <= _newly_sel < len(st.session_state.rois):
                    st.session_state.selected_roi = _newly_sel
                    st.session_state.roi_draw_armed = True
                    _sr = st.session_state.rois[_newly_sel]
                    st.session_state.roi_anchor_box = {
                        "x": int(round(float(_sr.get("x", 0)))),
                        "y": int(round(float(_sr.get("y", 0)))),
                        "w": int(round(float(_sr.get("w", 0)))),
                        "h": int(round(float(_sr.get("h", 0)))),
                    }
                    st.session_state.roi_wait_user_move = True
                    st.session_state.roi_reject_anchor_events = 0
                    st.rerun()
                if _meta_changed:
                    st.rerun()
            act_sel = st.session_state.selected_roi

            _scale_val = st.number_input(
                "OCR Scale fuer alle ROIs",
                min_value=0.1,
                max_value=5.0,
                value=float(st.session_state.get("roi_global_scale", 1.2)),
                step=0.1,
                key="roi_global_scale_input",
                help="Gemeinsamer Scale-Wert fuer OCR; gilt fuer alle ROIs.",
            )
            if abs(float(st.session_state.get("roi_global_scale", 1.2)) - float(_scale_val)) > 1e-9:
                st.session_state.roi_global_scale = float(_scale_val)
                for _r in st.session_state.rois:
                    if isinstance(_r, dict):
                        _r["max_scale"] = float(_scale_val)

            if isinstance(act_sel, int) and 0 <= act_sel < len(st.session_state.rois):
                sr = st.session_state.rois[act_sel]
                st.caption(
                    f"#{act_sel} {sr.get('name','')} "
                    f"[{int(sr.get('x',0))},{int(sr.get('y',0))},{int(sr.get('w',0))},{int(sr.get('h',0))}]"
                )

            _ocr_probe_indices = _roi_ocr_probe_indices()
            _can_ocr_probe = frame is not None and bool(_ocr_probe_indices)
            _all_ocr_probe_ok = _roi_ocr_all_ok()
            if _all_ocr_probe_ok:
                st.markdown('<style>.st-key-roi_ocr_probe_btn button{background:#3ddc84!important;border-color:#3ddc84!important;color:#07100b!important;box-shadow:0 0 14px rgba(61,220,132,.22)!important;}</style>', unsafe_allow_html=True)

            if bool(st.session_state.get("roi_ocr_probe_running", False)):
                st.session_state.tab_default = "ROI Setup"
                _render_blocking_overlay("OCR-Test ROI läuft ...")
                tess_cmd = find_tesseract_cmd()
                if not tess_cmd:
                    st.session_state.roi_ocr_probe_running = False
                    st.session_state.roi_ocr_probe_result = None
                    set_status("Tesseract wurde nicht gefunden. Installiere Tesseract oder setze TESSERACT_CMD.", "warn")
                    st.rerun()
                all_probe_results = []
                for _idx in _ocr_probe_indices:
                    probe_roi = {
                        **st.session_state.rois[_idx],
                        "max_scale": float(st.session_state.get("roi_global_scale", 1.2)),
                    }
                    probe = diagnose_roi_ocr(
                        frame,
                        probe_roi,
                        (int(fw), int(fh)),
                        tmp_root=LOG_DIR / "ocr_tmp",
                    )
                    _conf = float(probe.get("confidence", 0.0) or 0.0)
                    _scale = probe.get("scale", "")
                    _fr_up = probe.get("frUp", probe.get("fr_up", probe.get("variant", "")))
                    _details = (
                        f"raw={probe.get('raw', '')}; "
                        f"conf={_conf:.2f}; "
                        f"scale={_scale}; "
                        f"frUp={_fr_up}"
                    )
                    st.session_state.rois[_idx] = {
                        **st.session_state.rois[_idx],
                        "ocr_test_ok": bool(probe.get("ok")),
                        "ocr_test_value": probe.get("value", ""),
                        "ocr_test_raw": probe.get("raw", ""),
                        "ocr_test_confidence": _conf,
                        "ocr_test_scale": _scale,
                        "ocr_test_frUp": _fr_up,
                        "ocr_test_error": probe.get("error", ""),
                        "ocr_test_details": _details,
                    }
                    all_probe_results.append({
                        "idx": _idx,
                        "name": st.session_state.rois[_idx].get("name", ""),
                        **probe,
                    })
                st.session_state.roi_ocr_probe_result = all_probe_results
                st.session_state.roi_editor_df = None
                st.session_state.roi_ocr_probe_running = False
                st.session_state.tab_default = "ROI Setup"
                st.rerun()

            if st.button(
                "OCR-Test ROI",
                width="stretch",
                key="roi_ocr_probe_btn",
                disabled=(not _can_ocr_probe) or bool(st.session_state.get("roi_ocr_probe_running", False)),
                help="Testet alle ROIs außer track_minimap.",
            ):
                for _idx in _ocr_probe_indices:
                    st.session_state.rois[_idx]["ocr_test_ok"] = False
                st.session_state.roi_ocr_probe_running = True
                _render_blocking_overlay("OCR-Test ROI läuft ...")
                _ok_probe, _msg_probe = _run_roi_ocr_probe_now(frame, fw, fh, _ocr_probe_indices)
                st.session_state.roi_ocr_probe_running = False
                st.session_state.tab_default = "ROI Setup"
                set_status(_msg_probe, "ok" if _ok_probe else "warn")
                st.rerun()

            if st.button("Ausgew\u00e4hlte ROI l\u00f6schen", width="stretch",
                         key="roi_del_btn", disabled=act_sel is None):
                if isinstance(act_sel, int) and 0 <= act_sel < len(st.session_state.rois):
                    st.session_state.roi_delete_confirm_idx = int(act_sel)

            _confirm_idx = st.session_state.get("roi_delete_confirm_idx")
            if isinstance(_confirm_idx, int) and 0 <= _confirm_idx < len(st.session_state.rois):
                _roi_name = st.session_state.rois[_confirm_idx].get("name", "")
                st.warning(f"ROI #{_confirm_idx} ({_roi_name}) wirklich löschen?")
                _del_yes, _del_no = st.columns(2)
                if _del_yes.button("Ja, löschen", width="stretch", key="roi_del_confirm_yes"):
                    st.session_state.rois.pop(_confirm_idx)
                    st.session_state.selected_roi = None
                    st.session_state.roi_draw_armed = False
                    st.session_state.roi_wait_user_move = False
                    st.session_state.roi_anchor_box = {}
                    st.session_state.roi_reject_anchor_events = 0
                    st.session_state.roi_editor_df = None
                    st.session_state.roi_delete_confirm_idx = None
                    if st.session_state.media_source == "video":
                        get_frame.clear()
                    set_status("ROI gelöscht.", "info")
                    st.rerun()
                if _del_no.button("Nein", width="stretch", key="roi_del_confirm_no"):
                    st.session_state.roi_delete_confirm_idx = None
                    st.rerun()





