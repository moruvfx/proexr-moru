import numpy as np
from conftest import write_exr

from proexr.media.image_source import ImageSequenceSource
from proexr.media.sequence import find_sequence


def test_float_color_layers_are_stored_as_half_but_depth_stays_float(tmp_path):
    path = tmp_path / "deep.exr"
    write_exr(path, ("B", "G", "R", "Z"), 0.25, pixel_type="float")
    source = ImageSequenceSource(find_sequence(path))
    assert source.read(0, layer=0).pixels.dtype == np.float16
    assert source.read(0, layer=1).pixels.dtype == np.float32
