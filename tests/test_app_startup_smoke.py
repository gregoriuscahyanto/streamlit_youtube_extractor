import os
import subprocess
import sys
import time
import unittest
from pathlib import Path


class TestAppStartupSmoke(unittest.TestCase):
    @staticmethod
    def _python_has_streamlit(python_exe: str, repo: Path) -> bool:
        try:
            r = subprocess.run(
                [python_exe, "-c", "import streamlit; print(streamlit.__version__)"],
                cwd=str(repo),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )
            return r.returncode == 0
        except Exception:
            return False

    @staticmethod
    def _resolve_python_for_streamlit(repo: Path) -> str | None:
        candidates = [sys.executable]
        venv_py = repo / ".venv" / "Scripts" / "python.exe"
        if venv_py.exists():
            candidates.append(str(venv_py))
        for py in candidates:
            if TestAppStartupSmoke._python_has_streamlit(py, repo):
                return py
        return None

    def test_streamlit_starts_without_parse_or_traceback_errors(self):
        repo = Path(__file__).resolve().parents[1]
        app_path = repo / "app.py"
        self.assertTrue(app_path.exists(), "app.py fehlt")
        python_exe = self._resolve_python_for_streamlit(repo)
        if not python_exe:
            self.skipTest("Kein Python mit installiertem streamlit gefunden.")

        cmd = [
            python_exe,
            "-m",
            "streamlit",
            "run",
            str(app_path),
            "--server.headless",
            "true",
            "--server.port",
            "8773",
            "--logger.level",
            "debug",
        ]

        env = os.environ.copy()
        proc = subprocess.Popen(
            cmd,
            cwd=str(repo),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )

        started = False
        output_lines = []
        deadline = time.time() + 30
        try:
            while time.time() < deadline:
                line = proc.stdout.readline() if proc.stdout is not None else ""
                if line:
                    output_lines.append(line.rstrip("\n"))
                    if "Local URL:" in line:
                        started = True
                        break
                else:
                    if proc.poll() is not None:
                        break
                    time.sleep(0.05)
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
            if proc.stdout is not None:
                proc.stdout.close()

        output = "\n".join(output_lines)
        self.assertTrue(started, f"Streamlit nicht gestartet.\nOutput:\n{output}")
        self.assertNotIn("Traceback", output, f"Traceback beim Start gefunden.\nOutput:\n{output}")
        self.assertNotIn("Failed to parse source", output, f"Parse-Fehler beim Start gefunden.\nOutput:\n{output}")


if __name__ == "__main__":
    unittest.main()
