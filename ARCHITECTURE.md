# Architecture

## Goal
`streamlit_youtube_extractor` is a Streamlit application for selecting OCR regions of interest, synchronizing reduced video/audio assets, running OCR/audio RPM workflows, and exporting MATLAB-compatible `recordResult` structures.

## Layers

```text
UI shell
  app.py
  app_tabs/*.py

Application services
  backend.py
  storage.py
  local_storage.py
  r2_client.py

Domain utilities
  roi_utils.py
  track_analysis.py
  ocr_diagnostic.py

External formats and assets
  *.mat, *.json, videos, audio, reference tracks
```

## Dependency rules
- `app.py` wires session state, navigation, global constants, and tab modules.
- `app_tabs/*` may import application services and domain utilities, but should not implement persistent storage formats directly when a backend helper exists.
- `backend.py` owns MAT/JSON structure creation and decoding helpers.
- `roi_utils.py`, `track_analysis.py`, and `ocr_diagnostic.py` should remain import-safe and testable without Streamlit.
- Tests may import any production module but must avoid real cloud/network dependencies unless explicitly marked.

## Boundary contracts
- ROI coordinates are stored as pixel-space `x`, `y`, `w`, `h` and clamped to video dimensions before persistence.
- MAT export must preserve the `recordResult.ocr.roi_table` and `recordResult.ocr.roi_table_raw` semantics expected by the MATLAB reference workflow.
- The legacy MATLAB `OCRExtractor.m` remains the compatibility reference for field names and OCR parameter shape.

## Agent readability rules
- Public helper functions should have narrow inputs/outputs and docstrings when behavior is non-obvious.
- Cross-tab state keys should be documented in `docs/STATE_KEYS.md` before they are reused across modules.
- Long functions should be split when a pure helper can be tested independently.
