"""
storage.py
Verwaltet die Ordnerstruktur auf Nextcloud/bwSyncAndShare:

  <root>/
  ├── captures/
  │   └── 20251104_202910/
  │       ├── 20251104_202910.mp4
  │       └── 20251104_202910.wav
  └── results/
      ├── results_20251104_202910.mat
      └── results_20251104_202910.json
"""

from __future__ import annotations
from pathlib import PurePosixPath
from webdav_client import WebDAVClient


class StorageManager:
    """Kapselt alle Dateipfad-Logik für die Nextcloud-Struktur."""

    def __init__(self, client: WebDAVClient, root: str = "/"):
        self.client = client
        self.root   = root.rstrip("/")  # z.B. "" oder "/mein_projekt"

    # ── Pfad-Helfer ────────────────────────────────────────────────────────────

    def captures_dir(self, folder: str) -> str:
        """z.B. /captures/20251104_202910"""
        return f"{self.root}/captures/{folder}"

    def video_path(self, folder: str) -> str:
        """z.B. /captures/20251104_202910/20251104_202910.mp4"""
        return f"{self.captures_dir(folder)}/{folder}.mp4"

    def audio_path(self, folder: str) -> str:
        """z.B. /captures/20251104_202910/20251104_202910.wav"""
        return f"{self.captures_dir(folder)}/{folder}.wav"

    def results_dir(self) -> str:
        return f"{self.root}/results"

    def result_json_path(self, folder: str) -> str:
        return f"{self.results_dir()}/results_{folder}.json"

    def result_mat_path(self, folder: str) -> str:
        return f"{self.results_dir()}/results_{folder}.mat"

    # ── Upload ─────────────────────────────────────────────────────────────────

    def upload_result_json(self, folder: str, json_str: str) -> tuple[bool, str]:
        return self.client.upload_string(json_str, self.result_json_path(folder))

    def upload_result_mat(self, folder: str, mat_bytes: bytes) -> tuple[bool, str]:
        return self.client.upload_bytes(mat_bytes, self.result_mat_path(folder),
                                        content_type="application/octet-stream")

    # ── Download ───────────────────────────────────────────────────────────────

    def download_video(self, folder: str, local_path: str) -> tuple[bool, str]:
        return self.client.download_file(self.video_path(folder), local_path)

    def download_audio(self, folder: str, local_path: str) -> tuple[bool, str]:
        return self.client.download_file(self.audio_path(folder), local_path)

    def download_result_json(self, folder: str, local_path: str) -> tuple[bool, str]:
        return self.client.download_file(self.result_json_path(folder), local_path)

    def download_result_mat(self, folder: str, local_path: str) -> tuple[bool, str]:
        return self.client.download_file(self.result_mat_path(folder), local_path)

    # ── Ordner auflisten ───────────────────────────────────────────────────────

    def list_capture_folders(self) -> tuple[bool, list[str] | str]:
        """Gibt alle Unterordner in captures/ zurück."""
        ok, items = self.client.list_files(f"{self.root}/captures/")
        if not ok:
            return False, items
        folders = []
        for item in items:
            # Nur direkte Unterordner (kein Slash am Ende → keine Dateien)
            p = item.rstrip("/").split("/")[-1]
            if p and p != "captures":
                folders.append(p)
        return True, sorted(folders, reverse=True)  # neueste zuerst

    def list_results(self) -> tuple[bool, list[str] | str]:
        """Gibt alle Dateien in results/ zurück."""
        ok, items = self.client.list_files(f"{self.root}/results/")
        if not ok:
            return False, items
        files = [item.split("/")[-1] for item in items if item.split("/")[-1]]
        return True, sorted(files, reverse=True)
