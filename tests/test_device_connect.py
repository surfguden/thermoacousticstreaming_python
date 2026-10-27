"""Prepare page and DeviceConnector: choose devices, connect them one by one, report each.

Simulation and fake devices only; no hardware. The camera fake can fail or block, which stands in
for an SDK that errors or is slow to open.
"""

from __future__ import annotations

import threading
from time import monotonic, sleep

import pytest
from PySide6.QtWidgets import QApplication

from thermo_acoustic.application import ApplicationController
from thermo_acoustic.application.commands import DeviceOperation
from thermo_acoustic.domain.models import ConnectionState, DeviceId, OperatingMode
from thermo_acoustic.drivers.camera import SimulatedCamera
from thermo_acoustic.hal.registry import DeviceRegistry
from thermo_acoustic.ui.main_window import MainWindow


class ControlledCamera(SimulatedCamera):
    fail_with: str | None = None
    release = threading.Event()
    entered = threading.Event()
    block = False

    def open_camera(self):
        type(self).entered.set()
        if type(self).block:
            type(self).release.wait(10)
        if type(self).fail_with:
            raise RuntimeError(type(self).fail_with)
        return super().open_camera()


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication(["test-device-connect"])


@pytest.fixture
def env(qt_app):
    ControlledCamera.fail_with = None
    ControlledCamera.block = False
    ControlledCamera.release = threading.Event()
    ControlledCamera.entered = threading.Event()
    controller = ApplicationController(
        DeviceRegistry(factories={DeviceId.CAMERA: ControlledCamera}), mode=OperatingMode.SIMULATION)
    events = []
    controller.command_event.connect(events.append)
    controller.start()
    window = MainWindow(controller)
    window.show()

    def wait(condition, timeout=8):
        deadline = monotonic() + timeout
        while monotonic() < deadline and not condition():
            qt_app.processEvents()
            sleep(0.01)
        assert condition()

    yield window, controller, events, wait
    ControlledCamera.release.set()
    window.close()
    controller.shutdown()


def _connect_ops(events, state="queued"):
    return [(e.device, e.state) for e in events
            if e.operation is DeviceOperation.CONNECT and e.state == state]


def _choose(window, *devices):
    for device in DeviceId:
        window.prepare_panel.checkboxes[device].setChecked(device in devices)


def _connection(controller, device):
    return controller.statuses()[device].connection


def test_only_the_selected_devices_are_connected_and_nothing_else_is_sent(env):
    window, controller, events, wait = env
    _choose(window, DeviceId.PUMP, DeviceId.VALVE)
    window.prepare_panel.connect_button.click()
    wait(lambda: not window.connector.active)
    assert _connection(controller, DeviceId.PUMP) is ConnectionState.CONNECTED
    assert _connection(controller, DeviceId.VALVE) is ConnectionState.CONNECTED
    for device in (DeviceId.AD2, DeviceId.CAMERA, DeviceId.TEC, DeviceId.Z_STAGE):
        assert _connection(controller, device) is ConnectionState.DISCONNECTED
    queued = {(e.device, e.operation) for e in events if e.state == "queued"}
    assert queued == {(DeviceId.PUMP, DeviceOperation.CONNECT), (DeviceId.VALVE, DeviceOperation.CONNECT)}
    assert "connected" in window.prepare_panel.result_labels[DeviceId.PUMP].text()


def test_group_connect_uses_the_same_command_as_the_device_pages_own_connect(env):
    window, controller, events, wait = env
    for device in DeviceId:
        panel = window.panels[device]
        sent = []
        panel.command_requested.connect(lambda action, command, sent=sent: sent.append(command))
        panel._buttons["connect"].click()  # the own Connect button, captured before it reaches the controller
        built = panel.build_connect_command()
        assert len(sent) == 1
        assert (sent[0].device, sent[0].operation, sent[0].arguments) == (
            built.device, built.operation, built.arguments)
    # The pump page's input (configuration folder) is part of the command, not dropped.
    assert window.panels[DeviceId.PUMP].build_connect_command().arguments.configuration_dir


