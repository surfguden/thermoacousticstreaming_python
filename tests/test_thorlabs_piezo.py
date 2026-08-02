from __future__ import annotations

import threading
import time

import pytest

from thermo_acoustic.thorlabs_piezo import CLOSED_LOOP_MODE_NAME, PiezoStage, PiezoStageError


class FakeSystemDecimal:
    """Mimics pythonnet's System.Decimal: supports str() (a clean numeric
    string) but deliberately does NOT support float() directly.

    Confirmed against real hardware (Session 48): float(a_real_System.
    Decimal) raised "TypeError: float() argument must be a string or a
    real number, not 'Decimal'" -- unlike Python's own stdlib
    decimal.Decimal, which does implement __float__ and would NOT have
    caught this bug. thorlabs_piezo.py originally called float(channel.
    GetMaxTravel()) directly; that passed every test here because
    FakeChannel returned plain floats, which happily survive float(). Using
    this wrapper instead means a regression back to bare float(channel.
    GetX()) fails a unit test immediately, not just real hardware."""

    def __init__(self, value):
        self._value = value

    def __str__(self):
        return str(self._value)

    def __repr__(self):
        return f"FakeSystemDecimal({self._value!r})"


class FakeChannel:
    def __init__(self, max_travel_um=450.0, max_v=150.0, min_v=-25.0, mode="OpenLoop"):
        self.calls = []
        self.max_travel_um = max_travel_um
        self.max_v = max_v
        self.min_v = min_v
        self.mode = mode
        self.position_um = 0.0

    def WaitForSettingsInitialized(self, timeout_ms):
        self.calls.append(("WaitForSettingsInitialized", timeout_ms))

    def StartPolling(self, interval_ms):
        self.calls.append(("StartPolling", interval_ms))

    def StopPolling(self):
        self.calls.append(("StopPolling",))

    def GetMaxTravel(self):
        return FakeSystemDecimal(self.max_travel_um)

    def GetMaxOutputVoltage(self):
        return FakeSystemDecimal(self.max_v)

    def GetMinOutputVoltage(self):
        return FakeSystemDecimal(self.min_v)

    def GetPositionControlMode(self):
        return self.mode

    def SetPositionControlMode(self, mode):
        self.calls.append(("SetPositionControlMode", mode))
        self.mode = mode

    def GetPosition(self):
        return FakeSystemDecimal(self.position_um)

    def SetPosition(self, value):
        self.calls.append(("SetPosition", value))
        self.position_um = float(value)


class FakeDevice:
    instances = []

    def __init__(self, serial_number, channel=None, fail_connect=False):
        self.serial_number = serial_number
        self.calls = []
        self._channel = channel or FakeChannel()
        self._fail_connect = fail_connect
        FakeDevice.instances.append(self)

    def Connect(self, serial_number):
        self.calls.append(("Connect", serial_number))
        if self._fail_connect:
            raise RuntimeError("Device is not connected")

    def GetChannel(self, index):
        self.calls.append(("GetChannel", index))
        return self._channel

    def ShutDown(self):
        self.calls.append(("ShutDown",))


class FakeBenchtopPrecisionPiezo:
    next_device = None

    @classmethod
    def CreateBenchtopPiezo(cls, serial_number):
        if cls.next_device is not None:
            return cls.next_device
        return FakeDevice(serial_number)


class FakeDeviceManagerCLI:
    build_device_list_calls = 0

    @classmethod
    def BuildDeviceList(cls):
        cls.build_device_list_calls += 1


def make_stage(channel=None, fail_connect=False) -> PiezoStage:
    FakeDevice.instances = []
    FakeDeviceManagerCLI.build_device_list_calls = 0
    device = FakeDevice("44533854", channel=channel, fail_connect=fail_connect)
    FakeBenchtopPrecisionPiezo.next_device = device
    stage = PiezoStage(
        serial_number="44533854",
        device_manager_cli=FakeDeviceManagerCLI,
        benchtop_precision_piezo_cls=FakeBenchtopPrecisionPiezo,
        closed_loop_mode="CloseLoop",
        decimal_type=float,
    )
    return stage


def test_connect_reads_real_limits_and_mode_without_hardcoding():
    channel = FakeChannel(max_travel_um=450.0, max_v=150.0, min_v=-25.0, mode="OpenLoop")
    stage = make_stage(channel=channel)

    stage.connect()

    assert stage.connected
    assert stage.max_travel_um == 450.0
    assert stage.max_output_voltage_v == 150.0
    assert stage.min_output_voltage_v == -25.0
    assert stage.position_control_mode == "OpenLoop"
    assert FakeDeviceManagerCLI.build_device_list_calls == 1
    assert ("StartPolling", stage.polling_interval_ms) in channel.calls


def test_connect_is_idempotent():
    stage = make_stage()
    stage.connect()
    stage.connect()
    connect_calls = [call for call in FakeDevice.instances[0].calls if call[0] == "Connect"]
    assert len(connect_calls) == 1


