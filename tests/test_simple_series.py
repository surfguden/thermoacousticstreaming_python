"""Offline checks for the fixed-form series and temperature record.

Tests that construct `SimpleSeriesPanel` directly (not `MainWindow`) are
panel-level automation: they drive the same Qt widgets and signal/slot
paths a human click would, but are not literal mouse/keyboard input into
the running application window, and no other panel (status dashboard,
Z-stack, menus) is present. Do not read a passing panel-level test as
proof that a full-window operator session behaves identically in every
respect.
"""

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
        temperature_logging=True, description="Offline simple series",
    )


def test_batch_syringe_preflight_totals_and_queue_edits(tmp_path):
    app = QApplication.instance() or QApplication(["test-batch-syringe"])
    controller = ApplicationController(DeviceRegistry(), mode=OperatingMode.SIMULATION)
    controller.start()
    try:
        results = []
        controller.command_result.connect(results.append)
        controller.submit(DeviceCommand(DeviceId.PUMP, DeviceOperation.CONNECT))
        deadline = monotonic() + 3
        while monotonic() < deadline and not any(result.operation is DeviceOperation.CONNECT and result.ok
                                                   for result in results):
            app.processEvents(); sleep(0.01)
        controller.submit(DeviceCommand(DeviceId.PUMP, DeviceOperation.PUMP_FILL_LEVEL_SET,
                                        PumpSetFillLevelArgs(1.0, unit_index=0)))
        deadline = monotonic() + 3
        while monotonic() < deadline and not any(result.operation is DeviceOperation.PUMP_FILL_LEVEL_SET
                                                   and result.ok for result in results):
            app.processEvents(); sleep(0.01)
        base = replace(settings(), repeats=1, flush_unit_index=0,
                       frequency_hz=NumericRange(1_000_000, 1_000_000, 1),
                       amplitude_v=NumericRange(1, 1, 1),
                       exposure_ms=NumericRange(1, 1, 1), sweep_enabled=False,
                       temperature_control=False, temperature_logging=False)
        manager = controller.experiments
        first = manager.queue(compile_simple_series(base), tmp_path)
        second = manager.queue(compile_simple_series(replace(base, description="Second")), tmp_path)
        assert manager._flush_totals(list(manager._queued)) == {0: 0.4}
        finished = []
        manager.preflight_syringe(lambda ok, message: finished.append((ok, message)))
        deadline = monotonic() + 3
        while monotonic() < deadline and not finished:
            app.processEvents(); sleep(0.01)
        assert finished[0][0], finished
        assert manager.status()["syringe_preflight_passed"]
        third = manager.queue(compile_simple_series(replace(base, description="Third")), tmp_path)
        assert not manager.status()["syringe_preflight_passed"]
        manager.remove_queued(third)
        assert third.is_dir()
        assert manager.status()["queued_series"] == 2
        assert not manager.status()["syringe_preflight_passed"]
        manager.update_queued(second, compile_simple_series(replace(base, description="Edited",
            exposure_ms=NumericRange(2, 2, 1))))
        assert manager.queued_definition(second)["description"] == "Edited"
        assert first.is_dir()
    finally:
        controller.shutdown()


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
    assert expansion.experiments[0].relative_path.split("/") == [
        "temperature_20.0", "frequency_1000000.0", "sweep_width_100000.0",
        "amplitude_1.0", "exposure_1.0", "repeat_0001"]
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


def test_temperature_wait_for_stability_is_additive_and_opt_in():
    # Default-off: compiles byte-identically to the pre-existing fixed-wait
    # shape (no behavior change for any series that doesn't opt in).
    default_steps = compile_simple_series(settings())["steps"]
    assert [step["type"] for step in default_steps[1]["steps"][:2]] == ["tec_set", "wait"]

    stable = replace(settings(), temperature_wait_for_stability=True,
                     temperature_tolerance_c=0.3, temperature_min_settle_s=2,
                     temperature_max_wait_s=120)
    stable_steps = compile_simple_series(stable)["steps"]
    temperature_steps = stable_steps[1]["steps"][:3]
    assert [step["type"] for step in temperature_steps] == ["tec_set", "tec_wait_stable", "wait"]
    wait_stable_args = temperature_steps[1]["args"]
    assert wait_stable_args["tolerance_c"] == 0.3
    assert wait_stable_args["min_settle_s"] == 2
    assert wait_stable_args["max_wait_s"] == 120
    assert wait_stable_args["channels"] == [stable.tec_channel]
    # The hold step (temperature_wait_s) is unchanged in meaning when
    # stability-wait is on -- it is now an additional hold applied only
    # after stability, not the sole timing control.
    assert temperature_steps[2]["args"]["seconds"] == stable.temperature_wait_s
    validate_definition(compile_simple_series(stable))


