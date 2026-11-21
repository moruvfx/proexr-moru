"""Main window: wires media, cache, player, viewer and panels together."""
from __future__ import annotations

import os
import sys
import traceback

from PySide6.QtCore import QObject, QSettings, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (QApplication, QComboBox, QDockWidget, QDoubleSpinBox,
                               QFileDialog, QHBoxLayout, QLabel, QMainWindow,
                               QMessageBox, QSpinBox, QToolButton, QVBoxLayout, QWidget)

from .. import __version__
from ..cache import FrameCache
from ..media.source import VideoSource, open_media
from ..player import LOOP, ONCE, PINGPONG, Player
from . import shortcuts
from .panels import AdjustPanel, InfoPanel, Playlist
from .timeline import Timeline
from .viewer import CHANNELS, VIEWS, Viewer

FPS_PRESETS = [12, 15, 23.976, 24, 25, 29.97, 30, 48, 50, 59.94, 60, 120]
SPEEDS = [0.1, 0.25, 0.5, 1.0, 1.5, 2.0, 4.0]
CACHE_GB = [1, 2, 4, 8, 12, 16, 24, 32, 48, 64]


def total_ram() -> int:
    try:
        if sys.platform == "win32":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = MS()
            m.dwLength = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return int(m.ullTotalPhys)
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except Exception:
        return 8 << 30


