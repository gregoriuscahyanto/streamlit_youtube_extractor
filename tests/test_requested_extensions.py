import ast
import io
import zipfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd


class _State(dict):
    def __getattr__(self, name):
        return self[name]

    def __setattr__(self, name, value):
        self[name] = value


def _load_functions(names):
    repo = Path(__file__).resolve().parents[1]
    source = (repo / "app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in set(names)]
    namespace = {
        "np": np,
        "pd": pd,
        "io": io,
        "zipfile": zipfile,
        "Path": Path,
        "st": SimpleNamespace(session_state=_State(mat_summary_cache={})),
        "datetime": __import__("datetime").datetime,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(repo / "app.py"), "exec"), namespace)
    return namespace


def test_youtube_title_xlsx_export_is_real_excel_without_cloud_dependency():
    ns = _load_functions([
        "_audio_title_from_summary",
        "_summary_video_link",
        "_build_youtube_title_excel_bytes",
    ])
    ns["st"].session_state["mat_summary_cache"] = {
        "results/results_20260219_151929.mat": {
            "title": "Schaefer Mini Onboard Nordschleife",
            "youtube_url": "https://youtu.be/example",
            "mat_file": "results_20260219_151929.mat",
        }
    }
    data = ns["_build_youtube_title_excel_bytes"]([
        {"mat_datei": "20260219_151929", "remote_key": "results/results_20260219_151929.mat"}
    ])

    with zipfile.ZipFile(io.BytesIO(data), "r") as z:
        names = set(z.namelist())
        sheet = z.read("xl/worksheets/sheet1.xml").decode("utf-8")

    assert "[Content_Types].xml" in names
    assert "youtube video title" in sheet
    assert "Schaefer Mini Onboard Nordschleife" in sheet
    assert "https://youtu.be/example" in sheet


def test_audio_validation_metrics_and_best_shift():
    ns = _load_functions([
        "_audio_validation_metrics",
        "_audio_find_best_validation_shift",
    ])
    t_audio = np.array([0.0, 1.0, 2.0, 3.0])
    rpm_audio = np.array([1000.0, 1100.0, 1200.0, 1300.0])
    t_ref = t_audio - 0.5
    rpm_ref = rpm_audio.copy()

    shifted = ns["_audio_validation_metrics"](t_audio, rpm_audio, t_ref, rpm_ref, 0.5, "Absolutwert")
    assert shifted["ok"] is True
    assert shifted["mae"] == 0.0

    best, log = ns["_audio_find_best_validation_shift"](t_audio, rpm_audio, t_ref, rpm_ref, "Absolutwert", -1.0, 1.0, 0.5)
    assert best["ok"] is True
    assert abs(best["shift_s"] - 0.5) < 1e-9
    assert any("Best match" in line for line in log)


def test_tabs_and_audio_config_ui_are_wired():
    repo = Path(__file__).resolve().parents[1]
    app_source = (repo / "app.py").read_text(encoding="utf-8")
    mat_source = (repo / "app_tabs" / "mat_selection_tab.py").read_text(encoding="utf-8")
    audio_source = (repo / "app_tabs" / "audio_tab.py").read_text(encoding="utf-8")
    roi_source = (repo / "app_tabs" / "roi_setup_tab.py").read_text(encoding="utf-8")

    assert not (repo / "app_tabs" / "track_analysis_tab.py").exists()
    assert '"Track Analysis"' not in app_source
    assert "audio_config" in app_source
    assert "YouTube-Titel Excel" in mat_source
    assert "_build_youtube_title_excel_bytes" in mat_source
    assert "Audio Config speichern" in audio_source
    assert "Hole naechste Datei" in audio_source
    assert "RPM Validierung" in audio_source
    assert "Find best match" in audio_source
    assert "def _render_track_analysis_section" in roi_source
    assert "2 · Track Analysis" in roi_source
