"""Renderer for local MAT-to-JSON conversion in <local_base_path>/results."""


def render(ns):
    globals().update(ns)
    st.markdown('<div class="section-title">MAT zu JSON Konvertierung</div>', unsafe_allow_html=True)

    def _results_dir_from_local_db() -> Path | None:
        lp = str(st.session_state.get("local_base_path") or "").strip()
        if not lp:
            return None
        try:
            return (Path(lp).expanduser().resolve() / "results").resolve()
        except Exception:
            return None

    def _fallback_recordresult_json_bytes(raw: bytes) -> tuple[bool, bytes, str]:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mat")
        tmp.close()
        try:
            Path(tmp.name).write_bytes(raw)

            mat_to_plain = globals().get("_mat_struct_to_plain")
            norm = globals().get("_normalize_sidecar_json_payload")

            data = None
            robust_loader = globals().get("_loadmat_audio_save_robust")
            if callable(robust_loader):
                try:
                    data, _load_note = robust_loader(tmp.name)
                except Exception:
                    data = None
            if isinstance(data, dict) and data:
                rr_obj = data.get("recordResult")
                if rr_obj is None:
                    for k, v in data.items():
                        if str(k).lower() == "recordresult":
                            rr_obj = v
                            break
                if rr_obj is not None:
                    rr_plain = mat_to_plain(rr_obj) if callable(mat_to_plain) else rr_obj
                    if isinstance(rr_plain, dict) and rr_plain:
                        payload = {"recordResult": _mat_export_to_jsonable(rr_plain)}
                        if callable(norm):
                            payload = norm(payload)
                        out = json.dumps(payload, ensure_ascii=False, indent=2, default=lambda o: _mat_export_to_jsonable(o)).encode("utf-8")
                        return True, out, ""

            try:
                import h5py
                h5_decode = globals().get("_h5_decode_value")
                h5_get_ci = globals().get("_h5_get_path_ci")
                with h5py.File(tmp.name, "r") as f:
                    rr_node = h5_get_ci(f, ["recordResult"]) if callable(h5_get_ci) else (f["recordResult"] if "recordResult" in f else None)
                    if rr_node is not None:
                        rr_val = h5_decode(rr_node, f) if callable(h5_decode) else None
                        rr_plain = mat_to_plain(rr_val) if callable(mat_to_plain) else rr_val
                        if isinstance(rr_plain, dict) and rr_plain:
                            fix_roi = globals().get("_fix_roi_table_in_rr")
                            if callable(fix_roi):
                                fix_roi(rr_plain, tmp.name)
                            payload = {"recordResult": _mat_export_to_jsonable(rr_plain)}
                            if callable(norm):
                                payload = norm(payload)
                            out = json.dumps(payload, ensure_ascii=False, indent=2, default=lambda o: _mat_export_to_jsonable(o)).encode("utf-8")
                            return True, out, ""
            except Exception as e_h5:
                return False, b"", str(e_h5)
        except Exception as e:
            return False, b"", str(e)
        finally:
            try:
                Path(tmp.name).unlink(missing_ok=True)
            except Exception:
                pass
        return False, b"", "recordResult nicht lesbar"

    def _convert_mat_bytes(raw: bytes) -> tuple[bool, bytes, str]:
        if not raw:
            return False, b"", "leere MAT-Datei"
        try:
            helper = globals().get("_mat_bytes_to_recordresult_json_bytes")
            if callable(helper):
                out = helper(raw)
                if out:
                    return True, bytes(out), ""
            from core.save_helpers import rr_from_mat_bytes
            rr, _extra = rr_from_mat_bytes(raw)
            if not isinstance(rr, dict) or not rr:
                ok_fb, out_fb, msg_fb = _fallback_recordresult_json_bytes(raw)
                if ok_fb:
                    return True, out_fb, msg_fb
                return False, b"", str(msg_fb or "recordResult nicht lesbar")
            payload = {"recordResult": _mat_export_to_jsonable(rr)}
            norm = globals().get("_normalize_sidecar_json_payload")
            if callable(norm):
                payload = norm(payload)
            data = json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                default=lambda o: _mat_export_to_jsonable(o),
            ).encode("utf-8")
            return True, data, ""
        except Exception as e:
            return False, b"", str(e)

    def _scan_results_rows(results_dir: Path, status_map: dict) -> tuple[list[dict], list[Path]]:
        mat_files = sorted(results_dir.glob("*.mat"))
        rows: list[dict] = []
        pending: list[Path] = []
        for mat_path in mat_files:
            json_path = mat_path.with_suffix(".json")
            mat_exists = bool(mat_path.exists())
            json_exists = bool(json_path.exists())
            if json_exists:
                status = "bereits vorhanden"
            else:
                status = "ausstehend"
                pending.append(mat_path)
            prev = status_map.get(mat_path.name)
            if isinstance(prev, dict):
                prev_status = str(prev.get("status") or "").strip()
                if prev_status:
                    status = prev_status
            rows.append(
                {
                    "name der mat datei": mat_path.name,
                    "äquivalente json datei": json_path.name,
                    "mat datei vorhanden": "ja" if mat_exists else "nein",
                    "json datei vorhanden": "ja" if json_exists else "nein",
                    "konvertierungsstatus": status,
                }
            )
        return rows, pending

    st.session_state.setdefault("mat_to_json_status_map", {})
    status_map = dict(st.session_state.get("mat_to_json_status_map") or {})

    results_dir = _results_dir_from_local_db()
    if results_dir is None:
        st.warning("Lokale DB ist nicht gesetzt. Bitte zuerst im Tab 'Cloud Connection & Root' den lokalen Basispfad setzen.")
        return

    results_dir.mkdir(parents=True, exist_ok=True)
    st.caption(f"Verwendeter Ordner: {results_dir}")

    rows, pending = _scan_results_rows(results_dir, status_map)
    total = len(rows)
    pending_n = len(pending)

    if total > 0:
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True, height=380)
    else:
        st.dataframe(
            pd.DataFrame(
                columns=[
                    "name der mat datei",
                    "äquivalente json datei",
                    "mat datei vorhanden",
                    "json datei vorhanden",
                    "konvertierungsstatus",
                ]
            ),
            width="stretch",
            hide_index=True,
            height=220,
        )

    st.caption(f"MAT-Dateien: {total} | ohne JSON: {pending_n}")
    progress_slot = st.empty()
    current_slot = st.empty()
    convert_clicked = st.button(
        "alle .mat dateien ohne .json in .json konvertieren",
        type="primary",
        width="stretch",
        key="mat_to_json_convert_all_missing_btn",
        disabled=(pending_n <= 0),
    )

    if convert_clicked and pending_n > 0:
        ok_n = 0
        err_n = 0
        for i, mat_path in enumerate(pending, start=1):
            mat_name = mat_path.name
            json_path = mat_path.with_suffix(".json")
            current_slot.caption(f"Aktuell: {json_path.name} ({i}/{pending_n})")
            try:
                raw = mat_path.read_bytes()
                ok, json_bytes, err = _convert_mat_bytes(raw)
                if ok:
                    json_path.write_bytes(json_bytes)
                    status_map[mat_name] = {"status": "konvertiert", "error": ""}
                    ok_n += 1
                else:
                    status_map[mat_name] = {"status": f"fehler: {err}", "error": str(err or "")}
                    err_n += 1
            except Exception as e:
                status_map[mat_name] = {"status": f"fehler: {e}", "error": str(e)}
                err_n += 1
            remain = max(0, pending_n - i)
            progress_slot.progress(
                i / max(1, pending_n),
                text=f"{i}/{pending_n} konvertiert | verbleibend: {remain}",
            )

        st.session_state.mat_to_json_status_map = status_map
        if err_n == 0:
            set_status(f"MAT->JSON abgeschlossen: {ok_n}/{pending_n} konvertiert.", "ok")
        else:
            set_status(f"MAT->JSON abgeschlossen: {ok_n} OK, {err_n} Fehler.", "warn")
        st.rerun()
