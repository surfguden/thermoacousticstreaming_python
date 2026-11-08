"""Preparation conveniences: saved device selection, Z reference helper, raw-frame saving, pump level against the
queued flush demand, and the live frames of a running experiment.

Behaviour risks only: none of the helpers may send a device command, and each shows exactly what it knows.
"""

from __future__ import annotations

import json
from dataclasses import replace
from time import monotonic, sleep

import numpy as np
import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from thermo_acoustic.application import ApplicationController
from thermo_acoustic.application.frame_export import save_raw_frame
from thermo_acoustic.application.simple_series import NumericRange, compile_simple_series
from thermo_acoustic.domain.models import (
    ConnectionState, DeviceId, DeviceStatus, OperatingMode, PumpReadback, PumpUnitReadback, ZStageReadback,
)
from thermo_acoustic.hal.registry import DeviceRegistry
from thermo_acoustic.ui.device_panels import PumpPanel, ZStagePanel, queued_flush_text
from thermo_acoustic.ui.main_window import MainWindow
from thermo_acoustic.ui.widgets import CameraImageWindow


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication(["test-prepare-conveniences"])


@pytest.fixture
def env(qt_app):
    controller = ApplicationController(DeviceRegistry(), mode=OperatingMode.SIMULATION)
    events = []
    controller.command_event.connect(events.append)
    controller.start()
    window = MainWindow(controller)
    window.show()

    def wait(condition, timeout=10):
        deadline = monotonic() + timeout
        while monotonic() < deadline and not condition():
            qt_app.processEvents()
            sleep(0.01)
        assert condition()

    yield window, controller, events, wait
    window.close()
    controller.shutdown()


# ---------------------------------------------------------------- saved device selection
def test_device_selection_is_saved_and_loading_it_only_ticks_boxes(env, tmp_path):
    window, controller, events, wait = env
    window.prepare_panel.set_selected_devices([DeviceId.CAMERA, DeviceId.Z_STAGE])
    path = tmp_path / "settings.json"
    window.save_profile(path)
    assert json.loads(path.read_text())["prepare"] == {"selected_devices": ["camera", "z_stage"]}
    window.prepare_panel.set_selected_devices([DeviceId.PUMP])
    before = len(events)
    window.load_profile(path)
    assert window.prepare_panel.selected_devices() == [DeviceId.CAMERA, DeviceId.Z_STAGE]
    assert len(events) == before  # no command of any kind
    assert all(controller.statuses()[d].connection is ConnectionState.DISCONNECTED for d in DeviceId)
    assert not window.prepare_panel.connector.active  # ticking is not connecting


def test_old_settings_without_the_field_keep_the_current_ticks_and_bad_values_apply_nothing(env, tmp_path):
    window, controller, events, wait = env
    path = tmp_path / "old.json"
    window.save_profile(path)
    document = json.loads(path.read_text())
    del document["prepare"]
    path.write_text(json.dumps(document))
    window.prepare_panel.set_selected_devices([DeviceId.TEC])
    window.load_profile(path)  # an older file: loads, and leaves the ticks as they are
    assert window.prepare_panel.selected_devices() == [DeviceId.TEC]
    camera = window.panels[DeviceId.CAMERA]
    for bad in ({"selected_devices": ["camera", "toaster"]}, {"selected_devices": ["camera", "camera"]},
                {"selected_devices": "camera"}, ["camera"]):
        camera.sequence_frames.setValue(5)
        document["prepare"] = bad
        document["devices"]["camera"] = {"sequence_frames": 27}
        path.write_text(json.dumps(document))
        with pytest.raises(ValueError, match="selected_devices"):
            window.load_profile(path)
        assert camera.sequence_frames.value() == 5  # validated before anything was applied
        assert window.prepare_panel.selected_devices() == [DeviceId.TEC]


# ---------------------------------------------------------------- Z helper
def _z_panel(qt_app, position=None, commanded=None, connected=True):
    panel = ZStagePanel()
    sent = []
    panel.command_requested.connect(lambda *args: sent.append(args))
    readback = ZStageReadback(position_um=position, commanded_position_um=commanded, closed_loop=True)
    panel.set_status(DeviceStatus(DeviceId.Z_STAGE, ConnectionState.CONNECTED if connected else ConnectionState.DISCONNECTED,
                                  readback=readback if connected else None))
    return panel, sent


