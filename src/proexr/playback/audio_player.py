import queue
import threading
from collections.abc import Callable

import numpy as np

from ..media.audio import CHANNELS, SAMPLE_RATE, AudioTrack

QUEUED_BLOCKS = 24
BLOCK_SIZE = 1024


def open_default_output(callback: Callable) -> object | None:
    """Start a PortAudio output stream, or return None when no audio device or library is present."""
    try:
        import sounddevice
        stream = sounddevice.OutputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="int16",
                                          blocksize=BLOCK_SIZE, callback=callback)
        stream.start()
        return stream
    except Exception:  # noqa: BLE001 - any audio backend failure just means silent playback
        return None


class AudioPlayer:
    """Plays an AudioTrack from a position; a decode thread feeds the device callback through a queue."""

    def __init__(self, open_output: Callable[[Callable], object | None] = open_default_output) -> None:
        self._open_output = open_output
        self._stream = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._blocks: queue.Queue[np.ndarray] = queue.Queue(QUEUED_BLOCKS)
        self._pending = np.zeros((0, CHANNELS), np.int16)
        self.volume = 1.0

    @property
    def is_playing(self) -> bool:
        return self._thread is not None

    def play(self, track: AudioTrack, seconds: float) -> bool:
        self.stop()
        self._stop.clear()
        self._thread = threading.Thread(target=self._decode, args=(track, seconds), daemon=True)
        self._thread.start()
        self._stream = self._open_output(self._fill)
        if self._stream is None:
            self.stop()
            return False
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        while not self._blocks.empty():
            self._blocks.get_nowait()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        self._pending = np.zeros((0, CHANNELS), np.int16)

    def _decode(self, track: AudioTrack, seconds: float) -> None:
        try:
            for block in track.samples_from(seconds):
                while not self._stop.is_set():
                    try:
                        self._blocks.put(block, timeout=0.05)
                        break
                    except queue.Full:
                        continue
                if self._stop.is_set():
                    return
        except Exception:  # noqa: BLE001 - a decode error ends the audio, video keeps playing
            return

    def _fill(self, outdata: np.ndarray, frames: int, _time, _status) -> None:
        filled = 0
        while filled < frames:
            if not len(self._pending):
                try:
                    self._pending = self._blocks.get_nowait()
                except queue.Empty:
                    break
            take = min(frames - filled, len(self._pending))
            outdata[filled:filled + take] = self._pending[:take]
            self._pending = self._pending[take:]
            filled += take
        outdata[filled:] = 0
        if self.volume != 1.0:
            outdata[:] = (outdata * self.volume).astype(np.int16)
