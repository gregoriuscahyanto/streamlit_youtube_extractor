import argparse, time, threading, queue, subprocess, shutil, platform, sys, os
import numpy as np
import pyautogui
import webbrowser
import pyaudiowpatch as paw
import soundfile as sf
import mss
import cv2
import re
import urllib.request
import html
try:
    import requests
except Exception:
    requests = None

# --- ensure utf-8 stdout/stderr when launched from MATLAB on Windows ---
import io
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    # Py<3.7 fallback
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# print(sd.query_devices())

# ===================== Konfiguration =====================
TARGET_FPS   = 30.0           # 30 oder 60, je nach Performance
FRAME_DT     = 1.0 / TARGET_FPS
AUDIO_SR     = 48000          # 44100/48000 üblich
AUDIO_CH     = 2
AUDIO_FMT    = "PCM_16"
PREP_WAIT_S  = 10.0           # Wartezeit nach Laden/YT-UI, bevor wir loslegen
BUFFER_WAIT  = 3.0            # Pufferzeit in Vollbild bei Standbild 0:00
MAX_Q        = int(TARGET_FPS * 2)  # ~2s Frame-Puffer
REGION_MODE  = False          # True -> Rect statt Fullscreen-Monitor (unten anpassen)
REGION_RECT  = {"left":0,"top":0,"width":1280,"height":720}  # nur wenn REGION_MODE=True
PROGRESS_BAR_LENGTH = 40

# (Optional) bessere Sleep-Auflösung unter Windows
if platform.system().lower() == "windows":
    try:
        import ctypes
        ctypes.windll.winmm.timeBeginPeriod(1)
    except Exception:
        pass

# ===================== Utilities =====================
def progress_line(elapsed, total):
    p = min(elapsed / total, 1.0)
    filled = int(PROGRESS_BAR_LENGTH * p)
    bar = "█" * filled + "-" * (PROGRESS_BAR_LENGTH - filled)
    return f"[{bar}] {elapsed:5.1f}/{total:5.1f}s ({p*100:3.0f}%)"

def key(seq):
    """Hilfsfunktion für kurze Tastensequenzen."""
    if isinstance(seq, (list, tuple)):
        pyautogui.hotkey(*seq)
    else:
        pyautogui.press(seq)

def safe_sleep(s):
    """Kurze Sleeps ohne starre Abhängigkeit, damit Keyboard-Events durchkommen."""
    time.sleep(s)

def has_ffmpeg():
    return shutil.which("ffmpeg") is not None

def find_loopback_device():
    """Return the pyaudiowpatch device index for the current default audio output's loopback.

    pyaudiowpatch exposes every WASAPI output as a virtual '[Loopback]' input device.
    We simply find the default output, then look up its matching loopback by name.
    This works automatically for any output device (Realtek speakers, Plantronics
    headphones, etc.) — no manual configuration needed.
    """
    p = paw.PyAudio()
    try:
        wasapi_idx = next(
            i for i in range(p.get_host_api_count())
            if "WASAPI" in (p.get_host_api_info_by_index(i).get("name") or "")
        )
        default_out_idx = p.get_host_api_info_by_index(wasapi_idx)["defaultOutputDevice"]
        out_name = p.get_device_info_by_index(default_out_idx)["name"]
        print(f"[AUDIO] Active output: index={default_out_idx}, name={out_name}")

        target_name = out_name + " [Loopback]"
        # Pass 1: exact match for the active output's loopback
        for i in range(p.get_device_count()):
            d = p.get_device_info_by_index(i)
            if d.get("isLoopbackDevice") and d["name"] == target_name:
                print(f"[AUDIO] Loopback device: index={i}, name={d['name']}")
                return i

        # Pass 2: any loopback (fallback)
        for i in range(p.get_device_count()):
            d = p.get_device_info_by_index(i)
            if d.get("isLoopbackDevice") and d.get("maxInputChannels", 0) > 0:
                print(f"[AUDIO] Fallback loopback: index={i}, name={d['name']}")
                return i

        print("[AUDIO] No loopback device found.")
        return None
    finally:
        p.terminate()

