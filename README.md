---
title: streamlit_youtube_extractor
emoji: "ðŸŽ¬"
colorFrom: blue
colorTo: indigo
sdk: streamlit
sdk_version: "1.35.0"
python_version: "3.11"
app_file: app.py
pinned: false
---

# OCR Extractor v2 Ã¢â‚¬â€ ROI + Track-Analyse

Streamlit-App zur interaktiven ROI-Auswahl und Track-Minimap-Analyse.  
Ergebnisse werden als **JSON und MAT** parallel gespeichert Ã¢â‚¬â€ lokal und auf **bwSyncAndShare/Nextcloud** via WebDAV.

---

## Features

### Tab 1 Ã¢â‚¬â€œ ROI Setup
- Video laden: lokal oder von WebDAV (`captures/<folder>/<folder>.mp4`)
- Start/Ende und Frame-Position scrubben
- ROIs definieren, bearbeiten, lÃƒÂ¶schen (alle MATLAB-ROI-Namen inkl. `track_minimap`)
- **Speichern als JSON + MAT** (gleichzeitig) Ã¢â€ â€™ `results/results_<folder>.{json,mat}`
- Vorherige Konfiguration laden: JSON lokal, JSON von WebDAV, MAT von WebDAV

### Tab 2 Ã¢â‚¬â€œ Track-Analyse
- **Referenz-Track** laden (Bild lokal oder von `reference_track_siesmann/`)
- **8-Punkte-Kalibrierung**: je 8 Punkte auf Minimap + Referenzkarte definieren
- **Homographie-Berechnung** (RANSAC): Minimap Ã¢â€ â€™ Referenzkarte
- **ÃƒÅ“berlagerungsvisualisierung**: transformierte Minimap auf Referenzkarte
- **RÃƒÂ¼ckprojektionsfehler** fÃƒÂ¼r alle 8 Punkte (Abstand in Pixel)
- **Bewegenden Punkt** erkennen (HSV-Farberkennung, frei konfigurierbar)
- Verlaufstabelle der erkannten Positionen (t, x, y)

---

## Ordnerstruktur auf Nextcloud

```
<root>/
Ã¢â€Å“Ã¢â€â‚¬Ã¢â€â‚¬ captures/
Ã¢â€â€š   Ã¢â€Å“Ã¢â€â‚¬Ã¢â€â‚¬ 20251104_202910/
Ã¢â€â€š   Ã¢â€â€š   Ã¢â€Å“Ã¢â€â‚¬Ã¢â€â‚¬ 20251104_202910.mp4
Ã¢â€â€š   Ã¢â€â€š   Ã¢â€â€Ã¢â€â‚¬Ã¢â€â‚¬ 20251104_202910.wav
Ã¢â€â€š   Ã¢â€â€Ã¢â€â‚¬Ã¢â€â‚¬ 20251201_143022/
Ã¢â€â€š       Ã¢â€Å“Ã¢â€â‚¬Ã¢â€â‚¬ 20251201_143022.mp4
Ã¢â€â€š       Ã¢â€â€Ã¢â€â‚¬Ã¢â€â‚¬ 20251201_143022.wav
Ã¢â€Å“Ã¢â€â‚¬Ã¢â€â‚¬ results/
Ã¢â€â€š   Ã¢â€Å“Ã¢â€â‚¬Ã¢â€â‚¬ results_20251104_202910.mat   Ã¢â€ Â MATLAB-kompatibel
Ã¢â€â€š   Ã¢â€Å“Ã¢â€â‚¬Ã¢â€â‚¬ results_20251104_202910.json  Ã¢â€ Â fÃƒÂ¼r Streamlit / zukÃƒÂ¼nftige Python-Pipeline
Ã¢â€â€š   Ã¢â€â€Ã¢â€â‚¬Ã¢â€â‚¬ ...
Ã¢â€â€Ã¢â€â‚¬Ã¢â€â‚¬ reference_track_siesmann/
    Ã¢â€â€Ã¢â€â‚¬Ã¢â€â‚¬ track.png                     Ã¢â€ Â Referenzkarte
```

Die App legt diese Struktur automatisch an (MKCOL), wenn sie noch nicht existiert.

---

## Setup

```bash
git clone https://github.com/DEIN-USER/ocr-extractor.git
cd ocr-extractor
pip install -r requirements.txt
streamlit run app.py
```

## Deployment auf Streamlit Community Cloud

1. GitHub-Repo (public oder private)
2. https://share.streamlit.io Ã¢â€ â€™ New App Ã¢â€ â€™ `app.py`
3. Optional: Secrets hinterlegen:

```toml
# .streamlit/secrets.toml (NIE committen!)
[webdav]
url      = "https://bwsyncandshare.kit.edu/remote.php/dav/files/DEIN_USER/"
username = "DEIN_USER"
password = "APP_PASSWORT_NICHT_KIT_PASSWORT"
root     = "/"
```

---

## MAT-Format (MATLAB-kompatibel)

```matlab
% Laden in MATLAB:
S = load('results_20251104_202910.mat');
rr = S.recordResult;

rr.ocr.params.start_s        % Startzeit
rr.ocr.params.end_s          % Endzeit
rr.ocr.roi_table              % ROI-Tabelle
rr.ocr.trkCalSlim.ref_pts     % Referenzpunkte
rr.ocr.trkCalSlim.minimap_pts % Minimap-Punkte
rr.metadata.video             % Videoname
```

---

## JSON-Format

```json
{
  "params": { "start_s": 10.5, "end_s": 95.2 },
  "roi_table": [
    { "name_roi": "v_Fzg_kmph", "roi": [842,45,120,55],
      "fmt": "integer", "pattern": "", "max_scale": 1.2 },
    { "name_roi": "track_minimap", "roi": [10,10,300,200],
      "fmt": "any", "pattern": "", "max_scale": 1.0 }
  ],
  "video": { "width": 1920, "height": 1080, "fps": 60.0, "duration": 120.5 },
  "track": {
    "ref_pts":     [[x1,y1], ..., [x8,y8]],
    "minimap_pts": [[x1,y1], ..., [x8,y8]],
    "moving_pt_color_range": {"h_lo":0,"h_hi":30,"s_lo":150,"s_hi":255,
                               "v_lo":150,"v_hi":255}
  }
}
```

---

## Dateien

```
ocr_extractor_v2/
Ã¢â€Å“Ã¢â€â‚¬Ã¢â€â‚¬ app.py              Ã¢â€ Â Haupt-App (Tab1: ROI, Tab2: Track)
Ã¢â€Å“Ã¢â€â‚¬Ã¢â€â‚¬ track_analysis.py   Ã¢â€ Â Homographie, Farberkennung, Overlay
Ã¢â€Å“Ã¢â€â‚¬Ã¢â€â‚¬ webdav_client.py    Ã¢â€ Â WebDAV via requests
Ã¢â€Å“Ã¢â€â‚¬Ã¢â€â‚¬ storage.py          Ã¢â€ Â Ordnerstruktur-Logik
Ã¢â€Å“Ã¢â€â‚¬Ã¢â€â‚¬ requirements.txt
Ã¢â€Å“Ã¢â€â‚¬Ã¢â€â‚¬ .streamlit/config.toml
Ã¢â€Å“Ã¢â€â‚¬Ã¢â€â‚¬ .gitignore
Ã¢â€â€Ã¢â€â‚¬Ã¢â€â‚¬ README.md
```

