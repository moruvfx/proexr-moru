from collections.abc import Callable
from enum import Enum

MAX_FRAMES_PER_TICK = 240
REALTIME_PATIENCE_SECONDS = 0.25


class LoopMode(Enum):
    LOOP = "loop"
    PINGPONG = "pingpong"
    ONCE = "once"


class PlaybackClock:
    def __init__(self, first: int, last: int, fps: float, loop_mode: LoopMode = LoopMode.LOOP,
                 realtime: bool = True, is_ready: Callable[[int], bool] = lambda number: True) -> None:
        self.first, self.last = first, last
        self.in_point, self.out_point = first, last
        self.current = first
        self.fps = fps
        self.speed = 1.0
        self.direction = 0
        self.loop_mode = loop_mode
        self.realtime = realtime
        self.is_ready = is_ready
        self.dropped = 0
        self._started_at = 0.0

    @property
    def is_playing(self) -> bool:
        return self.direction != 0

    @property
    def rate(self) -> float:
        return max(0.01, self.fps * self.speed)

    def set_range(self, first: int, last: int) -> None:
        self.first, self.last = first, last
        self.in_point, self.out_point = first, last
        self.current = min(max(self.current, first), last)

    def set_in_out(self, in_point: int, out_point: int) -> None:
        self.in_point = max(self.first, min(in_point, out_point))
        self.out_point = min(self.last, max(in_point, out_point))

    def seek(self, number: int) -> None:
        self.current = min(max(number, self.first), self.last)

    def start(self, direction: int, now: float) -> None:
        if not self.in_point <= self.current <= self.out_point:
            self.current = self.in_point if direction > 0 else self.out_point
        elif self.loop_mode is LoopMode.ONCE and self._step(self.current, direction)[0] is None:
            self.current = self.in_point if direction > 0 else self.out_point
        self.direction = direction
        self.dropped = 0
        self._started_at = now

    def stop(self) -> None:
        self.direction = 0

    def restart_timing(self, now: float) -> None:
        self._started_at = now

    def _step(self, number: int, direction: int) -> tuple[int | None, int]:
        following = number + direction
        if self.in_point <= following <= self.out_point:
            return following, direction
        if self.loop_mode is LoopMode.LOOP:
            return (self.in_point if direction > 0 else self.out_point), direction
        if self.loop_mode is LoopMode.PINGPONG and self.in_point != self.out_point:
            return number - direction, -direction
        return None, direction

    def tick(self, now: float) -> int | None:
        if not self.is_playing:
            return None
        due = int((now - self._started_at) * self.rate)
        if due <= 0:
            return None
        if self.realtime:
            return self._tick_realtime(now, due)
        return self._tick_every_frame(now)

    def _tick_realtime(self, now: float, due: int) -> int | None:
        number, direction = self.current, self.direction
        newest, newest_direction, steps = None, direction, 0
        for _ in range(min(due, MAX_FRAMES_PER_TICK)):
            number, direction = self._step(number, direction)
            if number is None:
                break
            steps += 1
            if self.is_ready(number):
                newest, newest_direction = number, direction
        if newest is None:
            if self._step(self.current, self.direction)[0] is None:
                self.stop()
            elif due > self.rate * REALTIME_PATIENCE_SECONDS:
                self._started_at = now
            return None
        if newest == number:
            self.dropped += steps - 1
            self._started_at += steps / self.rate
        else:
            self._started_at = now
        self.current, self.direction = newest, newest_direction
        return newest

    def _tick_every_frame(self, now: float) -> int | None:
        following, direction = self._step(self.current, self.direction)
        if following is None:
            self.stop()
            return None
        if not self.is_ready(following):
            return None
        self.current, self.direction = following, direction
        self._started_at += 1.0 / self.rate
        if now - self._started_at > 2.0 / self.rate:
            self._started_at = now - 1.0 / self.rate
        return following
