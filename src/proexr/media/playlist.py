import json
from pathlib import Path

from ..errors import PlaylistError

PLAYLIST_VERSION = 1
PLAYLIST_SUFFIX = ".proexr.json"


def save_playlist(path: Path, media: list[Path]) -> None:
    """Write the media paths as JSON; paths inside the playlist's folder are stored relative to it."""
    folder = Path(path).resolve().parent
    entries = []
    for item in media:
        item = Path(item).resolve()
        entries.append(item.relative_to(folder).as_posix() if item.is_relative_to(folder) else str(item))
    try:
        Path(path).write_text(json.dumps({"version": PLAYLIST_VERSION, "media": entries}, indent=2), "utf-8")
    except OSError as error:
        raise PlaylistError(f"Cannot save playlist {path}: {error}") from error


def load_playlist(path: Path) -> list[Path]:
    try:
        data = json.loads(Path(path).read_text("utf-8"))
        entries = data["media"]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise PlaylistError(f"Cannot read playlist {path}: {error}") from error
    folder = Path(path).resolve().parent
    return [(folder / entry).resolve() for entry in entries if isinstance(entry, str)]
