import os

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QFileDialog, QFormLayout, QLabel, QMessageBox, QWidget

from ..color.ocio_pipeline import BUILTIN_CONFIG, BakedLut, ColorManagement
from ..errors import ColorConfigError
from ..media.frame import MediaSource

BUILTIN_CONFIGS = {
    "ACES CG config (built-in)": BUILTIN_CONFIG,
    "ACES Studio config (built-in)": "ocio://studio-config-latest",
}
LOAD_CONFIG_LABEL = "Load .ocio file..."


class OcioPanel(QWidget):
    lutChanged = Signal(object)

    def __init__(self, config_source: str | None, display: str | None, view: str | None) -> None:
        super().__init__()
        self.color: ColorManagement | None = None
        self._input_by_source: dict[int, str] = {}
        self._source: MediaSource | None = None
        self._is_updating = False
        form = QFormLayout(self)
        form.setContentsMargins(12, 10, 12, 10)
        self.config_box = QComboBox()
        self.config_box.setAccessibleName("OCIO config")
        self.input_box = QComboBox()
        self.input_box.setAccessibleName("Input colorspace")
        self.display_box = QComboBox()
        self.display_box.setAccessibleName("Display")
        self.view_box = QComboBox()
        self.view_box.setAccessibleName("View")
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setProperty("role", "muted")
        form.addRow("Config", self.config_box)
        form.addRow("Input", self.input_box)
        form.addRow("Display", self.display_box)
        form.addRow("View", self.view_box)
        form.addRow(self.status)
        self.config_box.addItems(list(BUILTIN_CONFIGS))
        if os.environ.get("OCIO"):
            self.config_box.addItem(f"$OCIO ({os.environ['OCIO']})", os.environ["OCIO"])
        self.config_box.addItem(LOAD_CONFIG_LABEL)
        self.config_box.activated.connect(self._config_chosen)
        self.input_box.currentTextChanged.connect(self._input_chosen)
        self.display_box.currentTextChanged.connect(self._display_chosen)
        self.view_box.currentTextChanged.connect(lambda _: self._rebake())
        self.load_config(config_source or BUILTIN_CONFIG, display, view)

    @property
    def config_source(self) -> str:
        return self.color.source if self.color else BUILTIN_CONFIG

    def load_config(self, source: str, display: str | None = None, view: str | None = None) -> bool:
        try:
            color = ColorManagement.load(source)
        except ColorConfigError as error:
            QMessageBox.warning(self, "OCIO", str(error))
            return False
        self.color = color
        self._input_by_source.clear()
        self._is_updating = True
        self.input_box.clear()
        self.input_box.addItems(color.colorspaces)
        self.display_box.clear()
        self.display_box.addItems(color.displays)
        self.display_box.setCurrentText(display if display in color.displays else color.default_display)
        self._fill_views(view)
        self._is_updating = False
        if self._source is not None:
            self.set_source(self._source)
        else:
            self._rebake()
        return True

    def _config_chosen(self, index: int) -> None:
        label = self.config_box.itemText(index)
        if label == LOAD_CONFIG_LABEL:
            path, _ = QFileDialog.getOpenFileName(self, "Load OCIO config", "", "OCIO config (*.ocio)")
            if path and self.load_config(path):
                self.config_box.insertItem(index, path, path)
                self.config_box.setCurrentIndex(index)
            return
        self.load_config(BUILTIN_CONFIGS.get(label) or self.config_box.itemData(index))

    def _fill_views(self, preferred: str | None = None) -> None:
        display = self.display_box.currentText()
        views = self.color.views(display) if display else []
        self.view_box.clear()
        self.view_box.addItems(views)
        if preferred in views:
            self.view_box.setCurrentText(preferred)
        elif views:
            self.view_box.setCurrentText(self.color.default_view(display))

    def _display_chosen(self, _display: str) -> None:
        if self._is_updating:
            return
        self._is_updating = True
        self._fill_views(self.view_box.currentText())
        self._is_updating = False
        self._rebake()

    def set_source(self, source: MediaSource) -> None:
        self._source = source
        declared = source.properties.get("oiio:ColorSpace", "")
        default = declared if declared in self.color.colorspaces else self.color.default_input(source.colorspace)
        self._is_updating = True
        self.input_box.setCurrentText(self._input_by_source.get(source.uid, default))
        self._is_updating = False
        self._rebake()

    def _input_chosen(self, space: str) -> None:
        if self._source is not None and space:
            self._input_by_source[self._source.uid] = space
        if not self._is_updating:
            self._rebake()

    def current_lut(self) -> BakedLut | None:
        if self.color is None or not self.view_box.currentText():
            return None
        return self.color.bake(self.input_box.currentText(), self.display_box.currentText(), self.view_box.currentText())

    def _rebake(self) -> None:
        if self._is_updating:
            return
        try:
            lut = self.current_lut()
        except ColorConfigError as error:
            self.status.setText(str(error))
            return
        self.status.setText(f"{self.color.name}" if self.color else "")
        self.lutChanged.emit(lut)
