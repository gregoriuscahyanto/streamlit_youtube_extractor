"""Regression tests for non-monotonic OCR time axes in compare/edit views."""

import json
import math
from pathlib import Path

from app_tabs.compare_tab import _load_file_data
from app_tabs.edit_tab import _interpolate_column


def test_compare_load_sorts_non_monotonic_time_axis():
    """Compare plots must not connect OCR rows in unsorted file order."""
    p = Path("logs") / "pytest_compare_time_order.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        p.write_text(
            json.dumps(
                {
                    "recordResult": {
                        "ocr": {
                            "cleaned": {
                                "time_s": [0.0, 2.0, 1.0],
                                "frame_idx": [1, 21, 11],
                                "v_Fzg_kmph": [100.0, 200.0, 150.0],
                            }
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

        data = _load_file_data(str(p), 0.0)
    finally:
        try:
            p.unlink()
        except OSError:
            pass

    assert data["time_s"] == [0.0, 1.0, 2.0]
    assert data["v_Fzg_kmph"] == [100.0, 150.0, 200.0]
    assert data["frame_idx"] == [1.0, 11.0, 21.0]


def test_edit_interpolation_sorts_unsorted_source_anchors():
    """Linear interpolation must use sorted unique x anchors, not file order."""
    out = _interpolate_column(
        xs=[0.0, 2.0, 1.0],
        ys=[100.0, 200.0, 150.0],
        remove_idx={2},
        method="linear",
    )

    assert math.isclose(out[2], 150.0)
