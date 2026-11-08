"""After a batch has run to its normal end the valve is left Open, once, confirmed; no other ending does this.
Simulated devices only. 'Open' and 'Closed' are the chip-side meanings of valve positions 1 and 2."""

from __future__ import annotations

import tempfile
import threading
from dataclasses import replace
from pathlib import Path
from time import monotonic, sleep
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from test_simple_series import settings
from thermo_acoustic.application import ApplicationController
from thermo_acoustic.application.commands import (
    DeviceCommand, DeviceOperation, PumpSetFillLevelArgs, ValvePosition,
)
from thermo_acoustic.application.simple_series import NumericRange, compile_simple_series
from thermo_acoustic.domain.models import ConnectionState, DeviceId, OperatingMode
from thermo_acoustic.hal.registry import DeviceRegistry

STEP = "Setting the valve Open after the batch"


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication(["test-batch-valve-open"])


def _wait(app, condition, timeout=90):
    deadline = monotonic() + timeout
    while monotonic() < deadline and not condition():
        app.processEvents()
        sleep(0.005)
    return condition()


class Batch:
    def __init__(self, app, series=1, repeats=1, patch=None):
        self.app = app
        self.controller = ApplicationController(DeviceRegistry(mode=OperatingMode.SIMULATION), mode=OperatingMode.SIMULATION)
        c = self.controller
        c.start()
        self.events = []
        c.command_event.connect(self.events.append)
        results = []
        c.command_result.connect(results.append)
        for device in (DeviceId.AD2, DeviceId.CAMERA, DeviceId.PUMP, DeviceId.VALVE):
            c.submit(DeviceCommand(device, DeviceOperation.CONNECT))
        assert _wait(app, lambda: sum(r.operation is DeviceOperation.CONNECT and r.ok for r in results) == 4, 20)
        c.submit(DeviceCommand(DeviceId.PUMP, DeviceOperation.PUMP_FILL_LEVEL_SET, PumpSetFillLevelArgs(1.0)))
        assert _wait(app, lambda: any(r.operation is DeviceOperation.PUMP_FILL_LEVEL_SET and r.ok for r in results), 20)
        c.experiments.confirm_unchecked = lambda summary: True
        c.experiments.confirm_batch = lambda summary: True
        if patch is not None:
            patch(c)
        self.base = tempfile.mkdtemp()
        for index in range(series):
            form = replace(settings(), flush_unit_index=0, flush_volume_ml=0.05, frame_count=2, repeats=repeats,
                           frequency_hz=NumericRange(1e6, 1e6, 1), amplitude_v=NumericRange(1, 1, 1),
                           exposure_ms=NumericRange(1, 1, 1), sweep_enabled=False, temperature_control=False,
                           temperature_logging=False, roi=(0, 0, 16, 16), description=f"series {index}")
            c.experiments.queue(compile_simple_series(form), self.base)
        outcome = []
        c.experiments.preflight_syringe(lambda ok, message: outcome.append(ok))
        assert _wait(app, lambda: bool(outcome), 20)

    def opens(self):
        """Valve Open commands the batch itself sent at its end (the flush workflow's own are source 'workflow')."""
        return [e for e in self.events if e.operation is DeviceOperation.VALVE_POSITION_SET and e.source == "experiment"
                and e.state == "queued" and e.arguments.position == ValvePosition.OPEN.value]

    def run(self):
        assert self.controller.experiments.start()
        assert _wait(self.app, lambda: self.controller.experiments.status()["state"] in
                     ("completed", "failed", "aborted", "stopped"))
        return self.controller.experiments.status()

    def close(self):
        self.controller.shutdown()


def test_a_normal_batch_ends_with_one_confirmed_open_after_its_last_flush(qt_app):
    batch = Batch(qt_app, series=1, repeats=2)
    try:
        status = batch.run()
        assert status["state"] == "completed" and status["phase"] == "Experiment series completed", status["phase"]
        assert len(batch.opens()) == 1  # once, at the end of the whole batch, not per repeat
        valve = batch.controller.statuses()[DeviceId.VALVE].readback
        assert valve.confirmed_position == ValvePosition.OPEN.value and valve.ready
        steps = [(e.operation, e.source) for e in batch.events if e.state == "completed"
                 and e.operation in (DeviceOperation.VALVE_POSITION_SET, DeviceOperation.VALVE_WAIT_READY)]
        assert steps[-2:] == [(DeviceOperation.VALVE_POSITION_SET, "experiment"),
                              (DeviceOperation.VALVE_WAIT_READY, "experiment")]  # the last valve actions of the batch
        assert status["batch_completed_experiments"] == 2 and not status["end_problems"]
    finally:
        batch.close()


