"""Cloud Connection & Root tab — local DB only."""


def render(ns):
    globals().update(ns)

    st.markdown('<div class="section-title">Verbindung & Pfad</div>', unsafe_allow_html=True)

    with st.expander("Debug-Logs", expanded=False):
        st.caption(f"Crash-Log Datei: {LOG_FILE}")
        if LOG_FILE.exists():
            try:
                log_text = LOG_FILE.read_text(encoding="utf-8", errors="ignore")
            except Exception as e:
                log_text = f"Log konnte nicht gelesen werden: {e}"
            st.code(log_text[-12000:] if log_text else "(leer)", language="text")
            c_log1, c_log2 = st.columns(2)
            c_log1.download_button(
                "Log herunterladen",
                data=log_text.encode("utf-8", errors="ignore"),
                file_name="app_crash.log",
                mime="text/plain",
                width="stretch",
            )
            if c_log2.button("Log leeren", width="stretch"):
                try:
                    LOG_FILE.write_text("", encoding="utf-8")
                    set_status("Crash-Log geleert.", "info")
                    st.rerun()
                except Exception as e:
                    set_status(f"Log konnte nicht geleert werden: {e}", "warn")
        else:
            st.info("Noch kein Crash-Log vorhanden.")

    local_ok = bool(st.session_state.local_connected)

    st.markdown('<div class="section-card" style="background:#132114;border-color:#305b34;">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Lokale DB</div>', unsafe_allow_html=True)

    st.markdown(
        f"""
        <div style="background:#132114;border:1px solid #376a3d;border-radius:10px;padding:.8rem 1rem;margin-bottom:.7rem;">
          <div style="font-family:'JetBrains Mono',monospace;font-size:.66rem;color:#9fbe9f;text-transform:uppercase;letter-spacing:.08em;">Status</div>
          <div style="display:flex;align-items:center;gap:10px;margin-top:6px;">
            <span class="conn-dot {'ok' if local_ok else 'off'}" style="width:13px;height:13px;"></span>
            <span style="font-family:'Syne',sans-serif;font-size:1.03rem;font-weight:700;color:{'#3ddc84' if local_ok else '#ff5c5c'};">
              {'Verbunden' if local_ok else 'Nicht verbunden'}
            </span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.container(border=True):
        st.markdown(
            "<div style=\"font-family:JetBrains Mono,monospace;font-size:.66rem;color:#9fbe9f;"
            "text-transform:uppercase;letter-spacing:.08em;margin-bottom:.45rem;\">Lokaler Zugriff</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            """
            <div style="background:#17301a;border:1px solid #2b5a31;border-radius:8px;padding:.55rem .7rem;
                 font-family:'JetBrains Mono',monospace;font-size:.68rem;color:#b8ddb9;line-height:1.5;margin-bottom:.6rem;">
            Hinweis: Nur auf localhost nutzbar. Der gewaehlte Ordner muss einen Unterordner <b>captures</b> enthalten.
            </div>
            """,
            unsafe_allow_html=True,
        )

        if st.button("Ordner waehlen (lokal)", width="stretch", key="local_pick_btn"):
            try:
                ok_pick, picked = _pick_local_folder_dialog(st.session_state.local_base_path_input)
                if ok_pick and picked:
                    st.session_state.local_base_path_input = picked
                    lp = Path(picked).expanduser().resolve()
                    captures_dir = lp / "captures"
                    if captures_dir.exists() and captures_dir.is_dir():
                        local_client = LocalStorageAdapter(str(lp))
                        ok_local, msg_local = local_client.test_connection()
                        if ok_local:
                            st.session_state.local_connected = True
                            st.session_state.local_client = local_client
                            st.session_state.local_base_path = str(lp)
                            st.session_state.local_root = ""
                            set_status(f"Lokale DB verbunden: {lp}", "ok")
                        else:
                            st.session_state.local_connected = False
                            st.session_state.local_client = None
                            set_status(f"Lokale DB Verbindung fehlgeschlagen: {msg_local}", "warn")
                    else:
                        st.session_state.local_connected = False
                        st.session_state.local_client = None
                        set_status("Lokale DB nicht verbunden: Unterordner 'captures' fehlt.", "warn")
                    st.rerun()
                elif picked:
                    set_status(f"Ordnerdialog nicht verfuegbar: {picked}", "warn")
            except Exception as e:
                set_status(f"Lokale DB Verbindung fehlgeschlagen: {e}", "warn")

        st.markdown(
            f'<div class="breadcrumb">Lokaler Basispfad: '
            f'{st.session_state.local_base_path if st.session_state.local_connected else "(noch nicht gesetzt)"}'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.markdown('</div>', unsafe_allow_html=True)
