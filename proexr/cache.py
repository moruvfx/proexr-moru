"""Frame cache with play-direction-aware prefetching.

* Image sequences are decoded by a pool of worker threads (OpenImageIO and
  OpenEXR release the GIL, so decoding really runs in parallel).
* Video is decoded by one dedicated thread per source, sequentially, because
  FFmpeg decoders are stateful; FFmpeg itself uses frame threads internally.
* Eviction drops the frame that playback will need *last* (looping aware),
  which keeps a loop that fits in memory fully cached.
"""
from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

from .media.source import Frame, MediaSource


class FrameCache:
    def __init__(self, max_bytes: int = 4 << 30, workers: int | None = None):
        self.max_bytes = max_bytes
        self.workers = workers or max(2, min(16, (os.cpu_count() or 4) - 1))
        self._frames: OrderedDict[tuple, Frame] = OrderedDict()
        self._bytes = 0
        self._lock = threading.RLock()
        self._cv = threading.Condition(self._lock)
        self._pending: set[tuple] = set()
        self._errors: dict[tuple, str] = {}
        self._pool = ThreadPoolExecutor(self.workers, thread_name_prefix="decode")
        self._video_threads: dict[int, threading.Thread] = {}

        # playback state, set by the UI
        self.source: MediaSource | None = None
        self.layer = 0
        self.playhead = 0
        self.direction = 1
        self.range = (0, 0)
        self.enabled = True
        self._generation = 0
        self.frame_bytes = 0

        self.on_frame_ready = None  # callback(key) from worker threads
        self._stop = False
        self._sched = threading.Thread(target=self._scheduler, name="prefetch", daemon=True)
        self._sched.start()

    # ------------------------------------------------------------ public --
    @staticmethod
    def key(source: MediaSource, frame: int, layer: int):
        return (source.uid, layer, frame)

    def get(self, source, frame, layer) -> Frame | None:
        k = self.key(source, frame, layer)
        with self._lock:
            fr = self._frames.get(k)
            if fr is not None:
                self._frames.move_to_end(k)
            return fr

    def error(self, source, frame, layer):
        return self._errors.get(self.key(source, frame, layer))

    def set_state(self, source, layer, playhead, direction, frange):
        with self._cv:
            if source is not self.source or layer != self.layer:
                self._generation += 1
            self.source, self.layer = source, layer
            self.playhead, self.direction, self.range = playhead, direction or 1, frange
            self._cv.notify_all()

    def cached_frames(self, source, layer) -> set[int]:
        with self._lock:
            return {k[2] for k in self._frames if k[0] == source.uid and k[1] == layer}

    @property
    def used_bytes(self):
        return self._bytes

    def clear(self, source=None):
        with self._lock:
            for k in [k for k in self._frames if source is None or k[0] == source.uid]:
                self._bytes -= self._frames.pop(k).nbytes
            self._errors.clear()

    def set_budget(self, max_bytes):
        with self._cv:
            self.max_bytes = max_bytes
            self._evict(0)
            self._cv.notify_all()

    def shutdown(self):
        with self._cv:
            self._stop = True
            self._cv.notify_all()
        self._pool.shutdown(wait=False, cancel_futures=True)

    # ---------------------------------------------------------- internals --
    def _distance(self, frame):
        """How far in the future playback reaches this frame (loop aware)."""
        a, b = self.range
        n = max(1, b - a + 1)
        if not (a <= frame <= b):
            return n + abs(frame - self.playhead)
        return ((frame - self.playhead) * self.direction) % n

    def _evict(self, incoming: int, new_dist: float = -1):
        """Make room; refuse (False) if the newcomer is needed later than any victim."""
        while self._frames and self._bytes + incoming > self.max_bytes:
            cur = self.source.uid if self.source else None
            def score(k):
                if k[0] != cur or k[1] != self.layer:
                    return float("inf")
                return self._distance(k[2])
            victim = max(self._frames, key=score)
            if score(victim) <= new_dist:
                return False
            self._bytes -= self._frames.pop(victim).nbytes
        return True

    def _store(self, k, frame: Frame):
        with self._cv:
            if k in self._frames:
                return
            nd = self._distance(k[2]) if self.source and k[0] == self.source.uid else float("inf")
            if not self._evict(frame.nbytes, nd):
                return
            self._frames[k] = frame
            self._bytes += frame.nbytes
            self.frame_bytes = frame.nbytes
            self._cv.notify_all()

    def _wanted(self):
        """Frames to load next, nearest-in-play-order first."""
        src = self.source
        if src is None or not self.enabled:
            return []
        a, b = self.range
        n = b - a + 1
        fb = self.frame_bytes or (src.width * src.height * 4 * 2) or 1
        budget = max(1, int(self.max_bytes * 0.92 // fb))
        out = []
        for i in range(min(n, budget)):
            f = a + ((self.playhead - a) + i * self.direction) % n
            k = (src.uid, self.layer, f)
            if k not in self._frames and k not in self._pending and k not in self._errors:
                out.append(k)
        return out

    def _scheduler(self):
        while True:
            with self._cv:
                if self._stop:
                    return
                src = self.source
                wanted = self._wanted() if src else []
                if src is not None and not src.parallel:
                    wanted = wanted[:1] if not any(p[0] == src.uid for p in self._pending) else []
                else:
                    room = self.workers * 2 - len(self._pending)
                    wanted = wanted[:max(0, room)]
                if not wanted:
                    self._cv.wait(0.25)
                    continue
                for k in wanted:
                    self._pending.add(k)
                gen = self._generation
            for k in wanted:
                self._pool.submit(self._load, src, k, gen)

    def _load(self, src: MediaSource, k, gen):
        try:
            if gen != self._generation and not self._still_wanted(src, k):
                return
            frame = src.read(k[2], k[1])
            self._store(k, frame)
        except Exception as exc:  # keep going, report in UI
            with self._lock:
                self._errors[k] = str(exc)
        finally:
            with self._cv:
                self._pending.discard(k)
                self._cv.notify_all()
        cb = self.on_frame_ready
        if cb:
            cb(k)

    def _still_wanted(self, src, k):
        return self.source is src and k[1] == self.layer

    def load_now(self, source, frame, layer) -> Frame | None:
        """Synchronous read used for scrubbing when nothing is cached."""
        k = self.key(source, frame, layer)
        fr = self.get(source, frame, layer)
        if fr is not None:
            return fr
        try:
            fr = source.read(frame, layer)
        except Exception as exc:
            self._errors[k] = str(exc)
            return None
        self._store(k, fr)
        return fr
