"""Analysis ROI and intensity profile: raw-pixel numbers, view mapping, and no device traffic."""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from thermo_acoustic.application import ApplicationController
from thermo_acoustic.application.image_analysis import (
    clamp_rect, column_profile, move_rect, rect_from_points, roi_statistics, row_profile,
)
from thermo_acoustic.domain.models import DeviceId, OperatingMode
from thermo_acoustic.hal.registry import DeviceRegistry
from thermo_acoustic.ui.main_window import MainWindow
from thermo_acoustic.ui.widgets import CameraImageWindow
from thermo_acoustic.ui.saved_frames_window import SavedFramesWindow


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication(["test-image-tools"])


def ramp(rows=40, columns=60) -> np.ndarray:
    return (np.arange(rows)[:, None] * 1000 + np.arange(columns)[None, :]).astype(np.uint16)


@pytest.mark.parametrize("viewer_type", [CameraImageWindow, SavedFramesWindow])
def test_display_mode_and_auto_once_keep_fields_in_sync(qt_app, viewer_type):
    window = viewer_type()
    try:
        window.show()
        window.set_measurement_visible(False)
        qt_app.processEvents()
        assert window.display_range_controls.isVisible()
        assert not window.side_panel.isVisible()
        assert not window.adjust_intensity_button.isEnabled()
        window.display_mode.setCurrentIndex(window.display_mode.findData("auto"))
        first = np.array([[100, 200], [300, 400]], dtype=np.uint16)
        original = first.copy()
        window.show_frame(first, "first")
        assert window.preview.display_limits == (100, 400)
        assert (window.limit_low.value(), window.limit_high.value()) == (100, 400)
        assert window.limit_low.isReadOnly() and window.limit_high.isReadOnly()
        second = np.array([[1000, 1100], [1200, 1300]], dtype=np.uint16)
        window.show_frame(second, "second")
        assert (window.limit_low.value(), window.limit_high.value()) == (1000, 1300)
        window.adjust_intensity_button.click()
        assert window.display_mode.currentData() == "manual"
        assert not window.limit_low.isReadOnly() and not window.limit_high.isReadOnly()
        window.show_frame(first, "first again")
        assert window.preview.display_limits == (1000, 1300)
        assert (window.limit_low.value(), window.limit_high.value()) == (1000, 1300)
        window.limit_low.setValue(50)
        window.limit_high.setValue(500)
        window.limit_high.editingFinished.emit()
        assert window.preview.display_limits == (50, 500)
        window.limit_high.setValue(450)
        window.limit_high.setFocus()
        QTest.keyClick(window.limit_high, Qt.Key.Key_Return)
        assert window.preview.display_limits == (50, 450)
        assert window.isVisible()
        window.show_frame(second, "manual remains fixed")
        assert window.preview.display_limits == (50, 450)
        window.limit_low.setValue(600)
        window.limit_low.editingFinished.emit()
        assert window.preview.display_limits == (50, 450)
        assert (window.limit_low.value(), window.limit_high.value()) == (50, 450)
        assert np.array_equal(first, original)
    finally:
        window.close()


# ------------------------------------------------------------------ pure numbers
def test_roi_statistics_use_raw_pixels_and_clamp_to_the_frame():
    frame = ramp()
    stats = roi_statistics(frame, (10, 5, 4, 3))
    region = frame[5:8, 10:14].astype(np.float64)
    assert stats.rect == (10, 5, 4, 3) and stats.pixel_count == 12
    assert stats.mean == pytest.approx(region.mean()) and stats.std == pytest.approx(region.std())
    assert (stats.minimum, stats.maximum) == (5010, 7013)
    # A rectangle running past the edge is cut to the frame, not wrapped or padded.
    edge = roi_statistics(frame, (58, 38, 10, 10))
    assert edge.rect == (58, 38, 2, 2) and edge.pixel_count == 4
    assert roi_statistics(frame, (100, 100, 5, 5)) is None
    assert roi_statistics(np.zeros((0, 0), np.uint16), (0, 0, 1, 1)) is None


def test_roi_statistics_do_not_depend_on_display_range_or_modify_the_frame():
    frame = ramp()
    before = frame.copy()
    first = roi_statistics(frame, (0, 0, 60, 40))
    assert roi_statistics(frame, (0, 0, 60, 40)) == first
    assert np.array_equal(frame, before)
    assert first.minimum == 0 and first.maximum == 39059  # whole range, whatever a stretch would show


def test_rect_from_points_covers_every_touched_pixel_and_stays_inside():
    shape = (40, 60)
    assert rect_from_points((10.5, 5.5), (29.5, 14.5), shape) == (10, 5, 20, 10)
    assert rect_from_points((29.5, 14.5), (10.5, 5.5), shape) == (10, 5, 20, 10)  # any drag direction
    assert rect_from_points((-20, -20), (500, 500), shape) == (0, 0, 60, 40)
    assert rect_from_points((10.2, 10.2), (10.2, 10.2), shape) == (10, 10, 1, 1)  # touches one pixel
    assert rect_from_points((10.0, 10.0), (10.0, 20.0), shape) is None  # no width
    assert rect_from_points((float("nan"), 0), (5, 5), shape) is None