def test_z_copy_and_reference_never_move_and_need_a_real_measurement(qt_app):
    panel, sent = _z_panel(qt_app, position=None, commanded=20.0)  # a commanded target is not a measurement
    assert not panel.use_measured_button.isEnabled() and not panel.set_reference_button.isEnabled()
    panel, sent = _z_panel(qt_app, position=12.5)
    panel.use_measured_button.click()
    assert panel.position.value() == 12.5 and sent == []  # the target field only
    panel.set_reference_button.click()
    assert "Reference focus 12.5 µm" in panel.reference_label.text() and sent == []
    panel.set_status(DeviceStatus(DeviceId.Z_STAGE, ConnectionState.CONNECTED,
                                  readback=ZStageReadback(position_um=13.0, closed_loop=True)))
    assert "measured now 13 µm (+0.500 µm from it)" in panel.reference_label.text()
    panel.position.setValue(1.0)
    panel.reference_to_target_button.click()
    assert panel.position.value() == 12.5 and sent == []
    assert "focused" not in panel.reference_label.text().lower()
    panel.set_status(DeviceStatus(DeviceId.Z_STAGE, ConnectionState.CONNECTED, readback=ZStageReadback()))
    assert "measured now unknown" in panel.reference_label.text()  # unknown is not zero or "at reference"
    panel.set_status(DeviceStatus(DeviceId.Z_STAGE, ConnectionState.DISCONNECTED))
    assert "none" in panel.reference_label.text() and not panel.clear_reference_button.isEnabled()  # forgotten


# ---------------------------------------------------------------- raw frame saving
def _frame(seed=1):
    return np.random.RandomState(seed).randint(0, 65535, size=(20, 30)).astype(np.uint16)


def test_raw_frame_file_has_exactly_the_pixels_and_nothing_is_overwritten_by_failures(tmp_path):
    frame = _frame()
    saved = save_raw_frame(frame, tmp_path / "shot")
    assert saved.name == "shot.tif"
    assert np.array_equal(np.array(Image.open(saved)), frame)
    assert not list(tmp_path.glob(".*.part"))
    for bad in (frame.astype(np.float32), frame[None], np.zeros((0, 3), np.uint16), "not a frame"):
        with pytest.raises(ValueError):
            save_raw_frame(bad, tmp_path / "bad.tif")
    with pytest.raises(OSError):
        save_raw_frame(frame, tmp_path / "missing_folder" / "x.tif")
    assert not (tmp_path / "bad.tif").exists()


def test_the_viewer_saves_the_frame_shown_at_the_click_not_a_later_one(qt_app, tmp_path, monkeypatch):
    viewer = CameraImageWindow()
    shown, later = _frame(1), _frame(2)
    viewer.show_frame(shown, "live")
    viewer.limit_low.setValue(100)
    viewer.limit_high.setValue(200)
    viewer.apply_manual_range()  # display range only
    target = tmp_path / "chosen.tif"

    def dialog_while_frames_keep_arriving(*_args, **_kwargs):
        viewer.show_frame(later, "live")  # the live view moves on while the file dialog is open
        return str(target), ""
    monkeypatch.setattr(QFileDialog, "getSaveFileName", dialog_while_frames_keep_arriving)
    viewer.save_current_raw_frame()
    assert np.array_equal(np.array(Image.open(target)), shown)  # the frame at the click, unstretched
    assert "Saved raw frame 30 × 20" in viewer.save_feedback.text()
    # cancelled, and nothing shown: both say so and write nothing
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: ("", ""))
    viewer.save_current_raw_frame()
    assert "no file was chosen" in viewer.save_feedback.text()
    empty = CameraImageWindow()
    empty.save_current_raw_frame()
    assert "no image is shown" in empty.save_feedback.text()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(tmp_path / "no" / "x.tif"), ""))
    viewer.save_current_raw_frame()
    assert viewer.save_feedback.text().startswith("Not saved:")


# ---------------------------------------------------------------- pump level against the queued demand
def test_queued_flush_text_keeps_unknown_apart_from_zero_and_marks_arithmetic():
    assert queued_flush_text(None, 1.0, True) == "Queued flush: none"
    assert "0.3 mL left after it" in queued_flush_text(0.7, 1.0, True) and "arithmetic, not measured" in queued_flush_text(0.7, 1.0, True)
    assert "short by 0.3 mL" in queued_flush_text(0.5, 0.2, True)
    assert "level not read yet" in queued_flush_text(0.5, None, True)  # not "0 mL"
    assert "pump not connected" in queued_flush_text(0.5, 1.0, False)  # an old level is not shown as current


