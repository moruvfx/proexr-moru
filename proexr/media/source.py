"""Media sources: image sequences (OpenImageIO) and video files (FFmpeg/PyAV).

Every source is strictly read-only. Files are opened for reading only and
nothing is ever written next to them.
"""
from __future__ import annotations

import itertools
import os
import threading
from dataclasses import dataclass, field

import numpy as np

from .seq import Sequence, sequence_for_file

try:
    import OpenImageIO as oiio
except ImportError:  # pragma: no cover - reported in the UI
    oiio = None

try:
    import av
except ImportError:  # pragma: no cover
    av = None

_ids = itertools.count(1)


@dataclass
class Frame:
    data: np.ndarray            # (H, W, C) C in 1..4
    colorspace: str             # "linear" or "srgb"
    frame: int
    held: bool = False          # True when a missing frame was substituted

    @property
    def width(self) -> int:
        return self.data.shape[1]

    @property
    def height(self) -> int:
        return self.data.shape[0]

    @property
    def channels(self) -> int:
        return self.data.shape[2]

    @property
    def nbytes(self) -> int:
        return self.data.nbytes


@dataclass
class Layer:
    name: str
    subimage: int
    indices: list[int]          # channel indices inside the subimage, in display order
    channel_names: list[str]

    @property
    def label(self) -> str:
        chans = ",".join(c.rsplit(".", 1)[-1] for c in self.channel_names)
        return f"{self.name}  ({chans})"


@dataclass
class MediaSource:
    path: str
    name: str
    kind: str = "image"
    first: int = 0
    last: int = 0
    fps: float = 24.0
    width: int = 0
    height: int = 0
    pixel_aspect: float = 1.0
    layers: list[Layer] = field(default_factory=list)
    info: dict = field(default_factory=dict)
    parallel: bool = True       # can several threads read at once?
    uid: int = field(default_factory=lambda: next(_ids))

    @property
    def length(self) -> int:
        return self.last - self.first + 1

    def read(self, frame: int, layer: int = 0) -> Frame:  # pragma: no cover
        raise NotImplementedError

    def close(self):
        pass


# ---------------------------------------------------------------- images ---

_RGBA_ALIASES = [
    ("r", "g", "b", "a"),
    ("red", "green", "blue", "alpha"),
    ("x", "y", "z", None),
    ("u", "v", None, None),
]


def _build_layers(specs) -> list[Layer]:
    """Group EXR channels (``diffuse.R`` ...) into displayable layers."""
    layers: list[Layer] = []
    multipart = len(specs) > 1
    for si, spec in enumerate(specs):
        part = spec.getattribute("name") if multipart else None
        groups: dict[str, list[tuple[int, str]]] = {}
        for ci, cname in enumerate(spec.channelnames):
            base, _, chan = cname.rpartition(".")
            groups.setdefault(base, []).append((ci, chan))
        for base, chans in groups.items():
            lower = {c.lower(): (i, c) for i, c in chans}
            used: set[int] = set()
            for alias in _RGBA_ALIASES:
                req = [a for a in alias[:3] if a]
                if all(a in lower for a in req):
                    picked = [lower[a] for a in alias if a and a in lower]
                    idx = [p[0] for p in picked]
                    used.update(idx)
                    lname = base or ("RGBA" if alias[3] and alias[3] in lower else "RGB")
                    if part and part != base:
                        lname = f"{part}/{lname}" if base else part
                    layers.append(Layer(lname, si, idx,
                                        [spec.channelnames[i] for i in idx]))
                    break
            # an alpha on its own next to RGB is already used; others become
            # single-channel layers (depth Z, masks, AOV scalars...)
            for i, c in chans:
                if i in used:
                    continue
                lname = f"{base}.{c}" if base else c
                if part:
                    lname = f"{part}/{lname}"
                layers.append(Layer(lname, si, [i], [spec.channelnames[i]]))
    # main RGBA first
    layers.sort(key=lambda l: (l.subimage, 0 if l.name in ("RGBA", "RGB") else 1))
    return layers


