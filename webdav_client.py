"""
WebDAV-Client für bwSyncAndShare (Nextcloud-kompatibel).
Getestet mit: https://bwsyncandshare.kit.edu
"""

from __future__ import annotations
import requests
from requests.auth import HTTPBasicAuth
from pathlib import PurePosixPath
import xml.etree.ElementTree as ET
from urllib.parse import unquote, quote


class WebDAVClient:
    """WebDAV-Client für Nextcloud / bwSyncAndShare."""

    def __init__(self, base_url: str, username: str, password: str):
        # base_url z.B.:
        # https://bwsyncandshare.kit.edu/remote.php/dav/files/UUID%40bwidm.scc.kit.edu/
        # Wir speichern sie EXAKT wie angegeben (nicht verändern!)
        self.base_url = base_url if base_url.endswith("/") else base_url + "/"
        self.auth     = HTTPBasicAuth(username, password)
        self.session  = requests.Session()
        self.session.auth = self.auth
        # Standard-Header für alle Requests
        self.session.headers.update({
            "User-Agent": "OCR-Extractor/1.0",
        })

    # ── URL-Aufbau ─────────────────────────────────────────────────────────────

    def _url(self, remote_path: str) -> str:
        """
        Hängt remote_path an base_url.
        "/" oder "" → base_url (Benutzer-Root)
        "/captures"  → base_url + "captures/"
        "/captures/20251104/file.mp4" → base_url + "captures/20251104/file.mp4"
        """
        clean = remote_path.strip("/")
        if not clean:
            return self.base_url
        # Letzter Teil: Ordner bekommt trailing slash, Datei nicht
        last = clean.split("/")[-1]
        has_ext = "." in last and not last.startswith(".")
        suffix = "" if has_ext else "/"
        return self.base_url + clean + suffix

    def _url_file(self, remote_path: str) -> str:
        """URL für Dateien — nie trailing slash."""
        clean = remote_path.strip("/")
        if not clean:
            return self.base_url.rstrip("/")
        return self.base_url + clean

    # ── Verbindungstest ────────────────────────────────────────────────────────

    def test_connection(self) -> tuple[bool, str]:
        """
        Testet Verbindung mit OPTIONS (kein PROPFIND nötig).
        OPTIONS funktioniert ohne spezielle Berechtigungen.
        """
        try:
            # Erst OPTIONS versuchen — das ist immer erlaubt
            r = self.session.options(
                self.base_url,
                timeout=10,
            )
            if r.status_code in (200, 204, 207):
                return True, ""

            # Fallback: PROPFIND mit Depth 0
            r2 = self.session.request(
                "PROPFIND",
                self.base_url,
                headers={
                    "Depth": "0",
                    "Content-Type": "application/xml",
                },
                data="""<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/></d:prop></d:propfind>""",
                timeout=10,
            )
            if r2.status_code in (200, 207):
                return True, ""
            if r2.status_code == 401:
                return False, "Authentifizierung fehlgeschlagen (401). Username/Passwort prüfen."
            if r2.status_code == 403:
                return False, f"Zugriff verweigert (403). Tipp: URL muss mit dem Benutzerordner enden (inkl. UUID)."
            if r2.status_code == 404:
                return False, "URL nicht gefunden (404). Pfad prüfen."
            return False, f"HTTP {r2.status_code}"

        except requests.exceptions.ConnectionError as e:
            return False, f"Verbindungsfehler: {e}"
        except requests.exceptions.Timeout:
            return False, "Timeout — Server nicht erreichbar."
        except Exception as e:
            return False, str(e)

    # ── Verzeichnis auflisten ──────────────────────────────────────────────────

    def list_files(self, remote_dir: str = "/") -> tuple[bool, list[str] | str]:
        """
        Listet Verzeichnisinhalt auf.
        Gibt (True, ["ordner/", "datei.txt", ...]) zurück.
        Einträge mit "/" am Ende = Ordner, ohne = Datei.
        """
        try:
            url = self._url(remote_dir)
            r = self.session.request(
                "PROPFIND",
                url,
                headers={
                    "Depth": "1",
                    "Content-Type": "application/xml; charset=utf-8",
                },
                data="""<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="DAV:">
  <d:prop>
    <d:resourcetype/>
    <d:displayname/>
    <d:getcontentlength/>
  </d:prop>
</d:propfind>""",
                timeout=20,
            )

            if r.status_code not in (207, 200):
                return False, f"HTTP {r.status_code}"

            root_xml = ET.fromstring(r.text)
            ns = {"d": "DAV:"}
            items = []

            responses = root_xml.findall("d:response", ns)
            # Ersten Eintrag überspringen = das Verzeichnis selbst
            for resp in responses[1:]:
                href_el = resp.find("d:href", ns)
                if href_el is None or not href_el.text:
                    continue

                # href dekodieren (%40 → @, %20 → Leerzeichen usw.)
                href = unquote(href_el.text)
                name = href.rstrip("/").split("/")[-1]
                if not name:
                    continue

                is_dir = resp.find(".//d:resourcetype/d:collection", ns) is not None
                items.append(name + "/" if is_dir else name)

            return True, sorted(items, key=lambda x: (not x.endswith("/"), x.lower()))

        except ET.ParseError as e:
            return False, f"XML-Parse-Fehler: {e}"
        except Exception as e:
            return False, str(e)

    # ── Download ───────────────────────────────────────────────────────────────

    def download_file(self, remote_path: str, local_path: str) -> tuple[bool, str]:
        """Lädt eine Datei herunter."""
        try:
            r = self.session.get(
                self._url_file(remote_path),
                stream=True,
                timeout=120,
            )
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
        """Lädt einen String als Datei hoch."""
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
            return False, f"HTTP {r.status_code}: {r.text[:300]}"
        except Exception as e:
            return False, str(e)

    def upload_bytes(self, data: bytes, remote_path: str,
                     content_type: str = "application/octet-stream") -> tuple[bool, str]:
        """Lädt Bytes als Datei hoch."""
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
            return False, f"HTTP {r.status_code}: {r.text[:300]}"
        except Exception as e:
            return False, str(e)

    def upload_file(self, local_path: str, remote_path: str) -> tuple[bool, str]:
        """Lädt eine lokale Datei hoch."""
        self._ensure_dirs(remote_path)
        try:
            with open(local_path, "rb") as f:
                r = self.session.put(
                    self._url_file(remote_path),
                    data=f,
                    timeout=120,
                )
            if r.status_code in (200, 201, 204):
                return True, ""
            return False, f"HTTP {r.status_code}: {r.text[:300]}"
        except Exception as e:
            return False, str(e)

    def delete_file(self, remote_path: str) -> tuple[bool, str]:
        """Löscht eine Datei."""
        try:
            r = self.session.delete(self._url_file(remote_path), timeout=15)
            if r.status_code in (200, 204, 404):
                return True, ""
            return False, f"HTTP {r.status_code}"
        except Exception as e:
            return False, str(e)

    # ── Ordner anlegen ─────────────────────────────────────────────────────────

    def _ensure_dirs(self, remote_path: str) -> None:
        """Legt alle übergeordneten Ordner via MKCOL an."""
        parts = PurePosixPath(remote_path.strip("/")).parts
        if len(parts) <= 1:
            return
        path_so_far = ""
        for part in parts[:-1]:
            path_so_far += "/" + part
            try:
                self.session.request(
                    "MKCOL",
                    self._url_file(path_so_far),
                    timeout=10,
                )
                # 201 = neu, 405 = existiert bereits — beides OK
            except Exception:
                pass
