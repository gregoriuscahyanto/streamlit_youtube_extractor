"""RTK checks for comparison-tab audio channels and derived vehicle dynamics."""

from pathlib import Path
import json
import uuid

import pytest

from app_tabs.compare_tab import (
    _add_compare_derivatives,
    _compute_s_m_from_speed,
    _load_file_data,
)


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_compare_loads_all_audio_processed_channels_from_json():
    tmp_dir = ROOT / "logs" / "rtk_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    path = tmp_dir / f"cmp_audio_{uuid.uuid4().hex}.json"
    path.write_text(
        json.dumps(
            {
                "recordResult": {
                    "audio_rpm": {
                        "processed": {
                            "t_s": [0.0, 1.0],
                            "rpm": [1000.0, 1100.0],
                            "gear": [2, 2],
                            "gear_center_rpm": [980.0, 1080.0],
                            "wheel_power_kw": [10.0, 12.0],
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    cols = _load_file_data(str(path), offset_s=0.5, offset_m=0.0)

    assert cols["time_s"] == [0.5, 1.5]
    assert cols["audio_rpm"] == [1000.0, 1100.0]
    assert cols["audio_gear"] == [2.0, 2.0]
    assert cols["audio_gear_center_rpm"] == [980.0, 1080.0]
    assert cols["audio_wheel_power_kw"] == [10.0, 12.0]
    path.unlink(missing_ok=True)


def test_compare_computes_distance_like_editor_and_wheel_power():
    data = {
        "time_s": [0.0, 1.0, 2.0],
        "v_Fzg_kmph": [36.0, 36.0, 72.0],
    }

    s_m = _compute_s_m_from_speed(data)
    assert s_m == pytest.approx([0.0, 10.0, 30.0])

    ok, missing = _add_compare_derivatives(
        data,
        {
            "enable_wheel_dynamics": True,
            "rho": 1.225,
            "g": 9.81,
            "crr": 0.01,
            "lambda_rot": 1.0,
            "mass_kg": 1500.0,
            "cw": 0.32,
            "area_m2": 2.2,
            "r_dyn_m": 0.34,
        },
    )

    assert ok is True
    assert missing == []
    assert data["s_m"] == pytest.approx([0.0, 10.0, 30.0])
    assert "wheel_power_kw" in data
    assert "wheel_torque_nm" in data
    assert len(data["wheel_force_aero_n"]) == 3
    assert data["wheel_power_kw"][1] > 0.0


def test_compare_derivatives_ui_tokens_exist():
    txt = _read("app_tabs/compare_tab.py")
    assert "Abgeleitete Verlaeufe" in txt
    assert "Radleistung und Raddrehmoment aus Fahrwiderstaenden berechnen" in txt
    assert "Luftdichte rho [kg/m^3]" in txt
    assert "Masse m [kg] (Pflicht)" in txt
    assert "Stirnflaeche A [m^2] (Pflicht)" in txt
    assert "wheel_power_kw" in txt
    assert "wheel_torque_nm" in txt
    assert "_add_compare_derivatives(_cols, _cmp_deriv_cfg)" in txt
