from pathlib import Path

import av
import numpy as np
import OpenImageIO as oiio
import pytest

WIDTH, HEIGHT = 64, 36


def write_exr(path: Path, channels: tuple[str, ...], value: float, pixel_type: str = "half",
              data_window: tuple[int, int, int, int] | None = None) -> None:
    x, y, w, h = data_window or (0, 0, WIDTH, HEIGHT)
    spec = oiio.ImageSpec(w, h, len(channels), pixel_type)
    spec.x, spec.y = x, y
    spec.full_x, spec.full_y, spec.full_width, spec.full_height = 0, 0, WIDTH, HEIGHT
    spec.channelnames = channels
    pixels = np.empty((h, w, len(channels)), np.float32)
    for i in range(len(channels)):
        pixels[:, :, i] = value + i * 0.1
    out = oiio.ImageOutput.create(str(path))
    out.open(str(path), spec)
    out.write_image(pixels)
    out.close()


@pytest.fixture
def exr_sequence(tmp_path: Path) -> Path:
    folder = tmp_path / "seq"
    folder.mkdir()
    for frame in range(1001, 1011):
        if frame == 1005:
            continue
        write_exr(folder / f"shot.{frame:04d}.exr",
                  ("A", "B", "G", "R", "diffuse.B", "diffuse.G", "diffuse.R", "Z"),
                  (frame - 1000) / 10)
    return folder


@pytest.fixture
def video_file(tmp_path: Path) -> Path:
    path = tmp_path / "clip.mp4"
    container = av.open(str(path), "w")
    stream = container.add_stream("libx264", rate=25)
    stream.width, stream.height, stream.pix_fmt = 64, 48, "yuv420p"
    stream.options = {"g": "10"}
    for i in range(50):
        img = np.zeros((48, 64, 3), np.uint8)
        img[:, :, 0] = i * 5
        for packet in stream.encode(av.VideoFrame.from_ndarray(img, format="rgb24")):
            container.mux(packet)
    for packet in stream.encode():
        container.mux(packet)
    container.close()
    return path
