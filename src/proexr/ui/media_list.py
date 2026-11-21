from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QContextMenuEvent, QKeyEvent
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QMenu

from ..media.frame import MediaSource

KIND_LABELS = {"video": "VIDEO", "sequence": "SEQ", "image": "IMAGE"}


class MediaList(QListWidget):
    sourceSelected = Signal(object)
    removeRequested = Signal(object)
    compareRequested = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setDragDropMode(QListWidget.InternalMove)
        self.setWordWrap(True)
        self.setTextElideMode(Qt.ElideMiddle)
        self.currentItemChanged.connect(self._selection_changed)

    def add_source(self, source: MediaSource) -> None:
        item = QListWidgetItem(self._describe(source, is_compare=False))
        item.setToolTip(str(source.path))
        item.setData(Qt.UserRole, source)
        self.addItem(item)

    @staticmethod
    def _describe(source: MediaSource, is_compare: bool) -> str:
        frames = f"  {source.length} fr" if source.length > 1 else ""
        marker = "[B]  " if is_compare else ""
        return (f"{marker}{source.label}\n{KIND_LABELS[source.kind]}  {source.width}x{source.height}"
                f"{frames}  {source.fps:g} fps")

    def mark_compare(self, compare: MediaSource | None) -> None:
        for row in range(self.count()):
            source = self.item(row).data(Qt.UserRole)
            self.item(row).setText(self._describe(source, source is compare))

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        item = self.itemAt(event.pos())
        menu = QMenu(self)
        if item is not None:
            source = item.data(Qt.UserRole)
            menu.addAction("Compare with this (set as B)", lambda: self.compareRequested.emit(source))
            menu.addAction("Remove from list", lambda: self.removeRequested.emit(source))
        menu.addAction("Clear compare", lambda: self.compareRequested.emit(None))
        menu.exec(event.globalPos())

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