class _Bridge(QObject):
    ready = Signal(object)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ProEXR Viewer")
        self.resize(1500, 900)
        self.settings = QSettings("PROEXR_MORU", "ProEXRViewer")
        VideoSource.hw_decode = self.settings.value("hw_decode", True, type=bool)

        ram = total_ram()
        default_gb = max(1, min(16, int(ram * 0.3 / (1 << 30))))
        self.cache_gb = self.settings.value("cache_gb", default_gb, type=int)
        self.cache = FrameCache(self.cache_gb << 30)
        self._bridge = _Bridge()
        self._bridge.ready.connect(self._on_frame_ready, Qt.QueuedConnection)
        self.cache.on_frame_ready = self._bridge.ready.emit

        self.source = None
        self.layer = 0
        self.player = Player(self)
        self.player.is_ready = lambda f: self.source is not None and \
            self.cache.get(self.source, f, self.layer) is not None
        self.player.frameChanged.connect(self._display)
        self.player.stateChanged.connect(self._sync_transport)

        self.viewer = Viewer()
        self.viewer.message = "Drop images, EXR sequences, videos or folders here\n\nCtrl+O open file   ·   Ctrl+Shift+O open folder"
        self.viewer.filesDropped.connect(self.open_paths)
        self.viewer.pixelHovered.connect(self._on_pixel)
        self.viewer.zoomChanged.connect(lambda z: self.zoom_label.setText(f"{z * 100:.0f}%"))

        self._build_toolbar()
        self._build_central()
        self._build_docks()
        self._build_status()
        self._build_actions()
        self.setAcceptDrops(True)

        self._ui_timer = QTimer(self)
        self._ui_timer.timeout.connect(self._refresh_status)
        self._ui_timer.start(250)

        geo = self.settings.value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        state = self.settings.value("state")
        if state is not None:
            self.restoreState(state)
        self._default_state = None

    # ================================================================ UI ==
    def _build_toolbar(self):
        tb = self.addToolBar("View")
        tb.setObjectName("viewbar")
        tb.setMovable(False)

        def label(t):
            l = QLabel(t)
            l.setStyleSheet("color:#7d7d86; padding-left:6px;")
            return l

        tb.addWidget(label("Layer"))
        self.layer_combo = QComboBox()
        self.layer_combo.setMinimumWidth(150)
        self.layer_combo.currentIndexChanged.connect(self._on_layer)
        tb.addWidget(self.layer_combo)
        tb.addWidget(label("Channel"))
        self.channel_combo = QComboBox()
        self.channel_combo.addItems(CHANNELS)
        self.channel_combo.currentIndexChanged.connect(self._on_channel)
        tb.addWidget(self.channel_combo)
        tb.addWidget(label("View"))
        self.view_combo = QComboBox()
        self.view_combo.addItems(VIEWS)
        self.view_combo.setCurrentIndex(self.settings.value("view", 1, type=int))
        self.view_combo.currentIndexChanged.connect(self._on_view)
        self.viewer.view = self.view_combo.currentIndex()
        tb.addWidget(self.view_combo)
        tb.addSeparator()
        tb.addWidget(label("Exp"))
        self.exp_spin = QDoubleSpinBox()
        self.exp_spin.setRange(-10, 10)
        self.exp_spin.setSingleStep(0.5)
        self.exp_spin.setDecimals(2)
        self.exp_spin.setFixedWidth(70)
        tb.addWidget(self.exp_spin)
        tb.addWidget(label("Gamma"))
        self.gamma_spin = QDoubleSpinBox()
        self.gamma_spin.setRange(0.1, 4)
        self.gamma_spin.setSingleStep(0.1)
        self.gamma_spin.setValue(1.0)
        self.gamma_spin.setFixedWidth(64)
        tb.addWidget(self.gamma_spin)
        tb.addSeparator()
        self.zoom_label = QLabel("100%")
        self.zoom_label.setMinimumWidth(48)
        self.zoom_label.setAlignment(Qt.AlignCenter)
        self._tb = tb

    def _tool(self, text, tip, slot, checkable=False):
        b = QToolButton()
        b.setText(text)
        b.setToolTip(tip)
        b.setCheckable(checkable)
        b.clicked.connect(slot)
        return b

    def _build_central(self):
        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.viewer, 1)

        self.timeline = Timeline()
        self.timeline.scrubbed.connect(self._on_scrub)
        self.timeline.scrubStarted.connect(self._scrub_start)
        lay.addWidget(self.timeline)

        bar = QWidget()
        bar.setStyleSheet("background:#202023;")
        h = QHBoxLayout(bar)
        h.setContentsMargins(8, 4, 8, 6)
        h.setSpacing(4)
        self.frame_spin = QSpinBox()
        self.frame_spin.setRange(-10**7, 10**7)
        self.frame_spin.setFixedWidth(84)
        self.frame_spin.setKeyboardTracking(False)
        self.frame_spin.valueChanged.connect(lambda v: self.player.seek(v))
        self.in_label = QLabel("In 0")
        self.out_label = QLabel("Out 0")
        for l in (self.in_label, self.out_label):
            l.setStyleSheet("color:#b9875c;")
        h.addWidget(self.frame_spin)
        h.addWidget(self.in_label)
        h.addWidget(self.out_label)
        h.addStretch(1)
        self.b_first = self._tool("⏮", "First frame (Home)", lambda: self.player.seek(self.player.in_point))
        self.b_prev = self._tool("◀|", "Previous frame (Left)", lambda: self.player.step(-1))
        self.b_rev = self._tool("◀", "Play reverse (J)", lambda: self._play(-1), True)
        self.b_stop = self._tool("■", "Stop (K)", lambda: self.player.stop())
        self.b_fwd = self._tool("▶", "Play forward (L / Space)", lambda: self._play(1), True)
        self.b_next = self._tool("|▶", "Next frame (Right)", lambda: self.player.step(1))
        self.b_last = self._tool("⏭", "Last frame (End)", lambda: self.player.seek(self.player.out_point))
        for b in (self.b_first, self.b_prev, self.b_rev, self.b_stop, self.b_fwd, self.b_next, self.b_last):
            b.setMinimumWidth(34)
            h.addWidget(b)
        h.addStretch(1)
        self.loop_combo = QComboBox()
        self.loop_combo.addItems(["Loop", "Ping-pong", "Play once"])
        self.loop_combo.currentIndexChanged.connect(
            lambda i: setattr(self.player, "loop_mode", (LOOP, PINGPONG, ONCE)[i]))
        h.addWidget(self.loop_combo)
        h.addWidget(QLabel(" FPS"))
        self.fps_combo = QComboBox()
        self.fps_combo.setEditable(True)
        self.fps_combo.addItems([f"{f:g}" for f in FPS_PRESETS])
        self.fps_combo.setFixedWidth(76)
        self.fps_combo.currentTextChanged.connect(self._on_fps)
        h.addWidget(self.fps_combo)
        h.addWidget(QLabel(" Speed"))
        self.speed_combo = QComboBox()
        self.speed_combo.addItems([f"{s:g}x" for s in SPEEDS])
        self.speed_combo.setCurrentIndex(SPEEDS.index(1.0))
        self.speed_combo.currentIndexChanged.connect(lambda i: self.player.set_speed(SPEEDS[i]))
        h.addWidget(self.speed_combo)
        self.rt_btn = self._tool("Realtime", "Realtime: skip frames that are late.\nOff: play every frame, slowing down if needed.",
                                 self._on_realtime, True)
        self.rt_btn.setChecked(True)
        h.addWidget(self.rt_btn)
        lay.addWidget(bar)
        self.setCentralWidget(central)

    def _dock(self, title, widget, area, name):
        d = QDockWidget(title, self)
        d.setObjectName(name)
        d.setWidget(widget)
        d.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable |
                      QDockWidget.DockWidgetClosable)
        self.addDockWidget(area, d)
        return d

    def _build_docks(self):
        self.playlist = Playlist()
        self.playlist.activated_source.connect(self.set_source)
        self.playlist.remove_requested.connect(self.close_source)
        self.d_playlist = self._dock("Media", self.playlist, Qt.LeftDockWidgetArea, "dock_media")
        self.adjust = AdjustPanel()
        self.adjust.changed.connect(self._on_adjust)
        self.d_adjust = self._dock("Color", self.adjust, Qt.RightDockWidgetArea, "dock_color")
        self.info = InfoPanel()
        self.d_info = self._dock("Info", self.info, Qt.RightDockWidgetArea, "dock_info")
        self.resizeDocks([self.d_playlist, self.d_adjust], [240, 300], Qt.Horizontal)
        # keep toolbar exposure/gamma in sync with the colour panel
        self.exp_spin.valueChanged.connect(lambda v: self.adjust.ctrls["exposure"].setValue(v))
        self.gamma_spin.valueChanged.connect(lambda v: self.adjust.ctrls["gamma"].setValue(v))

    def _build_status(self):
        sb = self.statusBar()
        self.pixel_label = QLabel("")
        self.cache_label = QLabel("")
        self.fps_label = QLabel("")
        self.gpu_label = QLabel("")
        sb.addWidget(self.pixel_label, 1)
        sb.addPermanentWidget(self.fps_label)
        sb.addPermanentWidget(self.cache_label)
        sb.addPermanentWidget(self.zoom_label)
        sb.addPermanentWidget(self.gpu_label)

    def _build_actions(self):
        keys = shortcuts.load()
        self.actions_by_id = {}

        def act(aid, slot, checkable=False, checked=False):
            a = QAction(shortcuts.DEFAULTS[aid][1], self)
            a.setShortcuts([QKeySequence(k) for k in keys.get(aid, [])])
            a.setShortcutContext(Qt.WindowShortcut)
            a.setCheckable(checkable)
            if checkable:
                a.setChecked(checked)
                a.toggled.connect(slot)
            else:
                a.triggered.connect(slot)
            self.addAction(a)
            self.actions_by_id[aid] = a
            return a

        mb = self.menuBar()
        m = mb.addMenu("&File")
        m.addAction(act("open_file", self.open_file_dialog))
        m.addAction(act("open_folder", self.open_folder_dialog))
        m.addAction(act("close_media", lambda: self.source and self.close_source(self.source)))
        m.addSeparator()
        m.addAction(act("quit", self.close))

        m = mb.addMenu("&Playback")
        for aid, slot in [
            ("toggle_play", self.player.toggle), ("play_forward", lambda: self._play(1)),
            ("play_reverse", lambda: self._play(-1)), ("stop", self.player.stop), (None, None),
            ("next_frame", lambda: self.player.step(1)), ("prev_frame", lambda: self.player.step(-1)),
            ("next_10", lambda: self.player.step(10)), ("prev_10", lambda: self.player.step(-10)),
            ("first_frame", lambda: self.player.seek(self.player.in_point)),
            ("last_frame", lambda: self.player.seek(self.player.out_point)), (None, None),
            ("set_in", self._set_in), ("set_out", self._set_out), ("clear_in_out", self._clear_in_out),
            ("cycle_loop", lambda: self.loop_combo.setCurrentIndex((self.loop_combo.currentIndex() + 1) % 3)),
            ("speed_up", lambda: self.speed_combo.setCurrentIndex(min(len(SPEEDS) - 1, self.speed_combo.currentIndex() + 1))),
            ("speed_down", lambda: self.speed_combo.setCurrentIndex(max(0, self.speed_combo.currentIndex() - 1))),
            (None, None),
            ("next_media", lambda: self._cycle_media(1)), ("prev_media", lambda: self._cycle_media(-1)),
        ]:
            if aid is None:
                m.addSeparator()
            else:
                m.addAction(act(aid, slot))

        m = mb.addMenu("&View")
        m.addAction(act("fit", self.viewer.fit))
        m.addAction(act("actual", self.viewer.actual_pixels))
        m.addAction(act("zoom_in", lambda: self.viewer.set_zoom(self.viewer.zoom * 1.25)))
        m.addAction(act("zoom_out", lambda: self.viewer.set_zoom(self.viewer.zoom / 1.25)))
        m.addSeparator()
        m.addAction(act("fullscreen", self.toggle_fullscreen))
        m.addAction(act("viewer_only", self.toggle_panels))
        m.addSeparator()
        m.addAction(act("safe_areas", lambda v: self._overlay("safe", v), True))
        m.addAction(act("grid", lambda v: self._overlay("grid", v), True))
        a = QAction("Center cross", self, checkable=True)
        a.toggled.connect(lambda v: self._overlay("center", v))
        m.addAction(a)
        m.addAction(act("clipping", self._on_clip, True))
        nn = QAction("Nearest-neighbour when zoomed in", self, checkable=True, checked=True)
        nn.toggled.connect(lambda v: (setattr(self.viewer, "nearest_when_zoomed", v), self.viewer.update()))
        m.addAction(nn)
        tc = QAction("Show timecode on timeline", self, checkable=True)
        tc.toggled.connect(lambda v: (setattr(self.timeline, "show_timecode", v), self.timeline.update()))
        m.addAction(tc)
        m.addSeparator()
        panels = m.addMenu("Panels")
        for d in (self.d_playlist, self.d_adjust, self.d_info):
            panels.addAction(d.toggleViewAction())
        reset = QAction("Reset layout", self)
        reset.triggered.connect(self._reset_layout)
        panels.addAction(reset)

        m = mb.addMenu("&Color")
        for i, aid in enumerate(["ch_rgb", "ch_r", "ch_g", "ch_b", "ch_a", "ch_l"]):
            m.addAction(act(aid, lambda _=False, i=i: self.channel_combo.setCurrentIndex(i)))
        m.addSeparator()
        m.addAction(act("next_layer", lambda: self._cycle_layer(1)))
        m.addAction(act("prev_layer", lambda: self._cycle_layer(-1)))
        m.addSeparator()
        m.addAction(act("exp_up", lambda: self.adjust.nudge_exposure(0.5)))
        m.addAction(act("exp_down", lambda: self.adjust.nudge_exposure(-0.5)))
        m.addAction(act("reset_color", self.adjust.reset))

        m = mb.addMenu("&Settings")
        cm = m.addMenu("Frame cache size")
        g = QActionGroup(self)
        for gb in CACHE_GB:
            a = QAction(f"{gb} GB", self, checkable=True, checked=(gb == self.cache_gb))
            a.triggered.connect(lambda _=False, gb=gb: self._set_cache(gb))
            g.addAction(a)
            cm.addAction(a)
        hw = QAction("Hardware video decoding (NVIDIA NVDEC / D3D11)", self, checkable=True,
                     checked=VideoSource.hw_decode)
        hw.toggled.connect(self._set_hw)
        m.addAction(hw)

        m = mb.addMenu("&Help")
        a = QAction("Keyboard shortcuts", self)
        a.triggered.connect(self._show_shortcuts)
        m.addAction(a)
        a = QAction("Edit shortcuts file...", self)
        a.triggered.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(shortcuts.shortcuts_path())))
        m.addAction(a)
        a = QAction("About", self)
        a.triggered.connect(self._about)
        m.addAction(a)

    # ============================================================ media ==
    def open_file_dialog(self):
        start = self.settings.value("last_dir", "")
        paths, _ = QFileDialog.getOpenFileNames(self, "Open media", start,
            "Media (*.exr *.sxr *.png *.jpg *.jpeg *.tif *.tiff *.tga *.dpx *.cin *.hdr *.bmp *.psd *.webp "
            "*.jp2 *.jxl *.mp4 *.mov *.avi *.mkv *.mxf *.webm *.m4v *.mpg *.ts);;All files (*)")
        if paths:
            self.open_paths(paths)

    def open_folder_dialog(self):
        d = QFileDialog.getExistingDirectory(self, "Open folder", self.settings.value("last_dir", ""))
        if d:
            self.open_paths([d])

    def open_paths(self, paths):
        added = []
        seen = {(s.path if s.kind == "video" else (getattr(s, "seq", None) and (s.seq.directory, s.seq.prefix, s.seq.ext)))
                for s in self.playlist.sources()}
        errors = []
        for p in paths:
            try:
                for src in open_media(p):
                    sig = src.path if src.kind == "video" else (src.seq.directory, src.seq.prefix, src.seq.ext)
                    if sig in seen:
                        continue
                    seen.add(sig)
                    self.playlist.add(src)
                    added.append(src)
            except Exception as exc:
                errors.append(f"{os.path.basename(p)}: {exc}")
                traceback.print_exc()
            self.settings.setValue("last_dir", p if os.path.isdir(p) else os.path.dirname(p))
        if added:
            self.playlist.select(added[0])
        if errors:
            QMessageBox.warning(self, "Could not open", "\n".join(errors[:20]))

    def set_source(self, src):
        if src is self.source:
            return
        self.player.stop()
        self.source = src
        self.layer = 0
        self.viewer.message = ""
        self.viewer.pixel_aspect = src.pixel_aspect
        self.viewer.fit_mode = True
        self.layer_combo.blockSignals(True)
        self.layer_combo.clear()
        self.layer_combo.addItems([l.label for l in src.layers])
        self.layer_combo.setEnabled(len(src.layers) > 1)
        self.layer_combo.blockSignals(False)
        self.player.set_range(src.first, src.last, src.fps)
        self.player.current = src.first
        self.fps_combo.blockSignals(True)
        self.fps_combo.setCurrentText(f"{src.fps:.3f}".rstrip("0").rstrip("."))
        self.fps_combo.blockSignals(False)
        missing = getattr(getattr(src, "seq", None), "missing", []) or []
        self.timeline.set_range(src.first, src.last, src.fps, missing)
        self.frame_spin.blockSignals(True)
        self.frame_spin.setValue(src.first)
        self.frame_spin.blockSignals(False)
        extra = {"Layers": str(len(src.layers))}
        if src.kind == "video":
            extra["Decoder"] = f"hardware ({src.hw_active})" if src.hw_active else "software (multi-threaded)"
        self.info.show_info(src.info, extra)
        self.setWindowTitle(f"{src.name} - ProEXR Viewer")
        self._sync_transport()
        self._display(src.first, sync=True)

    def close_source(self, src):
        row = self.playlist.sources().index(src)
        self.playlist.takeItem(row)
        self.cache.clear(src)
        src.close()
        if src is self.source:
            self.source = None
            self.player.stop()
            if self.playlist.count():
                self.playlist.setCurrentRow(min(row, self.playlist.count() - 1))
            else:
                self.viewer.set_frame(None)
                self.viewer.message = "Drop media here"
                self.viewer.update()
                self.info.clear()
                self.layer_combo.clear()

    # ========================================================= display ==
    def _display(self, f, sync=False):
        src = self.source
        if src is None:
            return
        self.cache.set_state(src, self.layer, f, self.player.direction or 1,
                             (self.player.in_point, self.player.out_point))
        fr = self.cache.get(src, f, self.layer)
        if fr is None and sync:
            fr = self.cache.load_now(src, f, self.layer)
        if fr is not None:
            self.viewer.set_frame(fr)
        elif self.cache.error(src, f, self.layer):
            self.viewer.message = f"Cannot read frame {f}:\n{self.cache.error(src, f, self.layer)}"
            self.viewer.update()
        self.timeline.set_current(f)
        self.frame_spin.blockSignals(True)
        self.frame_spin.setValue(f)
        self.frame_spin.blockSignals(False)

    def _on_frame_ready(self, key):
        src = self.source
        if src is None or self.player.playing:
            return
        if key == (src.uid, self.layer, self.player.current):
            fr = self.cache.get(src, key[2], self.layer)
            if fr is not None and fr is not self.viewer.frame:
                self.viewer.message = ""
                self.viewer.set_frame(fr)

    def _scrub_start(self):
        self.player.stop()

    def _on_scrub(self, f):
        self.player.seek(f)

    def _play(self, d):
        if self.player.direction == d:
            self.player.stop()
        else:
            self.player.play(d)
            self.cache.set_state(self.source, self.layer, self.player.current, d,
                                 (self.player.in_point, self.player.out_point)) if self.source else None

    def _on_layer(self, i):
        if i < 0 or self.source is None:
            return
        self.layer = i
        self._display(self.player.current, sync=not self.player.playing)

    def _cycle_layer(self, d):
        n = self.layer_combo.count()
        if n > 1:
            self.layer_combo.setCurrentIndex((self.layer_combo.currentIndex() + d) % n)

    def _cycle_media(self, d):
        n = self.playlist.count()
        if n:
            self.playlist.setCurrentRow((self.playlist.currentRow() + d) % n)

    def _on_channel(self, i):
        self.viewer.channel = i
        self.viewer.update()

    def _on_view(self, i):
        self.viewer.view = i
        self.settings.setValue("view", i)
        self.viewer.update()

    def _on_adjust(self, vals):
        self.viewer.set_adjust(**vals)
        for spin, key in ((self.exp_spin, "exposure"), (self.gamma_spin, "gamma")):
            spin.blockSignals(True)
            spin.setValue(vals[key])
            spin.blockSignals(False)

    def _on_clip(self, v):
        self.viewer.show_clip = v
        self.viewer.update()

    def _overlay(self, name, v):
        self.viewer.overlays[name] = v
        self.viewer.update()

    def _on_fps(self, text):
        try:
            fps = float(text)
        except ValueError:
            return
        if fps > 0:
            self.player.set_fps(fps)
            self.timeline.fps = fps

    def _on_realtime(self, v):
        self.player.realtime = bool(v)

    def _set_in(self):
        self.player.set_in()

    def _set_out(self):
        self.player.set_out()

    def _clear_in_out(self):
        self.player.clear_in_out()

    def _sync_transport(self):
        p = self.player
        self.b_fwd.setChecked(p.direction > 0)
        self.b_rev.setChecked(p.direction < 0)
        self.timeline.in_point, self.timeline.out_point = p.in_point, p.out_point
        self.in_label.setText(f"In {p.in_point}")
        self.out_label.setText(f"Out {p.out_point}")
        self.timeline.update()
        if self.source is not None:
            self.cache.set_state(self.source, self.layer, p.current, p.direction or 1, (p.in_point, p.out_point))

    def _on_pixel(self, info):
        if not info:
            self.pixel_label.setText("")
            return
        v = info["value"]
        names = "RGBA" if len(v) > 1 else "V"
        vals = "  ".join(f"{names[i]} {v[i]:.4f}" for i in range(len(v)))
        raw = ""
        if info["dtype"] in ("uint8", "uint16"):
            raw = "   (" + " ".join(str(int(x)) for x in info["raw"]) + ")"
        self.pixel_label.setText(f"x {info['x']:>5}  y {info['y']:>5}    {vals}{raw}")

    def _refresh_status(self):
        src = self.source
        if src is not None:
            self.timeline.set_cached(self.cache.cached_frames(src, self.layer))
        used = self.cache.used_bytes / (1 << 30)
        self.cache_label.setText(f"Cache {used:.1f}/{self.cache_gb} GB")
        if self.player.playing:
            self.fps_label.setText(f"{self.player.measured_fps():5.1f} / {self.player.rate:g} fps")
        else:
            self.fps_label.setText("")
        gi = getattr(self.viewer, "gl_info", None)
        if gi and not self.gpu_label.text():
            self.gpu_label.setText(gi["renderer"][:40])
            self.gpu_label.setToolTip(f"{gi['renderer']}\nOpenGL {gi['version']}")

    # ========================================================= window ===
    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def toggle_panels(self):
        vis = not self.d_adjust.isVisible() and not self.d_playlist.isVisible() and not self.d_info.isVisible()
        if not vis:
            self._panel_state = self.saveState()
            for d in (self.d_playlist, self.d_adjust, self.d_info):
                d.hide()
            self._tb.hide()
            self.menuBar().hide()
            self.statusBar().hide()
        else:
            self._tb.show()
            self.menuBar().show()
            self.statusBar().show()
            if getattr(self, "_panel_state", None) is not None:
                self.restoreState(self._panel_state)
            else:
                for d in (self.d_playlist, self.d_adjust, self.d_info):
                    d.show()

    def _reset_layout(self):
        for d in (self.d_playlist, self.d_adjust, self.d_info):
            d.setFloating(False)
            d.show()
        self.addDockWidget(Qt.LeftDockWidgetArea, self.d_playlist)
        self.addDockWidget(Qt.RightDockWidgetArea, self.d_adjust)
        self.addDockWidget(Qt.RightDockWidgetArea, self.d_info)

    def _set_cache(self, gb):
        self.cache_gb = gb
        self.settings.setValue("cache_gb", gb)
        self.cache.set_budget(gb << 30)

    def _set_hw(self, v):
        VideoSource.hw_decode = v
        self.settings.setValue("hw_decode", v)

    def _show_shortcuts(self):
        keys = shortcuts.load()
        rows = "".join(f"<tr><td style='padding-right:16px;color:#ffb37a'>{', '.join(keys[k])}</td>"
                       f"<td>{v[1]}</td></tr>" for k, v in shortcuts.DEFAULTS.items())
        QMessageBox.information(self, "Keyboard shortcuts",
                                f"<table>{rows}</table><p>Customise: Help &gt; Edit shortcuts file, then restart.</p>")

    def _about(self):
        gi = getattr(self.viewer, "gl_info", {})
        QMessageBox.about(self, "ProEXR Viewer",
                          f"<b>ProEXR Viewer</b> {__version__}<br>Read-only VFX media viewer.<br><br>"
                          f"GPU: {gi.get('renderer', '?')}<br>OpenGL: {gi.get('version', '?')}")

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.open_paths(paths)

    def closeEvent(self, e):
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("state", self.saveState())
        self.player.stop()
        self.cache.shutdown()
        for s in self.playlist.sources():
            s.close()
        super().closeEvent(e)
