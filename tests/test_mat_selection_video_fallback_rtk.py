import ast
from pathlib import Path


def _load_fns(*names: str):
    repo = Path(__file__).resolve().parents[1]
    src = (repo / "app.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    needed = set(names)
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in needed]
    ns = {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(repo / "app.py"), "exec"), ns)
    return {n: ns[n] for n in names}


def test_capture_folder_candidates_include_metadata_paths():
    fns = _load_fns("_capture_folder_from_path_hint", "_capture_folder_candidates_from_json_doc")
    fn = fns["_capture_folder_candidates_from_json_doc"]
    doc = {
        "recordResult": {
            "metadata": {
                "outdir": r"captures\20251113_121113",
                "video": r"captures\20251113_121113\screen_20251113_121113_video.mp4",
                "audio": r"captures\20251113_121113\screen_20251113_121113_audio.wav",
            }
        }
    }
    cands = fn("wrong_folder_name", doc)
    assert "wrong_folder_name" in cands
    assert "20251113_121113" in cands


def test_video_loader_uses_framepack_local_and_cloud_fallbacks():
    src = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    assert "def _try_load_video_for_capture_folder_with_fallback" in src
    blk = src.split("def _try_load_video_for_capture_folder_with_fallback", 1)[1]
    assert "_load_framepack_from_r2(" in blk
    assert "_find_local_fullfps_video(" in blk
    assert "_load_full_video_from_r2(" in blk