def test_temperature_wait_for_stability_rejects_invalid_bounds():
    with pytest.raises(ValueError, match="tolerance"):
        compile_simple_series(replace(settings(), temperature_wait_for_stability=True,
                                      temperature_tolerance_c=-1))
    with pytest.raises(ValueError, match="settle"):
        compile_simple_series(replace(settings(), temperature_wait_for_stability=True,
                                      temperature_min_settle_s=-1))
    with pytest.raises(ValueError, match="maximum wait"):
        compile_simple_series(replace(settings(), temperature_wait_for_stability=True,
                                      temperature_max_wait_s=0))


def test_temperature_max_wait_below_one_second_compiles_without_a_software_floor():
    # No compile-time floor tied to TecWaitStableArgs' own poll_interval_s
    # default -- that default is a software polling choice, not a device
    # requirement, and packaging it as a rule this field must obey would be
    # exactly the kind of unnecessary restriction this project avoids.
    definition = compile_simple_series(replace(settings(), temperature_wait_for_stability=True,
                                                temperature_max_wait_s=0.5))
    temperature_steps = definition["steps"][1]["steps"][:3]
    assert temperature_steps[1]["args"]["max_wait_s"] == 0.5


def test_ui_configured_short_max_wait_actually_completes(tmp_path):
    # The execution-level proof that a sub-1s max_wait_s is genuinely
    # executable (not just compilable), through the real UI panel path
    # this time, not a hand-authored definition -- see
    # test_tec_wait_stable_with_a_sub_one_second_max_wait_actually_runs in
    # test_experiments.py for the same fix proven against a raw definition.
    app = QApplication.instance() or QApplication(["test-short-max-wait"])
    controller, panel, results, events = _connected_temperature_series_harness(app, repeats=1)
    try:
        panel.temperature[2].setValue(1)  # one temperature point, simplifies this check
        panel.temperature_max_wait.setValue(0.1)
        definition = panel._definition()
        folder = controller.experiments.queue(definition, tmp_path)
        assert controller.experiments.start()
        status = _wait_until_terminal(app, controller, timeout=15)
        assert status["state"] == "completed", status
        wait_stable = next(event for event in events
                           if event.operation is DeviceOperation.TEC_WAIT_STABLE and event.state == "completed")
        assert wait_stable.arguments.poll_interval_s == 0.1
    finally:
        panel.close()
        controller.shutdown()


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


def test_disabled_temperature_and_sweep_keep_fixed_folder_levels():
    definition = compile_simple_series(replace(settings(), temperature_control=False,
                                               sweep_enabled=False))
    path = validate_definition(definition).experiments[0].relative_path.split("/")
    assert path[0] == "temperature_NaN"
    assert path[2] == "sweep_width_NaN"
    assert path[-1] == "repeat_0001"


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
    from thermo_acoustic.application.simple_preflight import camera_preflight_fingerprint
    from thermo_acoustic.application.experiments import validate_definition
    manager.record_camera_preflight(camera_preflight_fingerprint(validate_definition(definition)))
    assert manager.start()
    controller.shutdown()


