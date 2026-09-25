"""Offline checks for the fixed-form series and temperature record."""

from __future__ import annotations

import csv
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest
from time import monotonic, sleep
from PySide6.QtWidgets import QApplication, QGridLayout, QMessageBox
from PySide6.QtCore import QObject, Signal

from thermo_acoustic.application.controller import ApplicationController
from thermo_acoustic.application.experiments import validate_definition
from thermo_acoustic.application.experiment_runner import ExperimentManager
from thermo_acoustic.application.simple_series import NumericRange, SimpleSeriesSettings, compile_simple_series
from thermo_acoustic.application.temperature_recording import TemperatureRecorder
from thermo_acoustic.application.commands import Ad2WaveformFunction, CameraConfigureExposureArgs
from thermo_acoustic.application.commands import (DeviceCommand, DeviceOperation,
                                                  PumpSetFillLevelArgs, TecApplySetpointsArgs,
                                                  WorkflowOperation)
from thermo_acoustic.application.simple_preflight import SimpleSeriesPreflight
from thermo_acoustic.domain.models import ConnectionState, DeviceId, OperatingMode
from thermo_acoustic.hal.registry import DeviceRegistry
from thermo_acoustic.ui.main_window import MainWindow


def settings() -> SimpleSeriesSettings:
    return SimpleSeriesSettings(
        repeats=2, frame_count=3, camera_fps=10, sound_start_s=0,
        sound_run_s=1, laser_start_s=0, laser_run_s=0.1, camera_start_s=0.1,
        frequency_hz=NumericRange(1_000_000, 2_000_000, 2),
        amplitude_v=NumericRange(1, 2, 2), exposure_ms=NumericRange(1, 2, 2),
        roi=(4, 8, 128, 64), flush_unit_index=1, flush_volume_ml=0.1,
        flush_flow_ul_min=500, sweep_enabled=True,
        sweep_width_hz=NumericRange(100_000, 200_000, 2), sweep_period_ms=2,
        temperature_control=True, tec_channel=2,
        temperature_c=NumericRange(20, 30, 2), temperature_wait_s=3,
        temperature_logging=True,
    )


def test_fixed_form_expansion_order_and_flush_count():
    expansion = validate_definition(compile_simple_series(settings()))
    assert len(expansion.experiments) == 64
    assert expansion.steps[0]["type"] == "flush"
    assert [step["type"] for step in expansion.steps[1:3]] == ["tec_set", "wait"]
    assert list(expansion.experiments[0].parameters) == [
        "temperature_c", "frequency_hz", "sweep_width_hz", "amplitude_v", "exposure_ms"]
    assert expansion.experiments[0].parameters["temperature_c"] == 20
    assert expansion.experiments[32].parameters["temperature_c"] == 30
    assert expansion.experiments[0].relative_path.endswith("repeat_0001")
    assert expansion.experiments[1].relative_path.endswith("repeat_0002")
    flushes = [expansion.steps[0]]
    for experiment in expansion.experiments:
        steps = experiment.steps
        flushes += [item for branch in steps[-1]["branches"] for item in branch
                    if item["type"] == "flush"]
    assert len(flushes) == 65
    assert sum(item["args"]["volume_ml"] for item in flushes) == pytest.approx(6.5)
    assert expansion.experiments[0].steps[0]["args"]["roi"] == {
        "x": 4, "y": 8, "width": 128, "height": 64}
    ad2 = expansion.experiments[0].steps[1]["args"]
    assert ad2["laser"]["on_voltage_v"] == 5
    assert ad2["ultrasound"]["sweep_width_hz"] == 100_000


def test_single_step_uses_start_and_sweep_bounds():
    assert NumericRange(1, 2, 1).values("Frequency") == [1]
    assert NumericRange(1, float("nan"), 1).values("Amplitude") == [1]
    assert NumericRange(1, 3, 3).values("Frequency") == [1, 2, 3]
    one_step = compile_simple_series(replace(settings(),
        frequency_hz=NumericRange(1_000_000, 2_000_000, 1),
        amplitude_v=NumericRange(1, 2, 1),
        exposure_ms=NumericRange(1, 2, 1)))
    first = validate_definition(one_step).experiments[0]
    assert first.parameters["frequency_hz"] == 1_000_000
    assert first.parameters["amplitude_v"] == 1
    assert first.parameters["exposure_ms"] == 1
    with pytest.raises(ValueError, match="start frequency"):
        compile_simple_series(replace(settings(), frequency_hz=NumericRange(100, 100, 1)))
    with pytest.raises(ValueError, match="target temperature"):
        compile_simple_series(replace(settings(), temperature_c=NumericRange(85, 85, 1)))


