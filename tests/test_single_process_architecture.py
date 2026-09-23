from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest
from PySide6.QtCore import QThread, QTimer
from PySide6.QtWidgets import QApplication

from thermo_acoustic.application import ApplicationController, DeviceCommand, DeviceOperation
from thermo_acoustic.application.audit import AuditLogger
from thermo_acoustic.application.commands import (
    Ad2ConfigureDigitalOutputArgs,
    Ad2ConfigureScopeArgs,
    Ad2ConfigureWaveformArgs,
    Ad2DigitalOutputType,
    Ad2ScopeReadResult,
    Ad2TriggerSource,
    CameraConfigureSnapshotArgs,
    CameraConfigureSequenceArgs,
    CameraConfigureExposureArgs,
    CameraConfigureRoiArgs,
    CameraExposureResult,
    CameraRoiResult,
    CameraSnapshotResult,
    CameraSequenceResult,
    CameraTimingResult,
    PumpConnectArgs,
    PumpFillLevelResult,
    PumpConfigurationResult,
    PumpConfigureFlowUnitArgs,
    PumpConfigureSyringeArgs,
    PumpFlowUnit,
    PumpRecoveryResult,
    PumpMoveArgs,
    PumpMovementResult,
    PumpReferenceMoveArgs,
    PumpSetFillLevelArgs,
    PumpSetFlowArgs,
    PumpSyringePreset,
    PumpStatusResult,
    TecApplySetpointsArgs,
    TecReadStatusArgs,
    TecStatusResult,
    TecWaitStableArgs,
    ValvePositionResult,
    ValveReadyResult,
    ValveSetPositionArgs,
    ValveWaitReadyArgs,
    ZStageClosedLoopRequirementResult,
    ZStagePositionResult,
    ZStageSetPositionArgs,
)
from thermo_acoustic.console.parser import parse_command
from thermo_acoustic.domain.models import (
    Ad2Readback,
    DeviceId,
    OperatingMode,
    PumpReadback,
    ZStageReadback,
)
from thermo_acoustic.drivers.ad2 import SimulatedAD2
from thermo_acoustic.hal.registry import DeviceRegistry
from thermo_acoustic.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication(["test"])
    yield app


def wait(app, ms=80):
    deadline = QTimer()
    deadline.setSingleShot(True)
    deadline.timeout.connect(app.quit)
    deadline.start(ms)
    app.exec()