def _connected_temperature_series_harness(app, *, repeats=2, hold_s=0.3):
    # Shared setup for the discriminating end-to-end tests below: connects
    # every relevant device, then drives the real panel widgets (not
    # SimpleSeriesSettings directly) to a two-temperature-point,
    # wait-for-stability series with a nonzero min-settle and a nonzero
    # post-stability hold and a flush present. Returns
    # (controller, panel, results, events) already connected; callers queue
    # + start + assert their own scenario.
    controller = ApplicationController(DeviceRegistry(mode=OperatingMode.SIMULATION),
                                       mode=OperatingMode.SIMULATION)
    # Only the panel under test, not the full MainWindow: constructing every
    # other panel (status dashboard, Z-stack, etc.) adds no coverage here
    # and multiplies per-status_changed-signal work across this test's many
    # device round trips -- an earlier version of this harness built the
    # full MainWindow and took 5+ minutes per test; this takes ~20s.
    from thermo_acoustic.ui.simple_series_panel import SimpleSeriesPanel
    panel = SimpleSeriesPanel(controller)
    results = []
    events = []
    controller.command_result.connect(results.append)
    controller.command_event.connect(events.append)
    controller.start()
    for device in (DeviceId.AD2, DeviceId.CAMERA, DeviceId.PUMP, DeviceId.VALVE, DeviceId.TEC):
        controller.submit(DeviceCommand(device, DeviceOperation.CONNECT))
    deadline = monotonic() + 5
    while monotonic() < deadline and sum(result.operation is DeviceOperation.CONNECT and result.ok
                                          for result in results) < 5:
        app.processEvents(); sleep(0.01)
    assert sum(result.operation is DeviceOperation.CONNECT and result.ok for result in results) == 5
    controller.submit(DeviceCommand(DeviceId.PUMP, DeviceOperation.PUMP_FILL_LEVEL_SET,
                                    PumpSetFillLevelArgs(1.0)))
    deadline = monotonic() + 3
    while monotonic() < deadline and not any(result.operation is DeviceOperation.PUMP_FILL_LEVEL_SET
                                              and result.ok for result in results):
        app.processEvents(); sleep(0.01)

    panel.description.setText("UI temperature series trace test")
    panel.repeats.setValue(repeats)
    panel.frames.setValue(2)
    panel.fps.setValue(10)
    panel.sweep_enabled.setChecked(False)
    for widget, value in zip(panel.frequency, (1_000_000, 1_000_000, 1)):
        widget.setValue(value)
    for widget, value in zip(panel.amplitude, (1, 1, 1)):
        widget.setValue(value)
    for widget, value in zip(panel.exposure, (1, 1, 1)):
        widget.setValue(value)
    panel.roi_x.setValue(0); panel.roi_y.setValue(0)
    panel.roi_width.setValue(16); panel.roi_height.setValue(16)
    panel.pump_unit.setCurrentIndex(0)
    panel.volume.setValue(0.05)
    panel.flow.setValue(500)
    panel.temperature_control.setChecked(True)
    panel.tec_channel.setCurrentIndex(0)
    for widget, value in zip(panel.temperature, (20, 25, 2)):
        widget.setValue(value)
    panel.temperature_wait_for_stability.setChecked(True)
    panel.temperature_tolerance.setValue(0.5)
    panel.temperature_min_settle.setValue(0.05)
    panel.temperature_max_wait.setValue(5)
    panel.temp_wait.setValue(hold_s)
    return controller, panel, results, events


_TERMINAL_STATES = {"completed", "failed", "stopped", "aborted"}


def _wait_until_terminal(app, controller, timeout=45):
    deadline = monotonic() + timeout
    while monotonic() < deadline and controller.experiments.status()["state"] not in _TERMINAL_STATES:
        app.processEvents(); sleep(0.01)
    return controller.experiments.status()


def _wait_until_n_experiments_completed(app, controller, n, timeout=30):
    deadline = monotonic() + timeout
    while monotonic() < deadline and controller.experiments.status()["batch_completed_experiments"] < n:
        app.processEvents(); sleep(0.01)
    assert controller.experiments.status()["batch_completed_experiments"] >= n, controller.experiments.status()


def test_ui_configured_parameter_sweep_with_repeats_runs_every_combination(tmp_path):
    # Representative check #2 (parameter sweep + repeats, through the real
    # panel): distinct from the main trace test below, which uses a single
    # frequency/amplitude/exposure value throughout and varies only the
    # temperature axis. A genuine multi-value sweep (2 frequencies) x 2
    # repeats x 1 temperature point must run all 4 combinations, in the
    # folder-naming order the compiler promises, via real device dispatch
    # -- not only via the structural (no-device) cartesian-expansion checks
    # in test_fixed_form_expansion_order_and_flush_count.
    #
    # PANEL-LEVEL AUTOMATION, NOT A FULL-WINDOW OPERATION: this constructs
    # SimpleSeriesPanel directly and sets its widgets programmatically. It
    # exercises the same Qt signal/slot code a human click would (widget
    # valueChanged -> _preview()/_settings(), button click ->
    # controller.submit()), but it is not literal mouse/keyboard input into
    # a running MainWindow, and no other panel (status dashboard, Z-stack,
    # menus) is present or exercised. Do not read this as proof that a
    # human operating the actual application window would see identical
    # behavior in every respect (e.g. window-level event filters, focus
    # handling, or cross-panel interactions are untouched by this test).
    app = QApplication.instance() or QApplication(["test-ui-parameter-sweep"])
    controller, panel, results, events = _connected_temperature_series_harness(app, repeats=2)
    try:
        panel.temperature[2].setValue(1)  # one temperature point, isolates the sweep axis
        for widget, value in zip(panel.frequency, (1_000_000, 2_000_000, 2)):
            widget.setValue(value)
        definition = panel._definition()
        folder = controller.experiments.queue(definition, tmp_path)
        assert controller.experiments.start()
        status = _wait_until_terminal(app, controller)
        assert status["state"] == "completed", status

        manifest = json.loads((folder / "metadata" / "manifest.json").read_text())
        assert [item["parameters"]["frequency_hz"] for item in manifest["experiments"]] == [
            1_000_000.0, 1_000_000.0, 2_000_000.0, 2_000_000.0]  # 2 frequencies x 2 repeats, in order
        status_doc = json.loads((folder / "metadata" / "status.json").read_text())
        assert status_doc["finalized_outcome"] == "completed"
        assert status_doc["requested_experiments"] == status_doc["experiments_completed"] == 4
    finally:
        panel.close()
        controller.shutdown()