def test_ultrasound_fm_is_center_plus_minus_half_width():
    definition = compile_simple_series(settings())
    ad2 = validate_definition(definition).experiments[0].steps[1]["args"]
    output = ExperimentManager._waveform_args(ad2, 0.001).channels[0]
    assert output.frequency_hz == 1_000_000
    assert output.fm_enabled
    assert output.fm_function is Ad2WaveformFunction.TRIANGLE
    assert output.fm_frequency_hz == 500
    assert output.fm_modulation_index_percent == 5
    assert output.frequency_hz * (1 - output.fm_modulation_index_percent / 100) == 950_000


def test_temperature_csv_has_zero_and_timestamped_samples(tmp_path):
    recorder = TemperatureRecorder(tmp_path / "temperature.csv")
    recorder.add({"timestamp_utc": "2026-09-25T00:00:01+00:00",
                  "monotonic_s": recorder.started_at + 1,
                  "channel_1_c": 20.1, "channel_2_c": 21.1, "error": ""})
    recorder.close()
    recorder._executor.shutdown(wait=True)
    assert recorder.error() is None
    with recorder.path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["elapsed_s"] == "0"
    assert rows[0]["timestamp_utc"]
    assert float(rows[1]["elapsed_s"]) == pytest.approx(1)
    assert rows[1]["channel_2_c"] == "21.1"


def test_explicit_count_preflight_uses_simulated_workers_and_discards_frames():
    app = QApplication.instance() or QApplication(["test-simple-preflight"])
    controller = ApplicationController(DeviceRegistry(mode=OperatingMode.SIMULATION),
                                       mode=OperatingMode.SIMULATION)
    results = []
    controller.command_result.connect(results.append)
    preflight = SimpleSeriesPreflight(controller)
    finished = []
    preflight.finished.connect(lambda *args: finished.append(args))
    controller.start()
    try:
        for device in (DeviceId.AD2, DeviceId.CAMERA, DeviceId.PUMP, DeviceId.VALVE):
            controller.submit(DeviceCommand(device, DeviceOperation.CONNECT))
        deadline = monotonic() + 5
        while monotonic() < deadline and sum(result.operation is DeviceOperation.CONNECT and result.ok
                                              for result in results) < 4:
            app.processEvents(); sleep(0.01)
        assert sum(result.operation is DeviceOperation.CONNECT and result.ok for result in results) == 4
        controller.submit(DeviceCommand(DeviceId.PUMP, DeviceOperation.PUMP_FILL_LEVEL_SET,
                                        PumpSetFillLevelArgs(1.0)))
        deadline = monotonic() + 3
        while monotonic() < deadline and not any(result.operation is DeviceOperation.PUMP_FILL_LEVEL_SET
                                                  for result in results):
            app.processEvents(); sleep(0.01)
        definition = compile_simple_series(replace(settings(), repeats=1, frame_count=2,
            frequency_hz=NumericRange(1_000_000, 1_000_000, 1),
            amplitude_v=NumericRange(1, 1, 1), exposure_ms=NumericRange(1, 2, 2),
            sweep_enabled=False, temperature_control=False, temperature_logging=False,
            roi=(0, 0, 16, 16), flush_unit_index=0))
        preflight.run(definition)
        deadline = monotonic() + 10
        while monotonic() < deadline and not finished:
            app.processEvents(); sleep(0.01)
        assert finished and finished[0][0], finished
        assert sum(result.operation is DeviceOperation.AD2_SOFTWARE_TRIGGER for result in results) == 2
        assert sum(result.operation is DeviceOperation.CAMERA_SEQUENCE_COLLECT for result in results) == 2
    finally:
        controller.shutdown()


