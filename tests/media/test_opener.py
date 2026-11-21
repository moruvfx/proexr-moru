import pytest

from proexr.errors import UnsupportedMediaError
from proexr.media.opener import open_media


def test_opens_file_folder_and_video(exr_sequence, video_file):
    assert [s.kind for s in open_media(exr_sequence / "shot.1001.exr")] == ["sequence"]
    assert [s.kind for s in open_media(video_file, hardware_decode=False)] == ["video"]
    (exr_sequence / "clip.mp4").write_bytes(video_file.read_bytes())
    assert sorted(s.kind for s in open_media(exr_sequence, hardware_decode=False)) == ["sequence", "video"]


def test_rejects_unknown_files(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("hi")
    with pytest.raises(UnsupportedMediaError):
        open_media(path)