def test_ui_configured_temperature_series_runs_pump_valve_camera_ad2_tec_in_order(tmp_path):
    # Discriminating end-to-end check, built from the real UI entry point
    # (SimpleSeriesPanel), not a hand-written definition: two temperature
    # points x two repeats, wait-for-stability enabled with a nonzero
    # min-settle and a nonzero post-stability hold, flush present, every
    # relevant device connected. Asserts the actual command/event ORDER,
    # not just a final "completed" state -- this is the one combination
    # (TEC multi-point + repeats + pump/valve together) nothing else in
    # the suite covers.
    app = QApplication.instance() or QApplication(["test-ui-temperature-series"])
    controller, panel, results, events = _connected_temperature_series_harness(app)
    try:
        definition = panel._definition()
        assert [step["type"] for step in definition["steps"][1]["steps"][:3]] == [
            "tec_set", "tec_wait_stable", "wait"]

        folder = controller.experiments.queue(definition, tmp_path)
        assert controller.experiments.start()
        status = _wait_until_terminal(app, controller)
        assert status["state"] == "completed", status

        completed = [event for event in events if event.state == "completed"]

        def first_index(operation, after=0):
            return next(i for i, event in enumerate(completed) if i >= after
                       and event.operation is operation)

        # 1. The series-level flush (before any temperature point) precedes
        #    the first TEC setpoint.
        series_flush = first_index(WorkflowOperation.FLUSH)
        first_tec_set = first_index(DeviceOperation.TEC_SETPOINTS_APPLY)
        assert series_flush < first_tec_set

        # 2. Exactly two temperature points were commanded, in order, each
        #    followed by a wait-stable for the SAME target before any camera
        #    arming for that point's experiments.
        tec_set_events = [event for event in completed if event.operation is DeviceOperation.TEC_SETPOINTS_APPLY]
        assert len(tec_set_events) == 2
        assert [event.arguments.target_temperature_c for event in tec_set_events] == [20.0, 25.0]
        assert all(event.arguments.channels == (1,) for event in tec_set_events)
        tec_wait_events = [event for event in completed if event.operation is DeviceOperation.TEC_WAIT_STABLE]
        assert len(tec_wait_events) == 2
        assert [event.arguments.target_temperature_c for event in tec_wait_events] == [20.0, 25.0]
        hold_events = [event for event in completed if event.operation is WorkflowOperation.WAIT]
        assert len(hold_events) == 2  # one post-stability hold per temperature point

        # 3. Within each point, tec_set -> tec_wait_stable -> (repeats'
        #    experiments) -- the second point's tec_set must not be
        #    commanded until the first point's own repeats (2 of them) and
        #    their post-acquisition parallel cleanup have all finished.
        second_tec_set = first_index(DeviceOperation.TEC_SETPOINTS_APPLY, after=first_tec_set + 1)
        first_point_triggers = [i for i, event in enumerate(completed)
                               if event.operation is DeviceOperation.AD2_SOFTWARE_TRIGGER and i < second_tec_set]
        assert len(first_point_triggers) == 2  # both repeats of the first point ran before the second point started

        # 4. Within one experiment, the real execution order matches the
        #    validator's required order, not merely that the validator
        #    allowed it: tec_wait_stable, then the hold, both complete
        #    before camera/AD2 are armed, and digital output is armed
        #    before the trigger fires, not merely "sometime before".
        first_trigger = first_point_triggers[0]
        first_tec_wait = completed.index(tec_wait_events[0])
        first_hold = completed.index(hold_events[0])
        arm_camera = first_index(DeviceOperation.CAMERA_SEQUENCE_ARM)
        arm_waveform = first_index(DeviceOperation.AD2_WAVEFORM_START)
        arm_digital = first_index(DeviceOperation.AD2_DIGITAL_OUTPUT_START)
        collect = first_index(DeviceOperation.CAMERA_SEQUENCE_COLLECT, after=first_trigger)
        assert first_tec_set < first_tec_wait < first_hold < arm_camera
        assert arm_camera < arm_waveform < arm_digital < first_trigger < collect

        # 4b. The post-stability hold actually occupied wall-clock time --
        #     not merely that the "wait" step appeared in the compiled
        #     definition and was skipped or short-circuited.
        elapsed = (hold_events[0].timestamp - tec_wait_events[0].timestamp).total_seconds()
        assert elapsed >= 0.3 * 0.8  # generous margin against scheduling jitter

        # 5. Per-experiment flush/save overlap resolves before the next
        #    experiment's camera is reconfigured -- confirmed by the
        #    corresponding AD2_DIGITAL_OUTPUT_STOP (end of wait_outputs)
        #    preceding the next experiment's CAMERA_SEQUENCE_CONFIGURE.
        #    CAMERA_SEQUENCE_CONFIGURE fires once more than the experiment
        #    count: _configure_all_before_fluidics validates this series'
        #    one unique camera/AD2 combination up front, before any flush or
        #    TEC action, in addition to each experiment's own leaf node
        #    re-applying it immediately before that experiment runs -- the
        #    per-experiment occurrences are the last four, in order.
        stop_digital = [i for i, event in enumerate(completed)
                       if event.operation is DeviceOperation.AD2_DIGITAL_OUTPUT_STOP]
        configure_camera = [i for i, event in enumerate(completed)
                           if event.operation is DeviceOperation.CAMERA_SEQUENCE_CONFIGURE]
        assert len(stop_digital) == 4  # one per experiment (2 points x 2 repeats)
        assert len(configure_camera) == 5  # 1 series-level validation + 4 per-experiment
        per_experiment_configure = configure_camera[-4:]
        assert stop_digital[0] < per_experiment_configure[1]

        manifest = json.loads((folder / "metadata" / "manifest.json").read_text())
        assert [item["parameters"]["temperature_c"] for item in manifest["experiments"]] == [20.0, 20.0, 25.0, 25.0]
        status_doc = json.loads((folder / "metadata" / "status.json").read_text())
        assert status_doc["finalized_outcome"] == "completed"
        assert status_doc["requested_experiments"] == status_doc["experiments_completed"] == 4
        assert status_doc["experiments_failed"] == 0
    finally:
        panel.close()
        controller.shutdown()


