"""Watchdog dashboard and controls (separate tab)."""


def render(ns):
    globals().update(ns)
    from app_tabs import youtube_tab as _yt

    st.markdown('<div class="section-title">Watchdog Dashboard</div>', unsafe_allow_html=True)
    st.caption("Watchdog-Agent im Hintergrund: MAT->JSON, YouTube-Download und OCR (pro Task auswählbar).")

    from core.watchdog_state import _YT_WATCHDOG, _YT_WATCHDOG_LOCK

    snap = _yt.watchdog_snapshot()
    is_running = bool(snap.get("running"))
    interval_sec = int(snap.get("interval_sec", 10) or 10)

    # ── Aktive Aufgaben — immer editierbar, wirken beim nächsten Tick ─────────
    st.markdown("**Aktive Aufgaben**")
    st.caption("Änderungen werden beim nächsten Tick übernommen, ohne die laufende Aufgabe zu unterbrechen.")
    t1, t2 = st.columns(2)
    task_mat_json = t1.checkbox(
        "Konvertierung MAT → JSON",
        value=bool(st.session_state.get("yt_watchdog_task_mat_json", False)),
        key="wd_task_mat_json_cb",
    )
    task_download = t2.checkbox(
        "YouTube Download",
        value=bool(st.session_state.get("yt_watchdog_task_download", False)),
        key="wd_task_download_cb",
    )
    task_ocr = st.checkbox(
        "OCR Auswertung",
        value=bool(st.session_state.get("yt_watchdog_task_ocr", True)),
        key="wd_task_ocr_cb",
    )
    task_reclean = st.checkbox(
        "Nachfiltern (Plausibilität + Steigung auf cleaned anwenden)",
        value=bool(st.session_state.get("yt_watchdog_task_reclean", False)),
        key="wd_task_reclean_cb",
        help="Wendet Min/Max und Max-Steigung aus dem ROI-Katalog auf alle result-JSONs an. "
             "Jede Datei wird pro Watchdog-Session einmal verarbeitet.",
    )
    task_retrofix = st.checkbox(
        "Nachkorrektur (Zeitgrenzen trimmen + Plausibilität + Track-Minimap neu berechnen)",
        value=bool(st.session_state.get("yt_watchdog_task_retrofix", False)),
        key="wd_task_retrofix_cb",
        help="Kombinierte Nachkorrektur pro Datei: "
             "(1) Zeilen außerhalb start_s/end_s löschen, "
             "(2) Min/Max + Steigung filtern, "
             "(3) track_minimap neu auswerten wenn track_minimap_found überall 0 war "
             "(behebt den list-vs-dict Bug).",
    )

    # Persist to session state and push live to the running watchdog thread.
    st.session_state.yt_watchdog_task_mat_json = task_mat_json
    st.session_state.yt_watchdog_task_download = task_download
    st.session_state.yt_watchdog_task_ocr = task_ocr
    st.session_state.yt_watchdog_task_reclean = task_reclean
    st.session_state.yt_watchdog_task_retrofix = task_retrofix
    if is_running:
        _new_tasks = {
            "mat_json": task_mat_json,
            "download": task_download,
            "ocr": task_ocr,
            "reclean": task_reclean,
            "retrofix": task_retrofix,
        }
        with _YT_WATCHDOG_LOCK:
            if _YT_WATCHDOG.get("tasks") != _new_tasks:
                _YT_WATCHDOG["tasks"] = _new_tasks

    # ── Start / Stop form ─────────────────────────────────────────────────────
    with st.form("watchdog_config_form", border=False):
        _ocr_fps_options = ["2", "1", "max"]
        _ocr_fps_labels = {"2": "2 fps (Standard)", "1": "1 fps", "max": "max (native fps)"}
        _ocr_fps_cur = str(st.session_state.get("yt_watchdog_ocr_fps", "2") or "2")
        if _ocr_fps_cur not in _ocr_fps_options:
            _ocr_fps_cur = "2"
        ocr_fps = st.selectbox(
            "OCR Auflösung",
            options=_ocr_fps_options,
            index=_ocr_fps_options.index(_ocr_fps_cur),
            format_func=lambda v: _ocr_fps_labels.get(v, v),
            disabled=is_running,
        )

        w1, w2, w3 = st.columns([2, 2, 2])
        wd_interval = int(w1.number_input(
            "Watchdog-Intervall (Sek.)",
            min_value=2,
            max_value=300,
            value=interval_sec,
            step=1,
            disabled=is_running,
        ))
        start_clicked = w2.form_submit_button(
            "Watchdog starten",
            type="primary",
            use_container_width=True,
            disabled=is_running or bool(st.session_state.get("yt_bg_active")),
        )
        stop_clicked = w3.form_submit_button(
            "Watchdog stoppen",
            use_container_width=True,
            disabled=not is_running,
        )

    if start_clicked:
        st.session_state.yt_watchdog_ocr_fps = str(ocr_fps)
        st.session_state.yt_watchdog_interval_sec_cmd = int(wd_interval)
        st.session_state.yt_watchdog_cmd = "start"
        st.rerun()
    if stop_clicked:
        st.session_state.yt_watchdog_cmd = "stop"
        st.rerun()

    # Status line
    _lamp_color = "#22c55e" if is_running else "#ef4444"
    _lamp = f'<span style="display:inline-block;width:12px;height:12px;border-radius:50%;background:{_lamp_color};margin-right:6px;vertical-align:middle;"></span>'
    wd_state = "aktiv" if is_running else "inaktiv"
    st.markdown(
        f'{_lamp}<span style="font-size:0.85em;color:#aaa;">'
        f"Watchdog: <b>{wd_state}</b> | MAT->JSON={int(snap.get('mat_json', 0))} | "
        f"Downloads={int(snap.get('downloads', 0))} | "
        f"OCR={int(snap.get('ocr', 0))} | Fehler={int(snap.get('errors', 0))}"
        f"</span>",
        unsafe_allow_html=True,
    )

    # Log (JS polling, zero Streamlit rerun)
    try:
        lp = str(st.session_state.get("local_base_path") or "").strip()
        log_file = (Path(lp).expanduser().resolve() / "logs" / "watchdog.log") if lp else None
    except Exception:
        log_file = None

    if log_file and log_file.exists():
        st.caption(f"Vollständiger Log: {log_file}")

    # Get the port of the existing cached HTTP server
    try:
        _als = globals().get("_audio_live_server")
        srv_port = int(_als()["port"]) if callable(_als) else 0
    except Exception:
        srv_port = 0

    if srv_port:
        poll_ms = 2000  # always 2s regardless of interval_sec so the log stays live
        html = f"""
<style>
  #wd-log {{
    background:#0e1117; color:#fafafa; font-family:monospace; font-size:12px;
    padding:10px 12px; border-radius:6px; white-space:pre-wrap;
    min-height:40px; max-height:300px; overflow-y:auto;
    border:1px solid #333;
  }}
  #wd-log .wd-cur-line {{ color:#facc15; }}
</style>
<div id="wd-log">Lade...</div>
<script>
(function() {{
  var seen = 0;
  var lastCur = '';
  var el = document.getElementById('wd-log');
  function render(logs, cur) {{
    var text = logs.join('\\n') || '(keine Einträge)';
    el.innerHTML = '';
    var pre = document.createTextNode(text);
    el.appendChild(pre);
    if (cur) {{
      var line = document.createElement('span');
      line.className = 'wd-cur-line';
      line.textContent = '\\n▶ ' + cur;
      el.appendChild(line);
    }}
    el.scrollTop = el.scrollHeight;
  }}
  function poll() {{
    fetch('http://127.0.0.1:{srv_port}/watchdog-log')
      .then(function(r){{ return r.json(); }})
      .then(function(d) {{
        var logs = d.logs || [];
        var cur = d.current || '';
        if (logs.length !== seen || cur !== lastCur) {{
          render(logs, cur);
          seen = logs.length;
          lastCur = cur;
        }}
      }})
      .catch(function(){{ }});
  }}
  poll();
  setInterval(poll, {poll_ms});
}})();
</script>
"""
        st.markdown("**Watchdog-Log (letzte 15 Einträge)**")
        components.html(html, height=320, scrolling=False)
    else:
        # Fallback: static display
        wd_logs = list(snap.get("logs") or [])
        wd_cur = str(snap.get("current") or "").strip()
        lines = wd_logs[-15:] if wd_logs else []
        if wd_cur:
            lines = lines + [f"▶ {wd_cur}"]
        with st.expander("Watchdog-Log (letzte 15 Einträge)", expanded=True):
            st.code("\n".join(lines) if lines else "(keine Einträge)", language="text")
