from dataclasses import dataclass, field
from itertools import count
from pathlib import Path
from typing import Literal

import numpy as np

from .layers import Layer

Colorspace = Literal["linear", "srgb"]
MediaKind = Literal["image", "sequence", "video"]
_source_ids = count(1)


@dataclass(frozen=True)
class Frame:
    pixels: np.ndarray
    colorspace: Colorspace
    number: int
    is_held: bool = False
    layout: str = "rgb"  # "rgb" (h, w, c) or planar video "yuv420p" / "nv12" stored as (h*3/2, w) uint8
    yuv_matrix: str = "bt709"
    yuv_full_range: bool = False

    @property
    def is_planar(self) -> bool:
        return self.layout != "rgb"

    @property
    def width(self) -> int:
        return self.pixels.shape[1]

    @property
    def height(self) -> int:
        return self.pixels.shape[0] * 2 // 3 if self.is_planar else self.pixels.shape[0]

    @property
    def channel_count(self) -> int:
        return 3 if self.is_planar else self.pixels.shape[2]

    def rgb_region(self, x0: int, y0: int, x1: int, y1: int) -> np.ndarray:
        """Pixels of a region as (h, w, c) in the frame's own type; planar video is converted to uint8 RGB."""
        if not self.is_planar:
            return self.pixels[y0:y1, x0:x1]
        from .yuv import to_rgb
        return to_rgb(self.pixels, self.layout, self.yuv_matrix, self.yuv_full_range, (x0, y0, x1, y1))

    @property
    def nbytes(self) -> int:
        return self.pixels.nbytes


@dataclass(eq=False)
class MediaSource:
    path: Path
    label: str
    kind: MediaKind
    first: int = 0
    last: int = 0
    fps: float = 24.0
    width: int = 0
    height: int = 0
    pixel_aspect: float = 1.0
    colorspace: Colorspace = "srgb"
    layers: list[Layer] = field(default_factory=list)
    properties: dict[str, str] = field(default_factory=dict)
    missing_frames: list[int] = field(default_factory=list)
    parallel_reads: bool = True
    uid: int = field(default_factory=lambda: next(_source_ids))

    @property
    def length(self) -> int:
        return self.last - self.first + 1

    def read(self, number: int, layer: int = 0) -> Frame:
        raise NotImplementedError

    def close(self) -> None:
        return None
