"""Operator Abort: which devices get a stop, that the batch is not "aborted" until the stops have returned, and that a
failed stop is reported instead of hidden behind the plain aborted wording. Simulated devices only."""

from __future__ import annotations

import dataclasses
import json
import threading
from time import monotonic, sleep

import pytest
from PySide6.QtWidgets import QApplication

from thermo_acoustic.application.commands import DeviceOperation
from thermo_acoustic.domain.models import ConnectionState, DeviceId
from test_simple_series import _connected_temperature_series_harness, _wait_until_terminal


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication(["test-abort-stop-results"])


def _run_and_abort(app, tmp_path, *, before_abort=None, patch=None):
    """Start a one-experiment series, Abort when the PC trigger has completed (an acquisition is running)."""
    controller, panel, results, events = _connected_temperature_series_harness(app, repeats=1, hold_s=0.2)
    if patch is not None:
        patch(controller)
    fired = []
    status_log = []

    def on_event(event):
        if (not fired and event.operation is DeviceOperation.AD2_SOFTWARE_TRIGGER and event.state == "completed"):
            fired.append(True)
            if before_abort is not None:
                before_abort(controller)
            controller.experiments.abort()
    controller.command_event.connect(on_event)
    controller.experiments.changed.connect(lambda status: status_log.append((status["state"], status["phase"],
                                                                             list(status.get("stop_failures", ())))))
    definition = panel._definition()
    folder = controller.experiments.queue(definition, tmp_path)
    assert controller.experiments.start()
    return controller, panel, events, status_log, folder


def _stops(events, device):
    """Distinct SAFE_STOP requests the batch itself sent to `device`."""
    return {e.request_id for e in events if e.operation is DeviceOperation.SAFE_STOP and e.device is device
            and e.source == "experiment"}


def _finish(app, controller, panel):
    status = _wait_until_terminal(app, controller)
    panel.close()
    return status


def test_abort_stops_a_connected_device_whose_last_operation_failed(qt_app, tmp_path):
    """ERROR here means connected with a failed operation, not disconnected: it must still get its stop."""
    def mark_ad2_error(controller):
        controller._statuses[DeviceId.AD2] = dataclasses.replace(
            controller._statuses[DeviceId.AD2], connection=ConnectionState.ERROR, fault="simulated failed operation")
    controller, panel, events, _log, _folder = _run_and_abort(qt_app, tmp_path, before_abort=mark_ad2_error)
    try:
        _wait_until_terminal(qt_app, controller)
        assert len(_stops(events, DeviceId.AD2)) == 1  # was 0: ERROR was skipped
    finally:
        panel.close()
        controller.shutdown()


def test_one_stop_per_device_per_abort(qt_app, tmp_path):
    controller, panel, events, _log, _folder = _run_and_abort(qt_app, tmp_path)
    try:
        _wait_until_terminal(qt_app, controller)
        for device in (DeviceId.AD2, DeviceId.CAMERA, DeviceId.PUMP, DeviceId.VALVE):
            assert len(_stops(events, device)) == 1, device  # AD2 and camera used to get two
    finally:
        panel.close()
        controller.shutdown()


def test_a_failed_stop_is_reported_and_not_hidden_behind_aborted(qt_app, tmp_path):
    def break_ad2_stop(controller):
        def broken():
            raise RuntimeError("simulated AD2 stop failure")
        controller.registry.by_id(DeviceId.AD2).safe_stop = broken
    controller, panel, events, log, folder = _run_and_abort(qt_app, tmp_path, patch=break_ad2_stop)
    try:
        status = _wait_until_terminal(qt_app, controller)
        assert status["state"] == "aborted"  # an operator abort stays an abort, not a device fault
        assert "simulated AD2 stop failure" in status["phase"]
        assert any("ad2" in item.lower() and "simulated AD2 stop failure" in item for item in status["stop_failures"])
        saved = json.loads((folder / "metadata" / "status.json").read_text())
        assert "simulated AD2 stop failure" in json.dumps(saved)  # recorded on disk, not only on screen
    finally:
        panel.close()
        controller.shutdown()


def test_the_batch_is_not_aborted_while_a_stop_is_still_outstanding(qt_app, tmp_path):
    release = threading.Event()
    reached = threading.Event()

    def slow_ad2_stop(controller):
        worker = controller.registry.by_id(DeviceId.AD2)
        original = worker.safe_stop

        def slow():
            reached.set()
            assert release.wait(20)
            return original()
        worker.safe_stop = slow
    controller, panel, events, log, _folder = _run_and_abort(qt_app, tmp_path, patch=slow_ad2_stop)
    try:
        deadline = monotonic() + 30
        while monotonic() < deadline and not reached.is_set():
            qt_app.processEvents()
            sleep(0.005)
        assert reached.is_set()
        for _ in range(60):  # the stop has not returned: the batch must still be winding down
            qt_app.processEvents()
            sleep(0.01)
        assert controller.experiments.status()["state"] == "stopping", controller.experiments.status()["state"]
        assert controller.experiments.batch_active  # the operation lock stays in force
        release.set()
        status = _wait_until_terminal(qt_app, controller)
        assert status["state"] == "aborted" and not status.get("stop_failures")
    finally:
        release.set()
        panel.close()
        controller.shutdown()


def test_a_stop_failure_shows_in_red_on_the_monitor_and_an_ordinary_abort_does_not(qt_app):
    from thermo_acoustic.ui.status_dashboard import StatusDashboard
    dashboard = StatusDashboard()
    base = {"state": "aborted", "planned_experiments": 1, "batch_completed_experiments": 0, "series": [],
            "last_saved": None, "current_parameters": None,
            "phase": "Experiment batch aborted: Operator aborted experiment batch"}
    dashboard.update_experiment(base)
    assert "a65a00" in dashboard.alert.styleSheet() and "Safe stop" not in dashboard.alert.text()
    dashboard.update_experiment({**base, "stop_failures": ["ad2: simulated"],
                                 "phase": base["phase"] + "; safe stop problems: ad2: simulated"})
    assert "b71c1c" in dashboard.alert.styleSheet() and "ad2: simulated" in dashboard.alert.text()


def test_panic_while_a_stop_is_outstanding_does_not_leave_the_batch_stuck(qt_app, tmp_path):
    release = threading.Event()
    reached = threading.Event()

    def slow_ad2_stop(controller):
        worker = controller.registry.by_id(DeviceId.AD2)
        original = worker.safe_stop

        def slow():
            reached.set()
            release.wait(20)
            return original()
        worker.safe_stop = slow
    controller, panel, events, log, _folder = _run_and_abort(qt_app, tmp_path, patch=slow_ad2_stop)
    try:
        deadline = monotonic() + 30
        while monotonic() < deadline and not reached.is_set():
            qt_app.processEvents()
            sleep(0.005)
        assert reached.is_set()
        controller.panic_stop()
        release.set()
        status = _wait_until_terminal(qt_app, controller)
        assert status["state"] == "aborted"
        assert controller.panic_status()["state"] in {"completed", "failed"}
    finally:
        release.set()
        panel.close()
        controller.shutdown()
