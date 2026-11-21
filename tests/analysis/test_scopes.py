import numpy as np
import pytest

from proexr.analysis.scopes import histogram, pixel_report, vectorscope, waveform


def gradient(width: int = 64, height: int = 8) -> np.ndarray:
    ramp = np.linspace(0.0, 1.0, width, dtype=np.float32)
    return np.repeat(np.stack([ramp, ramp, ramp], axis=-1)[None], height, axis=0)


def test_histogram_counts_every_pixel_per_channel():
    counts = histogram(gradient(), bins=16)
    assert counts.shape == (4, 16)
    assert counts[0].sum() == 64 * 8
    assert counts[0, 0] == counts[0, -1] == 4 * 8


def test_waveform_places_brightness_by_column():
    trace = waveform(gradient(), columns=64, levels=64)
    assert trace.shape == (3, 64, 64)
    assert trace[0, :, 0].argmax() == 0
    assert trace[0, :, -1].argmax() == 63


def test_vectorscope_neutral_is_centered_and_red_is_off_center():
    grey = np.full((4, 4, 3), 0.5, np.float32)
    scope = vectorscope(grey, size=65)
    assert np.unravel_index(scope.argmax(), scope.shape) == (32, 32)
    red = np.zeros((4, 4, 3), np.float32)
    red[..., 0] = 1.0
    y, x = np.unravel_index(vectorscope(red, size=65).argmax(), (65, 65))
    assert x < 32 and y < 16


def test_pixel_report_gives_values_luminance_stops_and_area_average():
    pixels = np.zeros((10, 10, 3), np.float32)
    pixels[5, 5] = [0.18, 0.18, 0.18]
    report = pixel_report(pixels, 5, 5, ["R", "G", "B"], radius=1)
    assert report.values == pytest.approx([0.18, 0.18, 0.18])
    assert report.luminance == pytest.approx(0.18)
    assert report.stops == pytest.approx(0.0, abs=1e-6)
    assert report.area_average == pytest.approx([0.02, 0.02, 0.02], abs=1e-6)


def test_pixel_report_normalizes_integer_pixels():
    pixels = np.full((2, 2, 3), 255, np.uint8)
    report = pixel_report(pixels, 0, 0, ["R", "G", "B"])
    assert report.values == pytest.approx([1.0, 1.0, 1.0])
    assert report.raw == [255, 255, 255]
