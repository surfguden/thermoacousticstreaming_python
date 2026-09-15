from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest
from PySide6.QtCore import QThread, QTimer
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

def test_all_simulated_devices_have_basic_operations(qt_app):
    registry = DeviceRegistry()
    controller = ApplicationController(registry, mode=OperatingMode.SIMULATION)
    controller.start()
    for device in DeviceId:
        controller.submit(DeviceCommand(device, "connect"))
    wait(qt_app, 250)

    commands = (
        DeviceCommand(DeviceId.AD2, "configure", (1000.0, 1.0)),
        DeviceCommand(DeviceId.AD2, "start"),
        DeviceCommand(DeviceId.AD2, "trigger"),
        DeviceCommand(DeviceId.PUMP, "set-flow", (20,)),
        DeviceCommand(DeviceId.VALVE, "set-position", (1,)),
        DeviceCommand(DeviceId.CAMERA, "snapshot"),
        DeviceCommand(DeviceId.TEC, "set-temperature", (25,)),
        DeviceCommand(DeviceId.Z_STAGE, "enable-closed-loop"),
        DeviceCommand(DeviceId.Z_STAGE, "move", (50,)),
    )
    for command in commands:
        controller.submit(command)
    wait(qt_app, 450)

    assert controller.statuses()[DeviceId.AD2].active
    assert controller.statuses()[DeviceId.PUMP].readings["flow_ul_min"] == 20
    assert controller.statuses()[DeviceId.Z_STAGE].readings["position_um"] == 50
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
    controller.submit(DeviceCommand(DeviceId.PUMP, "connect"))
    wait(qt_app)
    assert calls == []
    assert controller.statuses()[DeviceId.PUMP].connection.value == "disconnected"

    controller.confirm_real_connection = lambda _: True
    controller.submit(DeviceCommand(DeviceId.PUMP, "connect"))
    wait(qt_app)
    assert calls == ["constructed", "initialized"]
    assert worker_thread_checks == [True, True]
    assert controller.statuses()[DeviceId.PUMP].connection.value == "connected"

    controller.submit(DeviceCommand(DeviceId.PUMP, "safe_stop"))
    wait(qt_app)
    assert calls == ["constructed", "initialized", "stopped"]

    controller.submit(DeviceCommand(DeviceId.PUMP, "disconnect"))
    wait(qt_app)
    assert calls == ["constructed", "initialized", "stopped", "cleaned"]
    assert worker_thread_checks == [True, True, True, True]
    assert not registry.by_id(DeviceId.PUMP).device_constructed
    controller.shutdown()

def test_ui_renders_offscreen_and_audit_is_jsonl(qt_app, tmp_path):
    registry = DeviceRegistry(); controller = ApplicationController(registry, mode=OperatingMode.SIMULATION, audit=AuditLogger(tmp_path / "audit.jsonl")); window = MainWindow(controller); window.show(); wait(qt_app, 20); assert window.windowTitle() == "Thermo-acoustic control"; window.close(); assert (tmp_path / "audit.jsonl").exists()

def test_parser_validation_and_eof_contract():
    assert parse_command("help") == "help"
    assert parse_command("z-stage move 50").args == (50.0,)
    with pytest.raises(ValueError): parse_command("pump set-flow")