def test_registry_startup_does_not_import_real_drivers():
    source_root = Path(__file__).resolve().parents[1] / "src"
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(source_root)
    script = """
import sys
from thermo_acoustic.domain.models import OperatingMode
from thermo_acoustic.hal.registry import DeviceRegistry

DeviceRegistry()
DeviceRegistry(OperatingMode.REAL)
loaded = sorted(name for name in sys.modules if name.startswith('thermo_acoustic.drivers'))
if loaded:
    raise SystemExit('unexpected driver imports: ' + ', '.join(loaded))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout


def test_typed_commands_reject_wrong_device_and_argument_type():
    with pytest.raises(ValueError, match="not valid"):
        DeviceCommand(DeviceId.CAMERA, DeviceOperation.PUMP_STATUS_READ)
    with pytest.raises(TypeError, match="PumpSetFlowArgs"):
        DeviceCommand(DeviceId.PUMP, DeviceOperation.PUMP_FLOW_SET)
    with pytest.raises(TypeError, match="DeviceOperation"):
        DeviceCommand(DeviceId.PUMP, "pump.status.read")


def test_simulation_is_default_and_status_is_cached(qt_app):
    registry = DeviceRegistry()
    controller = ApplicationController(registry, mode=OperatingMode.SIMULATION)
    assert all(status.connection.value != "connected" for status in controller.statuses().values())
    controller.start()
    controller.submit(DeviceCommand(DeviceId.PUMP, DeviceOperation.CONNECT))
    wait(qt_app)
    assert controller.statuses()[DeviceId.PUMP].connection.value == "connected"
    assert isinstance(controller.statuses()[DeviceId.PUMP].readback, PumpReadback)
    controller.shutdown()


def test_ui_and_console_share_fifo_and_request_ids(qt_app):
    registry = DeviceRegistry()
    controller = ApplicationController(registry, mode=OperatingMode.SIMULATION)
    events = []
    controller.command_event.connect(events.append)
    controller.start()
    controller.submit(
        DeviceCommand(
            DeviceId.PUMP,
            DeviceOperation.CONNECT,
            request_id="ui-1",
            source="ui",
        )
    )
    parsed = parse_command("pump set-flow 100")
    controller.submit(
        DeviceCommand(
            parsed.device,
            parsed.operation,
            parsed.arguments,
            request_id="console-1",
            source="console",
        )
    )
    wait(qt_app, 250)
    completed = [event.request_id for event in events if event.state == "completed"]
    assert completed == ["ui-1", "console-1"]
    assert any(event.source == "console" and event.request_id == "console-1" for event in events)
    controller.shutdown()


def test_all_simulated_devices_have_typed_direct_operations(qt_app):
    registry = DeviceRegistry()
    controller = ApplicationController(
        registry,
        mode=OperatingMode.SIMULATION,
        confirm_operation=lambda _: True,
    )
    results = []
    controller.command_result.connect(results.append)
    controller.start()
    for device in DeviceId:
        controller.submit(DeviceCommand(device, DeviceOperation.CONNECT))
    wait(qt_app, 250)

    commands = (
        DeviceCommand(
            DeviceId.AD2,
            DeviceOperation.AD2_WAVEFORM_CONFIGURE,
            Ad2ConfigureWaveformArgs(1000.0, 1.0),
        ),
        DeviceCommand(DeviceId.AD2, DeviceOperation.AD2_WAVEFORM_START),
        DeviceCommand(
            DeviceId.AD2,
            DeviceOperation.AD2_DIGITAL_OUTPUT_CONFIGURE,
            Ad2ConfigureDigitalOutputArgs(
                channel_index=0,
                output_type=Ad2DigitalOutputType.CUSTOM,
                clock_frequency_hz=500.0,
                bits=(1, 1, 0, 0),
            ),
        ),
        DeviceCommand(DeviceId.AD2, DeviceOperation.AD2_DIGITAL_OUTPUT_START),
        DeviceCommand(DeviceId.AD2, DeviceOperation.AD2_DIGITAL_OUTPUT_STOP),
        DeviceCommand(DeviceId.AD2, DeviceOperation.AD2_DIGITAL_OUTPUT_RESET),
        DeviceCommand(
            DeviceId.PUMP,
            DeviceOperation.PUMP_SYRINGE_CONFIGURE,
            PumpConfigureSyringeArgs(preset=PumpSyringePreset.BD_5_ML),
        ),
        DeviceCommand(
            DeviceId.PUMP,
            DeviceOperation.PUMP_FLOW_UNIT_CONFIGURE,
            PumpConfigureFlowUnitArgs(PumpFlowUnit.MICROLITRE_PER_MINUTE),
        ),
        DeviceCommand(DeviceId.PUMP, DeviceOperation.PUMP_FLOW_SET, PumpSetFlowArgs(20)),
        DeviceCommand(
            DeviceId.PUMP,
            DeviceOperation.PUMP_FILL_LEVEL_SET,
            PumpSetFillLevelArgs(2.0, 100.0),
        ),
        DeviceCommand(DeviceId.PUMP, DeviceOperation.PUMP_FILL_LEVEL_READ),
        DeviceCommand(DeviceId.PUMP, DeviceOperation.PUMP_STATUS_READ),
        DeviceCommand(DeviceId.PUMP, DeviceOperation.PUMP_FAULT_RECOVER),
        DeviceCommand(
            DeviceId.VALVE,
            DeviceOperation.VALVE_POSITION_SET,
            ValveSetPositionArgs(1),
        ),
        DeviceCommand(
            DeviceId.VALVE,
            DeviceOperation.VALVE_WAIT_READY,
            ValveWaitReadyArgs(),
        ),
        DeviceCommand(DeviceId.VALVE, DeviceOperation.VALVE_POSITION_READ),
        DeviceCommand(
            DeviceId.CAMERA,
            DeviceOperation.CAMERA_SNAPSHOT_CONFIGURE,
            CameraConfigureSnapshotArgs(2.5),
        ),
        DeviceCommand(DeviceId.CAMERA, DeviceOperation.CAMERA_SNAPSHOT_CAPTURE),
        DeviceCommand(DeviceId.CAMERA, DeviceOperation.CAMERA_TIMING_READ),
        DeviceCommand(
            DeviceId.CAMERA,
            DeviceOperation.CAMERA_EXPOSURE_CONFIGURE,
            CameraConfigureExposureArgs(3.5),
        ),
        DeviceCommand(
            DeviceId.CAMERA,
            DeviceOperation.CAMERA_ROI_CONFIGURE,
            CameraConfigureRoiArgs(100, 120, 512, 256),
        ),
        DeviceCommand(
            DeviceId.TEC,
            DeviceOperation.TEC_SETPOINTS_APPLY,
            TecApplySetpointsArgs({1: 25.0, 2: 26.0}),
        ),
        DeviceCommand(
            DeviceId.TEC,
            DeviceOperation.TEC_STATUS_READ,
            TecReadStatusArgs(),
        ),
        DeviceCommand(
            DeviceId.Z_STAGE,
            DeviceOperation.Z_STAGE_CLOSED_LOOP_REQUIREMENT_READ,
        ),
    )
    for command in commands:
        controller.submit(command)
    wait(qt_app, 650)
    controller.submit(DeviceCommand(DeviceId.Z_STAGE, DeviceOperation.Z_STAGE_CLOSED_LOOP_ENABLE))
    controller.submit(
        DeviceCommand(
            DeviceId.Z_STAGE,
            DeviceOperation.Z_STAGE_POSITION_SET,
            ZStageSetPositionArgs(50),
        )
    )
    controller.submit(DeviceCommand(DeviceId.Z_STAGE, DeviceOperation.Z_STAGE_POSITION_READ))
    wait(qt_app, 300)

    assert all(result.ok for result in results)
    values = [result.value for result in results]
    assert any(isinstance(value, PumpFillLevelResult) for value in values)
    assert any(isinstance(value, PumpConfigurationResult) for value in values)
    assert any(isinstance(value, PumpRecoveryResult) for value in values)
    assert any(isinstance(value, PumpStatusResult) for value in values)
    assert any(isinstance(value, ValveReadyResult) for value in values)
    assert any(isinstance(value, ValvePositionResult) for value in values)
    assert any(isinstance(value, CameraSnapshotResult) for value in values)
    assert any(isinstance(value, CameraTimingResult) for value in values)
    assert any(isinstance(value, CameraExposureResult) for value in values)
    assert any(isinstance(value, CameraRoiResult) for value in values)
    assert any(isinstance(value, TecStatusResult) for value in values)
    assert any(isinstance(value, ZStageClosedLoopRequirementResult) for value in values)
    assert any(isinstance(value, ZStagePositionResult) for value in values)
    assert controller.statuses()[DeviceId.AD2].readback.waveform_running
    assert not controller.statuses()[DeviceId.AD2].readback.digital_output_configured
    assert controller.statuses()[DeviceId.PUMP].readback.max_volume_ml == 5.0
    assert controller.statuses()[DeviceId.PUMP].readback.fill_level_ml == 2.0
    assert controller.statuses()[DeviceId.PUMP].readback.last_recovery_succeeded
    assert controller.statuses()[DeviceId.CAMERA].readback.exposure_ms == 3.5
    assert controller.statuses()[DeviceId.CAMERA].readback.roi.horizontal_size == 512
    assert controller.statuses()[DeviceId.Z_STAGE].readback.position_um == 50
    controller.shutdown()


def test_ad2_scope_arm_trigger_and_read_share_one_worker(qt_app):
    registry = DeviceRegistry()
    controller = ApplicationController(registry, mode=OperatingMode.SIMULATION)
    completed = []
    controller.command_result.connect(completed.append)
    controller.start()
    controller.submit(DeviceCommand(DeviceId.AD2, DeviceOperation.CONNECT))
    controller.submit(
        DeviceCommand(
            DeviceId.AD2,
            DeviceOperation.AD2_SCOPE_CONFIGURE,
            Ad2ConfigureScopeArgs(
                sample_count=3,
                channels=(0,),
                trigger_source=Ad2TriggerSource.DIGITAL_OUT,
            ),
        )
    )
    controller.submit(DeviceCommand(DeviceId.AD2, DeviceOperation.AD2_SOFTWARE_TRIGGER))
    controller.submit(DeviceCommand(DeviceId.AD2, DeviceOperation.AD2_SCOPE_READ))
    wait(qt_app, 300)

    assert [item.operation for item in completed] == [
        DeviceOperation.CONNECT,
        DeviceOperation.AD2_SCOPE_CONFIGURE,
        DeviceOperation.AD2_SOFTWARE_TRIGGER,
        DeviceOperation.AD2_SCOPE_READ,
    ]
    assert all(item.ok for item in completed)
    assert completed[-1].value == Ad2ScopeReadResult({0: [0.0, 0.0, 0.0]})
    readback = controller.statuses()[DeviceId.AD2].readback
    assert isinstance(readback, Ad2Readback)
    assert readback.scope_state == "idle"
    controller.shutdown()


def test_ad2_scope_wait_is_deferred_and_abort_bypasses_global_fifo(qt_app):
    class WaitingScope(SimulatedAD2):
        def __init__(self):
            super().__init__()
            self.abort_called = False

        def scope_poll(self):
            return None

        def scope_abort(self):
            self.abort_called = True
            super().scope_abort()

    device = WaitingScope()
    registry = DeviceRegistry(factories={DeviceId.AD2: lambda: device})
    controller = ApplicationController(registry, mode=OperatingMode.SIMULATION)
    events = []
    controller.command_event.connect(events.append)
    controller.start()
    controller.submit(DeviceCommand(DeviceId.AD2, DeviceOperation.CONNECT))
    controller.submit(
        DeviceCommand(
            DeviceId.AD2,
            DeviceOperation.AD2_SCOPE_CONFIGURE,
            Ad2ConfigureScopeArgs(sample_count=16, timeout_s=5, poll_interval_s=0.01),
        )
    )
    read = DeviceCommand(DeviceId.AD2, DeviceOperation.AD2_SCOPE_READ)
    controller.submit(read)
    wait(qt_app, 80)
    assert controller.statuses()[DeviceId.AD2].busy

    abort = DeviceCommand(DeviceId.AD2, DeviceOperation.ABORT_ACTIVE)
    controller.submit(abort)
    wait(qt_app, 80)

    assert device.abort_called
    states = {(event.request_id, event.state) for event in events}
    assert (abort.request_id, "completed") in states
    assert (read.request_id, "cancelled") in states
    assert not controller.statuses()[DeviceId.AD2].busy
    controller.shutdown()


def test_z_stage_mode_switch_requires_query_and_confirmation(qt_app):
    confirmations = []
    registry = DeviceRegistry()
    controller = ApplicationController(
        registry,
        mode=OperatingMode.SIMULATION,
        confirm_operation=lambda request: confirmations.append(request) or False,
    )
    events = []
    controller.command_event.connect(events.append)
    controller.start()
    controller.submit(DeviceCommand(DeviceId.Z_STAGE, DeviceOperation.CONNECT))
    wait(qt_app)

    controller.submit(DeviceCommand(DeviceId.Z_STAGE, DeviceOperation.Z_STAGE_CLOSED_LOOP_ENABLE))
    assert events[-1].state == "failed"
    assert "Read" in events[-1].message
    assert confirmations == []

    controller.submit(
        DeviceCommand(
            DeviceId.Z_STAGE,
            DeviceOperation.Z_STAGE_CLOSED_LOOP_REQUIREMENT_READ,
        )
    )
    wait(qt_app)
    status = controller.statuses()[DeviceId.Z_STAGE]
    assert isinstance(status.readback, ZStageReadback)
    assert status.readback.closed_loop_confirmation_required

    controller.submit(DeviceCommand(DeviceId.Z_STAGE, DeviceOperation.Z_STAGE_CLOSED_LOOP_ENABLE))
    assert events[-1].state == "failed"
    assert len(confirmations) == 1
    assert not status.readback.closed_loop
    controller.shutdown()


def test_second_slice_hal_matches_injected_real_driver_contracts(qt_app):
    calls = []

    class FakeAd2:
        def initialize(self):
            calls.append(("ad2", "initialize"))

        def cleanup(self):
            calls.append(("ad2", "cleanup"))

        def do_configure(self, config):
            calls.append(("ad2", "configure", config))

        def start_stop_do(self, running):
            calls.append(("ad2", "running", running))

        def do_reset(self):
            calls.append(("ad2", "reset"))

    class FakeCamera:
        def open_camera(self):
            calls.append(("camera", "open"))

        def close(self):
            calls.append(("camera", "close"))

        def configure_exposure_time(self, exposure_ms):
            calls.append(("camera", "exposure", exposure_ms))
            return 2.49

        def configure_roi(self, roi):
            calls.append(("camera", "roi", roi))

        def read_subregion_limits_and_value(self):
            return None, {
                "horizontal_offset": 100,
                "vertical_offset": 120,
                "horizontal_size": 512,
                "vertical_size": 256,
            }

    class FakePump:
        max_volume_ml = 5.0
        max_flow_rate_ul_min = 1000.0

        def initialize(self):
            calls.append(("pump", "initialize"))

        def cleanup(self):
            calls.append(("pump", "cleanup"))

        def stop(self):
            calls.append(("pump", "stop"))

        def configure_syringe(self, config):
            calls.append(("pump", "syringe", config))

        def configure_flow_unit(self, unit):
            calls.append(("pump", "unit", unit))

        def set_fill_level(self, level, flow):
            calls.append(("pump", "fill", level, flow))

        def clear_fault_and_reinitialize(self):
            calls.append(("pump", "recover"))

    registry = DeviceRegistry(
        OperatingMode.REAL,
        {
            DeviceId.AD2: FakeAd2,
            DeviceId.CAMERA: FakeCamera,
            DeviceId.PUMP: FakePump,
        },
    )
    controller = ApplicationController(
        registry,
        mode=OperatingMode.REAL,
        confirm_real_connection=lambda _: True,
    )
    results = []
    controller.command_result.connect(results.append)
    controller.start()
    for device in (DeviceId.AD2, DeviceId.CAMERA, DeviceId.PUMP):
        controller.submit(DeviceCommand(device, DeviceOperation.CONNECT))
    commands = (
        DeviceCommand(
            DeviceId.AD2,
            DeviceOperation.AD2_DIGITAL_OUTPUT_CONFIGURE,
            Ad2ConfigureDigitalOutputArgs(clock_frequency_hz=500.0),
        ),
        DeviceCommand(DeviceId.AD2, DeviceOperation.AD2_DIGITAL_OUTPUT_START),
        DeviceCommand(DeviceId.AD2, DeviceOperation.AD2_DIGITAL_OUTPUT_STOP),
        DeviceCommand(DeviceId.AD2, DeviceOperation.AD2_DIGITAL_OUTPUT_RESET),
        DeviceCommand(
            DeviceId.CAMERA,
            DeviceOperation.CAMERA_EXPOSURE_CONFIGURE,
            CameraConfigureExposureArgs(2.5),
        ),
        DeviceCommand(
            DeviceId.CAMERA,
            DeviceOperation.CAMERA_ROI_CONFIGURE,
            CameraConfigureRoiArgs(100, 120, 512, 256),
        ),
        DeviceCommand(
            DeviceId.PUMP,
            DeviceOperation.PUMP_SYRINGE_CONFIGURE,
            PumpConfigureSyringeArgs(preset=PumpSyringePreset.BD_5_ML),
        ),
        DeviceCommand(
            DeviceId.PUMP,
            DeviceOperation.PUMP_FLOW_UNIT_CONFIGURE,
            PumpConfigureFlowUnitArgs(PumpFlowUnit.MICROLITRE_PER_MINUTE),
        ),
        DeviceCommand(
            DeviceId.PUMP,
            DeviceOperation.PUMP_FILL_LEVEL_SET,
            PumpSetFillLevelArgs(2.0, 100.0),
        ),
        DeviceCommand(DeviceId.PUMP, DeviceOperation.PUMP_FAULT_RECOVER),
    )
    for command in commands:
        controller.submit(command)
    wait(qt_app, 600)

    assert all(result.ok for result in results)
    assert ("ad2", "running", True) in calls
    assert ("ad2", "running", False) in calls
    assert ("camera", "exposure", 2.5) in calls
    assert ("pump", "unit", "ul/min") in calls
    assert ("pump", "fill", 2.0, 100.0) in calls
    assert ("pump", "recover") in calls
    controller.shutdown()


def test_real_connection_confirmation_and_lazy_fake_device(qt_app):
    calls = []
    worker_thread_checks = []

    class FakeDevice:
        def initialize(self):
            calls.append("initialized")
            worker_thread_checks.append(QThread.currentThread() is registry.by_id(DeviceId.PUMP).thread())

        def stop(self):
            calls.append("stopped")
            worker_thread_checks.append(QThread.currentThread() is registry.by_id(DeviceId.PUMP).thread())

        def cleanup(self):
            calls.append("cleaned")
            worker_thread_checks.append(QThread.currentThread() is registry.by_id(DeviceId.PUMP).thread())

    def create_device():
        calls.append("constructed")
        worker_thread_checks.append(QThread.currentThread() is registry.by_id(DeviceId.PUMP).thread())
        return FakeDevice()

    registry = DeviceRegistry(OperatingMode.REAL, {DeviceId.PUMP: create_device})
    assert calls == []
    assert not registry.by_id(DeviceId.PUMP).device_constructed

    controller = ApplicationController(
        registry,
        mode=OperatingMode.REAL,
        confirm_real_connection=lambda _: False,
    )
    controller.start()
    controller.submit(DeviceCommand(DeviceId.PUMP, DeviceOperation.CONNECT))
    wait(qt_app)
    assert calls == []

    controller.confirm_real_connection = lambda _: True
    controller.submit(DeviceCommand(DeviceId.PUMP, DeviceOperation.CONNECT))
    wait(qt_app)
    assert calls == ["constructed", "initialized"]
    assert worker_thread_checks == [True, True]

    controller.submit(DeviceCommand(DeviceId.PUMP, DeviceOperation.SAFE_STOP))
    wait(qt_app)
    assert calls == ["constructed", "initialized", "stopped"]

    controller.submit(DeviceCommand(DeviceId.PUMP, DeviceOperation.DISCONNECT))
    wait(qt_app)
    assert calls == ["constructed", "initialized", "stopped", "cleaned"]
    assert worker_thread_checks == [True, True, True, True]
    assert not registry.by_id(DeviceId.PUMP).device_constructed
    controller.shutdown()


def test_pump_configuration_reaches_worker_before_initialize(qt_app, tmp_path):
    (tmp_path / "qmixdevices.xml").touch()
    calls = []

    class FakePumpBank:
        unit_count = 0

        def set_configuration_path(self, path):
            calls.append(("configuration", path))

        def initialize(self):
            assert calls == [("configuration", tmp_path.resolve())]
            calls.append(("initialized", None))

        def cleanup(self):
            pass

    registry = DeviceRegistry(OperatingMode.REAL, {DeviceId.PUMP: FakePumpBank})
    controller = ApplicationController(
        registry, mode=OperatingMode.REAL, confirm_real_connection=lambda _: True
    )
    controller.start()
    controller.submit(
        DeviceCommand(
            DeviceId.PUMP,
            DeviceOperation.CONNECT,
            PumpConnectArgs(tmp_path),
        )
    )
    wait(qt_app)
    assert calls == [("configuration", tmp_path.resolve()), ("initialized", None)]
    controller.shutdown()


def test_pump_configuration_argument_is_not_valid_for_other_devices(tmp_path):
    (tmp_path / "qmixdevices.xml").touch()
    with pytest.raises(ValueError, match="only valid for the pump"):
        DeviceCommand(DeviceId.AD2, DeviceOperation.CONNECT, PumpConnectArgs(tmp_path))


def test_ui_renders_offscreen_and_audit_is_jsonl(qt_app, tmp_path):
    registry = DeviceRegistry()
    controller = ApplicationController(
        registry,
        mode=OperatingMode.SIMULATION,
        audit=AuditLogger(tmp_path / "audit.jsonl"),
    )
    window = MainWindow(controller)
    window.show()
    wait(qt_app, 20)
    assert window.windowTitle() == "Thermo-acoustic control"
    window.close()
    assert (tmp_path / "audit.jsonl").exists()


def test_parser_is_a_text_to_typed_command_adapter():
    assert parse_command("help") == "help"
    move = parse_command("z-stage move 50")
    assert move.operation is DeviceOperation.Z_STAGE_POSITION_SET
    assert move.arguments == ZStageSetPositionArgs(50.0)
    status = parse_command("pump read-status")
    assert status.operation is DeviceOperation.PUMP_STATUS_READ
    digital = parse_command("ad2 configure-do 0 500 1100")
    assert digital.arguments.bits == (1, 1, 0, 0)
    assert digital.arguments.output_type is Ad2DigitalOutputType.CUSTOM
    syringe = parse_command("pump configure-syringe bd-5ml")
    assert syringe.arguments.preset is PumpSyringePreset.BD_5_ML
    roi = parse_command("camera set-roi 100 120 512 256")
    assert roi.arguments == CameraConfigureRoiArgs(100, 120, 512, 256)
    sequence = parse_command("camera configure-sequence 20 2.5")
    sequence_start = parse_command("camera sequence start --frames 20 --exposure-ms 2.5")
    assert sequence_start.operation is DeviceOperation.CAMERA_SEQUENCE_CAPTURE
    assert sequence_start.arguments.frame_count == 20
    assert parse_command("camera snapshot --exposure-ms 4").arguments.exposure_ms == 4
    assert parse_command("camera continuous-snapshot --exposure-ms 3").operation is DeviceOperation.CAMERA_CONTINUOUS_CAPTURE
    save = parse_command("camera save-sequence output --format stacked")
    assert save.operation is DeviceOperation.CAMERA_SEQUENCE_SAVE
    assert save.arguments.format.value == "stacked"
    assert sequence.arguments.frame_count == 20
    assert parse_command("pump refill").operation is DeviceOperation.PUMP_REFILL
    assert parse_command("pump reference-move").operation is DeviceOperation.PUMP_REFERENCE_MOVE
    assert parse_command("abort camera").operation is DeviceOperation.ABORT_ACTIVE
    assert parse_command("tec wait-stable 25 0.2 5 300").operation is DeviceOperation.TEC_WAIT_STABLE
    with pytest.raises(ValueError):
        parse_command("pump set-flow")


def test_long_operations_are_typed_and_complete_in_simulation(qt_app):
    registry = DeviceRegistry()
    controller = ApplicationController(registry, mode=OperatingMode.SIMULATION, confirm_operation=lambda _: True)
    results = []
    controller.command_result.connect(results.append)
    controller.start()
    for device in (DeviceId.CAMERA, DeviceId.PUMP, DeviceId.TEC):
        controller.submit(DeviceCommand(device, DeviceOperation.CONNECT))
    controller.submit(
        DeviceCommand(
            DeviceId.CAMERA,
            DeviceOperation.CAMERA_SEQUENCE_CONFIGURE,
            CameraConfigureSequenceArgs(3, 2.0, poll_interval_s=0.01),
        )
    )
    controller.submit(DeviceCommand(DeviceId.CAMERA, DeviceOperation.CAMERA_SEQUENCE_CAPTURE))
    controller.submit(
        DeviceCommand(
            DeviceId.PUMP,
            DeviceOperation.PUMP_REFILL,
            PumpMoveArgs(timeout_s=1.0, poll_interval_s=0.01),
        )
    )
    controller.submit(
        DeviceCommand(
            DeviceId.PUMP,
            DeviceOperation.PUMP_EMPTY,
            PumpMoveArgs(timeout_s=1.0, poll_interval_s=0.01),
        )
    )
    controller.submit(
        DeviceCommand(
            DeviceId.PUMP,
            DeviceOperation.PUMP_REFERENCE_MOVE,
            PumpReferenceMoveArgs(timeout_s=1.0, poll_interval_s=0.01),
        )
    )
    controller.submit(
        DeviceCommand(
            DeviceId.TEC,
            DeviceOperation.TEC_SETPOINTS_APPLY,
            TecApplySetpointsArgs(25.0),
        )
    )
    controller.submit(
        DeviceCommand(
            DeviceId.TEC,
            DeviceOperation.TEC_WAIT_STABLE,
            TecWaitStableArgs(25.0, 0.1, 0.0, 1.0, poll_interval_s=0.01),
        )
    )
    wait(qt_app, 500)

    assert all(result.ok for result in results)
    sequence = next(
        result.value
        for result in results
        if result.operation is DeviceOperation.CAMERA_SEQUENCE_CAPTURE
    )
    assert isinstance(sequence, CameraSequenceResult)
    assert len(sequence.frames) == 3
    movements = [
        result.value
        for result in results
        if result.operation
        in {
            DeviceOperation.PUMP_REFILL,
            DeviceOperation.PUMP_EMPTY,
            DeviceOperation.PUMP_REFERENCE_MOVE,
        }
    ]
    assert all(isinstance(result, PumpMovementResult) for result in movements)
    assert movements[-1].referenced
    controller.shutdown()


def test_pump_refill_returns_after_start_and_allows_readback_while_pumping(qt_app):
    calls = []

    class SlowPump:
        max_volume_ml = 1.0
        max_flow_rate_ul_min = 1000.0

        def initialize(self):
            calls.append(("initialize", QThread.currentThread()))

        def cleanup(self):
            calls.append(("cleanup", QThread.currentThread()))

        def refill(self, flow_rate):
            calls.append(("refill", QThread.currentThread()))
            self.pumping = True

        def read_status(self):
            calls.append(("status", QThread.currentThread()))
            return self.pumping

        def read_fill_level(self):
            return 0.0

        def stop(self):
            calls.append(("stop", QThread.currentThread()))
            self.pumping = False

    pump = SlowPump()
    pump.pumping = False
    registry = DeviceRegistry(OperatingMode.SIMULATION, {DeviceId.PUMP: lambda: pump})
    controller = ApplicationController(registry, mode=OperatingMode.SIMULATION)
    events = []
    controller.command_event.connect(events.append)
    controller.start()
    controller.submit(DeviceCommand(DeviceId.PUMP, DeviceOperation.CONNECT))
    wait(qt_app)
    controller.submit(
        DeviceCommand(
            DeviceId.PUMP,
            DeviceOperation.PUMP_REFILL,
            PumpMoveArgs(timeout_s=2.0, poll_interval_s=0.01),
            request_id="refill",
        )
    )
    controller.submit(
        DeviceCommand(
            DeviceId.PUMP,
            DeviceOperation.PUMP_STATUS_READ,
            request_id="queued-status",
        )
    )
    wait(qt_app, 60)
    assert any(event.request_id == "refill" and event.state == "completed" for event in events)
    assert any(event.request_id == "queued-status" and event.state == "completed" for event in events)
    assert controller.statuses()[DeviceId.PUMP].readback.units[0].is_pumping

    controller.submit(
        DeviceCommand(
            DeviceId.PUMP,
            DeviceOperation.PUMP_FLOW_STOP,
            request_id="urgent-stop",
        )
    )
    wait(qt_app, 150)

    terminal = [
        (event.request_id, event.state)
        for event in events
        if event.state in {"completed", "cancelled", "failed"}
    ]
    assert ("urgent-stop", "completed") in terminal
    assert ("refill", "completed") in terminal
    assert ("queued-status", "completed") in terminal
    assert not controller.statuses()[DeviceId.PUMP].readback.units[0].is_pumping
    worker_thread = registry.by_id(DeviceId.PUMP).thread()
    assert all(thread is worker_thread for _, thread in calls)
    controller.shutdown()


def test_pump_reference_move_requires_remove_syringe_confirmation(qt_app):
    confirmations = []
    registry = DeviceRegistry()
    controller = ApplicationController(
        registry, mode=OperatingMode.SIMULATION,
        confirm_operation=lambda request: confirmations.append(request) or False,
    )
    events = []
    controller.command_event.connect(events.append)
    controller.start()
    controller.submit(DeviceCommand(DeviceId.PUMP, DeviceOperation.CONNECT))
    wait(qt_app)

    command = DeviceCommand(DeviceId.PUMP, DeviceOperation.PUMP_REFERENCE_MOVE, PumpReferenceMoveArgs(unit_index=1))
    controller.submit(command)
    assert events[-1].state == "failed"
    assert len(confirmations) == 1
    assert "Pump 2" in confirmations[0].prompt
    assert "Remove the syringe" in confirmations[0].prompt
    assert not registry.by_id(DeviceId.PUMP).device._pumps[1].referenced
    controller.shutdown()


def test_pump_poll_reports_observed_per_unit_flow_and_syringe(qt_app):
    registry = DeviceRegistry()
    controller = ApplicationController(registry, mode=OperatingMode.SIMULATION)
    controller.start()
    controller.submit(DeviceCommand(DeviceId.PUMP, DeviceOperation.CONNECT))
    controller.submit(DeviceCommand(DeviceId.PUMP, DeviceOperation.PUMP_SYRINGE_CONFIGURE,
        PumpConfigureSyringeArgs(inner_diameter_mm=4.7, max_piston_stroke_mm=57.0, unit_index=1)))
    controller.submit(DeviceCommand(DeviceId.PUMP, DeviceOperation.PUMP_FLOW_SET, PumpSetFlowArgs(25.0, 1)))
    wait(qt_app, 650)
    units = controller.statuses()[DeviceId.PUMP].readback.units
    assert units[0].current_flow_ul_min == 0.0
    assert units[1].current_flow_ul_min == 25.0
    assert units[1].is_pumping is True
    assert units[1].is_faulted is False
    assert units[1].syringe_inner_diameter_mm == 4.7
    assert units[1].syringe_max_piston_stroke_mm == 57.0
    controller.shutdown()


def test_pump_rejects_out_of_range_targets_before_driver_call(qt_app):
    registry = DeviceRegistry()
    controller = ApplicationController(registry, mode=OperatingMode.SIMULATION)
    events = []
    controller.command_event.connect(events.append)
    controller.start()
    controller.submit(DeviceCommand(DeviceId.PUMP, DeviceOperation.CONNECT))
    wait(qt_app)
    pump = registry.by_id(DeviceId.PUMP).device._pumps[0]

    controller.submit(DeviceCommand(DeviceId.PUMP, DeviceOperation.PUMP_FLOW_SET,
        PumpSetFlowArgs(pump.max_flow_rate_ul_min + 1)))
    controller.submit(DeviceCommand(DeviceId.PUMP, DeviceOperation.PUMP_FILL_LEVEL_SET,
        PumpSetFillLevelArgs(pump.max_volume_ml + 1, 100.0)))
    wait(qt_app)
    assert [event.state for event in events if event.operation in {
        DeviceOperation.PUMP_FLOW_SET, DeviceOperation.PUMP_FILL_LEVEL_SET}
        and event.state in {"completed", "failed"}] == ["failed", "failed"]
    assert pump.flow_ul_min == 0.0
    assert pump.fill_level_ml == 0.0
    controller.shutdown()


def test_camera_and_tec_urgent_stops_cancel_deferred_operations(qt_app):
    registry = DeviceRegistry()
    controller = ApplicationController(registry, mode=OperatingMode.SIMULATION)
    events = []
    controller.command_event.connect(events.append)
    controller.start()
    controller.submit(DeviceCommand(DeviceId.CAMERA, DeviceOperation.CONNECT))
    controller.submit(DeviceCommand(DeviceId.TEC, DeviceOperation.CONNECT))
    controller.submit(
        DeviceCommand(
            DeviceId.CAMERA,
            DeviceOperation.CAMERA_SEQUENCE_CONFIGURE,
            CameraConfigureSequenceArgs(1000, poll_interval_s=0.01),
        )
    )
    controller.submit(
        DeviceCommand(
            DeviceId.CAMERA,
            DeviceOperation.CAMERA_SEQUENCE_CAPTURE,
            request_id="camera-sequence",
        )
    )
    wait(qt_app, 80)
    assert controller.statuses()[DeviceId.CAMERA].readback.capture_active
    controller.submit(
        DeviceCommand(
            DeviceId.CAMERA,
            DeviceOperation.CAMERA_CAPTURE_STOP,
            request_id="camera-stop",
        )
    )
    wait(qt_app, 80)
    assert not controller.statuses()[DeviceId.CAMERA].readback.capture_active

    controller.submit(
        DeviceCommand(
            DeviceId.TEC,
            DeviceOperation.TEC_WAIT_STABLE,
            TecWaitStableArgs(25.0, 0.1, 0.0, 2.0, poll_interval_s=0.01),
            request_id="tec-wait",
        )
    )
    wait(qt_app, 40)
    controller.submit(
        DeviceCommand(
            DeviceId.TEC,
            DeviceOperation.TEC_OUTPUTS_OFF,
            request_id="tec-off",
        )
    )
    wait(qt_app, 80)

    terminal = {
        (event.request_id, event.state)
        for event in events
        if event.state in {"completed", "cancelled", "failed"}
    }
    assert ("camera-sequence", "cancelled") in terminal
    assert ("camera-stop", "completed") in terminal
    assert ("tec-wait", "cancelled") in terminal
    assert ("tec-off", "completed") in terminal
    assert not controller.statuses()[DeviceId.TEC].active
    controller.shutdown()


def test_long_operation_timeouts_must_be_finite_and_positive():
    with pytest.raises(ValueError, match="finite and positive"):
        PumpMoveArgs(timeout_s=float("inf"))
    with pytest.raises(ValueError, match="finite and positive"):
        CameraConfigureSequenceArgs(2, frame_timeout_s=0.0)
    with pytest.raises(ValueError, match="finite and positive"):
        TecWaitStableArgs(25.0, 0.1, 0.0, float("inf"))
