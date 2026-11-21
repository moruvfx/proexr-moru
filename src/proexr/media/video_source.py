import threading
from collections.abc import Iterator
from pathlib import Path

import av
import numpy as np

from ..errors import MediaReadError
from .frame import Frame, MediaSource
from .layers import Layer

HARDWARE_DEVICES = ("cuda", "d3d11va", "dxva2", "videotoolbox", "vaapi")
MAX_DECODE_AHEAD = 48
HIGH_BIT_DEPTH_MARKERS = ("10", "12", "16", "p010", "p016")


class VideoSource(MediaSource):
    def __init__(self, path: Path, hardware_decode: bool = True) -> None:
        super().__init__(path=path, label=path.name, kind="video", parallel_reads=False)
        self._lock = threading.Lock()
        self._hardware_decode = hardware_decode
        self.hardware_device: str | None = None
        self._decoded: Iterator[av.VideoFrame] | None = None
        self._next_number: int | None = None
        self._last_pixels: np.ndarray | None = None
        self._open()
        stream = self._stream
        rate = stream.average_rate or stream.guessed_rate or stream.base_rate
        self.fps = float(rate) if rate else 24.0
        codec = stream.codec_context
        self.width, self.height = codec.width, codec.height
        aspect = stream.sample_aspect_ratio or codec.sample_aspect_ratio
        self.pixel_aspect = float(aspect) if aspect and float(aspect) > 0 else 1.0
        self._start_seconds = float(stream.start_time * stream.time_base) if stream.start_time else 0.0
        self.first, self.last = 0, self._count_frames() - 1
        self.colorspace = "srgb"
        pixel_format = codec.format.name if codec.format else "unknown"
        self._is_high_bit_depth = any(m in pixel_format for m in HIGH_BIT_DEPTH_MARKERS)
        self.layers = [Layer("RGB", 0, [0, 1, 2], ["R", "G", "B"])]
        self.properties = {
            "File": path.name,
            "Folder": str(path.parent),
            "Codec": codec.codec.long_name or codec.name,
            "Resolution": f"{self.width} x {self.height}",
            "Pixel format": pixel_format,
            "Frame rate": f"{self.fps:.3f}",
            "Frames": str(self.length),
            "Duration": f"{self.length / self.fps:.2f} s",
            "Container": self._container.format.long_name,
            "Decoder": f"hardware ({self.hardware_device})" if self.hardware_device else "software",
        }

    def _open(self) -> None:
        self._container = None
        if self._hardware_decode:
            self._open_hardware()
        if self._container is None:
            try:
                self._container = av.open(str(self.path), "r")
            except av.FFmpegError as error:
                raise MediaReadError(f"Cannot open {self.path}: {error}") from error
        if not self._container.streams.video:
            raise MediaReadError(f"No video stream in {self.path}")
        self._stream = self._container.streams.video[0]
        self._stream.thread_type = "AUTO"

    def _open_hardware(self) -> None:
        from av.codec.hwaccel import HWAccel, hwdevices_available
        available = hwdevices_available()
        for device in HARDWARE_DEVICES:
            if device not in available:
                continue
            try:
                self._container = av.open(str(self.path), "r",
                                          hwaccel=HWAccel(device, allow_software_fallback=True))
            except av.FFmpegError:
                continue
            self.hardware_device = device
            return

    def _count_frames(self) -> int:
        if self._stream.frames:
            return int(self._stream.frames)
        if self._stream.duration is not None:
            seconds = float(self._stream.duration * self._stream.time_base)
        else:
            seconds = (self._container.duration or 0) / av.time_base
        return max(1, round(seconds * self.fps))

    def _frame_number(self, frame: av.VideoFrame) -> int:
        return round((float(frame.time) - self._start_seconds) * self.fps)

    def _decode(self) -> Iterator[av.VideoFrame]:
        for packet in self._container.demux(self._stream):
            yield from packet.decode()

    def _seek(self, number: int) -> None:
        timestamp = int((number / self.fps + self._start_seconds) / self._stream.time_base)
        self._container.seek(max(timestamp, 0), stream=self._stream, backward=True, any_frame=False)
        self._decoded = self._decode()
        self._next_number = None

    def _to_rgb(self, frame: av.VideoFrame) -> np.ndarray:
        target = "rgb48le" if self._is_high_bit_depth else "rgb24"
        return frame.to_ndarray(format=target)

    def _read_locked(self, number: int) -> Frame:
        needs_seek = (self._decoded is None or self._next_number is None or number < self._next_number
                      or number > self._next_number + MAX_DECODE_AHEAD)
        if needs_seek:
            self._seek(number)
        chosen = None
        for decoded in self._decoded:
            self._next_number = self._frame_number(decoded) + 1
            chosen = decoded
            if self._next_number > number:
                break
        if chosen is None:
            if self._last_pixels is None:
                raise MediaReadError(f"No frames decoded from {self.path}")
            return Frame(self._last_pixels, self.colorspace, number, is_held=True)
        self._last_pixels = self._to_rgb(chosen)
        return Frame(self._last_pixels, self.colorspace, number)

    def read(self, number: int, layer: int = 0) -> Frame:
        number = min(max(number, self.first), self.last)
        with self._lock:
            try:
                return self._read_locked(number)
            except av.FFmpegError as error:
                if self.hardware_device is None:
                    raise MediaReadError(f"Decode failed at frame {number}: {error}") from error
                self._container.close()
                self._hardware_decode, self.hardware_device = False, None
                self._open()
                self._decoded = None
                return self._read_locked(number)

    def close(self) -> None:
        with self._lock:
            self._container.close()
