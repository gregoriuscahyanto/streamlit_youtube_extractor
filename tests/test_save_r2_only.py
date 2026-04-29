# -*- coding: utf-8 -*-
"""Tests for R2-only save helpers (no Streamlit dependency)."""

import io
import unittest

import numpy as np
import scipy.io as sio

from save_helpers import (
    build_merged_mat_json,
    build_merged_mat_json_fields,
    field_exists_in_rr,
    rr_from_mat_bytes,
)


def _simple_mat_bytes(extra_rr: dict | None = None) -> bytes:
    """Create a minimal recordResult MAT v5 bytes."""
    rr: dict = {"metadata": {"title": "Test"}}
    if extra_rr:
        rr.update(extra_rr)
    buf = io.BytesIO()
    sio.savemat(buf, {"recordResult": rr})
    return buf.getvalue()


class TestFieldExistsInRr(unittest.TestCase):
    def test_field_not_present(self):
        raw = _simple_mat_bytes()
        self.assertFalse(field_exists_in_rr(raw, "audio_config"))

    def test_field_present(self):
        raw = _simple_mat_bytes({"audio_config": {"nfft": 8192.0}})
        self.assertTrue(field_exists_in_rr(raw, "audio_config"))

    def test_audio_rpm_present(self):
        raw = _simple_mat_bytes({"audio_rpm": {"processed": {"t_s": np.array([0.0, 1.0])}}})
        self.assertTrue(field_exists_in_rr(raw, "audio_rpm"))

    def test_returns_false_on_empty_bytes(self):
        self.assertFalse(field_exists_in_rr(b"", "audio_config"))

    def test_returns_false_on_corrupt_bytes(self):
        self.assertFalse(field_exists_in_rr(b"not a mat file xyz", "audio_config"))


class TestRrFromMatBytes(unittest.TestCase):
    def test_extracts_rr_dict(self):
        raw = _simple_mat_bytes({"audio_config": {"nfft": 8192.0}})
        rr, extra = rr_from_mat_bytes(raw)
        self.assertIsInstance(rr, dict)
        self.assertIn("audio_config", rr)

    def test_extra_top_level_keys_excluded(self):
        buf = io.BytesIO()
        sio.savemat(buf, {"recordResult": {"metadata": {"title": "T"}}, "other_var": 42.0})
        raw = buf.getvalue()
        rr, extra = rr_from_mat_bytes(raw)
        self.assertIn("other_var", extra)
        self.assertNotIn("other_var", rr)

    def test_returns_empty_dict_on_corrupt(self):
        rr, extra = rr_from_mat_bytes(b"corrupt")
        self.assertIsInstance(rr, dict)
        self.assertIsInstance(extra, dict)


class TestBuildMergedMatJson(unittest.TestCase):
    def test_adds_new_field(self):
        raw = _simple_mat_bytes()
        new_data = {"nfft": 8192, "method": "Hybrid"}
        mat_bytes, json_bytes = build_merged_mat_json(raw, "audio_config", new_data)
        self.assertIsInstance(mat_bytes, bytes)
        self.assertGreater(len(mat_bytes), 0)
        self.assertIsInstance(json_bytes, bytes)
        self.assertGreater(len(json_bytes), 0)

    def test_overwrites_existing_field(self):
        import json
        raw = _simple_mat_bytes({"audio_config": {"nfft": 512.0}})
        new_data = {"nfft": 8192}
        mat_bytes, json_bytes = build_merged_mat_json(raw, "audio_config", new_data)
        # Check JSON contains new value
        payload = json.loads(json_bytes.decode("utf-8"))
        rr = payload.get("recordResult", {})
        cfg = rr.get("audio_config", {})
        self.assertEqual(cfg.get("nfft"), 8192)

    def test_mat_and_json_have_same_structure(self):
        import json
        raw = _simple_mat_bytes()
        mat_bytes, json_bytes = build_merged_mat_json(raw, "audio_config", {"nfft": 4096})
        # Load back MAT and compare with JSON
        mat_data = sio.loadmat(io.BytesIO(mat_bytes), squeeze_me=True, struct_as_record=False)
        json_data = json.loads(json_bytes.decode("utf-8"))
        # Both should have recordResult
        self.assertIn("recordResult", json_data)
        rr_mat = mat_data.get("recordResult")
        self.assertIsNotNone(rr_mat)

    def test_fallback_when_source_is_empty(self):
        mat_bytes, json_bytes = build_merged_mat_json(b"", "audio_config", {"nfft": 8192})
        self.assertIsInstance(mat_bytes, bytes)
        self.assertIsInstance(json_bytes, bytes)

    def test_json_is_valid_utf8(self):
        raw = _simple_mat_bytes({"metadata": {"title": "Nürburgring Runde"}})
        _, json_bytes = build_merged_mat_json(raw, "audio_config", {"src": "test"})
        decoded = json_bytes.decode("utf-8")
        self.assertIn("recordResult", decoded)

    def test_multi_field_update_preserves_unrelated_sections(self):
        import json
        raw = _simple_mat_bytes({
            "ocr": {"params": {"start_s": 1.0}, "roi_table": ["old"]},
            "audio_config": {"nfft": 4096.0},
            "audio_rpm": {"processed": {"rpm": np.array([1000.0])}},
            "validation": {"results": {"ok": True}},
        })
        _mat_bytes, json_bytes = build_merged_mat_json_fields(
            raw,
            {
                "ocr": {"params": {"start_s": 2.0}, "roi_table": ["new"]},
                "metadata": {"video_faulty": True},
            },
        )
        rr = json.loads(json_bytes.decode("utf-8"))["recordResult"]
        self.assertEqual(rr["ocr"]["params"]["start_s"], 2.0)
        self.assertTrue(rr["metadata"]["video_faulty"])
        self.assertEqual(rr["metadata"]["title"], "Test")
        self.assertIn("audio_config", rr)
        self.assertIn("audio_rpm", rr)
        self.assertIn("validation", rr)


if __name__ == "__main__":
    unittest.main()