# ===================== NEW: Active window -> Monitor detection (Windows) =====================
def get_active_window_rect():
    """
    Returns dict: {"left":..,"top":..,"width":..,"height":..} for the ACTIVE window.
    On Windows, pyautogui.getActiveWindow() usually works (via pygetwindow backend).
    """
    try:
        w = pyautogui.getActiveWindow()
        if w is None:
            return None
        # Some window managers may return negative coords if window spans screens; that's okay.
        return {
            "left": int(w.left),
            "top": int(w.top),
            "width": int(w.width),
            "height": int(w.height),
        }
    except Exception as e:
        print("⚠️ Could not get active window rect:", e)
        return None

def pick_best_monitor_for_rect(sct, rect):
    """
    Choose the mss monitor that overlaps the given rect the most.
    Returns (monitor_dict, index).
    """
    def intersect_area(a, b):
        ax1, ay1 = a["left"], a["top"]
        ax2, ay2 = a["left"] + a["width"], a["top"] + a["height"]
        bx1, by1 = b["left"], b["top"]
        bx2, by2 = b["left"] + b["width"], b["top"] + b["height"]
        ix1, iy1 = max(ax1, bx1), max(ay1, by1)
        ix2, iy2 = min(ax2, bx2), min(ay2, by2)
        iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
        return iw * ih

    best_i = 1
    best_area = -1
    for i in range(1, len(sct.monitors)):  # 1..N (0 is "all monitors")
        mon = sct.monitors[i]
        area = intersect_area(rect, mon)
        if area > best_area:
            best_area = area
            best_i = i

    return sct.monitors[best_i], best_i

# ===================== Audio: Producer (Callback) =====================
class AudioRecorder:
    def __init__(self, sr=AUDIO_SR, ch=AUDIO_CH, dtype='int16'):
        self.sr = sr
        self.ch = ch
        self._queue = queue.Queue()
        self._start_event = threading.Event()
        self._stream = None
        self._pa = None
        self.frames = 0

    def _cb(self, in_data, frame_count, time_info, status):
        if self._start_event.is_set():
            data = np.frombuffer(in_data, dtype=np.int16).reshape(-1, self.ch)
            self._queue.put(data.copy())
            self.frames += frame_count
        return (None, paw.paContinue)

    def start(self, device=None):
        self._pa = paw.PyAudio()
        self._stream = self._pa.open(
            format=paw.paInt16,
            channels=self.ch,
            rate=self.sr,
            input=True,
            input_device_index=device,
            frames_per_buffer=1024,
            stream_callback=self._cb,
        )
        self._stream.start_stream()

    def trigger(self):
        self._start_event.set()

    def stop(self):
        if self._stream:
            self._stream.stop_stream()
            self._stream.close()
        if self._pa:
            self._pa.terminate()

    def dump_to_wav(self, path):
        with sf.SoundFile(path, mode='w', samplerate=self.sr, channels=self.ch, subtype=AUDIO_FMT) as f:
            while not self._queue.empty():
                f.write(self._queue.get())

