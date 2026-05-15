"""Watchdog dashboard and controls (separate tab)."""


def render(ns):
    globals().update(ns)
    from app_tabs import youtube_tab as _yt

    st.markdown('<div class="section-title">Watchdog Dashboard</div>', unsafe_allow_html=True)
    st.caption("Automatisiert Download, Lite-Erstellung und OCR für YouTube-Captures.")

    snap = _yt.watchdog_snapshot()
    w1, w2, w3 = st.columns([2, 2, 2])
    wd_interval = int(
        w1.number_input(
            "Watchdog-Intervall (Sek.)",
            min_value=2,
            max_value=300,
            value=int(snap.get("interval_sec", 20) or 20),
            step=1,
            key="watchdog_tab_interval_sec",
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
        st.session_state.yt_watchdog_interval_sec_cmd = int(wd_interval)
        st.session_state.yt_watchdog_cmd = "start"
        st.rerun()
    if stop_clicked:
        st.session_state.yt_watchdog_cmd = "stop"
        st.rerun()

    snap = _yt.watchdog_snapshot()
    wd_state = "aktiv" if bool(snap.get("running")) else "inaktiv"
    st.caption(
        f"Watchdog: {wd_state} | Downloads={int(snap.get('downloads', 0))} | "
        f"Lite={int(snap.get('lite', 0))} | OCR={int(snap.get('ocr', 0))} | "
        f"Fehler={int(snap.get('errors', 0))}"
    )
    wd_cur = str(snap.get("current") or "").strip()
    wd_last = str(snap.get("last_tick") or "").strip()
    if wd_cur:
        st.caption(f"Aktueller Schritt: {wd_cur}")
    if wd_last:
        st.caption(f"Letzter Tick: {wd_last}")

    with st.expander("Watchdog-Log", expanded=False):
        wd_logs = list(snap.get("logs") or [])
        if wd_logs:
            st.code("\n".join(wd_logs[-80:]), language="text")
        else:
            st.caption("Noch keine Einträge.")

    if bool(snap.get("running")):
        time.sleep(0.4)
        st.rerun()
