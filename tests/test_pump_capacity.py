"""Pump capacity checks: float representation noise must not reject a series that exactly fits, and a real
shortfall must still be rejected, for each unit separately and never for an unreadable level."""

from __future__ import annotations

import math
import tempfile
from dataclasses import replace
from pathlib import Path
from time import monotonic, sleep
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from test_simple_series import settings
from thermo_acoustic.application import ApplicationController
from thermo_acoustic.application.commands import DeviceCommand, DeviceOperation, PumpSetFillLevelArgs
from thermo_acoustic.application.experiment_runner import ExperimentManager
from thermo_acoustic.application.simple_series import NumericRange, compile_simple_series
from thermo_acoustic.domain.models import DeviceId, OperatingMode
from thermo_acoustic.hal.registry import DeviceRegistry


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication(["test-pump-capacity"])


def _wait(app, condition, timeout=60):
    deadline = monotonic() + timeout
    while monotonic() < deadline and not condition():
        app.processEvents()
        sleep(0.01)
    return condition()


def _run_two_series(app, volumes, level_before_start=None):
    """Two series whose flushes need `volumes` mL each, on a pump filled to 1 mL; returns the final status."""
    controller = ApplicationController(DeviceRegistry(mode=OperatingMode.SIMULATION), mode=OperatingMode.SIMULATION)
    controller.start()
    try:
        results = []
        controller.command_result.connect(results.append)
        for device in (DeviceId.AD2, DeviceId.CAMERA, DeviceId.PUMP, DeviceId.VALVE):
            controller.submit(DeviceCommand(device, DeviceOperation.CONNECT))
        assert _wait(app, lambda: sum(r.operation is DeviceOperation.CONNECT and r.ok for r in results) == 4, 20)
        controller.submit(DeviceCommand(DeviceId.PUMP, DeviceOperation.PUMP_FILL_LEVEL_SET, PumpSetFillLevelArgs(1.0)))
        assert _wait(app, lambda: any(r.operation is DeviceOperation.PUMP_FILL_LEVEL_SET and r.ok for r in results), 20)
        controller.experiments.confirm_unchecked = lambda summary: True
        controller.experiments.confirm_batch = lambda summary: True
        base = tempfile.mkdtemp()
        for index, volume in enumerate(volumes):
            series = replace(settings(), flush_unit_index=0, flush_volume_ml=volume, frame_count=2, repeats=1,
                             frequency_hz=NumericRange(1e6, 1e6, 1), amplitude_v=NumericRange(1, 1, 1),
                             exposure_ms=NumericRange(1, 1, 1), sweep_enabled=False, temperature_control=False,
                             temperature_logging=False, roi=(0, 0, 16, 16), description=f"series {index}")
            controller.experiments.queue(compile_simple_series(series), base)
        outcome = []
        controller.experiments.preflight_syringe(lambda ok, message: outcome.append((ok, message)))
        assert _wait(app, lambda: bool(outcome), 20)
        if level_before_start is not None:
            controller.submit(DeviceCommand(DeviceId.PUMP, DeviceOperation.PUMP_FILL_LEVEL_SET,
                                            PumpSetFillLevelArgs(level_before_start)))
            sleep(0.3)
            _wait(app, lambda: False, 0.5)
        assert controller.experiments.start()
        assert _wait(app, lambda: controller.experiments.status()["state"] in ("completed", "failed", "aborted"), 90)
        return controller.experiments.status(), outcome[0]
    finally:
        controller.shutdown()


def test_two_series_that_exactly_fit_the_syringe_both_run(qt_app):
    # 0.3 + 0.3 mL for the first series, 0.2 + 0.2 mL for the second, 1 mL in the syringe: the level after the
    # first series is 0.39999999999999997 in floating point and the second needs 0.4. That is not a shortage.
    status, preflight = _run_two_series(qt_app, [0.3, 0.2])
    assert preflight[0] is True
    assert status["state"] == "completed", status["phase"]


def test_a_real_shortfall_is_still_rejected_even_a_tiny_one(qt_app):
    for level, expected in ((0.55, "0.55"), (0.6 - 1e-6, "0.6")):
        status, _preflight = _run_two_series(qt_app, [0.3, 0.2], level_before_start=level)
        assert status["state"] == "failed" and "needs 0.6 mL total flush volume" in status["phase"], (level, status["phase"])
        assert expected in status["phase"]


