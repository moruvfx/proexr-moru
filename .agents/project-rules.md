# Project rules: ProEXR Viewer

> Provisional: generated for a new project. Re-run /vibecode-init once the first features exist.

## Stack
- Python 3.11+, PySide6 (Qt Widgets) desktop app, primary target Windows x64 with NVIDIA GPU.
- Rendering: OpenGL 3.3 core through `QOpenGLWidget` + PyOpenGL; all colour math lives in one GLSL fragment shader.
- Decoding: OpenImageIO (EXR, DPX, TIFF, TGA, HDR, PNG, JPEG...) and PyAV/FFmpeg (video, optional NVDEC).
- Arrays: numpy. No other runtime dependencies without asking.
- Package manager: uv with `uv.lock` committed; metadata in `pyproject.toml`.

## Layout
- Application code in `src/proexr/`, grouped by kind: `media/` (reading files), `playback/` (cache and clock), `ui/` (Qt widgets).
- Tests in `tests/`, mirroring `src/proexr/` paths (`tests/media/test_sequence.py` tests `src/proexr/media/sequence.py`).
- Colour tokens only in `src/proexr/ui/palette.py`; widgets read them, never hex literals.

## Conventions
- Source media is read-only: never open a user file for writing, never write next to it.
- `media/` and `playback/` never import Qt so they stay unit-testable without a display.
- App errors derive from `proexr.errors.ProexrError`.
- Icons are line glyphs drawn in `src/proexr/ui/icons.py`; no emoji or text glyphs as icons.
- The image area background stays neutral grey so it does not bias colour judgement.

## Verification
- Tests: `uv run pytest` (UI tests need a display; on Linux CI use `xvfb-run -a uv run pytest`).
- Lint: `uv run ruff check src tests`.

## Decisions
- Stack and layout above chosen by Claude on 2026-11-21 for performance on Windows/NVIDIA; the owner asked for the build end to end, so the init questions were answered with the recommended options.
