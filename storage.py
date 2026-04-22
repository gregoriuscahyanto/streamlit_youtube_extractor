"""
storage.py
Manages the folder structure in Cloudflare R2:

  <bucket>/
  ├── [prefix/]captures/
  │   └── 20251104_202910/
  │       ├── 20251104_202910.mp4
  │       └── 20251104_202910.wav
  └── [prefix/]results/
      ├── results_20251104_202910.mat
      └── results_20251104_202910.json
"""
from __future__ import annotations
from r2_client import R2Client


class StorageManager:

    def __init__(self, client: R2Client, prefix: str = ""):
        self.client = client
        self.prefix = prefix.strip("/")

    def _key(self, *parts: str) -> str:
        segs = ([self.prefix] if self.prefix else []) + [p.strip("/") for p in parts if p.strip("/")]
        return "/".join(segs)

    # ── Path helpers ───────────────────────────────────────────────────────────

    def captures_dir(self, folder: str) -> str:
        return self._key("captures", folder)

    def video_path(self, folder: str) -> str:
        return self._key("captures", folder, f"{folder}.mp4")

    def audio_path(self, folder: str) -> str:
        return self._key("captures", folder, f"{folder}.wav")

    def results_dir(self) -> str:
        return self._key("results")

    def result_json_path(self, folder: str) -> str:
        return self._key("results", f"results_{folder}.json")

    def result_mat_path(self, folder: str) -> str:
        return self._key("results", f"results_{folder}.mat")

    # ── Upload ─────────────────────────────────────────────────────────────────

    def upload_result_json(self, folder: str, json_str: str) -> tuple[bool, str]:
        return self.client.upload_string(json_str, self.result_json_path(folder))

    def upload_result_mat(self, folder: str, mat_bytes: bytes) -> tuple[bool, str]:
        return self.client.upload_bytes(mat_bytes, self.result_mat_path(folder))

    # ── Download ───────────────────────────────────────────────────────────────

    def download_video(self, folder: str, local_path: str) -> tuple[bool, str]:
        return self.client.download_file(self.video_path(folder), local_path)

    def download_audio(self, folder: str, local_path: str) -> tuple[bool, str]:
        return self.client.download_file(self.audio_path(folder), local_path)

    def download_result_json(self, folder: str, local_path: str) -> tuple[bool, str]:
        return self.client.download_file(self.result_json_path(folder), local_path)

    def download_result_mat(self, folder: str, local_path: str) -> tuple[bool, str]:
        return self.client.download_file(self.result_mat_path(folder), local_path)

    # ── List ───────────────────────────────────────────────────────────────────

    def list_capture_folders(self) -> tuple[bool, list[str] | str]:
        ok, items = self.client.list_files(self._key("captures"))
        if not ok:
            return False, items
        return True, sorted([i.rstrip("/") for i in items if i.endswith("/")], reverse=True)

    def list_results(self) -> tuple[bool, list[str] | str]:
        ok, items = self.client.list_files(self._key("results"))
        if not ok:
            return False, items
        return True, sorted([i for i in items if not i.endswith("/")], reverse=True)
