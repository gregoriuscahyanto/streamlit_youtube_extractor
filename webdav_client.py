"""
WebDAV-Client für bwSyncAndShare (Nextcloud-kompatibel).
Nutzt nur `requests` – keine extra WebDAV-Bibliothek nötig.
"""

from __future__ import annotations
import io
import requests
from requests.auth import HTTPBasicAuth
from pathlib import PurePosixPath


class WebDAVClient:
    """Einfacher WebDAV-Client für Nextcloud / bwSyncAndShare."""

    def __init__(self, base_url: str, username: str, password: str):
        # Basis-URL normalisieren: endet immer mit /
        self.base_url = base_url.rstrip("/") + "/"
        self.auth     = HTTPBasicAuth(username, password)
        self.session  = requests.Session()
        self.session.auth = self.auth

    # ── interne Hilfsfunktionen ────────────────────────────────────────────────

    def _url(self, remote_path: str) -> str:
        """Baut die vollständige URL aus dem Remote-Pfad."""
        # remote_path: z.B. /OCR/config.json  →  base_url + OCR/config.json
        return self.base_url + remote_path.lstrip("/")

    # ── öffentliche API ────────────────────────────────────────────────────────

    def test_connection(self) -> tuple[bool, str]:
        """
        Testet die Verbindung via PROPFIND auf das Root-Verzeichnis.
        Gibt (True, "") oder (False, Fehlermeldung) zurück.
        """
        try:
            r = self.session.request(
                "PROPFIND",
                self.base_url,
                headers={"Depth": "0"},
                timeout=10,
            )
            if r.status_code in (207, 200):
                return True, ""
            if r.status_code == 401:
                return False, "Authentifizierung fehlgeschlagen (401)."
            if r.status_code == 404:
                return False, "URL nicht gefunden (404). Pfad prüfen."
            return False, f"HTTP {r.status_code}"
        except requests.exceptions.ConnectionError as e:
            return False, f"Verbindungsfehler: {e}"
        except requests.exceptions.Timeout:
            return False, "Timeout beim Verbinden."
        except Exception as e:
            return False, str(e)

    def list_files(self, remote_dir: str = "/") -> tuple[bool, list[str] | str]:
        """
        Listet Dateien im Verzeichnis auf.
        Gibt (True, [pfad, ...]) oder (False, Fehlermeldung) zurück.
        """
        try:
            r = self.session.request(
                "PROPFIND",
                self._url(remote_dir),
                headers={
                    "Depth": "1",
                    "Content-Type": "application/xml",
                },
                data="""<?xml version="1.0"?>
<d:propfind xmlns:d="DAV:">
  <d:prop><d:displayname/><d:resourcetype/></d:prop>
</d:propfind>""",
                timeout=15,
            )
            if r.status_code not in (207, 200):
                return False, f"HTTP {r.status_code}"

            # Einfaches XML-Parsing ohne externe Bibliothek
            import xml.etree.ElementTree as ET
            root = ET.fromstring(r.text)
            ns = {"d": "DAV:"}
            files = []
            for resp in root.findall("d:response", ns):
                href = resp.find("d:href", ns)
                if href is not None and href.text:
                    p = href.text.rstrip("/")
                    # Nur nicht-Verzeichnisse zurückgeben
                    rt = resp.find(".//d:resourcetype/d:collection", ns)
                    if rt is None:
                        files.append(p)
            return True, files
        except Exception as e:
            return False, str(e)

    def download_file(self, remote_path: str, local_path: str) -> tuple[bool, str]:
        """
        Lädt eine Datei von WebDAV herunter.
        Gibt (True, "") oder (False, Fehlermeldung) zurück.
        """
        try:
            r = self.session.get(self._url(remote_path), stream=True, timeout=60)
            if r.status_code == 200:
                with open(local_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        f.write(chunk)
                return True, ""
            return False, f"HTTP {r.status_code}"
        except Exception as e:
            return False, str(e)

    def upload_file(self, local_path: str, remote_path: str) -> tuple[bool, str]:
        """
        Lädt eine lokale Datei zu WebDAV hoch (PUT).
        Legt übergeordnete Verzeichnisse automatisch an (MKCOL).
        Gibt (True, "") oder (False, Fehlermeldung) zurück.
        """
        self._ensure_dirs(remote_path)
        try:
            with open(local_path, "rb") as f:
                r = self.session.put(self._url(remote_path), data=f, timeout=120)
            if r.status_code in (200, 201, 204):
                return True, ""
            return False, f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as e:
            return False, str(e)

    def upload_string(self, content: str, remote_path: str,
                      encoding: str = "utf-8") -> tuple[bool, str]:
        """
        Lädt einen String (z.B. JSON) als Datei zu WebDAV hoch.
        Gibt (True, "") oder (False, Fehlermeldung) zurück.
        """
        self._ensure_dirs(remote_path)
        try:
            data = content.encode(encoding)
            r = self.session.put(
                self._url(remote_path),
                data=data,
                headers={"Content-Type": "application/json; charset=utf-8"},
                timeout=30,
            )
            if r.status_code in (200, 201, 204):
                return True, ""
            return False, f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as e:
            return False, str(e)

    def upload_bytes(self, data: bytes, remote_path: str,
                     content_type: str = "application/octet-stream") -> tuple[bool, str]:
        """
        Lädt Bytes direkt zu WebDAV hoch.
        """
        self._ensure_dirs(remote_path)
        try:
            r = self.session.put(
                self._url(remote_path),
                data=data,
                headers={"Content-Type": content_type},
                timeout=120,
            )
            if r.status_code in (200, 201, 204):
                return True, ""
            return False, f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as e:
            return False, str(e)

    def delete_file(self, remote_path: str) -> tuple[bool, str]:
        """Löscht eine Datei auf WebDAV."""
        try:
            r = self.session.delete(self._url(remote_path), timeout=15)
            if r.status_code in (200, 204, 404):
                return True, ""
            return False, f"HTTP {r.status_code}"
        except Exception as e:
            return False, str(e)

    # ── interne Helfer ─────────────────────────────────────────────────────────

    def _ensure_dirs(self, remote_path: str) -> None:
        """
        Stellt sicher, dass alle übergeordneten Verzeichnisse des remote_path
        auf dem Server existieren (MKCOL).
        """
        parts = PurePosixPath(remote_path.lstrip("/")).parts
        if len(parts) <= 1:
            return  # Datei liegt im Root, kein Verzeichnis nötig
        # Verzeichnis-Teile ohne den Dateinamen
        dirs = parts[:-1]
        path_so_far = ""
        for d in dirs:
            path_so_far += "/" + d
            try:
                self.session.request(
                    "MKCOL",
                    self._url(path_so_far),
                    timeout=10,
                )
                # 201 = erstellt, 405 = existiert bereits — beides OK
            except Exception:
                pass  # weiter versuchen
