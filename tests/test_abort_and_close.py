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


# ------------------------------------------------------- real MainWindow close
def _window_with_series(app, repeats=1):
    from thermo_acoustic.ui.main_window import MainWindow
    controller, panel, results, events = _connected_temperature_series_harness(app, repeats=repeats)
    window = MainWindow(controller)
    window.show()
    controller.experiments.confirm_unchecked = lambda _summary: True
    controller.experiments.confirm_batch = lambda _summary: True
    app.processEvents()
    return controller, panel, window, events


def _close_when(controller, predicate, window):
    outcome = {}

    def handler(event):
        if "result" not in outcome and predicate(event):
            outcome["result"] = window.close()

    controller.command_event.connect(handler)
    return outcome


def _wait_for(app, predicate, timeout):
    deadline = monotonic() + timeout
    while monotonic() < deadline and not predicate():
        app.processEvents(); sleep(0.005)
    return predicate()


@pytest.mark.parametrize("phase", ["capture", "save_and_flush", "tec_wait"])
def test_closing_the_window_mid_run_reuses_abort_and_closes_after_the_drain(qt_app, tmp_path, phase):
    app = qt_app
    controller, panel, window, events = _window_with_series(app)
    try:
        if phase == "tec_wait":
            make_tec_unstable(controller)
            panel.temperature_max_wait.setValue(30)
        predicate = {
            "capture": lambda e: e.operation is DeviceOperation.AD2_SOFTWARE_TRIGGER and e.state == "completed",
            "save_and_flush": lambda e: e.operation is DeviceOperation.CAMERA_SEQUENCE_COLLECT and e.state == "completed",
            "tec_wait": lambda e: e.operation is DeviceOperation.TEC_WAIT_STABLE and e.state == "running",
        }[phase]
        outcome = _close_when(controller, predicate, window)
        folder = controller.experiments.queue(panel._definition(), tmp_path)
        assert controller.experiments.start()
        assert _wait_for(app, lambda: "result" in outcome, 40), "close was never requested"
        # The close is deferred while the batch drains, not accepted with work in flight.
        assert outcome["result"] is False
        assert window.isVisible()
        with pytest.raises(RuntimeError):
            controller.experiments.start()
        # Once the abort and its save/flush drain have finished the window closes by itself.
        assert _wait_for(app, lambda: not window.isVisible(), 60), controller.experiments.status()
        document = json.loads((folder / "metadata" / "status.json").read_text())
        assert document["state"] == "aborted" and document["finalized_outcome"] == "aborted"
        assert "window" in document["error"].lower()
        # Data already written stays complete; no half-written experiment folder is left.
        for experiment_dir in folder.rglob("repeat_*"):
            if experiment_dir.is_dir():
                assert (experiment_dir / "experiment.json").exists(), experiment_dir
        assert not any(worker._thread.isRunning() for worker in controller.registry.all())
    finally:
        panel.close()
        window.close()
        controller.shutdown()


def _idle_window():
    from thermo_acoustic.application.controller import ApplicationController
    from thermo_acoustic.domain.models import OperatingMode
    from thermo_acoustic.hal.registry import DeviceRegistry
    from thermo_acoustic.ui.main_window import MainWindow
    controller = ApplicationController(DeviceRegistry(), mode=OperatingMode.SIMULATION)
    window = MainWindow(controller)
    controller.start()
    window.show()
    return controller, window


def test_close_while_idle_closes_at_once(qt_app):
    controller, window = _idle_window()
    qt_app.processEvents()
    assert window.close() is True
    assert not any(worker._thread.isRunning() for worker in controller.registry.all())


def test_a_failing_disconnect_is_reported_and_the_second_close_is_accepted(qt_app):
    controller, window = _idle_window()
    controller.submit(DeviceCommand(DeviceId.PUMP, DeviceOperation.CONNECT))
    assert _wait_for(qt_app, lambda: controller.statuses()[DeviceId.PUMP].connection.value == "connected", 5)

    def broken_disconnect():
        raise RuntimeError("simulated disconnect failure")

    controller.registry.by_id(DeviceId.PUMP).disconnect_device = broken_disconnect
    assert window.close() is False
    assert window.isVisible()
    assert "simulated disconnect failure" in window.statusBar().currentMessage()
    assert not any(worker._thread.isRunning() for worker in controller.registry.all())
    assert window.close() is True


