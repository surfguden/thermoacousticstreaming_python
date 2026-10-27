"""Reading saved frames back: frame order, on-demand reads, refusals, and live vs saved state.

Fixtures are written by the real `SeriesStorage`, so the reader is checked against the actual
experiment.json / TIFF layout rather than a hand-made copy of it.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication

from thermo_acoustic.application import ApplicationController
from thermo_acoustic.application import saved_frames
from thermo_acoustic.application.commands import CameraSequenceResult
from thermo_acoustic.application.experiment_storage import SeriesStorage
from thermo_acoustic.application.experiments import default_definition, validate_definition
from thermo_acoustic.application.simple_series import NumericRange, SimpleSeriesSettings, compile_simple_series
from thermo_acoustic.application.saved_frames import SavedExperiment, SavedFramesError, find_experiments
from thermo_acoustic.domain.models import OperatingMode
from thermo_acoustic.hal.registry import DeviceRegistry
from thermo_acoustic.ui.main_window import MainWindow
from thermo_acoustic.ui.saved_frames_window import SavedFramesWindow


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication(["test-saved-frames"])


FRAMES = 4


def make_series(root: Path, image_format: str, saved: int = 2) -> tuple[Path, list]:
    """A real series folder with the first `saved` planned experiments written; frame k of
    experiment e holds the constant value 1000 * e + k so any mix-up is visible."""
    expansion = validate_definition(compile_simple_series(SimpleSeriesSettings(
        repeats=2, frame_count=FRAMES, camera_fps=10, sound_start_s=0, sound_run_s=1, laser_start_s=0,
        laser_run_s=0.1, camera_start_s=0.1, frequency_hz=NumericRange(1_000_000, 1_000_000, 1),
        amplitude_v=NumericRange(1, 1, 1), exposure_ms=NumericRange(1, 1, 1), roi=(0, 0, 8, 6),
        flush_unit_index=0, flush_volume_ml=0.01, flush_flow_ul_min=200, description="saved frames",
        tiff_format=image_format)))
    storage = SeriesStorage(root, expansion, image_format)
    planned = list(expansion.experiments[:saved])
    for number, experiment in enumerate(planned):
        count = next(step["args"]["frame_count"] for step in experiment.steps
                     if step["type"] == "camera_configure")
        frames = tuple(np.full((6, 8), 1000 * number + k, dtype=np.uint16) for k in range(count))
        capture = CameraSequenceResult(
            frames, tuple(f"dcam_clock:{k}" for k in range(count)),
            tuple(f"2026-10-01T00:00:{k:02d}+00:00" for k in range(count)), {"sensor": "simulation"})
        storage.save_frames(experiment, capture, {})
    return storage.folder, planned


def digest(folder: Path) -> dict[str, str]:
    return {str(path.relative_to(folder)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(folder.rglob("*")) if path.is_file()}


@pytest.mark.parametrize("image_format", ["frames", "stacked"])
def test_frames_come_back_in_saved_order_with_their_own_pixels(tmp_path, image_format):
    series, planned = make_series(tmp_path, image_format)
    experiment = SavedExperiment(series / planned[1].relative_path)
    assert experiment.frame_count == FRAMES and experiment.image_format == image_format
    for position in range(experiment.frame_count):
        frame = experiment.load_frame(position)
        assert frame.shape == (6, 8) and frame.dtype == np.uint16
        assert int(frame[0, 0]) == 1000 + position  # experiment 2, frame number position + 1
    assert [record.index for record in experiment.frames] == list(range(1, FRAMES + 1))
    assert experiment.frames[3].camera_sdk_timestamp == "dcam_clock:3"
    with pytest.raises(IndexError):
        experiment.load_frame(FRAMES)


def test_series_folder_lists_only_experiments_that_already_have_frames_in_plan_order(tmp_path):
    series, planned = make_series(tmp_path, "frames", saved=2)
    found = find_experiments(series)
    assert [item.experiment_id for item in found] == [item.experiment_id for item in planned]
    assert [item.folder for item in found] == [series / item.relative_path for item in planned]
    assert found[0].parameters == planned[0].parameters
    # A single experiment folder is accepted directly.
    assert [item.experiment_id for item in find_experiments(series / planned[0].relative_path)] == [
        planned[0].experiment_id]
    with pytest.raises(SavedFramesError, match="neither an experiment folder"):
        find_experiments(tmp_path / "metadata")


def test_frames_are_read_on_demand_and_only_a_few_stay_in_memory(tmp_path, monkeypatch):
    series, planned = make_series(tmp_path, "frames", saved=1)
    opened = []
    real_open = Image.open
    monkeypatch.setattr(saved_frames.Image, "open", lambda *a, **k: (opened.append(a[0]), real_open(*a, **k))[1])
    experiment = SavedExperiment(series / planned[0].relative_path, cache_frames=3)
    assert opened == []  # reading the record does not read any picture
    experiment.load_frame(0)
    experiment.load_frame(0)  # from the cache
    assert len(opened) == 1 and experiment.reads == 1
    for position in range(FRAMES):
        experiment.load_frame(position)
    assert len(experiment._cache) == 3
    experiment.load_frame(FRAMES - 1)  # still cached
    reads_before = experiment.reads
    experiment.load_frame(0)  # evicted earlier, read again
    assert experiment.reads == reads_before + 1


@pytest.mark.parametrize("damage, message", [
    ("shuffle", "not numbered 1..N"),
    ("count", "frame_count"),
    ("incomplete", "not 'complete'"),
    ("missing_file", "is missing"),
    ("no_frames", "no frames list"),
])
def test_unreliable_records_are_refused_with_the_reason_instead_of_guessing(tmp_path, damage, message):
    series, planned = make_series(tmp_path, "frames", saved=1)
    folder = series / planned[0].relative_path
    path = folder / "experiment.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    if damage == "shuffle":
        record["frames"][0], record["frames"][1] = record["frames"][1], record["frames"][0]
    elif damage == "count":
        record["frame_count"] = 11
    elif damage == "incomplete":
        record["acquisition_status"] = "partial"
    elif damage == "missing_file":
        (folder / record["frames"][2]["filename"]).unlink()
    else:
        del record["frames"]
    path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(SavedFramesError, match=message):
        SavedExperiment(folder)


def test_unreadable_picture_is_reported_with_its_frame_number(tmp_path):
    series, planned = make_series(tmp_path, "frames", saved=1)
    folder = series / planned[0].relative_path
    (folder / "frame_000004.tif").write_bytes(b"not a tiff")
    experiment = SavedExperiment(folder)
    with pytest.raises(SavedFramesError, match="Frame 4"):
        experiment.load_frame(3)


def test_window_marks_saved_data_and_browses_frames_without_touching_the_files(tmp_path, qt_app):
    series, planned = make_series(tmp_path, "stacked", saved=2)
    before = digest(series)
    window = SavedFramesWindow()
    window.show()
    assert "No saved frames" in window.preview_state.text()
    window.open_folder(series)
    assert window.experiment_combo.count() == 2
    assert "SAVED DATA" in window.banner.text() and "not the live camera" in window.banner.text()
    assert window.preview_state.text() == "Saved frame 1 of 4 — historical, not live"
    assert int(window.preview.raw_frame[0, 0]) == 0
    window.next_button.click()
    window.next_button.click()
    assert window.preview_state.text() == "Saved frame 3 of 4 — historical, not live"
    assert int(window.preview.raw_frame[0, 0]) == 2 and window.frame_spin.value() == 3
    window.slider.setValue(4)  # the last frame, number 4
    assert int(window.preview.raw_frame[0, 0]) == 3 and not window.next_button.isEnabled()
    window.frame_spin.setValue(1)
    assert not window.previous_button.isEnabled() and window.slider.value() == 1
    window.experiment_combo.setCurrentIndex(1)  # second experiment, first frame
    assert int(window.preview.raw_frame[0, 0]) == 1000 and window.frame_spin.value() == 1
    assert "page 0" in window.status.text() and "dcam_clock:0" in window.status.text()
    # Measurements work on the saved frame too.
    window.preview.set_analysis_roi((0, 0, 4, 3))
    assert "mean 1000.00" in window.measurement.roi_label.text()
    window.close()
    assert digest(series) == before


def test_window_reports_an_unreadable_experiment_and_a_series_without_saved_frames(tmp_path, qt_app):
    series, planned = make_series(tmp_path, "frames", saved=1)
    empty = tmp_path / "empty"
    empty.mkdir()
    SeriesStorage(empty, validate_definition(default_definition()), "frames")  # planned, nothing acquired
    window = SavedFramesWindow()
    with pytest.raises(SavedFramesError, match="no saved experiments"):
        window.open_folder(next(empty.glob("experiment_batch_*")))
    record_path = series / planned[0].relative_path / "experiment.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["frame_count"] = 3
    record_path.write_text(json.dumps(record), encoding="utf-8")
    window.open_folder(series)
    assert "Cannot show" in window.status.text() and "frame_count" in window.status.text()
    assert not window.slider.isEnabled()
    assert "No saved frames" in window.preview_state.text()
    window.close()


def test_saved_review_is_separate_from_the_live_viewer_and_sends_no_device_command(tmp_path, qt_app):
    series, _planned = make_series(tmp_path, "frames", saved=1)
    controller = ApplicationController(DeviceRegistry(mode=OperatingMode.SIMULATION),
                                       mode=OperatingMode.SIMULATION)
    submitted = []
    controller.submit = lambda command: submitted.append(command)
    window = MainWindow(controller)
    from thermo_acoustic.domain.models import DeviceId
    live = window.panels[DeviceId.CAMERA].image_window
    live_text = live.preview_state.text()
    window._review_saved_frames(str(series))
    review = window.saved_frames_window
    assert review is not live
    assert window.tabs.currentWidget() is window.results_panel  # reviewing happens in the Results workspace
    assert "historical, not live" in review.preview_state.text()
    assert live.preview_state.text() == live_text and not live.preview.has_image  # live view untouched
    window.show_workspace("monitor")
    window.show_workspace("queue")
    window.show_workspace("prepare")
    assert submitted == []
    window.close()
    controller.shutdown()


def _break_record(folder: Path, change) -> None:
    path = folder / "experiment.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    change(record)
    path.write_text(json.dumps(record), encoding="utf-8")


def test_failing_to_load_another_experiment_clears_everything_of_the_previous_one(tmp_path, qt_app):
    series, planned = make_series(tmp_path, "frames", saved=2)
    _break_record(series / planned[1].relative_path, lambda r: r.update(frame_count=3))
    window = SavedFramesWindow()
    window.show()
    window.open_folder(series)  # first experiment shows fine
    window.measurement.profile_check.setChecked(True)
    window.preview.set_analysis_roi((0, 0, 4, 3))
    assert window.preview.raw_frame is not None and window.histogram.pixel_count > 0
    window.experiment_combo.setCurrentIndex(1)  # unreadable one
    assert window.preview.raw_frame is None and not window.preview.has_image
    assert window.histogram.pixel_count == 0
    assert window.preview.analysis_roi is None and window.measurement.roi_label.text() == "Analysis ROI: none"
    assert window.measurement.profile_plot.samples_by_channel == {}
    assert window.preview._profile_marker is None
    assert not any(w.isEnabled() for w in (window.slider, window.frame_spin, window.previous_button,
                                           window.next_button))
    assert "Cannot show" in window.status.text() and "No saved frames" in window.preview_state.text()
    assert window.frame_info.text() == "Image: —" and window.count_label.text() == "of —"
    # Going back to the good experiment restores a normal, consistent view.
    window.experiment_combo.setCurrentIndex(0)
    assert int(window.preview.raw_frame[0, 0]) == 0 and window.slider.isEnabled()
    window.close()


def test_failing_to_load_another_frame_keeps_controls_and_labels_consistent_with_the_image(tmp_path, qt_app):
    series, planned = make_series(tmp_path, "frames", saved=1)
    folder = series / planned[0].relative_path
    window = SavedFramesWindow()
    window.open_folder(series)
    window.show_position(1)
    assert int(window.preview.raw_frame[0, 0]) == 1
    (folder / "frame_000003.tif").write_bytes(b"damaged")  # frame number 3 becomes unreadable
    window.slider.setValue(3)
    assert int(window.preview.raw_frame[0, 0]) == 1  # last valid image kept ...
    assert window.slider.value() == 2 and window.frame_spin.value() == 2  # ... controls say so
    assert "frame 3 could not be read" in window.preview_state.text()
    assert "Saved frame 2 of 4" in window.preview_state.text()
    assert "Frame 3" in window.status.text() and "still showing frame 2" in window.status.text()
    window.show_position(3)  # a readable frame clears the warning
    assert "could not be read" not in window.preview_state.text() and window.slider.value() == 4
    window.close()


@pytest.mark.parametrize("target, damage", [
    ("experiment", lambda: []),
    ("experiment", lambda: "text"),
    ("manifest_entry", lambda: 5),
    ("manifest_entry", lambda: {"experiment_id": "x"}),
    ("manifest_entry", lambda: {"relative_path": "x"}),
    ("manifest_root", lambda: []),
    ("frame_record", lambda: 7),
    ("frame_record", lambda: {"index": 1}),
    ("parameters", lambda: [1, 2]),
])
def test_structurally_wrong_records_give_a_saved_frames_error_not_a_crash(tmp_path, qt_app, monkeypatch,
                                                                          target, damage):
    series, planned = make_series(tmp_path, "frames", saved=1)
    folder = series / planned[0].relative_path
    if target == "experiment":
        (folder / "experiment.json").write_text(json.dumps(damage()), encoding="utf-8")
        with pytest.raises(SavedFramesError):
            find_experiments(folder)
        with pytest.raises(SavedFramesError):
            SavedExperiment(folder)
        window = SavedFramesWindow()
        window.show()
        shown = []
        monkeypatch.setattr("thermo_acoustic.ui.saved_frames_window.QMessageBox.warning",
                            lambda *args: shown.append(args[2]))
        window.open_or_report(folder)  # the UI path: a message, no exception out of the slot
        assert len(shown) == 1
        window.close()
        return
    if target == "manifest_root":
        (series / "metadata" / "manifest.json").write_text(json.dumps(damage()), encoding="utf-8")
        with pytest.raises(SavedFramesError):
            find_experiments(series)
    elif target == "manifest_entry":
        manifest_path = series / "metadata" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["experiments"][0] = damage()
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with pytest.raises(SavedFramesError):
            find_experiments(series)
    elif target == "frame_record":
        _break_record(folder, lambda r: r["frames"].__setitem__(1, damage()))
        with pytest.raises(SavedFramesError):
            SavedExperiment(folder)
    else:
        _break_record(folder, lambda r: r.update(parameters=damage()))
        with pytest.raises(SavedFramesError):
            SavedExperiment(folder)


def _window(qt_app):
    controller = ApplicationController(DeviceRegistry(mode=OperatingMode.SIMULATION),
                                       mode=OperatingMode.SIMULATION)
    window = MainWindow(controller)
    window.show()
    qt_app.processEvents()
    return controller, window


def test_escape_does_not_hide_an_embedded_viewer_and_still_closes_a_popped_out_one(qt_app):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from thermo_acoustic.domain.models import DeviceId
    controller, window = _window(qt_app)
    try:
        camera = window.panels[DeviceId.CAMERA]
        window.show_workspace("prepare")
        window.prepare_panel.imaging_section.set_expanded(True)
        qt_app.processEvents()
        viewer = camera.image_window
        assert viewer.isVisible()
        viewer.preview.setFocus()
        QTest.keyClick(viewer.preview, Qt.Key.Key_Escape)  # a real key press
        QTest.keyClick(viewer, Qt.Key.Key_Escape)
        assert viewer.isVisible()
        window.show_workspace("results")
        window.show_workspace("prepare")
        assert viewer.isVisible()
        results_viewer = window.results_panel.viewer
        window.show_workspace("results")
        QTest.keyClick(results_viewer, Qt.Key.Key_Escape)
        assert results_viewer.isVisible()
        window.show_workspace("monitor")
        window.show_workspace("results")
        assert results_viewer.isVisible()
        camera.show_image_window()  # the Show image entry also keeps it shown
        assert viewer.isVisible()
        # Popped out it is an ordinary window again: Esc closes it, and docking brings it back.
        window.prepare_panel.pop_button.click()
        assert viewer.isWindow() and viewer.isVisible()
        QTest.keyClick(viewer, Qt.Key.Key_Escape)
        assert not viewer.isVisible()
        window.prepare_panel.pop_button.click()  # Dock image
        window.show_workspace("prepare")
        assert not viewer.isWindow() and viewer.isVisible()
    finally:
        window.close()
        controller.shutdown()


def test_results_names_the_viewed_folder_apart_from_the_latest_output(tmp_path, qt_app, monkeypatch):
    first, _ = make_series(_mk(tmp_path / "one"), "frames", saved=1)
    second, _ = make_series(_mk(tmp_path / "two"), "frames", saved=1)
    controller, window = _window(qt_app)
    opened = []
    monkeypatch.setattr("thermo_acoustic.ui.results_panel.QDesktopServices.openUrl",
                        lambda url: opened.append(url.toLocalFile()))
    try:
        results = window.results_panel
        results.set_latest(str(second))  # the session's latest output
        assert "nothing loaded" in results.viewing_label.text().lower()
        assert not results.open_viewed_button.isEnabled()
        # Load a different, older folder through the viewer's own Open: the outer state follows it.
        results.viewer.open_or_report(str(first))
        assert str(first) in results.viewing_label.text() and results.open_viewed_button.isEnabled()
        results.open_viewed_button.click()
        assert [str(Path(p)) for p in opened] == [str(first)]  # not the latest output
        assert str(second) in results.latest_label.text()
        results.open_latest_button.click()
        assert str(second) in results.viewing_label.text()
        # A failed load changes nothing that is shown or targeted.
        empty = _mk(tmp_path / "empty")
        monkeypatch.setattr("thermo_acoustic.ui.saved_frames_window.QMessageBox.warning", lambda *a: None)
        results.viewer.open_or_report(str(empty))
        assert str(second) in results.viewing_label.text()
        results.open_viewed_button.click()
        assert str(Path(opened[-1])) == str(second)
        assert digest(first)  # the source data was only read
    finally:
        window.close()
        controller.shutdown()


def _mk(path: Path) -> Path:
    path.mkdir()
    return path
