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


def test_tab_has_progress_feedback_for_current_file_and_remaining():
    txt = _read("app_tabs/mat_to_json_tab.py")
    assert "progress_slot = st.empty()" in txt
    assert "current_slot = st.empty()" in txt
    assert 'current_slot.caption(f"Aktuell: {json_path.name} ({i}/{pending_n})")' in txt
    assert 'text=f"{i}/{pending_n} konvertiert | verbleibend: {remain}"' in txt


def test_tab_reuses_canonical_mat_to_json_helpers():
    txt = _read("app_tabs/mat_to_json_tab.py")
    assert "def _convert_mat_bytes(raw: bytes)" in txt
    assert "def _fallback_recordresult_json_bytes(raw: bytes)" in txt
    assert 'helper = globals().get("_mat_bytes_to_recordresult_json_bytes")' in txt
    assert 'robust_loader = globals().get("_loadmat_audio_save_robust")' in txt
    assert 'h5_decode = globals().get("_h5_decode_value")' in txt
    assert 'h5_get_ci = globals().get("_h5_get_path_ci")' in txt
    assert 'payload = {"recordResult": _mat_export_to_jsonable(rr_plain)}' in txt
    assert "from core.save_helpers import rr_from_mat_bytes" in txt
    assert "_mat_export_to_jsonable(rr)" in txt
    assert "_normalize_sidecar_json_payload" in txt
