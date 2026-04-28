"""Renderer for the Streamlit tab extracted from app.py.

The renderer receives app.py globals so existing helper functions and
session-state conventions remain shared during the incremental split.
"""

def render(ns):
    globals().update(ns)
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

    cloud_ok = bool(st.session_state.r2_connected)
    local_ok = bool(st.session_state.local_connected)

    col_cloud, col_local = st.columns(2, gap="large")

    with col_cloud:
        st.markdown('<div class="section-card" style="background:#0b1524;border-color:#234465;">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">Cloud DB | Cloudflare R2</div>', unsafe_allow_html=True)
        # Card 1: Status
        st.markdown(
            f"""
            <div style="background:#0b1524;border:1px solid #2b4f77;border-radius:10px;padding:.8rem 1rem;margin-bottom:.7rem;">
              <div style="font-family:'JetBrains Mono',monospace;font-size:.66rem;color:#8aa8c7;text-transform:uppercase;letter-spacing:.08em;">Cloud DB Status</div>
              <div style="display:flex;align-items:center;gap:10px;margin-top:6px;">
                <span class="conn-dot {'ok' if cloud_ok else 'off'}" style="width:13px;height:13px;"></span>
                <span style="font-family:'Syne',sans-serif;font-size:1.03rem;font-weight:700;color:{'#3ddc84' if cloud_ok else '#ff5c5c'};">
                  {'Verbunden' if cloud_ok else 'Nicht verbunden'}
                </span>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # Card 2: Credentials + connect
        with st.container(border=True, key="cloud_access_card"):
            st.markdown(
                "<div style=\"font-family:JetBrains Mono,monospace;font-size:.66rem;color:#8aa8c7;text-transform:uppercase;letter-spacing:.08em;margin-bottom:.45rem;\">Cloud Zugang</div>",
                unsafe_allow_html=True,
            )
            r2_account = st.text_input(
                "Account ID",
                key="r2_account_id",
                help="Cloudflare Dashboard -> R2 -> Account ID",
            )
            r2_key = st.text_input(
                "Access Key ID",
                key="r2_access_key_id",
                help="R2 -> Manage API Tokens -> Create API Token",
            )
            r2_secret = st.text_input(
                "Secret Access Key",
                key="r2_secret_access_key",
                type="password",
            )
            r2_bucket = st.text_input(
                "Bucket Name",
                key="r2_bucket",
                placeholder="mein-bucket",
            )

            try:
                r2_connect_clicked = st.button("Cloud DB verbinden", type="primary", width="stretch", key="r2_connect_btn")
            except Exception as e:
                if "can't be used in an `st.form()`" not in str(e):
                    raise
                r2_connect_clicked = st.form_submit_button("Cloud DB verbinden", type="primary", width="stretch")

            if r2_connect_clicked:
                if r2_account and r2_key and r2_secret and r2_bucket:
                    with st.spinner("Verbinde Cloud DB ..."):
                        _ok, _msg, _client = connect_r2_client(r2_account, r2_key, r2_secret, r2_bucket)
                    if _ok:
                        st.session_state.r2_connected = True
                        st.session_state.r2_client = _client
                        st.session_state.r2_prefix_options = list_root_prefixes(_client)
                        st.session_state.r2_prefix = ""
                        st.session_state.mat_scan_prefix = None
                        set_status("Cloud DB verbunden.", "ok")
                    else:
                        st.session_state.r2_connected = False
                        set_status(f"Cloud DB Verbindung fehlgeschlagen: {_msg}", "warn")
                    st.rerun()
                else:
                    set_status("Bitte alle Cloud-DB Felder ausfuellen.", "warn")
                    st.rerun()

        # Card 3: Root + refresh
        with st.container(border=True, key="cloud_root_card"):
            st.markdown(
                "<div style=\"font-family:JetBrains Mono,monospace;font-size:.66rem;color:#8aa8c7;text-transform:uppercase;letter-spacing:.08em;margin-bottom:.45rem;\">Cloud Root</div>",
                unsafe_allow_html=True,
            )
            if st.session_state.r2_connected:
                opts = st.session_state.r2_prefix_options or [""]
                cur = st.session_state.r2_prefix
                idx = opts.index(cur) if cur in opts else 0
                chosen = st.selectbox(
                    "Cloud Prefix",
                    opts,
                    index=idx,
                    format_func=lambda x: x or "(Bucket-Root)",
                    label_visibility="collapsed",
                    key="root_dd",
                )
                if chosen != st.session_state.r2_prefix:
                    st.session_state.r2_prefix = chosen
                    st.session_state.mat_scan_prefix = None
                    set_status(f"Cloud Root: {chosen or '(root)'}", "ok")
                if st.button("Cloud Liste aktualisieren", width="stretch", key="refresh_root"):
                    st.session_state.r2_prefix_options = get_root_prefixes()
                    st.rerun()
            else:
                st.caption("Erst Cloud DB verbinden.")
        st.markdown('</div>', unsafe_allow_html=True)

    with col_local:
        st.markdown('<div class="section-card" style="background:#132114;border-color:#305b34;">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">Lokale DB</div>', unsafe_allow_html=True)
        # Card 1: Status
        st.markdown(
            f"""
            <div style="background:#132114;border:1px solid #376a3d;border-radius:10px;padding:.8rem 1rem;margin-bottom:.7rem;">
              <div style="font-family:'JetBrains Mono',monospace;font-size:.66rem;color:#9fbe9f;text-transform:uppercase;letter-spacing:.08em;">Lokale DB Status</div>
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
        # Card 2: Notice + picker + path
        with st.container(border=True, key="local_access_card"):
            st.markdown(
                "<div style=\"font-family:JetBrains Mono,monospace;font-size:.66rem;color:#9fbe9f;text-transform:uppercase;letter-spacing:.08em;margin-bottom:.45rem;\">Lokaler Zugriff</div>",
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
                f'<div class="breadcrumb">Lokaler Basispfad: {st.session_state.local_base_path if st.session_state.local_connected else "(noch nicht gesetzt)"}</div>',
                unsafe_allow_html=True,
            )


        st.markdown('</div>', unsafe_allow_html=True)


