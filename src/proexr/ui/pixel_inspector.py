from PySide6.QtWidgets import QCheckBox, QGridLayout, QLabel, QWidget

from ..analysis.scopes import PixelReport
from . import palette


class PixelInspector(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(12, 10, 12, 10)
        self.freeze = QCheckBox("Freeze (keep current pixel)")
        self.position = QLabel("Move the cursor over the image")
        self.position.setProperty("role", "muted")
        self.details = QLabel()
        self.details.setStyleSheet(f"font-family: {palette.MONO_FAMILY};")
        self.grid.addWidget(self.freeze, 0, 0)
        self.grid.addWidget(self.position, 1, 0)
        self.grid.addWidget(self.details, 2, 0)
        self.grid.setRowStretch(3, 1)

    def show_report(self, report: PixelReport | None) -> None:
        if self.freeze.isChecked() or report is None:
            return
        self.position.setText(f"Pixel  x {report.x}   y {report.y}")
        lines = []
        for name, raw, value, mean in zip(report.channel_names, report.raw, report.values, report.area_average,
                                          strict=False):
            short = name.rpartition(".")[2]
            raw_text = f"  ({raw})" if isinstance(raw, int) else ""
            lines.append(f"{short:<6}{value:>11.5f}{raw_text}   avg {mean:.5f}")
        lines.append("")
        lines.append(f"Luminance {report.luminance:.5f}")
        lines.append(f"Stops vs 18% grey {report.stops:+.2f}" if report.luminance > 0 else "Stops vs 18% grey  -inf")
        self.details.setText("\n".join(lines))
