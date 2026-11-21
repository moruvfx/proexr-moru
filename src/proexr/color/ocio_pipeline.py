from dataclasses import dataclass
from typing import Literal

import numpy as np
import PyOpenColorIO as ocio

from ..errors import ColorConfigError
from ..media.frame import Colorspace

BUILTIN_CONFIG = "ocio://default"
LUT_SIZE = 65
LOG_MIN_STOPS = -12.0
LOG_MAX_STOPS = 8.0
RANGE_MIN = -0.25
RANGE_MAX = 1.5
DEFAULT_LINEAR_INPUT = "Linear Rec.709 (sRGB)"
DEFAULT_DISPLAY_INPUT = "sRGB Encoded Rec.709 (sRGB)"
Shaper = Literal["log", "range"]


@dataclass(frozen=True)
class BakedLut:
    table: np.ndarray
    shaper: Shaper
    domain_min: float
    domain_max: float


def shape(values: np.ndarray, lut: BakedLut) -> np.ndarray:
    """Maps input pixel values to 0..1 LUT coordinates using the LUT's shaper."""
    if lut.shaper == "log":
        stops = np.log2(np.maximum(values, 2.0 ** lut.domain_min))
        return np.clip((stops - lut.domain_min) / (lut.domain_max - lut.domain_min), 0.0, 1.0)
    return np.clip((values - lut.domain_min) / (lut.domain_max - lut.domain_min), 0.0, 1.0)


def apply_baked_lut(lut: BakedLut, rgb: np.ndarray) -> np.ndarray:
    """Applies a baked LUT on the CPU with trilinear interpolation; rgb is (N, 3). Mirrors the GPU path."""
    size = lut.table.shape[0]
    coords = shape(rgb.astype(np.float64), lut) * (size - 1)
    low = np.clip(np.floor(coords).astype(int), 0, size - 2)
    frac = coords - low
    result = np.zeros_like(coords)
    for corner in range(8):
        offset = np.array([(corner >> 0) & 1, (corner >> 1) & 1, (corner >> 2) & 1])
        weight = np.prod(np.where(offset, frac, 1.0 - frac), axis=1)
        r, g, b = (low + offset).T
        result += weight[:, None] * lut.table[b, g, r]
    return result.astype(np.float32)


class ColorManagement:
    def __init__(self, config: ocio.Config, source: str) -> None:
        self.config = config
        self.source = source

    @classmethod
    def load(cls, source: str = BUILTIN_CONFIG) -> "ColorManagement":
        try:
            config = ocio.Config.CreateFromFile(source)
            config.validate()
        except (ocio.Exception, ocio.ExceptionMissingFile) as error:
            raise ColorConfigError(f"Cannot load OCIO config {source}: {error}") from error
        return cls(config, source)

    @property
    def name(self) -> str:
        return self.config.getName() or self.source

    @property
    def colorspaces(self) -> list[str]:
        return [space.getName() for space in self.config.getColorSpaces()]

    @property
    def displays(self) -> list[str]:
        return list(self.config.getDisplays())

    @property
    def default_display(self) -> str:
        return self.config.getDefaultDisplay()

    def views(self, display: str) -> list[str]:
        return list(self.config.getViews(display))

    def default_view(self, display: str) -> str:
        return self.config.getDefaultView(display)

    def default_input(self, colorspace: Colorspace) -> str:
        preferred = DEFAULT_LINEAR_INPUT if colorspace == "linear" else DEFAULT_DISPLAY_INPUT
        if preferred in self.colorspaces:
            return preferred
        role = ocio.ROLE_SCENE_LINEAR if colorspace == "linear" else ocio.ROLE_COLOR_PICKING
        space = self.config.getColorSpace(role)
        return space.getName() if space else self.colorspaces[0]

    def _processor(self, input_space: str, display: str, view: str) -> ocio.CPUProcessor:
        transform = ocio.DisplayViewTransform(src=input_space, display=display, view=view)
        try:
            return self.config.getProcessor(transform).getDefaultCPUProcessor()
        except ocio.Exception as error:
            raise ColorConfigError(f"Cannot build {input_space} -> {display}/{view}: {error}") from error

    def _is_scene_linear(self, input_space: str) -> bool:
        space = self.config.getColorSpace(input_space)
        encoding = space.getEncoding() if space else ""
        return encoding == "scene-linear" or (not encoding and "linear" in input_space.lower())

    def apply_exact(self, input_space: str, display: str, view: str, rgb: np.ndarray) -> np.ndarray:
        pixels = np.ascontiguousarray(rgb, np.float32).copy()
        self._processor(input_space, display, view).applyRGB(pixels)
        return pixels

    def bake(self, input_space: str, display: str, view: str, size: int = LUT_SIZE) -> BakedLut:
        if self._is_scene_linear(input_space):
            shaper, low, high = "log", LOG_MIN_STOPS, LOG_MAX_STOPS
            axis = 2.0 ** np.linspace(low, high, size)
        else:
            shaper, low, high = "range", RANGE_MIN, RANGE_MAX
            axis = np.linspace(low, high, size)
        b, g, r = np.meshgrid(axis, axis, axis, indexing="ij")
        lattice = np.stack([r, g, b], axis=-1).astype(np.float32)
        table = self.apply_exact(input_space, display, view, lattice.reshape(-1, 3)).reshape(size, size, size, 3)
        return BakedLut(np.ascontiguousarray(table), shaper, low, high)
