"""The camera timing check must judge the configuration that will run, not the previous one.

A fake camera reports a minimum trigger interval that depends on the exposure last applied to it
(or a long one before anything is applied). Simulated devices only.
"""

from __future__ import annotations

from time import monotonic, sleep

import pytest
from PySide6.QtWidgets import QApplication

from thermo_acoustic.application.commands import DeviceOperation, WorkflowOperation
from thermo_acoustic.domain.models import DeviceId
from test_simple_series import _connected_temperature_series_harness, _wait_until_terminal

FLUID_OR_OUTPUT_ACTIONS = {
    DeviceOperation.PUMP_FILL_LEVEL_SET, DeviceOperation.PUMP_REFILL, DeviceOperation.PUMP_EMPTY,
    DeviceOperation.VALVE_POSITION_SET, DeviceOperation.TEC_SETPOINTS_APPLY,
    DeviceOperation.AD2_SOFTWARE_TRIGGER, DeviceOperation.CAMERA_SEQUENCE_ARM,
    WorkflowOperation.FLUSH,
}


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication(["test-camera-timing"])


def install_timing_camera(controller, *, before_config_s, after_config_s):
    """`after_config_s(exposure_ms)` is the minimum interval once that exposure has been applied."""
    device = controller.registry.by_id(DeviceId.CAMERA).device
    applied: list[float] = []
    original_exposure = device.configure_exposure_time

    def configure_exposure_time(exposure_ms):
        applied.append(float(exposure_ms))
        return original_exposure(exposure_ms)

    def read_min_trigger_interval():
        device._require_initialized()
        return before_config_s if not applied else after_config_s(applied[-1])

    device.configure_exposure_time = configure_exposure_time
    device.read_min_trigger_interval = read_min_trigger_interval
    return applied


def run_series(app, controller, panel, tmp_path, events):
    panel.fps.setValue(10)  # 0.1 s frame interval
    controller.experiments.queue(panel._definition(), tmp_path)
    assert controller.experiments.start()
    status = _wait_until_terminal(app, controller, timeout=90)
    dispatched = [e for e in events if e.source == "experiment" and e.state == "running"
                  and e.operation in FLUID_OR_OUTPUT_ACTIONS]
    return status, dispatched


def test_a_long_interval_reported_for_the_old_configuration_does_not_reject_the_new_one(qt_app, tmp_path):
    controller, panel, results, events = _connected_temperature_series_harness(qt_app, repeats=1)
    try:
        panel.temperature_control.setChecked(False)
        applied = install_timing_camera(controller, before_config_s=0.5, after_config_s=lambda _e: 0.002)
        status, dispatched = run_series(qt_app, controller, panel, tmp_path, events)
        assert applied, "the new configuration was never applied before judging it"
        assert status["state"] == "completed", status
        assert dispatched, "an acceptable configuration must be allowed to run"
    finally:
        panel.close()
        controller.shutdown()


def test_a_configuration_that_is_really_too_fast_is_rejected_after_it_is_applied_but_before_any_action(
        qt_app, tmp_path):
    controller, panel, results, events = _connected_temperature_series_harness(qt_app, repeats=1)
    try:
        applied = install_timing_camera(controller, before_config_s=0.5, after_config_s=lambda _e: 0.5)
        status, dispatched = run_series(qt_app, controller, panel, tmp_path, events)
        assert status["state"] == "failed", status
        assert "Achieved frame interval" in status["phase"] and "live SDK minimum" in status["phase"]
        assert applied, "the check must have used the applied configuration"
        assert dispatched == []
    finally:
        panel.close()
        controller.shutdown()


def test_every_configuration_in_the_scan_is_checked_not_only_the_first(qt_app, tmp_path):
    controller, panel, results, events = _connected_temperature_series_harness(qt_app, repeats=1)
    try:
        for widget, value in zip(panel.exposure, (1, 2, 2)):  # exposures 1 ms and 2 ms
            widget.setValue(value)
        applied = install_timing_camera(
            controller, before_config_s=0.5, after_config_s=lambda exposure: 0.5 if exposure == 2.0 else 0.002)
        status, dispatched = run_series(qt_app, controller, panel, tmp_path, events)
        assert status["state"] == "failed", status
        assert 1.0 in applied and 2.0 in applied
        assert "live SDK minimum" in status["phase"]
        assert dispatched == []
    finally:
        panel.close()
        controller.shutdown()
