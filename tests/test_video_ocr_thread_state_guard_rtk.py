"""RTK checks: video OCR path guards session_state access for local DB flags."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_local_helpers_use_session_get_for_thread_safe_access():
    txt = _read("app.py")
    assert "def _get_local_capture_folders() -> list[str]:" in txt
    assert 'client = st.session_state.get("local_client")' in txt
    assert 'bool(st.session_state.get("local_connected"))' in txt
    assert "def _local_capture_folder_path(folder: str) -> Path | None:" in txt
    assert 'base = Path(str(st.session_state.get("local_base_path") or "")).expanduser().resolve()' in txt
