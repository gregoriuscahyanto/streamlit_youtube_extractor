import ast
import io
import json
import os
import tempfile
from pathlib import Path
from pathlib import PurePosixPath
from datetime import datetime

import numpy as np
import scipy.io as sio
import concurrent.futures as cf


def _load_app_functions(names: set[str]):
    repo = Path(__file__).resolve().parents[1]
    source = (repo / "app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    namespace = {
        "json": json,
        "np": np,
        "sio": sio,
        "Path": Path,
        "PurePosixPath": PurePosixPath,
        "datetime": datetime,
        "tempfile": tempfile,
        "cf": cf,
        "os": os,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(repo / "app.py"), "exec"), namespace)
    return namespace


def _mat_bytes(payload: dict) -> bytes:
    buf = io.BytesIO()
    sio.savemat(buf, payload, do_compression=True)
    return buf.getvalue()


class _MemR2Client:
    def __init__(self, objects: dict[str, bytes]):
        self.objects = dict(objects)

    def list_files(self, prefix: str):
        p = str(prefix).strip("/")
        out = []
        for key in sorted(self.objects):
            key_clean = str(key).strip("/")
            if not key_clean.startswith(p + "/"):
                continue
            tail = key_clean[len(p) + 1 :]
            if "/" in tail:
                continue
            out.append(tail)
        return True, out

    def download_file(self, key: str, target_path: str):
        k = str(key).strip("/")
        if k not in self.objects:
            return False, "not found"
        Path(target_path).write_bytes(self.objects[k])
        return True, ""

    def upload_bytes(self, data: bytes, key: str, content_type: str = ""):
        self.objects[str(key).strip("/")] = bytes(data)
        return True, ""


def test_json_sidecar_update_replaces_only_selected_fields_and_merges_metadata():
    ns = _load_app_functions(
        {
            "_mat_scalar",
            "_mat_export_to_jsonable",
            "_load_json_doc_from_bytes",
            "_deep_merge_missing_json",
            "_deep_replace_json",
            "_build_json_sidecar_bytes_preserving_fields",
        }
    )

    existing_doc = {
        "recordResult": {
            "ocr": {"params": {"start_s": 1.0}},
            "audio_config": {"nfft": 1024},
            "metadata": {"title": "Old Title", "youtube_url": "https://example", "keep": True},
        }
    }
    replace_fields = {
        "audio_config": {"nfft": 4096},
        "metadata": {"title": "New Title", "location": "Nuerburgring"},
    }

    out = ns["_build_json_sidecar_bytes_preserving_fields"](
        existing_doc=existing_doc,
        replace_fields=replace_fields,
        extra_rr_fields=None,
        fallback_json_bytes=None,
    )
    parsed = json.loads(out.decode("utf-8"))
    rr = parsed["recordResult"]

    assert rr["ocr"]["params"]["start_s"] == 1.0
    assert rr["audio_config"]["nfft"] == 4096
    assert rr["metadata"]["title"] == "New Title"
    assert rr["metadata"]["youtube_url"] == "https://example"
    assert rr["metadata"]["keep"] is True
    assert rr["metadata"]["location"] == "Nuerburgring"


def test_bulk_mat_to_json_sidecar_converts_all_missing_files():
    ns = _load_app_functions(
        {
            "_mat_scalar",
            "_mat_export_to_jsonable",
            "_r2_json_sidecar_key",
            "_normalize_sidecar_json_payload",
            "_mat_bytes_to_recordresult_json_bytes",
            "_bulk_convert_missing_mat_sidecars",
        }
    )
    ns["_results_dir_key"] = lambda: "results"

    client = _MemR2Client(
        {
            "results/a.mat": _mat_bytes({"recordResult": {"metadata": {"title": "A"}}}),
            "results/b.mat": _mat_bytes({"recordResult": {"metadata": {"title": "B"}}}),
            "results/c.mat": _mat_bytes({"recordResult": {"metadata": {"title": "C"}}}),
            "results/b.json": json.dumps({"recordResult": {"metadata": {"title": "B-JSON"}}}).encode("utf-8"),
        }
    )
    targets = [
        {"mat_key": "results/a.mat"},
        {"mat_key": "results/b.mat"},
        {"mat_key": "results/c.mat"},
    ]

    created = ns["_bulk_convert_missing_mat_sidecars"](targets, client, max_workers=2)

    assert created == 2
    assert "results/a.json" in client.objects
    assert "results/c.json" in client.objects
    assert json.loads(client.objects["results/b.json"].decode("utf-8"))["recordResult"]["metadata"]["title"] == "B-JSON"


def test_recordresult_sidecar_builder_is_canonical_and_mcos_free():
    ns = _load_app_functions(
        {
            "_mat_scalar",
            "_mat_export_to_jsonable",
            "_normalize_sidecar_json_payload",
            "_mat_bytes_to_recordresult_json_bytes",
        }
    )
    raw = _mat_bytes(
        {
            "recordResult": {
                "metadata": {"title": "Demo"},
                "audio_config": {"nfft": 4096},
            },
            "other_var": np.array([1, 2, 3], dtype=np.int16),
        }
    )
    out = ns["_mat_bytes_to_recordresult_json_bytes"](raw)
    assert isinstance(out, (bytes, bytearray))
    payload = json.loads(out.decode("utf-8"))
    assert list(payload.keys()) == ["recordResult"]
    txt = out.decode("utf-8")
    assert "\"s0\"" not in txt
    assert "\"s1\"" not in txt
    assert "\"s2\"" not in txt
    assert "\"arr\"" not in txt


def test_sidecar_payload_normalizer_strips_mcos_wrappers():
    ns = _load_app_functions({"_normalize_sidecar_json_payload"})
    payload = {
        "recordResult": {
            "metadata": {
                "title": "X",
                "video": {"s0": "", "s1": "MCOS", "s2": "string", "arr": [1, 2]},
                "created_at": {"s0": "", "s1": "MCOS", "s2": "datetime", "arr": [1, 2]},
            },
            "ocr": {
                "table": {"s0": "", "s1": "MCOS", "s2": "table", "arr": [1, 2]},
            },
            "validation": {"results": {"comparison_accuracy_v": float("nan")}},
        }
    }
    out = ns["_normalize_sidecar_json_payload"](payload)
    assert out["recordResult"]["metadata"]["video"] == ""
    assert out["recordResult"]["metadata"]["created_at"] == ""
    assert out["recordResult"]["ocr"]["table"] == []
    assert out["recordResult"]["validation"]["results"]["comparison_accuracy_v"] is None
