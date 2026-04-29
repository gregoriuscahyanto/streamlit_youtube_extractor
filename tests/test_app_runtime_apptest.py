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

        # The app intentionally avoids st.tabs because Streamlit renders every
        # tab body on each rerun. Force each active area once through the
        # segmented navigation.
        self.assertEqual(len(at.button_group), 1, "Hauptnavigation fehlt.")
        self.assertEqual(
            list(at.button_group[0].options),
            [
                "Cloud Connection & Root",
                "Sync",
                "MAT Selection",
                "ROI Setup",
                "Audio Auswertung",
            ],
        )
        for idx, label in enumerate(at.button_group[0].options):
            at.button_group[0].set_value(label).run(timeout=30)
            self.assertEqual(
                len(at.exception),
                0,
                f"Exception nach Bereich-Run {idx} ({label}): {[e.value for e in at.exception]}",
            )


if __name__ == "__main__":
    unittest.main()
