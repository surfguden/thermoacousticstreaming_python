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
    Ad2ConfigureScopeArgs,
    Ad2ConfigureWaveformArgs,
    Ad2ScopeReadResult,
    Ad2TriggerSource,
    CameraConfigureSnapshotArgs,
    CameraSnapshotResult,
    CameraTimingResult,
    PumpFillLevelResult,
    PumpSetFlowArgs,
    PumpStatusResult,
    TecApplySetpointsArgs,
    TecReadStatusArgs,
    TecStatusResult,
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
        DeviceCommand(DeviceId.PUMP, DeviceOperation.PUMP_FLOW_SET, PumpSetFlowArgs(20)),
        DeviceCommand(DeviceId.PUMP, DeviceOperation.PUMP_FILL_LEVEL_READ),
        DeviceCommand(DeviceId.PUMP, DeviceOperation.PUMP_STATUS_READ),
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
    assert any(isinstance(value, PumpStatusResult) for value in values)
    assert any(isinstance(value, ValveReadyResult) for value in values)
    assert any(isinstance(value, ValvePositionResult) for value in values)
    assert any(isinstance(value, CameraSnapshotResult) for value in values)
    assert any(isinstance(value, CameraTimingResult) for value in values)
    assert any(isinstance(value, TecStatusResult) for value in values)
    assert any(isinstance(value, ZStageClosedLoopRequirementResult) for value in values)
    assert any(isinstance(value, ZStagePositionResult) for value in values)
    assert controller.statuses()[DeviceId.AD2].readback.waveform_running
    assert controller.statuses()[DeviceId.PUMP].readback.requested_flow_ul_min == 20
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
    with pytest.raises(ValueError):
        parse_command("pump set-flow")
