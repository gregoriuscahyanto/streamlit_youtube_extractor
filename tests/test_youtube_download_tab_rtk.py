"""RTK checks for the YouTube download tab and Python-only download path."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_app_registers_youtube_download_tab():
    txt = _read("app.py")
    assert "YouTube Download" in txt
    assert "youtube_tab.render(globals())" in txt


def test_tab_uses_record_youtube_cfr_script_not_ytdlp():
    txt = _read("app_tabs/youtube_tab.py")
    assert 'rec_script = Path("scripts") / "record_youtube_cfr.py"' in txt
    assert "sys.executable" in txt
    assert "record_youtube_cfr.py" in txt
    assert "yt_dlp" not in txt


def test_batch_script_uses_record_youtube_cfr_script():
    txt = _read("scripts/youtube_batch_download.py")
    assert 'rec_script = Path("scripts") / "record_youtube_cfr.py"' in txt
    assert "yt_dlp" not in txt
