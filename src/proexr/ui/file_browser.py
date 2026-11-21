from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PySide6.QtCore import QDir, QModelIndex, QObject, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import QFileSystemModel, QLabel, QListWidget, QListWidgetItem, QSplitter, QTreeView, QVBoxLayout, QWidget

from ..errors import ProexrError
from ..media.image_source import ImageSequenceSource
from ..media.sequence import find_sequence, scan_folder
from ..media.thumbnail import thumbnail_pixels
from ..media.video_source import VideoSource
from . import palette
from .icons import make_icon

THUMBNAIL_SIZE = 150
THUMBNAIL_WORKERS = 2


def render_thumbnail(path: Path, is_video: bool) -> np.ndarray | None:
    """First frame of the media as a small sRGB image, or None if it cannot be read."""
    try:
        source = VideoSource(path, hardware_decode=False) if is_video else ImageSequenceSource(find_sequence(path))
        try:
            return thumbnail_pixels(source.read(source.first), THUMBNAIL_SIZE)
        finally:
            source.close()
    except (ProexrError, OSError, ValueError):
        return None


class ThumbnailRelay(QObject):
    ready = Signal(int, int, object)


class FileBrowser(QWidget):
    """Folder tree on top, media found in the selected folder below as a thumbnail grid."""

    openRequested = Signal(list)

    def __init__(self, start_folder: str = "") -> None:
        super().__init__()
        self._pool = ThreadPoolExecutor(THUMBNAIL_WORKERS, thread_name_prefix="thumbnail")
        self._generation = 0
        self._relay = ThumbnailRelay()
        self._relay.ready.connect(self._thumbnail_ready, Qt.QueuedConnection)

        self.model = QFileSystemModel(self)
        self.model.setFilter(QDir.AllDirs | QDir.NoDotAndDotDot | QDir.Drives)
        self.model.setRootPath("")
        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setHeaderHidden(True)
        for column in (1, 2, 3):
            self.tree.hideColumn(column)
        self.tree.setAccessibleName("Folders")
        self.tree.selectionModel().currentChanged.connect(self._folder_changed)

        self.grid = QListWidget()
        self.grid.setViewMode(QListWidget.IconMode)
        self.grid.setIconSize(QSize(THUMBNAIL_SIZE, THUMBNAIL_SIZE * 9 // 16))
        self.grid.setGridSize(QSize(THUMBNAIL_SIZE + 16, THUMBNAIL_SIZE * 9 // 16 + 44))
        self.grid.setResizeMode(QListWidget.Adjust)
        self.grid.setMovement(QListWidget.Static)
        self.grid.setWordWrap(True)
        self.grid.setTextElideMode(Qt.ElideMiddle)
        self.grid.setSelectionMode(QListWidget.ExtendedSelection)
        self.grid.setAccessibleName("Media in folder")
        self.grid.itemActivated.connect(lambda _item: self.open_selected())
        self.status = QLabel()
        self.status.setStyleSheet(f"color: {palette.TEXT_MUTED.name()};")

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.tree)
        splitter.addWidget(self.grid)
        splitter.setSizes([220, 420])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)
        layout.addWidget(self.status)
        if start_folder and Path(start_folder).is_dir():
            self.show_folder(start_folder)

    def show_folder(self, folder: str) -> None:
        index = self.model.index(str(Path(folder).resolve()))
        if index.isValid():
            self.tree.setCurrentIndex(index)
            self.tree.scrollTo(index)
        self._list_media(Path(folder))

    def _folder_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        if current.isValid():
            self._list_media(Path(self.model.filePath(current)))

    def _list_media(self, folder: Path) -> None:
        self._generation += 1
        self.grid.clear()
        try:
            sequences, videos = scan_folder(folder)
        except OSError as error:
            self.status.setText(str(error))
            return
        entries = [(s.path_for(s.first), s.label, False) for s in sequences] + [(v, v.name, True) for v in videos]
        placeholder = make_icon("image")
        for row, (path, label, is_video) in enumerate(entries):
            item = QListWidgetItem(placeholder, label)
            item.setToolTip(str(path))
            item.setData(Qt.UserRole, str(path))
            self.grid.addItem(item)
            self._pool.submit(self._load_thumbnail, self._generation, row, path, is_video)
        self.status.setText(f"{len(entries)} media in {folder.name or folder}")

    def _load_thumbnail(self, generation: int, row: int, path: Path, is_video: bool) -> None:
        if generation != self._generation:
            return
        pixels = render_thumbnail(path, is_video)
        if pixels is not None:
            self._relay.ready.emit(generation, row, pixels)

    def _thumbnail_ready(self, generation: int, row: int, pixels: np.ndarray) -> None:
        if generation != self._generation or row >= self.grid.count():
            return
        height, width = pixels.shape[:2]
        image = QImage(pixels.data, width, height, width * 3, QImage.Format_RGB888).copy()
        self.grid.item(row).setIcon(QIcon(QPixmap.fromImage(image)))

    def open_selected(self) -> None:
        paths = [item.data(Qt.UserRole) for item in self.grid.selectedItems()]
        if paths:
            self.openRequested.emit(paths)

    def shutdown(self) -> None:
        self._generation += 1
        self._pool.shutdown(wait=False, cancel_futures=True)
