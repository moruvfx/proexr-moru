from pathlib import Path

from proexr.media.sequence import find_sequence, scan_folder, split_frame_number


def touch(folder: Path, *names: str) -> None:
    for name in names:
        (folder / name).write_bytes(b"")


def test_split_frame_number_handles_common_patterns():
    assert split_frame_number("shot.1001.exr") == ("shot.", 1001, 4, ".exr")
    assert split_frame_number("plate_0007.dpx") == ("plate_", 7, 4, ".dpx")
    assert split_frame_number("render12.png") == ("render", 12, 2, ".png")
    assert split_frame_number("comp-v2-0010.tif") == ("comp-v2-", 10, 4, ".tif")
    assert split_frame_number("still.jpg") is None


def test_find_sequence_collects_siblings_and_gaps(tmp_path):
    touch(tmp_path, "shot.1001.exr", "shot.1002.exr", "shot.1004.exr", "other.1001.exr", "shot.1003.png")
    seq = find_sequence(tmp_path / "shot.1002.exr")
    assert seq.frames == [1001, 1002, 1004]
    assert seq.missing == [1003]
    assert seq.path_for(1004) == tmp_path / "shot.1004.exr"
    assert seq.path_for(1003) is None
    assert seq.label == "shot.####.exr [1001-1004]"


def test_find_sequence_for_unnumbered_file_is_single_frame(tmp_path):
    touch(tmp_path, "still.jpg")
    seq = find_sequence(tmp_path / "still.jpg")
    assert seq.frames == [0]
    assert seq.path_for(0) == tmp_path / "still.jpg"
    assert seq.label == "still.jpg"


def test_scan_folder_separates_sequences_and_videos(tmp_path):
    touch(tmp_path, "a.0001.exr", "a.0002.exr", "b_01.png", "b_02.png", "clip.mov", "notes.txt", "logo.png")
    sequences, videos = scan_folder(tmp_path)
    assert sorted(s.label for s in sequences) == ["a.####.exr [1-2]", "b_##.png [1-2]", "logo.png"]
    assert videos == [tmp_path / "clip.mov"]