def test_controller_signals_every_worker_before_waiting(qt_app):
    """Six workers that each need ~0.6 s must not take ~3.6 s in sequence."""
    from thermo_acoustic.application.controller import ApplicationController
    from thermo_acoustic.domain.models import OperatingMode
    from thermo_acoustic.hal.registry import DeviceRegistry
    controller = ApplicationController(DeviceRegistry(), mode=OperatingMode.SIMULATION)
    controller.start()
    for worker in controller.registry.all():
        original = worker.disconnect_device

        def slow(original=original):
            sleep(0.6)
            original()

        worker.disconnect_device = slow
    started = monotonic()
    errors = controller.shutdown()
    elapsed = monotonic() - started
    assert errors == []
    assert elapsed < 2.0, elapsed
    assert controller.shutdown_pending_devices() == []


HUNG_WORKER_SCRIPT = """
import os, sys, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication
from thermo_acoustic.application.commands import DeviceCommand, DeviceOperation
from thermo_acoustic.application.controller import ApplicationController
from thermo_acoustic.domain.models import DeviceId, OperatingMode
from thermo_acoustic.hal.registry import DeviceRegistry
from thermo_acoustic.ui.main_window import MainWindow

app = QApplication(["hung-worker"])
ApplicationController.SHUTDOWN_WAIT_S = 0.3
controller = ApplicationController(DeviceRegistry(), mode=OperatingMode.SIMULATION)
window = MainWindow(controller)
controller.start()
window.show()
controller.submit(DeviceCommand(DeviceId.PUMP, DeviceOperation.CONNECT))
end = time.monotonic() + 5
while time.monotonic() < end and controller.statuses()[DeviceId.PUMP].connection.value != "connected":
    app.processEvents(); time.sleep(0.01)
worker = controller.registry.by_id(DeviceId.PUMP)
original = worker.disconnect_device
worker.disconnect_device = lambda: (time.sleep(1.5), original())[1]

first = window.close()
print("FIRST_CLOSE_ACCEPTED", first, flush=True)
print("WINDOW_STILL_OPEN", window.isVisible(), flush=True)
print("PENDING", controller.shutdown_pending_devices(), flush=True)
print("STATUS", window.statusBar().currentMessage(), flush=True)
try:
    controller.submit(DeviceCommand(DeviceId.PUMP, DeviceOperation.PUMP_STATUS_READ))
    print("NEW_COMMAND", "accepted", flush=True)
except RuntimeError:
    print("NEW_COMMAND", "refused", flush=True)
try:
    controller.experiments.start()
    print("NEW_RUN", "accepted", flush=True)
except RuntimeError:
    print("NEW_RUN", "refused", flush=True)
end = time.monotonic() + 5
while time.monotonic() < end and worker._thread.isRunning():
    app.processEvents(); time.sleep(0.01)
second = window.close()
print("SECOND_CLOSE_ACCEPTED", second, flush=True)
print("THREADS_RUNNING", [w.device_id.value for w in controller.registry.all() if w._thread.isRunning()], flush=True)
"""


def test_a_worker_that_outlives_the_wait_keeps_the_app_open_until_it_finishes():
    """Runs in a subprocess: tearing down a QThread that is still running aborts the whole process."""
    import os
    import subprocess
    import sys
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path), "QT_QPA_PLATFORM": "offscreen"}
    run = subprocess.run([sys.executable, "-c", HUNG_WORKER_SCRIPT], env=env, capture_output=True,
                         text=True, timeout=60)
    lines = {line.split(" ", 1)[0]: line.split(" ", 1)[1] if " " in line else ""
             for line in run.stdout.splitlines()}
    assert run.returncode == 0, (run.returncode, run.stdout, run.stderr)
    assert lines["FIRST_CLOSE_ACCEPTED"] == "False"
    assert lines["WINDOW_STILL_OPEN"] == "True"
    assert lines["PENDING"] == "['pump']"
    assert "pump" in lines["STATUS"]
    assert lines["NEW_COMMAND"] == "refused" and lines["NEW_RUN"] == "refused"
    assert lines["SECOND_CLOSE_ACCEPTED"] == "True"
    assert lines["THREADS_RUNNING"] == "[]"


def test_a_safe_stop_failure_at_close_is_kept_even_when_cleanup_succeeds(qt_app):
    """The result must come from the worker thread itself, not from a queued signal."""
    controller, window = _idle_window()
    controller.submit(DeviceCommand(DeviceId.PUMP, DeviceOperation.CONNECT))
    assert _wait_for(qt_app, lambda: controller.statuses()[DeviceId.PUMP].connection.value == "connected", 5)
    worker = controller.registry.by_id(DeviceId.PUMP)

    def broken_safe_stop():
        raise RuntimeError("simulated safe stop failure")

    worker.safe_stop = broken_safe_stop
    cleaned = []
    original_cleanup = worker.cleanup_device
    worker.cleanup_device = lambda: (original_cleanup(), cleaned.append(True))[1]
    assert window.close() is False, "the failed stop was not reported"
    assert window.isVisible()
    assert cleaned == [True]  # the device was closed; only the stop failed
    assert "simulated safe stop failure" in window.statusBar().currentMessage()
    assert not any(w._thread.isRunning() for w in controller.registry.all())
    # Nothing depends on later event processing: the error is still there on every call.
    qt_app.processEvents()
    assert any("simulated safe stop failure" in error for error in controller.shutdown())
    assert window.close() is True


