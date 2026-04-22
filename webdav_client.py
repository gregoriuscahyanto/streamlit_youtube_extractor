"""
WebDAV-Client fuer bwSyncAndShare (Nextcloud).
base_url = vollstaendige URL zum Benutzerordner, z.B.:
  https://bwsyncandshare.kit.edu/remote.php/dav/files/UUID%40bwidm.scc.kit.edu/
"""
from __future__ import annotations
import requests
from requests.auth import HTTPBasicAuth
from pathlib import PurePosixPath
import xml.etree.ElementTree as ET
from urllib.parse import quote, unquote, urlsplit


class WebDAVClient:

    def __init__(self, base_url: str, username: str, password: str):
        # base_url endet immer mit /
        self.base_url = self._normalize_base_url(base_url, username)
        self.auth     = HTTPBasicAuth(username, password)
        self.session  = requests.Session()
        self.session.auth = self.auth
        self.session.headers.update({"User-Agent": "OCR-Extractor/1.0"})
        self.last_list_debug = ""

    def _normalize_base_url(self, base_url: str, username: str) -> str:
        """
        Akzeptiert sowohl die generische DAV-URL .../files/ als auch
        die benutzerspezifische URL .../files/<username>/.
        """
        clean = (base_url or "").strip().rstrip("/")
        if not clean:
            return ""

        parsed = urlsplit(clean)
        path = parsed.path.rstrip("/")
        username_raw = (username or "").strip()
        username_encoded = quote(username_raw, safe="")

        if path.endswith("/remote.php/dav/files"):
            clean = clean + "/" + username_encoded
        return clean.rstrip("/") + "/"

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

    def _normalize_href_path(self, href: str) -> str:
        """Normalisiert HREF/URL auf einen vergleichbaren Pfad ohne abschliessenden Slash."""
        parsed = urlsplit(href)
        path = unquote(parsed.path or href).strip()
        if not path:
            return "/"
        return path.rstrip("/") or "/"

    def _relative_href_name(self, href: str, requested_path: str) -> str:
        """Extrahiert den direkten Kindnamen relativ zum angefragten Verzeichnis."""
        href_path = self._normalize_href_path(href)
        if href_path == requested_path:
            return ""

        prefix = requested_path.rstrip("/") + "/"
        if not href_path.startswith(prefix):
            return ""

        relative = href_path[len(prefix):].strip("/")
        if not relative or "/" in relative:
            return ""
        return relative

    def _parse_propfind_items(self, response_text: str, requested_url: str) -> list[str]:
        root_xml = ET.fromstring(response_text)
        ns = {"d": "DAV:"}
        responses = root_xml.findall("d:response", ns)
        items = []
        seen = set()
        requested_path = self._normalize_href_path(requested_url)

        for resp in responses:
            href_el = resp.find("d:href", ns)
            if href_el is None or not href_el.text:
                continue
            raw_href = unquote(href_el.text)
            name = self._relative_href_name(raw_href, requested_path)
            if not name:
                continue
            is_dir = (
                resp.find(".//d:resourcetype/d:collection", ns) is not None
                or raw_href.rstrip().endswith("/")
            )
            item_name = name + "/" if is_dir else name
            if item_name in seen:
                continue
            seen.add(item_name)
            items.append(item_name)

        items.sort(key=lambda x: (not x.endswith("/"), x.lower()))
        return items

    # ── Verbindungstest ────────────────────────────────────────────────────────

    def test_connection(self) -> tuple[bool, str]:
        """OPTIONS auf base_url — immer erlaubt, kein 403 Risiko."""
        try:
            r = self.session.options(self.base_url, timeout=10)
            if r.status_code in (200, 204, 207):
                return True, ""
            # Fallback PROPFIND
            r2 = self.session.request(
                "PROPFIND", self.base_url,
                headers={"Depth": "0", "Content-Type": "application/xml"},
                data='<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/></d:prop></d:propfind>',
                timeout=10)
            if r2.status_code in (200, 207): return True, ""
            if r2.status_code == 401: return False, "Authentifizierung fehlgeschlagen (401)."
            if r2.status_code == 403: return False, "Zugriff verweigert (403)."
            return False, f"HTTP {r2.status_code}"
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
            # Server-kompatibel: identisch zur funktionierenden curl-Abfrage
            body = (
                '<?xml version="1.0"?>'
                '<d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/></d:prop></d:propfind>'
            )
            urls_to_try = [url]
            if remote_dir.strip("/") == "" and url.endswith("/"):
                urls_to_try.append(url.rstrip("/"))

            last_error = "Keine Antwort."
            for candidate_url in urls_to_try:
                r = self.session.request(
                    "PROPFIND", candidate_url,
                    headers={
                        "Depth": "1",
                        "Content-Type": "application/xml",
                        "Accept": "application/xml",
                    },
                    data=body,
                    timeout=20)

                if r.status_code not in (207, 200):
                    last_error = f"HTTP {r.status_code} @ {candidate_url}"
                    continue

                items = self._parse_propfind_items(r.text, candidate_url)
                self.last_list_debug = f"url={candidate_url} items={items!r}"
                if items or len(urls_to_try) == 1 or candidate_url == urls_to_try[-1]:
                    return True, items

            self.last_list_debug = last_error
            return False, last_error

        except ET.ParseError as e:
            self.last_list_debug = f"XML-Fehler: {e}"
            return False, f"XML-Fehler: {e}"
        except Exception as e:
            self.last_list_debug = str(e)
            return False, str(e)

    # ── Download ───────────────────────────────────────────────────────────────

    def download_file(self, remote_path: str, local_path: str) -> tuple[bool, str]:
        try:
            r = self.session.get(self._build_url(remote_path), stream=True, timeout=120)
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
                timeout=30)
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
                timeout=120)
            if r.status_code in (200, 201, 204): return True, ""
            return False, f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as e:
            return False, str(e)

    def upload_file(self, local_path: str, remote_path: str) -> tuple[bool, str]:
        self._ensure_dirs(remote_path)
        try:
            with open(local_path, "rb") as f:
                r = self.session.put(self._build_url(remote_path), data=f, timeout=120)
            if r.status_code in (200, 201, 204): return True, ""
            return False, f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as e:
            return False, str(e)

    def delete_file(self, remote_path: str) -> tuple[bool, str]:
        try:
            r = self.session.delete(self._build_url(remote_path), timeout=15)
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
                self.session.request("MKCOL", self._build_url(path), timeout=10)
            except Exception:
                pass
