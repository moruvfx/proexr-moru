"""Timeline ruler with playhead, in/out range and cache indicator."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

ACCENT = QColor(255, 140, 50)


class Timeline(QWidget):
    scrubbed = Signal(int)
    scrubStarted = Signal()
    scrubFinished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(46)
        self.setMouseTracking(True)
        self.first, self.last = 0, 0
        self.in_point, self.out_point = 0, 0
        self.current = 0
        self.cached: set[int] = set()
        self.missing: set[int] = set()
        self.fps = 24.0
        self.show_timecode = False
        self._hover = None
        self._dragging = False

    def set_range(self, first, last, fps=24.0, missing=()):
        self.first, self.last = first, max(first, last)
        self.in_point, self.out_point = self.first, self.last
        self.fps = fps
        self.missing = set(missing)
        self.update()

    def set_current(self, f):
        if f != self.current:
            self.current = f
            self.update()

    def set_cached(self, frames):
        self.cached = frames
        self.update()

    # geometry
    def _x(self, f):
        m = 10
        n = max(1, self.last - self.first + 1)
        return m + (f - self.first) / n * (self.width() - 2 * m)

    def _frame_at(self, x):
        m = 10
        n = max(1, self.last - self.first + 1)
        f = self.first + int((x - m) / max(1, self.width() - 2 * m) * n)
        return max(self.first, min(self.last, f))

    def _label(self, f):
        if not self.show_timecode:
            return str(f)
        fps = max(1, round(self.fps))
        s, fr = divmod(f, fps)
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}:{fr:02d}"

    def paintEvent(self, e):
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor(30, 30, 33))
        n = self.last - self.first + 1
        fw = (w - 20) / max(1, n)
        # in/out range
        xi, xo = self._x(self.in_point), self._x(self.out_point + 1)
        p.fillRect(QRectF(xi, 0, xo - xi, h), QColor(44, 44, 50))
        # cache bar
        bar_y = h - 5
        if self.cached:
            p.setPen(Qt.NoPen)
            col = QColor(70, 190, 110)
            runs = sorted(self.cached)
            start = prev = runs[0]
            for f in runs[1:] + [None]:
                if f is not None and f == prev + 1:
                    prev = f
                    continue
                x0, x1 = self._x(start), self._x(prev + 1)
                p.fillRect(QRectF(x0, bar_y, max(1.0, x1 - x0), 3), col)
                if f is not None:
                    start = prev = f
        for f in self.missing:
            x = self._x(f)
            p.fillRect(QRectF(x, bar_y, max(1.0, fw), 3), QColor(220, 70, 60))
        # ticks
        font = QFont(self.font())
        font.setPointSizeF(8)
        p.setFont(font)
        target_px = 70 if not self.show_timecode else 110
        steps = [1, 2, 5, 10, 12, 24, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000, 10000]
        step = next((s for s in steps if s * fw >= target_px), steps[-1])
        start = (self.first // step) * step
        for f in range(start, self.last + 2, step):
            if f < self.first:
                continue
            x = self._x(f)
            p.setPen(QPen(QColor(90, 90, 98), 1))
            p.drawLine(int(x), 18, int(x), h - 8)
            p.setPen(QColor(150, 150, 158))
            p.drawText(int(x) + 3, 13, self._label(f))
        if fw >= 4:
            p.setPen(QPen(QColor(60, 60, 66), 1))
            for f in range(self.first, self.last + 1):
                x = int(self._x(f))
                p.drawLine(x, h - 14, x, h - 8)
        # in/out markers
        p.setPen(QPen(ACCENT.darker(130), 2))
        p.drawLine(int(xi), 16, int(xi), h)
        p.drawLine(int(xo), 16, int(xo), h)
        # hover
        if self._hover is not None and not self._dragging:
            x = self._x(self._hover) + fw / 2
            p.setPen(QPen(QColor(255, 255, 255, 50), 1))
            p.drawLine(int(x), 16, int(x), h)
        # playhead
        x = self._x(self.current)
        p.fillRect(QRectF(x, 16, max(2.0, fw), h - 16), QColor(255, 140, 50, 90))
        p.setPen(QPen(ACCENT, 2))
        p.drawLine(int(x + fw / 2), 16, int(x + fw / 2), h)
        label = self._label(self.current)
        tw = p.fontMetrics().horizontalAdvance(label) + 10
        lx = min(max(0, int(x + fw / 2 - tw / 2)), w - tw)
        p.fillRect(lx, 0, tw, 16, ACCENT)
        p.setPen(QColor(20, 20, 20))
        p.drawText(QRectF(lx, 0, tw, 16), Qt.AlignCenter, label)
        p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._dragging = True
            self.scrubStarted.emit()
            self.scrubbed.emit(self._frame_at(e.position().x()))

    def mouseMoveEvent(self, e):
        f = self._frame_at(e.position().x())
        if self._dragging:
            self.scrubbed.emit(f)
        elif f != self._hover:
            self._hover = f
            self.update()

    def mouseReleaseEvent(self, e):
        if self._dragging:
            self._dragging = False
            self.scrubFinished.emit()

    def leaveEvent(self, e):
        self._hover = None
        self.update()
