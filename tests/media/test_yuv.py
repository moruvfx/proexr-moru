import av
import numpy as np
import pytest

from proexr.media.frame import Frame
from proexr.media.yuv import pick_matrix, planes, to_rgb

COLOR = (200, 40, 90)


def encoded(layout: str) -> np.ndarray:
    source = av.VideoFrame.from_ndarray(np.full((48, 64, 3), COLOR, np.uint8), format="rgb24")
    return source.reformat(format=layout).to_ndarray()  # FFmpeg default: BT.601, limited range


@pytest.mark.parametrize("layout", ["yuv420p", "nv12"])
def test_cpu_conversion_matches_ffmpeg(layout):
    rgb = to_rgb(encoded(layout), layout, "bt601", full_range=False)
    assert rgb.shape == (48, 64, 3)
    assert np.abs(rgb.astype(int) - COLOR).max() <= 3


def test_planes_have_half_resolution_chroma():
    y, u, v = planes(encoded("yuv420p"), "yuv420p")
    assert y.shape == (48, 64) and u.shape == (24, 32) and v.shape == (24, 32)
    y, uv = planes(encoded("nv12"), "nv12")
    assert uv.shape == (24, 32, 2)


def test_planar_frame_reports_image_size_and_region():
    frame = Frame(encoded("nv12"), "srgb", 0, layout="nv12", yuv_matrix="bt601")
    assert (frame.width, frame.height, frame.channel_count) == (64, 48, 3)
    region = frame.rgb_region(10, 10, 13, 12)
    assert region.shape == (2, 3, 3) and np.abs(region.astype(int) - COLOR).max() <= 3


def test_matrix_defaults_follow_resolution():
    assert pick_matrix(2, 1080) == "bt709"
    assert pick_matrix(2, 480) == "bt601"
    assert pick_matrix(9, 480) == "bt2020"
