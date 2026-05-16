"""RTK checks: YouTube tab no longer depends on Lite sync/postprocess."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_tab_does_not_expose_lite_target_selector_or_state():
    txt = _read("app_tabs/youtube_tab.py")
    assert "def _lite_target_mode() -> str:" not in txt
    assert "yt_lite_storage_target" not in txt
    assert "compressed_db_mode" not in txt


def test_tab_does_not_have_lite_postprocess_pipeline():
    txt = _read("app_tabs/youtube_tab.py")
    assert "def _local_framepack_1fps(folder: str" not in txt
    assert "def _local_audio_proxy_1k(folder: str" not in txt
    assert "def _copy_json_to_local_capture(folder: str, json_path: str" not in txt
    assert "def _upload_json_copy_to_r2(folder: str, json_path: str) -> tuple[bool, str]:" not in txt
    assert "def _postprocess_lite_assets(folder: str, json_path: str" not in txt


def test_tab_table_does_not_show_lite_columns():
    txt = _read("app_tabs/youtube_tab.py")
    assert '"speicherziel lite/json":' not in txt
    assert '"lite status":' not in txt
    assert '"lite_target"' not in txt
    assert '"lite_status"' not in txt