# ===================== Video: CFR Grabber + Writer =====================
class CFRVideoRecorder:
    def __init__(self, filename, fps=TARGET_FPS, region=None):
        self.filename = filename
        self.fps = fps
        self.frame_dt = 1.0 / fps
        self.q = queue.Queue(maxsize=MAX_Q)
        self._stop = threading.Event()
        self._start_event = threading.Event()
        self.nframes = 0
        self.sct = mss.mss()
        self.region = region

        if region is None:
            # NEW: Pick the monitor where the ACTIVE window sits (YouTube browser window should be active here)
            win_rect = get_active_window_rect()
            if win_rect:
                mon, idx = pick_best_monitor_for_rect(self.sct, win_rect)
                print(f"[INFO] Active window rect: {win_rect}")
                print(f"[INFO] Capturing monitor {idx}: {mon}")
                self.rect = {"left": mon["left"], "top": mon["top"], "width": mon["width"], "height": mon["height"]}
            else:
                mon = self.sct.monitors[1]
                print("[INFO] Active window not detected -> fallback to primary monitor (1).")
                self.rect = {"left": mon["left"], "top": mon["top"], "width": mon["width"], "height": mon["height"]}
        else:
            self.rect = region

        W, H = self.rect["width"], self.rect["height"]

        # jetzt: AVI mit XVID (oder alternativ "MJPG")
        fourcc = cv2.VideoWriter_fourcc(*"XVID")
        self.writer = cv2.VideoWriter(self.filename, fourcc, self.fps, (W, H))

        self._writer_thread = threading.Thread(target=self._writer_loop, daemon=True)

    def _writer_loop(self):
        try:
            while not self._stop.is_set() or not self.q.empty():
                try:
                    frame = self.q.get(timeout=0.1)
                except queue.Empty:
                    continue
                self.writer.write(frame)
        finally:
            self.writer.release()

    def start(self):
        self._writer_thread.start()

    def trigger(self, record_duration):
        """Blocking capture loop mit fester Taktung."""
        self._start_event.set()

        t0 = time.perf_counter()
        next_t = t0
        last_ui = 0.0

        try:
            while True:
                now = time.perf_counter()
                elapsed = now - t0
                if elapsed >= record_duration:
                    break

                if now < next_t:
                    time.sleep(next_t - now)

                grabbed = self.sct.grab(self.rect)  # BGRA
                frame_bgr = cv2.cvtColor(np.array(grabbed), cv2.COLOR_BGRA2BGR)

                if self.q.full():
                    # Drop oldest if overloaded
                    try:
                        self.q.get_nowait()
                    except queue.Empty:
                        pass
                self.q.put_nowait(frame_bgr)
                self.nframes += 1

                next_t += self.frame_dt
                now2 = time.perf_counter()
                if next_t < now2 - 2*self.frame_dt:
                    while next_t < now2 - self.frame_dt:
                        next_t += self.frame_dt

                if elapsed - last_ui >= 1.0:
                    print("\rRecording " + progress_line(elapsed, record_duration), end="", flush=True)
                    last_ui = elapsed
        except KeyboardInterrupt:
            print("\n⏹️  Aufnahme manuell gestoppt.")
        finally:
            print()

    def stop(self):
        self._stop.set()
        self._writer_thread.join()

# ===================== Browser/YT Steuerung =====================
def open_youtube_and_prepare(url):
    webbrowser.open(url, new=1)
    safe_sleep(5.0)

    key(['ctrl', 'l'])
    pyautogui.typewrite(url)
    key('enter')
    safe_sleep(PREP_WAIT_S)

    # Fokus einmalig (OK, aber nur hier)
    click_active_window_center()
    safe_sleep(0.2)

    # an Anfang springen
    key('0')
    safe_sleep(0.25)

    # Vollbild
    key('f')
    safe_sleep(BUFFER_WAIT)

    # WICHTIG: kein click_active_window_center() mehr im Vollbild


def click_active_window_center():
    rect = get_active_window_rect()
    if not rect:
        return False
    cx = rect["left"] + rect["width"] // 2
    cy = rect["top"] + rect["height"] // 2
    try:
        pyautogui.click(cx, cy)
        safe_sleep(0.15)
        return True
    except Exception as e:
        print("⚠️ Could not click active window center:", e)
        return False

def sync_start_and_play():
    print("⏱️  Sync in 3…"); safe_sleep(1.0)
    print("⏱️  2…");       safe_sleep(1.0)
    print("⏱️  1…");       safe_sleep(1.0)

    ok = ensure_playing(max_tries=4, motion_timeout=5.0)
    print(f"[INFO] Playback started: {ok}")

def press_play_toggle():
    # KEIN klicken im Vollbild, das kann Vollbild/Focus kaputt machen
    # Stattdessen nur Tastatur. Space ist oft robuster als 'k'
    key('space')
    safe_sleep(0.12)

def ensure_playing(max_tries=3, motion_timeout=4.0):
    """
    Versucht Play zu starten und wartet auf echte Bewegung.
    Wenn nach motion_timeout keine Motion: nochmal toggle (Retry).
    """
    for i in range(1, max_tries + 1):
        print(f"[SYNC] Try {i}/{max_tries}: toggling play…")
        press_play_toggle()

        ok = wait_for_playback_motion(timeout=motion_timeout)
        print(f"[SYNC] Motion after toggle: {ok}")

        if ok:
            return True

        # Falls Overlay/Spinner/Focus: nochmal klicken bevor nächster Versuch
        # click_active_window_center()
        safe_sleep(0.2)

    return False