def test_stability_wait_failure_stops_series_before_any_point_starts(tmp_path):
    # Failure injection #1: the TEC never reaches tolerance (simulated
    # controller is monkeypatched to hold an unreachable reading), so
    # tec_wait_stable times out during the FIRST temperature point, before
    # any "experiment" node has even begun. No experiment should ever
    # start, the second point's tec_set must never fire, and the series
    # must end failed with a consistent (all-zero) experiment count --
    # not silently advancing, and not miscounting a failure that happened
    # before any experiment existed as an "experiment failure".
    app = QApplication.instance() or QApplication(["test-stability-wait-failure"])
    controller, panel, results, events = _connected_temperature_series_harness(app)
    try:
        tec_device = controller.registry.by_id(DeviceId.TEC).device
        original_read_status = tec_device.read_status
        def stuck_read_status(channels=None):
            result = original_read_status(channels)
            # Reported temperature never moves, regardless of target --
            # within_tolerance can never become true.
            return {channel: status.__class__(channel=status.channel, current_temperature_c=999.0,
                                              target_temperature_c=status.target_temperature_c,
                                              output_stage_static_on=status.output_stage_static_on,
                                              ready=status.ready)
                   for channel, status in result.items()}
        tec_device.read_status = stuck_read_status

        panel.temperature_max_wait.setValue(1.0)  # >= the fixed poll interval, so this exercises the
                                                   # real timeout path, not the separate argument-
                                                   # construction failure covered by the test above
        definition = panel._definition()
        folder = controller.experiments.queue(definition, tmp_path)
        assert controller.experiments.start()
        status = _wait_until_terminal(app, controller, timeout=10)
        assert status["state"] == "failed", status

        completed_ops = [event.operation for event in events if event.state == "completed"]
        assert DeviceOperation.TEC_SETPOINTS_APPLY in completed_ops
        assert completed_ops.count(DeviceOperation.TEC_SETPOINTS_APPLY) == 1  # second point's tec_set never fired
        assert DeviceOperation.CAMERA_SEQUENCE_ARM not in completed_ops
        assert DeviceOperation.AD2_SOFTWARE_TRIGGER not in completed_ops

        # ExperimentManager.status()["failure_reason"] is only populated
        # transiently while _finish_failure_when_safe() runs -- it is reset
        # to None once the series has fully finalized, which has already
        # happened by this point (status["state"] == "failed" above). The
        # persisted status.json is the durable record of why it failed.
        status_doc = json.loads((folder / "metadata" / "status.json").read_text())
        assert "did not stabilize" in status_doc["error"]
        assert status_doc["finalized_outcome"] == "failed"
        assert status_doc["experiments_started"] == 0
        assert status_doc["experiments_completed"] == 0
        assert status_doc["experiments_failed"] == 0  # no experiment had started yet to fail
    finally:
        panel.close()
        controller.shutdown()


