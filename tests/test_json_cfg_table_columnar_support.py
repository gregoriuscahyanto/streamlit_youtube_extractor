import ast
from pathlib import Path


def _load_fn(name: str):
    repo = Path(__file__).resolve().parents[1]
    src = (repo / "app.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    needed = {
        name,
        "_mat_obj_get",
        "_mat_scalar",
        "_mat_to_text",
        "_parse_roi_value",
        "_pts_from_mat_value",
        "_marker_to_color_range",
    }
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in needed]
    ns = {"np": __import__("numpy")}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(repo / "app.py"), "exec"), ns)
    return ns[name]


def test_recordresult_json_to_cfg_accepts_columnar_roi_table():
    fn = _load_fn("_recordresult_json_to_cfg")
    doc = {
        "recordResult": {
            "ocr": {
                "params": {"start_s": 1.0, "end_s": 9.0},
                "roi_table": {
                    "name_roi": ["speed", "rpm"],
                    "roi": [[10, 20, 30, 40], [50, 60, 70, 80]],
                    "fmt": ["float", "int_4"],
                    "max_scale": [1.2, 1.3],
                },
            }
        }
    }
    cfg = fn(doc, vid_duration=12.0)
    assert cfg["t_start"] == 1.0
    assert cfg["t_end"] == 9.0
    assert len(cfg["rois"]) == 2
    assert cfg["rois"][0]["name"] == "speed"
    assert cfg["rois"][1]["name"] == "rpm"


def test_recordresult_json_to_cfg_accepts_string_roi_and_audio_params_fallback():
    fn = _load_fn("_recordresult_json_to_cfg")
    doc = {
        "recordResult": {
            "audio_rpm": {
                "params": {
                    "nfft": 8192,
                    "ovPerc": 75,
                    "fmax": 1000,
                    "order": 1,
                    "r_dyn": 0.35,
                    "tol_pct": 6.0,
                    "i_axle": 4.059,
                    "gears": [3.56, 2.53, 1.68],
                    "prefer_low": False,
                    "use_v": True,
                }
            },
            "ocr": {
                "params": {"start_s": 2.0, "end_s": 11.0, "audio_offset_s": 0.4},
                "roi_table": {
                    "name_roi": ["v_Fzg_mph", "track_minimap"],
                    "roi": ["750   14  417  227", "0   29  305  237"],
                    "fmt": ["integer", "any"],
                    "max_scale": [1.2, 1.2],
                },
                "trkCalSlim": {"ptsMini": [[1, 2], [3, 4], [5, 6], [7, 8]]},
            },
        }
    }
    cfg = fn(doc, vid_duration=20.0)
    assert cfg["t_start"] == 2.0
    assert cfg["t_end"] == 11.0
    assert len(cfg["rois"]) == 2
    assert cfg["rois"][0]["x"] == 750.0
    assert cfg["rois"][1]["h"] == 237.0
    assert isinstance(cfg.get("minimap_pts"), list) and len(cfg["minimap_pts"]) >= 4
    ac = cfg.get("audio_config") or {}
    assert ac.get("nfft") == 8192
    assert ac.get("overlap_pct") == 75
    assert ac.get("fmax") == 1000
    assert ac.get("order") == 1
    assert ac.get("r_dyn_m") == 0.35
    assert ac.get("tol_pct") == 6.0
    assert ac.get("axle_ratio") == 4.059
    assert ac.get("gear_ratios") == [3.56, 2.53, 1.68]
    assert ac.get("use_ocr_v") is True
    assert ac.get("audio_offset_s") == 0.4


def test_recordresult_json_to_cfg_accepts_flat_single_roi_table():
    fn = _load_fn("_recordresult_json_to_cfg")
    doc = {
        "recordResult": {
            "ocr": {
                "params": {"start_s": 0.0, "end_s": 105.0},
                "roi_table": ["v_Fzg_kmph", [1323.0, 794.0, 855.0, 388.0], "integer", 1.2],
            }
        }
    }
    cfg = fn(doc, vid_duration=105.0)
    assert len(cfg["rois"]) == 1
    roi = cfg["rois"][0]
    assert roi["name"] == "v_Fzg_kmph"
    assert roi["x"] == 1323.0
    assert roi["h"] == 388.0
    assert roi["fmt"] == "integer"
