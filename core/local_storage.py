"""
Local filesystem storage adapter with an R2-like interface.
"""
from __future__ import annotations

from pathlib import Path
import shutil


class LocalStorageAdapter:
    def __init__(self, base_path: str):
        self.base = Path(base_path).expanduser().resolve()

    def test_connection(self) -> tuple[bool, str]:
        if not self.base.exists():
            return False, f"Basispfad nicht gefunden: {self.base}"
        if not self.base.is_dir():
            return False, f"Basispfad ist kein Ordner: {self.base}"
        return True, ""

    def _resolve_key(self, key: str) -> Path:
        rel = key.strip("/\\")
        target = (self.base / rel).resolve() if rel else self.base
        # Keep all operations inside base folder.
        if self.base != target and self.base not in target.parents:
            raise ValueError("Ungueltiger Pfad ausserhalb des Basisordners.")
        return target

    def list_files(self, prefix: str = "") -> tuple[bool, list[str] | str]:
        """
        Lists immediate children under prefix.
        Returns entries relative to prefix and marks directories with trailing slash.
        """
        try:
            folder = self._resolve_key(prefix)
            if not folder.exists():
                return False, f"Nicht gefunden: {prefix}"
            if not folder.is_dir():
                return False, f"Kein Ordner: {prefix}"
            items: list[str] = []
            for p in folder.iterdir():
                name = p.name + ("/" if p.is_dir() else "")
                items.append(name)
            items.sort(key=lambda x: (not x.endswith("/"), x.lower()))
            return True, items
        except Exception as e:
            return False, str(e)

    def download_file(self, key: str, local_path: str) -> tuple[bool, str]:
        try:
            src = self._resolve_key(key)
            if not src.exists() or not src.is_file():
                return False, f"Datei nicht gefunden: {key}"
            dst = Path(local_path).expanduser().resolve()
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            return True, ""
        except Exception as e:
            return False, str(e)

    def upload_file(self, local_path: str, key: str) -> tuple[bool, str]:
        try:
            src = Path(local_path).expanduser().resolve()
            if not src.exists() or not src.is_file():
                return False, f"Lokale Datei nicht gefunden: {local_path}"
            dst = self._resolve_key(key)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            return True, ""
        except Exception as e:
            return False, str(e)

    def upload_bytes(self, data: bytes, key: str) -> tuple[bool, str]:
        try:
            dst = self._resolve_key(key)
            dst.parent.mkdir(parents=True, exist_ok=True)
            with open(dst, "wb") as f:
                f.write(data)
            return True, ""
        except Exception as e:
            return False, str(e)

    def upload_string(self, content: str, key: str, encoding: str = "utf-8") -> tuple[bool, str]:
        try:
            dst = self._resolve_key(key)
            dst.parent.mkdir(parents=True, exist_ok=True)
            with open(dst, "w", encoding=encoding) as f:
                f.write(content)
            return True, ""
        except Exception as e:
            return False, str(e)

    def delete_file(self, key: str) -> tuple[bool, str]:
        try:
            target = self._resolve_key(key)
            if not target.exists():
                return False, f"Nicht gefunden: {key}"
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            return True, ""
        except Exception as e:
            return False, str(e)

