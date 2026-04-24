import unittest
from pathlib import Path


class TestAppRuntimeWithAppTest(unittest.TestCase):
    def test_app_and_tabs_run_without_exception(self):
        try:
            from streamlit.testing.v1 import AppTest
        except Exception:
            self.skipTest("streamlit.testing.v1 nicht verfuegbar.")
            return

        repo = Path(__file__).resolve().parents[1]
        at = AppTest.from_file(str(repo / "app.py"))
        at.run(timeout=30)

        self.assertEqual(
            len(at.exception),
            0,
            f"Exception im Initial-Run: {[e.value for e in at.exception]}",
        )

        # Force execution inside each tab once. This catches many runtime crashes
        # that won't appear in a pure startup smoke test.
        expected_tabs = 5
        self.assertEqual(len(at.tabs), expected_tabs, "Unerwartete Anzahl Tabs.")
        for idx in range(expected_tabs):
            at.tabs[idx].run(timeout=30)
            self.assertEqual(
                len(at.exception),
                0,
                f"Exception nach Tab-Run {idx}: {[e.value for e in at.exception]}",
            )


if __name__ == "__main__":
    unittest.main()
