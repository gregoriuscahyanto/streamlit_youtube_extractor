"""RTK checks for the dedicated local results MAT-to-JSON conversion tab."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_app_registers_mat_to_json_tab():
    txt = _read("app.py")
    assert "mat_to_json_tab" in txt
    assert '"MAT to JSON"' in txt
    assert "mat_to_json_tab.render(globals())" in txt


def test_tab_uses_only_local_results_folder():
    txt = _read("app_tabs/mat_to_json_tab.py")
    assert "def _results_dir_from_local_db() -> Path | None:" in txt
    assert 'lp = str(st.session_state.get("local_base_path") or "").strip()' in txt
    assert 'Path(lp).expanduser().resolve() / "results"' in txt
    assert "st.file_uploader(" not in txt
    assert "accept_multiple_files=True" not in txt


def test_tab_has_required_overview_columns_and_bulk_convert_button():
    txt = _read("app_tabs/mat_to_json_tab.py")
    assert '"name der mat datei"' in txt
    assert '"äquivalente json datei"' in txt
    assert '"mat datei vorhanden"' in txt
    assert '"json datei vorhanden"' in txt
    assert '"konvertierungsstatus"' in txt
    assert '"alle .mat dateien ohne .json in .json konvertieren"' in txt


def test_tab_reconverts_invalid_or_empty_json_when_mcos_tables_exist():
    txt = _read("app_tabs/mat_to_json_tab.py")
    assert "def _json_recordresult_ocr_lengths_from_path(json_path: Path) -> dict:" in txt
    assert "def _json_has_row_table_lists(json_path: Path) -> bool:" in txt
    assert "def _normalize_json_file_in_place(json_path: Path) -> tuple[bool, str]:" in txt
    assert 'status = "json fehlerhaft - neu konvertieren"' in txt
    assert 'status = "json leer (table/cleaned) - neu konvertieren"' in txt
    assert 'status = "json zeilenformat gefunden - neu konvertieren"' in txt
    assert "elif _json_has_row_table_lists(json_path):" in txt
    assert "if json_path.exists() and _json_has_row_table_lists(json_path):" in txt
    assert '"konvertiert (json-normalisierung)"' in txt
    assert "if raw and _has_mcos_table_in_mat(raw):" in txt
    assert "fehlend/neu zu konvertieren" in txt


def test_tab_has_progress_feedback_for_current_file_and_remaining():
    txt = _read("app_tabs/mat_to_json_tab.py")
    assert "table_slot = st.empty()" in txt
    assert "def _render_rows_table(table_rows: list[dict]) -> None:" in txt
    assert "_render_rows_table(rows_local)" in txt
    assert "progress_slot = st.empty()" in txt
    assert "current_slot = st.empty()" in txt
    assert "seriell (Datei für Datei)" in txt
    assert '"Auswahl stoppen"' in txt
    assert 'st.session_state.setdefault("mat_to_json_running", False)' in txt
    assert 'st.session_state.setdefault("mat_to_json_stop_requested", False)' in txt
    assert "ThreadPoolExecutor" not in txt
    assert "as_completed" not in txt
    assert "rows_live, _pending_live = _scan_results_rows(results_dir, status_map_local)" in txt
    assert "_render_rows_table(rows_live)" in txt
    assert 'current_slot.caption(f"Aktuell fertig: {json_name} ({done_n}/{max(1,total_n)})")' in txt
    assert 'text=f"{done_n}/{max(1,total_n)} konvertiert | verbleibend: {remain}"' in txt
    assert "Stop angefordert: MAT->JSON stoppt nach aktueller Datei." in txt
    assert 'fragment_fn = getattr(st, "fragment", None) or getattr(st, "experimental_fragment", None)' in txt
    assert "can_start = not running_local" in txt
    assert "can_stop = running_local" in txt
    assert "disabled=not can_start" in txt
    assert "disabled=not can_stop" in txt
    assert 'set_status("Keine ausstehenden MAT-Dateien zur Konvertierung.", "warn")' in txt


def test_tab_reuses_canonical_mat_to_json_helpers():
    txt = _read("app_tabs/mat_to_json_tab.py")
    assert "def _convert_mat_bytes(raw: bytes)" in txt
    assert "def _fallback_recordresult_json_bytes(raw: bytes)" in txt
    assert "def _matlab_convert_recordresult_json(raw: bytes) -> tuple[bool, bytes, str]:" in txt
    assert "def _maybe_fix_mcos_tables_with_matlab(raw: bytes, json_bytes: bytes) -> tuple[bytes, str]:" in txt
    assert 'helper = globals().get("_mat_bytes_to_recordresult_json_bytes")' in txt
    assert 'robust_loader = globals().get("_loadmat_audio_save_robust")' in txt
    assert 'h5_decode = globals().get("_h5_decode_value")' in txt
    assert 'h5_get_ci = globals().get("_h5_get_path_ci")' in txt
    assert 'matlab_exe = shutil.which("matlab")' in txt
    assert 'cmd = [matlab_exe, "-batch", f"run(\'{_q(m_tmp.name)}\')"]' in txt
    assert 'payload = {"recordResult": _mat_export_to_jsonable(rr_plain)}' in txt
    assert "from core.save_helpers import rr_from_mat_bytes" in txt
    assert "_mat_export_to_jsonable(rr)" in txt
    assert "_normalize_sidecar_json_payload" in txt
