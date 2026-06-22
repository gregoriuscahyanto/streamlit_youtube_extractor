"""RTK checks for UTF-8 UI labels and robust YouTube metadata propagation."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_recorder_supports_metadata_only_mode_and_meta_json_line():
    txt = _read("scripts/record_youtube_cfr.py")
    assert '--metadata-only' in txt
    assert "def emit_result_metadata(" in txt
    assert "RESULT_META_JSON:" in txt
    assert "if bool(args.metadata_only):" in txt


def test_tab_fetches_url_metadata_via_recorder_and_uses_fallback_values():
    txt = _read("app_tabs/youtube_tab.py")
    assert "def _fetch_metadata_for_url(" in txt
    assert '"--metadata-only"' in txt
    assert "meta_url = _fetch_metadata_for_url(url)" in txt
    assert "meta_url_init = _fetch_metadata_for_url(url)" in txt
    assert 'meta.get("RESULT_TITLE") or meta_url.get("title")' in txt
    assert 'meta.get("RESULT_PUBDATE") or meta_url.get("pubDate")' in txt
    assert 'meta.get("RESULT_DESC") or meta_url.get("desc")' in txt
    assert 'meta.get("RESULT_CHANNAME") or meta_url.get("chanName")' in txt


def test_tab_parses_result_meta_json_and_continuations():
    txt = _read("app_tabs/youtube_tab.py")
    assert 'if key == "RESULT_META_JSON":' in txt
    assert 'pending_key = key if key in {"RESULT_DESC", "RESULT_TITLE", "RESULT_PUBDATE", "RESULT_CHANNAME"} else ""' in txt
    assert 'out[pending_key] = str(out.get(pending_key) or "") + "\\n" + t' in txt


def test_no_mojibake_label_remains_for_delete_button():
    txt = _read("app_tabs/youtube_tab.py")
    assert "Ausgewählte löschen" in txt
    bad_label = "Ausgew" + chr(0x00C3) + chr(0x00A4) + "hlte l" + chr(0x00C3) + chr(0x00B6) + "schen"
    assert bad_label not in txt
