from pathlib import Path

from ..errors import UnsupportedMediaError
from .frame import MediaSource
from .image_source import ImageSequenceSource
from .sequence import find_sequence, is_image, is_video, scan_folder
from .video_source import VideoSource


def open_media(path: Path, hardware_decode: bool = True) -> list[MediaSource]:
    path = Path(path).resolve()
    if path.is_dir():
        sequences, videos = scan_folder(path)
        return [ImageSequenceSource(s) for s in sequences] + [VideoSource(v, hardware_decode) for v in videos]
    if is_video(path):
        return [VideoSource(path, hardware_decode)]
    if is_image(path):
        return [ImageSequenceSource(find_sequence(path))]
    raise UnsupportedMediaError(f"Unsupported file type: {path.name}")
