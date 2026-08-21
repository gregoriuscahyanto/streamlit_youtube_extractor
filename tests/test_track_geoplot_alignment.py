import numpy as np

from app_tabs.track_geoplot import align_traces_to_centerline, snap_trace_to_centerline


def test_snap_trace_projects_to_segments_and_progress_is_monotonic():
    centerline = [
        [0.0, 0.0],
        [100.0, 0.0],
        [100.0, 100.0],
        [0.0, 100.0],
        [0.0, 0.0],
    ]
    xs = [5.0, 25.0, 50.0, 75.0, 98.0, 102.0, 101.0]
    ys = [3.0, -2.0, 4.0, -3.0, 1.0, 20.0, 45.0]

    snapped = snap_trace_to_centerline(xs, ys, centerline)

    assert snapped is not None
    sx = np.asarray(snapped["xs"], dtype=float)
    sy = np.asarray(snapped["ys"], dtype=float)
    progress = np.asarray(snapped["s_progress"], dtype=float)

    # First five samples belong to the horizontal bottom segment.
    assert np.allclose(sy[:5], 0.0, atol=1e-9)
    # Last samples belong to the vertical right segment.
    assert np.allclose(sx[-2:], 100.0, atol=1e-9)
    # Progress used for coverage/direction checks must never move backwards.
    assert np.all(np.diff(progress) >= -1e-12)


def test_align_traces_uses_identical_canonical_xy_grid():
    centerline = [
        [0.0, 0.0],
        [100.0, 0.0],
        [100.0, 100.0],
        [0.0, 100.0],
        [0.0, 0.0],
    ]

    trace_a = {
        "name": "car-a",
        "xs": [2.0, 25.0, 50.0, 75.0, 99.0, 101.0, 100.0, 80.0],
        "ys": [2.0, -2.0, 3.0, -2.0, 1.0, 30.0, 70.0, 99.0],
        "cs": [100.0, 110.0, 120.0, 130.0, 125.0, 115.0, 105.0, 95.0],
        "ps": np.linspace(0.0, 2500.0, 20).tolist(),
        "centerline": centerline,
    }
    trace_b = {
        "name": "car-b",
        "xs": [-3.0, 22.0, 52.0, 78.0, 103.0, 97.0, 96.0, 77.0],
        "ys": [-4.0, 4.0, -3.0, 5.0, 3.0, 28.0, 72.0, 104.0],
        "cs": [98.0, 108.0, 118.0, 128.0, 123.0, 113.0, 103.0, 93.0],
        "ps": np.linspace(0.0, 2520.0, 20).tolist(),
        "centerline": centerline,
    }

    aligned = align_traces_to_centerline([trace_a, trace_b], grid_step_m=5.0)

    assert len(aligned) == 2
    assert aligned[0]["snap_s_label"] == "s_m"
    assert aligned[1]["snap_s_label"] == "s_m"
    assert aligned[0]["snap_grid_step_m"] == 5.0
    assert aligned[1]["snap_grid_step_m"] == 5.0

    # The important comparison invariant: both vehicles are rendered on exactly
    # the same canonical coordinates instead of their individual detected XYs.
    assert np.allclose(aligned[0]["xs"], aligned[1]["xs"], equal_nan=True)
    assert np.allclose(aligned[0]["ys"], aligned[1]["ys"], equal_nan=True)
    assert np.allclose(aligned[0]["snap_s"], aligned[1]["snap_s"], equal_nan=True)


def test_alignment_falls_back_cleanly_without_centerline():
    traces = [
        {"name": "a", "xs": [0.0, 1.0], "ys": [0.0, 1.0], "cs": [1.0, 2.0]},
        {"name": "b", "xs": [0.0, 1.0], "ys": [1.0, 2.0], "cs": [2.0, 3.0]},
    ]

    aligned = align_traces_to_centerline(traces, grid_step_m=5.0)

    assert aligned == traces
