"""Watchdog dashboard and controls (separate tab)."""


def render(ns):
    globals().update(ns)
    from app_tabs import youtube_tab as _yt

    st.markdown('<div class="section-title">Watchdog Dashboard</div>', unsafe_allow_html=True)
    st.caption("Watchdog-Agent im Hintergrund: MAT->JSON, YouTube-Download, Sync Full/Lite und OCR (pro Task auswählbar).")

    snap = _yt.watchdog_snapshot()
    tasks_snap = dict(snap.get("tasks") or {})
    st.session_state.setdefault("yt_watchdog_task_mat_json", bool(tasks_snap.get("mat_json", True)))
    st.session_state.setdefault("yt_watchdog_task_download", bool(tasks_snap.get("download", True)))
    st.session_state.setdefault("yt_watchdog_task_sync_lite", bool(tasks_snap.get("sync_lite", True)))
    st.session_state.setdefault("yt_watchdog_task_ocr", bool(tasks_snap.get("ocr", True)))

    st.markdown("**Aktive Aufgaben**")
    t1, t2 = st.columns(2)
    task_mat_json = bool(
        t1.checkbox(
            "Konvertierung MAT -> JSON",
            value=bool(st.session_state.get("yt_watchdog_task_mat_json", True)),
            key="watchdog_task_mat_json",
            disabled=bool(snap.get("running")),
        )
    )
    task_download = bool(
        t2.checkbox(
            "YouTube Download",
            value=bool(st.session_state.get("yt_watchdog_task_download", True)),
            key="watchdog_task_download",
            disabled=bool(snap.get("running")),
        )
    )
    t3, t4 = st.columns(2)
    task_sync = bool(
        t3.checkbox(
            "Sync Voll <-> Lite",
            value=bool(st.session_state.get("yt_watchdog_task_sync_lite", True)),
            key="watchdog_task_sync",
            disabled=bool(snap.get("running")),
        )
    )
    task_ocr = bool(
        t4.checkbox(
            "OCR Auswertung",
            value=bool(st.session_state.get("yt_watchdog_task_ocr", True)),
            key="watchdog_task_ocr",
            disabled=bool(snap.get("running")),
        )
    )

    w1, w2, w3 = st.columns([2, 2, 2])
    wd_interval = int(
        w1.number_input(
            "Watchdog-Intervall (Sek.)",
            min_value=2,
            max_value=300,
            value=int(snap.get("interval_sec", 20) or 20),
            step=1,
            key="watchdog_tab_interval_sec",
            disabled=bool(snap.get("running")),
        )
    )
    start_clicked = w2.button(
        "Watchdog starten",
        width="stretch",
        key="watchdog_tab_start_btn",
        disabled=bool(snap.get("running")) or bool(st.session_state.get("yt_bg_active")),
    )
    stop_clicked = w3.button(
        "Watchdog stoppen",
        width="stretch",
        key="watchdog_tab_stop_btn",
        disabled=not bool(snap.get("running")),
    )

    if start_clicked:
        st.session_state.yt_watchdog_task_mat_json = bool(task_mat_json)
        st.session_state.yt_watchdog_task_download = bool(task_download)
        st.session_state.yt_watchdog_task_sync_lite = bool(task_sync)
        st.session_state.yt_watchdog_task_ocr = bool(task_ocr)
        st.session_state.yt_watchdog_interval_sec_cmd = int(wd_interval)
        st.session_state.yt_watchdog_cmd = "start"
        st.rerun()
    if stop_clicked:
        st.session_state.yt_watchdog_cmd = "stop"
        st.rerun()

    # Only the live status/log section auto-refreshes
    fragment_fn = getattr(st, "fragment", None) or getattr(st, "experimental_fragment", None)
    is_running = bool(_yt.watchdog_snapshot().get("running"))
    run_every = 1.0 if is_running else None

    def _render_status():
        snap2 = _yt.watchdog_snapshot()
        wd_state = "aktiv" if bool(snap2.get("running")) else "inaktiv"
        st.caption(
            f"Watchdog: {wd_state} | MAT->JSON={int(snap2.get('mat_json', 0))} | Downloads={int(snap2.get('downloads', 0))} | "
            f"Sync/Lite={int(snap2.get('sync_lite', snap2.get('lite', 0)))} | OCR={int(snap2.get('ocr', 0))} | "
            f"Fehler={int(snap2.get('errors', 0))}"
        )
        wd_cur = str(snap2.get("current") or "").strip()
        wd_last = str(snap2.get("last_tick") or "").strip()
        if wd_cur:
            st.caption(f"Aktueller Schritt: {wd_cur}")
        if wd_last:
            st.caption(f"Letzter Tick: {wd_last}")

        with st.expander("Watchdog-Log", expanded=False):
            wd_logs = list(snap2.get("logs") or [])
            if wd_logs:
                st.code("\n".join(wd_logs[-80:]), language="text")
            else:
                st.caption("Noch keine Einträge.")

    if callable(fragment_fn):
        @fragment_fn(run_every=run_every)
        def _status_fragment():
            _render_status()
        _status_fragment()
    else:
        _render_status()
        if is_running:
            time.sleep(1.0)
            st.rerun()
