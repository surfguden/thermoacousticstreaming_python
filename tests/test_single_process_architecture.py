from __future__ import annotations
import sys
import pytest
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
from thermo_acoustic.application import ApplicationController, DeviceCommand
from thermo_acoustic.application.audit import AuditLogger
from thermo_acoustic.console.parser import parse_command
from thermo_acoustic.hal.registry import DeviceRegistry
from thermo_acoustic.domain.models import DeviceId, OperatingMode
from thermo_acoustic.ui.main_window import MainWindow

@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication(["test"])
    yield app

def wait(app, ms=80):
    deadline = QTimer(); deadline.setSingleShot(True); deadline.timeout.connect(app.quit); deadline.start(ms); app.exec()

def test_simulation_is_default_and_status_is_cached(qt_app):
    registry = DeviceRegistry(); controller = ApplicationController(registry, mode=OperatingMode.SIMULATION)
    assert all(not status.connection.value == "connected" for status in controller.statuses().values())
    controller.start(); controller.submit(DeviceCommand(DeviceId.PUMP, "connect")); wait(qt_app)
    assert controller.statuses()[DeviceId.PUMP].connection.value == "connected"
    controller.shutdown()

def test_ui_and_console_share_fifo_and_request_ids(qt_app):
    registry = DeviceRegistry(); controller = ApplicationController(registry, mode=OperatingMode.SIMULATION); events = []
    controller.command_event.connect(events.append); controller.start()
    controller.submit(DeviceCommand(DeviceId.PUMP, "connect", source="ui", request_id="ui-1"))
    parsed = parse_command("pump set-flow 100")
    controller.submit(parsed.__class__(parsed.device, parsed.operation, parsed.args, request_id="console-1", source="console"))
    wait(qt_app, 250)
    completed = [event.request_id for event in events if event.state == "completed"]
    assert completed == ["ui-1", "console-1"]
    assert any(event.source == "console" and event.request_id == "console-1" for event in events)
    controller.shutdown()

def test_all_simulated_workers_have_basic_operations(qt_app):
    registry = DeviceRegistry(); controller = ApplicationController(registry, mode=OperatingMode.SIMULATION); controller.start()
    commands = [(DeviceId.AD2, "connect", ()), (DeviceId.PUMP, "connect", ()), (DeviceId.VALVE, "connect", ()), (DeviceId.CAMERA, "connect", ()), (DeviceId.TEC, "connect", ()), (DeviceId.Z_STAGE, "connect", ())]
    for device, operation, args in commands: controller.submit(DeviceCommand(device, operation, args))
    wait(qt_app, 250)
    controller.submit(DeviceCommand(DeviceId.PUMP, "set-flow", (20,))); controller.submit(DeviceCommand(DeviceId.VALVE, "set-position", (1,))); controller.submit(DeviceCommand(DeviceId.CAMERA, "snapshot")); controller.submit(DeviceCommand(DeviceId.TEC, "set-temperature", (25,))); controller.submit(DeviceCommand(DeviceId.Z_STAGE, "enable-closed-loop")); controller.submit(DeviceCommand(DeviceId.Z_STAGE, "move", (50,))); wait(qt_app, 350)
    assert controller.statuses()[DeviceId.PUMP].readings["flow_ul_min"] == 20
    assert controller.statuses()[DeviceId.Z_STAGE].readings["position_um"] == 50
    controller.shutdown()

def test_real_connection_confirmation_and_lazy_fake_driver(qt_app):
    calls = []
    class FakeDriver: pass
    registry = DeviceRegistry(OperatingMode.REAL, {DeviceId.PUMP: lambda: (calls.append("constructed") or FakeDriver())})
    assert calls == ["constructed"]
    controller = ApplicationController(registry, mode=OperatingMode.REAL, confirm_real_connection=lambda _: False); controller.start(); controller.submit(DeviceCommand(DeviceId.PUMP, "connect")); wait(qt_app)
    assert controller.statuses()[DeviceId.PUMP].connection.value == "disconnected"
    controller.shutdown()

def test_ui_renders_offscreen_and_audit_is_jsonl(qt_app, tmp_path):
    registry = DeviceRegistry(); controller = ApplicationController(registry, mode=OperatingMode.SIMULATION, audit=AuditLogger(tmp_path / "audit.jsonl")); window = MainWindow(controller); window.show(); wait(qt_app, 20); assert window.windowTitle() == "Thermo-acoustic control"; window.close(); assert (tmp_path / "audit.jsonl").exists()

def test_parser_validation_and_eof_contract():
    assert parse_command("help") == "help"
    assert parse_command("z-stage move 50").args == (50.0,)
    with pytest.raises(ValueError): parse_command("pump set-flow")
