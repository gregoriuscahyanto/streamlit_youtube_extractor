import unittest

from roi_utils import (
    can_add_roi_from_drag,
    clamp_roi_to_video,
    normalize_time_range,
    roi_from_crop_box,
    seed_drag_roi,
)


class TestRoiUtils(unittest.TestCase):
    def test_clamp_basic(self):
        x, y, w, h = clamp_roi_to_video(10, 20, 300, 100, 1920, 1080)
        self.assertEqual((x, y, w, h), (10.0, 20.0, 300.0, 100.0))

    def test_clamp_outside_bounds(self):
        x, y, w, h = clamp_roi_to_video(-20, -10, 5000, 3000, 1920, 1080)
        self.assertEqual(x, 0.0)
        self.assertEqual(y, 0.0)
        self.assertEqual(w, 1920.0)
        self.assertEqual(h, 1080.0)

    def test_crop_box_to_roi(self):
        box = {"left": 50, "top": 40, "width": 200, "height": 120}
        roi = roi_from_crop_box(box, 1920, 1080)
        self.assertEqual(roi, (50.0, 40.0, 200.0, 120.0))

    def test_crop_box_none_if_too_small(self):
        self.assertIsNone(roi_from_crop_box({"left": 0, "top": 0, "width": 0, "height": 10}, 1920, 1080))
        self.assertIsNone(roi_from_crop_box({"left": 0, "top": 0, "width": 10, "height": 0}, 1920, 1080))

    def test_crop_box_accepts_x_y_keys(self):
        box = {"x": 15, "y": 25, "width": 35, "height": 45}
        roi = roi_from_crop_box(box, 1920, 1080)
        self.assertEqual(roi, (15.0, 25.0, 35.0, 45.0))

    def test_can_add_roi_requires_drag_box(self):
        ok, msg = can_add_roi_from_drag(None)
        self.assertFalse(ok)
        self.assertIn("Maus", msg)

        ok, msg = can_add_roi_from_drag({})
        self.assertFalse(ok)
        self.assertIn("Maus", msg)

        ok, msg = can_add_roi_from_drag({"x": 10, "y": 20, "w": 0, "h": 50})
        self.assertFalse(ok)
        self.assertIn("Maus", msg)

        ok, msg = can_add_roi_from_drag({"x": 10, "y": 20, "w": 50, "h": 30})
        self.assertTrue(ok)
        self.assertEqual(msg, "")

    def test_seed_drag_roi_has_minimum_and_center(self):
        d = seed_drag_roi(100, 50)
        self.assertGreaterEqual(d["w"], 32)
        self.assertGreaterEqual(d["h"], 24)
        self.assertGreaterEqual(d["x"], 0)
        self.assertGreaterEqual(d["y"], 0)
        self.assertLessEqual(d["x"] + d["w"], 100)
        self.assertLessEqual(d["y"] + d["h"], 50)

    def test_seed_drag_roi_scales_with_large_video(self):
        d = seed_drag_roi(1920, 1080)
        self.assertEqual(d["w"], int(round(1920 * 0.20)))
        self.assertEqual(d["h"], int(round(1080 * 0.18)))

    def test_normalize_time_range_keeps_start_not_greater_than_end(self):
        s, e = normalize_time_range(start_s=9.0, end_s=2.0, duration_s=10.0, fps=25.0)
        self.assertLess(s, e)
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(e, 10.0)

    def test_normalize_time_range_clamps_to_duration(self):
        s, e = normalize_time_range(start_s=99.0, end_s=999.0, duration_s=12.0, fps=10.0)
        self.assertLess(s, e)
        self.assertLessEqual(e, 12.0)


if __name__ == "__main__":
    unittest.main()
