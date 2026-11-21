from functools import cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from . import palette

ICON_SIZE = 20
STROKE_WIDTH = 1.6


def _triangle(path: QPainterPath, left: float, right: float, pointing_right: bool) -> None:
    tip, base = (right, left) if pointing_right else (left, right)
    path.moveTo(base, 5)
    path.lineTo(tip, 10)
    path.lineTo(base, 15)
    path.closeSubpath()


def _bar(path: QPainterPath, x: float) -> None:
    path.moveTo(x, 5)
    path.lineTo(x, 15)


def _glyph(name: str) -> QPainterPath:
    path = QPainterPath()
    if name == "play":
        _triangle(path, 6, 15, True)
    elif name == "play_reverse":
        _triangle(path, 5, 14, False)
    elif name == "pause":
        _bar(path, 7.5)
        _bar(path, 12.5)
    elif name == "stop":
        path.addRect(QRectF(6, 6, 8, 8))
    elif name == "step_forward":
        _triangle(path, 5, 12, True)
        _bar(path, 15)
    elif name == "step_back":
        _triangle(path, 8, 15, False)
        _bar(path, 5)
    elif name == "to_start":
        _bar(path, 5)
        _triangle(path, 7, 15, False)
    elif name == "to_end":
        _triangle(path, 5, 13, True)
        _bar(path, 15)
    elif name == "fit":
        for x, y, dx, dy in ((4, 4, 1, 1), (16, 4, -1, 1), (4, 16, 1, -1), (16, 16, -1, -1)):
            path.moveTo(x, y + 4 * dy)
            path.lineTo(x, y)
            path.lineTo(x + 4 * dx, y)
    elif name == "actual_pixels":
        path.addRect(QRectF(4, 4, 12, 12))
        path.moveTo(9, 8)
        path.lineTo(10.5, 7)
        path.lineTo(10.5, 13)
    elif name == "fullscreen":
        path.addRect(QRectF(3.5, 5, 13, 10))
        path.moveTo(7, 10)
        path.lineTo(13, 10)
    elif name == "open":
        path.moveTo(3, 6)
        path.lineTo(8, 6)
        path.lineTo(9.5, 7.5)
        path.lineTo(17, 7.5)
        path.lineTo(17, 15)
        path.lineTo(3, 15)
        path.closeSubpath()
    return path


@cache
def make_icon(name: str) -> QIcon:
    """Builds a thin line icon by name ("play", "stop", "fit"...) in normal, active and disabled colours."""
    icon = QIcon()
    for mode, color in ((QIcon.Normal, palette.TEXT), (QIcon.Active, palette.TEXT),
                        (QIcon.Selected, palette.ACCENT_TEXT), (QIcon.Disabled, palette.TEXT_FAINT)):
        for scale in (1, 2):
            icon.addPixmap(_render(name, QColor(color), scale), mode, QIcon.Off)
            icon.addPixmap(_render(name, QColor(palette.ACCENT_TEXT), scale), mode, QIcon.On)
    return icon


def _render(name: str, color: QColor, scale: int) -> QPixmap:
    pixmap = QPixmap(ICON_SIZE * scale, ICON_SIZE * scale)
    pixmap.setDevicePixelRatio(scale)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(color, STROKE_WIDTH, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.drawPath(_glyph(name).translated(QPointF(0, 0)))
    painter.end()
    return pixmap
