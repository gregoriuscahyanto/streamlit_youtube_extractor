---
title: streamlit_youtube_extractor
emoji: "🚀"
colorFrom: blue
colorTo: indigo
sdk: streamlit
sdk_version: "1.35.0"
python_version: "3.11"
app_file: app.py
pinned: false
---
# OCR Extractor v2 ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â ROI + Track-Analyse

Streamlit-App zur interaktiven ROI-Auswahl und Track-Minimap-Analyse.  
Ergebnisse werden als **JSON und MAT** parallel gespeichert ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â lokal und auf **bwSyncAndShare/Nextcloud** via WebDAV.

---

## Features

### Tab 1 ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Å“ ROI Setup
- Video laden: lokal oder von WebDAV (`captures/<folder>/<folder>.mp4`)
- Start/Ende und Frame-Position scrubben
- ROIs definieren, bearbeiten, lÃƒÆ’Ã‚Â¶schen (alle MATLAB-ROI-Namen inkl. `track_minimap`)
- **Speichern als JSON + MAT** (gleichzeitig) ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ `results/results_<folder>.{json,mat}`
- Vorherige Konfiguration laden: JSON lokal, JSON von WebDAV, MAT von WebDAV

### Tab 2 ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Å“ Track-Analyse
- **Referenz-Track** laden (Bild lokal oder von `reference_track_siesmann/`)
- **8-Punkte-Kalibrierung**: je 8 Punkte auf Minimap + Referenzkarte definieren
- **Homographie-Berechnung** (RANSAC): Minimap ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ Referenzkarte
- **ÃƒÆ’Ã…â€œberlagerungsvisualisierung**: transformierte Minimap auf Referenzkarte
- **RÃƒÆ’Ã‚Â¼ckprojektionsfehler** fÃƒÆ’Ã‚Â¼r alle 8 Punkte (Abstand in Pixel)
- **Bewegenden Punkt** erkennen (HSV-Farberkennung, frei konfigurierbar)
- Verlaufstabelle der erkannten Positionen (t, x, y)

---

## Ordnerstruktur auf Nextcloud

```
<root>/
ÃƒÂ¢Ã¢â‚¬ÂÃ…â€œÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ captures/
ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬Å¡   ÃƒÂ¢Ã¢â‚¬ÂÃ…â€œÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ 20251104_202910/
ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬Å¡   ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬Å¡   ÃƒÂ¢Ã¢â‚¬ÂÃ…â€œÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ 20251104_202910.mp4
ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬Å¡   ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬Å¡   ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬ÂÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ 20251104_202910.wav
ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬Å¡   ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬ÂÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ 20251201_143022/
ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬Å¡       ÃƒÂ¢Ã¢â‚¬ÂÃ…â€œÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ 20251201_143022.mp4
ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬Å¡       ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬ÂÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ 20251201_143022.wav
ÃƒÂ¢Ã¢â‚¬ÂÃ…â€œÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ results/
ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬Å¡   ÃƒÂ¢Ã¢â‚¬ÂÃ…â€œÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ results_20251104_202910.mat   ÃƒÂ¢Ã¢â‚¬Â Ã‚Â MATLAB-kompatibel
ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬Å¡   ÃƒÂ¢Ã¢â‚¬ÂÃ…â€œÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ results_20251104_202910.json  ÃƒÂ¢Ã¢â‚¬Â Ã‚Â fÃƒÆ’Ã‚Â¼r Streamlit / zukÃƒÆ’Ã‚Â¼nftige Python-Pipeline
ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬Å¡   ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬ÂÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ ...
ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬ÂÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ reference_track_siesmann/
    ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬ÂÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ track.png                     ÃƒÂ¢Ã¢â‚¬Â Ã‚Â Referenzkarte
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
2. https://share.streamlit.io ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ New App ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ `app.py`
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
ÃƒÂ¢Ã¢â‚¬ÂÃ…â€œÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ app.py              ÃƒÂ¢Ã¢â‚¬Â Ã‚Â Haupt-App (Tab1: ROI, Tab2: Track)
ÃƒÂ¢Ã¢â‚¬ÂÃ…â€œÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ track_analysis.py   ÃƒÂ¢Ã¢â‚¬Â Ã‚Â Homographie, Farberkennung, Overlay
ÃƒÂ¢Ã¢â‚¬ÂÃ…â€œÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ webdav_client.py    ÃƒÂ¢Ã¢â‚¬Â Ã‚Â WebDAV via requests
ÃƒÂ¢Ã¢â‚¬ÂÃ…â€œÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ storage.py          ÃƒÂ¢Ã¢â‚¬Â Ã‚Â Ordnerstruktur-Logik
ÃƒÂ¢Ã¢â‚¬ÂÃ…â€œÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ requirements.txt
ÃƒÂ¢Ã¢â‚¬ÂÃ…â€œÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ .streamlit/config.toml
ÃƒÂ¢Ã¢â‚¬ÂÃ…â€œÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ .gitignore
ÃƒÂ¢Ã¢â‚¬ÂÃ¢â‚¬ÂÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ README.md
```

