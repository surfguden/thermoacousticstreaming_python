"""Workflow behavior is verified only against simulated devices."""

from __future__ import annotations

from time import monotonic, sleep

import pytest
from PySide6.QtWidgets import QApplication

from thermo_acoustic.application import ApplicationController, DeviceCommand, DeviceOperation
from thermo_acoustic.application.audit import AuditLogger
from thermo_acoustic.application.commands import (
    FlushArgs, ValveSetPositionArgs, WaitArgs, WorkflowCommand, WorkflowOperation,
)
from thermo_acoustic.console.parser import parse_command
from thermo_acoustic.domain.models import DeviceId, OperatingMode
from thermo_acoustic.hal.registry import DeviceRegistry
from thermo_acoustic.ui.workflow_panel import WorkflowPanel


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication(["test-workflows"])


def until(app, predicate, timeout=5.0):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        sleep(0.01)
    assert predicate(), "Timed out waiting for simulated workflow"


def connected_controller(app):
    controller = ApplicationController(DeviceRegistry(), mode=OperatingMode.SIMULATION)
    results = []
    events = []
    controller.command_result.connect(results.append)
    controller.command_event.connect(events.append)
    controller.start()
    for device in (DeviceId.PUMP, DeviceId.VALVE, DeviceId.CAMERA):
        controller.submit(DeviceCommand(device, DeviceOperation.CONNECT))
    until(app, lambda: sum(event.state == "completed" and event.operation is DeviceOperation.CONNECT for event in events) == 3)
    return controller, results, events


def test_flush_allows_camera_commands_but_reserves_pump_and_valve(qt_app):
    controller, results, events = connected_controller(qt_app)
    try:
        controller.submit(parse_command("pump refill"))
        until(qt_app, lambda: any(result.operation is DeviceOperation.PUMP_REFILL for result in results))
        flush = WorkflowCommand(WorkflowOperation.FLUSH, FlushArgs(0, 0.1, 1000, 0))
        camera = DeviceCommand(DeviceId.CAMERA, DeviceOperation.CAMERA_TIMING_READ)
        pump = DeviceCommand(DeviceId.PUMP, DeviceOperation.PUMP_STATUS_READ)
        controller.submit(flush)
        controller.submit(pump)
        controller.submit(camera)
        until(qt_app, lambda: any(result.request_id == flush.request_id for result in results))
        until(qt_app, lambda: any(result.request_id == pump.request_id for result in results))
        completed = [event.request_id for event in events if event.state == "completed"]
        assert completed.index(camera.request_id) < completed.index(flush.request_id)
        assert completed.index(flush.request_id) < completed.index(pump.request_id)
        assert next(result for result in results if result.request_id == flush.request_id).ok
        valve = controller.statuses()[DeviceId.VALVE].readback
        assert valve.confirmed_position == 2
    finally:
        controller.shutdown()


def test_flush_rejects_negative_target_and_cancels_later_queue(qt_app):
    controller, results, events = connected_controller(qt_app)
    try:
        flush = WorkflowCommand(WorkflowOperation.FLUSH, FlushArgs(0, 0.1, 1000))
        barrier = WorkflowCommand(WorkflowOperation.WAIT, WaitArgs(0))
        controller.submit(flush)
        controller.submit(barrier)
        until(qt_app, lambda: any(result.request_id == flush.request_id for result in results))
        result = next(result for result in results if result.request_id == flush.request_id)
        assert not result.ok and "cannot flush" in result.error
        assert any(event.request_id == barrier.request_id and event.state == "cancelled" for event in events)
        assert controller.statuses()[DeviceId.VALVE].readback.confirmed_position == 2
    finally:
        controller.shutdown()


