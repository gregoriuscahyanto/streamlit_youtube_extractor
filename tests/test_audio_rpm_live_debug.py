import ast
import concurrent.futures as cf
import io
import json
import socket
import tempfile
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import numpy as np
from scipy.io import wavfile


class _RollingStub:
    def __init__(self, values, window):
        self.values = np.asarray(values, dtype=float)
        self.window = int(max(1, window))

    def median(self):
        half = self.window // 2
        out = np.empty_like(self.values, dtype=float)
        for idx in range(self.values.size):
            lo = max(0, idx - half)
            hi = min(self.values.size, idx + half + 1)
            out[idx] = np.nanmedian(self.values[lo:hi])
        return _SeriesStub(out)


class _SeriesStub:
    def __init__(self, values):
        self.values = np.asarray(values, dtype=float)

    def rolling(self, window, center=True, min_periods=1):
        del center, min_periods
        return _RollingStub(self.values, window)

    def to_numpy(self, dtype=float):
        return np.asarray(self.values, dtype=dtype).copy()


class _PandasStub:
    Series = _SeriesStub


class _SignalStub:
    @staticmethod
    def spectrogram(x, fs, window="hann", nperseg=256, noverlap=0, nfft=None, detrend=False, scaling="spectrum", mode="magnitude"):
        del window, detrend, scaling
        x = np.asarray(x, dtype=np.float32).reshape(-1)
        nperseg = int(max(1, min(nperseg, len(x))))
        nfft = int(nfft or nperseg)
        noverlap = int(max(0, min(noverlap, nperseg - 1)))
        hop = max(1, nperseg - noverlap)
        starts = list(range(0, max(1, len(x) - nperseg + 1), hop)) or [0]
        win = np.hanning(nperseg).astype(np.float32)
        cols = []
        for start in starts:
            frame = x[start:start + nperseg]
            if frame.size < nperseg:
                frame = np.pad(frame, (0, nperseg - frame.size))
            cols.append(np.abs(np.fft.rfft(frame * win, n=nfft)))
        freqs = np.fft.rfftfreq(nfft, d=1.0 / float(fs))
        times = (np.asarray(starts, dtype=float) + nperseg / 2.0) / float(fs)
        return freqs, times, np.stack(cols, axis=1).astype(np.float32)


class _DummyStreamlit:
    def __init__(self):
        self.session_state = {}

    def cache_resource(self, *args, **kwargs):
        if args and callable(args[0]):
            return args[0]

        def decorator(fn):
            return fn

        return decorator


def _load_audio_namespace():
    repo = Path(__file__).resolve().parents[1]
    source = (repo / "app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    audio_nodes = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("_audio_")
    ]
    namespace = {
        "np": np,
        "pd": _PandasStub,
        "signal": _SignalStub,
        "wavfile": wavfile,
        "Path": Path,
        "tempfile": tempfile,
        "time": time,
        "io": io,
        "zipfile": zipfile,
        "json": json,
        "socket": socket,
        "threading": threading,
        "cf": cf,
        "BaseHTTPRequestHandler": BaseHTTPRequestHandler,
        "ThreadingHTTPServer": ThreadingHTTPServer,
        "urlparse": urlparse,
        "parse_qs": parse_qs,
        "st": _DummyStreamlit(),
        "components": SimpleNamespace(html=lambda *args, **kwargs: None),
    }
    exec(compile(ast.Module(body=audio_nodes, type_ignores=[]), str(repo / "app.py"), "exec"), namespace)
    return namespace


def _synthetic_engine_audio(rpm=2200.0, rpm_end=3800.0, fs=4000, seconds=5.0, cyl=4, takt=4):
    t = np.arange(int(fs * seconds), dtype=np.float32) / float(fs)
    conv = 2.0 * float(cyl) / float(takt)
    rpm_profile = float(rpm) + (float(rpm_end) - float(rpm)) * (t / float(seconds))
    f0 = rpm_profile / 60.0 * conv
    phase = 2.0 * np.pi * np.cumsum(f0) / float(fs)
    y = (
        0.70 * np.sin(phase)
        + 0.25 * np.sin(2.0 * phase + 0.25)
        + 0.08 * np.sin(2.0 * np.pi * 37.0 * t + 0.50)
    )
    return y.astype(np.float32), fs, float(seconds)


