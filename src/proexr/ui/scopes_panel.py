import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QImage, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QComboBox, QVBoxLayout, QWidget

from ..analysis.scopes import CB_WEIGHTS, CR_WEIGHTS, histogram, vectorscope, waveform
from . import palette

SCOPE_RESOLUTION = 256
SCOPE_MODES = ("Waveform (RGB)", "Parade", "Histogram", "Vectorscope")
VECTOR_TARGETS = {"R": (0.75, 0, 0), "Y": (0.75, 0.75, 0), "G": (0, 0.75, 0),
                  "C": (0, 0.75, 0.75), "B": (0, 0, 0.75), "M": (0.75, 0, 0.75)}


def _intensity(counts: np.ndarray) -> np.ndarray:
    scaled = np.log1p(counts.astype(np.float32))
    peak = scaled.max()
    return (scaled / peak * 255).astype(np.uint8) if peak > 0 else scaled.astype(np.uint8)


def _to_image(rgb: np.ndarray) -> QImage:
    data = np.ascontiguousarray(rgb)
    image = QImage(data.data, data.shape[1], data.shape[0], data.shape[1] * 3, QImage.Format_RGB888)
    return image.copy()


class ScopeCanvas(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(240, 180)
        self.mode = 0
        self.image: QImage | None = None
        self.histogram: np.ndarray | None = None

    def show_sample(self, sample: np.ndarray) -> None:
        size = SCOPE_RESOLUTION
        if self.mode in (0, 1):
            trace = _intensity(waveform(sample, columns=size, levels=size))[:, ::-1]
            if self.mode == 0:
                rgb = np.stack([trace[0], trace[1], trace[2]], axis=-1)
            else:
                rgb = np.zeros((size, size * 3, 3), np.uint8)
                for channel in range(3):
                    rgb[:, channel * size:(channel + 1) * size, channel] = trace[channel]
            self.image, self.histogram = _to_image(rgb), None
        elif self.mode == 2:
            self.image, self.histogram = None, histogram(sample, bins=size)
        else:
            density = _intensity(vectorscope(sample, size=size))
            self.image, self.histogram = _to_image(np.stack([density] * 3, axis=-1)), None
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), palette.BACKGROUND)
        area = QRectF(self.rect()).adjusted(8, 8, -8, -8)
        if self.mode == 3:
            side = min(area.width(), area.height())
            area = QRectF(area.center().x() - side / 2, area.center().y() - side / 2, side, side)
        if self.image is not None:
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            painter.drawImage(area, self.image)
        if self.histogram is not None:
            self._paint_histogram(painter, area)
        self._paint_graticule(painter, area)
        painter.end()

    def _paint_histogram(self, painter: QPainter, area: QRectF) -> None:
        counts = self.histogram[:3].astype(np.float32)
        peak = np.percentile(counts, 99.5) or 1.0
        colors = (palette.SCOPE_RED, palette.SCOPE_GREEN, palette.SCOPE_BLUE)
        bins = counts.shape[1]
        for channel, color in enumerate(colors):
            painter.setPen(QPen(color, 1))
            points = [QPointF(area.left() + i / (bins - 1) * area.width(),
                              area.bottom() - min(1.0, counts[channel, i] / peak) * area.height()) for i in range(bins)]
            painter.drawPolyline(points)

    def _paint_graticule(self, painter: QPainter, area: QRectF) -> None:
        painter.setPen(QPen(palette.GUIDE, 1, Qt.DotLine))
        if self.mode == 3:
            painter.drawEllipse(area)
            center = area.center()
            painter.drawLine(QPointF(area.left(), center.y()), QPointF(area.right(), center.y()))
            painter.drawLine(QPointF(center.x(), area.top()), QPointF(center.x(), area.bottom()))
            painter.setPen(palette.TEXT_MUTED)
            for label, rgb in VECTOR_TARGETS.items():
                cb, cr = float(np.dot(rgb, CB_WEIGHTS)), float(np.dot(rgb, CR_WEIGHTS))
                x = area.left() + (cb + 0.5) * area.width()
                y = area.top() + (0.5 - cr) * area.height()
                painter.drawRect(QRectF(x - 5, y - 5, 10, 10))
                painter.drawText(QPointF(x + 7, y + 4), label)
            return
        for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
            y = area.bottom() - fraction * area.height()
            painter.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
            painter.drawText(QPointF(area.left() + 2, y - 2), f"{int(fraction * 100)}")


class ScopesPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        column = QVBoxLayout(self)
        column.setContentsMargins(6, 6, 6, 6)
        self.mode_box = QComboBox()
        self.mode_box.addItems(SCOPE_MODES)
        self.mode_box.setAccessibleName("Scope type")
        self.canvas = ScopeCanvas()
        column.addWidget(self.mode_box)
        column.addWidget(self.canvas, 1)
        self.mode_box.currentIndexChanged.connect(self._set_mode)
        self._last_sample: np.ndarray | None = None

    def _set_mode(self, index: int) -> None:
        self.canvas.mode = index
        if self._last_sample is not None:
            self.canvas.show_sample(self._last_sample)

    def show_sample(self, sample: np.ndarray) -> None:
        self._last_sample = sample
        self.canvas.show_sample(sample)
