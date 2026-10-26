"""Abort, Z-stack exclusion and window-close paths, against simulated devices only."""

from __future__ import annotations

import dataclasses
import json
from time import monotonic, sleep

import pytest
from PySide6.QtWidgets import QApplication

from thermo_acoustic.application.commands import (
    DeviceCommand, DeviceOperation, TecReadStatusArgs,
)
from thermo_acoustic.domain.models import DeviceId
from test_simple_series import (
    _TERMINAL_STATES, _connected_temperature_series_harness, _wait_until_terminal,
)


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication(["test-abort-close"])


def pump_events(app, seconds):
    end = monotonic() + seconds
    while monotonic() < end:
        app.processEvents()
        sleep(0.005)


def make_tec_unstable(controller):
    """The simulated TEC reports a temperature far from the target, so stability never arrives."""
    device = controller.registry.by_id(DeviceId.TEC).device
    original = device.read_status
    def read_status(channels=None):
        return {channel: dataclasses.replace(status, current_temperature_c=0.0)
                for channel, status in original(channels).items()}

    device.read_status = read_status
    return device


def test_abort_during_the_tec_stability_wait_cancels_it_and_frees_the_command_lane(qt_app, tmp_path):
    app = qt_app
    controller, panel, results, events = _connected_temperature_series_harness(app, repeats=1)
    try:
        panel.temperature_max_wait.setValue(12)  # a lingering wait would hold the lane ~12 s
        tec = make_tec_unstable(controller)
        folder = controller.experiments.queue(panel._definition(), tmp_path)
        assert controller.experiments.start()
        deadline = monotonic() + 20
        while monotonic() < deadline and not any(
                e.operation is DeviceOperation.TEC_WAIT_STABLE and e.state == "running" for e in events):
            app.processEvents(); sleep(0.005)
        pump_events(app, 0.3)
        controller.experiments.abort()
        started = monotonic()
        status = _wait_until_terminal(app, controller)
        assert status["state"] == "aborted", status

        # The wait is cancelled and the polling stops...
        pump_events(app, 0.4)
        assert controller.active_device_command() is None
        assert controller.statuses()[DeviceId.TEC].busy is False
        # ...so an ordinary command is not held until max_wait_s.
        controller.submit(DeviceCommand(DeviceId.TEC, DeviceOperation.TEC_STATUS_READ, TecReadStatusArgs()))
        deadline = monotonic() + 3
        while monotonic() < deadline and not any(
                e.operation is DeviceOperation.TEC_STATUS_READ and e.state == "completed" for e in events):
            app.processEvents(); sleep(0.005)
        assert any(e.operation is DeviceOperation.TEC_STATUS_READ and e.state == "completed" for e in events)
        assert monotonic() - started < 8

        # The wait is cancelled, not the regulation: output policy is unchanged.
        assert tec.outputs_enabled is True
        # The terminal state is the abort, and the late result did not start anything.
        document = json.loads((folder / "metadata" / "status.json").read_text())
        assert document["finalized_outcome"] == "aborted"
        assert document["experiments_started"] == 0
        assert controller.experiments.status()["state"] == "aborted"
        assert not any(e.operation is DeviceOperation.CAMERA_SEQUENCE_ARM for e in events)
    finally:
        panel.close()
        controller.shutdown()


# ------------------------------------------------- Z stack vs a running batch
def connect_z_stage(app, controller, events):
    for operation in (DeviceOperation.CONNECT,
                      DeviceOperation.Z_STAGE_CLOSED_LOOP_REQUIREMENT_READ,
                      DeviceOperation.Z_STAGE_CLOSED_LOOP_ENABLE):
        controller.submit(DeviceCommand(DeviceId.Z_STAGE, operation))
        deadline = monotonic() + 3
        while monotonic() < deadline and not any(
                e.operation is operation and e.state == "completed" for e in events):
            app.processEvents(); sleep(0.005)
    assert controller.statuses()[DeviceId.Z_STAGE].readback.closed_loop


def z_settings(folder):
    from thermo_acoustic.application.z_stack import ZStackSettings
    return ZStackSettings(0.0, 5.0, 3, 5.0, (0, 0, 16, 16), folder)


