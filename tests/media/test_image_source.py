import numpy as np
import pytest

from conftest import HEIGHT, WIDTH, write_exr
from proexr.errors import MediaReadError
from proexr.media.image_source import ImageSequenceSource
from proexr.media.sequence import find_sequence


def test_sequence_metadata(exr_sequence):
    source = ImageSequenceSource(find_sequence(exr_sequence / "shot.1003.exr"))
    assert (source.first, source.last) == (1001, 1010)
    assert (source.width, source.height) == (WIDTH, HEIGHT)
    assert [l.name for l in source.layers] == ["RGBA", "diffuse", "Z"]
    assert source.colorspace == "linear"
    assert source.kind == "sequence"


def test_reads_main_layer_as_half_in_rgba_order(exr_sequence):
    source = ImageSequenceSource(find_sequence(exr_sequence / "shot.1001.exr"))
    frame = source.read(1002, layer=0)
    assert frame.pixels.dtype == np.float16
    assert frame.pixels.shape == (HEIGHT, WIDTH, 4)
    # channels on disk are A,B,G,R with values v, v+.1, v+.2, v+.3
    np.testing.assert_allclose(frame.pixels[0, 0], [0.5, 0.4, 0.3, 0.2], atol=1e-3)


def test_reads_aov_and_single_channel_layers(exr_sequence):
    source = ImageSequenceSource(find_sequence(exr_sequence / "shot.1001.exr"))
    diffuse = source.read(1001, layer=1)
    np.testing.assert_allclose(diffuse.pixels[0, 0], [0.7, 0.6, 0.5], atol=1e-3)
    depth = source.read(1001, layer=2)
    assert depth.pixels.shape == (HEIGHT, WIDTH, 1)


def test_missing_frame_holds_previous(exr_sequence):
    source = ImageSequenceSource(find_sequence(exr_sequence / "shot.1001.exr"))
    frame = source.read(1005)
    assert frame.is_held
    np.testing.assert_allclose(frame.pixels[0, 0, 3], 0.4, atol=1e-3)


def test_data_window_is_placed_inside_display_window(tmp_path):
    path = tmp_path / "crop.exr"
    write_exr(path, ("R", "G", "B"), 1.0, data_window=(10, 5, 20, 10))
    frame = ImageSequenceSource(find_sequence(path)).read(0)
    assert frame.pixels.shape == (HEIGHT, WIDTH, 3)
    assert frame.pixels[0, 0, 0] == 0
    assert frame.pixels[5, 10, 0] == pytest.approx(1.0, abs=1e-3)
    assert frame.pixels[14, 29, 0] == pytest.approx(1.0, abs=1e-3)
    assert frame.pixels[14, 30, 0] == 0


def test_eight_bit_png_stays_uint8_and_srgb(tmp_path):
    import OpenImageIO as oiio
    path = tmp_path / "logo.png"
    oiio.ImageBuf(np.full((4, 6, 3), 0.5, np.float32)).write(str(path), "uint8")
    source = ImageSequenceSource(find_sequence(path))
    frame = source.read(0)
    assert frame.pixels.dtype == np.uint8
    assert source.colorspace == "srgb"
    assert source.kind == "image"


def test_unreadable_file_raises_media_error(tmp_path):
    path = tmp_path / "broken.exr"
    path.write_bytes(b"not an exr")
    with pytest.raises(MediaReadError):
        ImageSequenceSource(find_sequence(path))


def test_source_files_are_not_modified(exr_sequence):
    before = {p.name: (p.stat().st_mtime_ns, p.stat().st_size) for p in exr_sequence.iterdir()}
    source = ImageSequenceSource(find_sequence(exr_sequence / "shot.1001.exr"))
    for f in range(source.first, source.last + 1):
        source.read(f, layer=1)
    after = {p.name: (p.stat().st_mtime_ns, p.stat().st_size) for p in exr_sequence.iterdir()}
    assert before == after
