"""Helpers for importing local media into canonical capture folders."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

import cv2


def _ffmpeg_exe() -> str | None:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def _run_ffmpeg(args: list[str]) -> tuple[bool, str]:
    exe = _ffmpeg_exe()
    if not exe:
        return False, "ffmpeg nicht verfuegbar"
    cmd = [exe, *args]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except Exception as exc:
        return False, f"ffmpeg Aufruf fehlgeschlagen: {exc}"
    if proc.returncode == 0:
        return True, ""
    err = (proc.stderr or proc.stdout or "").strip()
    return False, f"ffmpeg fehlgeschlagen: {err[-400:]}"


def _sanitize_folder(folder: str) -> str:
    out = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in str(folder or "").strip())
    return out.strip("._") or datetime.now().strftime("%Y%m%d_%H%M%S")


def _upload_name(upload, fallback: str) -> str:
    name = str(getattr(upload, "name", "") or "").strip()
    return Path(name).name or fallback


def _upload_bytes(upload) -> bytes:
    if upload is None:
        return b""
    if isinstance(upload, (bytes, bytearray)):
        return bytes(upload)
    getbuffer = getattr(upload, "getbuffer", None)
    if callable(getbuffer):
        return bytes(getbuffer())
    getvalue = getattr(upload, "getvalue", None)
    if callable(getvalue):
        return bytes(getvalue())
    read = getattr(upload, "read", None)
    if callable(read):
        return bytes(read())
    raise TypeError("Upload-Typ wird nicht unterstuetzt")


def _write_upload(upload, dst: Path, fallback_name: str) -> Path:
    dst.mkdir(parents=True, exist_ok=True)
    name = _upload_name(upload, fallback_name)
    path = dst / name
    path.write_bytes(_upload_bytes(upload))
    return path


def _probe_video(video_path: Path) -> tuple[float, float]:
    fps_v = 30.0
    duration_v = 0.0
    try:
        cap = cv2.VideoCapture(str(video_path))
        if cap.isOpened():
            fps_probe = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
            fc_probe = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
            if fps_probe > 0:
                fps_v = fps_probe
            if fps_probe > 0 and fc_probe > 0:
                duration_v = fc_probe / fps_probe
        cap.release()
    except Exception:
        pass
    if duration_v <= 0:
        duration_v = 86400.0
    return float(fps_v), float(duration_v)


def _trim_input_args(trim_start_s: float) -> list[str]:
    args: list[str] = []
    start_v = max(0.0, float(trim_start_s or 0.0))
    if start_v > 0:
        args.extend(["-ss", f"{start_v:.3f}"])
    return args


def _trim_duration_args(trim_start_s: float, trim_end_s: float | None) -> list[str]:
    args: list[str] = []
    start_v = max(0.0, float(trim_start_s or 0.0))
    end_v = None if trim_end_s is None else float(trim_end_s)
    if end_v is not None and end_v > start_v:
        args.extend(["-t", f"{(end_v - start_v):.3f}"])
    return args


def _video_filter_args(target_fps: float | None) -> list[str]:
    if target_fps is None:
        return []
    fps_v = float(target_fps)
    if fps_v <= 0:
        return []
    fps_txt = str(int(fps_v)) if abs(fps_v - int(fps_v)) < 1e-9 else f"{fps_v:.3f}".rstrip("0").rstrip(".")
    return ["-vf", f"fps={fps_txt}"]
    return args


def _write_results_json(
    base_dir: Path,
    folder: str,
    video_dst: Path,
    audio_dst: Path,
    title: str,
    trim_start_s: float,
    trim_end_s: float | None,
    target_fps: float | None = None,
) -> Path:
    fps_v, duration_v = _probe_video(video_dst)
    res_dir = base_dir / "results"
    res_dir.mkdir(parents=True, exist_ok=True)
    path = res_dir / f"results_{folder}.json"
    payload: dict = {}
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            if not isinstance(payload, dict):
                payload = {}
        except Exception:
            payload = {}
    record = payload.get("recordResult")
    if not isinstance(record, dict):
        record = {}
    record["metadata"] = {
        "title": str(title or video_dst.stem),
        "video": video_dst.name,
        "audio": str(audio_dst),
        "url": "",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "outdir": str(video_dst.parent),
        "fps": float(fps_v),
        "duration": float(duration_v),
        "pubDate": "",
        "desc": "",
        "chanName": "",
        "source": "local_upload",
        "trim_start_s": float(trim_start_s or 0.0),
        "trim_end_s": None if trim_end_s is None else float(trim_end_s),
        "import_target_fps": None if target_fps is None else float(target_fps),
    }
    payload["recordResult"] = record
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def import_local_media(
    base_dir: Path | str,
    folder: str,
    video_upload,
    audio_upload=None,
    title: str = "",
    trim_start_s: float = 0.0,
    trim_end_s: float | None = None,
    target_fps: float | None = None,
    progress_cb=None,
) -> tuple[bool, str, dict]:
    base = Path(base_dir).expanduser().resolve()
    folder = _sanitize_folder(folder)
    cap_dir = base / "captures" / folder
    cap_dir.mkdir(parents=True, exist_ok=True)
    video_dst = cap_dir / f"screen_{folder}_video.avi"
    audio_dst = cap_dir / f"screen_{folder}_audio.wav"
    trim_start_s = max(0.0, float(trim_start_s or 0.0))
    trim_end_s = None if trim_end_s is None else float(trim_end_s)
    if trim_end_s is not None and trim_end_s <= trim_start_s:
        return False, "Ende muss groesser als Start sein.", {}

    tmp_dir = Path(tempfile.mkdtemp(prefix="local_media_ingest_"))
    try:
        if callable(progress_cb):
            progress_cb("Quelldateien werden vorbereitet")
        video_src = video_upload if isinstance(video_upload, Path) else _write_upload(video_upload, tmp_dir, "upload_video.bin")
        audio_src = audio_upload if isinstance(audio_upload, Path) else (_write_upload(audio_upload, tmp_dir, "upload_audio.bin") if audio_upload is not None else None)
        trim_in_args = _trim_input_args(trim_start_s)
        trim_duration_args = _trim_duration_args(trim_start_s, trim_end_s)
        video_filter_args = _video_filter_args(target_fps)

        if callable(progress_cb):
            progress_cb("Video wird normalisiert")
        ok_video, msg_video = _run_ffmpeg(
            [
                "-y",
                *trim_in_args,
                "-i",
                str(video_src),
                *trim_duration_args,
                "-map",
                "0:v:0",
                *video_filter_args,
                "-c:v",
                "mjpeg",
                "-q:v",
                "8",
                "-an",
                str(video_dst),
            ]
        )
        if not ok_video:
            return False, msg_video, {}

        audio_input = audio_src if audio_src is not None else video_src
        if callable(progress_cb):
            progress_cb("Audio wird erzeugt")
        ok_audio, msg_audio = _run_ffmpeg(
            [
                "-y",
                *trim_in_args,
                "-i",
                str(audio_input),
                *trim_duration_args,
                "-vn",
                "-ac",
                "1",
                "-ar",
                "44100",
                str(audio_dst),
            ]
        )
        if not ok_audio:
            if audio_src is None:
                return False, "Kein Audio gefunden: eingebettete Audiospur konnte nicht extrahiert werden.", {}
            return False, msg_audio, {}

        if callable(progress_cb):
            progress_cb("Metadaten werden geschrieben")
        json_path = _write_results_json(
            base,
            folder,
            video_dst,
            audio_dst,
            title or _upload_name(video_upload, video_dst.stem),
            trim_start_s,
            trim_end_s,
            target_fps,
        )
        return True, str(json_path), {"folder": folder, "video": str(video_dst), "audio": str(audio_dst), "json": str(json_path)}
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
