"""RTK checks: YouTube tab syncs link metadata from local results JSON files."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_youtube_tab_reads_results_json_metadata_for_rows():
    txt = _read("app_tabs/youtube_tab.py")
    assert "def _detect_capture_media(" in txt
    assert "def _resolve_media_path_value(" in txt
    assert "def _rows_from_results_json() -> list[dict]:" in txt
    assert 'res_dir = _capture_base() / "results"' in txt
    assert 'for jp in sorted(res_dir.glob("results_*.json")):' in txt
    assert 'meta.get("url")' in txt
    assert 'meta.get("title")' in txt
    assert 'meta.get("pubDate")' in txt
    assert "has_v, has_a, _fv, _fa = _detect_capture_media(cf, meta)" in txt
    assert '"json_path": str(jp)' in txt


def test_youtube_tab_merges_db_rows_with_results_json_rows():
    txt = _read("app_tabs/youtube_tab.py")
    assert "def _merge_rows_with_results_json(rows: list[dict]) -> tuple[list[dict], bool]:" in txt
    assert "rows, rows_changed = _merge_rows_with_results_json(rows)" in txt
    assert "if rows_changed:" in txt
    assert "_write_db(rows)" in txt
