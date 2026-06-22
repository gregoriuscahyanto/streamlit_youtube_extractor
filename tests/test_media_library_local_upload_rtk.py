"""RTK checks for local media import support in the media library."""

import json
import shutil
import tempfile
from pathlib import Path

from local_media_ingest import import_local_media


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_media_tab_exposes_local_import_inputs():
    txt = _read("app_tabs/media_tab.py")
    assert '"Lokales Video aus Pfad"' in txt
    assert '"Separate Audio aus Pfad (optional)"' in txt
    assert '"Datei waehlen"' in txt
    assert '"Audio waehlen"' in txt
    assert "_pick_local_file(" in txt
    assert "st.file_uploader(" not in txt
    assert '"Capture-Ordner"' in txt
    assert 'placeholder="Wird beim Import automatisch aus Datum/Uhrzeit erzeugt"' in txt
    assert 'key="lib_local_capture_folder_display"' in txt
    assert '"Start / Ende (s)"' in txt
    assert ".image(" in txt
    assert '"Filmstreifen"' in txt
    assert "st.columns(4)" in txt
    assert 'with st.expander("Lokaler Import"' in txt
    assert 'getattr(st, "fragment", None)' in txt or 'getattr(st, "experimental_fragment", None)' in txt
    assert "_resolve_local_path_input(" in txt
    assert "disabled=True" in txt
    assert "disabled=_video_source_path is None" in txt
    assert 'st.session_state.pop("lib_local_video_path_pending", "")' in txt
    assert 'st.session_state["lib_local_video_path_pending"] = _picked' in txt
    assert 'st.session_state.pop("lib_local_audio_path_pending", "")' in txt
    assert 'st.session_state["lib_local_audio_path_pending"] = _picked' in txt
    assert '"Videovorschau erscheint nach der Dateiauswahl."' in txt
    assert '"Start-/Ende-Slider wird nach der Dateiauswahl aktiviert."' in txt
    assert '"Vorschau ab (s)"' not in txt
    assert '"Titel ist Pflicht."' in txt
    assert "_title_required" in txt
    assert '"Import-FPS"' in txt
    assert '"10 fps"' in txt
    assert '"2 fps"' in txt
    assert "_local_import_target_fps" in txt
    assert '"GoPro-Kompensation anwenden"' not in txt
    assert "compensate_gopro=" not in txt


def test_media_tab_uses_background_import_and_preview_helpers():
    txt = _read("app_tabs/media_tab.py")
    assert "from local_media_ingest import import_local_media" in txt
    assert "_LOCAL_IMPORT_LOCK" in txt
    assert "_LOCAL_IMPORT" in txt
    assert "_run_local_import_job(" in txt
    assert "Lokaler Import" in txt
    assert "Import-Log" in txt
    assert "_build_frame_preview" in txt
    assert "_read_video_frame" in txt
    assert "_render_preview_fragment" in txt
    assert "_prepare_video_preview_path" in txt
    assert "trim_start_s=" in txt
    assert "trim_end_s=" in txt
    assert "target_fps=" in txt
    assert "mid_count = 4" in txt
    assert "cv2.CAP_PROP_POS_MSEC" in txt
    assert "tkinter" in txt


def test_streamlit_config_allows_large_local_uploads():
    txt = _read(".streamlit/config.toml")
    assert "maxUploadSize = 8192" in txt


def test_local_media_ingest_is_trim_only_without_gopro_compensation():
    txt = _read("local_media_ingest.py")
    assert "def import_local_media(" in txt
    assert "compensate_gopro" not in txt
    assert "_stabilize_gopro_video_2fps" not in txt
    assert "_undistort_wide_frame" not in txt
    assert "cv2.phaseCorrelate" not in txt
    assert '"gopro_compensation"' not in txt
    assert "progress_cb=None" in txt
    assert 'progress_cb("Video wird normalisiert"' in txt
    assert 'progress_cb("Audio wird erzeugt"' in txt
    assert 'progress_cb("Metadaten werden geschrieben"' in txt
    assert "def _trim_input_args(" in txt
    assert "def _trim_duration_args(" in txt
    assert "def _video_filter_args(" in txt
    assert '"-t"' in txt
    assert 'f"fps={fps_txt}"' in txt


class _Upload:
    def __init__(self, name: str, data: bytes):
        self.name = name
        self._data = data

    def getbuffer(self):
        return self._data


def test_local_media_ingest_builds_canonical_video_audio_and_json(monkeypatch):
    calls = []

    def _fake_run_ffmpeg(args):
        calls.append(list(args))
        out_path = Path(args[-1])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"ok")
        return True, ""

    monkeypatch.setattr("local_media_ingest._run_ffmpeg", _fake_run_ffmpeg)
    monkeypatch.setattr("local_media_ingest._probe_video", lambda _p: (25.0, 12.5))

    tmp_root = Path(tempfile.mkdtemp(prefix="rtk_local_upload_", dir=str(ROOT / "logs")))
    try:
        ok, msg, info = import_local_media(
            tmp_root,
            "folder 01",
            _Upload("clip.mp4", b"video"),
            None,
            title="Local Clip",
            trim_start_s=1.25,
            trim_end_s=4.5,
            target_fps=10.0,
        )

        assert ok, msg
        assert info["folder"] == "folder_01"
        assert len(calls) == 2
        assert calls[0][0:4] == ["-y", "-ss", "1.250", "-i"]
        assert calls[1][0:4] == ["-y", "-ss", "1.250", "-i"]
        assert "-t" in calls[0]
        assert "3.250" in calls[0]
        assert "-vf" in calls[0]
        assert "fps=10" in calls[0]

        json_path = tmp_root / "results" / "results_folder_01.json"
        doc = json.loads(json_path.read_text(encoding="utf-8"))
        meta = doc["recordResult"]["metadata"]
        assert meta["title"] == "Local Clip"
        assert meta["source"] == "local_upload"
        assert meta["video"] == "screen_folder_01_video.avi"
        assert meta["audio"].endswith("screen_folder_01_audio.wav")
        assert meta["trim_start_s"] == 1.25
        assert meta["trim_end_s"] == 4.5
        assert meta["import_target_fps"] == 10.0
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)
