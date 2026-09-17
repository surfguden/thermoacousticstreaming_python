from __future__ import annotations

import json

import numpy as np
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from thermo_acoustic.application import ApplicationController
from thermo_acoustic.application.commands import (
    Ad2ScopeReadResult,
    CameraSnapshotResult,
    DeviceOperation,
    OPERATION_SPECS,
)
from thermo_acoustic.domain.models import ConnectionState, DeviceId, DeviceStatus, OperatingMode
from thermo_acoustic.hal.registry import DeviceRegistry
from thermo_acoustic.ui.device_panels import Ad2Panel, CameraPanel, PANEL_TYPES, PumpPanel
from thermo_acoustic.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication(["test-device-ui"])


def wait(app, ms=80):
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(app.quit)
    timer.start(ms)
    app.exec()


@pytest.mark.parametrize("device", tuple(DeviceId))
def test_each_panel_builds_every_typed_device_operation(qt_app, device):
    del qt_app
    panel = PANEL_TYPES[device]()
    commands = []
    panel.command_requested.connect(lambda _action, command: commands.append(command))

    panel._buttons["connect"].click()
    panel.set_status(DeviceStatus(device, ConnectionState.CONNECTED, busy=True))
    for action, button in panel._buttons.items():
        if action != "connect":
            button.click()

    operations = {command.operation for command in commands}
    expected = {
        operation
        for operation, spec in OPERATION_SPECS.items()
        if device in spec.devices
    }
    assert operations == expected


def test_duplicate_action_is_prevented_with_visible_notice(qt_app):
    del qt_app
    panel = PumpPanel()
    commands = []
    notices = []
    panel.command_requested.connect(lambda action, command: commands.append((action, command)))
    panel.notice.connect(notices.append)
    panel.set_status(DeviceStatus(DeviceId.PUMP, ConnectionState.CONNECTED))

    panel._buttons["status"].click()
    action, command = commands[-1]
    panel.mark_pending(action, command.request_id)
    panel._buttons["status"].click()

    assert len(commands) == 1
    assert "not queued again" in notices[-1]
    assert "pending" in panel._buttons["status"].text().lower()
    panel.clear_pending(command.request_id)
    assert panel._buttons["status"].text() == "Read status"


def test_main_window_routes_panel_commands_and_terminal_events(qt_app):
    controller = ApplicationController(DeviceRegistry(), mode=OperatingMode.SIMULATION)
    window = MainWindow(controller)
    controller.start()
    pump = window.panels[DeviceId.PUMP]

    pump._buttons["connect"].click()
    wait(qt_app)
    assert pump.connection_label.text() == "Connected"
    assert pump._pending == {}

    pump.flow.setValue(44.0)
    pump._buttons["set_flow"].click()
    wait(qt_app)
    assert controller.statuses()[DeviceId.PUMP].readback.requested_flow_ul_min == 44.0
    assert pump._pending == {}
    window.close()


def test_status_readback_and_result_widgets_update(qt_app):
    del qt_app
    camera = CameraPanel()
    camera.set_status(
        DeviceStatus(DeviceId.CAMERA, ConnectionState.CONNECTED, busy=True, active=True)
    )
    assert camera.connection_label.text() == "Connected"
    assert "busy" in camera.state_label.text()
    assert "active" in camera.state_label.text()

    camera.handle_result(CameraSnapshotResult(np.arange(16, dtype=np.uint16).reshape(4, 4)))
    assert camera.preview.has_image

    ad2 = Ad2Panel()
    ad2.handle_result(Ad2ScopeReadResult({0: [0.0, 1.0], 1: [1.0, -1.0]}))
    assert ad2.scope_plot.samples_by_channel == {0: [0.0, 1.0], 1: [1.0, -1.0]}


def test_profile_round_trip_is_input_only_and_submits_nothing(qt_app, tmp_path):
    del qt_app
    controller = ApplicationController(DeviceRegistry(), mode=OperatingMode.SIMULATION)
    events = []
    controller.command_event.connect(events.append)
    window = MainWindow(controller)
    pump = window.panels[DeviceId.PUMP]
    camera = window.panels[DeviceId.CAMERA]
    pump.flow.setValue(321.5)
    camera.sequence_frames.setValue(27)
    path = tmp_path / "settings.json"
    window.save_profile(path)

    document = json.loads(path.read_text(encoding="utf-8"))
    assert set(document) == {"schema_version", "devices"}
    assert "connection" not in path.read_text(encoding="utf-8")

    pump.flow.setValue(1.0)
    camera.sequence_frames.setValue(1)
    window.load_profile(path)
    assert pump.flow.value() == 321.5
    assert camera.sequence_frames.value() == 27
    assert events == []


def test_profile_load_is_atomic_and_rejects_invalid_data(qt_app, tmp_path):
    del qt_app
    controller = ApplicationController(DeviceRegistry(), mode=OperatingMode.SIMULATION)
    window = MainWindow(controller)
    camera = window.panels[DeviceId.CAMERA]
    original_exposure = camera.exposure.value()
    document = window.profile_document()
    document["devices"]["camera"]["exposure_ms"] = original_exposure + 10
    document["devices"]["pump"]["move_timeout_s"] = 1.0
    document["devices"]["pump"]["move_poll_s"] = 2.0
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError, match="must not exceed"):
        window.load_profile(path)
    assert camera.exposure.value() == original_exposure

    path.write_text('{"schema_version": 99, "devices": {}}', encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported"):
        window.load_profile(path)

    path.write_text(
        '{"schema_version": 1, "devices": {"camera": {"exposure_ms": Infinity}}}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Non-finite"):
        window.load_profile(path)