def wait_for_playback_motion(timeout=10.0, box_w=240, box_h=140, thresh=3.0, stable_hits=3):
    """
    Wartet bis im Zentrum des aktiven Fensters Bildbewegung erkannt wird.
    - thresh: mittlere Pixeländerung (0..255) über ROI
    - stable_hits: wie viele "bewegte" Messungen hintereinander nötig sind
    """
    rect = get_active_window_rect()
    if not rect:
        return False

    # ---- ROI NICHT MEHR IN DER MITTE ----

    # 70% der Höhe = unteres Drittel
    cy = rect["top"] + int(rect["height"] * 0.70)

    # 35% der Breite = leicht links von Mitte
    cx = rect["left"] + int(rect["width"] * 0.35)

    left = max(rect["left"], cx - box_w // 2)
    top  = max(rect["top"],  cy - box_h // 2)

    roi = {
        "left": left,
        "top": top,
        "width": box_w,
        "height": box_h
    }

    sct = mss.mss()
    prev = None
    hits = 0
    t0 = time.perf_counter()

    while (time.perf_counter() - t0) < timeout:
        img = np.array(sct.grab(roi))[:, :, :3]  # BGR/RGB egal, wir machen gray
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        if prev is not None:
            diff = cv2.absdiff(gray, prev)
            mad = float(np.mean(diff))
            if mad >= thresh:
                hits += 1
                if hits >= stable_hits:
                    return True
            else:
                hits = 0
        prev = gray
        safe_sleep(0.12)

    return False


# ===================== Mux mit ffmpeg (optional) =====================
def mux_av(video_in, audio_wav, out_avi):
    cmd = [
        "ffmpeg", "-y",
        "-i", video_in,
        "-i", audio_wav,
        # Video unverändert übernehmen (XVID im AVI-Container)
        "-c:v", "copy",
        # Audio als unkomprimiertes PCM (maximale Kompatibilität, größere Dateien)
        "-c:a", "pcm_s16le",
        "-shortest",
        out_avi
    ]
    print("🔗 Muxe Audio+Video…")
    subprocess.run(cmd, check=False)


# --- helper: fetch YouTube HTML with user-agent ---
def fetch_html(url: str):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print("⚠️ Could not fetch HTML:", e)
        return ""

# --- get video title from YouTube (og:title -> <title> fallback) ---
def get_youtube_title(url):
    html_txt = fetch_html(url)
    title = None
    # Try og:title meta
    m1 = re.search(r'<meta\s+property="og:title"\s+content="(.*?)"\s*/?>', html_txt, flags=re.IGNORECASE)
    if m1:
        title = m1.group(1)
    else:
        # Fallback: <title>Video Title - YouTube</title>
        m2 = re.search(r'<title>(.*?)</title>', html_txt, flags=re.IGNORECASE | re.DOTALL)
        if m2:
            title = m2.group(1)
            # strip trailing " - YouTube" if present
            title = re.sub(r'\s*-\s*YouTube\s*$', '', title).strip()
    if title:
        title = html.unescape(title)
        # sanitize for safety in logs/files if ever used in filenames
        title = title.replace("\n", " ").replace("\r", " ").strip()
    return title or "(unbekannter Titel)"

def get_youtube_duration(url):
    try:
        with urllib.request.urlopen(url) as resp:
            html_txt = resp.read().decode("utf-8")
        match = re.search(r'"approxDurationMs":"(\d+)"', html_txt)
        if match:
            return int(match.group(1)) / 1000.0
    except Exception as e:
        print("⚠️ Could not get duration:", e)
    return 60.0  # fallback

def get_youtube_publish_date(url):
    try:
        html_txt = fetch_html(url)

        # 1. Variante: <meta itemprop="datePublished" content="2022-10-13T08:41:07-07:00">
        m1 = re.search(
            r'itemprop=["\']datePublished["\'][^>]*content=["\']([^"\']+)["\']',
            html_txt, flags=re.IGNORECASE
        )
        if m1:
            iso_str = m1.group(1)  # z.B. 2022-10-13T08:41:07-07:00
            # nur Datumsteil nehmen (vor dem 'T')
            date_part = iso_str.split('T', 1)[0]
            return date_part  # -> 2022-10-13

        # 2. Fallbacks wie vorher (optional)
        m2 = re.search(
            r'"publishDate"\s*:\s*"(\d{4}-\d{2}-\d{2})"',
            html_txt, flags=re.IGNORECASE
        )
        if m2:
            return m2.group(1)

        m3 = re.search(
            r'"uploadDate"\s*:\s*"(\d{4}-\d{2}-\d{2})',
            html_txt, flags=re.IGNORECASE
        )
        if m3:
            return m3.group(1)

    except Exception as e:
        print("⚠️ Could not get publish date:", e)

    return "(unbekanntes Veröffentlichungsdatum)"


# --- Beschreibung holen ---
def get_youtube_description(url):
    """
    Beschreibungstext aus <meta ...> oder JSON.
    """
    try:
        html_txt = fetch_html(url)
        desc = None

        # 1. og:description
        m1 = re.search(
            r'<meta\s+property="og:description"\s+content="(.*?)"\s*/?>',
            html_txt, flags=re.IGNORECASE | re.DOTALL
        )
        if m1:
            desc = m1.group(1)
        else:
            # 2. normales description-Tag
            m2 = re.search(
                r'<meta\s+name="description"\s+content="(.*?)"\s*/?>',
                html_txt, flags=re.IGNORECASE | re.DOTALL
            )
            if m2:
                desc = m2.group(1)
            else:
                # 3. JSON-Feld "shortDescription":"...","isCrawlable"
                m3 = re.search(
                    r'"shortDescription"\s*:\s*"(.*?)"\s*,\s*"isCrawlable"',
                    html_txt, flags=re.DOTALL | re.IGNORECASE
                )
                if m3:
                    desc = m3.group(1)
                    # JSON-escaped Newlines etc. bereinigen
                    desc = desc.replace(r"\n", "\n").replace(r"\r", "")

        if desc:
            desc = html.unescape(desc)
            desc = desc.strip()
            return desc

    except Exception as e:
        print("⚠️ Could not get description:", e)

    return "(keine Beschreibung gefunden)"

import re
import html

def get_youtube_channel_name(url):
    """
    Liefert den Namen des YouTube-Kanals (Account), der das Video veröffentlicht hat.
    """
    try:
        html_txt = fetch_html(url)
        name = None

        # 1. Variante: Microdata im <head>, z.B.
        # <link itemprop="name" content="Channel Name">
        m1 = re.search(
            r'<link\s+itemprop=["\']name["\']\s+content=["\']([^"\']+)["\']',
            html_txt,
            flags=re.IGNORECASE
        )
        if m1:
            name = m1.group(1)
        else:
            # 2. Variante: JSON-Feld "ownerChannelName":"Channel Name"
            m2 = re.search(
                r'"ownerChannelName"\s*:\s*"([^"]+)"',
                html_txt,
                flags=re.IGNORECASE
            )
            if m2:
                name = m2.group(1)

        if name:
            name = html.unescape(name)
            name = name.replace("\n", " ").replace("\r", " ").strip()
            return name

    except Exception as e:
        print("⚠️ Could not get channel name:", e)

    return "(unbekannter Kanal)"


# ===================== Main =====================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True, help="YouTube-URL")
    parser.add_argument("--duration", type=float, required=True, help="Aufnahmedauer in Sekunden")
    parser.add_argument("--out", default="capture", help="Basisname der Ausgabe (ohne Endung)")
    parser.add_argument("--fps", type=float, default=TARGET_FPS, help="Ziel-FPS (CFR)")
    parser.add_argument("--region", action="store_true", help="Region statt Fullscreen")
    parser.add_argument("--rect", type=str, default="", help='Rect "left,top,width,height" (nur mit --region)')
    parser.add_argument("--outdir", default=".", help="Ausgabe-Ordner")
    parser.add_argument("--audio-device", type=int, default=None, help="sounddevice device index (Output-Device für Loopback)")
    parser.add_argument("--no-loopback", action="store_true", help="deaktiviert WASAPI loopback")

    args = parser.parse_args()

    url = args.url
    record_duration = args.duration
    base = args.out
    fps = args.fps

    desc = get_youtube_description(url);
    pubDate = get_youtube_publish_date(url);
    chanName = get_youtube_channel_name(url);

    print(f"RESULT_DESC: {desc}", flush=True)
    print(f"RESULT_PUBDATE: {pubDate}", flush=True)
    print(f"RESULT_CHANNAME: {chanName}", flush=True)

    # Videolänge bestimmen (falls möglich)
    vid_len = get_youtube_duration(url)

    if vid_len is not None:
        # Effektive Aufnahmedauer = min(Mindestdauer, echte Videolänge)
        record_duration = min(record_duration, vid_len)
        print(f"[INFO] Video-Länge erkannt: {vid_len:.2f} s  |  Aufnahme: {record_duration:.2f} s (min)")
    else:
        # Länge unbekannt -> wir nehmen die gewünschte Mindestdauer
        record_duration = record_duration
        print(f"[INFO] Video-Länge unbekannt – Aufnahme: {record_duration:.2f} s (min)")

    # Region optional überschreiben
    region = None
    if args.region:
        if args.rect:
            parts = [int(x.strip()) for x in args.rect.split(",")]
            region = {"left": parts[0], "top": parts[1], "width": parts[2], "height": parts[3]}
        else:
            region = REGION_RECT

    # nach dem Parsen:
    outdir = os.path.abspath(args.outdir)
    os.makedirs(outdir, exist_ok=True)

    base = args.out  # bleibt nur der Basisname, ohne Pfad

    video_tmp = os.path.join(outdir, f"{base}_video.avi")
    audio_wav = os.path.join(outdir, f"{base}_audio.wav")
    out_mux   = os.path.join(outdir, f"{base}.avi")

    # 1) YT öffnen & vorbereiten
    print("🌐 Öffne YouTube und bereite Vollbild/0:00 vor…")
    open_youtube_and_prepare(url)

    # NEW: log which window is active right now (should be browser)
    wr = get_active_window_rect()
    print("[INFO] Active window rect after prepare:", wr)

    # 2) Recorder initialisieren
    print("🎤 Initialisiere Audio…")
    audio = AudioRecorder(sr=AUDIO_SR, ch=AUDIO_CH, dtype='int16')

    device_index = args.audio_device
    if device_index is None:
        device_index = find_loopback_device()
    if device_index is None:
        raise RuntimeError(
            "Kein Loopback-Aufnahmegerät gefunden. "
            "Bitte StereoMix in den Windows-Soundeinstellungen aktivieren."
        )
    audio.start(device=device_index)

    print(f"🎥 Initialisiere Video @ {fps:.2f} fps…")
    video = CFRVideoRecorder(filename=video_tmp, fps=fps, region=region)
    video.start()

    # 3) Sync & Start
    sync_start_and_play()
    # HIER: Start-Events setzen (Audio & Video praktisch gleichzeitig)
    audio.trigger()
    video.trigger(record_duration)

    # 4) Stop & Dateien schreiben
    print("🧹 Stoppe Recorder…")
    video.stop()
    audio.stop()
    audio.dump_to_wav(audio_wav)
    print(f"📦 Video: {video_tmp}  |  Audio: {audio_wav}")
    print(f"📊 Captured {video.nframes} Frames @ target {fps:.2f} fps (CFR)")

    # 5) Optional: Muxen zu fertigem AVI
    if has_ffmpeg():
        mux_av(video_tmp, audio_wav, out_mux)
        print(f"✅ Fertig: {out_mux}")
    else:
        print("ℹ️  ffmpeg nicht gefunden – Audio/Video liegen separat vor.")

    print(f"📦 Video: {video_tmp}  |  Audio: {audio_wav}")
    print(f"📊 Captured {video.nframes} Frames @ target {fps:.2f} fps (CFR)")

    title = get_youtube_title(url)
    final_video_path = out_mux if has_ffmpeg() else video_tmp

    print(f"RESULT_VIDEO: {os.path.abspath(final_video_path)}", flush=True)
    print(f"RESULT_AUDIO: {os.path.abspath(audio_wav)}", flush=True)
    print(f"RESULT_TITLE: {title}", flush=True)
    print(f"RESULT_URL: {url}", flush=True)
    print(f"RESULT_DESC: {desc}", flush=True)
    print(f"RESULT_PUBDATE: {pubDate}", flush=True)
    print(f"RESULT_CHANNAME: {chanName}", flush=True)

    # 6) Vollbild verlassen
    key('f')
    safe_sleep(0.5)

    # 7) Browser-Tab schließen
    key(['ctrl', 'w'])
    safe_sleep(0.3)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("❌ Fehler:", e)
        sys.exit(1)
