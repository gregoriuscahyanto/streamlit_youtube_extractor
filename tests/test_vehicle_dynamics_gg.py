"""Regression tests for OCR/GPS-based G-G dynamics."""

import math

import pytest

from core.vehicle_dynamics import add_gg_dynamics


def test_add_gg_dynamics_computes_gx_from_constant_acceleration():
    data = {
        "time_s": [0.0, 1.0, 2.0, 3.0],
        "v_Fzg_kmph": [0.0, 36.0, 72.0, 108.0],
        "x_m": [0.0, 10.0, 30.0, 60.0],
        "y_m": [0.0, 0.0, 0.0, 0.0],
    }

    ok, missing = add_gg_dynamics(data, {"enable_gg_dynamics": True, "gg_smooth_window": 1})

    assert ok is True
    assert missing == []
    assert data["gx_g"] == pytest.approx([10.0 / 9.81] * 4)
    assert data["gy_g"] == pytest.approx([0.0, 0.0, 0.0, 0.0], abs=1e-9)


def test_add_gg_dynamics_computes_gy_from_meter_circle():
    r_m = 50.0
    v_kmph = 72.0
    points = []
    for i in range(13):
        a = i * (math.pi / 24.0)
        points.append((r_m * math.cos(a), r_m * math.sin(a)))
    data = {
        "time_s": list(range(len(points))),
        "v_Fzg_kmph": [v_kmph] * len(points),
        "x_m": [p[0] for p in points],
        "y_m": [p[1] for p in points],
    }

    ok, missing = add_gg_dynamics(data, {"enable_gg_dynamics": True, "gg_smooth_window": 1})

    assert ok is True
    assert missing == []
    mid = len(points) // 2
    expected = (20.0 * 20.0 / r_m) / 9.81
    assert data["gy_g"][mid] == pytest.approx(expected, rel=0.04)
    assert data["curvature_1pm"][mid] == pytest.approx(1.0 / r_m, rel=0.04)


def test_add_gg_dynamics_falls_back_to_track_xy_scale():
    data = {
        "time_s": [0.0, 1.0, 2.0],
        "v_Fzg_kmph": [36.0, 36.0, 36.0],
        "track_xy_x": [0.0, 10.0, 20.0],
        "track_xy_y": [0.0, 0.0, 0.0],
    }

    ok, missing = add_gg_dynamics(
        data,
        {"enable_gg_dynamics": True, "gg_source": "track_xy", "gg_m_per_px": 2.0, "gg_smooth_window": 1},
    )

    assert ok is True
    assert missing == []
    assert data["track_x_m"] == pytest.approx([0.0, 20.0, 40.0])
    assert data["track_y_m"] == pytest.approx([0.0, 0.0, 0.0])


def test_add_gg_dynamics_projects_lat_lon_to_local_meters():
    data = {
        "time_s": [0.0, 1.0, 2.0],
        "v_Fzg_kmph": [36.0, 36.0, 36.0],
        "lat": [50.0, 50.0, 50.0],
        "lon": [7.0, 7.0001, 7.0002],
    }

    ok, missing = add_gg_dynamics(data, {"enable_gg_dynamics": True, "gg_smooth_window": 1})

    assert ok is True
    assert missing == []
    assert data["track_x_m"][0] == pytest.approx(0.0)
    assert data["track_x_m"][2] > data["track_x_m"][1] > 0.0
    assert max(abs(v) for v in data["track_y_m"]) < 1e-6

