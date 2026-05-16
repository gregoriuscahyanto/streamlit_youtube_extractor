"""Renderer for local MAT-to-JSON conversion in <local_base_path>/results."""

import threading as _threading
from core.watchdog_state import get_path_lock

_CONV_LOCK = _threading.Lock()
_CONV: dict = {
    "running": False,
    "done_n": 0,
    "total_n": 0,
    "ok_n": 0,
    "err_n": 0,
    "current": "",
    "next_file": "",
    "stop_requested": False,
    "status_map": {},
    "thread": None,
}


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
            _load_err = ""
            robust_loader = globals().get("_loadmat_audio_save_robust")
            if callable(robust_loader):
                try:
                    data, _load_note = robust_loader(tmp.name)
                    if data is None:
                        _load_err = str(_load_note or "")
                except Exception as _e_rob:
                    data = None
                    _load_err = str(_e_rob)
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

            _HDF5_MAGIC = b"\x89HDF\r\n\x1a\n"
            if raw[:8] == _HDF5_MAGIC:
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
        if _load_err:
            return False, b"", _load_err
        return False, b"", "recordResult nicht lesbar"

    def _json_recordresult_ocr_lengths(json_bytes: bytes) -> dict:
        try:
            d = json.loads((json_bytes or b"").decode("utf-8", errors="ignore"))
            o = ((d.get("recordResult") or {}).get("ocr") or {}) if isinstance(d, dict) else {}
            def _row_count(v):
                if isinstance(v, list):
                    return len(v)
                if isinstance(v, dict):
                    lens = [len(x) for x in v.values() if isinstance(x, list)]
                    return max(lens) if lens else -1
                return -1
            out = {}
            for k in ("roi_table", "table", "cleaned"):
                v = o.get(k)
                out[k] = _row_count(v)
            return out
        except Exception:
            return {"roi_table": -1, "table": -1, "cleaned": -1}

    def _json_recordresult_ocr_lengths_from_path(json_path: Path) -> dict:
        try:
            return _json_recordresult_ocr_lengths(json_path.read_bytes())
        except Exception:
            return {"roi_table": -1, "table": -1, "cleaned": -1}

    def _json_has_row_table_lists(json_path: Path) -> bool:
        def _walk(v) -> bool:
            if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
                return True
            if isinstance(v, dict):
                for vv in v.values():
                    if _walk(vv):
                        return True
            if isinstance(v, list):
                for vv in v:
                    if _walk(vv):
                        return True
            return False

        try:
            obj = json.loads(json_path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            return False
        if not isinstance(obj, dict):
            return False
        return _walk(obj.get("recordResult"))

    def _has_mcos_table_in_mat(raw: bytes) -> bool:
        try:
            data = sio.loadmat(io.BytesIO(raw), squeeze_me=True, struct_as_record=False, verify_compressed_data_integrity=False)
            rr = data.get("recordResult")
            if rr is None:
                return False
            ocr = rr.get("ocr") if isinstance(rr, dict) else getattr(rr, "ocr", None)
            if ocr is None:
                return False
            for field in ("roi_table", "table", "cleaned"):
                v = ocr.get(field) if isinstance(ocr, dict) else getattr(ocr, field, None)
                if v is None:
                    continue
                if type(v).__name__ == "MatlabOpaque":
                    return True
                try:
                    arr = np.asarray(v)
                    if getattr(arr, "dtype", None) is not None and arr.dtype.names and {"s1", "s2", "arr"}.issubset(set(arr.dtype.names)):
                        return True
                except Exception:
                    pass
        except Exception:
            return False
        return False

    def _matlab_convert_recordresult_json(raw: bytes) -> tuple[bool, bytes, str]:
        matlab_exe = shutil.which("matlab")
        if not matlab_exe:
            return False, b"", "matlab.exe nicht gefunden"

        mat_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mat")
        mat_tmp.close()
        out_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        out_tmp.close()
        m_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".m")
        m_tmp.close()

        def _q(s: str) -> str:
            return str(s).replace("\\", "/").replace("'", "''")

        script = f"""
inPath = '{_q(mat_tmp.name)}';
outPath = '{_q(out_tmp.name)}';
s = load(inPath);
if ~isfield(s, 'recordResult')
    error('recordResultMissing');
end
payload = struct();
payload.recordResult = local_norm(s.recordResult);
txt = jsonencode(payload, PrettyPrint=true);
fid = fopen(outPath, 'w', 'n', 'UTF-8');
if fid < 0
    error('jsonOpenFailed');
end
fwrite(fid, txt, 'char');
fclose(fid);

function out = local_norm(x)
    if istable(x)
        out = table_to_rows(x);
        return;
    end
    if isstruct(x)
        if numel(x) > 1
            out = repmat(struct(), size(x));
            for i = 1:numel(x)
                f = fieldnames(x(i));
                for k = 1:numel(f)
                    out(i).(f{{k}}) = local_norm(x(i).(f{{k}}));
                end
            end
        else
            out = struct();
            f = fieldnames(x);
            for k = 1:numel(f)
                out.(f{{k}}) = local_norm(x.(f{{k}}));
            end
        end
        return;
    end
    if iscell(x)
        out = cell(size(x));
        for i = 1:numel(x)
            out{{i}} = local_norm(x{{i}});
        end
        return;
    end
    if isstring(x)
        if isscalar(x)
            out = char(x);
        else
            out = cellstr(x);
        end
        return;
    end
    if iscategorical(x) || isdatetime(x) || isduration(x)
        sx = string(x);
        if isscalar(sx)
            out = char(sx);
        else
            out = cellstr(sx);
        end
        return;
    end
    out = x;
end

function rows = table_to_rows(t)
    if isempty(t)
        rows = struct([]);
        return;
    end
    names = t.Properties.VariableNames;
    n = height(t);
    rows = repmat(struct(), n, 1);
    for i = 1:n
        for j = 1:numel(names)
            v = t{{i, j}};
            if iscell(v) && numel(v) == 1
                v = v{{1}};
            end
            rows(i).(names{{j}}) = local_norm(v);
        end
    end
end
"""
        try:
            Path(mat_tmp.name).write_bytes(raw)
            Path(m_tmp.name).write_text(script, encoding="utf-8")
            cmd = [matlab_exe, "-batch", f"run('{_q(m_tmp.name)}')"]
            p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
            if p.returncode != 0:
                err = ((p.stdout or "") + "\n" + (p.stderr or "")).strip()
                return False, b"", (err[-1200:] if err else "MATLAB-Konvertierung fehlgeschlagen")
            raw_out = Path(out_tmp.name).read_bytes()
            if not raw_out:
                return False, b"", "MATLAB lieferte leere JSON"
            return True, raw_out, "matlab fallback"
        except Exception as e:
            return False, b"", str(e)
        finally:
            for t in (mat_tmp.name, out_tmp.name, m_tmp.name):
                try:
                    Path(t).unlink(missing_ok=True)
                except Exception:
                    pass

    def _maybe_fix_mcos_tables_with_matlab(raw: bytes, json_bytes: bytes) -> tuple[bytes, str]:
        lengths = _json_recordresult_ocr_lengths(json_bytes)
        needs = (lengths.get("table", -1) == 0 or lengths.get("cleaned", -1) == 0)
        if needs and (not _has_mcos_table_in_mat(raw)):
            return json_bytes, ""
        if not needs:
            return json_bytes, ""
        ok_ml, out_ml, msg_ml = _matlab_convert_recordresult_json(raw)
        if ok_ml and out_ml:
            return out_ml, str(msg_ml or "")
        return json_bytes, ""

    def _normalize_json_bytes(json_bytes: bytes) -> bytes:
        norm = globals().get("_normalize_sidecar_json_payload")
        if not callable(norm):
            return json_bytes
        try:
            obj = json.loads((json_bytes or b"").decode("utf-8", errors="ignore"))
            if not isinstance(obj, dict):
                return json_bytes
            obj_n = norm(obj)
            return json.dumps(obj_n, ensure_ascii=False, indent=2, default=lambda o: _mat_export_to_jsonable(o)).encode("utf-8")
        except Exception:
            return json_bytes

    def _normalize_json_file_in_place(json_path: Path) -> tuple[bool, str]:
        try:
            raw = json_path.read_bytes()
        except Exception as e:
            return False, f"json read fehler: {e}"
        normed = _normalize_json_bytes(raw)
        if normed != raw:
            _lock = get_path_lock(str(json_path))
            if not _lock.acquire(blocking=False):
                return False, "Datei wird vom Watchdog bearbeitet"
            try:
                json_path.write_bytes(normed)
            except Exception as e:
                return False, f"json write fehler: {e}"
            finally:
                _lock.release()
        return True, ""

    def _convert_mat_bytes(raw: bytes) -> tuple[bool, bytes, str]:
        if not raw:
            return False, b"", "leere MAT-Datei"
        try:
            helper = globals().get("_mat_bytes_to_recordresult_json_bytes")
            if callable(helper):
                out = helper(raw)
                if out:
                    fixed, note = _maybe_fix_mcos_tables_with_matlab(raw, bytes(out))
                    return True, _normalize_json_bytes(bytes(fixed)), str(note or "")
            from core.save_helpers import rr_from_mat_bytes
            rr, _extra = rr_from_mat_bytes(raw)
            if not isinstance(rr, dict) or not rr:
                ok_fb, out_fb, msg_fb = _fallback_recordresult_json_bytes(raw)
                if ok_fb:
                    fixed_fb, note_fb = _maybe_fix_mcos_tables_with_matlab(raw, out_fb)
                    return True, _normalize_json_bytes(fixed_fb), str(note_fb or msg_fb or "")
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
            fixed_data, note_data = _maybe_fix_mcos_tables_with_matlab(raw, data)
            return True, _normalize_json_bytes(fixed_data), str(note_data or "")
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
            if not json_exists:
                status = "ausstehend"
                pending.append(mat_path)
            else:
                status = "bereits vorhanden"
                lengths = _json_recordresult_ocr_lengths_from_path(json_path)
                if lengths.get("table", -1) < 0 or lengths.get("cleaned", -1) < 0:
                    status = "json fehlerhaft - neu konvertieren"
                    pending.append(mat_path)
                elif lengths.get("table", -1) == 0 or lengths.get("cleaned", -1) == 0:
                    try:
                        raw = mat_path.read_bytes()
                    except Exception:
                        raw = b""
                    if raw and _has_mcos_table_in_mat(raw):
                        status = "json leer (table/cleaned) - neu konvertieren"
                        pending.append(mat_path)
                elif _json_has_row_table_lists(json_path):
                    status = "json zeilenformat gefunden - neu konvertieren"
                    pending.append(mat_path)
            prev = status_map.get(mat_path.name)
            if isinstance(prev, dict):
                prev_status = str(prev.get("status") or "").strip()
                if prev_status and status in ("ausstehend", "bereits vorhanden"):
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

    results_dir = _results_dir_from_local_db()
    if results_dir is None:
        st.warning("Lokale DB ist nicht gesetzt. Bitte zuerst im Tab 'Cloud Connection & Root' den lokalen Basispfad setzen.")
        return

    results_dir.mkdir(parents=True, exist_ok=True)
    st.caption(f"Verwendeter Ordner: {results_dir}")

    def _convert_one_mat(mat_path: Path) -> dict:
        mat_name = mat_path.name
        json_path = mat_path.with_suffix(".json")
        try:
            if json_path.exists() and _json_has_row_table_lists(json_path):
                ok_norm, err_norm = _normalize_json_file_in_place(json_path)
                if ok_norm:
                    return {"ok": True, "mat_name": mat_name, "status": "konvertiert (json-normalisierung)", "error": ""}
                return {"ok": False, "mat_name": mat_name, "status": f"fehler: {err_norm}", "error": str(err_norm or "")}
            raw = mat_path.read_bytes()
            ok, json_bytes, err = _convert_mat_bytes(raw)
            if ok:
                _lock = get_path_lock(str(json_path))
                if not _lock.acquire(blocking=False):
                    return {"ok": False, "mat_name": mat_name, "status": "gesperrt (Watchdog aktiv)", "error": "Datei wird vom Watchdog bearbeitet"}
                try:
                    json_path.write_bytes(json_bytes)
                finally:
                    _lock.release()
                return {"ok": True, "mat_name": mat_name, "status": "konvertiert", "error": ""}
            return {"ok": False, "mat_name": mat_name, "status": f"fehler: {err}", "error": str(err or "")}
        except Exception as e:
            return {"ok": False, "mat_name": mat_name, "status": f"fehler: {e}", "error": str(e)}

    def _run_conversion_thread(pending: list[Path]) -> None:
        with _CONV_LOCK:
            _CONV["running"] = True
            _CONV["done_n"] = 0
            _CONV["total_n"] = len(pending)
            _CONV["ok_n"] = 0
            _CONV["err_n"] = 0
            _CONV["stop_requested"] = False
            _CONV["current"] = ""
            _CONV["next_file"] = pending[1].name if len(pending) > 1 else ""
            _CONV["status_map"] = {}

        for i, mat_path in enumerate(pending):
            with _CONV_LOCK:
                if _CONV["stop_requested"]:
                    break
                _CONV["current"] = mat_path.name
                _CONV["next_file"] = pending[i + 1].name if i + 1 < len(pending) else ""

            res = _convert_one_mat(mat_path)

            with _CONV_LOCK:
                mat_name = str(res.get("mat_name") or "")
                st_txt = str(res.get("status") or "")
                er_txt = str(res.get("error") or "")
                if res.get("ok"):
                    _CONV["status_map"][mat_name] = {"status": st_txt or "konvertiert", "error": ""}
                    _CONV["ok_n"] += 1
                else:
                    _CONV["status_map"][mat_name] = {"status": st_txt, "error": er_txt}
                    _CONV["err_n"] += 1
                _CONV["done_n"] += 1

        with _CONV_LOCK:
            _CONV["running"] = False
            _CONV["current"] = ""

    fragment_fn = getattr(st, "fragment", None) or getattr(st, "experimental_fragment", None)

    def _render_panel() -> None:
        status_map_local = dict(st.session_state.get("mat_to_json_status_map") or {})

        with _CONV_LOCK:
            running = bool(_CONV["running"])
            done_n = int(_CONV["done_n"])
            total_n = int(_CONV["total_n"])
            ok_n = int(_CONV["ok_n"])
            err_n = int(_CONV["err_n"])
            current = str(_CONV["current"])
            next_file = str(_CONV["next_file"])
            stop_req = bool(_CONV["stop_requested"])
            live_map = dict(_CONV["status_map"])

        # Merge live conversion results into display map
        if live_map:
            status_map_local = dict(status_map_local)
            status_map_local.update(live_map)

        rows, pending = _scan_results_rows(results_dir, status_map_local)
        total = len(rows)
        pending_n = len(pending)

        if total > 0:
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True, height=380)
        else:
            st.dataframe(
                pd.DataFrame(columns=["name der mat datei", "äquivalente json datei",
                                       "mat datei vorhanden", "json datei vorhanden", "konvertierungsstatus"]),
                width="stretch", hide_index=True, height=220,
            )

        st.caption(f"MAT-Dateien: {total} | fehlend/neu zu konvertieren: {pending_n}")

        # Progress bar (only while running)
        if running:
            remain = max(0, total_n - done_n)
            st.progress(
                done_n / max(1, total_n),
                text=f"{done_n}/{total_n} konvertiert | verbleibend: {remain}",
            )
            lbl = "Stop angefordert – läuft noch..." if stop_req else f"Aktuell: {current} | Nächste: {next_file or '–'}"
            st.caption(lbl)

        c1, c2 = st.columns(2)
        convert_clicked = c1.button(
            "alle .mat dateien ohne .json in .json konvertieren",
            type="primary",
            width="stretch",
            key="mat_to_json_convert_all_missing_btn",
            disabled=running,
        )
        stop_clicked = c2.button(
            "Auswahl stoppen",
            width="stretch",
            key="mat_to_json_stop_btn",
            disabled=not running,
        )

        if stop_clicked:
            with _CONV_LOCK:
                _CONV["stop_requested"] = True

        if convert_clicked:
            if pending_n <= 0:
                set_status("Keine ausstehenden MAT-Dateien zur Konvertierung.", "warn")
            else:
                th = _threading.Thread(target=_run_conversion_thread, args=(list(pending),), daemon=True)
                with _CONV_LOCK:
                    _CONV["thread"] = th
                th.start()

        # Sync finished results to session state (once, after thread completes)
        if not running and live_map:
            merged = dict(st.session_state.get("mat_to_json_status_map") or {})
            merged.update(live_map)
            st.session_state.mat_to_json_status_map = merged
            with _CONV_LOCK:
                _CONV["status_map"] = {}
            if err_n == 0:
                set_status(f"MAT->JSON abgeschlossen: {ok_n}/{max(1,total_n)} konvertiert.", "ok")
            else:
                set_status(f"MAT->JSON abgeschlossen: {ok_n} OK, {err_n} Fehler.", "warn")

    if callable(fragment_fn):
        @fragment_fn(run_every=1.0)
        def _panel_fragment():
            _render_panel()
        _panel_fragment()
    else:
        _render_panel()
        if _CONV["running"]:
            time.sleep(1.0)
            st.rerun()