def test_failed_preflight_stops_error_state_camera_before_restoring_preview():
    class Controller(QObject):
        command_result = Signal(object)

        def __init__(self):
            super().__init__()
            self.count_preflight_active = True
            self.commands = []
            self.connections = {DeviceId.AD2: ConnectionState.CONNECTED,
                                DeviceId.CAMERA: ConnectionState.ERROR}

        def statuses(self):
            return {device: SimpleNamespace(connection=state)
                    for device, state in self.connections.items()}

        def submit(self, command):
            self.commands.append(command)

    controller = Controller()
    preflight = SimpleSeriesPreflight(controller)
    preflight._active = True
    preflight._fingerprint = "planned-settings"
    finished = []
    preflight.finished.connect(lambda *args: finished.append(args))

    preflight._finish(False, "Camera frame 1/2 timed out")
    stops = [command for command in controller.commands
             if command.operation is DeviceOperation.SAFE_STOP]
    assert {command.device for command in stops} == {DeviceId.AD2, DeviceId.CAMERA}
    assert controller.count_preflight_active
    assert not finished

    for command in stops:
        if command.device is DeviceId.CAMERA:
            controller.connections[DeviceId.CAMERA] = ConnectionState.CONNECTED
        controller.command_result.emit(SimpleNamespace(request_id=command.request_id,
                                                        ok=True, error=None))
    preview = controller.commands[-1]
    assert preview.operation is DeviceOperation.CAMERA_CONTINUOUS_CAPTURE
    assert preview.device is DeviceId.CAMERA
    controller.command_result.emit(SimpleNamespace(request_id=preview.request_id,
                                                    ok=True, error=None))
    assert finished == [(False, "Camera frame 1/2 timed out; camera preview restored",
                         "planned-settings")]
    assert not controller.count_preflight_active


def test_failed_preflight_keeps_camera_responsive_without_reconnect():
    app = QApplication.instance() or QApplication(["test-preflight-recovery"])
    registry = DeviceRegistry(mode=OperatingMode.SIMULATION)
    controller = ApplicationController(registry, mode=OperatingMode.SIMULATION)
    results = []
    controller.command_result.connect(results.append)
    preflight = SimpleSeriesPreflight(controller)
    finished = []
    preflight.finished.connect(lambda *args: finished.append(args))
    controller.start()
    try:
        for device in (DeviceId.AD2, DeviceId.CAMERA, DeviceId.PUMP, DeviceId.VALVE):
            controller.submit(DeviceCommand(device, DeviceOperation.CONNECT))
        deadline = monotonic() + 5
        while monotonic() < deadline and sum(result.operation is DeviceOperation.CONNECT and result.ok
                                              for result in results) < 4:
            app.processEvents(); sleep(0.01)
        assert sum(result.operation is DeviceOperation.CONNECT and result.ok for result in results) == 4
        controller.submit(DeviceCommand(DeviceId.PUMP, DeviceOperation.PUMP_FILL_LEVEL_SET,
                                        PumpSetFillLevelArgs(1.0)))
        deadline = monotonic() + 3
        while monotonic() < deadline and not any(result.operation is DeviceOperation.PUMP_FILL_LEVEL_SET
                                                  for result in results):
            app.processEvents(); sleep(0.01)

        camera = registry.by_id(DeviceId.CAMERA).device
        original_poll = camera.poll_buffered_sequence_frame

        def fail_once(timeout_ms):
            camera.poll_buffered_sequence_frame = original_poll
            raise RuntimeError("injected frame read failure")

        camera.poll_buffered_sequence_frame = fail_once
        definition = compile_simple_series(replace(settings(), repeats=1, frame_count=2,
            frequency_hz=NumericRange(1_000_000, 1_000_000, 1),
            amplitude_v=NumericRange(1, 1, 1), exposure_ms=NumericRange(1, 1, 1),
            sweep_enabled=False, temperature_control=False, temperature_logging=False,
            roi=(0, 0, 16, 16), flush_unit_index=0))
        preflight.run(definition)
        deadline = monotonic() + 10
        while monotonic() < deadline and not finished:
            app.processEvents(); sleep(0.01)
        assert finished and not finished[0][0]
        assert "injected frame read failure" in finished[0][1]
        assert "camera preview restored" in finished[0][1]
        assert any(result.operation is DeviceOperation.SAFE_STOP and result.device is DeviceId.CAMERA
                   and result.ok for result in results)

        controller.submit(DeviceCommand(DeviceId.CAMERA, DeviceOperation.CAMERA_SNAPSHOT_CAPTURE))
        deadline = monotonic() + 3
        while monotonic() < deadline and not any(result.operation is DeviceOperation.CAMERA_SNAPSHOT_CAPTURE
                                                  for result in results):
            app.processEvents(); sleep(0.01)
        assert any(result.operation is DeviceOperation.CAMERA_SNAPSHOT_CAPTURE and result.ok
                   for result in results)
    finally:
        controller.shutdown()