def test_move_rect_keeps_size_and_stays_inside_the_image():
    assert move_rect((10, 10, 20, 10), 5, -3, (40, 60)) == (15, 7, 20, 10)
    assert move_rect((10, 10, 20, 10), 100, 100, (40, 60)) == (40, 30, 20, 10)
    assert move_rect((10, 10, 20, 10), -100, -100, (40, 60)) == (0, 0, 20, 10)
    assert clamp_rect((0, 0, 5, 5), (40, 60)) == (0, 0, 5, 5)


def test_profiles_return_the_requested_row_or_column_of_raw_values():
    frame = ramp()
    assert np.array_equal(row_profile(frame, 7), frame[7, :]) and len(row_profile(frame, 7)) == 60
    assert np.array_equal(column_profile(frame, 12), frame[:, 12]) and len(column_profile(frame, 12)) == 40
    assert row_profile(frame, 40) is None and row_profile(frame, -1) is None
    assert column_profile(frame, 60) is None
    assert row_profile(None, 0) is None


# -------------------------------------------------------------- mapping in the viewer
def widget_point(preview, x: float, y: float) -> QPoint:
    """Widget position of image position (x, y) at the preview's current zoom and pan."""
    source, target = preview._view_geometry()
    scale = preview.effective_scale()
    return QPoint(round(target.x() + (x - source.x()) * scale), round(target.y() + (y - source.y()) * scale))


def drag(preview, start: QPoint, end: QPoint) -> None:
    left = Qt.MouseButton.LeftButton
    QTest.mousePress(preview, left, Qt.KeyboardModifier.NoModifier, start)
    QTest.mouseMove(preview, end)
    QTest.mouseRelease(preview, left, Qt.KeyboardModifier.NoModifier, end)


def viewer(qt_app, frame=None) -> CameraImageWindow:
    window = CameraImageWindow()
    window.resize(1000, 700)
    window.show()
    qt_app.processEvents()
    window.show_frame(ramp() if frame is None else frame, "test")
    window.measurement.roi_button.setChecked(True)
    qt_app.processEvents()
    return window


def test_drawing_an_roi_selects_the_pixels_under_the_drag_when_fit(qt_app):
    window = viewer(qt_app)
    preview = window.preview
    drag(preview, widget_point(preview, 10.5, 5.5), widget_point(preview, 29.5, 14.5))
    assert preview.analysis_roi == (10, 5, 20, 10)
    frame = preview.raw_frame
    stats = roi_statistics(frame, (10, 5, 20, 10))
    text = window.measurement.roi_label.text()
    assert "x=10, y=5, 20×10 px (200 px)" in text
    assert f"mean {stats.mean:.2f}" in text and f"min {stats.minimum}" in text and f"max {stats.maximum}" in text
    window.close()


