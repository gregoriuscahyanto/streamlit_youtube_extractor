# -*- coding: utf-8 -*-
"""RTK/pytest tests for audio_validation.py."""

import io
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.io as sio

from audio_validation import (
    build_validation_figure,
    dataframe_from_mat_bytes,
    dataframe_from_upload,
    find_best_shift,
    mat_collect_numeric_arrays,
    validation_metrics,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_sine_rpm(n=200, fs=10.0, offset_s=0.0, noise=0.0, rng=None):
    """Return (t, rpm) arrays: 1 Hz sine on top of 3000 RPM baseline."""
    rng = rng or np.random.default_rng(0)
    t = np.linspace(0, n / fs, n) + offset_s
    rpm = 3000.0 + 500.0 * np.sin(2 * np.pi * 0.25 * t)
    if noise > 0:
        rpm = rpm + rng.normal(0, noise, size=n)
    return t, rpm


def _flat_mat_bytes(arrays: dict) -> bytes:
    """Create a MAT v5 bytes with top-level numeric arrays."""
    buf = io.BytesIO()
    sio.savemat(buf, {k: v for k, v in arrays.items()})
    return buf.getvalue()


def _nested_mat_bytes() -> bytes:
    """Create a MAT v5 bytes with recordResult.audio_rpm.processed struct."""
    t, rpm = _make_sine_rpm()
    struct = {
        "recordResult": {
            "audio_rpm": {
                "processed": {
                    "t_s": t,
                    "rpm": rpm,
                    "freq_hz": rpm / 60.0,
                }
            }
        }
    }
    buf = io.BytesIO()
    sio.savemat(buf, struct)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# mat_collect_numeric_arrays
# ---------------------------------------------------------------------------

class TestMatCollect(unittest.TestCase):
    def test_flat_dict(self):
        t = np.linspace(0, 10, 100)
        rpm = np.ones(100) * 4000.0
        cols = mat_collect_numeric_arrays({"t": t, "__header__": "x", "rpm": rpm})
        self.assertIn("t", cols)
        self.assertIn("rpm", cols)
        self.assertNotIn("__header__", cols)

    def test_nested_mat_struct(self):
        raw = _nested_mat_bytes()
        df = dataframe_from_mat_bytes(raw)
        self.assertFalse(df.empty, "DataFrame should not be empty for nested MAT")
        # At least t_s and rpm should appear somewhere
        col_set = set(df.columns)
        has_t = any("t_s" in c or "t" == c.split(".")[-1] for c in col_set)
        has_rpm = any("rpm" in c.lower() for c in col_set)
        self.assertTrue(has_t, f"Expected t_s column, got: {list(col_set)}")
        self.assertTrue(has_rpm, f"Expected rpm column, got: {list(col_set)}")

    def test_flat_mat_bytes(self):
        t, rpm = _make_sine_rpm(n=50)
        raw = _flat_mat_bytes({"t": t, "rpm": rpm})
        df = dataframe_from_mat_bytes(raw)
        self.assertFalse(df.empty)
        self.assertIn("t", df.columns)
        self.assertIn("rpm", df.columns)
        self.assertEqual(len(df), 50)

    def test_returns_empty_on_bad_bytes(self):
        df = dataframe_from_mat_bytes(b"not a mat file")
        self.assertTrue(df.empty)

    def test_depth_limit_no_infinite_loop(self):
        # construct a deeply nested dict that would loop without depth limit
        d: dict = {"x": np.ones(5)}
        for _ in range(20):
            d = {"nested": d}
        cols = mat_collect_numeric_arrays(d)
        # should not crash regardless of depth
        self.assertIsInstance(cols, dict)


# ---------------------------------------------------------------------------
# dataframe_from_upload
# ---------------------------------------------------------------------------

class TestDataframeFromUpload(unittest.TestCase):
    def test_csv_upload(self):
        csv = b"time,rpm\n0.0,3000\n1.0,3500\n2.0,4000\n"
        df = dataframe_from_upload(csv, "test.csv")
        self.assertFalse(df.empty)
        self.assertIn("time", df.columns)

    def test_xlsx_upload(self):
        buf = io.BytesIO()
        pd.DataFrame({"zeit": [0.0, 1.0], "rpm": [3000.0, 4000.0]}).to_excel(buf, index=False)
        df = dataframe_from_upload(buf.getvalue(), "test.xlsx")
        self.assertFalse(df.empty)
        self.assertIn("rpm", df.columns)

    def test_mat_upload_flat(self):
        t, rpm = _make_sine_rpm(n=30)
        raw = _flat_mat_bytes({"t": t, "rpm": rpm})
        df = dataframe_from_upload(raw, "test.mat")
        self.assertFalse(df.empty)

    def test_mat_upload_nested(self):
        raw = _nested_mat_bytes()
        df = dataframe_from_upload(raw, "test.mat")
        self.assertFalse(df.empty, "Nested MAT upload should yield non-empty DataFrame")

    def test_unknown_extension_returns_empty(self):
        df = dataframe_from_upload(b"data", "file.bin")
        self.assertTrue(df.empty)


# ---------------------------------------------------------------------------
# validation_metrics
# ---------------------------------------------------------------------------

class TestValidationMetrics(unittest.TestCase):
    def setUp(self):
        self.t, self.rpm = _make_sine_rpm(n=300, fs=10.0)

    def test_perfect_match(self):
        r = validation_metrics(self.t, self.rpm, self.t, self.rpm)
        self.assertTrue(r["ok"])
        self.assertAlmostEqual(r["mae"], 0.0, places=6)
        self.assertAlmostEqual(r["sum_abs_err"], 0.0, places=4)

    def test_known_offset_detected(self):
        # reference is offset by +100 RPM – MAE should be ~100
        r = validation_metrics(self.t, self.rpm, self.t, self.rpm + 100.0)
        self.assertTrue(r["ok"])
        self.assertAlmostEqual(r["mae"], 100.0, delta=1.0)

    def test_shift_applied(self):
        # shift reference back 1 s so it aligns with audio
        t_ref = self.t - 1.0          # ref is 1 s early
        r = validation_metrics(self.t, self.rpm, t_ref, self.rpm, shift_s=1.0)
        self.assertTrue(r["ok"])
        self.assertLess(r["mae"], 5.0)  # near-perfect after shift

    def test_no_overlap_returns_error(self):
        t_far = self.t + 10000.0
        r = validation_metrics(self.t, self.rpm, t_far, self.rpm)
        self.assertFalse(r["ok"])
        self.assertIn("error", r)

    def test_empty_input(self):
        r = validation_metrics([], [], [], [])
        self.assertFalse(r["ok"])

    def test_sum_abs_err_present(self):
        r = validation_metrics(self.t, self.rpm, self.t, self.rpm + 50.0)
        self.assertIn("sum_abs_err", r)
        self.assertGreater(r["sum_abs_err"], 0)

    def test_rmse_present(self):
        r = validation_metrics(self.t, self.rpm, self.t, self.rpm)
        self.assertIn("rmse", r)
        self.assertAlmostEqual(r["rmse"], 0.0, places=5)

    def test_percentage_mode(self):
        r = validation_metrics(self.t, self.rpm, self.t, self.rpm * 1.1, mode="Prozentual")
        self.assertTrue(r["ok"])
        # ~10 % offset → mape should be ~10
        self.assertAlmostEqual(r["mape_pct"], 10.0, delta=2.0)


# ---------------------------------------------------------------------------
# find_best_shift
# ---------------------------------------------------------------------------

class TestFindBestShift(unittest.TestCase):
    def test_finds_zero_shift_for_aligned(self):
        t, rpm = _make_sine_rpm(n=200, fs=5.0)
        best, log = find_best_shift(t, rpm, t, rpm, min_s=-1.0, max_s=1.0, step_s=0.1)
        self.assertTrue(best["ok"])
        self.assertAlmostEqual(best["shift_s"], 0.0, delta=0.15)
        self.assertAlmostEqual(best["mae"], 0.0, delta=1.0)

    def test_finds_correct_shift(self):
        t, rpm = _make_sine_rpm(n=200, fs=5.0)
        # ref is 1 s late → best shift should be −1 s (shift ref forward by 1 s)
        t_ref = t + 1.0
        best, log = find_best_shift(t, rpm, t_ref, rpm, min_s=-2.0, max_s=2.0, step_s=0.1)
        self.assertTrue(best["ok"])
        self.assertAlmostEqual(best["shift_s"], -1.0, delta=0.15)

    def test_minimises_sum_abs_err(self):
        t, rpm = _make_sine_rpm(n=100, fs=5.0)
        best, _ = find_best_shift(t, rpm, t, rpm + 200.0, min_s=-0.5, max_s=0.5, step_s=0.1)
        # adding 200 RPM offset → sum_abs_err = mae * n
        self.assertTrue(best["ok"])
        self.assertIn("sum_abs_err", best)

    def test_progress_callback_called(self):
        t, rpm = _make_sine_rpm(n=50, fs=5.0)
        calls: list[float] = []
        find_best_shift(
            t, rpm, t, rpm,
            min_s=-0.2, max_s=0.2, step_s=0.1,
            progress_cb=lambda frac, msg: calls.append(frac),
        )
        self.assertGreater(len(calls), 0)
        self.assertLessEqual(max(calls), 1.0)

    def test_returns_debug_log(self):
        t, rpm = _make_sine_rpm(n=50, fs=5.0)
        _, log = find_best_shift(t, rpm, t, rpm, min_s=-0.1, max_s=0.1, step_s=0.1)
        self.assertIsInstance(log, list)
        self.assertGreater(len(log), 0)

    def test_no_valid_shift_returns_error(self):
        t = np.array([0.0, 1.0, 2.0])
        rpm = np.array([3000.0, 3000.0, 3000.0])
        t_far = t + 10000.0
        best, log = find_best_shift(t, rpm, t_far, rpm, min_s=-1.0, max_s=1.0, step_s=0.5)
        self.assertFalse(best["ok"])


# ---------------------------------------------------------------------------
# build_validation_figure
# ---------------------------------------------------------------------------

class TestBuildValidationFigure(unittest.TestCase):
    def setUp(self):
        self.t, self.rpm = _make_sine_rpm(n=200, fs=10.0)

    def test_returns_figure_for_valid_input(self):
        fig = build_validation_figure(self.t, self.rpm, self.t, self.rpm + 100.0)
        self.assertIsNotNone(fig)

    def test_figure_has_two_rows(self):
        fig = build_validation_figure(self.t, self.rpm, self.t, self.rpm)
        # Plotly subplots: traces assigned to different y-axes
        yaxes = {tr.yaxis for tr in fig.data if hasattr(tr, "yaxis")}
        self.assertGreaterEqual(len(yaxes), 2)

    def test_figure_contains_both_curves(self):
        fig = build_validation_figure(
            self.t, self.rpm, self.t, self.rpm + 50.0,
            label_audio="Audio", label_ref="Messung",
        )
        names = [tr.name for tr in fig.data if tr.name]
        self.assertIn("Audio",   names)
        self.assertIn("Messung", names)

    def test_error_trace_present_on_overlap(self):
        fig = build_validation_figure(self.t, self.rpm, self.t, self.rpm)
        names = [tr.name for tr in fig.data if tr.name]
        self.assertIn("Fehler", names)

    def test_shifted_figure_ok(self):
        t_ref = self.t + 1.0
        fig = build_validation_figure(self.t, self.rpm, t_ref, self.rpm, shift_s=-1.0)
        self.assertIsNotNone(fig)

    def test_no_overlap_returns_figure_without_error_trace(self):
        t_far = self.t + 10000.0
        fig = build_validation_figure(self.t, self.rpm, t_far, self.rpm)
        names = [tr.name for tr in fig.data if tr.name]
        self.assertNotIn("Fehler", names)

    def test_empty_input_returns_figure(self):
        # Should not crash even with empty arrays
        fig = build_validation_figure([], [], [], [])
        self.assertIsNotNone(fig)


if __name__ == "__main__":
    unittest.main()
