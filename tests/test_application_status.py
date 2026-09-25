"""Application status and safety checks; all devices are simulated."""

from __future__ import annotations

import json
from dataclasses import replace
from time import monotonic, sleep

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication, QMessageBox
import pytest

from thermo_acoustic.application.commands import CommandEvent, DeviceCommand, DeviceOperation, FlushArgs, WorkflowCommand, WorkflowOperation
from thermo_acoustic.application.controller import ApplicationController
from thermo_acoustic.application.experiments import default_definition, validate_definition
from thermo_acoustic.application.session_logging import UiLogWriter, create_session_logs
from thermo_acoustic.application.simple_series import NumericRange, SimpleSeriesSettings, compile_simple_series
from thermo_acoustic.domain.models import DeviceId, OperatingMode, PumpReadback, PumpUnitReadback
from thermo_acoustic.hal.registry import DeviceRegistry
from thermo_acoustic.ui.main_window import MainWindow


def wait(app, predicate, seconds=5):
    deadline = monotonic() + seconds
    while monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        sleep(0.01)
    assert predicate()


def simple_settings() -> SimpleSeriesSettings:
    return SimpleSeriesSettings(
        repeats=1, frame_count=2, camera_fps=10, sound_start_s=0,
        sound_run_s=0.1, laser_start_s=0, laser_run_s=0.1, camera_start_s=0,
        frequency_hz=NumericRange(1_000_000, 1_000_000, 1),
        amplitude_v=NumericRange(1, 1, 1), exposure_ms=NumericRange(1, 1, 1),
        roi=(0, 0, 16, 16), flush_unit_index=0, flush_volume_ml=0.1,
        flush_flow_ul_min=500, description="  Temperature sweep  ", flush_wait_after_s=2.5,
    )


def test_descriptor_is_required_for_queue_and_flush_wait_is_compiled(tmp_path):
    QApplication.instance() or QApplication(["test-descriptor"])
    controller = ApplicationController(DeviceRegistry(), mode=OperatingMode.SIMULATION)
    definition = compile_simple_series(simple_settings())
    assert definition["description"] == "Temperature sweep"
    assert definition["steps"][0]["args"]["wait_after_s"] == 2.5
    experiment = validate_definition(definition).experiments[0]
    assert experiment.steps[-1]["branches"][1][-1]["args"]["wait_after_s"] == 2.5
    assert controller.experiments.queue(definition, tmp_path).exists()
    old = default_definition()
    with pytest.raises(ValueError, match="descriptor"):
        controller.experiments.queue(old, tmp_path)
    old["description"] = "  "
    with pytest.raises(ValueError, match="descriptor"):
        controller.experiments.queue(old, tmp_path)
    controller.experiments._state = "running"
    with pytest.raises(RuntimeError, match="while an experiment batch"):
        controller.experiments.queue(definition, tmp_path)
    controller.shutdown()


def test_session_logs_do_not_replace_previous_launch(tmp_path):
    first = create_session_logs(tmp_path, "real")
    writer = UiLogWriter(first.ui)
    assert writer.write("first command") is None
    second = create_session_logs(tmp_path, "real")
    assert second.folder != first.folder
    assert first.ui.read_text(encoding="utf-8") == "first command\n"
    assert second.audit.parent == second.hardware.parent == second.ui.parent


def test_top_status_and_dashboard_are_passive_and_lock_commands():
    QApplication.instance() or QApplication(["test-status-ui"])
    controller = ApplicationController(DeviceRegistry(), mode=OperatingMode.SIMULATION)
    window = MainWindow(controller)
    try:
        status = {**controller.experiments.status(), "state": "running",
                  "planned_experiments": 118, "current_experiment_number": 6,
                  "phase": "Acquiring frames"}
        controller.experiments.changed.emit(status)
        assert window.activity_title.text() == "Running experiment 6/118…"
        assert window.activity_detail.text() == "Acquiring frames"
        assert not window.panels[DeviceId.CAMERA]._buttons["connect"].isEnabled()
        assert not window.workflow_panel.flush_button.isEnabled()
        assert not window.experiment_panel.queue_button.isEnabled()
        window.builder_window.panel.description.setText("Builder descriptor")
        assert window.builder_window.panel._definition()["description"] == "Builder descriptor"
        window.dashboard.add_temperature_sample({"monotonic_s": monotonic(),
                                                 "channel_1_c": 20.0, "channel_2_c": 21.0})
        assert len(window.dashboard.temperature_plot._samples) == 1
        controller.experiments.changed.emit({**status, "state": "failed", "phase": "Experiment series failed: valve timeout"})
        assert "valve timeout" in window.activity_detail.text()
        window._status(controller.statuses())
        assert "valve timeout" in window.activity_detail.text()
        window._event(CommandEvent("manual", "completed", DeviceId.AD2,
                                   DeviceOperation.AD2_WAVEFORM_CONFIGURE, "ui"))
        assert window.activity_title.text() == "Idle"
        assert "waveform configure" in window.activity_detail.text()
        assert window.experiment_panel.queue_button.isEnabled()
    finally:
        window.close()


