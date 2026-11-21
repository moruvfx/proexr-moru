from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QListWidget, QListWidgetItem

from ..media.frame import MediaSource

KIND_LABELS = {"video": "VIDEO", "sequence": "SEQ", "image": "IMAGE"}


class MediaList(QListWidget):
    sourceSelected = Signal(object)
    removeRequested = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setDragDropMode(QListWidget.InternalMove)
        self.setWordWrap(True)
        self.setTextElideMode(Qt.ElideMiddle)
        self.currentItemChanged.connect(self._selection_changed)

    def add_source(self, source: MediaSource) -> None:
        frames = f"  {source.length} fr" if source.length > 1 else ""
        item = QListWidgetItem(f"{source.label}\n{KIND_LABELS[source.kind]}  {source.width}x{source.height}"
                               f"{frames}  {source.fps:g} fps")
        item.setToolTip(str(source.path))
        item.setData(Qt.UserRole, source)
        self.addItem(item)

    def sources(self) -> list[MediaSource]:
        return [self.item(row).data(Qt.UserRole) for row in range(self.count())]

    def select_source(self, source: MediaSource) -> None:
        self.setCurrentRow(self.sources().index(source))

    def remove_source(self, source: MediaSource) -> None:
        self.takeItem(self.sources().index(source))

    def _selection_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is not None:
            self.sourceSelected.emit(current.data(Qt.UserRole))

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.currentItem() is not None:
            self.removeRequested.emit(self.currentItem().data(Qt.UserRole))
            return
        super().keyPressEvent(event)
