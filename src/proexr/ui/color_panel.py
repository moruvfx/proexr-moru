from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSlider, QWidget


class ResettableSlider(QSlider):
    resetRequested = Signal()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        self.resetRequested.emit()


class SliderField(QWidget):
    valueChanged = Signal(float)

    def __init__(self, minimum: float, maximum: float, default: float, step: float, decimals: int) -> None:
        super().__init__()
        self.default = default
        self._scale = 1.0 / step
        self._is_syncing = False
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.slider = ResettableSlider(Qt.Horizontal)
        self.slider.setRange(round(minimum * self._scale), round(maximum * self._scale))
        self.slider.setToolTip("Double-click to reset")
        self.slider.setMinimumWidth(140)
        self.field = QDoubleSpinBox()
        self.field.setRange(minimum, maximum)
        self.field.setDecimals(decimals)
        self.field.setSingleStep(step * 10)
        self.field.setKeyboardTracking(False)
        self.field.setFixedWidth(76)
        row.addWidget(self.slider, 1)
        row.addWidget(self.field)
        self.slider.valueChanged.connect(self._slider_moved)
        self.field.valueChanged.connect(self._field_changed)
        self.slider.resetRequested.connect(self.reset)
        self.set_value(default)

    def _slider_moved(self, position: int) -> None:
        if not self._is_syncing:
            self._sync(position / self._scale)

    def _field_changed(self, value: float) -> None:
        if not self._is_syncing:
            self._sync(value)

    def _sync(self, value: float) -> None:
        self._is_syncing = True
        self.field.setValue(value)
        self.slider.setValue(round(value * self._scale))
        self._is_syncing = False
        self.valueChanged.emit(self.field.value())

    def value(self) -> float:
        return self.field.value()

    def set_value(self, value: float) -> None:
        self._sync(value)

    def reset(self) -> None:
        self._sync(self.default)


class ColorPanel(QWidget):
    gradeChanged = Signal(dict)

    def __init__(self) -> None:
        super().__init__()
        grid = QGridLayout(self)
        grid.setContentsMargins(12, 10, 12, 10)
        grid.setVerticalSpacing(8)
        self.exposure = SliderField(-10.0, 10.0, 0.0, 0.01, 2)
        self.gamma = SliderField(0.1, 4.0, 1.0, 0.01, 2)
        self.gain = SliderField(0.0, 10.0, 1.0, 0.01, 2)
        self.offset = SliderField(-1.0, 1.0, 0.0, 0.001, 3)
        self.contrast = SliderField(0.2, 3.0, 1.0, 0.01, 2)
        self.saturation = SliderField(0.0, 3.0, 1.0, 0.01, 2)
        self.balance_red = SliderField(0.0, 3.0, 1.0, 0.01, 2)
        self.balance_green = SliderField(0.0, 3.0, 1.0, 0.01, 2)
        self.balance_blue = SliderField(0.0, 3.0, 1.0, 0.01, 2)
        grid.addWidget(QLabel("Exposure"), 0, 0)
        grid.addWidget(self.exposure, 0, 1)
        grid.addWidget(QLabel("Gamma"), 1, 0)
        grid.addWidget(self.gamma, 1, 1)
        grid.addWidget(QLabel("Gain"), 2, 0)
        grid.addWidget(self.gain, 2, 1)
        grid.addWidget(QLabel("Offset"), 3, 0)
        grid.addWidget(self.offset, 3, 1)
        grid.addWidget(QLabel("Contrast"), 4, 0)
        grid.addWidget(self.contrast, 4, 1)
        grid.addWidget(QLabel("Saturation"), 5, 0)
        grid.addWidget(self.saturation, 5, 1)
        balance = QLabel("Color balance")
        balance.setProperty("role", "section")
        grid.addWidget(balance, 6, 0, 1, 2)
        grid.addWidget(QLabel("Red"), 7, 0)
        grid.addWidget(self.balance_red, 7, 1)
        grid.addWidget(QLabel("Green"), 8, 0)
        grid.addWidget(self.balance_green, 8, 1)
        grid.addWidget(QLabel("Blue"), 9, 0)
        grid.addWidget(self.balance_blue, 9, 1)
        reset = QPushButton("Reset all")
        reset.clicked.connect(self.reset)
        grid.addWidget(reset, 10, 0, 1, 2)
        note = QLabel("View-only adjustments. Source files are never modified.")
        note.setWordWrap(True)
        note.setProperty("role", "muted")
        grid.addWidget(note, 11, 0, 1, 2)
        grid.setRowStretch(12, 1)
        for field in self._fields():
            field.valueChanged.connect(self._emit)

    def _fields(self) -> list[SliderField]:
        return [self.exposure, self.gamma, self.gain, self.offset, self.contrast, self.saturation,
                self.balance_red, self.balance_green, self.balance_blue]

    def grade(self) -> dict:
        return {"exposure": self.exposure.value(), "gamma": self.gamma.value(), "gain": self.gain.value(),
                "offset": self.offset.value(), "contrast": self.contrast.value(),
                "saturation": self.saturation.value(),
                "balance": (self.balance_red.value(), self.balance_green.value(), self.balance_blue.value())}

    def _emit(self, _value: float) -> None:
        self.gradeChanged.emit(self.grade())

    def reset(self) -> None:
        for field in self._fields():
            field.reset()

    def nudge_exposure(self, stops: float) -> None:
        self.exposure.set_value(self.exposure.value() + stops)
