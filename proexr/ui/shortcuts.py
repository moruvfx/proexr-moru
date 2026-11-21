"""Keyboard shortcuts with user overrides from a JSON file.

Edit ``shortcuts.json`` in the settings folder (Help > Edit shortcuts) and
restart; any action id below can be remapped, e.g. ``{"play_forward": "L"}``.
Use a list for several keys: ``{"toggle_play": ["Space", "K"]}``.
"""
from __future__ import annotations

import json
import os

from PySide6.QtCore import QStandardPaths

DEFAULTS = {
    # file
    "open_file": ("Ctrl+O", "Open file..."),
    "open_folder": ("Ctrl+Shift+O", "Open folder..."),
    "close_media": ("Ctrl+W", "Close current media"),
    "quit": ("Ctrl+Q", "Quit"),
    # playback
    "toggle_play": ("Space", "Play / pause"),
    "play_forward": ("L", "Play forward"),
    "play_reverse": ("J", "Play reverse"),
    "stop": ("K", "Stop"),
    "next_frame": ("Right", "Next frame"),
    "prev_frame": ("Left", "Previous frame"),
    "next_10": ("Shift+Right", "Forward 10 frames"),
    "prev_10": ("Shift+Left", "Back 10 frames"),
    "first_frame": ("Home", "Go to first frame"),
    "last_frame": ("End", "Go to last frame"),
    "set_in": ("I", "Set in point"),
    "set_out": ("O", "Set out point"),
    "clear_in_out": ("Alt+X", "Clear in/out"),
    "cycle_loop": ("Ctrl+L", "Cycle loop mode"),
    "speed_up": ("]", "Faster"),
    "speed_down": ("[", "Slower"),
    "next_media": ("PgDown", "Next media in playlist"),
    "prev_media": ("PgUp", "Previous media in playlist"),
    # view
    "fit": ("F", "Fit to window"),
    "actual": ("1", "100% (1:1 pixels)"),
    "zoom_in": ("=", "Zoom in"),
    "zoom_out": ("-", "Zoom out"),
    "fullscreen": ("F11", "Full screen"),
    "viewer_only": ("Tab", "Hide/show panels"),
    "safe_areas": ("Shift+S", "Safe areas"),
    "grid": ("Shift+G", "Rule-of-thirds grid"),
    "clipping": ("Shift+C", "Show clipped pixels"),
    # color
    "ch_rgb": ("C", "Channel: RGB"),
    "ch_r": ("R", "Channel: red"),
    "ch_g": ("G", "Channel: green"),
    "ch_b": ("B", "Channel: blue"),
    "ch_a": ("A", "Channel: alpha"),
    "ch_l": ("Y", "Channel: luminance"),
    "exp_up": ("Ctrl+Up", "Exposure +1/2 stop"),
    "exp_down": ("Ctrl+Down", "Exposure -1/2 stop"),
    "reset_color": ("Ctrl+0", "Reset colour adjustments"),
    "next_layer": ("Ctrl+Right", "Next EXR layer"),
    "prev_layer": ("Ctrl+Left", "Previous EXR layer"),
}


def config_dir() -> str:
    d = QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation) or os.path.expanduser("~/.proexr")
    os.makedirs(d, exist_ok=True)
    return d


def shortcuts_path() -> str:
    return os.path.join(config_dir(), "shortcuts.json")


def load() -> dict[str, list[str]]:
    keys = {k: [v[0]] for k, v in DEFAULTS.items()}
    path = shortcuts_path()
    if not os.path.exists(path):
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({k: v[0] for k, v in DEFAULTS.items()}, fh, indent=2)
        except OSError:
            pass
        return keys
    try:
        with open(path, encoding="utf-8") as fh:
            user = json.load(fh)
        for k, v in user.items():
            if k in keys:
                keys[k] = v if isinstance(v, list) else [v]
    except (OSError, ValueError):
        pass
    return keys
