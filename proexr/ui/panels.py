"""Side panels: colour adjustments, media info, playlist."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QPushButton, QSlider,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)


class SliderSpin(QWidget):
    """Slider + numeric field; double-click the slider to reset."""
    valueChanged = Signal(float)

    def __init__(self, lo, hi, default, step=0.01, decimals=2, parent=None):
        super().__init__(parent)
        self.default = default
        self._scale = 1.0 / step
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(int(lo * self._scale), int(hi * self._scale))
        self.spin = QDoubleSpinBox()
        self.spin.setRange(lo, hi)
        self.spin.setSingleStep(step * 10 if step < 0.1 else step)
        self.spin.setDecimals(decimals)
        self.spin.setFixedWidth(70)
        self.spin.setKeyboardTracking(False)
        lay.addWidget(self.slider, 1)
        lay.addWidget(self.spin)
        self.slider.valueChanged.connect(lambda v: self._set(v / self._scale, from_slider=True))
        self.spin.valueChanged.connect(lambda v: self._set(v))
        self.slider.mouseDoubleClickEvent = lambda e: self.reset()
        self._block = False
        self.setValue(default)

    def _set(self, v, from_slider=False):
        if self._block:
            return
        self._block = True
        if from_slider:
            self.spin.setValue(v)
        else:
            self.slider.setValue(int(round(v * self._scale)))
        self._block = False
        self.valueChanged.emit(self.value())

    def value(self):
        return self.spin.value()

    def setValue(self, v):
        self._block = True
        self.spin.setValue(v)
        self.slider.setValue(int(round(v * self._scale)))
        self._block = False
        self.valueChanged.emit(v)

    def reset(self):
        self.setValue(self.default)


class AdjustPanel(QWidget):
    changed = Signal(dict)

    SPECS = [
        ("exposure", "Exposure", -10, 10, 0.0, 0.01, 2),
        ("gamma", "Gamma", 0.1, 4.0, 1.0, 0.01, 2),
        ("gain", "Gain", 0.0, 10.0, 1.0, 0.01, 2),
        ("offset", "Offset", -1.0, 1.0, 0.0, 0.001, 3),
        ("contrast", "Contrast", 0.2, 3.0, 1.0, 0.01, 2),
        ("saturation", "Saturation", 0.0, 3.0, 1.0, 0.01, 2),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        grid = QGridLayout(self)
        grid.setContentsMargins(10, 8, 10, 8)
        grid.setVerticalSpacing(6)
        self.ctrls = {}
        row = 0
        for key, label, lo, hi, d, step, dec in self.SPECS:
            grid.addWidget(QLabel(label), row, 0)
            w = SliderSpin(lo, hi, d, step, dec)
            w.valueChanged.connect(self._emit)
            grid.addWidget(w, row, 1)
            self.ctrls[key] = w
            row += 1
        sec = QLabel("Color balance")
        sec.setObjectName("section")
        grid.addWidget(sec, row, 0, 1, 2)
        row += 1
        for i, ch in enumerate("RGB"):
            grid.addWidget(QLabel(ch), row, 0)
            w = SliderSpin(0.0, 3.0, 1.0, 0.01, 2)
            w.valueChanged.connect(self._emit)
            grid.addWidget(w, row, 1)
            self.ctrls["bal_" + ch] = w
            row += 1
        btn = QPushButton("Reset all")
        btn.clicked.connect(self.reset)
        grid.addWidget(btn, row, 0, 1, 2)
        grid.setRowStretch(row + 1, 1)
        note = QLabel("Adjustments are view-only. Source files are never modified.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#6f6f78; font-size:8pt;")
        grid.addWidget(note, row + 2, 0, 1, 2)

    def values(self):
        c = self.ctrls
        return dict(exposure=c["exposure"].value(), gamma=c["gamma"].value(),
                    gain=c["gain"].value(), offset=c["offset"].value(),
                    contrast=c["contrast"].value(), saturation=c["saturation"].value(),
                    balance=(c["bal_R"].value(), c["bal_G"].value(), c["bal_B"].value()))

    def _emit(self, *_):
        self.changed.emit(self.values())

    def reset(self):
        for w in self.ctrls.values():
            w.reset()

    def nudge_exposure(self, d):
        w = self.ctrls["exposure"]
        w.setValue(w.value() + d)


class InfoPanel(QTreeWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(2)
        self.setHeaderLabels(["Property", "Value"])
        self.setRootIsDecorated(False)
        self.setAlternatingRowColors(True)
        self.setColumnWidth(0, 120)

    def show_info(self, info: dict, extra: dict | None = None):
        self.clear()
        for k, v in list(info.items()) + list((extra or {}).items()):
            if k.startswith("_"):
                k = k[1:].capitalize()
            it = QTreeWidgetItem([k, str(v)])
            it.setToolTip(1, str(v))
            self.addTopLevelItem(it)


class Playlist(QListWidget):
    activated_source = Signal(object)
    remove_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragDropMode(QListWidget.InternalMove)
        self.currentItemChanged.connect(self._changed)

    def add(self, src):
        it = QListWidgetItem(src.name)
        kind = {"video": "VIDEO", "sequence": "SEQ", "image": "IMG"}.get(src.kind, "")
        res = f"{src.width}x{src.height}"
        frames = f"{src.length} fr" if src.length > 1 else ""
        it.setText(f"{src.name}\n{kind}  {res}  {frames}  {src.fps:g} fps")
        it.setToolTip(src.path)
        it.setData(Qt.UserRole, src)
        self.addItem(it)
        return it

    def sources(self):
        return [self.item(i).data(Qt.UserRole) for i in range(self.count())]

    def select(self, src):
        for i in range(self.count()):
            if self.item(i).data(Qt.UserRole) is src:
                self.setCurrentRow(i)
                return

    def _changed(self, cur, _prev):
        if cur is not None:
            self.activated_source.emit(cur.data(Qt.UserRole))

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.currentItem():
            self.remove_requested.emit(self.currentItem().data(Qt.UserRole))
            return
        super().keyPressEvent(e)
