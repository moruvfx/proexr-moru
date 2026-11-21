import numpy as np

from proexr.media.frame import Frame
from proexr.media.thumbnail import thumbnail_pixels


def test_linear_float_frame_becomes_small_srgb_uint8():
    pixels = np.full((400, 800, 4), 0.18, np.float16)
    thumb = thumbnail_pixels(Frame(pixels, "linear", 1), max_size=160)
    assert thumb.dtype == np.uint8 and thumb.shape == (80, 160, 3)
    assert 115 <= thumb[0, 0, 0] <= 120


def test_single_channel_is_repeated_to_grey():
    pixels = np.full((10, 10, 1), 65535, np.uint16)
    thumb = thumbnail_pixels(Frame(pixels, "srgb", 1))
    assert thumb.shape == (10, 10, 3) and (thumb == 255).all()


def test_nan_and_negative_values_are_clamped():
    pixels = np.array([[[np.nan, -1.0, 4.0]]], np.float32)
    assert thumbnail_pixels(Frame(pixels, "linear", 1)).tolist() == [[[0, 0, 255]]]
