import json
import os
from pathlib import Path

from PySide6.QtCore import QStandardPaths

DEFAULT_SHORTCUTS: dict[str, tuple[str, str]] = {
    "open_file": ("Ctrl+O", "Open file..."),
    "open_folder": ("Ctrl+Shift+O", "Open folder..."),
    "close_media": ("Ctrl+W", "Close media"),
    "quit": ("Ctrl+Q", "Quit"),
    "toggle_play": ("Space", "Play / pause"),
    "play_forward": ("L", "Play forward"),
    "play_reverse": ("J", "Play reverse"),
    "stop": ("K", "Stop"),
    "next_frame": ("Right", "Next frame"),
    "previous_frame": ("Left", "Previous frame"),
    "forward_ten": ("Shift+Right", "Forward 10 frames"),
    "back_ten": ("Shift+Left", "Back 10 frames"),
    "go_to_start": ("Home", "Go to in point"),
    "go_to_end": ("End", "Go to out point"),
    "set_in": ("I", "Set in point"),
    "set_out": ("O", "Set out point"),
    "clear_in_out": ("Alt+X", "Clear in/out"),
    "cycle_loop": ("Ctrl+L", "Cycle loop mode"),
    "faster": ("]", "Faster"),
    "slower": ("[", "Slower"),
    "cycle_compare_source": ("Ctrl+B", "Compare: set next media as B"),
    "toggle_compare": ("\\", "Compare on / off"),
    "next_media": ("PgDown", "Next media"),
    "previous_media": ("PgUp", "Previous media"),
    "fit": ("F", "Fit to window"),
    "actual_pixels": ("1", "100% (1:1 pixels)"),
    "zoom_in": ("=", "Zoom in"),
    "zoom_out": ("-", "Zoom out"),
    "fullscreen": ("F11", "Full screen"),
    "hide_panels": ("Tab", "Hide / show panels"),
    "safe_areas": ("Shift+S", "Safe areas"),
    "thirds": ("Shift+G", "Rule-of-thirds grid"),
    "clipping": ("Shift+C", "Highlight clipped pixels"),
    "channel_rgb": ("C", "Channel: RGB"),
    "channel_red": ("R", "Channel: red"),
    "channel_green": ("G", "Channel: green"),
    "channel_blue": ("B", "Channel: blue"),
    "channel_alpha": ("A", "Channel: alpha"),
    "channel_luminance": ("Y", "Channel: luminance"),
    "exposure_up": ("Ctrl+Up", "Exposure +1/2 stop"),
    "exposure_down": ("Ctrl+Down", "Exposure -1/2 stop"),
    "reset_grade": ("Ctrl+0", "Reset colour adjustments"),
    "next_layer": ("Ctrl+Right", "Next layer"),
    "previous_layer": ("Ctrl+Left", "Previous layer"),
}


def config_dir() -> Path:
    """Folder for user settings files; PROEXR_CONFIG_DIR overrides the OS default."""
    folder = Path(os.environ.get("PROEXR_CONFIG_DIR") or
                  QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation) or Path.home() / ".proexr")
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def shortcuts_path() -> Path:
    """Path of the user's shortcuts.json; created with the defaults on first load."""
    return config_dir() / "shortcuts.json"


def load() -> dict[str, list[str]]:
    """Returns action id -> key sequences, defaults merged with the user's shortcuts.json."""
    keys = {action: [default] for action, (default, _) in DEFAULT_SHORTCUTS.items()}
    path = shortcuts_path()
    if not path.exists():
        path.write_text(json.dumps({a: k[0] for a, k in keys.items()}, indent=2), encoding="utf-8")
        return keys
    try:
        overrides = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return keys
    for action, value in overrides.items():
        if action in keys:
            keys[action] = value if isinstance(value, list) else [value]
    return keys
