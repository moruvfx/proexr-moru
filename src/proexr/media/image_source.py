import numpy as np
import OpenImageIO as oiio

from ..errors import MediaReadError
from .frame import Colorspace, Frame, MediaSource
from .layers import group_layers
from .sequence import ImageSequence

SCENE_LINEAR_EXTENSIONS = frozenset({".exr", ".sxr", ".hdr", ".rgbe", ".pfm"})
METADATA_KEYS = ("compression", "oiio:ColorSpace", "Software", "DateTime", "dpx:Transfer",
                 "oiio:BitsPerSample", "PixelAspectRatio")


def _read_type(spec: oiio.ImageSpec, colorspace: Colorspace) -> str:
    name = str(spec.format)
    if name == "uint8":
        return "half" if colorspace == "linear" else "uint8"
    if name == "uint16":
        return "uint16"
    if name == "half":
        return "half"
    return "float"


def _guess_colorspace(sequence: ImageSequence, spec: oiio.ImageSpec) -> Colorspace:
    declared = spec.get_string_attribute("oiio:ColorSpace", "").lower()
    if declared.startswith("lin") or "linear" in declared or "aces" in declared:
        return "linear"
    if any(word in declared for word in ("srgb", "rec709", "gamma")):
        return "srgb"
    suffix = sequence.path_for(sequence.first).suffix.lower()
    return "linear" if suffix in SCENE_LINEAR_EXTENSIONS else "srgb"


def _place_in_display_window(pixels: np.ndarray, spec: oiio.ImageSpec) -> np.ndarray:
    full_w, full_h = spec.full_width, spec.full_height
    if (spec.x, spec.y, spec.width, spec.height) == (spec.full_x, spec.full_y, full_w, full_h):
        return pixels
    canvas = np.zeros((full_h, full_w, pixels.shape[2]), pixels.dtype)
    offset_x, offset_y = spec.x - spec.full_x, spec.y - spec.full_y
    src_x, src_y = max(0, -offset_x), max(0, -offset_y)
    dst_x, dst_y = max(0, offset_x), max(0, offset_y)
    w = min(pixels.shape[1] - src_x, full_w - dst_x)
    h = min(pixels.shape[0] - src_y, full_h - dst_y)
    if w > 0 and h > 0:
        canvas[dst_y:dst_y + h, dst_x:dst_x + w] = pixels[src_y:src_y + h, src_x:src_x + w]
    return canvas


class ImageSequenceSource(MediaSource):
    def __init__(self, sequence: ImageSequence) -> None:
        first_path = sequence.path_for(sequence.first)
        super().__init__(path=first_path, label=sequence.label,
                         kind="sequence" if len(sequence.files) > 1 else "image",
                         first=sequence.first, last=sequence.last)
        self.sequence = sequence
        self.missing_frames = sequence.missing
        specs = self._read_specs()
        main = specs[0]
        self.width, self.height = main.full_width, main.full_height
        self.pixel_aspect = float(main.get_float_attribute("PixelAspectRatio", 1.0) or 1.0)
        self.colorspace = _guess_colorspace(sequence, main)
        part_names = [s.get_string_attribute("name", f"part{i}") for i, s in enumerate(specs)]
        self.layers = group_layers([list(s.channelnames) for s in specs], part_names)
        self.properties = self._describe(main, len(specs))

    def _open(self, path) -> oiio.ImageInput:
        image = oiio.ImageInput.open(str(path))
        if image is None:
            raise MediaReadError(f"Cannot open {path}: {oiio.geterror()}")
        return image

    def _read_specs(self) -> list[oiio.ImageSpec]:
        image = self._open(self.path)
        try:
            specs = []
            while image.seek_subimage(len(specs), 0):
                specs.append(oiio.ImageSpec(image.spec()))
            return specs
        finally:
            image.close()

    def _describe(self, spec: oiio.ImageSpec, parts: int) -> dict[str, str]:
        properties = {
            "File": self.label,
            "Folder": str(self.sequence.folder),
            "Frames": f"{self.first}-{self.last} ({len(self.sequence.files)} files)",
            "Resolution": f"{spec.full_width} x {spec.full_height}",
            "Data window": f"{spec.x},{spec.y} {spec.width} x {spec.height}",
            "Pixel type": str(spec.format),
            "Channels": f"{spec.nchannels}" + (f" in {parts} parts" if parts > 1 else ""),
            "Colorspace": self.colorspace,
        }
        if self.missing_frames:
            properties["Missing frames"] = str(len(self.missing_frames))
        for key in METADATA_KEYS:
            value = spec.getattribute(key)
            if value not in (None, ""):
                properties[key] = str(value)
        return properties

    def _resolve(self, number: int) -> tuple[object, bool]:
        path = self.sequence.path_for(number)
        if path is not None:
            return path, False
        earlier = [f for f in self.sequence.frames if f <= number]
        return self.sequence.path_for(earlier[-1] if earlier else self.first), True

    def read(self, number: int, layer: int = 0) -> Frame:
        path, is_held = self._resolve(number)
        selected = self.layers[min(layer, len(self.layers) - 1)]
        begin, end = min(selected.channel_indices), max(selected.channel_indices) + 1
        image = self._open(path)
        try:
            image.seek_subimage(selected.part, 0)
            spec = oiio.ImageSpec(image.spec())
            pixels = image.read_image(selected.part, 0, begin, end, _read_type(spec, self.colorspace))
            if pixels is None:
                raise MediaReadError(f"Cannot read {path}: {image.geterror()}")
        finally:
            image.close()
        if pixels.ndim == 2:
            pixels = pixels[:, :, None]
        order = [i - begin for i in selected.channel_indices]
        if order != list(range(end - begin)):
            pixels = pixels[:, :, order]
        pixels = np.ascontiguousarray(_place_in_display_window(pixels, spec))
        return Frame(pixels, self.colorspace, number, is_held)
