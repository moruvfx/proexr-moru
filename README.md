# ProEXR Viewer

Professional, read-only media viewer and player for VFX artists, compositors and editors.
Opens EXR (multi-layer, multi-part), DPX, TIFF, TGA, HDR, PNG, JPEG, image sequences and video
(MP4, MOV, ProRes, H.264, H.265, MKV, AVI...). Source files are never modified.

## Run on Windows

1. Install Python 3.11 or newer from python.org (tick "Add python.exe to PATH").
2. Install uv once, in PowerShell: `py -m pip install uv`
3. In the project folder:

```powershell
uv sync
uv run proexr                       # empty window, drop files or folders in
uv run proexr D:\shots\sh010\comp.1001.exr D:\refs\edit.mov
```

Without uv: `py -m venv .venv`, `.venv\Scripts\activate`, `pip install -e .`, then `proexr`.

## What it does (phase 1)

- Image sequences are detected automatically (`shot.1001.exr`, `plate_0001.dpx`...); gaps hold the previous frame and show red on the timeline.
- EXR layers and passes appear in the Layer menu; channels RGB, R, G, B, A and luminance.
- Exposure, gamma, gain, offset, contrast, saturation and colour balance are applied on the GPU in real time.
- View transforms: Raw, sRGB, Rec.709, ACES filmic (approximation). Full OCIO comes in phase 2.
- Smooth playback: frames are decoded ahead of the playhead on worker threads into a RAM cache (green bar on the timeline). Realtime mode skips late frames, otherwise every frame is shown.
- Play forward/reverse, loop, ping-pong, play once, in/out points, speed 0.1x-4x, any frame rate.
- Zoom (wheel), pan (drag), fit (F), 1:1 pixels (1), safe areas, thirds grid, clipping highlight, full screen, hide panels (Tab).
- Pixel values under the cursor in the status bar; file metadata in the Info panel.
- Dockable panels; the layout is remembered.

## Shortcuts

Space play/pause, J/K/L reverse/stop/forward, Left/Right step, Home/End in/out, I/O set in/out,
F fit, 1 actual pixels, R/G/B/A/C/Y channels, Ctrl+Up/Down exposure, Ctrl+Left/Right layer, F11 full screen.
Help > Keyboard shortcuts lists all of them; Help > Edit shortcuts file remaps any key.

## Settings

- Settings > Frame cache size: RAM used for decoded frames (default 30% of RAM, at most 16 GB).
- Settings > Hardware video decoding: NVDEC/D3D11 when the FFmpeg build supports it, software otherwise.

## Development

```bash
uv sync
uv run pytest            # on Linux without a display: xvfb-run -a uv run pytest
uv run ruff check src tests
```

Layout: `src/proexr/media` reads files, `src/proexr/playback` holds the frame cache and playback clock (no Qt), `src/proexr/ui` holds the Qt widgets and the GLSL viewer. Project conventions are in `.agents/project-rules.md`.
