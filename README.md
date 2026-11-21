# ProEXR Viewer

Professional, read-only media viewer and player for VFX artists, compositors and editors.
Opens EXR (multi-layer, multi-part), DPX, TIFF, TGA, HDR, PNG, JPEG, image sequences and video
(MP4, MOV, ProRes, H.264, H.265, MKV, AVI...). Source files are never modified.

## Install on Windows

Download `ProEXR-Viewer-Setup-x.y.z.exe` from [Releases](https://github.com/moruvfx/proexr-moru/releases/latest),
run it and start ProEXR Viewer from the Desktop shortcut. No Python needed; it installs for your user only
(no admin prompt). The app checks for new versions once a day and offers to install them
(Help > Check for updates). A portable `.zip` is attached to each release too.

## Run from source

```powershell
py -m pip install uv
uv sync
uv run proexr D:\shots\sh010\comp.1001.exr D:\refs\edit.mov
```

## Features

- Image sequences are detected automatically (`shot.1001.exr`, `plate_0001.dpx`...); gaps hold the previous frame and show red on the timeline.
- EXR layers and passes appear in the Layer menu; channels RGB, R, G, B, A and luminance.
- GPU colour: exposure, gamma, gain, offset, contrast, saturation and colour balance in real time.
- Colour management: OCIO with the built-in ACES 2.1 CG and Studio configs or any `config.ocio`; input, display and view per media.
- Compare A/B: B only, wipe (drag the line), side by side, difference. Right-click a media item to set it as B; Ctrl+B cycles B, `\` toggles.
- Scopes: waveform, RGB parade, histogram, vectorscope; Pixel panel with exact values and a 5x5 average.
- Smooth playback: frames are decoded ahead of the playhead on worker threads into a RAM cache (green bar on the timeline) that shrinks when free RAM runs low. Float images are cached as half to fit twice as many frames.
- Video decoding on the GPU (NVIDIA NVDEC, D3D11) when available, CPU otherwise; the status bar shows which. 8-bit 4:2:0 video stays in YUV and is converted to RGB in the shader, halving cache memory and upload size.
- The status bar shows read and upload time per frame; Help > Copy performance report gives the full picture to share when playback is slow. Audio plays during forward 1x playback (M mutes).
- Play forward/reverse, loop, ping-pong, play once, in/out points, speed 0.1x-4x, any frame rate.
- Browser panel with thumbnails; playlists (File > Save/Open playlist).
- Zoom (wheel), pan (drag), fit (F), 1:1 pixels (1), safe areas, thirds grid, aspect guides (2.39, 1.85, 16:9...), clipping highlight, full screen, hide panels (Tab).
- Dockable panels; the layout is remembered. Source files are only ever read.

## Shortcuts

Space play/pause, J/K/L reverse/stop/forward, Left/Right step, Home/End in/out, I/O set in/out,
F fit, 1 actual pixels, R/G/B/A/C/Y channels, Ctrl+Up/Down exposure, Ctrl+Left/Right layer, F11 full screen.
Help > Keyboard shortcuts lists all of them; Help > Edit shortcuts file remaps any key.

## Settings

- Settings > Frame cache size: RAM used for decoded frames (default 30% of RAM, at most 16 GB).
- Settings > Hardware video decoding: NVDEC/D3D11 when the FFmpeg build supports it, software otherwise.
- Settings > Clear frame cache frees the RAM held by decoded frames.

## Build the installer

GitHub Actions (`.github/workflows/build-windows.yml`) builds on every push and publishes a release for `v*` tags
or a manual run with "release" ticked. Locally on Windows:

```powershell
uv sync --group build
uv run python packaging/write_version_info.py
uv run pyinstaller packaging/proexr.spec --noconfirm
iscc /DAppVersion=0.2.0 packaging\installer.iss     # Inno Setup 6
```

## Development

```bash
uv sync
uv run pytest            # on Linux without a display: xvfb-run -a uv run pytest
uv run ruff check src tests
```

Layout: `src/proexr/media` reads files, `src/proexr/playback` holds the frame cache and playback clock (no Qt), `src/proexr/ui` holds the Qt widgets and the GLSL viewer. Project conventions are in `.agents/project-rules.md`.
