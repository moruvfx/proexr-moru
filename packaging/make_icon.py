"""Draws the app icon (dark rounded square, red play triangle over EXR-style channel bars) into a multi-size .ico."""
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPainterPath, QPolygonF

SIZES = (16, 24, 32, 48, 64, 128, 256)


def render(size: int) -> QImage:
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    scale = size / 256
    painter.scale(scale, scale)
    path = QPainterPath()
    path.addRoundedRect(QRectF(8, 8, 240, 240), 48, 48)
    painter.fillPath(path, QColor("#17171C"))
    for i, color in enumerate(("#E5484D", "#46A758", "#3E63DD")):
        painter.fillRect(QRectF(48, 172 + i * 16, 160, 10), QColor(color))
    painter.setBrush(QColor("#F2F2F5"))
    painter.setPen(Qt.NoPen)
    painter.drawPolygon(QPolygonF([QPointF(100, 52), QPointF(172, 100), QPointF(100, 148)]))
    painter.end()
    return image


def main(target: str) -> None:
    QGuiApplication(sys.argv[:1])
    images = [render(size) for size in SIZES]
    images[-1].save(str(Path(__file__).resolve().parents[1] / "src" / "proexr" / "resources" / "proexr.png"))
    # Qt's ICO writer stores one image per file, so assemble the multi-size icon by hand (PNG-compressed entries).
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    blobs = []
    for image in images:
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.WriteOnly)
        image.save(buffer, "PNG")
        blobs.append(bytes(data))
    header = (0).to_bytes(2, "little") + (1).to_bytes(2, "little") + len(blobs).to_bytes(2, "little")
    offset = 6 + 16 * len(blobs)
    entries = b""
    for size, blob in zip(SIZES, blobs, strict=True):
        dim = 0 if size >= 256 else size
        entries += bytes([dim, dim, 0, 0]) + (1).to_bytes(2, "little") + (32).to_bytes(2, "little")
        entries += len(blob).to_bytes(4, "little") + offset.to_bytes(4, "little")
        offset += len(blob)
    Path(target).write_bytes(header + entries + b"".join(blobs))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "packaging/proexr.ico")
