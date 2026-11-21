"""Playback clock.

Advances the playhead from a high-resolution clock rather than counting timer
ticks, so the effective frame rate does not drift. Only frames that are
already decoded are shown; if decoding falls behind the player either skips
ahead to the newest ready frame (realtime) or waits (every frame).
"""
from __future__ import annotations

import time
from collections import deque

from PySide6.QtCore import QObject, Qt, QTimer, Signal

LOOP, PINGPONG, ONCE = "loop", "pingpong", "once"


class Player(QObject):
    frameChanged = Signal(int)
    stateChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.first = self.last = 0
        self.in_point = self.out_point = 0
        self.current = 0
        self.fps = 24.0
        self.speed = 1.0
        self.direction = 0          # -1, 0, +1
        self.loop_mode = LOOP
        self.realtime = True
        self.is_ready = lambda f: True
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._anchor = 0
        self._t0 = 0.0
        self._shown = deque(maxlen=120)
        self.dropped = 0

    # ---------------------------------------------------------- setup ----
    def set_range(self, first, last, fps=None):
        self.first, self.last = first, last
        self.in_point, self.out_point = first, last
        if fps:
            self.fps = fps
        self.current = min(max(self.current, first), last)

    def set_in(self, f=None):
        self.in_point = self.current if f is None else f
        if self.out_point < self.in_point:
            self.out_point = self.last
        self.stateChanged.emit()

    def set_out(self, f=None):
        self.out_point = self.current if f is None else f
        if self.in_point > self.out_point:
            self.in_point = self.first
        self.stateChanged.emit()

    def clear_in_out(self):
        self.in_point, self.out_point = self.first, self.last
        self.stateChanged.emit()

    @property
    def playing(self):
        return self.direction != 0

    @property
    def rate(self):
        return max(0.01, self.fps * self.speed)

    # ---------------------------------------------------------- control --
    def play(self, direction=1):
        if direction == self.direction:
            return
        if not (self.in_point <= self.current <= self.out_point):
            self.seek(self.in_point if direction > 0 else self.out_point)
        elif self.loop_mode == ONCE:
            if direction > 0 and self.current >= self.out_point:
                self.seek(self.in_point)
            elif direction < 0 and self.current <= self.in_point:
                self.seek(self.out_point)
        self.direction = direction
        self._rebase()
        self.dropped = 0
        self._timer.start(max(1, int(1000.0 / self.rate / 4)))
        self.stateChanged.emit()

    def stop(self):
        if self.direction:
            self.direction = 0
            self._timer.stop()
            self.stateChanged.emit()

    def toggle(self):
        if self.playing:
            self.stop()
        else:
            self.play(1)

    def seek(self, f):
        f = int(min(max(f, self.first), self.last))
        if f != self.current:
            self.current = f
            self.frameChanged.emit(f)
        self._rebase()

    def step(self, n):
        self.stop()
        f = self.current + n
        lo, hi = self.in_point, self.out_point
        if f > hi:
            f = lo
        elif f < lo:
            f = hi
        self.seek(f)

    def set_speed(self, s):
        self.speed = s
        self._rebase()
        if self.playing:
            self._timer.setInterval(max(1, int(1000.0 / self.rate / 4)))

    def set_fps(self, fps):
        self.fps = fps
        self.set_speed(self.speed)

    # ---------------------------------------------------------- clock ----
    def _rebase(self):
        self._anchor = self.current
        self._t0 = time.perf_counter()

    def _next(self, f, d):
        """Frame after f in direction d, honouring the loop mode. Returns (frame, dir)."""
        lo, hi = self.in_point, self.out_point
        n = f + d
        if lo <= n <= hi:
            return n, d
        if self.loop_mode == LOOP:
            return (lo if d > 0 else hi), d
        if self.loop_mode == PINGPONG:
            if hi == lo:
                return f, d
            return f - d, -d
        return None, d   # once: stop

    def _tick(self):
        if not self.direction:
            return
        now = time.perf_counter()
        due = int((now - self._t0) * self.rate)
        if due <= 0:
            return
        if self.realtime:
            # walk forward `due` frames, remember the furthest ready one
            f, d = self.current, self.direction
            best, best_d, steps = None, d, 0
            for _ in range(min(due, 240)):
                nf, d = self._next(f, d)
                if nf is None:
                    break
                f = nf
                steps += 1
                if self.is_ready(f):
                    best, best_d = f, d
            if best is None:
                if self._next(self.current, self.direction)[0] is None:
                    self.stop()
                    return
                if due > self.rate * 0.25:          # waited too long: wait, don't jump
                    self._t0 = now
                return
            self.dropped += max(0, steps - 1) if best == f else 0
            self.direction = best_d
            self._show(best)
            self._anchor = best
            self._t0 += due / self.rate if best == f else 0
            if best != f:
                self._t0 = now
        else:
            nf, d = self._next(self.current, self.direction)
            if nf is None:
                self.stop()
                return
            if not self.is_ready(nf):
                return
            self.direction = d
            self._show(nf)
            self._t0 += 1.0 / self.rate
            if now - self._t0 > 2.0 / self.rate:
                self._t0 = now

    def _show(self, f):
        self.current = f
        self._shown.append(time.perf_counter())
        self.frameChanged.emit(f)

    def measured_fps(self) -> float:
        if len(self._shown) < 2 or not self.playing:
            return 0.0
        span = self._shown[-1] - self._shown[0]
        return (len(self._shown) - 1) / span if span > 0 else 0.0
