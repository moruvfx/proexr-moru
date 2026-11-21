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

    @property
    def width(self) -> int:
        return self.pixels.shape[1]

    @property
    def height(self) -> int:
        return self.pixels.shape[0]

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