def test_acquisition_failure_within_a_series_stops_before_the_next_repeat(tmp_path):
    # Failure injection #2: the first repeat's camera acquisition fails
    # (reusing the same missing-timestamp-style fault as the pre-existing
    # test_missing_sdk_timestamp_fails_acquisition_without_saving_frames,
    # but inside a multi-repeat/multi-point series instead of a
    # single-experiment one, which that test does not cover). Must stop
    # before the second repeat and before the second temperature point --
    # not just before the next queued SERIES, which
    # test_save_failure_stops_later_queued_series_without_overwriting
    # already covers at the series level.
    app = QApplication.instance() or QApplication(["test-acquisition-failure"])
    controller, panel, results, events = _connected_temperature_series_harness(app)
    try:
        camera = controller.registry.by_id(DeviceId.CAMERA).device
        camera.finish_buffered_sequence = lambda: (camera.stop_capture(), ())[1]

        definition = panel._definition()
        folder = controller.experiments.queue(definition, tmp_path)
        assert controller.experiments.start()
        status = _wait_until_terminal(app, controller)
        assert status["state"] == "failed", status

        completed_ops = [event.operation for event in events if event.state == "completed"]
        assert completed_ops.count(DeviceOperation.CAMERA_SEQUENCE_CONFIGURE) <= 2  # series-level validation + 1 experiment, never a 2nd repeat
        assert completed_ops.count(DeviceOperation.TEC_SETPOINTS_APPLY) == 1  # second point never started

        manifest = json.loads((folder / "metadata" / "manifest.json").read_text())
        leaf = folder / manifest["experiments"][0]["relative_path"]
        assert not leaf.exists()  # incomplete experiment discarded
        assert not list(folder.rglob("*.tif"))

        status_doc = json.loads((folder / "metadata" / "status.json").read_text())
        assert status_doc["finalized_outcome"] == "failed"
        assert status_doc["experiments_started"] == 1
        assert status_doc["experiments_completed"] == 0
        assert status_doc["experiments_failed"] == 1
    finally:
        panel.close()
        controller.shutdown()


def test_save_failure_within_a_series_stops_before_the_next_repeat(tmp_path):
    # Failure injection #3: the first experiment's file save fails
    # (reusing the fault-injection pattern from the pre-existing
    # test_save_failure_stops_later_queued_series_without_overwriting,
    # which only checks the next-QUEUED-SERIES case -- this checks the
    # next-experiment-WITHIN-the-same-series case, which that test does
    # not cover).
    app = QApplication.instance() or QApplication(["test-save-failure"])
    controller, panel, results, events = _connected_temperature_series_harness(app)
    try:
        definition = panel._definition()
        folder = controller.experiments.queue(definition, tmp_path)
        storage = controller.experiments._queued[0][1]
        def fail_save(*_args, **_kwargs):
            raise OSError("simulated disk failure")
        storage.save_frames = fail_save
        assert controller.experiments.start()
        status = _wait_until_terminal(app, controller)
        assert status["state"] == "failed", status

        completed_ops = [event.operation for event in events if event.state == "completed"]
        assert completed_ops.count(DeviceOperation.CAMERA_SEQUENCE_CONFIGURE) <= 2
        assert completed_ops.count(DeviceOperation.TEC_SETPOINTS_APPLY) == 1

        status_doc = json.loads((folder / "metadata" / "status.json").read_text())
        assert status_doc["finalized_outcome"] == "failed"
        assert "simulated disk failure" in status_doc["error"]
        assert status_doc["experiments_started"] == 1
        assert status_doc["experiments_completed"] == 0
        assert status_doc["experiments_failed"] == 1
    finally:
        panel.close()
        controller.shutdown()


def test_lifecycle_counts_are_persisted_before_the_series_ends(tmp_path):
    # Correction: record_experiment_started/completed/failed() previously
    # only incremented in-memory counters -- status.json was not rewritten
    # until the series' own next status() call (the initial "running" or
    # the final terminal one), so a crash between experiments would leave
    # status.json showing stale, pre-increment counts. Fixed: each of the
    # three now re-persists immediately. Proven here by reading status.json
    # from disk WHILE the series is still "running", not only afterward.
    app = QApplication.instance() or QApplication(["test-mid-run-persistence"])
    controller, panel, results, events = _connected_temperature_series_harness(app, repeats=2)
    try:
        definition = panel._definition()
        folder = controller.experiments.queue(definition, tmp_path)
        assert controller.experiments.start()
        _wait_until_n_experiments_completed(app, controller, 1, timeout=30)
        # The series has not finished (4 experiments total) -- read the
        # live file now, mid-series, not after completion.
        live_status = controller.experiments.status()
        assert live_status["state"] == "running", live_status
        on_disk = json.loads((folder / "metadata" / "status.json").read_text())
        assert on_disk["state"] == "running"
        assert on_disk["experiments_started"] >= 1
        assert on_disk["experiments_completed"] == 1
        assert on_disk["finalized_outcome"] is None  # not finished yet -- must not be set early
        final_status = _wait_until_terminal(app, controller)
        assert final_status["state"] == "completed", final_status
    finally:
        panel.close()
        controller.shutdown()


