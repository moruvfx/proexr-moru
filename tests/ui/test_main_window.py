import json
import time

import pytest
from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtTest import QTest
from ui_helpers import settle

from proexr.ui import shortcuts
from proexr.ui.main_window import MainWindow


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("PROEXR_CONFIG_DIR", str(tmp_path / "config"))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path / "settings"))
    win = MainWindow()
    win.resize(1200, 760)
    win.show()
    win.activateWindow()
    QTest.qWaitForWindowActive(win)
    settle(qapp)
    yield win
    win.close()


def wait_for(qapp, condition, timeout=5.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        qapp.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


def test_opening_sequence_shows_first_frame_and_layers(window, qapp, exr_sequence):
    window.open_paths([str(exr_sequence / "shot.1003.exr")])
    assert wait_for(qapp, lambda: window.viewer.frame is not None)
    assert window.viewer.frame.number == 1001
    assert window.layer_box.count() == 3
    assert window.timeline.first == 1001 and window.timeline.last == 1010


def test_opening_folder_adds_every_media_item(window, qapp, exr_sequence, video_file):
    (exr_sequence / "clip.mp4").write_bytes(video_file.read_bytes())
    window.open_paths([str(exr_sequence)])
    assert window.media_list.count() == 2


def test_space_key_plays_and_stops(window, qapp, exr_sequence):
    window.open_paths([str(exr_sequence)])
    assert wait_for(qapp, lambda: window.viewer.frame is not None)
    window.viewer.setFocus()
    QTest.keyClick(window.viewer, Qt.Key_Space)
    assert wait_for(qapp, lambda: window.viewer.frame.number > 1002)
    QTest.keyClick(window.viewer, Qt.Key_Space)
    assert not window.clock.is_playing


def test_arrow_keys_step_frames(window, qapp, exr_sequence):
    window.open_paths([str(exr_sequence)])
    assert wait_for(qapp, lambda: window.viewer.frame is not None)
    window.viewer.setFocus()
    QTest.keyClick(window.viewer, Qt.Key_Right)
    QTest.keyClick(window.viewer, Qt.Key_Right)
    assert wait_for(qapp, lambda: window.viewer.frame.number == 1003)
    QTest.keyClick(window.viewer, Qt.Key_Left)
    assert wait_for(qapp, lambda: window.viewer.frame.number == 1002)


def test_clicking_timeline_seeks(window, qapp, exr_sequence):
    window.open_paths([str(exr_sequence)])
    assert wait_for(qapp, lambda: window.viewer.frame is not None)
    timeline = window.timeline
    QTest.mouseClick(timeline, Qt.LeftButton, pos=QPoint(timeline.width() - 12, timeline.height() // 2))
    assert wait_for(qapp, lambda: window.viewer.frame.number == 1010)


def test_changing_layer_shows_that_layer(window, qapp, exr_sequence):
    window.open_paths([str(exr_sequence)])
    assert wait_for(qapp, lambda: window.viewer.frame is not None)
    window.layer_box.setCurrentIndex(2)
    assert wait_for(qapp, lambda: window.viewer.frame.pixels.shape[2] == 1)


def test_exposure_shortcut_changes_grade(window, qapp, exr_sequence):
    window.open_paths([str(exr_sequence)])
    window.viewer.setFocus()
    QTest.keyClick(window.viewer, Qt.Key_Up, Qt.ControlModifier)
    assert window.viewer.grade["exposure"] == pytest.approx(0.5)


def test_video_plays_through_cache(window, qapp, video_file):
    window.open_paths([str(video_file)])
    assert wait_for(qapp, lambda: window.viewer.frame is not None)
    window.play(1)
    assert wait_for(qapp, lambda: window.viewer.frame.number >= 10)
    window.clock.stop()


def test_user_shortcut_file_overrides_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("PROEXR_CONFIG_DIR", str(tmp_path))
    (tmp_path / "shortcuts.json").write_text(json.dumps({"toggle_play": ["P", "Space"]}))
    keys = shortcuts.load()
    assert keys["toggle_play"] == ["P", "Space"]
    assert keys["next_frame"] == ["Right"]


def test_ocio_view_bakes_lut_for_media_input(window, qapp, exr_sequence):
    window.open_paths([str(exr_sequence)])
    assert wait_for(qapp, lambda: window.viewer.frame is not None)
    window.view_box.setCurrentText("OCIO")
    assert window.ocio_panel.input_box.currentText() == "Linear Rec.709 (sRGB)"
    window.ocio_panel.view_box.setCurrentText("Un-tone-mapped")
    assert window.viewer.view_transform.name == "OCIO"
    assert window.viewer.display_lut is not None
    assert window.viewer.display_lut.shaper == "log"


def test_compare_wipe_shows_b_frame_aligned_to_a(window, qapp, exr_sequence, video_file):
    window.open_paths([str(exr_sequence), str(video_file)])
    a, b = window.media_list.sources()
    window.media_list.select_source(a)
    window.set_compare_source(b)
    window.compare_box.setCurrentText("Wipe")
    window.seek(1004)
    assert wait_for(qapp, lambda: window.viewer.compare_frame is not None and window.viewer.compare_frame.number == 3)
    assert window.viewer.compare_mode.name == "WIPE"
    assert "B" in window.media_list.item(1).text().split("\n")[0]


def test_compare_shortcut_cycles_b_source(window, qapp, exr_sequence, video_file):
    window.open_paths([str(exr_sequence), str(video_file)])
    window.viewer.setFocus()
    QTest.keyClick(window.viewer, Qt.Key_B, Qt.ControlModifier)
    assert window.compare_source is window.media_list.sources()[1]


def test_scopes_receive_display_samples(window, qapp, exr_sequence):
    window.open_paths([str(exr_sequence)])
    window.scopes_dock.show()
    window.scopes_dock.raise_()
    assert wait_for(qapp, lambda: window.scopes_panel.canvas.image is not None)
    window.scopes_panel.mode_box.setCurrentText("Histogram")
    assert window.scopes_panel.canvas.histogram is not None


def test_pixel_inspector_reports_hovered_pixel(window, qapp, exr_sequence):
    window.open_paths([str(exr_sequence)])
    assert wait_for(qapp, lambda: window.viewer.frame is not None)
    viewer = window.viewer
    QTest.mouseMove(viewer, QPoint(viewer.width() // 2, viewer.height() // 2))
    assert wait_for(qapp, lambda: "Luminance" in window.pixel_inspector.details.text())
    assert "R " in window.pixel_inspector.details.text()
