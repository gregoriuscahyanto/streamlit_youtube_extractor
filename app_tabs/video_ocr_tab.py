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
    st.session_state.setdefault("video_ocr_full_target_fps", "2")
    st.session_state.setdefault("ocr_scope_charts", [
        {"title": "Diagramm 1", "x_col": "time_s", "y_cols": [], "plot_type": "line"},
    ])

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
        wd_ocr_active = bool(wd_running and "OCR" in wd_current and capture_folder_now and capture_folder_now in wd_current)
        wd_ocr_running = bool(wd_running and "OCR" in wd_current)
    except Exception:
        wd_snap = {}
        wd_running = False
        wd_current = ""
        wd_ocr_active = False
        wd_ocr_running = False

    if wd_ocr_active:
        st.info(
            f"**Watchdog läuft automatisiert:** {wd_current}\n\n"
            "OCR wird im Hintergrund durchgeführt. Manuelle Auswertung ist währenddessen deaktiviert.",
            icon="🤖",
        )
    elif wd_ocr_running:
        _wd_live_folder_hint = str((wd_snap.get("ocr_live") or {}).get("folder") or "")
        st.info(
            f"**Watchdog OCR läuft** für Ordner: `{_wd_live_folder_hint or wd_current}` — Live-Daten werden unten angezeigt.",
            icon="🤖",
        )
    elif wd_running:
        st.caption(f"Watchdog aktiv (anderer Task): {wd_current or '—'}")

    def _watchdog_live_ocr_for_folder(folder: str, wd_cur: str) -> tuple[dict, list[dict], str]:
        """Read live OCR progress/snapshots from results JSON while watchdog OCR runs."""
        if not folder:
            return {}, [], ""
        base_lp = str(st.session_state.get("local_base_path") or "").strip()
        base_dir = Path(base_lp).expanduser().resolve() if base_lp else Path.cwd()
        json_candidates = [
            base_dir / "results" / f"results_{folder}.json",
            Path(str(st.session_state.get("mat_selected_key") or "").strip()),
            Path("_temp") / f"results_{folder}.json",
        ]
        json_path = None
        for cand in json_candidates:
            try:
                if cand and str(cand).strip() and cand.exists() and cand.is_file():
                    json_path = cand
                    break
            except Exception:
                continue
        if json_path is None:
            return {}, [], ""

        try:
            doc = json.loads(json_path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            return {}, [], str(json_path)
        rr = doc.get("recordResult") if isinstance(doc, dict) else {}
        if not isinstance(rr, dict):
            return {}, [], str(json_path)
        ocr = rr.get("ocr") if isinstance(rr.get("ocr"), dict) else {}
        tbl = ocr.get("table") if isinstance(ocr.get("table"), dict) else {}
        if not isinstance(tbl, dict) or not tbl:
            return {}, [], str(json_path)

        time_col = list(tbl.get("time_s") or [])
        frame_col = list(tbl.get("frame_idx") or [])
        row_count = len(time_col) if time_col else len(frame_col)
        if row_count <= 0:
            return {}, [], str(json_path)

        # Parse frame progress from watchdog current line: "... Frame X/Y (Z%)"
        done_frame = total_frame = None
        if "Frame " in str(wd_cur or "") and "/" in str(wd_cur or ""):
            try:
                tail = str(wd_cur).split("Frame ", 1)[1]
                lhs = tail.split("(", 1)[0].strip()
                a_str, b_str = lhs.split("/", 1)
                done_frame = int(float(a_str.strip()))
                total_frame = int(float(b_str.strip()))
            except Exception:
                done_frame = total_frame = None

        # Build last snapshots (numbers table shown in UI)
        keys = list(tbl.keys())
        start_idx = max(0, row_count - 40)
        live_rows: list[dict] = []
        for i in range(start_idx, row_count):
            row = {}
            for k in keys:
                v = tbl.get(k)
                if isinstance(v, list) and i < len(v):
                    row[k] = v[i]
            if row:
                live_rows.append(row)

        last_t = 0.0
        try:
            if time_col:
                last_t = float(time_col[-1])
        except Exception:
            last_t = 0.0

        summary = {
            "done": int(done_frame or row_count),
            "total": int(total_frame or max(row_count, 1)),
            "t_s": float(last_t),
            "rows": int(row_count),
            "partial": bool((ocr.get("params") or {}).get("partial")) if isinstance(ocr.get("params"), dict) else False,
        }
        return summary, live_rows, str(json_path)

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

    running = _is_running()

    _fps_options = ["2", "1", "max"]
    _fps_labels = {"2": "2 fps (Standard)", "1": "1 fps", "max": "max (native fps)"}
    _fps_cur = str(st.session_state.get("video_ocr_full_target_fps", "2") or "2")
    if _fps_cur not in _fps_options:
        _fps_cur = "2"
    fps_mode = st.selectbox(
        "OCR Auflösung",
        options=_fps_options,
        index=_fps_options.index(_fps_cur),
        format_func=lambda v: _fps_labels.get(v, v),
        disabled=running or wd_ocr_active,
        key="video_ocr_full_target_fps",
    )

    can_run = bool(ocr_rois) and bool(capture_folder) and (full_video is not None) and not wd_ocr_active
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
        rois_snapshot = [dict(r) for r in list(st.session_state.get("rois") or []) if isinstance(r, dict)]
        capture_folder_snapshot = str(capture_folder or "").strip()
        full_video_snapshot = str(full_video) if full_video is not None else ""
        target_fps_snapshot = str(fps_mode or "2").strip() or "2"
        # Snapshot all session state needed by the background thread — session state
        # is not accessible from non-Streamlit threads, so capture here in the main thread.
        track_params_snapshot = {
            "moving_pt_color_range": dict(st.session_state.get("moving_pt_color_range") or {}),
            "ref_track_img": st.session_state.get("ref_track_img"),
            "minimap_pts": list(st.session_state.get("minimap_pts") or []),
            "ref_track_pts": list(st.session_state.get("ref_track_pts") or []),
            "centerline_px": (lambda _c: _c.tolist() if hasattr(_c, "tolist") else (list(_c) if _c is not None else []))(st.session_state.get("centerline_px")),
            "roi_global_scale": float(st.session_state.get("roi_global_scale", 1.2) or 1.2),
            "progress_step_frames": int(st.session_state.get("video_ocr_live_progress_step_frames", 2) or 2),
        }
        st.session_state.video_ocr_full_running = True
        st.session_state.roi_ocr_full_running = True
        st.session_state.video_ocr_full_stop_requested = False
        st.session_state.video_ocr_full_progress = {"done": 0, "total": 1, "t_s": 0.0}
        st.session_state.video_ocr_full_live_rows = []
        stop_event = threading.Event()
        set_status("Video OCR gestartet (Hintergrund).", "info")

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

            ok, msg, res = _run_video_ocr_fullvideo_framewise_now(
                progress_cb=_on_progress,
                stop_cb=_stop_cb,
                rois_override=rois_snapshot,
                capture_folder_override=capture_folder_snapshot,
                video_path_override=full_video_snapshot,
                target_fps_str=target_fps_snapshot,
                track_params_override=track_params_snapshot,
            )
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

    # ── Live section — wrapped in a fragment so only this part reruns ─────────
    # st.fragment(run_every=...) reruns only this block every N seconds,
    # without triggering a full-page rerun. Other tabs/dropdowns stay interactive.
    def _live_section():
        # Re-read all live state fresh on each fragment run.
        try:
            from app_tabs.youtube_tab import watchdog_snapshot as _wds
            _snap = _wds()
            _wd_run = bool(_snap.get("running"))
            _wd_cur = str(_snap.get("current") or "")
            _wd_ocr = bool(_wd_run and "OCR" in _wd_cur)
        except Exception:
            _snap = {}
            _wd_ocr = False

        _manual = _is_running()
        _prog = dict(st.session_state.get("video_ocr_full_progress") or {})
        _done = int(_prog.get("done", 0) or 0)
        _total = int(max(1, int(_prog.get("total", 1) or 1)))
        _t_s = float(_prog.get("t_s", 0.0) or 0.0)
        _rows = list(st.session_state.get("video_ocr_full_live_rows") or [])

        if _wd_ocr:
            _live = dict(_snap.get("ocr_live") or {})
            if _live.get("active"):
                _done = int(_live.get("done", _done) or _done)
                _total = int(max(1, int(_live.get("total", _total) or _total)))
                _t_s = float(_live.get("t_s", _t_s) or _t_s)
                _wd_rows = list(_live.get("rows") or [])
                if _wd_rows:
                    _rows = _wd_rows

        st.progress(min(1.0, _done / _total), text=f"{_done}/{_total} Frames | t={_t_s:.2f}s")

        if _manual:
            st.info("Video OCR läuft im Hintergrund. Fortschritt wird live aktualisiert.", icon="⏳")

        st.caption("Live-Progress (OCR-Werte je Update):")
        if _rows:
            _df = pd.DataFrame(_rows)
        else:
            _df = pd.DataFrame(columns=["frame_idx", "time_s"])

        # Build _num: try to_numeric on every column; include only those where at
        # least one value converts successfully. This handles mixed string/empty columns
        # (OCR outputs are always strings; empty = failed OCR for that frame).
        _avail = list(_df.columns) if not _df.empty else []
        _num: list[str] = []
        if not _df.empty:
            for _col in _avail:
                try:
                    _conv = pd.to_numeric(_df[_col], errors="coerce")
                    if _conv.notna().any():
                        _df[_col] = _conv
                        _num.append(_col)
                except Exception:
                    pass

        st.dataframe(_df, use_container_width=True, hide_index=True, height=260 if _rows else 120)

        # ── Live-Scope Diagramme ──────────────────────────────────────────────
        st.markdown("#### Live-Diagramme")

        _has_geo = (
            not _df.empty
            and "track_xy_x" in _df.columns
            and "track_xy_y" in _df.columns
        )
        _plot_type_labels = {"line": "Linie", "scatter": "Punkte", "geoplot": "Geoplot"}
        _plot_type_opts = ["line", "scatter"] + (["geoplot"] if _has_geo else [])

        _charts = st.session_state.ocr_scope_charts
        _to_remove = None

        for _ci, _chart in enumerate(_charts):
            with st.container(border=True):
                _hc1, _hc2 = st.columns([6, 1])
                _chart["title"] = _hc1.text_input(
                    "Titel", value=_chart.get("title", f"Diagramm {_ci+1}"),
                    key=f"ls_ctitle_{_ci}", label_visibility="collapsed",
                )
                if _hc2.button("✕", key=f"ls_rm_{_ci}", help="Diagramm entfernen"):
                    _to_remove = _ci

                _cur_type = _chart.get("plot_type", "line")
                if _cur_type not in _plot_type_opts:
                    _cur_type = _plot_type_opts[0]

                if _cur_type == "geoplot":
                    # type selector spans full row for geoplot
                    _chart["plot_type"] = st.selectbox(
                        "Art",
                        options=_plot_type_opts,
                        index=_plot_type_opts.index(_cur_type),
                        format_func=_plot_type_labels.get,
                        key=f"ls_ctype_{_ci}",
                        label_visibility="collapsed",
                    )
                else:
                    _cc1, _cc2, _cc3 = st.columns([2, 2, 3])
                    _chart["plot_type"] = _cc1.selectbox(
                        "Art",
                        options=_plot_type_opts,
                        index=_plot_type_opts.index(_cur_type),
                        format_func=_plot_type_labels.get,
                        key=f"ls_ctype_{_ci}",
                        label_visibility="collapsed",
                    )
                    _x_opts = _num or _avail
                    _x_def = _chart.get("x_col", "time_s")
                    _x_idx = _x_opts.index(_x_def) if _x_def in _x_opts else 0
                    _chart["x_col"] = _cc2.selectbox(
                        "X-Achse", options=_x_opts, index=_x_idx,
                        key=f"ls_cx_{_ci}",
                    )
                    _y_opts = [c for c in _num if c != _chart["x_col"]]
                    _y_cur = [c for c in (_chart.get("y_cols") or []) if c in _y_opts]
                    _chart["y_cols"] = _cc3.multiselect(
                        "Y-Achse", options=_y_opts, default=_y_cur,
                        key=f"ls_cy_{_ci}",
                    )

                # ── Render ────────────────────────────────────────────────────
                _ptype = _chart.get("plot_type", "line")
                if _ptype == "geoplot":
                    if _has_geo:
                        try:
                            from app_tabs.track_geoplot import transform_centerline, make_geoplot_figure
                            _xs = _df["track_xy_x"].tolist()
                            _ys = _df["track_xy_y"].tolist()
                            _ts = _df["time_s"].tolist() if "time_s" in _df.columns else None
                            _cl_xy = None
                            _cl_px = st.session_state.get("centerline_px")
                            _mini = st.session_state.get("minimap_pts")
                            _ref = st.session_state.get("ref_track_pts")
                            if _cl_px is not None and _mini and _ref:
                                _cl_px_l = _cl_px.tolist() if hasattr(_cl_px, "tolist") else list(_cl_px)
                                _cl_xy = transform_centerline(_cl_px_l, _mini, _ref)
                            st.plotly_chart(
                                make_geoplot_figure(
                                    [{"name": "Fahrzeug", "xs": _xs, "ys": _ys, "ts": _ts}],
                                    centerline_xy=_cl_xy,
                                ),
                                use_container_width=True,
                            )
                        except Exception as _ge:
                            st.caption(f"Geoplot-Fehler: {_ge}")
                    else:
                        st.caption("track_xy_x/y nicht in den aktuellen Daten vorhanden.")
                else:
                    _y_cols = _chart.get("y_cols") or []
                    if _y_cols and not _df.empty:
                        try:
                            import plotly.graph_objects as go
                            _mode = "lines" if _ptype == "line" else "markers"
                            _fig = go.Figure()
                            for _yc in _y_cols:
                                if _yc in _df.columns:
                                    _fig.add_trace(go.Scatter(
                                        x=_df[_chart["x_col"]], y=_df[_yc],
                                        mode=_mode, name=_yc,
                                        marker=dict(size=4) if _mode == "markers" else {},
                                    ))
                            _fig.update_layout(
                                title=_chart.get("title", ""),
                                margin=dict(l=40, r=20, t=30, b=40), height=300,
                                xaxis_title=_chart["x_col"], yaxis_title="Wert",
                                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                                template="plotly_dark",
                            )
                            st.plotly_chart(_fig, use_container_width=True)
                        except Exception as _pe:
                            st.caption(f"Diagramm-Fehler: {_pe}")
                    elif not _y_cols:
                        st.caption("Y-Achse auswählen.")
                    else:
                        st.caption("Warte auf Daten ...")

        if _to_remove is not None:
            _charts.pop(_to_remove)
            st.rerun()

        if st.button("+ Diagramm hinzufügen", key="ls_add_chart"):
            _charts.append({
                "title": f"Diagramm {len(_charts) + 1}",
                "x_col": "time_s",
                "y_cols": [],
                "plot_type": "line",
            })
            st.rerun()

        _last = st.session_state.get("video_ocr_full_result") or {}
        if isinstance(_last, dict) and _last:
            if bool(_last.get("ok")):
                st.caption(
                    f"Zuletzt: rows={int(_last.get('rows', 0) or 0)} | "
                    f"frames={int(_last.get('frames_processed', 0) or 0)}"
                    f"/{int(_last.get('frames_total', 0) or 0)} | "
                    f"json={str(_last.get('json_key', '') or '-')}"
                )
            else:
                st.caption(f"Letzter Lauf fehlgeschlagen: {str(_last.get('error', ''))}")

    # Use st.fragment with run_every so only this block auto-refreshes.
    # Falls back to a plain call (+ full rerun) on older Streamlit versions.
    try:
        _frag_fn = st.fragment(_live_section, run_every=0.5)
        _frag_fn()
    except Exception:
        _live_section()
        if _is_running() or wd_ocr_running:
            time.sleep(0.25)
            st.rerun()