def test_stop_after_current_finishes_active_experiment_then_stops_before_next_point(tmp_path):
    # Stop semantics #1 (stop_after_current): lets the in-flight experiment
    # run to full completion (including its own parallel save/flush), then
    # stops -- the second temperature point's tec_set must never fire.
    app = QApplication.instance() or QApplication(["test-stop-after-current"])
    controller, panel, results, events = _connected_temperature_series_harness(app, repeats=1)
    try:
        definition = panel._definition()
        folder = controller.experiments.queue(definition, tmp_path)
        assert controller.experiments.start()
        # Call stop_after_current() while the first (only) experiment is
        # still mid-flight -- the check happens synchronously at the very
        # end of that experiment's own completion callback, with no gap
        # afterward for a test to intercept; waiting for
        # batch_completed_experiments==1 would already be too late with
        # only one repeat per point; there is no second experiment to wait
        # through before the series moves on to the next point.
        deadline = monotonic() + 30
        while monotonic() < deadline and not any(
            event.operation is DeviceOperation.AD2_SOFTWARE_TRIGGER and event.state == "completed"
            for event in events
        ):
            app.processEvents(); sleep(0.01)
        controller.experiments.stop_after_current()
        status = _wait_until_terminal(app, controller)
        assert status["state"] == "stopped", status

        completed_ops = [event.operation for event in events if event.state == "completed"]
        assert completed_ops.count(DeviceOperation.TEC_SETPOINTS_APPLY) == 1  # second point never started
        assert completed_ops.count(DeviceOperation.CAMERA_SEQUENCE_COLLECT) == 1  # exactly the one experiment ran

        status_doc = json.loads((folder / "metadata" / "status.json").read_text())
        assert status_doc["finalized_outcome"] == "stopped_after_current"
        assert status_doc["experiments_started"] == status_doc["experiments_completed"] == 1
        assert status_doc["experiments_failed"] == 0
    finally:
        panel.close()
        controller.shutdown()


def test_abort_during_a_running_series_stops_without_starting_the_next_experiment(tmp_path):
    # Stop semantics #2 (abort, "stop now"): unlike stop_after_current, does
    # not wait for the current experiment -- but the specific device-level
    # behavior (SAFE_STOP to all four devices, active-flush cancellation) is
    # already covered at the controller level by
    # test_panic_stops_connected_outputs_without_moving_valve and similar;
    # this test checks only the series-level consequence that test cannot:
    # the second repeat never starts, and the final record is consistent.
    app = QApplication.instance() or QApplication(["test-abort"])
    controller, panel, results, events = _connected_temperature_series_harness(app, repeats=2)
    try:
        definition = panel._definition()
        folder = controller.experiments.queue(definition, tmp_path)
        assert controller.experiments.start()
        _wait_until_n_experiments_completed(app, controller, 1, timeout=30)
        controller.experiments.abort()
        status = _wait_until_terminal(app, controller)
        assert status["state"] == "aborted", status

        completed_ops = [event.operation for event in events if event.state == "completed"]
        # The second repeat of the first point must never have reached
        # acquisition -- at most the one experiment that had already
        # finished before abort() was called.
        assert completed_ops.count(DeviceOperation.CAMERA_SEQUENCE_COLLECT) == 1
        assert completed_ops.count(DeviceOperation.TEC_SETPOINTS_APPLY) == 1

        status_doc = json.loads((folder / "metadata" / "status.json").read_text())
        assert status_doc["finalized_outcome"] == "aborted"
        assert status_doc["experiments_completed"] == 1
        # The second repeat's incomplete experiment, if any was in flight
        # when abort() landed, must not be miscounted as completed.
        assert status_doc["experiments_completed"] <= status_doc["experiments_started"]
    finally:
        panel.close()
        controller.shutdown()


