import numpy as np
import pytest
from ui_helpers import settle

from proexr.media.frame import Frame
from proexr.ui.viewer import Channel, CompareMode, Viewer, ViewTransform


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


def test_ocio_lut_view_matches_baked_transform(viewer, qapp):
    from proexr.color.ocio_pipeline import ColorManagement
    color = ColorManagement.load("ocio://default")
    viewer.set_display_lut(color.bake("Linear Rec.709 (sRGB)", "sRGB - Display", "Un-tone-mapped"))
    viewer.view_transform = ViewTransform.OCIO
    viewer.show_frame(solid([0.18, 0.18, 0.18, 1.0]))
    assert center(viewer, qapp) == pytest.approx((118, 118, 118), abs=2)


def test_ocio_view_keeps_display_referred_source_unchanged(viewer, qapp):
    from proexr.color.ocio_pipeline import ColorManagement
    color = ColorManagement.load("ocio://default")
    viewer.set_display_lut(color.bake("sRGB Encoded Rec.709 (sRGB)", "sRGB - Display", "Un-tone-mapped"))
    viewer.view_transform = ViewTransform.OCIO
    viewer.show_frame(solid([200, 100, 30], np.uint8, "srgb", 3))
    assert center(viewer, qapp) == pytest.approx((200, 100, 30), abs=3)


def pixel_at(viewer, qapp, fx: float, fy: float = 0.5) -> tuple[int, int, int]:
    settle(qapp)
    image = viewer.grabFramebuffer()
    color = image.pixelColor(int(image.width() * fx), int(image.height() * fy))
    return color.red(), color.green(), color.blue()


def show_pair(viewer):
    viewer.view_transform = ViewTransform.RAW
    viewer.show_frame(solid([1.0, 0.0, 0.0, 1.0]))
    viewer.show_compare_frame(solid([0.0, 0.0, 1.0, 1.0]))


def test_wipe_shows_a_left_and_b_right(viewer, qapp):
    show_pair(viewer)
    viewer.compare_mode = CompareMode.WIPE
    viewer.wipe_position = 0.5
    assert pixel_at(viewer, qapp, 0.4) == pytest.approx((255, 0, 0), abs=2)
    assert pixel_at(viewer, qapp, 0.6) == pytest.approx((0, 0, 255), abs=2)


def test_b_only_and_difference(viewer, qapp):
    show_pair(viewer)
    viewer.compare_mode = CompareMode.B_ONLY
    assert center(viewer, qapp) == pytest.approx((0, 0, 255), abs=2)
    viewer.compare_mode = CompareMode.DIFFERENCE
    assert center(viewer, qapp) == pytest.approx((255, 0, 255), abs=2)


def test_side_by_side_splits_the_view(viewer, qapp):
    show_pair(viewer)
    viewer.compare_mode = CompareMode.SIDE_BY_SIDE
    assert pixel_at(viewer, qapp, 0.25) == pytest.approx((255, 0, 0), abs=2)
    assert pixel_at(viewer, qapp, 0.75) == pytest.approx((0, 0, 255), abs=2)


def test_compare_off_ignores_b(viewer, qapp):
    show_pair(viewer)
    viewer.compare_mode = CompareMode.OFF
    assert pixel_at(viewer, qapp, 0.6) == pytest.approx((255, 0, 0), abs=2)


def test_display_sample_matches_what_is_shown(viewer, qapp):
    samples = []
    viewer.displaySampled.connect(samples.append)
    viewer.show_frame(solid([0.18, 0.18, 0.18, 1.0]))
    viewer.request_display_sample(64)
    settle(qapp)
    viewer.repaint()
    settle(qapp)
    assert samples, "no sample emitted"
    sample = samples[-1]
    assert sample.shape[1] == 64 and sample.shape[2] == 3
    assert sample.shape[0] == pytest.approx(64 * 40 / 60, abs=1)
    assert sample[5, 5] == pytest.approx((118, 118, 118), abs=2)


def test_gl_state_is_reset_for_qpainter_text(viewer, qapp):
    from OpenGL import GL
    viewer.show_frame(solid([0.5, 0.5, 0.5], channels=3))
    settle(qapp)
    viewer.grabFramebuffer()
    viewer.makeCurrent()
    try:
        assert GL.glGetIntegerv(GL.GL_UNPACK_ALIGNMENT) == 4
        assert GL.glGetIntegerv(GL.GL_ACTIVE_TEXTURE) == GL.GL_TEXTURE0
    finally:
        viewer.doneCurrent()


@pytest.mark.parametrize("layout", ["yuv420p", "nv12"])
def test_planar_video_frame_is_converted_on_gpu(viewer, qapp, layout):
    import av
    color = (200, 40, 90)
    source = av.VideoFrame.from_ndarray(np.full((40, 60, 3), color, np.uint8), format="rgb24")
    pixels = source.reformat(format=layout).to_ndarray()
    viewer.view_transform = ViewTransform.SRGB
    viewer.show_frame(Frame(pixels, "srgb", 0, layout=layout, yuv_matrix="bt601"))
    assert center(viewer, qapp) == pytest.approx(color, abs=4)
