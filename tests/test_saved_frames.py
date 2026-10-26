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
    assert review is not live and review.isVisible()
    assert "historical, not live" in review.preview_state.text()
    assert live.preview_state.text() == live_text and not live.preview.has_image  # live view untouched
    window._navigate("monitor")
    window._navigate("review")
    window._navigate("prepare")
    assert submitted == []
    review.close()
    window.close()
    controller.shutdown()
