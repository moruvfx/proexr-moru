import numpy as np
import pytest

from proexr.color.ocio_pipeline import ColorManagement, apply_baked_lut
from proexr.errors import ColorConfigError


@pytest.fixture(scope="module")
def color() -> ColorManagement:
    return ColorManagement.load("ocio://default")


def test_builtin_config_lists_spaces_displays_and_views(color):
    assert "ACEScg" in color.colorspaces
    assert "Linear Rec.709 (sRGB)" in color.colorspaces
    assert "sRGB - Display" in color.displays
    assert any("ACES" in view for view in color.views("sRGB - Display"))


def test_default_input_spaces_follow_media_encoding(color):
    assert color.default_input("linear") == "Linear Rec.709 (sRGB)"
    assert color.default_input("srgb") == "sRGB Encoded Rec.709 (sRGB)"


def test_baked_lut_matches_ocio_processor(color):
    baked = color.bake("Linear Rec.709 (sRGB)", "sRGB - Display", "Un-tone-mapped")
    samples = np.array([[0.0, 0.0, 0.0], [0.18, 0.18, 0.18], [0.5, 0.2, 0.05], [1.0, 1.0, 1.0]], np.float32)
    expected = color.apply_exact("Linear Rec.709 (sRGB)", "sRGB - Display", "Un-tone-mapped", samples)
    np.testing.assert_allclose(apply_baked_lut(baked, samples), expected, atol=0.01)
    assert apply_baked_lut(baked, samples)[1, 0] == pytest.approx(0.461, abs=0.01)


def test_aces_view_tone_maps_highlights_below_one(color):
    baked = color.bake("ACEScg", "sRGB - Display", "ACES 2.0 - SDR 100 nits (Rec.709)")
    out = apply_baked_lut(baked, np.array([[16.0, 16.0, 16.0]], np.float32))
    assert 0.8 < out[0, 0] <= 1.0


def test_display_referred_input_uses_linear_shaper(color):
    baked = color.bake("sRGB Encoded Rec.709 (sRGB)", "sRGB - Display", "Un-tone-mapped")
    assert baked.shaper == "range"
    out = apply_baked_lut(baked, np.array([[0.5, 0.25, 0.75]], np.float32))
    np.testing.assert_allclose(out[0], [0.5, 0.25, 0.75], atol=0.01)


def test_missing_config_raises(tmp_path):
    with pytest.raises(ColorConfigError):
        ColorManagement.load(str(tmp_path / "nope.ocio"))
