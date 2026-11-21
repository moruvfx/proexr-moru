## ProEXR Viewer

Download **ProEXR-Viewer-Setup-x.y.z.exe**, run it, and open ProEXR Viewer from the Desktop shortcut.
No Python needed. Installs for the current user (no admin prompt). The portable .zip runs without installing.

The app checks this page once a day and offers to install new versions (Help > Check for updates).

### 0.2.1
- Fixed garbled text in the viewer on NVIDIA drivers.
- Video is kept in YUV and converted on the GPU: half the RAM per frame and half the upload.
- Read/upload timings in the status bar and Help > Copy performance report.

### Highlights
- EXR multi-layer/multi-part, DPX, TIFF, PNG, JPEG, image sequences, MP4/MOV/ProRes/H.264/H.265/MKV
- Smooth playback with RAM cache that adapts to free memory, NVIDIA NVDEC / D3D11 video decoding
- GPU colour: exposure, gamma, grade, channels, OCIO / ACES (built-in ACES 2.1 configs or your own config.ocio)
- A/B compare: wipe, side by side, difference
- Scopes: waveform, RGB parade, histogram, vectorscope, pixel inspector
- Thumbnail browser, playlists, safe areas and aspect guides, audio for video files