def test_selecting_toggling_and_loading_settings_send_no_connect(env, tmp_path):
    window, controller, events, wait = env
    _choose(window, DeviceId.PUMP, DeviceId.CAMERA)
    _choose(window)
    path = tmp_path / "settings.json"
    window.save_profile(path)
    window.load_profile(path)
    for _ in range(20):
        QApplication.processEvents()
    assert [e for e in events if e.operation is DeviceOperation.CONNECT] == []
    assert all(s.connection is ConnectionState.DISCONNECTED for s in controller.statuses().values())


def test_nothing_selected_asks_for_a_selection(env):
    window, controller, events, wait = env
    _choose(window)
    window.prepare_panel.connect_button.click()
    assert "Select at least one device" in window.prepare_panel.hint_label.text()
    assert events == []


def test_connected_device_is_skipped_not_opened_again(env):
    window, controller, events, wait = env
    window.panels[DeviceId.PUMP]._buttons["connect"].click()
    wait(lambda: _connection(controller, DeviceId.PUMP) is ConnectionState.CONNECTED)
    _choose(window, DeviceId.PUMP, DeviceId.VALVE)
    window.prepare_panel.connect_button.click()
    wait(lambda: not window.connector.active)
    assert _connect_ops(events) == [(DeviceId.PUMP, "queued"), (DeviceId.VALVE, "queued")]  # pump once only
    assert "already connected" in window.prepare_panel.result_labels[DeviceId.PUMP].text()


def test_device_that_is_already_connecting_is_not_submitted_twice(env):
    window, controller, events, wait = env
    ControlledCamera.block = True
    window.panels[DeviceId.CAMERA]._buttons["connect"].click()
    wait(ControlledCamera.entered.is_set)
    _choose(window, DeviceId.CAMERA)
    window.prepare_panel.connect_button.click()
    assert window.connector.outcomes()[DeviceId.CAMERA].state == "already_connecting"
    assert not window.connector.active
    ControlledCamera.release.set()
    wait(lambda: _connection(controller, DeviceId.CAMERA) is ConnectionState.CONNECTED)
    assert len([1 for d, _ in _connect_ops(events) if d is DeviceId.CAMERA]) == 1


def test_a_slow_connect_delays_later_devices_but_does_not_cancel_them(env):
    window, controller, events, wait = env
    ControlledCamera.block = True
    _choose(window, DeviceId.VALVE, DeviceId.CAMERA)
    window.prepare_panel.connect_button.click()
    wait(ControlledCamera.entered.is_set)
    # The command lane is serial: the camera Connect is running, nothing else is sent meanwhile.
    ControlledCamera.release.set()
    wait(lambda: not window.connector.active)
    assert _connection(controller, DeviceId.VALVE) is ConnectionState.CONNECTED
    assert _connection(controller, DeviceId.CAMERA) is ConnectionState.CONNECTED


def test_one_failure_keeps_the_others_and_the_page_connect_can_retry(env):
    window, controller, events, wait = env
    ControlledCamera.fail_with = "camera busy"
    _choose(window, DeviceId.PUMP, DeviceId.CAMERA, DeviceId.VALVE)
    window.prepare_panel.connect_button.click()
    wait(lambda: not window.connector.active)
    outcomes = window.connector.outcomes()
    assert outcomes[DeviceId.CAMERA].state == "failed" and "camera busy" in outcomes[DeviceId.CAMERA].detail
    assert outcomes[DeviceId.PUMP].state == outcomes[DeviceId.VALVE].state == "connected"
    assert _connection(controller, DeviceId.PUMP) is ConnectionState.CONNECTED  # nothing rolled back
    assert _connection(controller, DeviceId.VALVE) is ConnectionState.CONNECTED
    assert _connection(controller, DeviceId.CAMERA) is ConnectionState.DISCONNECTED
    assert "camera busy" in window.prepare_panel.result_labels[DeviceId.CAMERA].text()
    assert len(_connect_ops(events)) == 3  # no automatic retry
    ControlledCamera.fail_with = None
    window.panels[DeviceId.CAMERA]._buttons["connect"].click()  # the device page still retries on its own
    wait(lambda: _connection(controller, DeviceId.CAMERA) is ConnectionState.CONNECTED)