def test_simple_series_runs_on_simulated_workers_and_logs_temperature(tmp_path):
    app = QApplication.instance() or QApplication(["test-simple-series"])
    controller = ApplicationController(DeviceRegistry(mode=OperatingMode.SIMULATION),
                                       mode=OperatingMode.SIMULATION)
    results = []
    controller.command_result.connect(results.append)
    controller.start()
    try:
        for device in (DeviceId.AD2, DeviceId.CAMERA, DeviceId.PUMP, DeviceId.VALVE, DeviceId.TEC):
            controller.submit(DeviceCommand(device, DeviceOperation.CONNECT))
        deadline = monotonic() + 5
        while monotonic() < deadline and sum(result.operation is DeviceOperation.CONNECT and result.ok
                                              for result in results) < 5:
            app.processEvents(); sleep(0.01)
        assert sum(result.operation is DeviceOperation.CONNECT and result.ok for result in results) == 5
        controller.submit(DeviceCommand(DeviceId.TEC, DeviceOperation.TEC_SETPOINTS_APPLY,
                                        TecApplySetpointsArgs(25.0)))
        controller.submit(DeviceCommand(DeviceId.PUMP, DeviceOperation.PUMP_FILL_LEVEL_SET,
                                        PumpSetFillLevelArgs(1.0)))
        deadline = monotonic() + 3
        while monotonic() < deadline and not all(any(result.operation is operation for result in results)
                for operation in (DeviceOperation.TEC_SETPOINTS_APPLY, DeviceOperation.PUMP_FILL_LEVEL_SET)):
            app.processEvents(); sleep(0.01)
        definition = compile_simple_series(replace(settings(), repeats=1, frame_count=2,
            frequency_hz=NumericRange(1_000_000, 1_000_000, 1),
            amplitude_v=NumericRange(1, 1, 1), exposure_ms=NumericRange(1, 1, 1),
            sweep_enabled=False, temperature_control=False, temperature_logging=True,
            roi=(0, 0, 16, 16), flush_unit_index=0))
        folder = controller.experiments.queue(definition, tmp_path)
        assert controller.experiments.start()
        deadline = monotonic() + 15
        while monotonic() < deadline and controller.experiments.status()["state"] not in {"completed", "failed"}:
            app.processEvents(); sleep(0.01)
        assert controller.experiments.status()["state"] == "completed"
        with (folder / "metadata" / "temperature.csv").open(newline="", encoding="utf-8") as stream:
            samples = list(csv.DictReader(stream))
        assert len(samples) >= 2
        assert samples[0]["elapsed_s"] == "0"
        assert any(row["channel_1_c"] and row["channel_2_c"] for row in samples[1:])
        assert len(list(folder.rglob("*.tif"))) == 2
        assert sum(result.operation is DeviceOperation.AD2_SOFTWARE_TRIGGER for result in results) == 1
    finally:
        controller.shutdown()