def test_panic_stop_during_a_running_series_ends_the_batch_without_moving_the_valve(tmp_path):
    # Stop semantics #3 (controller.panic_stop(), which calls
    # experiments.panic_abort() internally): the device-level facts (no
    # VALVE_POSITION_SET, which devices get SAFE_STOP) are already covered
    # by test_panic_stops_connected_outputs_without_moving_valve for the
    # no-series-running case; this test checks the one thing that case
    # cannot, with a real series actually running: the batch stops, the
    # next experiment never starts, and the valve is still never moved by
    # panic specifically (re-asserted here because it is the one
    # panic-specific device fact that interacts with a live series' own
    # valve usage, unlike the device connect/SAFE_STOP facts which don't).
    app = QApplication.instance() or QApplication(["test-panic-during-series"])
    controller, panel, results, events = _connected_temperature_series_harness(app, repeats=2)
    try:
        definition = panel._definition()
        folder = controller.experiments.queue(definition, tmp_path)
        assert controller.experiments.start()
        _wait_until_n_experiments_completed(app, controller, 1, timeout=30)
        before = len(events)
        controller.panic_stop()
        deadline = monotonic() + 15
        while monotonic() < deadline and controller.panic_status()["state"] == "stopping":
            app.processEvents(); sleep(0.01)
        assert controller.panic_status()["state"] == "completed"
        status = _wait_until_terminal(app, controller)
        assert status["state"] == "aborted", status

        completed_ops = [event.operation for event in events if event.state == "completed"]
        assert completed_ops.count(DeviceOperation.CAMERA_SEQUENCE_COLLECT) == 1
        assert not any(event.operation is DeviceOperation.VALVE_POSITION_SET for event in events[before:])

        status_doc = json.loads((folder / "metadata" / "status.json").read_text())
        assert status_doc["finalized_outcome"] == "aborted"
        assert status_doc["experiments_completed"] <= status_doc["experiments_started"]
    finally:
        panel.close()
        controller.shutdown()


def test_parallel_barrier_blocks_next_experiment_until_save_completes(tmp_path):
    # Direct test of the parallel barrier, not inferred from
    # AD2_DIGITAL_OUTPUT_STOP (which only marks wait_outputs' own
    # completion, strictly before the flush step in the same branch runs --
    # it is not evidence that EITHER branch, let alone both, has finished).
    # Makes save deliberately slow and measures that the wall-clock gap
    # between the first experiment's trigger and the second experiment's
    # own camera reconfiguration is at least the artificial save delay --
    # if the barrier did not hold, that gap would be far shorter (bounded
    # only by the fast simulated wait_outputs/flush branch).
    app = QApplication.instance() or QApplication(["test-barrier-save"])
    controller, panel, results, events = _connected_temperature_series_harness(app, repeats=2)
    try:
        panel.temperature[2].setValue(1)  # one temperature point only, simplifies timing
        definition = panel._definition()
        folder = controller.experiments.queue(definition, tmp_path)
        storage = controller.experiments._queued[0][1]
        original_save = storage.save_frames
        delay_s = 0.6
        def slow_save(*args, **kwargs):
            sleep(delay_s)
            return original_save(*args, **kwargs)
        storage.save_frames = slow_save
        assert controller.experiments.start()
        status = _wait_until_terminal(app, controller)
        assert status["state"] == "completed", status

        completed = [event for event in events if event.state == "completed"]
        triggers = [i for i, event in enumerate(completed) if event.operation is DeviceOperation.AD2_SOFTWARE_TRIGGER]
        configures = [i for i, event in enumerate(completed)
                     if event.operation is DeviceOperation.CAMERA_SEQUENCE_CONFIGURE]
        assert len(triggers) == 2
        first_trigger_time = completed[triggers[0]].timestamp
        second_configure_time = completed[configures[-1]].timestamp  # the 2nd experiment's own reconfigure
        elapsed = (second_configure_time - first_trigger_time).total_seconds()
        assert elapsed >= delay_s * 0.8
    finally:
        panel.close()
        controller.shutdown()


def test_parallel_barrier_blocks_next_experiment_until_flush_completes(tmp_path):
    # Same barrier, isolating the flush side instead of save: a real
    # (not monkeypatched) nonzero wait_after_s on the flush extends that
    # branch's own completion deterministically, with save left fast.
    app = QApplication.instance() or QApplication(["test-barrier-flush"])
    controller, panel, results, events = _connected_temperature_series_harness(app, repeats=2)
    try:
        panel.temperature[2].setValue(1)
        wait_after_s = 0.6
        panel.wait_after_flush.setValue(wait_after_s)
        definition = panel._definition()
        folder = controller.experiments.queue(definition, tmp_path)
        assert controller.experiments.start()
        status = _wait_until_terminal(app, controller)
        assert status["state"] == "completed", status

        completed = [event for event in events if event.state == "completed"]
        triggers = [i for i, event in enumerate(completed) if event.operation is DeviceOperation.AD2_SOFTWARE_TRIGGER]
        configures = [i for i, event in enumerate(completed)
                     if event.operation is DeviceOperation.CAMERA_SEQUENCE_CONFIGURE]
        assert len(triggers) == 2
        first_trigger_time = completed[triggers[0]].timestamp
        second_configure_time = completed[configures[-1]].timestamp
        elapsed = (second_configure_time - first_trigger_time).total_seconds()
        assert elapsed >= wait_after_s * 0.8
    finally:
        panel.close()
        controller.shutdown()