def test_flush_rejects_implausible_reading_even_when_it_would_also_be_negative(qt_app):
    # The reading itself is untrustworthy (10 ml on a 1 ml default-capacity
    # unit) and would also have produced a negative target under the
    # pre-existing target<0 check -- confirm the new, more diagnosable
    # message fires, not the old "cannot flush" one, and that failure still
    # runs the normal stop/valve-recovery path to a final failed state.
    controller, results, events = connected_controller(qt_app)
    try:
        pump = controller.registry.by_id(DeviceId.PUMP).device
        pump._pump(0).fill_level_ml = 10.0
        flush = WorkflowCommand(WorkflowOperation.FLUSH, FlushArgs(0, 20.0, 1000, 0))
        controller.submit(flush)
        until(qt_app, lambda: any(result.request_id == flush.request_id for result in results))
        result = next(result for result in results if result.request_id == flush.request_id)
        assert not result.ok
        assert "exceeds its configured capacity" in result.error
        assert "cannot flush" not in result.error
        # The recovery path (stop pump -> confirm idle -> close valve) only
        # reaches a confirmed-closed valve if PUMP_FLOW_STOP actually ran and
        # the pump was confirmed idle afterwards -- this is the same proof
        # pattern test_flush_rejects_negative_target_and_cancels_later_queue
        # already uses for the pre-existing target<0 failure path.
        assert controller.statuses()[DeviceId.VALVE].readback.confirmed_position == 2
    finally:
        controller.shutdown()


def test_flush_rejects_implausible_reading_even_when_computed_target_is_in_range(qt_app):
    # 10 ml reading minus a 0.1 ml flush leaves a positive, in-range target
    # (9.9 ml) that the pre-existing target<0 check would have let through --
    # only the new plausibility check catches this, and it must do so before
    # ever attempting to send PUMP_FILL_LEVEL_SET for that implausible target.
    controller, results, events = connected_controller(qt_app)
    try:
        pump = controller.registry.by_id(DeviceId.PUMP).device
        pump._pump(0).fill_level_ml = 10.0
        flush = WorkflowCommand(WorkflowOperation.FLUSH, FlushArgs(0, 0.1, 1000, 0))
        controller.submit(flush)
        until(qt_app, lambda: any(result.request_id == flush.request_id for result in results))
        result = next(result for result in results if result.request_id == flush.request_id)
        assert not result.ok
        assert "exceeds its configured capacity" in result.error
        assert not any(event.operation is DeviceOperation.PUMP_FILL_LEVEL_SET for event in events)
        assert controller.statuses()[DeviceId.VALVE].readback.confirmed_position == 2
    finally:
        controller.shutdown()


def test_flush_succeeds_with_a_legitimate_fill_level_reading(qt_app):
    controller, results, events = connected_controller(qt_app)
    try:
        controller.submit(parse_command("pump refill"))
        until(qt_app, lambda: any(result.operation is DeviceOperation.PUMP_REFILL for result in results))
        flush = WorkflowCommand(WorkflowOperation.FLUSH, FlushArgs(0, 0.1, 1000, 0))
        controller.submit(flush)
        until(qt_app, lambda: any(result.request_id == flush.request_id for result in results))
        result = next(result for result in results if result.request_id == flush.request_id)
        assert result.ok
    finally:
        controller.shutdown()


def test_flush_capacity_check_uses_the_selected_units_own_capacity(qt_app):
    # Unit 1 is given a larger capacity (5 ml) than unit 0's 1 ml default; a
    # 2 ml reading on unit 1 would be implausible against unit 0's capacity
    # but is legitimate against unit 1's own -- proves the check reads
    # PumpReadback.units[unit_index], not unit 0 or a fixed default.
    controller, results, events = connected_controller(qt_app)
    try:
        pump = controller.registry.by_id(DeviceId.PUMP).device
        pump._pump(1).max_volume_ml = 5.0
        pump._pump(1).fill_level_ml = 2.0
        flush = WorkflowCommand(WorkflowOperation.FLUSH, FlushArgs(1, 0.1, 1000, 0))
        controller.submit(flush)
        until(qt_app, lambda: any(result.request_id == flush.request_id for result in results))
        result = next(result for result in results if result.request_id == flush.request_id)
        assert result.ok
    finally:
        controller.shutdown()


