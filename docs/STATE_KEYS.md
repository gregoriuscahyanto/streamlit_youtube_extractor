# Streamlit Session State Keys

This document tracks shared keys that cross module boundaries. Add new cross-tab keys here.

| Prefix | Owner | Purpose |
| --- | --- | --- |
| `r2_*` | setup/sync/storage | Cloudflare R2 connection and listing state |
| `local_*` | setup/sync/storage | Local storage adapter state |
| `sync_*` | sync tab | Reduced frame/audio sync workflow |
| `mat_*` | MAT selection tab | Selected MAT file and scan state |
| `roi_*` | ROI setup tab | ROI editor, OCR probe, save/load state |
| `audio_*` | audio tab | Audio/RPM background analysis state |
| `track_*` | ROI Setup tab | Track calibration and detection outputs |
| `tab_default`, `active_main_tab` | app shell | Navigation behavior |