def test_panic_stops_connected_outputs_without_moving_valve():
    app = QApplication.instance() or QApplication(["test-panic"])
    controller = ApplicationController(DeviceRegistry(), mode=OperatingMode.SIMULATION)
    results, events = [], []
    controller.command_result.connect(results.append)
    controller.command_event.connect(events.append)
    controller.start()
    try:
        for device in (DeviceId.AD2, DeviceId.CAMERA, DeviceId.PUMP, DeviceId.TEC, DeviceId.VALVE):
            controller.submit(DeviceCommand(device, DeviceOperation.CONNECT))
        wait(app, lambda: sum(result.operation is DeviceOperation.CONNECT and result.ok for result in results) == 5)

        class ActiveFlush(QObject):
            disposed = False

            def dispose(self):
                self.disposed = True

        flush = ActiveFlush()
        controller._flush = flush
        controller._flush_command = WorkflowCommand(WorkflowOperation.FLUSH, FlushArgs(0, 0.1, 500))
        before = len(events)
        controller.panic_stop()
        assert controller.panic_status()["state"] == "stopping"
        with pytest.raises(RuntimeError, match="Panic safe stop"):
            controller.submit(DeviceCommand(DeviceId.VALVE, DeviceOperation.VALVE_POSITION_READ))
        wait(app, lambda: controller.panic_status()["state"] != "stopping")
        assert controller.panic_status()["state"] == "completed"
        assert flush.disposed
        assert not any(event.operation is DeviceOperation.VALVE_POSITION_SET for event in events[before:])
        stopped = {result.device for result in results if result.operation is DeviceOperation.SAFE_STOP and result.ok}
        assert stopped == {DeviceId.AD2, DeviceId.CAMERA, DeviceId.PUMP, DeviceId.TEC}
    finally:
        controller.shutdown()


def test_panic_requires_confirmation_and_reports_failed_stop(monkeypatch):
    app = QApplication.instance() or QApplication(["test-panic-failure"])
    registry = DeviceRegistry()
    controller = ApplicationController(registry, mode=OperatingMode.SIMULATION)
    window = MainWindow(controller)
    results = []
    controller.command_result.connect(results.append)
    controller.start()
    try:
        controller.submit(DeviceCommand(DeviceId.AD2, DeviceOperation.CONNECT))
        wait(app, lambda: any(result.operation is DeviceOperation.CONNECT and result.ok for result in results))
        monkeypatch.setattr(QMessageBox, "warning", lambda *_args: QMessageBox.StandardButton.Cancel)
        window._panic()
        assert controller.panic_status()["state"] == "idle"

        def fail_stop():
            raise RuntimeError("injected AD2 stop error")

        registry.by_id(DeviceId.AD2).safe_stop = fail_stop
        monkeypatch.setattr(QMessageBox, "warning", lambda *_args: QMessageBox.StandardButton.Yes)
        window._panic()
        wait(app, lambda: controller.panic_status()["state"] == "failed")
        assert "injected AD2 stop error" in window.activity_detail.text()
    finally:
        window.close()
        controller.shutdown()


def test_queue_preflight_badge_invalidates_with_syringe_level(tmp_path):
    QApplication.instance() or QApplication(["test-batch-badge"])
    controller = ApplicationController(DeviceRegistry(), mode=OperatingMode.SIMULATION)
    manager = controller.experiments
    definition = compile_simple_series(simple_settings())
    manager.queue(definition, tmp_path)
    pump = controller._statuses[DeviceId.PUMP]
    controller._statuses[DeviceId.PUMP] = replace(pump, readback=PumpReadback(
        units=(PumpUnitReadback(0, fill_level_ml=1.0),)))
    fingerprint = json.dumps(definition, sort_keys=True, allow_nan=False)
    assert not manager.status()["series"][0]["preflight_passed"]
    manager.record_simple_preflight(fingerprint, 0, 1.0)
    assert manager.status()["series"][0]["preflight_passed"]
    controller._statuses[DeviceId.PUMP] = replace(pump, readback=PumpReadback(
        units=(PumpUnitReadback(0, fill_level_ml=0.5),)))
    assert not manager.status()["series"][0]["preflight_passed"]
    controller.shutdown()