def test_roi_mapping_is_correct_when_zoomed_and_panned_and_stats_ignore_display_limits(qt_app):
    window = viewer(qt_app, ramp(400, 600))
    preview = window.preview
    window.limit_low.setValue(100)  # the display range is irrelevant to the numbers
    window.limit_high.setValue(200)
    window.apply_manual_range()
    preview.zoom_by(4.0, QPointF(preview.width() / 2, preview.height() / 2))
    # Pan with the ROI tool off, then draw again with it on.
    window.measurement.roi_button.setChecked(False)
    start = QPoint(preview.width() // 2, preview.height() // 2)
    drag(preview, start, start + QPoint(-120, -60))
    window.measurement.roi_button.setChecked(True)
    visible = preview.visible_source_rect()
    x0, y0 = int(visible.x()) + 20, int(visible.y()) + 15
    drag(preview, widget_point(preview, x0 + 0.5, y0 + 0.5), widget_point(preview, x0 + 24.5, y0 + 17.5))
    assert preview.analysis_roi == (x0, y0, 25, 18)
    expected = roi_statistics(preview.raw_frame, (x0, y0, 25, 18))
    assert f"mean {expected.mean:.2f}" in window.measurement.roi_label.text()
    assert "max {}".format(expected.maximum) in window.measurement.roi_label.text()
    window.close()


def test_roi_drag_may_leave_the_widget_and_is_clamped_to_the_image(qt_app):
    window = viewer(qt_app)
    preview = window.preview
    drag(preview, widget_point(preview, 40.5, 20.5), QPoint(preview.width() + 300, preview.height() + 300))
    assert preview.analysis_roi == (40, 20, 20, 20)  # runs to the bottom-right pixel, no further
    window.close()


def test_roi_can_be_moved_inside_the_image_and_cleared(qt_app):
    window = viewer(qt_app)
    preview = window.preview
    drag(preview, widget_point(preview, 10.5, 10.5), widget_point(preview, 19.5, 19.5))
    assert preview.analysis_roi == (10, 10, 10, 10)
    drag(preview, widget_point(preview, 15.5, 15.5), widget_point(preview, 25.5, 20.5))
    assert preview.analysis_roi == (20, 15, 10, 10)
    drag(preview, widget_point(preview, 25.5, 20.5), widget_point(preview, 5000, 5000))  # clamped
    assert preview.analysis_roi == (50, 30, 10, 10)
    window.measurement.clear_roi_button.click()
    assert preview.analysis_roi is None
    assert window.measurement.roi_label.text() == "Analysis ROI: none"
    window.close()


def test_roi_follows_new_frames_of_the_same_size_and_is_dropped_when_the_size_changes(qt_app):
    window = viewer(qt_app)
    preview = window.preview
    drag(preview, widget_point(preview, 10.5, 10.5), widget_point(preview, 19.5, 19.5))
    brighter = ramp() + 100
    window.show_frame(brighter, "next frame")
    assert preview.analysis_roi == (10, 10, 10, 10)
    assert f"mean {brighter[10:20, 10:20].mean():.2f}" in window.measurement.roi_label.text()
    window.show_frame(ramp(30, 50), "different sensor ROI")
    assert preview.analysis_roi is None
    assert window.measurement.roi_label.text() == "Analysis ROI: none"
    window.close()


def test_roi_needs_an_image_and_a_click_does_not_create_one(qt_app):
    window = CameraImageWindow()
    window.show()
    window.preview.set_analysis_roi((0, 0, 5, 5))
    assert window.preview.analysis_roi is None  # nothing to measure yet
    window.show_frame(ramp(), "x")
    window.measurement.roi_button.setChecked(True)
    qt_app.processEvents()
    point = widget_point(window.preview, 10.5, 10.5)
    drag(window.preview, point, point)
    assert window.preview.analysis_roi is None
    window.show_frame("not an image", "metadata only")  # frame without pixels
    assert window.measurement.roi_label.text() == "Analysis ROI: none"
    window.close()


def test_profile_shows_the_selected_row_and_column_of_the_raw_frame(qt_app):
    window = viewer(qt_app)
    panel = window.measurement
    panel.profile_check.setChecked(True)
    panel.profile_axis.setCurrentIndex(0)
    panel.profile_position.setValue(7)
    expected_row = ramp()[7, :]
    assert panel.profile_plot.samples_by_channel[0] == [float(v) for v in expected_row]
    assert window.preview._profile_marker == ("row", 7)
    panel.profile_axis.setCurrentIndex(1)
    assert panel.profile_position.maximum() == 59  # columns
    panel.profile_position.setValue(12)
    assert panel.profile_plot.samples_by_channel[0] == [float(v) for v in ramp()[:, 12]]
    assert window.preview._profile_marker == ("column", 12)
    assert "pixel" in panel.profile_plot.x_axis_label and "(s)" not in panel.profile_plot.x_axis_label
    panel.profile_check.setChecked(False)
    assert window.preview._profile_marker is None
    window.close()


def test_profile_position_is_kept_in_range_when_the_frame_size_changes(qt_app):
    window = viewer(qt_app)
    panel = window.measurement
    panel.profile_check.setChecked(True)
    panel.profile_position.setValue(39)  # last row of 40
    window.show_frame(ramp(10, 20), "smaller")
    assert panel.profile_position.maximum() == 9
    assert 0 <= panel.profile_position.value() <= 9
    assert len(panel.profile_plot.samples_by_channel[0]) == 20
    window.close()


def test_drawing_roi_and_profile_in_the_main_window_sends_no_device_command(qt_app):
    controller = ApplicationController(DeviceRegistry(mode=OperatingMode.SIMULATION),
                                       mode=OperatingMode.SIMULATION)
    submitted = []
    controller.submit = lambda command: submitted.append(command)  # any device traffic would land here
    window = MainWindow(controller)
    camera = window.panels[DeviceId.CAMERA].image_window
    camera.show()
    camera.show_frame(ramp(), "test")
    camera.measurement.roi_button.setChecked(True)
    qt_app.processEvents()
    drag(camera.preview, widget_point(camera.preview, 5.5, 5.5), widget_point(camera.preview, 25.5, 15.5))
    camera.measurement.profile_check.setChecked(True)
    camera.measurement.clear_roi_button.click()
    assert camera.preview.analysis_roi is None
    assert submitted == []
    camera.close()
    window.close()
    controller.shutdown()


def test_roi_and_profile_statistics_stay_cheap_on_a_full_sensor_frame(qt_app):
    """Guards the decision to compute on the UI thread: a worst-case 2304x2304 frame, full-frame ROI."""
    from time import perf_counter
    frame = np.random.default_rng(1).integers(0, 65535, (2304, 2304), dtype=np.uint16)
    start = perf_counter()
    roi_statistics(frame, (0, 0, 2304, 2304))
    row_profile(frame, 1000)
    column_profile(frame, 1000)
    assert perf_counter() - start < 1.0  # about 0.02 s measured on this workstation; only guards a regression