@pytest.mark.parametrize("phase", ["running", "stopping"])
def test_z_stack_entry_points_refuse_while_a_batch_owns_the_instruments(qt_app, tmp_path, phase):
    from thermo_acoustic.application.commands import WorkflowProgress
    app = qt_app
    controller, panel, results, events = _connected_temperature_series_harness(app, repeats=1)
    zfolder = tmp_path / "z"
    zfolder.mkdir()
    try:
        connect_z_stage(app, controller, events)
        zstack = controller.z_stack
        (tmp_path / "out").mkdir()
        controller.experiments.queue(panel._definition(), tmp_path / "out")
        assert controller.experiments.start()
        if phase == "running":
            deadline = monotonic() + 20
            while monotonic() < deadline and not any(
                    e.operation is DeviceOperation.CAMERA_SEQUENCE_ARM and e.state == "running" for e in events):
                app.processEvents(); sleep(0.005)
        else:
            seen = []
            controller.command_progress.connect(
                lambda _rid, value: seen.append(value) if isinstance(value, WorkflowProgress) else None)
            deadline = monotonic() + 20
            while monotonic() < deadline and not any(v.state == "open_settle" for v in seen):
                app.processEvents(); sleep(0.005)
            controller.experiments.abort()
            assert controller.experiments.status()["state"] == "stopping"  # flush still draining
        for attempt in (lambda: zstack.start(z_settings(zfolder)),
                        lambda: zstack.start_preview(5.0),
                        lambda: zstack.move_to(1.0),
                        lambda: zstack.move_relative(1.0)):
            with pytest.raises(RuntimeError, match="experiment"):
                attempt()
        # Refused up front: no stray state change or file in the Z-stack output folder.
        assert zstack.state == "idle"
        assert list(zfolder.iterdir()) == []
        _wait_until_terminal(app, controller)
    finally:
        panel.close()
        controller.shutdown()


# ------------------------------------------------- stage_move prerequisites
def definition_with_stage_move(panel, position_um):
    from thermo_acoustic.application.experiments import validate_definition
    definition = panel._definition()

    def walk(steps):
        for step in steps:
            if step["type"] == "experiment":
                step["steps"].insert(0, {"type": "stage_move", "args": {"position_um": position_um}})
            elif "steps" in step:
                walk(step["steps"])

    walk(definition["steps"])
    validate_definition(definition)
    return definition


def test_stage_move_series_refuses_to_start_without_closed_loop_before_any_other_action(qt_app, tmp_path):
    app = qt_app
    controller, panel, results, events = _connected_temperature_series_harness(app, repeats=1)
    try:
        controller.submit(DeviceCommand(DeviceId.Z_STAGE, DeviceOperation.CONNECT))
        deadline = monotonic() + 3
        while monotonic() < deadline and controller.statuses()[DeviceId.Z_STAGE].connection.value != "connected":
            app.processEvents(); sleep(0.005)
        z_device = controller.registry.by_id(DeviceId.Z_STAGE).device
        position_before = z_device.position_um
        assert controller.statuses()[DeviceId.Z_STAGE].readback.closed_loop is False
        folder = controller.experiments.queue(definition_with_stage_move(panel, 10.0), tmp_path)
        assert controller.experiments.start()
        status = _wait_until_terminal(app, controller)
        assert status["state"] == "failed", status
        assert "closed-loop" in status["phase"]
        # Nothing but the failure path's own SAFE_STOP was dispatched: no flush, heating,
        # camera configuration or AD2 waveform.
        dispatched = {e.operation for e in events if e.source == "experiment" and e.state == "running"}
        assert dispatched <= {DeviceOperation.SAFE_STOP}, dispatched
        # The stage was neither switched to closed loop nor moved.
        assert controller.statuses()[DeviceId.Z_STAGE].readback.closed_loop is False
        assert z_device.position_um == position_before
        document = json.loads((folder / "metadata" / "status.json").read_text())
        assert document["state"] == "failed" and document["experiments_started"] == 0
    finally:
        panel.close()
        controller.shutdown()


def test_stage_move_series_runs_when_the_stage_is_connected_and_closed_loop(qt_app, tmp_path):
    app = qt_app
    controller, panel, results, events = _connected_temperature_series_harness(app, repeats=1)
    try:
        connect_z_stage(app, controller, events)
        controller.experiments.queue(definition_with_stage_move(panel, 10.0), tmp_path)
        assert controller.experiments.start()
        status = _wait_until_terminal(app, controller, timeout=60)
        assert status["state"] == "completed", status
        assert any(e.operation is DeviceOperation.Z_STAGE_POSITION_SET and e.state == "completed" for e in events)
    finally:
        panel.close()
        controller.shutdown()