def _pump_status(connected=True, levels=(1.0, 0.2, None)):
    units = tuple(PumpUnitReadback(unit_index=i, fill_level_ml=level, max_volume_ml=1.0) for i, level in enumerate(levels))
    return DeviceStatus(DeviceId.PUMP, ConnectionState.CONNECTED if connected else ConnectionState.DISCONNECTED,
                        readback=PumpReadback(units=units))


def test_each_pump_unit_is_compared_separately(qt_app):
    panel = PumpPanel()
    panel.set_status(_pump_status())
    panel.set_queued_flush({0: 0.7, 1: 0.5, 2: 0.1})
    text = [panel.tiles_layout.itemAtPosition(0, i).widget().queue_label.text() for i in range(3)]
    assert "0.3 mL left after it" in text[0] and "short by 0.3 mL" in text[1] and "level not read yet" in text[2]
    assert panel.queue_summary.text() == "Queued series need for flushing: unit 1: 0.7 mL · unit 2: 0.5 mL · unit 3: 0.1 mL"
    panel.set_queued_flush({})
    assert panel.tiles_layout.itemAtPosition(0, 0).widget().queue_label.text() == "Queued flush: none"
    assert not panel.queue_summary.isVisibleTo(panel)


def test_demand_follows_the_queue_not_the_form(env, tmp_path):
    from test_simple_series import settings
    window, controller, events, wait = env
    flush_unit = 0
    definition = compile_simple_series(replace(settings(), flush_unit_index=flush_unit, flush_volume_ml=0.25,
                                               frequency_hz=NumericRange(1e6, 1e6, 1), sweep_enabled=False,
                                               temperature_control=False, temperature_logging=False))
    folder = controller.experiments.queue(definition, tmp_path)
    needed = controller.experiments.queued_flush_budget()
    assert needed and window.panels[DeviceId.PUMP]._queued_flush == needed
    window.experiment_panel.volume.setValue(0.9)  # an unqueued form edit changes nothing here
    window.prepare_panel._refresh()
    assert window.panels[DeviceId.PUMP]._queued_flush == needed
    controller.experiments.remove_queued(folder)
    assert window.panels[DeviceId.PUMP]._queued_flush == {}


# ---------------------------------------------------------------- live frames of a running experiment
def test_a_running_experiment_shows_its_frames_as_they_arrive(env, tmp_path):
    window, controller, events, wait = env
    for message in ("warning", "information", "question", "critical"):
        setattr(QMessageBox, message, staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    controller.experiments.confirm_unchecked = lambda summary: True
    controller.experiments.confirm_batch = lambda summary: True
    prepare = window.prepare_panel
    prepare.set_selected_devices([DeviceId.AD2, DeviceId.CAMERA, DeviceId.PUMP, DeviceId.VALVE])
    prepare.connect_button.click()
    wait(lambda: all(controller.statuses()[d].connection is ConnectionState.CONNECTED
                     for d in (DeviceId.AD2, DeviceId.CAMERA, DeviceId.PUMP, DeviceId.VALVE)), timeout=15)
    window.panels[DeviceId.PUMP]._buttons["refill_0"].click()
    wait(lambda: (controller.statuses()[DeviceId.PUMP].readback.units[0].fill_level_ml or 0) > 0.5, timeout=15)
    panel = window.experiment_panel
    panel.pump_unit.setCurrentIndex(0)
    panel.output_root.setText(str(tmp_path))
    panel.description.setText("live frames")
    panel.frames.setValue(6)
    panel.queue_button.click()
    panel.preflight_button.click()
    wait(lambda: panel.camera_preflight_label.text().endswith("Yes"), timeout=15)
    viewer = window.panels[DeviceId.CAMERA].image_window
    seen_status, seen_frames = [], []

    def record():
        text = viewer.status.text()
        if text.startswith("Experiment acquisition"):
            if not seen_status or seen_status[-1] != text:
                seen_status.append(text)
                seen_frames.append(viewer.preview.raw_frame.copy())
    controller.command_progress.connect(lambda *_: record())
    panel.start_button.click()
    wait(lambda: window._experiment_status["state"] in ("completed", "failed", "aborted"), timeout=90)
    assert window._experiment_status["state"] == "completed"
    # frames arrived one by one while the sequence was still short of its last frame
    assert any(f"frame {k}/6" in text for text in seen_status for k in (1, 2, 3, 4, 5)), seen_status
    assert len({frame.tobytes() for frame in seen_frames}) >= 2  # different frames, not one repeated image
    assert "this experiment" in seen_status[0] and "saved to disk after the last frame" in seen_status[0]
