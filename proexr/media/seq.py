"""Image sequence detection.

Recognises numbered frames such as ``shot.0001.exr``, ``shot_0001.exr``,
``shot0001.exr`` and ``shot.1.exr``.  Only reads directory listings, never
touches file contents.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

IMAGE_EXTS = {
    ".exr", ".sxr", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".tga", ".dpx",
    ".cin", ".hdr", ".rgbe", ".bmp", ".psd", ".webp", ".jp2", ".j2k", ".jxl",
    ".sgi", ".rgb", ".iff", ".ppm", ".pgm", ".pfm", ".gif", ".dds", ".ico",
}
VIDEO_EXTS = {
    ".mp4", ".mov", ".m4v", ".avi", ".mkv", ".mxf", ".webm", ".wmv", ".flv",
    ".mpg", ".mpeg", ".ts", ".m2ts", ".mts", ".3gp", ".ogv", ".y4m",
}

# prefix, frame digits, extension (digits are the LAST number before the ext)
_FRAME_RE = re.compile(r"^(?P<prefix>.*?)(?P<frame>-?\d+)(?P<ext>\.[A-Za-z0-9]+)$")


def is_image(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in IMAGE_EXTS


def is_video(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in VIDEO_EXTS


def is_media(path: str) -> bool:
    return is_image(path) or is_video(path)


@dataclass
class Sequence:
    directory: str
    prefix: str
    ext: str
    padding: int
    frames: list[int] = field(default_factory=list)
    files: dict[int, str] = field(default_factory=dict)

    @property
    def first(self) -> int:
        return self.frames[0]

    @property
    def last(self) -> int:
        return self.frames[-1]

    @property
    def missing(self) -> list[int]:
        have = set(self.frames)
        return [f for f in range(self.first, self.last + 1) if f not in have]

    def path(self, frame: int) -> str | None:
        name = self.files.get(frame)
        return os.path.join(self.directory, name) if name else None

    @property
    def display_name(self) -> str:
        pad = "#" * self.padding if self.padding > 1 else "#"
        if len(self.frames) == 1:
            return self.files[self.frames[0]]
        return f"{self.prefix}{pad}{self.ext}  [{self.first}-{self.last}]"


def split_frame(name: str):
    """Return (prefix, frame:int, padding, ext) or None."""
    m = _FRAME_RE.match(name)
    if not m:
        return None
    digits = m.group("frame")
    prefix = m.group("prefix")
    # "shot-0001" -> treat '-' as separator, not a negative sign
    if digits.startswith("-"):
        if prefix and prefix[-1].isalnum():
            prefix += "-"
            digits = digits[1:]
    sign = -1 if digits.startswith("-") else 1
    core = digits.lstrip("-")
    pad = len(core) if core.startswith("0") and len(core) > 1 else len(core)
    return prefix, sign * int(core), pad, m.group("ext")


def _group(directory: str, names: list[str]) -> list[Sequence]:
    groups: dict[tuple, Sequence] = {}
    singles: list[Sequence] = []
    for name in sorted(names):
        if not is_image(name):
            continue
        parts = split_frame(name)
        if parts is None:
            singles.append(Sequence(directory, name, "", 0, [0], {0: name}))
            continue
        prefix, frame, pad, ext = parts
        key = (prefix, ext.lower())
        seq = groups.get(key)
        if seq is None:
            seq = groups[key] = Sequence(directory, prefix, ext, pad)
        if frame not in seq.files:
            seq.files[frame] = name
            seq.frames.append(frame)
            seq.padding = min(seq.padding, pad) if seq.padding else pad
    out = []
    for seq in groups.values():
        seq.frames.sort()
        out.append(seq)
    out.extend(singles)
    out.sort(key=lambda s: s.display_name.lower())
    return out


def _listdir(directory: str) -> list[str]:
    try:
        with os.scandir(directory) as it:
            return [e.name for e in it if e.is_file()]
    except OSError:
        return []


def sequence_for_file(path: str) -> Sequence:
    """Find the sequence a single image file belongs to (may be length 1)."""
    directory, name = os.path.split(os.path.abspath(path))
    parts = split_frame(name)
    if parts is None:
        return Sequence(directory, name, "", 0, [0], {0: name})
    prefix, _, _, ext = parts
    candidates = [n for n in _listdir(directory)
                  if n.startswith(prefix) and n.lower().endswith(ext.lower())]
    for seq in _group(directory, candidates):
        if seq.prefix == prefix and seq.ext.lower() == ext.lower():
            return seq
    return Sequence(directory, name, "", 0, [0], {0: name})


def scan_directory(directory: str, recursive: bool = False):
    """Return (sequences, video_paths) found in a directory."""
    sequences: list[Sequence] = []
    videos: list[str] = []
    walker = os.walk(directory) if recursive else [(directory, [], _listdir(directory))]
    for root, _dirs, files in walker:
        sequences.extend(_group(root, files))
        videos.extend(os.path.join(root, f) for f in sorted(files) if is_video(f))
    return sequences, videos