PANIC_AFTER_TIMEOUT_SCRIPT = """
import os, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication
from thermo_acoustic.application.commands import DeviceCommand, DeviceOperation
from thermo_acoustic.application.controller import ApplicationController
from thermo_acoustic.domain.models import DeviceId, OperatingMode
from thermo_acoustic.hal.registry import DeviceRegistry
from thermo_acoustic.ui.main_window import MainWindow

app = QApplication(["panic-after-timeout"])
ApplicationController.SHUTDOWN_WAIT_S = 0.3
controller = ApplicationController(DeviceRegistry(), mode=OperatingMode.SIMULATION)
window = MainWindow(controller)
controller.start()
window.show()
for device in (DeviceId.PUMP, DeviceId.AD2):
    controller.submit(DeviceCommand(device, DeviceOperation.CONNECT))
end = time.monotonic() + 5
while time.monotonic() < end and not all(
        controller.statuses()[d].connection.value == "connected" for d in (DeviceId.PUMP, DeviceId.AD2)):
    app.processEvents(); time.sleep(0.01)

stops = {"pump": 0, "ad2": 0}
for device, key in ((DeviceId.PUMP, "pump"), (DeviceId.AD2, "ad2")):
    worker = controller.registry.by_id(device)
    original_stop = worker.safe_stop
    def counted(original_stop=original_stop, key=key):
        stops[key] += 1
        return original_stop()
    worker.safe_stop = counted
pump = controller.registry.by_id(DeviceId.PUMP)
original_disconnect = pump.disconnect_device
pump.disconnect_device = lambda: (time.sleep(1.5), original_disconnect())[1]
panic_events = []
controller.command_event.connect(lambda e: panic_events.append(e) if e.source == "panic" else None)

print("CLOSE_ACCEPTED", window.close(), flush=True)
print("PENDING", controller.shutdown_pending_devices(), flush=True)
try:
    controller.panic_stop()
    print("PANIC_RAISED", False, flush=True)
except Exception as exc:
    print("PANIC_RAISED", True, flush=True)
app.processEvents()
status = controller.panic_status()
print("PANIC_STATE", status["state"], flush=True)
print("PANIC_ERRORS", " | ".join(status["errors"]), flush=True)
print("PANIC_COMMANDS", len(panic_events), flush=True)
print("PANIC_BUTTON_TEXT", window.statusBar().currentMessage(), flush=True)
end = time.monotonic() + 5
while time.monotonic() < end and pump._thread.isRunning():
    app.processEvents(); time.sleep(0.01)
app.processEvents()
print("STOP_CALLS", stops, flush=True)
print("SECOND_CLOSE_ACCEPTED", window.close(), flush=True)
"""


def test_panic_after_a_shutdown_timeout_reports_the_real_situation_without_queuing_stops():
    """Subprocess: a thread still running at interpreter exit would abort the process."""
    import os
    import subprocess
    import sys
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path), "QT_QPA_PLATFORM": "offscreen"}
    run = subprocess.run([sys.executable, "-c", PANIC_AFTER_TIMEOUT_SCRIPT], env=env, capture_output=True,
                         text=True, timeout=60)
    lines = {line.split(" ", 1)[0]: line.split(" ", 1)[1] if " " in line else ""
             for line in run.stdout.splitlines()}
    assert run.returncode == 0, (run.returncode, run.stdout, run.stderr)
    assert lines["CLOSE_ACCEPTED"] == "False" and lines["PENDING"] == "['pump']"
    assert lines["PANIC_RAISED"] == "False"
    # No stop command was dispatched or queued by Panic, and none ran twice later.
    assert lines["PANIC_COMMANDS"] == "0"
    assert lines["STOP_CALLS"] == "{'pump': 1, 'ad2': 1}"
    # The blocked device is reported as what it is; the finished one is not blamed.
    assert lines["PANIC_STATE"] == "failed"
    assert "pump" in lines["PANIC_ERRORS"] and "cannot be interrupted" in lines["PANIC_ERRORS"]
    assert "Application shutdown has started" not in lines["PANIC_ERRORS"]
    assert "ad2" not in lines["PANIC_ERRORS"]
    assert lines["SECOND_CLOSE_ACCEPTED"] == "True"
