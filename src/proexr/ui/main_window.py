import os
import sys
import time
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QDesktopServices,
    QDragEnterEvent,
    QDropEvent,
    QKeySequence,
)
from PySide6.QtWidgets import (
    QComboBox,
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..errors import ProexrError
from ..media.frame import MediaSource
from ..media.opener import open_media
from ..playback.clock import PlaybackClock
from ..playback.frame_cache import CacheKey, FrameCache
from . import palette, shortcuts
from .color_panel import ColorPanel
from .info_panel import InfoPanel
from .media_list import MediaList
from .timeline import Timeline
from .transport_bar import SPEEDS, TransportBar
from .viewer import Channel, Viewer, ViewTransform

CACHE_SIZES_GB = (1, 2, 4, 8, 12, 16, 24, 32, 48, 64)
DEFAULT_CACHE_SHARE = 0.3
MAX_DEFAULT_CACHE_GB = 16
STATUS_INTERVAL_MS = 250
EXPOSURE_NUDGE = 0.5
EMPTY_HINT = "Drop images, EXR sequences, videos or folders here\n\nCtrl+O open file    Ctrl+Shift+O open folder"
FILE_FILTER = ("Media (*.exr *.sxr *.png *.jpg *.jpeg *.tif *.tiff *.tga *.dpx *.cin *.hdr *.bmp *.psd *.webp "
               "*.jp2 *.jxl *.mp4 *.mov *.avi *.mkv *.mxf *.webm *.m4v *.mpg *.ts);;All files (*)")
CHANNEL_NAMES = ("RGB", "Red", "Green", "Blue", "Alpha", "Luminance")
VIEW_NAMES = ("Raw", "sRGB", "Rec.709", "ACES filmic")


def total_memory_bytes() -> int:
    if sys.platform == "win32":
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                        ("total_physical", ctypes.c_ulonglong), ("available_physical", ctypes.c_ulonglong),
                        ("total_page", ctypes.c_ulonglong), ("available_page", ctypes.c_ulonglong),
                        ("total_virtual", ctypes.c_ulonglong), ("available_virtual", ctypes.c_ulonglong),
                        ("available_extended", ctypes.c_ulonglong)]
        status = MemoryStatus()
        status.length = ctypes.sizeof(MemoryStatus)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        return int(status.total_physical)
    return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")


