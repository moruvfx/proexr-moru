from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QFont, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from . import palette

MARGIN = 12
RULER_TOP = 18
TICK_STEPS = (1, 2, 5, 10, 12, 24, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000, 10000)
LABEL_SPACING = 72
TIMECODE_LABEL_SPACING = 112


class Timeline(QWidget):
    scrubbed = Signal(int)
    scrubStarted = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(52)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.first = self.last = 0
        self.in_point = self.out_point = 0
        self.current = 0
        self.fps = 24.0
        self.cached: set[int] = set()
        self.missing: set[int] = set()
        self.shows_timecode = False
        self._hovered: int | None = None
        self._is_scrubbing = False

    def set_range(self, first: int, last: int, fps: float, missing: list[int]) -> None:
        self.first, self.last = first, max(first, last)
        self.in_point, self.out_point = self.first, self.last
        self.fps = fps
        self.missing = set(missing)
        self.cached = set()
        self.update()

    def set_current(self, number: int) -> None:
        if number != self.current:
            self.current = number
            self.update()

    def set_cached(self, numbers: set[int]) -> None:
        if numbers != self.cached:
            self.cached = numbers
            self.update()

    def _frame_width(self) -> float:
        return (self.width() - 2 * MARGIN) / max(1, self.last - self.first + 1)

    def _x(self, number: int) -> float:
        return MARGIN + (number - self.first) * self._frame_width()

    def frame_at(self, x: float) -> int:
        number = self.first + int((x - MARGIN) / max(1e-6, self._frame_width()))
        return max(self.first, min(self.last, number))

    def _label(self, number: int) -> str:
        if not self.shows_timecode:
            return str(number)
        fps = max(1, round(self.fps))
        seconds, frames = divmod(number, fps)
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{frames:02d}"

    def _runs(self, numbers: set[int]) -> list[tuple[int, int]]:
        runs: list[tuple[int, int]] = []
        for number in sorted(numbers):
            if runs and number == runs[-1][1] + 1:
                runs[-1] = (runs[-1][0], number)
            else:
                runs.append((number, number))
        return runs

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        width, height = self.width(), self.height()
        frame_w = self._frame_width()
        painter.fillRect(self.rect(), palette.SURFACE)
        in_x, out_x = self._x(self.in_point), self._x(self.out_point + 1)
        painter.fillRect(QRectF(in_x, RULER_TOP, out_x - in_x, height - RULER_TOP), palette.SURFACE_RAISED)
        for start, end in self._runs(self.cached):
            painter.fillRect(QRectF(self._x(start), height - 5, max(1.0, self._x(end + 1) - self._x(start)), 3),
                             palette.CACHED)
        for number in self.missing:
            painter.fillRect(QRectF(self._x(number), height - 5, max(1.0, frame_w), 3), palette.MISSING)
        font = QFont(self.font())
        font.setPointSizeF(8.5)
        painter.setFont(font)
        spacing = TIMECODE_LABEL_SPACING if self.shows_timecode else LABEL_SPACING
        step = next((s for s in TICK_STEPS if s * frame_w >= spacing), TICK_STEPS[-1])
        for number in range((self.first // step) * step, self.last + 2, step):
            if number < self.first:
                continue
            x = int(self._x(number))
            painter.setPen(QPen(palette.BORDER_STRONG, 1))
            painter.drawLine(x, RULER_TOP, x, height - 8)
            painter.setPen(palette.TEXT_FAINT)
            painter.drawText(x + 4, 13, self._label(number))
        if frame_w >= 5:
            painter.setPen(QPen(palette.BORDER, 1))
            for number in range(self.first, self.last + 1):
                x = int(self._x(number))
                painter.drawLine(x, height - 14, x, height - 8)
        painter.setPen(QPen(palette.TEXT_MUTED, 2))
        painter.drawLine(int(in_x), RULER_TOP, int(in_x), height)
        painter.drawLine(int(out_x), RULER_TOP, int(out_x), height)
        if self._hovered is not None and not self._is_scrubbing:
            painter.setPen(QPen(palette.GUIDE, 1))
            x = int(self._x(self._hovered) + frame_w / 2)
            painter.drawLine(x, RULER_TOP, x, height)
        x = self._x(self.current)
        painter.fillRect(QRectF(x, RULER_TOP, max(2.0, frame_w), height - RULER_TOP), palette.ACCENT_SOFT)
        painter.setPen(QPen(palette.ACCENT, 2))
        center = int(x + frame_w / 2)
        painter.drawLine(center, RULER_TOP, center, height)
        label = self._label(self.current)
        label_w = painter.fontMetrics().horizontalAdvance(label) + 12
        label_x = min(max(0, center - label_w // 2), width - label_w)
        painter.fillRect(QRectF(label_x, 0, label_w, 17), palette.ACCENT)
        painter.setPen(palette.TEXT)
        painter.drawText(QRectF(label_x, 0, label_w, 17), Qt.AlignCenter, label)
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._is_scrubbing = True
            self.scrubStarted.emit()
            self.scrubbed.emit(self.frame_at(event.position().x()))

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        number = self.frame_at(event.position().x())
        if self._is_scrubbing:
            self.scrubbed.emit(number)
        elif number != self._hovered:
            self._hovered = number
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._is_scrubbing = False

    def leaveEvent(self, event) -> None:
        self._hovered = None
        self.update()
