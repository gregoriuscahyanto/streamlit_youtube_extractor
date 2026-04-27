"""
Tests for MAT file ROI parsing in backend.py.
Covers both numeric-array and string-encoded roi formats, plus edge cases.
"""
import io
import tempfile
import os
import numpy as np
import pytest
import scipy.io as sio

from backend import (
    _parse_roi_coords,
    _atleast_1d_cell,
    config_from_mat_file,
    build_mat_struct,
    mat_bytes_from_result,
    build_result_payload,
)


# ── _parse_roi_coords ──────────────────────────────────────────────────────────

class TestParseRoiCoords:
    def test_numeric_array(self):
        r = np.array([41.0, 52.0, 105.0, 52.0])
        assert _parse_roi_coords(r) == [41.0, 52.0, 105.0, 52.0]

    def test_numeric_list(self):
        assert _parse_roi_coords([321, 28, 306, 70]) == [321.0, 28.0, 306.0, 70.0]

    def test_string_space_separated(self):
        assert _parse_roi_coords("41 52 105 52") == [41.0, 52.0, 105.0, 52.0]

    def test_string_with_extra_spaces(self):
        assert _parse_roi_coords("  321  28  306  70  ") == [321.0, 28.0, 306.0, 70.0]

    def test_string_floats(self):
        result = _parse_roi_coords("10.5 20.0 100.3 50.7")
        assert result is not None
        assert abs(result[0] - 10.5) < 1e-9

    def test_string_numpy_scalar(self):
        # numpy object scalar wrapping a string (happens after loadmat squeeze_me=True)
        r = np.array("41 52 105 52", dtype=object)
        result = _parse_roi_coords(r)
        assert result == [41.0, 52.0, 105.0, 52.0]

    def test_too_short_returns_none(self):
        assert _parse_roi_coords([1, 2, 3]) is None
        assert _parse_roi_coords("1 2 3") is None

    def test_empty_returns_none(self):
        assert _parse_roi_coords("") is None
        assert _parse_roi_coords(np.array([])) is None

    def test_invalid_returns_none(self):
        assert _parse_roi_coords(None) is None

    def test_more_than_4_numbers_takes_first_4(self):
        result = _parse_roi_coords("10 20 30 40 99 88")
        assert result == [10.0, 20.0, 30.0, 40.0]

    def test_negative_coords(self):
        assert _parse_roi_coords("-5 -10 200 100") == [-5.0, -10.0, 200.0, 100.0]


# ── _atleast_1d_cell ───────────────────────────────────────────────────────────

class TestAtleast1dCell:
    def test_object_array_of_strings(self):
        arr = np.array(["a", "b"], dtype=object)
        result = _atleast_1d_cell(arr)
        assert result == ["a", "b"]

    def test_single_string_scalar(self):
        # After squeeze_me=True a 1-element cell becomes a scalar
        result = _atleast_1d_cell("hello")
        assert result == ["hello"]

    def test_single_numeric_roi_array_wrapped(self):
        # 1D float array of size 4 → single ROI, must NOT be split into 4 scalars
        arr = np.array([41.0, 52.0, 105.0, 52.0])
        result = _atleast_1d_cell(arr)
        assert len(result) == 1
        np.testing.assert_array_equal(result[0], arr)

    def test_2d_numeric_array_rows(self):
        arr = np.array([[10, 20, 30, 40], [1, 2, 3, 4]])
        result = _atleast_1d_cell(arr)
        assert len(result) == 2

    def test_object_array_of_float_arrays(self):
        arr = np.empty(2, dtype=object)
        arr[0] = np.array([41, 52, 105, 52])
        arr[1] = np.array([321, 28, 306, 70])
        result = _atleast_1d_cell(arr)
        assert len(result) == 2


# ── config_from_mat_file ───────────────────────────────────────────────────────

def _write_mat(data: dict) -> str:
    """Save data to a temp MAT file and return the path."""
    fd, path = tempfile.mkstemp(suffix=".mat")
    os.close(fd)
    sio.savemat(path, data)
    return path


def _make_mat_data(roi_field, names=None, fmts=None, patterns=None, scales=None,
                   start_s=10.0, end_s=120.0):
    """Build a recordResult struct dict for savemat."""
    n = len(np.atleast_1d(roi_field)) if not isinstance(roi_field, str) else 1
    if names is None:
        names = [f"roi_{i}" for i in range(n)]
    if fmts is None:
        fmts = ["any"] * n
    if patterns is None:
        patterns = [""] * n
    if scales is None:
        scales = [1.2] * n

    return {
        "recordResult": {
            "ocr": {
                "params": {"start_s": np.array(start_s), "end_s": np.array(end_s)},
                "roi_table": {
                    "name_roi": np.array(names, dtype=object),
                    "roi":      roi_field,
                    "fmt":      np.array(fmts, dtype=object),
                    "pattern":  np.array(patterns, dtype=object),
                    "max_scale": np.array(scales, dtype=float),
                },
            },
            "metadata": {"video": "test.mp4"},
        }
    }


