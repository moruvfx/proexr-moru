import math

import numpy as np

from .frame import Frame


def thumbnail_pixels(frame: Frame, max_size: int = 160) -> np.ndarray:
    """Small display-ready (h, w, 3) uint8 copy of a frame: nearest-neighbour downscale, sRGB encoded."""
    step = max(1, math.ceil(max(frame.width, frame.height) / max_size))
    pixels = frame.rgb_region(0, 0, frame.width, frame.height)[::step, ::step]
    if pixels.shape[2] >= 3:
        rgb = pixels[..., :3]
    else:
        rgb = np.repeat(pixels[..., :1], 3, axis=2)
    if rgb.dtype == np.uint8:
        return np.ascontiguousarray(rgb)
    if np.issubdtype(rgb.dtype, np.integer):
        values = rgb.astype(np.float32) / np.iinfo(rgb.dtype).max
    else:
        values = np.nan_to_num(rgb.astype(np.float32))
    values = np.clip(values, 0.0, 1.0)
    if frame.colorspace == "linear":
        values = np.where(values <= 0.0031308, values * 12.92, 1.055 * np.power(values, 1 / 2.4) - 0.055)
    return np.ascontiguousarray((values * 255 + 0.5).astype(np.uint8))