def test_several_series_keep_their_flushes_and_open_once_after_the_last(qt_app):
    calls = []

    def record_valve_calls(controller):
        device = controller.registry.by_id(DeviceId.VALVE).device
        original = device.set_position

        def set_position(position):
            calls.append((position, controller.experiments._phase == STEP))
            return original(position)
        device.set_position = set_position
    batch = Batch(qt_app, series=2, patch=record_valve_calls)
    try:
        status = batch.run()
        assert status["state"] == "completed" and len(batch.opens()) == 1
        flush_closes = [c for c in calls if c == (ValvePosition.CLOSED.value, False)]
        assert len(flush_closes) >= 3  # the flush workflow still closes the valve after each flush (initial + 2 series)
        assert calls[-1] == (ValvePosition.OPEN.value, True)  # and the batch's own Open is the very last valve action
        assert calls.count((ValvePosition.OPEN.value, True)) == 1
        assert batch.controller.statuses()[DeviceId.VALVE].readback.confirmed_position == ValvePosition.OPEN.value
    finally:
        batch.close()


def _break_open_at_end(controller, how):
    device = controller.registry.by_id(DeviceId.VALVE).device

    def in_end_step():
        return controller.experiments._phase == STEP
    if how == "set":
        original = device.set_position

        def set_position(position):
            if in_end_step():
                raise RuntimeError("simulated valve set failure")
            return original(position)
        device.set_position = set_position
    else:
        original = device.wait_until_ready

        def wait_until_ready(timeout_s, poll_s):
            return False if in_end_step() else original(timeout_s, poll_s)
        device.wait_until_ready = wait_until_ready


@pytest.mark.parametrize("how,expected", [("set", "could not be set Open"), ("confirm", "not confirm")])
def test_a_valve_step_that_fails_is_reported_and_the_science_is_kept(qt_app, how, expected):
    batch = Batch(qt_app, series=1, repeats=2, patch=lambda c: _break_open_at_end(c, how))
    try:
        status = batch.run()
        assert status["state"] == "completed" and status["batch_completed_experiments"] == 2
        assert status["end_problems"] and expected in status["end_problems"][0], status["end_problems"]
        assert "end-of-batch step had a problem" in status["phase"]  # not the plain success wording
        assert len(list(Path(batch.base).rglob("*.tif"))) == 4  # the saved images are all still there
    finally:
        batch.close()


def test_stop_after_current_and_abort_do_not_open_the_valve(qt_app):
    batch = Batch(qt_app, series=2)
    try:
        assert batch.controller.experiments.start()
        batch.controller.experiments.stop_after_current()
        assert _wait(qt_app, lambda: batch.controller.experiments.status()["state"] in ("stopped", "completed", "failed"))
        assert batch.controller.experiments.status()["state"] == "stopped" and batch.opens() == []
    finally:
        batch.close()
    batch = Batch(qt_app, series=1)
    try:
        fired = []

        def abort_on_trigger(event):
            if not fired and event.operation is DeviceOperation.AD2_SOFTWARE_TRIGGER and event.state == "completed":
                fired.append(1)
                batch.controller.experiments.abort()
        batch.controller.command_event.connect(abort_on_trigger)
        status = batch.run()
        assert status["state"] == "aborted" and batch.opens() == []
    finally:
        batch.close()


def test_abort_during_the_valve_step_stops_further_steps_and_does_not_claim_the_valve(qt_app):
    release = threading.Event()
    reached = threading.Event()

    def block_open_at_end(controller):
        device = controller.registry.by_id(DeviceId.VALVE).device
        original = device.set_position

        def set_position(position):
            if controller.experiments._phase == STEP:
                reached.set()
                assert release.wait(20)
            return original(position)
        device.set_position = set_position
    batch = Batch(qt_app, series=1, patch=block_open_at_end)
    try:
        assert batch.controller.experiments.start()
        assert _wait(qt_app, reached.is_set)
        batch.controller.experiments.abort()  # the Open command is already with the valve and cannot be recalled
        release.set()
        assert _wait(qt_app, lambda: batch.controller.experiments.status()["state"] in ("aborted", "completed", "failed"))
        status = batch.controller.experiments.status()
        assert status["state"] == "aborted" and "Open command had already been sent" in status["phase"], status["phase"]
        assert not [e for e in batch.events if e.operation is DeviceOperation.VALVE_WAIT_READY and e.source == "experiment"
                    and e.state == "running"]  # no later step of the old end sequence ran
        assert len(batch.opens()) == 1  # and it was not sent again
    finally:
        release.set()
        batch.close()


def test_with_no_valve_connected_the_end_step_is_skipped_and_says_so():
    from thermo_acoustic.application.experiment_runner import ExperimentManager
    submitted = []
    statuses = {d: SimpleNamespace(connection=ConnectionState.DISCONNECTED) for d in DeviceId}
    controller = SimpleNamespace(statuses=lambda: statuses, submit=submitted.append)
    manager = ExperimentManager.__new__(ExperimentManager)
    manager.controller = controller
    manager._state = "running"
    manager._failed = manager._abort_requested = False
    manager._end_problems, manager._end_failure, manager._callbacks = [], {}, {}
    manager._last_storage = None
    manager._publish = lambda: None
    manager.notice = SimpleNamespace(emit=lambda *_: None)
    manager._batch_pump_units = set()
    manager._valve_open_sent = False
    manager._end_of_batch()
    assert manager._state == "completed" and submitted == [] and manager._end_problems == []
    assert "valve is not connected" in manager._phase and "not set Open" in manager._phase  # never claims Open
