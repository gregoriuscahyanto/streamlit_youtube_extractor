# Product Notes

The app supports a workflow for motorsport video analysis:

1. Select or synchronize capture assets from local storage and Cloudflare R2.
2. Pick a MAT file and locate the corresponding reduced video/audio assets.
3. Define OCR ROIs, including an optional `track_minimap` ROI.
4. Persist JSON and MATLAB-compatible MAT output.
5. Run track/minimap and audio RPM analysis.

Primary users need fast iteration and visible progress for long-running media tasks. Do not hide long operations behind silent reruns.
