import threading
import time
from collections import deque

WINDOW = 48


class RollingStats:
    """Thread-safe rolling average of durations plus an event rate over the last few seconds."""

    def __init__(self, window: int = WINDOW) -> None:
        self._durations: deque[float] = deque(maxlen=window)
        self._stamps: deque[float] = deque(maxlen=window)
        self._lock = threading.Lock()

    def add(self, seconds: float, now: float | None = None) -> None:
        with self._lock:
            self._durations.append(seconds)
            self._stamps.append(time.perf_counter() if now is None else now)

    @property
    def average_ms(self) -> float:
        with self._lock:
            return 1000 * sum(self._durations) / len(self._durations) if self._durations else 0.0

    def rate(self, now: float | None = None, horizon: float = 3.0) -> float:
        """Events per second over the last `horizon` seconds."""
        now = time.perf_counter() if now is None else now
        with self._lock:
            recent = [t for t in self._stamps if now - t <= horizon]
        if len(recent) < 2:
            return 0.0
        span = now - recent[0]
        return (len(recent) - 1) / span if span > 0 else 0.0

    def clear(self) -> None:
        with self._lock:
            self._durations.clear()
            self._stamps.clear()
