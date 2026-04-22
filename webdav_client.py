"""
WebDAV-Client für bwSyncAndShare (Nextcloud-kompatibel).
Getestet mit: https://bwsyncandshare.kit.edu
"""

from __future__ import annotations
import requests
from requests.auth import HTTPBasicAuth
from pathlib import PurePosixPath
import xml.etree.ElementTree as ET
from urllib.parse import unquote


class WebDAVClient:
    """WebDAV-Client für Nextcloud / bwSyncAndShare."""

    def __init__(self, base_url: str, username: str, password: str):
        # base_url ist die vollständige URL inkl. Benutzerordner,
        # z.B. https://bwsyncandshare.kit.edu/remote.php/dav/files/UUID%40bwidm.scc.kit.edu/
        self.base_url = base_url.rstrip("/") + "/"
        self.auth     = HTTPBasicAuth(username, password)
        self.session  = requests.Session()
        self.session.auth = self.auth

    def _url(self, remote_path: str) -> str:
        """
        Baut vollständige URL.
        remote_path "/" → base_url
        remote_path "/captures/foo" → base_url + "captures/foo"
        """
        clean = remote_path.strip("/")
        if not clean:
            return self.base_url
        return self.base_url + clean + ("/" if not "." in clean.split("/")[-1] else "")

    def _url_file(self, remote_path: str) -> str:
        """URL für Dateien (kein trailing slash)."""
        clean = remote_path.strip("/")
        if not clean:
            return self.base_url
        return self.base_url + clean

    # ── Verbindungstest ────────────────────────────────────────────────────────

    def test_connection(self) -> tuple[bool, str]:
        """PROPFIND direkt auf base_url (Depth 0)."""
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
            if r.status_code == 403:
                return False, "Zugriff verweigert (403). URL oder Username prüfen."
            if r.status_code == 404:
                return False, "URL nicht gefunden (404)."
            return False, f"HTTP {r.status_code}"
        except requests.exceptions.ConnectionError as e:
            return False, f"Verbindungsfehler: {e}"
        except requests.exceptions.Timeout:
            return False, "Timeout."
        except Exception as e:
            return False, str(e)

    # ── Verzeichnis auflisten ──────────────────────────────────────────────────

    def list_files(self, remote_dir: str = "/") -> tuple[bool, list[str] | str]:
        """
        Listet Inhalt eines Verzeichnisses auf.
        Gibt (True, ['name/', 'file.txt', ...]) zurück — 
        Ordner mit trailing /, Dateien ohne.
        Die Namen sind relativ zum remote_dir.
        """
        try:
            url = self._url(remote_dir)
            r = self.session.request(
                "PROPFIND",
                url,
                headers={"Depth": "1"},
                data="""<?xml version="1.0"?>
<d:propfind xmlns:d="DAV:">
  <d:prop>
    <d:displayname/>
    <d:resourcetype/>
    <d:getcontentlength/>
    <d:getlastmodified/>
  </d:prop>
</d:propfind>""",
                timeout=15,
            )
            if r.status_code not in (207, 200):
                return False, f"HTTP {r.status_code}"

            root_xml = ET.fromstring(r.text)
            ns = {"d": "DAV:"}
            items = []

            # Ersten Eintrag überspringen (das ist das Verzeichnis selbst)
            responses = root_xml.findall("d:response", ns)
            for resp in responses[1:]:   # [0] = Verzeichnis selbst
                href_el = resp.find("d:href", ns)
                if href_el is None or not href_el.text:
                    continue

                href = unquote(href_el.text)   # URL-Dekodierung: %40 → @

                # Name = letzter Pfad-Teil
                name = href.rstrip("/").split("/")[-1]
                if not name:
                    continue

                # Ist es ein Ordner?
                is_col = resp.find(".//d:resourcetype/d:collection", ns) is not None
                # Wir geben relative Namen zurück: "ordner/" oder "datei.txt"
                items.append(name + "/" if is_col else name)

            return True, items

        except Exception as e:
            return False, str(e)

    # ── Download ───────────────────────────────────────────────────────────────

    def download_file(self, remote_path: str, local_path: str) -> tuple[bool, str]:
        try:
            r = self.session.get(self._url_file(remote_path),
                                 stream=True, timeout=120)
            if r.status_code == 200:
                with open(local_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        f.write(chunk)
                return True, ""
            return False, f"HTTP {r.status_code}"
        except Exception as e:
            return False, str(e)

    # ── Upload ─────────────────────────────────────────────────────────────────

    def upload_string(self, content: str, remote_path: str,
                      encoding: str = "utf-8") -> tuple[bool, str]:
        self._ensure_dirs(remote_path)
        try:
            r = self.session.put(
                self._url_file(remote_path),
                data=content.encode(encoding),
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
        self._ensure_dirs(remote_path)
        try:
            r = self.session.put(
                self._url_file(remote_path),
                data=data,
                headers={"Content-Type": content_type},
                timeout=120,
            )
            if r.status_code in (200, 201, 204):
                return True, ""
            return False, f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as e:
            return False, str(e)

    def upload_file(self, local_path: str, remote_path: str) -> tuple[bool, str]:
        self._ensure_dirs(remote_path)
        try:
            with open(local_path, "rb") as f:
                r = self.session.put(self._url_file(remote_path),
                                     data=f, timeout=120)
            if r.status_code in (200, 201, 204):
                return True, ""
            return False, f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as e:
            return False, str(e)

    def delete_file(self, remote_path: str) -> tuple[bool, str]:
        try:
            r = self.session.delete(self._url_file(remote_path), timeout=15)
            if r.status_code in (200, 204, 404):
                return True, ""
            return False, f"HTTP {r.status_code}"
        except Exception as e:
            return False, str(e)

    # ── Verzeichnisse anlegen ──────────────────────────────────────────────────

    def _ensure_dirs(self, remote_path: str) -> None:
        """Legt alle übergeordneten Verzeichnisse via MKCOL an."""
        parts = PurePosixPath(remote_path.strip("/")).parts
        if len(parts) <= 1:
            return
        path_so_far = ""
        for part in parts[:-1]:   # ohne Dateiname
            path_so_far += "/" + part
            try:
                self.session.request(
                    "MKCOL",
                    self._url_file(path_so_far),
                    timeout=10,
                )
                # 201 = neu angelegt, 405 = existiert bereits — beides OK
            except Exception:
                pass