def test_audio_rpm_extraction_tracks_synthetic_engine_signal():
    ns = _load_audio_namespace()
    rpm_start = 2200.0
    rpm_end = 3800.0
    y, fs, seconds = _synthetic_engine_audio(rpm=rpm_start, rpm_end=rpm_end)
    debug_lines = []
    progress = []

    result = ns["_audio_extract_rpm_robust"](
        y,
        fs,
        0.0,
        seconds,
        0.0,
        2048,
        75.0,
        500.0,
        4,
        4,
        1,
        1000.0,
        5000.0,
        "STFT Ridge",
        "Fest auswählen",
        "Fest auswählen",
        "Verbrenner/Hybrid",
        stft_mode="Fest auswählen",
        debug_cb=debug_lines.append,
        method_params={"fast_mode": True},
        progress_cb=lambda done, total, text="": progress.append((done, total, text)),
    )

    rpm = np.asarray(result["rpm"], dtype=float)
    result_t = np.asarray(result["t"], dtype=float)
    truth = rpm_start + (rpm_end - rpm_start) * (result_t / seconds)
    median_abs_error = float(np.nanmedian(np.abs(rpm - truth)))
    assert median_abs_error < 180.0
    assert result["selected_method"] == "STFT Ridge"
    assert any("Audiosegment" in line for line in debug_lines)
    assert progress and progress[-1][0] == progress[-1][1]


def test_audio_background_worker_updates_live_debug_state():
    ns = _load_audio_namespace()
    y, fs, seconds = _synthetic_engine_audio()
    live_updates = []

    def fake_live_update(job_id, *, log_line=None, progress=None, status=None):
        live_updates.append(
            {"job_id": job_id, "log_line": log_line, "progress": dict(progress or {}), "status": status}
        )

    ns["_audio_live_update"] = fake_live_update
    shared_log = []
    shared_progress = {}
    params = {
        "start_s": 0.0,
        "end_s": seconds,
        "offset_s": 0.0,
        "nfft": 2048,
        "overlap_pct": 75.0,
        "fmax": 500.0,
        "cyl": 4,
        "takt": 4,
        "order": 1,
        "rpm_min": 1000.0,
        "rpm_max": 5000.0,
        "method": "STFT Ridge",
        "cyl_mode": "Fest auswählen",
        "harmonic_mode": "Fest auswählen",
        "drive_type": "Verbrenner/Hybrid",
        "stft_mode": "Fest auswählen",
        "method_params": {"fast_mode": True},
    }

    result = ns["_audio_background_worker"](
        y,
        fs,
        "synthetic-video",
        params,
        {"vehicle_title": "synthetic"},
        shared_log,
        shared_progress,
        "job-test",
    )

    assert result["debug_lines"]
    assert any("Job" in line for line in shared_log)
    assert any("Auswahl" in line for line in shared_log)
    assert shared_progress["done"] == shared_progress["total"]
    assert any(update["progress"] for update in live_updates)
    assert any(update["status"] == "done" for update in live_updates)


def test_audio_load_current_capture_falls_back_to_video_audio_track():
    ns = _load_audio_namespace()
    repo = Path(__file__).resolve().parents[1]
    video_path = repo / "capture_video.mp4"
    temp_wav = repo / "audio_rpm_live_debug_proxy.wav"
    written_sources = []

    class _NamedTemp:
        def __init__(self, name):
            self.name = str(name)

        def close(self):
            return None

    class _TempfileStub:
        @staticmethod
        def NamedTemporaryFile(delete=False, suffix=""):
            return _NamedTemp(temp_wav)

    def fake_find_audio(folder):
        return None

    def fake_find_video(folder):
        return video_path

    def fake_build_audio_proxy(src_media, out_wav):
        written_sources.append(Path(src_media).name)
        y, fs, _seconds = _synthetic_engine_audio(seconds=1.0)
        wavfile.write(str(out_wav), fs, np.asarray(y * 32767.0, dtype=np.int16))
        return True, ""

    ns["st"].session_state.update({"capture_folder": "capture", "r2_connected": False, "r2_client": None})
    ns["tempfile"] = _TempfileStub
    ns["_find_local_audio_file"] = fake_find_audio
    ns["_find_local_fullfps_video"] = fake_find_video
    ns["_build_audio_proxy_wav"] = fake_build_audio_proxy

    ok, message, fs, y, source = ns["_audio_load_current_capture"]()

    assert ok, message
    assert fs == 4000
    assert y.size > 0
    assert source == "local-video:capture_video.mp4"
    assert written_sources == ["capture_video.mp4"]


def test_app_audio_tab_contains_live_polling_and_paper_based_methods():
    repo = Path(__file__).resolve().parents[1]
    source = (repo / "app.py").read_text(encoding="utf-8")
    source += "\n" + (repo / "app_tabs" / "audio_tab.py").read_text(encoding="utf-8")
    required_tokens = [
        "streamlit.components.v1",
        "ThreadPoolExecutor",
        "_audio_background_worker",
        "_audio_live_widget",
        "setTimeout(tick, 1000)",
        "STFT Viterbi",
        "Autokorrelation/YIN",
        "Cepstrum",
        "Harmonic Comb/HPS",
        "CWT/Wavelet",
        'source_kind = "video"',
    ]
    for token in required_tokens:
        assert token in source

