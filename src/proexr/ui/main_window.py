import subprocess
import sys
import threading
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

from .. import __version__, update
from ..analysis.scopes import pixel_report
from ..errors import MediaReadError, PlaylistError, ProexrError, UpdateError
from ..media.audio import AudioTrack, has_audio
from ..media.frame import MediaSource
from ..media.opener import open_media
from ..media.playlist import PLAYLIST_SUFFIX, load_playlist, save_playlist
from ..playback.audio_player import AudioPlayer
from ..playback.clock import PlaybackClock
from ..playback.frame_cache import CacheKey, FrameCache
from ..playback.memory import available_memory_bytes, safe_cache_budget, total_memory_bytes
from . import palette, shortcuts
from .color_panel import ColorPanel
from .file_browser import FileBrowser
from .info_panel import InfoPanel
from .media_list import MediaList
from .ocio_panel import OcioPanel
from .pixel_inspector import PixelInspector
from .scopes_panel import ScopesPanel
from .timeline import Timeline
from .transport_bar import SPEEDS, TransportBar
from .viewer import Channel, CompareMode, Viewer, ViewTransform

CACHE_SIZES_GB = (1, 2, 4, 8, 12, 16, 24, 32, 48, 64)
DEFAULT_CACHE_SHARE = 0.3
MAX_DEFAULT_CACHE_GB = 16
STATUS_INTERVAL_MS = 250
MEMORY_CHECK_INTERVAL_MS = 2000
UPDATE_CHECK_DELAY_MS = 4000
UPDATE_CHECK_EVERY_SECONDS = 24 * 3600
LAYOUT_VERSION = 2  # bump whenever docks are added or removed so stale saved layouts are ignored
SCOPE_INTERVAL_MS = 120
SCOPE_SAMPLE_WIDTH = 384
EXPOSURE_NUDGE = 0.5
EMPTY_HINT = "Drop images, EXR sequences, videos or folders here\n\nCtrl+O open file    Ctrl+Shift+O open folder"
FILE_FILTER = ("Media (*.exr *.sxr *.png *.jpg *.jpeg *.tif *.tiff *.tga *.dpx *.cin *.hdr *.bmp *.psd *.webp "
               "*.jp2 *.jxl *.mp4 *.mov *.avi *.mkv *.mxf *.webm *.m4v *.mpg *.ts);;All files (*)")
CHANNEL_NAMES = ("RGB", "Red", "Green", "Blue", "Alpha", "Luminance")
COMPARE_NAMES = ("Off", "B only", "Wipe", "Side by side", "Difference")
COMPARE_CACHE_SHARE = 0.4
ASPECT_GUIDES = (("Off", 0.0), ("2.39:1 scope", 2.39), ("1.85:1 flat", 1.85), ("16:9", 16 / 9),
                 ("4:3", 4 / 3), ("1:1", 1.0))
VIEW_NAMES = ("Raw", "sRGB", "Rec.709", "ACES filmic (approx)", "OCIO")


class FrameReadyRelay(QObject):
    ready = Signal(object)


