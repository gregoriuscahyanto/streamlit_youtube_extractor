---
title: streamlit_youtube_extractor
emoji: 🚀
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 8501
pinned: false
---

# OCR Extractor v2 - ROI + Track-Analyse

Streamlit-App zur interaktiven ROI-Auswahl und Track-Minimap-Analyse.  
Ergebnisse werden als **JSON und MAT** parallel gespeichert - lokal und optional auf **bwSyncAndShare/Nextcloud** via WebDAV.

---

## Features

### Tab 1 - ROI Setup
- Video laden: lokal oder von WebDAV (`captures/<folder>/<folder>.mp4`)
- Start/Ende und Frame-Position scrubben
- ROIs definieren, bearbeiten, loeschen (inkl. `track_minimap`)
- Speichern als JSON + MAT (gleichzeitig) nach `results/results_<folder>.{json,mat}`
- Vorherige Konfiguration laden: JSON lokal, JSON von WebDAV, MAT von WebDAV

### Tab 2 - Track-Analyse
- Referenz-Track laden (lokal oder aus `reference_track_siesmann/`)
- 8-Punkte-Kalibrierung: je 8 Punkte auf Minimap und Referenzkarte
- Homographie-Berechnung (RANSAC): Minimap -> Referenzkarte
- Ueberlagerungsvisualisierung auf der Referenzkarte
- Rueckprojektionsfehler fuer alle 8 Punkte (Pixel)
- Bewegenden Punkt erkennen (HSV-Farberkennung, konfigurierbar)
- Verlaufstabelle erkannter Positionen (t, x, y)

---

## Ordnerstruktur auf Nextcloud

```text
<root>/
├─ captures/
│  ├─ 20251104_202910/
│  │  ├─ 20251104_202910.mp4
│  │  └─ 20251104_202910.wav
│  └─ 20251201_143022/
│     ├─ 20251201_143022.mp4
│     └─ 20251201_143022.wav
├─ results/
│  ├─ results_20251104_202910.mat
│  ├─ results_20251104_202910.json
│  └─ ...
└─ reference_track_siesmann/
   └─ track.png
```

Die App legt benoetigte Ordner auf WebDAV bei Bedarf automatisch an.

---

## Lokales Setup

```bash
git clone <DEIN_REPO_URL>
cd streamlit_youtube_extractor
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
# source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

---

## Konfiguration via Secrets

### Lokal (`.streamlit/secrets.toml`)

```toml
[webdav]
url = "https://bwsyncandshare.kit.edu/remote.php/dav/files/DEIN_USER/"
username = "DEIN_USER"
password = "DEIN_APP_PASSWORT"
remote_dir = "streamlit_youtube_extractor_storage"

[gdrive]
enabled = false
```

### Streamlit Cloud
- Secrets in den App-Einstellungen unter `Secrets` hinterlegen (gleiche Keys wie oben).

### Hugging Face Spaces
- Space Variables/Secrets im HF-UI setzen (falls benoetigt).
- Deployment erfolgt ueber GitHub Actions Sync-Workflow.

---

## Deployment

### Streamlit Community Cloud
1. Repo auf GitHub pushen
2. App in Streamlit Cloud mit `app.py` starten
3. Secrets im Cloud-UI setzen

### Hugging Face Space (Docker)
- Dieses Repo enthaelt Docker-Deployment (`Dockerfile`, `sdk: docker`, `app_port: 8501`).
- Bei jedem Push auf `main` kann per GitHub Action in den Space synchronisiert werden.

---

## CLI und Backend

- `backend.py`: zentrale Logik (wird von GUI und CLI genutzt)
- `cli.py`: Kommandozeilen-Zugriff fuer lokale Tests/Debugging
- `app.py`: ausschliesslich GUI (Streamlit)

---

## Hinweise zur WebDAV-Fehlersuche

Wenn lokal funktioniert, aber Cloud `403` oder Timeout zeigt:
- App-Passwort statt Login-Passwort verwenden
- Korrekte WebDAV-URL mit User-Pfad pruefen
- Mit PROPFIND testen (Depth: 1)
- Netzwerk/Policy-Unterschiede zwischen Cloud-Provider und lokal beachten