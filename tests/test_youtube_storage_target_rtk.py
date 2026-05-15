"""RTK checks for YouTube lite target binding and artifact flow."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_tab_uses_global_compressed_db_mode_without_local_selector():
    txt = _read("app_tabs/youtube_tab.py")
    assert "def _lite_target_mode() -> str:" in txt
    assert 'mode = str(st.session_state.get("compressed_db_mode") or "local").strip().lower()' in txt
    assert 'st.session_state.yt_lite_storage_target = mode' in txt
    assert '"Speicherziel für Video-Lite/Audio<1000Hz/JSON-Kopie"' not in txt
    assert "target_label = st.radio(" not in txt


def test_tab_has_local_and_r2_lite_postprocess_paths():
    txt = _read("app_tabs/youtube_tab.py")
    assert "def _local_framepack_1fps(folder: str" in txt
    assert "def _local_audio_proxy_1k(folder: str" in txt
    assert "def _copy_json_to_local_capture(folder: str, json_path: str" in txt
    assert "def _upload_json_copy_to_r2(folder: str, json_path: str) -> tuple[bool, str]:" in txt
    assert "def _postprocess_lite_assets(folder: str, json_path: str" in txt
    assert 'uploader = globals().get("_upload_framepack_1fps")' in txt
    assert 'up_audio = globals().get("_upload_audio_proxy_1k")' in txt
    assert "client.upload_string(payload, cap_key)" in txt
    assert "client.upload_string(payload, res_key)" in txt


def test_tab_table_exposes_lite_target_and_status_columns():
    txt = _read("app_tabs/youtube_tab.py")
    assert '"speicherziel lite/json":' in txt
    assert '"lite status":' in txt
    assert '"lite_target"' in txt
    assert '"lite_status"' in txt
