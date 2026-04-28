import ast
import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import scipy.io as sio


def _load_mat_summary_namespace():
    repo = Path(__file__).resolve().parents[1]
    source = (repo / "app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    needed = {
        "_compute_mat_summary_remote",
        "_summarize_record_result_mat",
        "_summarize_record_result_hdf5",
        "_mat_scalar",
        "_mat_obj_get",
        "_mat_to_text",
        "_mat_truthy",
        "_mat_to_float",
        "_mat_is_nonempty",
        "_mat_table_height",
        "_mat_table_column",
        "_mat_numeric_vector",
        "_mat_has_nonempty_roi_field",
        "_mat_roi_table_has_track",
        "_parse_roi_value",
        "_mat_capture_guess_from_key",
    }
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in needed]
    namespace = {
        "np": np,
        "sio": sio,
        "Path": Path,
        "tempfile": tempfile,
        "summarize_mat_file": lambda _path: {"roi_selected": True, "track_selected": True},
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(repo / "app.py"), "exec"), namespace)
    namespace["_extract_rois_from_recordresult_hdf5"] = lambda _path: []
    namespace["_h5_get_path_ci"] = lambda *_args, **_kwargs: None
    namespace["_h5_to_text_list"] = lambda *_args, **_kwargs: []
    return namespace


def _load_audio_save_namespace():
    repo = Path(__file__).resolve().parents[1]
    source = (repo / "app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    needed = {
        "_mat_scalar",
        "_mat_struct_to_plain",
        "_matlab_field_name",
        "_cellstr_column",
        "_struct_array_from_dicts",
        "_build_audio_rpm_struct_from_result",
        "_save_audio_result_to_selected_mat",
    }
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in needed]
    namespace = {
        "np": np,
        "sio": sio,
        "Path": Path,
        "tempfile": tempfile,
        "shutil": shutil,
        "json": json,
        "datetime": datetime,
        "st": SimpleNamespace(session_state={}),
        "_build_save_mat_struct": lambda _result: {"recordResult": {}},
        "build_result_json": lambda: {},
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(repo / "app.py"), "exec"), namespace)
    return namespace


def _write_no_roi_mat(path: Path):
    roi_dtype = [
        ("name_roi", object),
        ("roi", object),
        ("fmt", object),
        ("max_scale", object),
    ]
    empty_roi_table = np.empty((0, 1), dtype=roi_dtype)
    sio.savemat(
        str(path),
        {
            "recordResult": {
                "metadata": {
                    "title": "Unit Test Video Title",
                    "no_roi_available": np.array([[1]], dtype=np.uint8),
                    "roi_status": "kein_roi_vorhanden",
                },
                "ocr": {
                    "params": {"start_s": 0.0, "end_s": 10.0},
                    "roi_table": empty_roi_table,
                    "no_roi_available": True,
                    "roi_status": "kein_roi_vorhanden",
                },
            }
        },
        do_compression=True,
    )


class _MatClient:
    def __init__(self, mat_path: Path):
        self.mat_path = mat_path

    def download_file(self, _remote_key, target):
        shutil.copyfile(self.mat_path, target)
        return True, ""

    def list_files(self, _prefix):
        return False, []


class _NamedTemp:
    def __init__(self, name):
        self.name = str(name)

    def close(self):
        return None


class _TempfileStub:
    def __init__(self, target: Path):
        self.target = target

    def NamedTemporaryFile(self, delete=False, suffix=""):
        return _NamedTemp(self.target)


def test_no_roi_stamp_overrides_backend_roi_summary_and_keeps_title():
    ns = _load_mat_summary_namespace()
    repo = Path(__file__).resolve().parents[1]
    tmp_dir = repo / "logs" / "mat_sync_audio_ui_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    mat_path = tmp_dir / "results_capture.mat"
    download_path = tmp_dir / "downloaded_capture.mat"
    for path in (mat_path, download_path):
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
    ns["tempfile"] = _TempfileStub(download_path)
    _write_no_roi_mat(mat_path)

    summary = ns["_compute_mat_summary_remote"](
        "results/results_capture.mat",
        _MatClient(mat_path),
        "",
    )

    assert summary["no_roi_available"] is True
    assert summary["roi_selected"] is False
    assert summary["track_selected"] is False
    assert summary["title"] == "Unit Test Video Title"


