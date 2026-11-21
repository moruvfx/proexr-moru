import numpy as np

from proexr.media.video_source import VideoSource


def red_level(frame) -> int:
    return int(frame.rgb_region(32, 24, 33, 25)[0, 0, 0])


def test_video_metadata(video_file):
    source = VideoSource(video_file, hardware_decode=False)
    assert source.fps == 25
    assert (source.first, source.last) == (0, 49)
    assert (source.width, source.height) == (64, 48)
    assert source.colorspace == "srgb"
    assert source.parallel_reads is False


def test_sequential_frames_are_correct(video_file):
    source = VideoSource(video_file, hardware_decode=False)
    levels = [red_level(source.read(i)) for i in range(10)]
    assert all(abs(level - i * 5) <= 3 for i, level in enumerate(levels))


def test_random_access_seeks_backwards_and_forwards(video_file):
    source = VideoSource(video_file, hardware_decode=False)
    for i in (40, 3, 27, 49, 0, 15):
        frame = source.read(i)
        assert frame.pixels.dtype == np.uint8
        assert abs(red_level(frame) - i * 5) <= 3, i


def test_out_of_range_frames_clamp(video_file):
    source = VideoSource(video_file, hardware_decode=False)
    assert abs(red_level(source.read(500)) - 49 * 5) <= 3


def test_hardware_decode_falls_back_to_software(video_file):
    source = VideoSource(video_file, hardware_decode=True)
    assert abs(red_level(source.read(12)) - 60) <= 3


def test_reading_after_close_raises_instead_of_crashing(video_file):
    import pytest

    from proexr.errors import MediaReadError
    from proexr.media.video_source import VideoSource

    source = VideoSource(video_file, hardware_decode=False)
    source.read(3)
    source.close()
    with pytest.raises(MediaReadError):
        source.read(4)


def test_8bit_420_video_stays_planar(video_file):
    frame = VideoSource(video_file, hardware_decode=False).read(5)
    assert frame.layout == "yuv420p" and frame.pixels.shape == (72, 64)
    assert (frame.width, frame.height) == (64, 48)


def test_planar_output_can_be_turned_off(video_file):
    source = VideoSource(video_file, hardware_decode=False)
    source.planar_output = False
    frame = source.read(5)
    assert frame.layout == "rgb" and frame.pixels.shape == (48, 64, 3)
