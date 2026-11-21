import os
import re
from dataclasses import dataclass, field
from pathlib import Path

IMAGE_EXTENSIONS = frozenset({
    ".exr", ".sxr", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".tga", ".dpx", ".cin", ".hdr",
    ".rgbe", ".bmp", ".psd", ".webp", ".jp2", ".j2k", ".jxl", ".sgi", ".rgb", ".iff", ".ppm",
    ".pfm", ".dds",
})
VIDEO_EXTENSIONS = frozenset({
    ".mp4", ".mov", ".m4v", ".avi", ".mkv", ".mxf", ".webm", ".wmv", ".mpg", ".mpeg", ".ts",
    ".m2ts", ".mts", ".3gp", ".ogv", ".y4m", ".flv",
})
FRAME_PATTERN = re.compile(r"^(?P<prefix>.*?)(?P<digits>\d+)(?P<ext>\.[A-Za-z0-9]+)$")


def is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


def is_video(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTENSIONS


@dataclass
class ImageSequence:
    folder: Path
    prefix: str
    extension: str
    padding: int
    files: dict[int, str] = field(default_factory=dict)

    @property
    def frames(self) -> list[int]:
        return sorted(self.files)

    @property
    def first(self) -> int:
        return min(self.files)

    @property
    def last(self) -> int:
        return max(self.files)

    @property
    def missing(self) -> list[int]:
        return [f for f in range(self.first, self.last + 1) if f not in self.files]

    @property
    def is_numbered(self) -> bool:
        return bool(self.extension)

    @property
    def label(self) -> str:
        if not self.is_numbered:
            return self.files[self.first]
        return f"{self.prefix}{'#' * self.padding}{self.extension} [{self.first}-{self.last}]"

    def path_for(self, frame: int) -> Path | None:
        name = self.files.get(frame)
        return self.folder / name if name else None


def split_frame_number(name: str) -> tuple[str, int, int, str] | None:
    match = FRAME_PATTERN.match(name)
    if match is None:
        return None
    digits = match["digits"]
    return match["prefix"], int(digits), len(digits), match["ext"]


def _list_files(folder: Path) -> list[str]:
    try:
        with os.scandir(folder) as entries:
            return sorted(e.name for e in entries if e.is_file())
    except OSError:
        return []


def _group_images(folder: Path, names: list[str]) -> list[ImageSequence]:
    groups: dict[tuple[str, str], ImageSequence] = {}
    singles: list[ImageSequence] = []
    for name in names:
        if not is_image(Path(name)):
            continue
        parts = split_frame_number(name)
        if parts is None:
            singles.append(ImageSequence(folder, name, "", 0, {0: name}))
            continue
        prefix, frame, padding, extension = parts
        sequence = groups.setdefault((prefix, extension.lower()),
                                     ImageSequence(folder, prefix, extension, padding))
        sequence.files.setdefault(frame, name)
        sequence.padding = min(sequence.padding, padding)
    return list(groups.values()) + singles


def find_sequence(path: Path) -> ImageSequence:
    path = path.resolve()
    parts = split_frame_number(path.name)
    if parts is None:
        return ImageSequence(path.parent, path.name, "", 0, {0: path.name})
    prefix, _, _, extension = parts
    siblings = [n for n in _list_files(path.parent)
                if n.startswith(prefix) and n.lower().endswith(extension.lower())]
    for sequence in _group_images(path.parent, siblings):
        if sequence.prefix == prefix and sequence.is_numbered:
            return sequence
    return ImageSequence(path.parent, path.name, "", 0, {0: path.name})


def scan_folder(folder: Path) -> tuple[list[ImageSequence], list[Path]]:
    names = _list_files(folder)
    sequences = sorted(_group_images(folder, names), key=lambda s: s.label.lower())
    videos = [folder / n for n in names if is_video(Path(n))]
    return sequences, videos