def test_sync_and_audio_ui_regression_tokens():
    repo = Path(__file__).resolve().parents[1]
    source = (repo / "app.py").read_text(encoding="utf-8")
    for rel in (
        "app_tabs/sync_tab.py",
        "app_tabs/mat_selection_tab.py",
        "app_tabs/audio_tab.py",
    ):
        source += "\n" + (repo / rel).read_text(encoding="utf-8")

    assert 'update_label = "Stop" if running else "Update"' in source
    assert "sync_select_missing_cloud" in source
    assert "table_slot.data_editor" in source
    assert "sync_refresh_btn_running" not in source
    assert "c_sync_refresh" not in source
    assert "Erwartete Frames unbekannt" not in source
    assert "Originalvideo nicht lesbar" in source

    start_button_pos = source.index('key="aud_run_new"')
    live_panel_pos = source.index("_audio_native_live_refresh_panel()", start_button_pos)
    assert live_panel_pos > start_button_pos
    assert source.count('with st.expander("Live-Debug Audioanalyse"') == 1
    assert "Start bestätigt: Audioanalyse läuft im Hintergrund" in source


def test_real_no_roi_example_mat_is_recognized():
    ns = _load_mat_summary_namespace()
    repo = Path(__file__).resolve().parents[1]
    mat_path = repo / "results_20260219_151929.mat"
    assert mat_path.exists(), "Beispiel-MAT results_20260219_151929.mat fehlt."

    summary = ns["_summarize_record_result_mat"](str(mat_path))

    assert summary["no_roi_available"] is True
    assert summary["roi_selected"] is False
    assert summary["track_selected"] is False
    assert summary["title"] == "Schäfer Mini Onboard Nordschleife Nuerburgring"


def test_tabs_are_split_into_renderer_modules():
    repo = Path(__file__).resolve().parents[1]
    modules = [
        "setup_tab.py",
        "sync_tab.py",
        "mat_selection_tab.py",
        "audio_tab.py",
        "roi_setup_tab.py",
        "track_analysis_tab.py",
    ]
    for name in modules:
        path = repo / "app_tabs" / name
        assert path.exists(), f"{name} fehlt."
        text = path.read_text(encoding="utf-8")
        assert "def render(ns):" in text

    app_source = (repo / "app.py").read_text(encoding="utf-8")
    assert "from app_tabs import" in app_source
    for name in ("setup_tab", "sync_tab", "mat_selection_tab", "audio_tab", "roi_setup_tab", "track_analysis_tab"):
        assert f"{name}.render(globals())" in app_source


def test_audio_result_can_be_saved_to_local_mat_copy():
    ns = _load_audio_save_namespace()
    repo = Path(__file__).resolve().parents[1]
    src = repo / "results_20251116_212257.mat"
    assert src.exists(), "Beispiel-MAT results_20251116_212257.mat fehlt."
    tmp_dir = repo / "logs" / "mat_sync_audio_ui_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    dst = tmp_dir / "audio_save_target.mat"
    shutil.copyfile(src, dst)

    ns["st"].session_state.update(
        {
            "mat_selected_key": "",
            "mat_pending_selected_key": "",
            "audio_last_mat_path": str(dst),
            "r2_connected": False,
            "r2_client": None,
            "audio_debug_lines": ["debug ok"],
        }
    )
    res = {
        "t": np.array([0.0, 0.5, 1.0], dtype=float),
        "rpm": np.array([1000.0, 1200.0, 1400.0], dtype=float),
        "selected_freq": np.array([40.0, 48.0, 56.0], dtype=float),
        "selected_method": "UnitTest",
        "source": "local-video:test.mp4",
        "params": {"conversion_factor": 2.0, "nfft": 512},
        "ui": {"vehicle_title": "Unit Test"},
        "freq_lines": {"UnitTest": np.array([40.0, 48.0, 56.0], dtype=float)},
        "candidate_table": [{"Methode": "UnitTest", "Score": 1.0}],
        "debug_lines": ["saved"],
    }

    ok, message = ns["_save_audio_result_to_selected_mat"](res)

    assert ok, message
    data = sio.loadmat(str(dst), squeeze_me=True, struct_as_record=False)
    rr = data["recordResult"]
    audio_rpm = getattr(rr, "audio_rpm")
    assert getattr(audio_rpm, "processed") is not None
    assert getattr(audio_rpm, "params") is not None
