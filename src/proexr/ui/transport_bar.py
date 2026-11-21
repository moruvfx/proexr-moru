from PySide6.QtCore import QSize
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QSpinBox, QToolButton, QWidget

from ..playback.clock import LoopMode
from .icons import make_icon

FPS_PRESETS = ("12", "15", "23.976", "24", "25", "29.97", "30", "48", "50", "59.94", "60", "120")
SPEEDS = (0.1, 0.25, 0.5, 1.0, 1.5, 2.0, 4.0)
LOOP_MODES = (LoopMode.LOOP, LoopMode.PINGPONG, LoopMode.ONCE)


def _button(icon: str, tooltip: str, checkable: bool = False) -> QToolButton:
    button = QToolButton()
    button.setIcon(make_icon(icon))
    button.setIconSize(QSize(20, 20))
    button.setToolTip(tooltip)
    button.setAccessibleName(tooltip)
    button.setCheckable(checkable)
    button.setMinimumSize(36, 32)
    return button


class TransportBar(QWidget):
    def __init__(self) -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 4, 10, 8)
        row.setSpacing(4)
        self.frame_field = QSpinBox()
        self.frame_field.setRange(-10_000_000, 10_000_000)
        self.frame_field.setKeyboardTracking(False)
        self.frame_field.setFixedWidth(90)
        self.frame_field.setAccessibleName("Current frame")
        self.range_label = QLabel("In 0   Out 0")
        self.range_label.setProperty("role", "muted")
        self.to_start = _button("to_start", "Go to in point (Home)")
        self.step_back = _button("step_back", "Previous frame (Left)")
        self.play_reverse = _button("play_reverse", "Play reverse (J)", checkable=True)
        self.stop = _button("stop", "Stop (K)")
        self.play_forward = _button("play", "Play forward (L, Space)", checkable=True)
        self.step_forward = _button("step_forward", "Next frame (Right)")
        self.to_end = _button("to_end", "Go to out point (End)")
        self.loop_box = QComboBox()
        self.loop_box.addItems(["Loop", "Ping-pong", "Play once"])
        self.loop_box.setAccessibleName("Loop mode")
        self.fps_box = QComboBox()
        self.fps_box.setEditable(True)
        self.fps_box.addItems(FPS_PRESETS)
        self.fps_box.setFixedWidth(84)
        self.fps_box.setAccessibleName("Frames per second")
        self.speed_box = QComboBox()
        self.speed_box.addItems([f"{s:g}x" for s in SPEEDS])
        self.speed_box.setCurrentIndex(SPEEDS.index(1.0))
        self.speed_box.setAccessibleName("Playback speed")
        self.realtime = QToolButton()
        self.realtime.setText("Realtime")
        self.realtime.setCheckable(True)
        self.realtime.setChecked(True)
        self.realtime.setToolTip("On: skip late frames to keep time.\nOff: show every frame, slowing down if needed.")
        row.addWidget(self.frame_field)
        row.addWidget(self.range_label)
        row.addStretch(1)
        row.addWidget(self.to_start)
        row.addWidget(self.step_back)
        row.addWidget(self.play_reverse)
        row.addWidget(self.stop)
        row.addWidget(self.play_forward)
        row.addWidget(self.step_forward)
        row.addWidget(self.to_end)
        row.addStretch(1)
        row.addWidget(self.loop_box)
        row.addWidget(QLabel("FPS"))
        row.addWidget(self.fps_box)
        row.addWidget(QLabel("Speed"))
        row.addWidget(self.speed_box)
        row.addWidget(self.realtime)

    def loop_mode(self) -> LoopMode:
        return LOOP_MODES[self.loop_box.currentIndex()]

    def speed(self) -> float:
        return SPEEDS[self.speed_box.currentIndex()]

    def show_direction(self, direction: int) -> None:
        self.play_forward.setChecked(direction > 0)
        self.play_reverse.setChecked(direction < 0)
        self.play_forward.setIcon(make_icon("pause" if direction > 0 else "play"))

    def show_range(self, in_point: int, out_point: int) -> None:
        self.range_label.setText(f"In {in_point}   Out {out_point}")
