from collections.abc import Iterator
from pathlib import Path

import av
import numpy as np

from ..errors import MediaReadError

SAMPLE_RATE = 48000
CHANNELS = 2


def has_audio(path: Path) -> bool:
    try:
        with av.open(str(path), "r") as container:
            return bool(container.streams.audio)
    except av.FFmpegError:
        return False


class AudioTrack:
    """First audio stream of a file, decoded to interleaved 16-bit stereo at 48 kHz."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        try:
            self._container = av.open(str(self.path), "r")
        except av.FFmpegError as error:
            raise MediaReadError(f"Cannot open {self.path}: {error}") from error
        if not self._container.streams.audio:
            self._container.close()
            raise MediaReadError(f"No audio stream in {self.path}")
        self._stream = self._container.streams.audio[0]

    def samples_from(self, seconds: float) -> Iterator[np.ndarray]:
        """Yield (n, 2) int16 blocks starting at `seconds` on the file's own timeline."""
        resampler = av.AudioResampler(format="s16", layout="stereo", rate=SAMPLE_RATE)
        target = max(0.0, seconds)
        try:
            self._container.seek(int(target / self._stream.time_base), stream=self._stream, backward=True)
            for packet in self._container.demux(self._stream):
                for decoded in packet.decode():
                    start = decoded.time
                    for frame in resampler.resample(decoded):
                        block = frame.to_ndarray().reshape(-1, CHANNELS)
                        if start is not None and start < target:
                            block = block[int((target - start) * SAMPLE_RATE):]
                            start += frame.samples / SAMPLE_RATE
                        if len(block):
                            yield block
        except av.FFmpegError as error:
            raise MediaReadError(f"Cannot decode audio in {self.path}: {error}") from error

    def close(self) -> None:
        self._container.close()