# ---- the comparison itself (no devices): units are judged separately and unknown levels never pass
def test_helper_accepts_representation_noise_only():
    from thermo_acoustic.application.pump_volume import remaining_volume_ml, volume_available
    assert volume_available(1.0 - 0.3 - 0.3, 0.2 + 0.2)  # 0.39999999999999997 against 0.4
    assert volume_available(0.4, 0.4) and volume_available(1.0, 0.7)
    assert not volume_available(0.4 - 1e-9, 0.4)  # a picolitre short of a 0.4 mL need is a real, if tiny, shortfall
    assert not volume_available(0.35, 0.4) and not volume_available(0.0, 1e-6)
    for bad in (math.nan, math.inf, -math.inf, None):
        assert not volume_available(bad, 0.4)  # an unreadable level is never "enough"
        assert not volume_available(1.0, bad)
    assert remaining_volume_ml(1.0 - 0.3 - 0.3, 0.4) == 0.0  # noise reads as exactly nothing left, not negative
    assert remaining_volume_ml(1.0, 0.7) == pytest.approx(0.3)
    assert remaining_volume_ml(0.35, 0.4) == pytest.approx(-0.05)
    assert remaining_volume_ml(math.nan, 0.4) is None


def test_the_series_check_judges_each_pump_unit_on_its_own():
    check = ExperimentManager._check_flush_capacity
    check({0: 0.4, 1: 0.5}, _units_dict({0: 1.0 - 0.3 - 0.3, 1: 0.5}))
    with pytest.raises(RuntimeError, match=r"Pump unit 2 needs 0.5 mL"):
        check({0: 0.4, 1: 0.5}, _units_dict({0: 0.4, 1: 0.49}))  # unit 1 is fine, unit 2 is short
    with pytest.raises(RuntimeError, match="Pump unit 1 has no readable fill level"):
        check({0: 0.4}, _units_dict({0: None}))
    with pytest.raises(RuntimeError, match="not a number"):
        check({0: 0.4}, _units_dict({0: math.nan}))  # NaN < x is False: it used to pass as "enough"


def _units_dict(levels):
    return {index: SimpleNamespace(unit_index=index, fill_level_ml=level) for index, level in levels.items()}


def test_the_flush_step_itself_accepts_a_level_that_fits_by_noise_and_refuses_a_real_shortage():
    """The per-flush check in the flush workflow uses the same rule (it used to compute target < 0)."""
    from thermo_acoustic.application.pump_volume import volume_available
    level, volume = 1.0 - 0.3 - 0.3 - 0.2, 0.2  # 0.19999999999999996 left, 0.2 to flush
    assert level - volume < 0 and volume_available(level, volume)  # the old test said "cannot flush"
    assert max(0.0, level - volume) == 0.0  # the pump is sent a legal target of exactly 0
    assert not volume_available(0.2 - 1e-6, 0.2)


def test_the_pump_card_text_and_colour_follow_the_same_rule(qt_app):
    from thermo_acoustic.domain.models import ConnectionState, DeviceStatus, PumpReadback, PumpUnitReadback
    from thermo_acoustic.ui.device_panels import PumpPanel, queued_flush_text
    noise_level = 1.0 - 0.3 - 0.3
    text = queued_flush_text(0.4, noise_level, True)
    assert "0 mL left after it" in text and "short" not in text
    panel = PumpPanel()
    panel.set_status(DeviceStatus(DeviceId.PUMP, ConnectionState.CONNECTED, readback=PumpReadback(units=(
        PumpUnitReadback(0, fill_level_ml=noise_level, max_volume_ml=1.0),
        PumpUnitReadback(1, fill_level_ml=0.35, max_volume_ml=1.0)))))
    panel.set_queued_flush({0: 0.4, 1: 0.4})
    first, second = (panel.tiles_layout.itemAtPosition(0, i).widget().queue_label for i in (0, 1))
    assert first.styleSheet() == "" and "0 mL left after it" in first.text()  # text and colour agree: not short
    assert "color" in second.styleSheet() and "short by 0.05 mL" in second.text()  # a real shortfall: both agree
    assert "level not readable" in queued_flush_text(0.4, float("nan"), True)