class UpdateRelay(QObject):
    checked = Signal(object, bool)  # Release or error message, whether the user asked
    downloaded = Signal(object)  # installer Path or error message


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
        self.compare_cache = FrameCache(int((self.cache_gb << 30) * COMPARE_CACHE_SHARE))
        self.compare_source: MediaSource | None = None
        self._relay = FrameReadyRelay()
        self._relay.ready.connect(self._frame_ready, Qt.QueuedConnection)
        self.cache.on_frame_ready = self._relay.ready.emit
        self.compare_cache.on_frame_ready = self._relay.ready.emit
        self.source: MediaSource | None = None
        self.layer = 0
        self.audio_player = AudioPlayer()
        self.audio_enabled = not self.settings.value("muted", False, type=bool)
        self._audio_tracks: dict[int, AudioTrack | None] = {}
        self._last_shown: int | None = None
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
        self._memory_timer = QTimer(self)
        self._memory_timer.timeout.connect(self._adapt_cache_to_memory)
        self._memory_timer.start(MEMORY_CHECK_INTERVAL_MS)
        self._update_relay = UpdateRelay()
        self._update_relay.checked.connect(self._update_checked, Qt.QueuedConnection)
        self._update_relay.downloaded.connect(self._update_downloaded, Qt.QueuedConnection)
        if self.settings.value("auto_update", True, type=bool):
            QTimer.singleShot(UPDATE_CHECK_DELAY_MS, lambda: self.check_for_updates(user_asked=False))
        if self.settings.value("geometry") is not None:
            self.restoreGeometry(self.settings.value("geometry"))
        if self.settings.value("window_state") is not None:
            self.restoreState(self.settings.value("window_state"), LAYOUT_VERSION)

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
        self.compare_box = QComboBox()
        self.compare_box.addItems(COMPARE_NAMES)
        self.compare_box.setAccessibleName("Compare mode")
        self.compare_box.currentIndexChanged.connect(self._set_compare_mode)
        for caption, widget in (("Layer", self.layer_box), ("Channel", self.channel_box),
                                ("View", self.view_box), ("Exposure", self.exposure_field),
                                ("Gamma", self.gamma_field), ("Compare", self.compare_box)):
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
        self.media_list.compareRequested.connect(self.set_compare_source)
        self.color_panel = ColorPanel()
        self.color_panel.gradeChanged.connect(self._apply_grade)
        self.info_panel = InfoPanel()
        self.ocio_panel = OcioPanel(self.settings.value("ocio_config"), self.settings.value("ocio_display"),
                                    self.settings.value("ocio_view"))
        self.ocio_panel.lutChanged.connect(self._apply_display_lut)
        self.viewer.set_display_lut(self.ocio_panel.current_lut())
        self.scopes_panel = ScopesPanel()
        self.viewer.displaySampled.connect(self.scopes_panel.show_sample)
        self.pixel_inspector = PixelInspector()
        self.file_browser = FileBrowser(self.settings.value("last_folder", ""))
        self.file_browser.openRequested.connect(self.open_paths)
        self.media_dock = self._add_dock("Media", self.media_list, Qt.LeftDockWidgetArea, "media_dock")
        self.browser_dock = self._add_dock("Browser", self.file_browser, Qt.LeftDockWidgetArea, "browser_dock")
        self.tabifyDockWidget(self.media_dock, self.browser_dock)
        self.media_dock.raise_()
        self.color_dock = self._add_dock("Color", self.color_panel, Qt.RightDockWidgetArea, "color_dock")
        self.ocio_dock = self._add_dock("Color management", self.ocio_panel, Qt.RightDockWidgetArea, "ocio_dock")
        self.info_dock = self._add_dock("Info", self.info_panel, Qt.RightDockWidgetArea, "info_dock")
        self.tabifyDockWidget(self.color_dock, self.ocio_dock)
        self.color_dock.raise_()
        self.scopes_dock = self._add_dock("Scopes", self.scopes_panel, Qt.BottomDockWidgetArea, "scopes_dock")
        self.inspector_dock = self._add_dock("Pixel", self.pixel_inspector, Qt.RightDockWidgetArea, "inspector_dock")
        self.tabifyDockWidget(self.info_dock, self.inspector_dock)
        self.info_dock.raise_()
        self.scopes_dock.hide()
        self._scope_timer = QTimer(self)
        self._scope_timer.timeout.connect(self._sample_for_scopes)
        self._scope_timer.start(SCOPE_INTERVAL_MS)
        self._scoped_frame = None
        self.media_list.setMinimumWidth(230)
        self.color_panel.setMinimumWidth(320)
        self.resizeDocks([self.media_dock, self.color_dock], [250, 340], Qt.Horizontal)
        self.resizeDocks([self.color_dock, self.info_dock], [460, 300], Qt.Vertical)
        self.exposure_field.valueChanged.connect(self.color_panel.exposure.set_value)
        self.gamma_field.valueChanged.connect(self.color_panel.gamma.set_value)

    def _build_status_bar(self) -> None:
        self.pixel_label = QLabel()
        self.pixel_label.setStyleSheet(f"font-family: {palette.MONO_FAMILY};")
        self.fps_label = QLabel()
        self.cache_label = QLabel()
        self.decoder_label = QLabel()
        self.zoom_label = QLabel("100%")
        self.gpu_label = QLabel()
        status = self.statusBar()
        status.addWidget(self.pixel_label, 1)
        status.addPermanentWidget(self.fps_label)
        status.addPermanentWidget(self.decoder_label)
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
        file_menu.addAction(self._action("open_playlist", self.open_playlist_dialog))
        file_menu.addAction(self._action("save_playlist", self.save_playlist_dialog))
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
        play_menu.addAction(self._action("cycle_compare_source", self._cycle_compare_source))
        play_menu.addAction(self._action("toggle_compare", self._toggle_compare))
        play_menu.addAction(self._action("next_media", lambda: self._cycle_media(1)))
        mute = self._action("mute", lambda on: self._set_audio_enabled(not on), True)
        mute.setChecked(not self.audio_enabled)
        play_menu.addAction(mute)
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
        aspect_menu = view_menu.addMenu("Aspect guide")
        aspect_group = QActionGroup(self)
        for name, ratio in ASPECT_GUIDES:
            option = QAction(name, self, checkable=True, checked=ratio == 0.0)
            option.triggered.connect(lambda _=False, ratio=ratio: self.set_aspect_guide(ratio))
            aspect_group.addAction(option)
            aspect_menu.addAction(option)
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
        panels.addAction(self.browser_dock.toggleViewAction())
        panels.addAction(self.color_dock.toggleViewAction())
        panels.addAction(self.ocio_dock.toggleViewAction())
        panels.addAction(self.scopes_dock.toggleViewAction())
        panels.addAction(self.inspector_dock.toggleViewAction())
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
        settings_menu.addSeparator()
        clear = QAction("Clear frame cache", self)
        clear.triggered.connect(self.clear_cache)
        settings_menu.addAction(clear)

        help_menu = bar.addMenu("&Help")
        keys = QAction("Keyboard shortcuts", self)
        keys.triggered.connect(self._show_shortcuts)
        help_menu.addAction(keys)
        edit_keys = QAction("Edit shortcuts file...", self)
        edit_keys.triggered.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(shortcuts.shortcuts_path()))))
        help_menu.addAction(edit_keys)
        check = QAction("Check for updates...", self)
        check.triggered.connect(lambda: self.check_for_updates(user_asked=True))
        help_menu.addAction(check)
        auto = QAction("Check for updates automatically", self, checkable=True,
                       checked=self.settings.value("auto_update", True, type=bool))
        auto.toggled.connect(lambda on: self.settings.setValue("auto_update", on))
        help_menu.addAction(auto)
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
        self.ocio_panel.set_source(source)
        self.setWindowTitle(f"{source.label} - ProEXR Viewer")
        self._sync_range()
        self._show(source.first, wait=True)

    def close_source(self, source: MediaSource) -> None:
        row = self.media_list.sources().index(source)
        self.media_list.remove_source(source)
        self.cache.forget(source)
        track = self._audio_tracks.pop(source.uid, None)
        if track is not None:
            self.audio_player.stop()
            track.close()
        if source is self.compare_source:
            self.set_compare_source(None)
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

    def _compare_number(self, number: int) -> int:
        b = self.compare_source
        return min(b.last, max(b.first, b.first + number - self.source.first))

    def _is_comparing(self) -> bool:
        return self.compare_source is not None and self.viewer.compare_mode is not CompareMode.OFF

    def _is_cached(self, number: int) -> bool:
        if self.source is None or self.cache.get(self.source, number, self.layer) is None:
            return False
        if self._is_comparing():
            return self.compare_cache.get(self.compare_source, self._compare_number(number), 0) is not None
        return True

    def _follow(self) -> None:
        if self.source is None:
            return
        direction = self.clock.direction or 1
        self.cache.follow(self.source, self.layer, self.clock.current, direction,
                          (self.clock.in_point, self.clock.out_point))
        if self._is_comparing():
            b = self.compare_source
            self.compare_cache.follow(b, 0, self._compare_number(self.clock.current), direction,
                                      (self._compare_number(self.clock.in_point), self._compare_number(self.clock.out_point)))
        else:
            self.compare_cache.follow(None, 0, 0, 1, (0, 0))

    def _show(self, number: int, wait: bool = False) -> None:
        if self.source is None:
            return
        self.clock.current = number
        self._last_shown = number
        self._follow()
        frame = self.cache.get(self.source, number, self.layer)
        if frame is None and wait:
            frame = self.cache.read_now(self.source, number, self.layer)
        if frame is not None:
            self.viewer.show_frame(frame)
            self._show_compare(number, wait)
        elif self.cache.error_for(self.source, number, self.layer):
            self.viewer.hint = f"Cannot read frame {number}:\n{self.cache.error_for(self.source, number, self.layer)}"
            self.viewer.update()
        self.timeline.set_current(number)
        self.transport.frame_field.blockSignals(True)
        self.transport.frame_field.setValue(number)
        self.transport.frame_field.blockSignals(False)

    def _show_compare(self, number: int, wait: bool) -> None:
        if not self._is_comparing():
            return
        b_number = self._compare_number(number)
        frame = self.compare_cache.get(self.compare_source, b_number, 0)
        if frame is None and wait:
            frame = self.compare_cache.read_now(self.compare_source, b_number, 0)
        if frame is not None:
            self.viewer.show_compare_frame(frame)

    def _frame_ready(self, key: CacheKey) -> None:
        if self.source is None or self.clock.is_playing:
            return
        if self._is_comparing() and key == (self.compare_source.uid, 0, self._compare_number(self.clock.current)):
            self._show_compare(self.clock.current, wait=False)
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
        self._sync_audio()

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
        self._sync_audio()

    def stop(self) -> None:
        self.clock.stop()
        self._play_timer.stop()
        self.transport.show_direction(0)
        self._follow()
        self.audio_player.stop()

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
            jumped = self._last_shown is not None and number < self._last_shown
            self._show(number)
            if jumped:
                self._sync_audio()
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
        self._sync_audio()

    def _retime(self) -> None:
        self.clock.restart_timing(time.perf_counter())
        if self.clock.is_playing:
            self._play_timer.setInterval(max(1, int(1000 / self.clock.rate / 4)))

    def set_layer(self, index: int) -> None:
        if index < 0 or self.source is None:
            return
        self.layer = index
        self._show(self.clock.current, wait=not self.clock.is_playing)

    def set_compare_source(self, source: MediaSource | None) -> None:
        self.compare_source = source
        self.media_list.mark_compare(source)
        self.viewer.show_compare_frame(None)
        if source is not None and self.viewer.compare_mode is CompareMode.OFF:
            self.compare_box.setCurrentText("Wipe")
        self._follow()
        self._show_compare(self.clock.current, wait=True)

    def _cycle_compare_source(self) -> None:
        candidates = [s for s in self.media_list.sources() if s is not self.source]
        if not candidates:
            return
        index = candidates.index(self.compare_source) + 1 if self.compare_source in candidates else 0
        self.set_compare_source(candidates[index % len(candidates)])

    def _set_compare_mode(self, index: int) -> None:
        self.viewer.compare_mode = CompareMode(index)
        if self.viewer.is_fit:
            self.viewer.fit()
        self._follow()
        self._show_compare(self.clock.current, wait=not self.clock.is_playing)
        self.viewer.update()

    def _toggle_compare(self) -> None:
        if self.compare_box.currentIndex():
            self._last_compare_index = self.compare_box.currentIndex()
            self.compare_box.setCurrentIndex(0)
        else:
            self.compare_box.setCurrentIndex(getattr(self, "_last_compare_index", CompareMode.WIPE))

    def _set_channel(self, index: int) -> None:
        self.viewer.channel = Channel(index)
        self.viewer.update()

    def _set_view_transform(self, index: int) -> None:
        self.viewer.view_transform = ViewTransform(index)
        if self.viewer.view_transform is ViewTransform.OCIO:
            self.ocio_dock.show()
            self.ocio_dock.raise_()
        self.settings.setValue("view_transform", index)
        self.viewer.update()

    def _apply_grade(self, grade: dict) -> None:
        self.viewer.set_grade(**grade)
        for field, key in ((self.exposure_field, "exposure"), (self.gamma_field, "gamma")):
            field.blockSignals(True)
            field.setValue(grade[key])
            field.blockSignals(False)

    def _apply_display_lut(self, lut) -> None:
        self.viewer.set_display_lut(lut)
        self.settings.setValue("ocio_config", self.ocio_panel.config_source)
        self.settings.setValue("ocio_display", self.ocio_panel.display_box.currentText())
        self.settings.setValue("ocio_view", self.ocio_panel.view_box.currentText())

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

    def _sample_for_scopes(self) -> None:
        if not self.scopes_dock.isVisible() or self.viewer.frame is None:
            return
        signature = (id(self.viewer.frame), tuple(sorted((k, str(v)) for k, v in self.viewer.grade.items())),
                     self.viewer.view_transform, self.viewer.channel, id(self.viewer.display_lut))
        if signature != self._scoped_frame:
            self._scoped_frame = signature
            self.viewer.request_display_sample(SCOPE_SAMPLE_WIDTH)

    def _show_pixel(self, pixel: dict | None) -> None:
        if not pixel:
            self.pixel_label.setText("")
            return
        frame = self.viewer.frame
        if frame is not None and self.source is not None:
            layer = self.source.layers[min(self.layer, len(self.source.layers) - 1)]
            names = layer.channel_names if len(layer.channel_names) == frame.pixels.shape[2] else list("RGBA")
            self.pixel_inspector.show_report(pixel_report(frame.pixels, pixel["x"], pixel["y"], names))
        values = pixel["values"]
        names = "RGBA" if len(values) > 1 else "V"
        text = "  ".join(f"{names[i]} {values[i]:.4f}" for i in range(len(values)))
        if pixel["is_integer"]:
            text += "   (" + " ".join(str(int(v)) for v in pixel["raw"]) + ")"
        self.pixel_label.setText(f"x {pixel['x']:>5}  y {pixel['y']:>5}    {text}")

    def _refresh_status(self) -> None:
        if self.source is not None:
            self.timeline.set_cached(self.cache.cached_numbers(self.source, self.layer))
        budget = self.cache.max_bytes / (1 << 30)
        used = self.cache.used_bytes / (1 << 30)
        percent = 100 * self.cache.used_bytes / self.cache.max_bytes if self.cache.max_bytes else 0
        self.cache_label.setText(f"Cache {used:.1f} / {budget:.1f} GB ({percent:.0f}%)")
        self.cache_label.setToolTip(f"Configured {self.cache_gb} GB; shrinks automatically when free RAM runs low")
        device = getattr(self.source, "hardware_device", None)
        is_video = self.source is not None and self.source.kind == "video"
        self.decoder_label.setText(("GPU decode: " + device if device else "CPU decode") if is_video else "")
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
        docks = (self.media_dock, self.browser_dock, self.color_dock, self.ocio_dock, self.info_dock, self.scopes_dock,
                 self.inspector_dock)
        hiding = self.view_bar.isVisible()
        if hiding:
            self._docks_before_hide = [d for d in docks if d.isVisible()]
        for dock in docks if hiding else self._docks_before_hide:
            dock.setVisible(not hiding)
        for widget in (self.menuBar(), self.statusBar(), self.view_bar):
            widget.setVisible(not hiding)

    def _reset_layout(self) -> None:
        for dock, area in ((self.media_dock, Qt.LeftDockWidgetArea), (self.browser_dock, Qt.LeftDockWidgetArea),
                           (self.color_dock, Qt.RightDockWidgetArea), (self.ocio_dock, Qt.RightDockWidgetArea),
                           (self.info_dock, Qt.RightDockWidgetArea), (self.inspector_dock, Qt.RightDockWidgetArea),
                           (self.scopes_dock, Qt.BottomDockWidgetArea)):
            dock.setFloating(False)
            self.addDockWidget(area, dock)
            dock.show()
        self.tabifyDockWidget(self.media_dock, self.browser_dock)
        self.tabifyDockWidget(self.color_dock, self.ocio_dock)
        self.tabifyDockWidget(self.info_dock, self.inspector_dock)
        for dock in (self.media_dock, self.color_dock, self.info_dock):
            dock.raise_()
        self.scopes_dock.hide()

    def _set_cache_size(self, size_gb: int) -> None:
        self.cache_gb = size_gb
        self.settings.setValue("cache_gb", size_gb)
        self._adapt_cache_to_memory()

    def _adapt_cache_to_memory(self) -> None:
        """Keep both caches inside the configured size and the RAM the system can spare right now."""
        available = available_memory_bytes()
        used = self.cache.used_bytes + self.compare_cache.used_bytes
        total = safe_cache_budget(self.cache_gb << 30, used, available)
        main_share = total if self.compare_source is None else int(total * (1 - COMPARE_CACHE_SHARE))
        if main_share != self.cache.max_bytes:
            self.cache.set_budget(main_share)
        compare_share = total - main_share if self.compare_source is not None else int(total * COMPARE_CACHE_SHARE)
        if compare_share != self.compare_cache.max_bytes:
            self.compare_cache.set_budget(compare_share)

    def set_aspect_guide(self, ratio: float) -> None:
        self.viewer.aspect_guide = ratio
        self.viewer.update()

    def _set_audio_enabled(self, enabled: bool) -> None:
        self.audio_enabled = enabled
        self.settings.setValue("muted", not enabled)
        self._sync_audio()

    def _audio_track(self, source: MediaSource) -> AudioTrack | None:
        if source.uid not in self._audio_tracks:
            track = None
            if source.kind == "video" and has_audio(source.path):
                try:
                    track = AudioTrack(source.path)
                except MediaReadError:
                    track = None
            self._audio_tracks[source.uid] = track
        return self._audio_tracks[source.uid]

    def _sync_audio(self) -> None:
        """Audio follows forward playback at 1x; any other state, or a jump, restarts or silences it."""
        source = self.source
        should_play = (source is not None and self.audio_enabled and self.clock.direction == 1
                       and self.clock.speed == 1.0)
        track = self._audio_track(source) if should_play else None
        if track is None:
            self.audio_player.stop()
            return
        seconds = getattr(source, "start_seconds", 0.0) + (self.clock.current - source.first) / source.fps
        self.audio_player.play(track, seconds)

    def open_playlist_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open playlist", self.settings.value("last_folder", ""),
                                              f"ProEXR playlist (*{PLAYLIST_SUFFIX} *.json)")
        if path:
            self.open_playlist(Path(path))

    def open_playlist(self, path: Path) -> None:
        try:
            media = load_playlist(path)
        except PlaylistError as error:
            QMessageBox.warning(self, "Could not open playlist", str(error))
            return
        self.open_paths([str(item) for item in media])

    def save_playlist_dialog(self) -> None:
        if not self.media_list.count():
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save playlist", self.settings.value("last_folder", ""),
                                              f"ProEXR playlist (*{PLAYLIST_SUFFIX})")
        if path:
            if not path.endswith(".json"):
                path += PLAYLIST_SUFFIX
            self.save_playlist(Path(path))

    def save_playlist(self, path: Path) -> None:
        try:
            save_playlist(path, [source.path for source in self.media_list.sources()])
        except PlaylistError as error:
            QMessageBox.warning(self, "Could not save playlist", str(error))

    def clear_cache(self) -> None:
        self.cache.clear()
        self.compare_cache.clear()
        self.timeline.set_cached(set())
        self._refresh_status()

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

    def check_for_updates(self, user_asked: bool) -> None:
        now = time.time()
        if not user_asked and now - self.settings.value("last_update_check", 0.0, type=float) < UPDATE_CHECK_EVERY_SECONDS:
            return
        self.settings.setValue("last_update_check", now)

        def work() -> None:
            try:
                self._update_relay.checked.emit(update.fetch_latest_release(), user_asked)
            except UpdateError as error:
                self._update_relay.checked.emit(str(error), user_asked)
        threading.Thread(target=work, daemon=True, name="update-check").start()

    def _update_checked(self, result, user_asked: bool) -> None:
        if isinstance(result, str):
            if user_asked:
                QMessageBox.warning(self, "Check for updates", f"Could not check for updates.\n{result}")
            return
        if not update.is_newer(result.version):
            if user_asked:
                QMessageBox.information(self, "Check for updates", f"ProEXR Viewer {__version__} is up to date.")
            return
        can_install = sys.platform == "win32" and getattr(sys, "frozen", False) and result.installer_url
        question = (f"ProEXR Viewer {result.version} is available (you have {__version__}).\n\n"
                    + ("Download and install it now? The viewer will close and reopen." if can_install
                       else "Open the download page?"))
        if QMessageBox.question(self, "Update available", question) != QMessageBox.Yes:
            return
        if not can_install:
            QDesktopServices.openUrl(QUrl(result.page_url))
            return
        self.statusBar().showMessage(f"Downloading ProEXR Viewer {result.version}...")

        def work() -> None:
            try:
                self._update_relay.downloaded.emit(update.download_installer(result))
            except UpdateError as error:
                self._update_relay.downloaded.emit(str(error))
        threading.Thread(target=work, daemon=True, name="update-download").start()

    def _update_downloaded(self, result) -> None:
        self.statusBar().clearMessage()
        if isinstance(result, str):
            QMessageBox.warning(self, "Update", f"Download failed.\n{result}")
            return
        subprocess.Popen([str(result), "/SILENT", "/SP-", "/NOCANCEL", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"],
                         close_fds=True)
        self.close()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.open_paths(paths)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("window_state", self.saveState(LAYOUT_VERSION))
        self.stop()
        self.cache.shutdown()
        self.compare_cache.shutdown()
        self.file_browser.shutdown()
        for track in self._audio_tracks.values():
            if track is not None:
                track.close()
        for source in self.media_list.sources():
            source.close()
        super().closeEvent(event)
