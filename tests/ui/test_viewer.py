import numpy as np
import pytest
from ui_helpers import settle

from proexr.media.frame import Frame
from proexr.ui.viewer import Channel, Viewer, ViewTransform


@pytest.fixture
def viewer(qapp):
    widget = Viewer()
    widget.resize(400, 240)
    widget.show()
    settle(qapp)
    yield widget
    widget.close()


def solid(value, dtype=np.float16, colorspace="linear", channels=4) -> Frame:
    pixels = np.empty((40, 60, channels), dtype)
    pixels[:] = value
    return Frame(pixels, colorspace, 0)


def center(viewer, qapp) -> tuple[int, int, int]:
    settle(qapp)
    image = viewer.grabFramebuffer()
    color = image.pixelColor(image.width() // 2, image.height() // 2)
    return color.red(), color.green(), color.blue()


def test_linear_mid_grey_is_shown_through_srgb(viewer, qapp):
    viewer.show_frame(solid([0.18, 0.18, 0.18, 1.0]))
    assert center(viewer, qapp) == pytest.approx((118, 118, 118), abs=2)


def test_exposure_plus_one_stop_doubles_linear_light(viewer, qapp):
    viewer.show_frame(solid([0.18, 0.18, 0.18, 1.0]))
    viewer.set_grade(exposure=1.0)
    assert center(viewer, qapp) == pytest.approx((161, 161, 161), abs=2)


def test_raw_view_shows_values_untransformed(viewer, qapp):
    viewer.view_transform = ViewTransform.RAW
    viewer.show_frame(solid([0.5, 0.25, 1.0, 1.0]))
    assert center(viewer, qapp) == pytest.approx((128, 64, 255), abs=2)


def test_red_channel_isolation_shows_grey(viewer, qapp):
    viewer.view_transform = ViewTransform.RAW
    viewer.channel = Channel.RED
    viewer.show_frame(solid([0.5, 0.1, 0.9, 1.0]))
    assert center(viewer, qapp) == pytest.approx((128, 128, 128), abs=2)


def test_alpha_channel_view(viewer, qapp):
    viewer.view_transform = ViewTransform.RAW
    viewer.channel = Channel.ALPHA
    viewer.show_frame(solid([0.9, 0.9, 0.9, 0.25]))
    assert center(viewer, qapp) == pytest.approx((64, 64, 64), abs=2)


def test_srgb_8bit_source_round_trips_unchanged(viewer, qapp):
    viewer.show_frame(solid([200, 100, 30], np.uint8, "srgb", 3))
    assert center(viewer, qapp) == pytest.approx((200, 100, 30), abs=2)


def test_single_channel_layer_is_grey(viewer, qapp):
    viewer.view_transform = ViewTransform.RAW
    viewer.show_frame(solid([0.5], np.float32, "linear", 1))
    assert center(viewer, qapp) == pytest.approx((128, 128, 128), abs=2)


def test_fit_and_actual_pixels_zoom(viewer, qapp):
    viewer.show_frame(solid([0.1, 0.1, 0.1, 1.0]))
    viewer.fit()
    assert viewer.zoom == pytest.approx(min(400 / 60, 240 / 40) * 0.98, rel=1e-3)
    viewer.show_actual_pixels()
    assert viewer.zoom * viewer.devicePixelRatioF() == pytest.approx(1.0)


def test_widget_to_image_maps_center(viewer, qapp):
    viewer.show_frame(solid([0.1, 0.1, 0.1, 1.0]))
    viewer.fit()
    from PySide6.QtCore import QPointF
    x, y = viewer.widget_to_image(QPointF(200, 120))
    assert (x, y) == pytest.approx((30, 20), abs=0.5)