def test_simple_tab_imports_live_camera_roi_and_exposure():
    app = QApplication.instance() or QApplication(["test-simple-ui"])
    controller = ApplicationController(DeviceRegistry(mode=OperatingMode.SIMULATION),
                                       mode=OperatingMode.SIMULATION)
    window = MainWindow(controller)
    results = []
    controller.command_result.connect(results.append)
    controller.start()
    try:
        controller.submit(DeviceCommand(DeviceId.CAMERA, DeviceOperation.CONNECT))
        deadline = monotonic() + 3
        while monotonic() < deadline and not any(result.operation is DeviceOperation.CONNECT for result in results):
            app.processEvents(); sleep(0.01)
        controller.submit(DeviceCommand(DeviceId.CAMERA, DeviceOperation.CAMERA_EXPOSURE_CONFIGURE,
                                        CameraConfigureExposureArgs(2.5)))
        deadline = monotonic() + 3
        while monotonic() < deadline and not any(result.operation is DeviceOperation.CAMERA_EXPOSURE_CONFIGURE
                                                  for result in results):
            app.processEvents(); sleep(0.01)
        window.experiment_panel._import_camera()
        deadline = monotonic() + 3
        while monotonic() < deadline and not any(result.operation is DeviceOperation.CAMERA_SETTINGS_READ
                                                  for result in results):
            app.processEvents(); sleep(0.01)
        panel = window.experiment_panel
        assert "only Start is used" in panel.frequency[2].toolTip()
        for controls in (panel.frequency, panel.amplitude, panel.sweep_width,
                         panel.temperature, panel.exposure):
            layout = controls[0].parentWidget().layout()
            assert isinstance(layout, QGridLayout)
            for column, (caption, control) in enumerate(zip(("Start", "Stop", "Steps"), controls)):
                assert layout.itemAtPosition(0, column).widget().text() == caption
                assert layout.itemAtPosition(1, column).widget() is control
        assert (panel.roi_x.value(), panel.roi_y.value(),
                panel.roi_width.value(), panel.roi_height.value()) == (0, 0, 2048, 1024)
        assert panel.exposure[0].value() == panel.exposure[1].value() == 2.5
        assert panel.exposure[2].value() == 1
    finally:
        window.close()


def test_failed_preflight_warning_remains_visible_after_recovery(monkeypatch):
    QApplication.instance() or QApplication(["test-preflight-warning-ui"])
    controller = ApplicationController(DeviceRegistry(mode=OperatingMode.SIMULATION),
                                       mode=OperatingMode.SIMULATION)
    window = MainWindow(controller)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _parent, title, message: warnings.append((title, message)))
    try:
        panel = window.experiment_panel
        panel._preflight_finished(False, "Camera frame timed out; camera preview restored", "settings")
        assert "Preflight failed: Camera frame timed out" in panel.state_label.text()
        assert warnings == [("Preflight failed", "Camera frame timed out; camera preview restored")]
    finally:
        window.close()


def test_temperature_log_open_failure_stops_before_fluidics(tmp_path, monkeypatch):
    import thermo_acoustic.application.experiment_runner as runner_module
    app = QApplication.instance() or QApplication(["test-temp-log-fail"])
    controller = ApplicationController(DeviceRegistry(mode=OperatingMode.SIMULATION),
                                       mode=OperatingMode.SIMULATION)
    events = []
    controller.command_event.connect(events.append)
    def fail_open(_path):
        raise OSError("disk unavailable")
    monkeypatch.setattr(runner_module, "TemperatureRecorder", fail_open)
    definition = compile_simple_series(replace(settings(), repeats=1, frame_count=2,
        frequency_hz=NumericRange(1_000_000, 1_000_000, 1),
        amplitude_v=NumericRange(1, 1, 1), exposure_ms=NumericRange(1, 1, 1),
        sweep_enabled=False, temperature_control=False,
        roi=(0, 0, 16, 16), flush_unit_index=0))
    controller.experiments.queue(definition, tmp_path)
    controller.experiments.start()
    deadline = monotonic() + 2
    while monotonic() < deadline and controller.experiments.status()["state"] != "failed":
        app.processEvents(); sleep(0.01)
    assert controller.experiments.status()["state"] == "failed"
    assert not any(event.operation is WorkflowOperation.FLUSH for event in events)
    controller.shutdown()


def test_start_warns_for_missing_or_stale_count_preflight(tmp_path):
    app = QApplication.instance() or QApplication(["test-preflight-warning"])
    controller = ApplicationController(DeviceRegistry(mode=OperatingMode.SIMULATION),
                                       mode=OperatingMode.SIMULATION)
    definition = compile_simple_series(replace(settings(), repeats=1,
        frequency_hz=NumericRange(1_000_000, 1_000_000, 1),
        amplitude_v=NumericRange(1, 1, 1), exposure_ms=NumericRange(1, 1, 1),
        sweep_enabled=False, temperature_control=False, temperature_logging=False))
    manager = controller.experiments
    manager.queue(definition, tmp_path)
    warnings = []
    manager.confirm_unchecked = lambda message: warnings.append(message) or False
    assert not manager.start()
    assert "not passed" in warnings[0]
    manager.record_simple_preflight(json.dumps(definition, sort_keys=True), 1, None)
    assert manager.start()
    controller.shutdown()