class FrameReadyRelay(QObject):
    ready = Signal(object)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("ProEXR Viewer")
        self.resize(1500, 920)
        self.settings = QSettings("PROEXR_MORU", "ProEXRViewer")
        self.hardware_decode = self.settings.value("hardware_decode", True, type=bool)
        default_gb = max(1, min(MAX_DEFAULT_CACHE_GB, int(total_memory_bytes() * DEFAULT_CACHE_SHARE) >> 30))
        self.cache_gb = self.settings.value("cache_gb", default_gb, type=int)
        self.cache = FrameCache(self.cache_gb << 30)
        self._relay = FrameReadyRelay()
        self._relay.ready.connect(self._frame_ready, Qt.QueuedConnection)
        self.cache.on_frame_ready = self._relay.ready.emit
        self.source: MediaSource | None = None
        self.layer = 0
        self.clock = PlaybackClock(0, 0, 24.0, is_ready=self._is_cached)
        self._shown_at: list[float] = []
        self._docks_before_hide: list[QDockWidget] = []
        self._play_timer = QTimer(self)
        self._play_timer.setTimerType(Qt.PreciseTimer)
        self._play_timer.timeout.connect(self._advance)

        self.viewer = Viewer()
        self.viewer.hint = EMPTY_HINT
        self.viewer.view_transform = ViewTransform(self.settings.value("view_transform", 1, type=int))
        self.viewer.filesDropped.connect(self.open_paths)
        self.viewer.pixelHovered.connect(self._show_pixel)
        self.viewer.zoomChanged.connect(lambda zoom: self.zoom_label.setText(f"{zoom * 100:.0f}%"))
        self.timeline = Timeline()
        self.timeline.scrubStarted.connect(self.stop)
        self.timeline.scrubbed.connect(self.seek)
        self.transport = TransportBar()
        self._build_view_bar()
        self._build_center()
        self._build_docks()
        self._build_status_bar()
        self._connect_transport()
        self._build_menus()
        self.setAcceptDrops(True)

        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._refresh_status)
        self._status_timer.start(STATUS_INTERVAL_MS)
        if self.settings.value("geometry") is not None:
            self.restoreGeometry(self.settings.value("geometry"))
        if self.settings.value("window_state") is not None:
            self.restoreState(self.settings.value("window_state"))

    def _build_view_bar(self) -> None:
        bar = self.view_bar = self.addToolBar("View")
        bar.setObjectName("view_bar")
        bar.setMovable(False)
        self.layer_box = QComboBox()
        self.layer_box.setMinimumWidth(170)
        self.layer_box.setAccessibleName("EXR layer")
        self.layer_box.currentIndexChanged.connect(self.set_layer)
        self.channel_box = QComboBox()
        self.channel_box.addItems(CHANNEL_NAMES)
        self.channel_box.setAccessibleName("Channel")
        self.channel_box.currentIndexChanged.connect(self._set_channel)
        self.view_box = QComboBox()
        self.view_box.addItems(VIEW_NAMES)
        self.view_box.setCurrentIndex(int(self.viewer.view_transform))
        self.view_box.setAccessibleName("View transform")
        self.view_box.currentIndexChanged.connect(self._set_view_transform)
        self.exposure_field = QDoubleSpinBox()
        self.exposure_field.setRange(-10, 10)
        self.exposure_field.setSingleStep(EXPOSURE_NUDGE)
        self.exposure_field.setAccessibleName("Exposure")
        self.gamma_field = QDoubleSpinBox()
        self.gamma_field.setRange(0.1, 4)
        self.gamma_field.setSingleStep(0.1)
        self.gamma_field.setValue(1.0)
        self.gamma_field.setAccessibleName("Gamma")
        for caption, widget in (("Layer", self.layer_box), ("Channel", self.channel_box),
                                ("View", self.view_box), ("Exposure", self.exposure_field),
                                ("Gamma", self.gamma_field)):
            label = QLabel(caption)
            label.setProperty("role", "muted")
            bar.addWidget(label)
            bar.addWidget(widget)

    def _build_center(self) -> None:
        center = QWidget()
        column = QVBoxLayout(center)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self.viewer, 1)
        column.addWidget(self.timeline)
        column.addWidget(self.transport)
        self.setCentralWidget(center)

    def _add_dock(self, title: str, widget: QWidget, area: Qt.DockWidgetArea, name: str) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setObjectName(name)
        dock.setWidget(widget)
        self.addDockWidget(area, dock)
        return dock

    def _build_docks(self) -> None:
        self.media_list = MediaList()
        self.media_list.sourceSelected.connect(self.set_source)
        self.media_list.removeRequested.connect(self.close_source)
        self.color_panel = ColorPanel()
        self.color_panel.gradeChanged.connect(self._apply_grade)
        self.info_panel = InfoPanel()
        self.media_dock = self._add_dock("Media", self.media_list, Qt.LeftDockWidgetArea, "media_dock")
        self.color_dock = self._add_dock("Color", self.color_panel, Qt.RightDockWidgetArea, "color_dock")
        self.info_dock = self._add_dock("Info", self.info_panel, Qt.RightDockWidgetArea, "info_dock")
        self.resizeDocks([self.media_dock, self.color_dock], [250, 320], Qt.Horizontal)
        self.exposure_field.valueChanged.connect(self.color_panel.exposure.set_value)
        self.gamma_field.valueChanged.connect(self.color_panel.gamma.set_value)

    def _build_status_bar(self) -> None:
        self.pixel_label = QLabel()
        self.pixel_label.setStyleSheet(f"font-family: {palette.MONO_FAMILY};")
        self.fps_label = QLabel()
        self.cache_label = QLabel()
        self.zoom_label = QLabel("100%")
        self.gpu_label = QLabel()
        status = self.statusBar()
        status.addWidget(self.pixel_label, 1)
        status.addPermanentWidget(self.fps_label)
        status.addPermanentWidget(self.cache_label)
        status.addPermanentWidget(self.zoom_label)
        status.addPermanentWidget(self.gpu_label)

    def _connect_transport(self) -> None:
        t = self.transport
        t.to_start.clicked.connect(lambda: self.seek(self.clock.in_point))
        t.step_back.clicked.connect(lambda: self.step(-1))
        t.play_reverse.clicked.connect(lambda: self.play(-1))
        t.stop.clicked.connect(self.stop)
        t.play_forward.clicked.connect(lambda: self.play(1))
        t.step_forward.clicked.connect(lambda: self.step(1))
        t.to_end.clicked.connect(lambda: self.seek(self.clock.out_point))
        t.frame_field.valueChanged.connect(self.seek)
        t.loop_box.currentIndexChanged.connect(lambda _: setattr(self.clock, "loop_mode", t.loop_mode()))
        t.fps_box.currentTextChanged.connect(self._set_fps)
        t.speed_box.currentIndexChanged.connect(self._set_speed)
        t.realtime.toggled.connect(lambda on: setattr(self.clock, "realtime", on))

    def _action(self, action_id: str, slot, checkable: bool = False) -> QAction:
        action = QAction(shortcuts.DEFAULT_SHORTCUTS[action_id][1], self)
        action.setShortcuts([QKeySequence(k) for k in self._keys[action_id]])
        action.setCheckable(checkable)
        (action.toggled if checkable else action.triggered).connect(slot)
        self.addAction(action)
        return action

    def _build_menus(self) -> None:
        self._keys = shortcuts.load()
        bar = self.menuBar()
        file_menu = bar.addMenu("&File")
        file_menu.addAction(self._action("open_file", self.open_file_dialog))
        file_menu.addAction(self._action("open_folder", self.open_folder_dialog))
        file_menu.addAction(self._action("close_media", lambda: self.source and self.close_source(self.source)))
        file_menu.addSeparator()
        file_menu.addAction(self._action("quit", self.close))

        play_menu = bar.addMenu("&Playback")
        play_menu.addAction(self._action("toggle_play", self.toggle_play))
        play_menu.addAction(self._action("play_forward", lambda: self.play(1)))
        play_menu.addAction(self._action("play_reverse", lambda: self.play(-1)))
        play_menu.addAction(self._action("stop", self.stop))
        play_menu.addSeparator()
        play_menu.addAction(self._action("next_frame", lambda: self.step(1)))
        play_menu.addAction(self._action("previous_frame", lambda: self.step(-1)))
        play_menu.addAction(self._action("forward_ten", lambda: self.step(10)))
        play_menu.addAction(self._action("back_ten", lambda: self.step(-10)))
        play_menu.addAction(self._action("go_to_start", lambda: self.seek(self.clock.in_point)))
        play_menu.addAction(self._action("go_to_end", lambda: self.seek(self.clock.out_point)))
        play_menu.addSeparator()
        play_menu.addAction(self._action("set_in", lambda: self._set_in_out(self.clock.current, self.clock.out_point)))
        play_menu.addAction(self._action("set_out", lambda: self._set_in_out(self.clock.in_point, self.clock.current)))
        play_menu.addAction(self._action("clear_in_out", lambda: self._set_in_out(self.clock.first, self.clock.last)))
        play_menu.addAction(self._action("cycle_loop", lambda: self._cycle(self.transport.loop_box, 1)))
        play_menu.addAction(self._action("faster", lambda: self._cycle(self.transport.speed_box, 1, wrap=False)))
        play_menu.addAction(self._action("slower", lambda: self._cycle(self.transport.speed_box, -1, wrap=False)))
        play_menu.addSeparator()
        play_menu.addAction(self._action("next_media", lambda: self._cycle_media(1)))
        play_menu.addAction(self._action("previous_media", lambda: self._cycle_media(-1)))

        view_menu = bar.addMenu("&View")
        view_menu.addAction(self._action("fit", self.viewer.fit))
        view_menu.addAction(self._action("actual_pixels", self.viewer.show_actual_pixels))
        view_menu.addAction(self._action("zoom_in", lambda: self.viewer.set_zoom(self.viewer.zoom * 1.25)))
        view_menu.addAction(self._action("zoom_out", lambda: self.viewer.set_zoom(self.viewer.zoom / 1.25)))
        view_menu.addSeparator()
        view_menu.addAction(self._action("fullscreen", self.toggle_fullscreen))
        view_menu.addAction(self._action("hide_panels", self.toggle_panels))
        view_menu.addSeparator()
        view_menu.addAction(self._action("safe_areas", lambda on: self._set_overlay("safe_areas", on), True))
        view_menu.addAction(self._action("thirds", lambda on: self._set_overlay("thirds", on), True))
        center = QAction("Center cross", self, checkable=True)
        center.toggled.connect(lambda on: self._set_overlay("center", on))
        view_menu.addAction(center)
        view_menu.addAction(self._action("clipping", self._set_clipping, True))
        nearest = QAction("Sharp pixels when zoomed in", self, checkable=True, checked=True)
        nearest.toggled.connect(self._set_nearest)
        view_menu.addAction(nearest)
        timecode = QAction("Timecode on timeline", self, checkable=True)
        timecode.toggled.connect(self._set_timecode)
        view_menu.addAction(timecode)
        panels = view_menu.addMenu("Panels")
        panels.addAction(self.media_dock.toggleViewAction())
        panels.addAction(self.color_dock.toggleViewAction())
        panels.addAction(self.info_dock.toggleViewAction())
        reset_layout = QAction("Reset layout", self)
        reset_layout.triggered.connect(self._reset_layout)
        panels.addAction(reset_layout)

        color_menu = bar.addMenu("&Color")
        color_menu.addAction(self._action("channel_rgb", lambda: self.channel_box.setCurrentIndex(Channel.RGB)))
        color_menu.addAction(self._action("channel_red", lambda: self.channel_box.setCurrentIndex(Channel.RED)))
        color_menu.addAction(self._action("channel_green", lambda: self.channel_box.setCurrentIndex(Channel.GREEN)))
        color_menu.addAction(self._action("channel_blue", lambda: self.channel_box.setCurrentIndex(Channel.BLUE)))
        color_menu.addAction(self._action("channel_alpha", lambda: self.channel_box.setCurrentIndex(Channel.ALPHA)))
        color_menu.addAction(self._action("channel_luminance",
                                          lambda: self.channel_box.setCurrentIndex(Channel.LUMINANCE)))
        color_menu.addSeparator()
        color_menu.addAction(self._action("next_layer", lambda: self._cycle(self.layer_box, 1)))
        color_menu.addAction(self._action("previous_layer", lambda: self._cycle(self.layer_box, -1)))
        color_menu.addSeparator()
        color_menu.addAction(self._action("exposure_up", lambda: self.color_panel.nudge_exposure(EXPOSURE_NUDGE)))
        color_menu.addAction(self._action("exposure_down", lambda: self.color_panel.nudge_exposure(-EXPOSURE_NUDGE)))
        color_menu.addAction(self._action("reset_grade", self.color_panel.reset))

        settings_menu = bar.addMenu("&Settings")
        cache_menu = settings_menu.addMenu("Frame cache size")
        group = QActionGroup(self)
        for size in CACHE_SIZES_GB:
            option = QAction(f"{size} GB", self, checkable=True, checked=size == self.cache_gb)
            option.triggered.connect(lambda _=False, size=size: self._set_cache_size(size))
            group.addAction(option)
            cache_menu.addAction(option)
        hardware = QAction("Hardware video decoding (NVIDIA NVDEC / D3D11)", self, checkable=True,
                           checked=self.hardware_decode)
        hardware.toggled.connect(self._set_hardware_decode)
        settings_menu.addAction(hardware)

        help_menu = bar.addMenu("&Help")
        keys = QAction("Keyboard shortcuts", self)
        keys.triggered.connect(self._show_shortcuts)
        help_menu.addAction(keys)
        edit_keys = QAction("Edit shortcuts file...", self)
        edit_keys.triggered.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(shortcuts.shortcuts_path()))))
        help_menu.addAction(edit_keys)
        about = QAction("About", self)
        about.triggered.connect(self._show_about)
        help_menu.addAction(about)

    def open_file_dialog(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Open media", self.settings.value("last_folder", ""), FILE_FILTER)
        if paths:
            self.open_paths(paths)

    def open_folder_dialog(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Open folder", self.settings.value("last_folder", ""))
        if folder:
            self.open_paths([folder])

    def open_paths(self, paths: list[str]) -> None:
        known = {str(s.path) for s in self.media_list.sources()}
        added: list[MediaSource] = []
        failures: list[str] = []
        for raw in paths:
            path = Path(raw)
            try:
                sources = open_media(path, self.hardware_decode)
            except ProexrError as error:
                failures.append(f"{path.name}: {error}")
                continue
            for source in sources:
                if str(source.path) not in known:
                    known.add(str(source.path))
                    self.media_list.add_source(source)
                    added.append(source)
            self.settings.setValue("last_folder", str(path if path.is_dir() else path.parent))
        if added:
            self.media_list.select_source(added[0])
        if failures:
            QMessageBox.warning(self, "Could not open", "\n".join(failures[:20]))

    def set_source(self, source: MediaSource) -> None:
        if source is self.source:
            return
        self.stop()
        self.source, self.layer = source, 0
        self.viewer.hint = ""
        self.viewer.pixel_aspect = source.pixel_aspect
        self.viewer.is_fit = True
        self.layer_box.blockSignals(True)
        self.layer_box.clear()
        self.layer_box.addItems([layer.label for layer in source.layers])
        self.layer_box.setEnabled(len(source.layers) > 1)
        self.layer_box.blockSignals(False)
        self.clock.set_range(source.first, source.last)
        self.clock.fps = source.fps
        self.clock.current = source.first
        self.transport.fps_box.blockSignals(True)
        self.transport.fps_box.setCurrentText(f"{source.fps:.3f}".rstrip("0").rstrip("."))
        self.transport.fps_box.blockSignals(False)
        self.timeline.set_range(source.first, source.last, source.fps, source.missing_frames)
        self.info_panel.show_properties(source.properties)
        self.setWindowTitle(f"{source.label} - ProEXR Viewer")
        self._sync_range()
        self._show(source.first, wait=True)

    def close_source(self, source: MediaSource) -> None:
        row = self.media_list.sources().index(source)
        self.media_list.remove_source(source)
        self.cache.forget(source)
        source.close()
        if source is not self.source:
            return
        self.source = None
        self.stop()
        if self.media_list.count():
            self.media_list.setCurrentRow(min(row, self.media_list.count() - 1))
            return
        self.viewer.show_frame(None)
        self.viewer.hint = EMPTY_HINT
        self.info_panel.clear()
        self.layer_box.clear()

    def _is_cached(self, number: int) -> bool:
        return self.source is not None and self.cache.get(self.source, number, self.layer) is not None

    def _follow(self) -> None:
        if self.source is not None:
            self.cache.follow(self.source, self.layer, self.clock.current, self.clock.direction or 1,
                              (self.clock.in_point, self.clock.out_point))

    def _show(self, number: int, wait: bool = False) -> None:
        if self.source is None:
            return
        self.clock.current = number
        self._follow()
        frame = self.cache.get(self.source, number, self.layer)
        if frame is None and wait:
            frame = self.cache.read_now(self.source, number, self.layer)
        if frame is not None:
            self.viewer.show_frame(frame)
        elif self.cache.error_for(self.source, number, self.layer):
            self.viewer.hint = f"Cannot read frame {number}:\n{self.cache.error_for(self.source, number, self.layer)}"
            self.viewer.update()
        self.timeline.set_current(number)
        self.transport.frame_field.blockSignals(True)
        self.transport.frame_field.setValue(number)
        self.transport.frame_field.blockSignals(False)

    def _frame_ready(self, key: CacheKey) -> None:
        if self.source is None or self.clock.is_playing:
            return
        if key == (self.source.uid, self.layer, self.clock.current) and \
                (self.viewer.frame is None or self.viewer.frame.number != key[2] or
                 self.viewer.frame.pixels.shape[2] != len(self.source.layers[self.layer].channel_indices)):
            self.viewer.show_frame(self.cache.get(self.source, key[2], self.layer))

    def seek(self, number: int) -> None:
        if self.source is None:
            return
        self.clock.seek(number)
        self.clock.restart_timing(time.perf_counter())
        self._show(self.clock.current)

    def step(self, frames: int) -> None:
        self.stop()
        target = self.clock.current + frames
        if target > self.clock.out_point:
            target = self.clock.in_point
        elif target < self.clock.in_point:
            target = self.clock.out_point
        self.seek(target)

    def play(self, direction: int) -> None:
        if self.source is None:
            return
        if self.clock.direction == direction:
            self.stop()
            return
        self.clock.start(direction, time.perf_counter())
        self._shown_at.clear()
        self._follow()
        self._play_timer.start(max(1, int(1000 / self.clock.rate / 4)))
        self.transport.show_direction(direction)

    def stop(self) -> None:
        self.clock.stop()
        self._play_timer.stop()
        self.transport.show_direction(0)
        self._follow()

    def toggle_play(self) -> None:
        if self.clock.is_playing:
            self.stop()
        else:
            self.play(1)

    def _advance(self) -> None:
        number = self.clock.tick(time.perf_counter())
        if number is not None:
            self._shown_at.append(time.perf_counter())
            del self._shown_at[:-60]
            self._show(number)
        elif not self.clock.is_playing:
            self.stop()

    def _set_in_out(self, in_point: int, out_point: int) -> None:
        self.clock.set_in_out(in_point, out_point)
        self._sync_range()

    def _sync_range(self) -> None:
        self.timeline.in_point, self.timeline.out_point = self.clock.in_point, self.clock.out_point
        self.timeline.update()
        self.transport.show_range(self.clock.in_point, self.clock.out_point)
        self._follow()

    def _set_fps(self, text: str) -> None:
        try:
            fps = float(text)
        except ValueError:
            return
        if fps > 0:
            self.clock.fps = fps
            self.timeline.fps = fps
            self._retime()

    def _set_speed(self, index: int) -> None:
        self.clock.speed = SPEEDS[index]
        self._retime()

    def _retime(self) -> None:
        self.clock.restart_timing(time.perf_counter())
        if self.clock.is_playing:
            self._play_timer.setInterval(max(1, int(1000 / self.clock.rate / 4)))

    def set_layer(self, index: int) -> None:
        if index < 0 or self.source is None:
            return
        self.layer = index
        self._show(self.clock.current, wait=not self.clock.is_playing)

    def _set_channel(self, index: int) -> None:
        self.viewer.channel = Channel(index)
        self.viewer.update()

    def _set_view_transform(self, index: int) -> None:
        self.viewer.view_transform = ViewTransform(index)
        self.settings.setValue("view_transform", index)
        self.viewer.update()

    def _apply_grade(self, grade: dict) -> None:
        self.viewer.set_grade(**grade)
        for field, key in ((self.exposure_field, "exposure"), (self.gamma_field, "gamma")):
            field.blockSignals(True)
            field.setValue(grade[key])
            field.blockSignals(False)

    def _set_overlay(self, name: str, enabled: bool) -> None:
        self.viewer.overlays[name] = enabled
        self.viewer.update()

    def _set_clipping(self, enabled: bool) -> None:
        self.viewer.show_clipping = enabled
        self.viewer.update()

    def _set_nearest(self, enabled: bool) -> None:
        self.viewer.nearest_when_magnified = enabled
        self.viewer.update()

    def _set_timecode(self, enabled: bool) -> None:
        self.timeline.shows_timecode = enabled
        self.timeline.update()

    def _cycle(self, box: QComboBox, step: int, wrap: bool = True) -> None:
        count = box.count()
        if count < 2:
            return
        index = box.currentIndex() + step
        box.setCurrentIndex(index % count if wrap else max(0, min(count - 1, index)))

    def _cycle_media(self, step: int) -> None:
        if self.media_list.count():
            self.media_list.setCurrentRow((self.media_list.currentRow() + step) % self.media_list.count())

    def _show_pixel(self, pixel: dict | None) -> None:
        if not pixel:
            self.pixel_label.setText("")
            return
        values = pixel["values"]
        names = "RGBA" if len(values) > 1 else "V"
        text = "  ".join(f"{names[i]} {values[i]:.4f}" for i in range(len(values)))
        if pixel["is_integer"]:
            text += "   (" + " ".join(str(int(v)) for v in pixel["raw"]) + ")"
        self.pixel_label.setText(f"x {pixel['x']:>5}  y {pixel['y']:>5}    {text}")

    def _refresh_status(self) -> None:
        if self.source is not None:
            self.timeline.set_cached(self.cache.cached_numbers(self.source, self.layer))
        self.cache_label.setText(f"Cache {self.cache.used_bytes / (1 << 30):.1f} / {self.cache_gb} GB")
        if self.clock.is_playing and len(self._shown_at) > 1:
            span = self._shown_at[-1] - self._shown_at[0]
            measured = (len(self._shown_at) - 1) / span if span > 0 else 0.0
            self.fps_label.setText(f"{measured:5.1f} / {self.clock.rate:g} fps")
        else:
            self.fps_label.setText("")
        if self.viewer.gl_renderer and not self.gpu_label.text():
            self.gpu_label.setText(self.viewer.gl_renderer[:48])

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def toggle_panels(self) -> None:
        docks = (self.media_dock, self.color_dock, self.info_dock)
        hiding = self.view_bar.isVisible()
        if hiding:
            self._docks_before_hide = [d for d in docks if d.isVisible()]
        for dock in docks if hiding else self._docks_before_hide:
            dock.setVisible(not hiding)
        for widget in (self.menuBar(), self.statusBar(), self.view_bar):
            widget.setVisible(not hiding)

    def _reset_layout(self) -> None:
        self.addDockWidget(Qt.LeftDockWidgetArea, self.media_dock)
        self.addDockWidget(Qt.RightDockWidgetArea, self.color_dock)
        self.addDockWidget(Qt.RightDockWidgetArea, self.info_dock)
        for dock in (self.media_dock, self.color_dock, self.info_dock):
            dock.setFloating(False)
            dock.show()

    def _set_cache_size(self, size_gb: int) -> None:
        self.cache_gb = size_gb
        self.settings.setValue("cache_gb", size_gb)
        self.cache.set_budget(size_gb << 30)

    def _set_hardware_decode(self, enabled: bool) -> None:
        self.hardware_decode = enabled
        self.settings.setValue("hardware_decode", enabled)

    def _show_shortcuts(self) -> None:
        rows = "".join(f"<tr><td style='padding-right:18px'><b>{', '.join(self._keys[a])}</b></td><td>{d[1]}</td></tr>"
                       for a, d in shortcuts.DEFAULT_SHORTCUTS.items())
        QMessageBox.information(self, "Keyboard shortcuts",
                                f"<table>{rows}</table><p>Change them in Help &gt; Edit shortcuts file, then restart.</p>")

    def _show_about(self) -> None:
        QMessageBox.about(self, "ProEXR Viewer", f"<b>ProEXR Viewer</b> {__version__}<br>Read-only VFX media viewer."
                          f"<br><br>GPU: {self.viewer.gl_renderer}")

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.open_paths(paths)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("window_state", self.saveState())
        self.stop()
        self.cache.shutdown()
        for source in self.media_list.sources():
            source.close()
        super().closeEvent(event)