def _read_dtype(fmt):
    b = str(fmt.basetype).lower() if hasattr(fmt, "basetype") else str(fmt)
    s = str(fmt).lower()
    if "half" in s:
        return "half", np.float16
    if "uint8" in s or s == "uint8":
        return "uint8", np.uint8
    if "uint16" in s:
        return "uint16", np.uint16
    return "float", np.float32


class ImageSequenceSource(MediaSource):
    def __init__(self, seq: Sequence, fps: float = 24.0):
        if oiio is None:
            raise RuntimeError("OpenImageIO is not installed")
        first_path = seq.path(seq.first)
        super().__init__(path=first_path, name=seq.display_name,
                         kind="sequence" if len(seq.frames) > 1 else "image",
                         first=seq.first, last=seq.last, fps=fps)
        self.seq = seq
        specs = self._read_specs(first_path)
        self.specs = specs
        main = specs[0]
        self.width, self.height = main.full_width, main.full_height
        self.pixel_aspect = float(main.get_float_attribute("PixelAspectRatio", 1.0) or 1.0)
        self.layers = _build_layers(specs) or [Layer("RGB", 0, list(range(main.nchannels)), list(main.channelnames))]
        fmt = os.path.splitext(first_path)[1].lower()
        self.colorspace = "linear" if fmt in (".exr", ".sxr", ".hdr", ".rgbe", ".pfm") else "srgb"
        cs = main.get_string_attribute("oiio:ColorSpace", "")
        if cs:
            if "linear" in cs.lower() or "aces" in cs.lower() or "scene" in cs.lower():
                self.colorspace = "linear"
            elif "srgb" in cs.lower() or "rec709" in cs.lower() or "gamma" in cs.lower():
                self.colorspace = "srgb"
        self.info = self._make_info(main, specs, fmt)
        fps_attr = main.getattribute("FramesPerSecond")
        try:
            if fps_attr:
                self.fps = float(fps_attr[0]) / float(fps_attr[1]) if isinstance(fps_attr, tuple) else float(fps_attr)
        except Exception:
            pass

    @staticmethod
    def _read_specs(path):
        inp = oiio.ImageInput.open(path)
        if inp is None:
            raise IOError(f"Cannot open {path}: {oiio.geterror()}")
        try:
            specs = []
            si = 0
            while inp.seek_subimage(si, 0):
                specs.append(inp.spec().copy() if hasattr(inp.spec(), "copy") else inp.spec())
                si += 1
            return specs or [inp.spec()]
        finally:
            inp.close()

    def _make_info(self, main, specs, fmt):
        info = {
            "File": self.seq.display_name,
            "Folder": self.seq.directory,
            "Frames": f"{self.first} - {self.last}  ({len(self.seq.frames)} files)",
            "Resolution": f"{main.full_width} x {main.full_height}",
            "Data window": f"{main.x},{main.y}  {main.width} x {main.height}",
            "Pixel type": str(main.format),
            "Channels": f"{main.nchannels}" + (f" in {len(specs)} parts" if len(specs) > 1 else ""),
            "Pixel aspect": f"{self.pixel_aspect:g}",
        }
        if self.seq.missing:
            info["Missing frames"] = str(len(self.seq.missing))
        for key in ("compression", "oiio:ColorSpace", "Software", "DateTime",
                    "chromaticities", "oiio:BitsPerSample", "tiff:Compression", "dpx:Transfer"):
            v = main.getattribute(key)
            if v not in (None, ""):
                info[key] = str(v)
        info["_layers"] = ", ".join(l.name for l in self.layers)
        return info

    def _resolve(self, frame: int):
        p = self.seq.path(frame)
        if p:
            return p, False
        # hold the nearest previous frame for gaps
        prev = [f for f in self.seq.frames if f <= frame]
        f = prev[-1] if prev else self.seq.first
        return self.seq.path(f), True

    def read(self, frame: int, layer: int = 0) -> Frame:
        path, held = self._resolve(frame)
        lay = self.layers[min(layer, len(self.layers) - 1)]
        inp = oiio.ImageInput.open(path)
        if inp is None:
            raise IOError(f"Cannot open {path}: {oiio.geterror()}")
        try:
            if lay.subimage:
                inp.seek_subimage(lay.subimage, 0)
            spec = inp.spec()
            cb, ce = min(lay.indices), max(lay.indices) + 1
            tname, _ = _read_dtype(spec.format)
            if tname == "uint8" and self.colorspace == "linear":
                tname = "half"
            pixels = inp.read_image(lay.subimage, 0, cb, ce, tname)
            if pixels is None:
                raise IOError(f"Read failed {path}: {inp.geterror()}")
        finally:
            inp.close()
        if pixels.ndim == 2:
            pixels = pixels[:, :, None]
        sel = [i - cb for i in lay.indices]
        if sel != list(range(ce - cb)):
            pixels = pixels[:, :, sel]
        pixels = self._to_display_window(pixels, spec)
        return Frame(np.ascontiguousarray(pixels), self.colorspace, frame, held)

    @staticmethod
    def _to_display_window(pix, spec):
        fw, fh = spec.full_width, spec.full_height
        if (spec.x, spec.y, spec.width, spec.height) == (spec.full_x, spec.full_y, fw, fh):
            return pix
        canvas = np.zeros((fh, fw, pix.shape[2]), dtype=pix.dtype)
        x0, y0 = spec.x - spec.full_x, spec.y - spec.full_y
        sx0, sy0 = max(0, -x0), max(0, -y0)
        dx0, dy0 = max(0, x0), max(0, y0)
        w = min(pix.shape[1] - sx0, fw - dx0)
        h = min(pix.shape[0] - sy0, fh - dy0)
        if w > 0 and h > 0:
            canvas[dy0:dy0 + h, dx0:dx0 + w] = pix[sy0:sy0 + h, sx0:sx0 + w]
        return canvas