def test_invalid_inputs_fail_that_device_only(env):
    window, controller, events, wait = env
    window.panels[DeviceId.VALVE].require_port = True  # as in real mode with no COM port chosen
    _choose(window, DeviceId.VALVE, DeviceId.PUMP)
    window.prepare_panel.connect_button.click()
    wait(lambda: not window.connector.active)
    outcomes = window.connector.outcomes()
    assert outcomes[DeviceId.VALVE].state == "failed" and "COM port" in outcomes[DeviceId.VALVE].detail
    assert outcomes[DeviceId.PUMP].state == "connected"
    assert (DeviceId.VALVE, "queued") not in _connect_ops(events)


@pytest.mark.parametrize("blocker", ["batch", "panic", "closing"])
def test_group_connect_cannot_bypass_active_experiment_panic_or_closing(env, blocker):
    window, controller, events, wait = env
    if blocker == "batch":
        controller.experiments._state = "running"
    elif blocker == "panic":
        controller._panic_state = "stopping"
    else:
        controller.begin_close()
    try:
        assert window.connector.blocked_reason()
        _choose(window, DeviceId.PUMP)
        window.prepare_panel._refresh()
        assert not window.prepare_panel.connect_button.isEnabled()
        with pytest.raises(RuntimeError):
            window.connector.connect({DeviceId.PUMP: window.panels[DeviceId.PUMP].build_connect_command()})
        assert events == []
    finally:
        controller.experiments._state = "idle"
        controller._panic_state = "idle"
        controller._close_requested = False


def test_panic_during_a_group_stops_the_devices_not_yet_submitted(env):
    window, controller, events, wait = env
    ControlledCamera.block = True
    _choose(window, DeviceId.CAMERA, DeviceId.TEC, DeviceId.Z_STAGE)
    window.prepare_panel.connect_button.click()
    wait(ControlledCamera.entered.is_set)  # camera Connect is running; TEC and Z-stage not yet submitted
    controller.panic_stop()
    ControlledCamera.release.set()  # the running Connect finishes by itself; it is not interrupted
    wait(lambda: not window.connector.active)
    outcomes = window.connector.outcomes()
    assert outcomes[DeviceId.TEC].state == outcomes[DeviceId.Z_STAGE].state == "not_started"
    assert "Panic" in outcomes[DeviceId.TEC].detail
    assert _connection(controller, DeviceId.TEC) is ConnectionState.DISCONNECTED
    assert (DeviceId.TEC, "queued") not in _connect_ops(events)


def test_second_group_is_refused_while_one_runs_and_the_set_is_fixed_at_start(env):
    window, controller, events, wait = env
    ControlledCamera.block = True
    _choose(window, DeviceId.CAMERA, DeviceId.VALVE)
    window.prepare_panel.connect_button.click()
    wait(ControlledCamera.entered.is_set)
    _choose(window, DeviceId.PUMP)  # changing the selection must not alter the running operation
    assert set(window.connector.outcomes()) == {DeviceId.CAMERA, DeviceId.VALVE}
    with pytest.raises(RuntimeError, match="already running"):
        window.connector.connect({DeviceId.PUMP: window.panels[DeviceId.PUMP].build_connect_command()})
    ControlledCamera.release.set()
    wait(lambda: not window.connector.active)
    assert _connection(controller, DeviceId.VALVE) is ConnectionState.CONNECTED
    assert _connection(controller, DeviceId.PUMP) is ConnectionState.DISCONNECTED


def test_device_pages_keep_their_own_connect_disconnect_and_open_page_works(env):
    window, controller, events, wait = env
    panel = window.panels[DeviceId.VALVE]
    panel._buttons["connect"].click()
    wait(lambda: _connection(controller, DeviceId.VALVE) is ConnectionState.CONNECTED)
    panel._buttons["disconnect"].click()
    wait(lambda: _connection(controller, DeviceId.VALVE) is ConnectionState.DISCONNECTED)
    window.prepare_panel.page_buttons[DeviceId.TEC].click()
    assert window.tabs.currentWidget() is window.panels[DeviceId.TEC]
