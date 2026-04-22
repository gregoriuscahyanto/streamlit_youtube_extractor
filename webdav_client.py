"""
WebDAV-Client fuer bwSyncAndShare (Nextcloud).
base_url = vollstaendige URL zum Benutzerordner, z.B.:
  https://bwsyncandshare.kit.edu/remote.php/dav/files/UUID%40bwidm.scc.kit.edu/
"""
from __future__ import annotations
import requests
from requests.adapters import HTTPAdapter
from requests.auth import HTTPBasicAuth
from urllib3.util.retry import Retry
from pathlib import PurePosixPath
import xml.etree.ElementTree as ET
from urllib.parse import quote, unquote


class WebDAVClient:

    def __init__(self, base_url: str, username: str, password: str):
        # base_url endet immer mit /
        self.base_url = self._normalize_base_url(base_url, username)
        self.auth     = HTTPBasicAuth(username, password)
        self.session  = requests.Session()
        self.session.auth = self.auth
        self.session.headers.update({"User-Agent": "OCR-Extractor/1.0"})
        self._timeout = (20, 120)  # connect/read timeout in Sekunden

        retry = Retry(
            total=3,
            connect=3,
            read=3,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "PUT", "DELETE", "PROPFIND", "MKCOL", "OPTIONS"}),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    @staticmethod
    def _normalize_base_url(base_url: str, username: str) -> str:
        """
        Akzeptiert beide Formen:
        1) .../remote.php/dav/files/
        2) .../remote.php/dav/files/<user>/
        Falls nur /files angegeben ist, wird <user> automatisch angehaengt.
        """
        base = (base_url or "").strip()
        if not base:
            return "/"

        trimmed = base.rstrip("/")
        low = trimmed.lower()
        if low.endswith("/remote.php/dav/files"):
            # Path-Segment kodieren (u.a. @ -> %40), wie bei funktionierendem curl.
            user_seg = quote((username or "").strip(), safe="")
            if user_seg:
                return f"{trimmed}/{user_seg}/"
        return trimmed + "/"

    def _request(self, method: str, url: str, **kwargs):
        if "timeout" not in kwargs:
            kwargs["timeout"] = self._timeout
        return self.session.request(method, url, **kwargs)

    def _build_url(self, remote_path: str) -> str:
        """
        Haengt remote_path an base_url.
        remote_path="" oder "/" -> base_url (kein extra Slash)
        remote_path="captures"  -> base_url + "captures/"
        remote_path="captures/file.mp4" -> base_url + "captures/file.mp4"
        """
        clean = remote_path.strip("/")
        if not clean:
            return self.base_url
        # Datei = hat Erweiterung im letzten Segment
        last = clean.split("/")[-1]
        is_file = "." in last and not last.startswith(".")
        return self.base_url + clean + ("" if is_file else "/")

    # ── Verbindungstest ────────────────────────────────────────────────────────

    def test_connection(self) -> tuple[bool, str]:
        """Verbindungstest per PROPFIND (entspricht typischer Nextcloud-WebDAV-Pruefung)."""
        try:
            r = self._request(
                "PROPFIND",
                self.base_url,
                headers={"Depth": "0", "Content-Type": "application/xml; charset=utf-8"},
                data='<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/></d:prop></d:propfind>',
            )
            if r.status_code in (200, 207):
                return True, ""
            if r.status_code == 401:
                return False, "Authentifizierung fehlgeschlagen (401)."
            if r.status_code == 403:
                return False, "Zugriff verweigert (403)."
            return False, f"HTTP {r.status_code}"
        except requests.exceptions.ConnectionError as e:
            return False, f"Verbindungsfehler: {e}"
        except requests.exceptions.Timeout:
            return False, "Timeout."
        except Exception as e:
            return False, str(e)

    # ── Verzeichnis auflisten ──────────────────────────────────────────────────

    def list_files(self, remote_dir: str = "") -> tuple[bool, list[str] | str]:
        """
        Listet Inhalt von remote_dir auf.
        Gibt (True, ["ordner/", "datei.txt", ...]) zurueck —
        relativ zu remote_dir, Ordner mit trailing /, Dateien ohne.
        """
        try:
            url = self._build_url(remote_dir)
            r = self._request(
                "PROPFIND", url,
                headers={"Depth": "1", "Content-Type": "application/xml; charset=utf-8"},
                data="""<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="DAV:">
  <d:prop><d:resourcetype/><d:displayname/></d:prop>
</d:propfind>""",
            )

            if r.status_code not in (207, 200):
                return False, f"HTTP {r.status_code}"

            root_xml  = ET.fromstring(r.text)
            ns        = {"d": "DAV:"}
            responses = root_xml.findall("d:response", ns)
            items     = []

            # Ersten Eintrag ueberspringen = das Verzeichnis selbst
            for resp in responses[1:]:
                href_el = resp.find("d:href", ns)
                if href_el is None or not href_el.text:
                    continue
                href   = unquote(href_el.text)          # %40 -> @, %20 -> Leerzeichen
                name   = href.rstrip("/").split("/")[-1]
                if not name:
                    continue
                is_dir = resp.find(".//d:resourcetype/d:collection", ns) is not None
                items.append(name + "/" if is_dir else name)

            # Ordner zuerst, dann Dateien, alphabetisch
            items.sort(key=lambda x: (not x.endswith("/"), x.lower()))
            return True, items

        except ET.ParseError as e:
            return False, f"XML-Fehler: {e}"
        except Exception as e:
            return False, str(e)

    # ── Download ───────────────────────────────────────────────────────────────

    def download_file(self, remote_path: str, local_path: str) -> tuple[bool, str]:
        try:
            r = self.session.get(self._build_url(remote_path), stream=True, timeout=self._timeout)
            if r.status_code == 200:
                with open(local_path, "wb") as f:
                    for chunk in r.iter_content(65536):
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
                self._build_url(remote_path),
                data=content.encode(encoding),
                headers={"Content-Type": "application/json; charset=utf-8"},
                timeout=self._timeout)
            if r.status_code in (200, 201, 204): return True, ""
            return False, f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as e:
            return False, str(e)

    def upload_bytes(self, data: bytes, remote_path: str,
                     content_type: str = "application/octet-stream") -> tuple[bool, str]:
        self._ensure_dirs(remote_path)
        try:
            r = self.session.put(
                self._build_url(remote_path),
                data=data,
                headers={"Content-Type": content_type},
                timeout=self._timeout)
            if r.status_code in (200, 201, 204): return True, ""
            return False, f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as e:
            return False, str(e)

    def upload_file(self, local_path: str, remote_path: str) -> tuple[bool, str]:
        self._ensure_dirs(remote_path)
        try:
            with open(local_path, "rb") as f:
                r = self.session.put(self._build_url(remote_path), data=f, timeout=self._timeout)
            if r.status_code in (200, 201, 204): return True, ""
            return False, f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as e:
            return False, str(e)

    def delete_file(self, remote_path: str) -> tuple[bool, str]:
        try:
            r = self.session.delete(self._build_url(remote_path), timeout=self._timeout)
            if r.status_code in (200, 204, 404): return True, ""
            return False, f"HTTP {r.status_code}"
        except Exception as e:
            return False, str(e)

    # ── Ordner anlegen ─────────────────────────────────────────────────────────

    def _ensure_dirs(self, remote_path: str) -> None:
        parts = PurePosixPath(remote_path.strip("/")).parts
        if len(parts) <= 1:
            return
        path = ""
        for part in parts[:-1]:
            path += "/" + part
            try:
                self._request("MKCOL", self._build_url(path))
            except Exception:
                pass
