import os
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from ..errors import ProexrError
from ..media.frame import Frame, MediaSource

CacheKey = tuple[int, int, int]
IDLE_WAIT_SECONDS = 0.25


def default_worker_count() -> int:
    return max(2, min(16, (os.cpu_count() or 4) - 1))


class FrameCache:
    def __init__(self, max_bytes: int, workers: int | None = None) -> None:
        self.max_bytes = max_bytes
        self.workers = workers or default_worker_count()
        self.on_frame_ready: Callable[[CacheKey], None] | None = None
        self._frames: dict[CacheKey, Frame] = {}
        self._pending: set[CacheKey] = set()
        self._errors: dict[CacheKey, str] = {}
        self._used_bytes = 0
        self._frame_bytes = 0
        self._condition = threading.Condition()
        self._pool = ThreadPoolExecutor(self.workers, thread_name_prefix="decode")
        self._source: MediaSource | None = None
        self._layer = 0
        self._playhead = 0
        self._direction = 1
        self._range = (0, 0)
        self._is_stopped = False
        threading.Thread(target=self._schedule, name="prefetch", daemon=True).start()

    @staticmethod
    def key(source: MediaSource, number: int, layer: int) -> CacheKey:
        return (source.uid, layer, number)

    @property
    def used_bytes(self) -> int:
        return self._used_bytes

    def follow(self, source: MediaSource | None, layer: int, playhead: int, direction: int,
               play_range: tuple[int, int]) -> None:
        with self._condition:
            self._source, self._layer = source, layer
            self._playhead, self._direction = playhead, direction or 1
            self._range = play_range
            self._condition.notify_all()

    def get(self, source: MediaSource, number: int, layer: int) -> Frame | None:
        return self._frames.get(self.key(source, number, layer))

    def error_for(self, source: MediaSource, number: int, layer: int) -> str | None:
        return self._errors.get(self.key(source, number, layer))

    def cached_numbers(self, source: MediaSource, layer: int) -> set[int]:
        with self._condition:
            return {k[2] for k in self._frames if k[0] == source.uid and k[1] == layer}

    def read_now(self, source: MediaSource, number: int, layer: int) -> Frame | None:
        cached = self.get(source, number, layer)
        if cached is not None:
            return cached
        key = self.key(source, number, layer)
        frame = self._read(source, key)
        if frame is not None:
            self._store(key, frame)
        return frame

    def set_budget(self, max_bytes: int) -> None:
        with self._condition:
            self.max_bytes = max_bytes
            self._make_room(0, needed_in=-1)
            self._condition.notify_all()

    def clear(self) -> None:
        """Drop every cached frame and remembered error; prefetching refills from the playhead."""
        with self._condition:
            self._frames.clear()
            self._errors.clear()
            self._used_bytes = 0
            self._condition.notify_all()

    def forget(self, source: MediaSource) -> None:
        with self._condition:
            for key in [k for k in self._frames if k[0] == source.uid]:
                self._used_bytes -= self._frames.pop(key).nbytes
            for key in [k for k in self._errors if k[0] == source.uid]:
                del self._errors[key]

    def shutdown(self) -> None:
        with self._condition:
            self._is_stopped = True
            self._condition.notify_all()
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _frames_until_needed(self, key: CacheKey) -> float:
        if self._source is None or key[0] != self._source.uid or key[1] != self._layer:
            return float("inf")
        first, last = self._range
        span = last - first + 1
        if not first <= key[2] <= last:
            return span + abs(key[2] - self._playhead)
        return ((key[2] - self._playhead) * self._direction) % span

    def _make_room(self, incoming: int, needed_in: float) -> bool:
        while self._frames and self._used_bytes + incoming > self.max_bytes:
            victim = max(self._frames, key=self._frames_until_needed)
            if self._frames_until_needed(victim) <= needed_in:
                return False
            self._used_bytes -= self._frames.pop(victim).nbytes
        return self._used_bytes + incoming <= self.max_bytes

    def _store(self, key: CacheKey, frame: Frame) -> None:
        with self._condition:
            if key in self._frames:
                return
            self._frame_bytes = frame.nbytes
            if not self._make_room(frame.nbytes, self._frames_until_needed(key)):
                return
            self._frames[key] = frame
            self._used_bytes += frame.nbytes
            self._condition.notify_all()

    def _wanted(self) -> list[CacheKey]:
        source = self._source
        first, last = self._range
        span = last - first + 1
        frame_bytes = self._frame_bytes or max(1, source.width * source.height * 8)
        count = min(span, max(1, self.max_bytes // frame_bytes))
        wanted = []
        for offset in range(count):
            number = first + (self._playhead - first + offset * self._direction) % span
            key = (source.uid, self._layer, number)
            if key not in self._frames and key not in self._pending and key not in self._errors:
                wanted.append(key)
        return wanted

    def _next_batch(self) -> list[CacheKey]:
        if self._source is None:
            return []
        wanted = self._wanted()
        if not self._source.parallel_reads:
            busy = any(k[0] == self._source.uid for k in self._pending)
            return [] if busy else wanted[:1]
        return wanted[:max(0, self.workers * 2 - len(self._pending))]

    def _schedule(self) -> None:
        while True:
            with self._condition:
                if self._is_stopped:
                    return
                batch = self._next_batch()
                if not batch:
                    self._condition.wait(IDLE_WAIT_SECONDS)
                    continue
                self._pending.update(batch)
                source = self._source
            try:
                for key in batch:
                    self._pool.submit(self._load, source, key)
            except RuntimeError:
                return  # pool shut down between the stop check and the submit

    def _read(self, source: MediaSource, key: CacheKey) -> Frame | None:
        try:
            return source.read(key[2], key[1])
        except (ProexrError, OSError, ValueError, RuntimeError) as error:
            with self._condition:
                self._errors[key] = str(error)
            return None

    def _load(self, source: MediaSource, key: CacheKey) -> None:
        frame = None
        if source is self._source and key[1] == self._layer:
            frame = self._read(source, key)
        if frame is not None:
            self._store(key, frame)
        with self._condition:
            self._pending.discard(key)
            self._condition.notify_all()
        if frame is not None and self.on_frame_ready is not None:
            self.on_frame_ready(key)