def test_connect_failure_raises_piezo_stage_error_and_leaves_disconnected():
    stage = make_stage(fail_connect=True)

    with pytest.raises(PiezoStageError):
        stage.connect()

    assert not stage.connected
    assert stage.channel is None


def test_disconnect_stops_polling_and_shuts_down():
    channel = FakeChannel()
    stage = make_stage(channel=channel)
    stage.connect()

    stage.disconnect()

    assert not stage.connected
    assert ("StopPolling",) in channel.calls
    assert ("ShutDown",) in FakeDevice.instances[0].calls


def test_disconnect_times_out_and_reports_instead_of_hanging_on_a_stuck_kinesis_call():
    # Task 2 (pending_feedback.md item 6): disconnect() previously used
    # plain try/except with no timeout guard -- a hung Kinesis .NET call
    # (StopPolling/ShutDown) would have blocked disconnect() forever.
    # Retrofitted to match QmixPumpBackend.close()'s timeout-guarded-thread
    # shape (the documented standard-cleanup template). Confirms the fix
    # empirically, not just by code inspection: StopPolling() genuinely
    # never returns on its own (same threading.Event().wait() pattern
    # test_application.py's own matching cleanup-timeout test uses), so the
    # only way this test can pass is if disconnect() itself times out
    # rather than waiting on the stuck call.
    class HangingChannel(FakeChannel):
        def StopPolling(self):
            threading.Event().wait()

    channel = HangingChannel()
    stage = make_stage(channel=channel)
    stage.connect()
    stage.disconnect_timeout_s = 0.1

    started_at = time.monotonic()
    with pytest.raises(PiezoStageError, match="timed out after 0.1s"):
        stage.disconnect()
    elapsed_s = time.monotonic() - started_at

    assert elapsed_s < 1.0, f"disconnect() must return once its timeout elapses, not block for the full hang ({elapsed_s:.2f}s)"
    # State is still cleaned up even though a step timed out -- matches
    # QmixPumpBackend.close()'s same "null out state regardless" behavior.
    assert not stage.connected
    assert stage.channel is None
    assert stage.device is None


def test_methods_require_connection_first():
    stage = make_stage()
    with pytest.raises(PiezoStageError):
        stage.get_position()
    with pytest.raises(PiezoStageError):
        stage.set_position(10.0)
    with pytest.raises(PiezoStageError):
        stage.needs_closed_loop_confirmation()
    with pytest.raises(PiezoStageError):
        stage.switch_to_closed_loop()


def test_closed_loop_confirmation_pattern_never_auto_switches():
    # Session 45 design decision: connect() must never switch modes on its
    # own, only report whether confirmation is needed.
    channel = FakeChannel(mode="OpenLoop")
    stage = make_stage(channel=channel)
    stage.connect()

    assert stage.position_control_mode == "OpenLoop"
    assert stage.needs_closed_loop_confirmation() is True
    assert not any(call[0] == "SetPositionControlMode" for call in channel.calls)

    stage.switch_to_closed_loop()

    assert stage.position_control_mode == CLOSED_LOOP_MODE_NAME
    assert ("SetPositionControlMode", "CloseLoop") in channel.calls
    assert stage.needs_closed_loop_confirmation() is False


def test_already_closed_loop_needs_no_confirmation():
    channel = FakeChannel(mode="CloseLoop")
    stage = make_stage(channel=channel)
    stage.connect()

    assert stage.needs_closed_loop_confirmation() is False


def test_get_and_set_position_require_closed_loop_mode():
    channel = FakeChannel(mode="OpenLoop")
    stage = make_stage(channel=channel)
    stage.connect()

    with pytest.raises(PiezoStageError, match="not ClosedLoop"):
        stage.get_position()
    with pytest.raises(PiezoStageError, match="not ClosedLoop"):
        stage.set_position(100.0)


def test_set_position_clamps_to_real_device_max_travel_not_hardcoded():
    channel = FakeChannel(max_travel_um=450.0, mode="CloseLoop")
    stage = make_stage(channel=channel)
    stage.connect()

    clamped = stage.set_position(10_000.0)  # far beyond max_travel_um

    assert clamped == 450.0
    assert ("SetPosition", 450.0) in channel.calls


def test_set_position_clamps_negative_target_to_zero():
    channel = FakeChannel(max_travel_um=450.0, mode="CloseLoop")
    stage = make_stage(channel=channel)
    stage.connect()

    clamped = stage.set_position(-50.0)

    assert clamped == 0.0
    assert ("SetPosition", 0.0) in channel.calls


def test_set_position_within_range_is_sent_unclamped():
    channel = FakeChannel(max_travel_um=450.0, mode="CloseLoop")
    stage = make_stage(channel=channel)
    stage.connect()

    clamped = stage.set_position(200.0)

    assert clamped == 200.0
    assert ("SetPosition", 200.0) in channel.calls


def test_get_position_reads_real_value_in_closed_loop():
    channel = FakeChannel(mode="CloseLoop")
    channel.position_um = 123.5
    stage = make_stage(channel=channel)
    stage.connect()

    assert stage.get_position() == 123.5
