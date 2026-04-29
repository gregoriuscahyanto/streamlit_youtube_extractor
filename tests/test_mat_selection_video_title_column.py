import ast
from pathlib import Path


def _load_functions(names: set[str]):
    repo = Path(__file__).resolve().parents[1]
    source = (repo / "app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    ns = {"LAMP_GREEN": "Y", "LAMP_RED": "N"}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(repo / "app.py"), "exec"), ns)
    return ns


def test_summary_row_exposes_video_title_and_keeps_remote_key_internal():
    ns = _load_functions({"_summary_to_overview_row", "_jn"})
    row = ns["_summary_to_overview_row"](
        {
            "capture_folder": "20260219_161613",
            "remote_key": "results/results_20260219_161613.mat",
            "title": "The 919 Tribute Tour: On-board record lap, Nordschleife.",
            "video_file_exists": True,
            "audio_file_exists": True,
        }
    )
    assert row["video_title"] == "The 919 Tribute Tour: On-board record lap, Nordschleife."
    assert row["remote_key"] == "results/results_20260219_161613.mat"


def test_mat_selection_tab_hides_remote_key_column_but_uses_it_for_selection():
    repo = Path(__file__).resolve().parents[1]
    src = (repo / "app_tabs" / "mat_selection_tab.py").read_text(encoding="utf-8")
    assert 'visible_df = styled_df.drop(columns=["remote_key"], errors="ignore")' in src
    assert "st.session_state.mat_user_selected_key = current_selected_key" in src or "mat_user_selected_key" in src
    assert '.get("remote_key"' in src