def test_wait_is_queue_barrier_and_cli_accepts_workflows(qt_app):
    controller, results, events = connected_controller(qt_app)
    try:
        command = parse_command("workflow wait --seconds 0.2")
        assert command.operation is WorkflowOperation.WAIT
        assert parse_command("workflow flush --unit 2 --volume-ml 0.5 --flow-ul-min 250 --wait-after-s 3").arguments.unit_index == 1
        with pytest.raises(ValueError):
            parse_command("workflow flush --unit 0 --volume-ml 1 --flow-ul-min 100")
        with pytest.raises(ValueError):
            ValveSetPositionArgs(3)
        camera = DeviceCommand(DeviceId.CAMERA, DeviceOperation.CAMERA_TIMING_READ)
        controller.submit(command)
        controller.submit(camera)
        until(qt_app, lambda: any(result.request_id == camera.request_id for result in results))
        completed = [event.request_id for event in events if event.state == "completed"]
        assert completed.index(command.request_id) < completed.index(camera.request_id)
    finally:
        controller.shutdown()


def test_workflow_panel_requires_connected_pump_unit(qt_app):
    panel = WorkflowPanel()
    emitted = []
    panel.command_requested.connect(lambda _, command: emitted.append(command))
    panel._request_flush()
    assert not emitted
    from thermo_acoustic.domain.models import PumpReadback, PumpUnitReadback
    panel.update_pumps(PumpReadback(units=(PumpUnitReadback(0, syringe_name="BD 1ml"),)))
    panel.unit.setCurrentIndex(1)
    panel._request_flush()
    assert emitted[0].arguments.unit_index == 0


def test_audit_path_is_anchored_at_startup(tmp_path, monkeypatch):
    launch_dir = tmp_path / "launch"
    other_dir = tmp_path / "other"
    launch_dir.mkdir()
    other_dir.mkdir()
    monkeypatch.chdir(launch_dir)
    audit = AuditLogger("logs/run.jsonl")
    monkeypatch.chdir(other_dir)
    assert audit.write("started") is None
    assert (launch_dir / "logs" / "run.jsonl").exists()
    assert not (other_dir / "logs").exists()


def test_unavailable_audit_log_does_not_block_flush_camera_or_stop(qt_app, tmp_path):
    blocked_parent = tmp_path / "logs"
    blocked_parent.write_text("not a directory", encoding="utf-8")
    controller = ApplicationController(
        DeviceRegistry(), mode=OperatingMode.SIMULATION,
        audit=AuditLogger(blocked_parent / "run.jsonl"),
    )
    results = []
    warnings = []
    controller.command_result.connect(results.append)
    controller.message.connect(warnings.append)
    controller.start()
    try:
        for device in (DeviceId.PUMP, DeviceId.VALVE):
            controller.submit(DeviceCommand(device, DeviceOperation.CONNECT))
        until(qt_app, lambda: len([r for r in results if r.operation is DeviceOperation.CONNECT]) == 2)
        controller.submit(parse_command("pump refill"))
        until(qt_app, lambda: any(r.operation is DeviceOperation.PUMP_REFILL for r in results))
        flush = WorkflowCommand(WorkflowOperation.FLUSH, FlushArgs(0, 0.1, 1000))
        camera = DeviceCommand(DeviceId.CAMERA, DeviceOperation.CONNECT)
        controller.submit(flush)
        controller.submit(camera)
        until(qt_app, lambda: any(r.request_id == flush.request_id for r in results))
        assert next(r for r in results if r.request_id == flush.request_id).ok
        assert next(r for r in results if r.request_id == camera.request_id).ok
        stop = parse_command("pump stop")
        controller.submit(stop)
        until(qt_app, lambda: any(r.request_id == stop.request_id for r in results))
        assert next(r for r in results if r.request_id == stop.request_id).ok
        assert len(warnings) == 1
        assert str(blocked_parent / "run.jsonl") in warnings[0]
    finally:
        controller.shutdown()
