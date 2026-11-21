import math
from dataclasses import dataclass

import numpy as np

LUMA_WEIGHTS = np.array([0.2126, 0.7152, 0.0722], np.float32)
CB_WEIGHTS = np.array([-0.1146, -0.3854, 0.5], np.float32)
CR_WEIGHTS = np.array([0.5, -0.4542, -0.0458], np.float32)
MIDDLE_GREY = 0.18
INTEGER_SCALE = {np.dtype(np.uint8): 255.0, np.dtype(np.uint16): 65535.0}


def _rgb(pixels: np.ndarray) -> np.ndarray:
    data = pixels.astype(np.float32) / INTEGER_SCALE.get(pixels.dtype, 1.0)
    if data.shape[2] == 1:
        return np.repeat(data, 3, axis=2)
    if data.shape[2] == 2:
        return np.concatenate([data, np.zeros_like(data[..., :1])], axis=2)
    return data[..., :3]


def histogram(pixels: np.ndarray, bins: int = 256) -> np.ndarray:
    """Counts per bin over 0..1 for R, G, B and luminance; returns shape (4, bins)."""
    rgb = np.clip(_rgb(pixels), 0.0, 1.0)
    planes = [rgb[..., 0], rgb[..., 1], rgb[..., 2], rgb @ LUMA_WEIGHTS]
    index = [np.minimum((p * bins).astype(np.int32), bins - 1).ravel() for p in planes]
    return np.stack([np.bincount(i, minlength=bins) for i in index])


def waveform(pixels: np.ndarray, columns: int = 256, levels: int = 256) -> np.ndarray:
    """RGB parade counts; returns shape (3, levels, columns) with level 0 = black."""
    rgb = np.clip(_rgb(pixels), 0.0, 1.0)
    height, width = rgb.shape[:2]
    column = np.minimum((np.arange(width) * columns) // width, columns - 1)
    column = np.broadcast_to(column[None, :], (height, width)).ravel()
    trace = np.zeros((3, levels, columns), np.int32)
    for channel in range(3):
        level = np.minimum((rgb[..., channel] * levels).astype(np.int32), levels - 1).ravel()
        np.add.at(trace[channel], (level, column), 1)
    return trace


def vectorscope(pixels: np.ndarray, size: int = 256) -> np.ndarray:
    """Cb/Cr density (Rec.709) on a size x size grid; neutral sits in the centre, up is +Cr."""
    rgb = np.clip(_rgb(pixels), 0.0, 1.0).reshape(-1, 3)
    cb, cr = rgb @ CB_WEIGHTS, rgb @ CR_WEIGHTS
    x = np.clip(np.round((cb + 0.5) * (size - 1)).astype(np.int32), 0, size - 1)
    y = np.clip(np.round((0.5 - cr) * (size - 1)).astype(np.int32), 0, size - 1)
    scope = np.zeros((size, size), np.int32)
    np.add.at(scope, (y, x), 1)
    return scope


@dataclass(frozen=True)
class PixelReport:
    x: int
    y: int
    channel_names: list[str]
    raw: list[float]
    values: list[float]
    luminance: float
    stops: float
    area_average: list[float]


def pixel_report(pixels: np.ndarray, x: int, y: int, channel_names: list[str], radius: int = 2) -> PixelReport:
    """Describes one pixel: raw and normalised values, luminance, stops from 18% grey, and the area mean."""
    scale = INTEGER_SCALE.get(pixels.dtype, 1.0)
    raw = pixels[y, x].astype(np.float64)
    values = raw / scale
    rgb = _rgb(pixels[y:y + 1, x:x + 1])[0, 0]
    luminance = float(rgb @ LUMA_WEIGHTS)
    stops = math.log2(luminance / MIDDLE_GREY) if luminance > 0 else float("-inf")
    area = pixels[max(0, y - radius):y + radius + 1, max(0, x - radius):x + radius + 1].astype(np.float64)
    average = area.reshape(-1, pixels.shape[2]).mean(axis=0) / scale
    raw_values = [int(v) for v in raw] if scale != 1.0 else [float(v) for v in raw]
    return PixelReport(x, y, channel_names, raw_values, [float(v) for v in values], luminance, stops,
                       [float(v) for v in average])
