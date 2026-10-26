"""Worker-level behaviour checked against simulated or fake devices (no hardware, no SDK)."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from thermo_acoustic.application.commands import (
    DeviceOperation, NoArguments, PumpMoveArgs, PumpSetFlowArgs, PumpUnitArgs,
)
from thermo_acoustic.domain.models import ConnectionState
from thermo_acoustic.drivers.pump import SimulatedPumpBank
from thermo_acoustic.hal.pump import PumpWorker
from thermo_acoustic.ui.device_panels import PumpPanel


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication(["test-device-workers"])


class Recorder:
    """Run worker operations synchronously on the test thread and keep the outcomes."""

    def __init__(self, worker) -> None:
        self.worker = worker
        self.succeeded: list[tuple[str, object]] = []
        self.failed: list[tuple[str, str]] = []
        worker.command_succeeded.connect(lambda rid, value: self.succeeded.append((rid, value)))
        worker.command_failed.connect(lambda rid, error: self.failed.append((rid, error)))
        self._counter = 0

    def run(self, operation, arguments=NoArguments()) -> bool:
        self._counter += 1
        before = len(self.succeeded)
        self.worker.execute(f"r{self._counter}", operation, arguments)
        return len(self.succeeded) > before


class RecordingBank(SimulatedPumpBank):
    def __init__(self) -> None:
        super().__init__(2)
        self.moves: list[tuple[str, int, float | None]] = []
        self.read_errors: list[Exception] = []
        self.reported_fault = False

    def refill(self, index, flow=None):
        self.moves.append(("refill", index, flow))
        super().refill(index, flow)

    def empty(self, index, flow=None):
        self.moves.append(("empty", index, flow))
        super().empty(index, flow)

    def read_fill_level(self, index):
        if self.read_errors:
            raise self.read_errors.pop(0)
        return super().read_fill_level(index)

    def read_fault(self, index):
        return self.reported_fault


def connected_pump():
    bank = RecordingBank()
    worker = PumpWorker(lambda: bank)
    recorder = Recorder(worker)
    assert recorder.run(DeviceOperation.CONNECT)
    return bank, worker, recorder


# ----------------------------------------------------------- explicit flow
def test_pump_move_passes_an_explicit_flow_to_the_device(qt_app):
    bank, _worker, recorder = connected_pump()
    assert recorder.run(DeviceOperation.PUMP_REFILL, PumpMoveArgs(flow_rate_ul_min=500.0, unit_index=1))
    assert recorder.run(DeviceOperation.PUMP_EMPTY, PumpMoveArgs(flow_rate_ul_min=250.0))
    assert bank.moves == [("refill", 1, 500.0), ("empty", 0, 250.0)]


def test_pump_move_without_a_flow_keeps_the_half_of_maximum_default(qt_app):
    bank, _worker, recorder = connected_pump()
    assert recorder.run(DeviceOperation.PUMP_REFILL, PumpMoveArgs())
    assert bank.moves == [("refill", 0, bank.capabilities(0)[1] / 2.0)]


@pytest.mark.parametrize("flow", [0.0, -100.0, 10_000.0 * 2])
def test_pump_move_rejects_an_invalid_explicit_flow_instead_of_substituting(qt_app, flow):
    bank, _worker, recorder = connected_pump()
    assert not recorder.run(DeviceOperation.PUMP_REFILL, PumpMoveArgs(flow_rate_ul_min=flow))
    assert bank.moves == []
    assert "flow_rate_ul_min" in recorder.failed[-1][1]


def test_pump_move_returns_after_the_start_command_and_does_not_wait_for_motion(qt_app):
    """timeout_s/poll_interval_s describe waiting, which this start-only operation never does."""
    bank, _worker, recorder = connected_pump()
    assert recorder.run(DeviceOperation.PUMP_REFILL, PumpMoveArgs(timeout_s=120.0, poll_interval_s=0.1))
    assert len(bank.moves) == 1


# ------------------------------------------------------------ stale faults
def test_pump_poll_clears_a_recovered_poll_error(qt_app):
    bank, worker, _recorder = connected_pump()
    bank.read_errors.append(RuntimeError("transient read failure"))
    worker.poll_once()
    assert worker.status().connection is ConnectionState.ERROR
    assert "transient read failure" in worker.status().fault
    worker.poll_once()
    assert worker.status().fault is None
    assert worker.status().connection is ConnectionState.CONNECTED


def test_pump_poll_does_not_clear_a_failed_command(qt_app):
    _bank, worker, recorder = connected_pump()
    assert not recorder.run(DeviceOperation.PUMP_FLOW_SET, PumpSetFlowArgs(1e9))
    failure = worker.status().fault
    assert failure
    worker.poll_once()
    assert worker.status().fault == failure


def test_pump_poll_does_not_clear_while_the_device_still_reports_a_fault(qt_app):
    bank, worker, _recorder = connected_pump()
    bank.read_errors.append(RuntimeError("transient read failure"))
    worker.poll_once()
    bank.reported_fault = True
    worker.poll_once()
    assert worker.status().fault is not None
    assert worker.status().readback.units[0].is_faulted is True
    bank.reported_fault = False
    worker.poll_once()
    assert worker.status().fault is None


# ------------------------------------------------------ connect and retry
class FlakyBank(SimulatedPumpBank):
    failures_left = 1
    created = 0

    def __init__(self) -> None:
        type(self).created += 1
        super().__init__(1)

    def initialize(self) -> None:
        if type(self).failures_left > 0:
            type(self).failures_left -= 1
            raise RuntimeError("could not open the bus")
        super().initialize()


def test_failed_connect_is_disconnected_and_can_be_retried(qt_app):
    FlakyBank.failures_left, FlakyBank.created = 1, 0
    worker = PumpWorker(FlakyBank)
    recorder = Recorder(worker)
    panel = PumpPanel()
    assert not recorder.run(DeviceOperation.CONNECT)
    status = worker.status()
    assert status.connection is ConnectionState.DISCONNECTED
    assert "could not open the bus" in status.fault
    panel.set_status(status)
    assert panel._buttons["connect"].isEnabled()
    assert recorder.run(DeviceOperation.CONNECT)  # nothing was left open; a fresh device is made
    assert FlakyBank.created == 2
    assert worker.status().connection is ConnectionState.CONNECTED
    assert worker.status().fault is None


def test_connected_device_with_an_error_is_not_offered_a_second_connect(qt_app):
    _bank, worker, recorder = connected_pump()
    assert not recorder.run(DeviceOperation.PUMP_FLOW_SET, PumpSetFlowArgs(1e9))
    status = worker.status()
    assert status.connection is ConnectionState.ERROR
    panel = PumpPanel()
    panel.set_status(status)
    assert not panel._buttons["connect"].isEnabled()
    assert panel._buttons["disconnect"].isEnabled()


# ------------------------------------------------------------- AD2 safe stop
class FakeAd2:
    """Minimal AD2 stand-in. `fail` maps an action name to the exception it raises."""

    def __init__(self, fail=None) -> None:
        self.fail = dict(fail or {})
        self.calls: list[str] = []

    def initialize(self) -> None: ...
    def cleanup(self) -> None: ...

    def _act(self, name: str) -> None:
        self.calls.append(name)
        if name in self.fail:
            raise self.fail[name]

    def wfg_start_stop_all_ch(self, running: bool) -> None: self._act(f"wfg_all_{running}")
    def stop_analog_outputs(self) -> None: self._act("wfg_direct_stop")
    def start_stop_do(self, running: bool) -> None: self._act(f"do_{running}")
    def scope_abort(self) -> None: self._act("scope_abort")


def ad2_worker(fake):
    from dataclasses import replace
    from thermo_acoustic.hal.ad2 import AD2Worker
    worker = AD2Worker(lambda: fake)
    recorder = Recorder(worker)
    assert recorder.run(DeviceOperation.CONNECT)
    worker.state.readback = replace(worker.state.readback, waveform_running=True,
                                    digital_output_running=True, scope_state="armed")
    worker.state.active = True
    return worker, recorder


def test_ad2_safe_stop_stops_everything_when_nothing_fails(qt_app):
    fake = FakeAd2()
    worker, recorder = ad2_worker(fake)
    assert recorder.run(DeviceOperation.SAFE_STOP)
    assert fake.calls == ["wfg_all_False", "do_False", "scope_abort"]
    readback = worker.status().readback
    assert (readback.waveform_running, readback.digital_output_running, readback.scope_state) == (False, False, "idle")
    assert worker.status().active is False


def test_ad2_safe_stop_keeps_going_after_a_failed_output_and_reports_every_failure(qt_app):
    fake = FakeAd2(fail={"wfg_all_False": RuntimeError("reconfigure refused"),
                         "wfg_direct_stop": RuntimeError("channel stop refused"),
                         "do_False": RuntimeError("digital refused")})
    worker, recorder = ad2_worker(fake)
    assert not recorder.run(DeviceOperation.SAFE_STOP)
    # every independent output and the scope were attempted despite the earlier failures
    assert fake.calls == ["wfg_all_False", "wfg_direct_stop", "do_False", "scope_abort"]
    message = recorder.failed[-1][1]
    for expected in ("reconfigure refused", "channel stop refused", "digital refused"):
        assert expected in message
    readback = worker.status().readback
    assert readback.waveform_running is True      # not claimed stopped
    assert readback.digital_output_running is True
    assert readback.scope_state == "idle"           # the scope abort did succeed
    assert worker.status().active is True


def test_ad2_safe_stop_falls_back_to_direct_channel_stops(qt_app):
    fake = FakeAd2(fail={"wfg_all_False": RuntimeError("reconfigure refused")})
    worker, recorder = ad2_worker(fake)
    assert recorder.run(DeviceOperation.SAFE_STOP)
    assert fake.calls == ["wfg_all_False", "wfg_direct_stop", "do_False", "scope_abort"]
    assert worker.status().readback.waveform_running is False


# ------------------------------------------------------------- Z stage position
def connected_z_stage():
    from thermo_acoustic.drivers.z_stage import SimulatedZStage
    from thermo_acoustic.hal.z_stage import ZStageWorker
    device = SimulatedZStage()
    worker = ZStageWorker(lambda: device)
    recorder = Recorder(worker)
    assert recorder.run(DeviceOperation.CONNECT)
    assert recorder.run(DeviceOperation.Z_STAGE_CLOSED_LOOP_REQUIREMENT_READ)
    assert recorder.run(DeviceOperation.Z_STAGE_CLOSED_LOOP_ENABLE)
    return device, worker, recorder


def test_a_position_command_is_recorded_as_commanded_not_as_a_measured_position(qt_app):
    from thermo_acoustic.application.commands import ZStageSetPositionArgs
    device, worker, recorder = connected_z_stage()
    device.get_position = lambda: device.position_um - 5.0  # the stage is still 5 µm short
    assert recorder.run(DeviceOperation.Z_STAGE_POSITION_SET, ZStageSetPositionArgs(20.0))
    # The command result keeps its meaning (the clamped target the controller accepted)...
    assert recorder.succeeded[-1][1].position_um == 20.0
    readback = worker.status().readback
    # ...but it is not presented as where the stage is.
    assert readback.commanded_position_um == 20.0
    assert readback.position_um is None
    assert recorder.run(DeviceOperation.Z_STAGE_POSITION_READ)
    assert recorder.succeeded[-1][1].position_um == 15.0
    readback = worker.status().readback
    assert readback.position_um == 15.0 and readback.commanded_position_um == 20.0
