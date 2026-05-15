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
    assert "--new-window" in txt
    assert "--other-display" in txt
    assert "CREATE_NO_WINDOW" in txt
    assert 'stem = f"screen_{folder}_audio"' in txt


def test_tab_writes_metadata_to_json_not_mat():
    txt = _read("app_tabs/youtube_tab.py")
    assert "def _write_capture_metadata_json" in txt
    assert "def _capture_media_paths" in txt
    assert "def _ensure_audio_file" in txt
    assert 'res_dir = base / "results"' in txt
    assert "JSON-Zielpfad:" in txt
    assert "yt_last_meta_json_path" in txt
    assert '"json path"' in txt
    assert '"json_path" in df.columns' in txt
    assert "JSON gespeichert:" in txt
    assert 'f"results_{folder}.json"' in txt
    assert 'path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")' in txt
    assert '"recordResult"' in txt
    assert '"metadata"' in txt
    assert '"title": title_v' in txt
    assert '"video": video_v' in txt
    assert '"audio": audio_v' in txt
    assert '"url": url_v' in txt
    assert '"created_at"' in txt
    assert '"outdir"' in txt
    assert '"fps"' in txt
    assert '"duration"' in txt
    assert '"pubDate": pub_v' in txt
    assert '"desc": desc_v' in txt
    assert '"chanName": chan_v' in txt
    assert '"youtube_url": url_v' not in txt
    assert '"source_url": url_v' not in txt
    assert '"video_title": title_v' not in txt
    assert '"youtube_title": title_v' not in txt
    assert '"capture_folder": folder' not in txt
    assert '"download_status"' not in txt[txt.index("def _write_capture_metadata_json"):txt.index("def _ensure_audio_file")]
    assert 'audio fehlt:' in txt
    assert "kein echtes Audio gefunden (kein Platzhalter erzeugt)" in txt
    assert ".mat" not in txt[txt.index("def _write_capture_metadata_json"):txt.index("def _status_lamp")]


def test_default_capture_folder_has_no_yt_prefix():
    txt = _read("app_tabs/youtube_tab.py")
    assert 'return datetime.now().strftime("%Y%m%d_%H%M%S")' in txt
    assert "yt_%Y" not in txt


def test_batch_script_uses_record_youtube_cfr_script():
    txt = _read("scripts/youtube_batch_download.py")
    assert 'rec_script = Path("scripts") / "record_youtube_cfr.py"' in txt
    assert "yt_dlp" not in txt
    assert 'stem = f"screen_{folder}_audio"' in txt