class TestConfigFromMatFile:
    def test_string_roi_two_entries(self):
        """roi stored as object array of strings — the MATLAB-table format."""
        roi_field = np.array(["41 52 105 52", "321 28 306 70"], dtype=object)
        path = _write_mat(_make_mat_data(
            roi_field,
            names=["v_Fzg_kmph", "t_s"],
            fmts=["int_min2_max3", "time_hh:mm:ss.S"],
        ))
        try:
            cfg = config_from_mat_file(path, vid_duration=200.0)
        finally:
            os.unlink(path)

        assert len(cfg["rois"]) == 2

        r0 = cfg["rois"][0]
        assert r0["name"] == "v_Fzg_kmph"
        assert r0["x"] == 41.0
        assert r0["y"] == 52.0
        assert r0["w"] == 105.0
        assert r0["h"] == 52.0
        assert r0["fmt"] == "int_min2_max3"

        r1 = cfg["rois"][1]
        assert r1["name"] == "t_s"
        assert r1["x"] == 321.0
        assert r1["fmt"] == "time_hh:mm:ss.S"

        assert cfg["t_start"] == 10.0
        assert cfg["t_end"] == 120.0

    def test_string_roi_reads_pattern_and_scale(self):
        roi_field = np.array(["41 52 105 52", "321 28 306 70"], dtype=object)
        path = _write_mat(_make_mat_data(
            roi_field,
            patterns=["\\d+", ""],
            scales=[1.5, 2.0],
        ))
        try:
            cfg = config_from_mat_file(path)
        finally:
            os.unlink(path)

        assert cfg["rois"][0]["pattern"] == "\\d+"
        assert abs(cfg["rois"][0]["max_scale"] - 1.5) < 1e-9
        assert abs(cfg["rois"][1]["max_scale"] - 2.0) < 1e-9

    def test_numeric_roi_two_entries(self):
        """roi stored as numeric matrix rows — the old struct format."""
        # Each row is one ROI: shape (2, 4)
        roi_field = np.array([[41, 52, 105, 52], [321, 28, 306, 70]], dtype=float)
        path = _write_mat(_make_mat_data(
            roi_field,
            names=["roi_a", "roi_b"],
            fmts=["any", "any"],
        ))
        try:
            cfg = config_from_mat_file(path)
        finally:
            os.unlink(path)

        assert len(cfg["rois"]) == 2
        assert cfg["rois"][0]["x"] == 41.0
        assert cfg["rois"][1]["x"] == 321.0

    def test_roundtrip_via_build_mat_struct(self):
        """MAT files written by build_mat_struct should be read back correctly."""
        result = build_result_payload(
            t_start=5.0,
            t_end=60.0,
            rois=[
                dict(name="speed", x=100, y=200, w=150, h=50,
                     fmt="int_min2_max3", pattern="\\d+", max_scale=1.3),
                dict(name="time",  x=300, y=400, w=200, h=60,
                     fmt="time_hh:mm:ss.S", pattern="", max_scale=1.0),
            ],
            video=dict(width=1920, height=1080, fps=25.0, duration=60.0),
        )
        buf = io.BytesIO()
        sio.savemat(buf, build_mat_struct(result, video_name="test.mp4"))
        buf.seek(0)

        fd, path = tempfile.mkstemp(suffix=".mat")
        os.close(fd)
        try:
            with open(path, "wb") as f:
                f.write(buf.read())
            cfg = config_from_mat_file(path, vid_duration=60.0)
        finally:
            os.unlink(path)

        assert len(cfg["rois"]) == 2
        assert cfg["t_start"] == 5.0
        assert cfg["t_end"] == 60.0

        r0 = cfg["rois"][0]
        assert r0["name"] == "speed"
        assert r0["x"] == 100.0
        assert r0["fmt"] == "int_min2_max3"

    def test_missing_roi_table_returns_empty(self):
        path = _write_mat({
            "recordResult": {
                "ocr": {"params": {"start_s": np.array(0.0), "end_s": np.array(10.0)}},
                "metadata": {"video": ""},
            }
        })
        try:
            cfg = config_from_mat_file(path)
        finally:
            os.unlink(path)
        assert cfg["rois"] == []

    def test_nonexistent_file_returns_empty(self):
        cfg = config_from_mat_file("/nonexistent/path/file.mat")
        assert cfg["rois"] == []
        assert cfg["t_start"] == 0.0