# ----------------------------------------------------------------- video ---

class VideoSource(MediaSource):
    """Sequential-first FFmpeg decoder with keyframe seeking for random access."""

    MAX_FORWARD = 48  # decode forward instead of seeking when this close

    hw_decode = True  # class-wide preference, toggled from the UI

    def __init__(self, path: str):
        if av is None:
            raise RuntimeError("PyAV (FFmpeg) is not installed")
        super().__init__(path=path, name=os.path.basename(path), kind="video", parallel=False)
        self._lock = threading.Lock()
        self.hw_active = None
        self._open()
        st = self.stream
        rate = st.average_rate or st.guessed_rate or st.base_rate
        self.fps = float(rate) if rate else 24.0
        self.width, self.height = st.codec_context.width, st.codec_context.height
        sar = st.sample_aspect_ratio or st.codec_context.sample_aspect_ratio
        self.pixel_aspect = float(sar) if sar and float(sar) > 0 else 1.0
        self.start = float(st.start_time * st.time_base) if st.start_time is not None else 0.0
        n = st.frames or 0
        if not n:
            dur = None
            if st.duration is not None:
                dur = float(st.duration * st.time_base)
            elif self.container.duration:
                dur = self.container.duration / 1_000_000
            n = int(round((dur or 0) * self.fps)) or 1
        self.first, self.last = 0, n - 1
        self.colorspace = "srgb"
        pix = st.codec_context.format.name if st.codec_context.format else "?"
        self._deep = any(t in pix for t in ("10", "12", "16", "p010", "p016")) or "rgb48" in pix
        self.layers = [Layer("RGB", 0, [0, 1, 2], ["R", "G", "B"])]
        self.info = {
            "File": os.path.basename(path),
            "Folder": os.path.dirname(path),
            "Codec": st.codec_context.codec.long_name or st.codec_context.name,
            "Resolution": f"{self.width} x {self.height}",
            "Pixel format": pix,
            "Frame rate": f"{self.fps:.3f}",
            "Frames": str(n),
            "Duration": f"{n / self.fps:.2f} s",
            "Bit rate": f"{(st.bit_rate or self.container.bit_rate or 0) / 1e6:.1f} Mb/s",
            "Container": self.container.format.long_name,
        }
        self._next = None   # index of the frame the decoder will produce next
        self._iter = None
        self._last_frame = None

    def _open(self):
        self.container = None
        if VideoSource.hw_decode:
            try:
                from av.codec.hwaccel import HWAccel, hwdevices_available
                for dev in ("cuda", "d3d11va", "dxva2", "videotoolbox", "vaapi"):
                    if dev in hwdevices_available():
                        self.container = av.open(self.path, "r", hwaccel=HWAccel(dev, allow_software_fallback=True))
                        self.hw_active = dev
                        break
            except Exception:
                self.container = None
                self.hw_active = None
        if self.container is None:
            self.container = av.open(self.path, "r")
            self.hw_active = None
        self.stream = self.container.streams.video[0]
        self.stream.thread_type = "AUTO"

    def _index(self, f) -> int:
        t = (f.pts * f.time_base) if f.pts is not None else f.time
        return int(round((float(t) - self.start) * self.fps))

    def _decode_iter(self):
        for packet in self.container.demux(self.stream):
            for f in packet.decode():
                yield f
        # flush
        for f in self.stream.decode(None) if False else []:
            yield f

    def _seek(self, index: int):
        ts = int((index / self.fps + self.start) / self.stream.time_base)
        self.container.seek(max(ts, 0), stream=self.stream, backward=True, any_frame=False)
        self._iter = self._decode_iter()
        self._next = None

    def _convert(self, f) -> np.ndarray:
        fmt = "rgb48le" if self._deep else "rgb24"
        kw = {}
        try:
            if f.colorspace in (0, 2, None) and self.height >= 720:  # unspecified
                kw["src_colorspace"] = "ITU709"
        except Exception:
            pass
        try:
            return f.to_ndarray(format=fmt, **kw)
        except TypeError:
            return f.to_ndarray(format=fmt)

    def read(self, frame: int, layer: int = 0) -> Frame:
        frame = max(self.first, min(self.last, frame))
        with self._lock:
            try:
                return self._read_locked(frame)
            except Exception:
                if self.hw_active:
                    # hardware path failed mid-stream: reopen in software
                    VideoSource.hw_decode = False
                    self.container.close()
                    self._open()
                    self._iter = None
                    return self._read_locked(frame)
                raise

    def _read_locked(self, frame: int) -> Frame:
        if self._iter is None or self._next is None or frame < self._next or frame > self._next + self.MAX_FORWARD:
            self._seek(frame)
        best = None
        for f in self._iter:
            idx = self._index(f)
            self._next = idx + 1
            if idx >= frame:
                best = f
                break
            best = f
        if best is None:
            if self._last_frame is not None:
                return Frame(self._last_frame, self.colorspace, frame, True)
            raise IOError("No video frames decoded")
        arr = self._convert(best)
        self._last_frame = arr
        return Frame(arr, self.colorspace, frame)

    def close(self):
        with self._lock:
            try:
                self.container.close()
            except Exception:
                pass


# ---------------------------------------------------------------- opening --

def open_media(path: str):
    from .seq import is_video, is_image, scan_directory
    path = os.path.abspath(path)
    if os.path.isdir(path):
        seqs, vids = scan_directory(path)
        return [ImageSequenceSource(s) for s in seqs] + [VideoSource(v) for v in vids]
    if is_video(path):
        return [VideoSource(path)]
    if is_image(path):
        return [ImageSequenceSource(sequence_for_file(path))]
    raise ValueError(f"Unsupported file: {path}")
