from __future__ import annotations

import threading
import time

import pytest

from thermo_acoustic.application import Application
from thermo_acoustic.hardware_factory import HardwareRuntimeConfig, build_hardware_bundle
from thermo_acoustic.tec import (
    TEC_TARGET_MAX_C,
    TEC_TARGET_MIN_C,
    MeerstetterTecBackend,
    SimulatedTecBackend,
    TecAbortedError,
    TecController,
    TecError,
    TecStatus,
    _MECOM_PARAM_DEVICE_STATUS,
    _MECOM_PARAM_ERROR_NUMBER,
    _MECOM_PARAM_OBJECT_TEMP,
    _MECOM_PARAM_OUTPUT_ENABLE,
    _MECOM_PARAM_TARGET_TEMP,
    _MECOM_WRITABLE_PARAMETER_NAMES,
    _PyMeComTecClient,
    _real_tec_client_factory,
)
from thermo_acoustic.workflows import Experiment2, ExperimentSeries2, TemperatureSeries


class RecordingTecBackend:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.status = TecStatus(
            current_temperature_c=25.0,
            target_temperature_c=25.0,
            output_stage_static_on=False,
            ready=True,
        )

    def connect(self) -> None:
        self.calls.append(("connect",))

    def close(self) -> None:
        self.calls.append(("close",))

    def read_status(self, channels: tuple[int, ...]) -> dict[int, TecStatus]:
        self.calls.append(("read_status", channels))
        return {
            channel: TecStatus(
                channel=channel,
                current_temperature_c=self.status.current_temperature_c,
                target_temperature_c=self.status.target_temperature_c,
                output_stage_static_on=self.status.output_stage_static_on,
                ready=self.status.ready,
                error_state=self.status.error_state,
            )
            for channel in channels
        }

    def set_output_stage_static_on(self, channel: int) -> None:
        self.calls.append(("set_output_stage_static_on", channel))
        self.status = TecStatus(
            current_temperature_c=self.status.current_temperature_c,
            target_temperature_c=self.status.target_temperature_c,
            output_stage_static_on=True,
            ready=True,
        )

    def set_target_temperature(self, channel: int, temperature_c: float) -> None:
        self.calls.append(("set_target_temperature", channel, temperature_c))
        self.status = TecStatus(
            current_temperature_c=temperature_c,
            target_temperature_c=temperature_c,
            output_stage_static_on=self.status.output_stage_static_on,
            ready=True,
        )

    def write_config(self) -> None:
        self.calls.append(("write_config",))


class FailingStatusTecBackend(RecordingTecBackend):
    def read_status(self, channels: tuple[int, ...]) -> dict[int, TecStatus]:
        self.calls.append(("read_status", channels))
        raise TecError("status read failed")


class ChannelAwareRecordingTecBackend:
    """Fake backend with real per-channel state, used to verify a
    TecController addresses channels 1 and 2 independently."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.target_temperature_c: dict[int, float] = {1: 25.0, 2: 25.0}
        self.output_stage_static_on: dict[int, bool] = {1: False, 2: False}

    def connect(self) -> None:
        self.calls.append(("connect",))

    def close(self) -> None:
        self.calls.append(("close",))

    def read_status(self, channels: tuple[int, ...]) -> dict[int, TecStatus]:
        self.calls.append(("read_status", channels))
        return {
            channel: TecStatus(
                channel=channel,
                current_temperature_c=self.target_temperature_c[channel],
                target_temperature_c=self.target_temperature_c[channel],
                output_stage_static_on=self.output_stage_static_on[channel],
                ready=True,
            )
            for channel in channels
        }

    def set_output_stage_static_on(self, channel: int) -> None:
        self.calls.append(("set_output_stage_static_on", channel))
        self.output_stage_static_on[channel] = True

    def set_target_temperature(self, channel: int, temperature_c: float) -> None:
        self.calls.append(("set_target_temperature", channel, temperature_c))
        self.target_temperature_c[channel] = temperature_c

    def write_config(self) -> None:
        self.calls.append(("write_config",))


class FakeMeComSerial:
    """Stands in for pyMeCom's MeComSerial in tests -- no real serial I/O.

    Records every get_parameter/set_parameter call. Scope rule (updated
    2026-08-04, after real-hardware verification): WRITES are strictly
    restricted to WRITABLE_PARAMETER_NAMES (2010/3000) -- anything else
    raises. READS are NOT restricted to a fixed list -- a read can't
    change device state, so this fake also answers arbitrary diagnostic
    parameter names (e.g. "Device Type", "General Operating Mode") the
    same way a real device would, rather than raising. get_parameter_raw()/
    set_parameter_raw() remain forbidden in both directions -- pyMeCom's
    own bypass of its built-in name-based allow-list is never needed,
    since every parameter this integration touches (whitelisted or
    diagnostic) has a known name.
    """

    WRITABLE_PARAMETER_NAMES = {
        "Output Enable Status",
        "Target Object Temperature",
    }

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.device_status: dict[int, int] = {1: 1, 2: 1}  # 1 = Ready
        self.error_number: dict[int, int] = {1: 0, 2: 0}
        self.object_temperature_c: dict[int, float] = {1: 25.0, 2: 25.0}
        self.output_enabled: dict[int, int] = {1: 0, 2: 0}
        # Arbitrary extra read-only parameters a diagnostic script might
        # ask for, keyed by (parameter_name, parameter_instance).
        self.extra_readable_parameters: dict[tuple[str, int], object] = {}

    def get_parameter(self, parameter_name=None, parameter_instance=1, **_kwargs):
        self.calls.append(("get_parameter", parameter_name, parameter_instance))
        if parameter_name == "Device Status":
            return self.device_status[parameter_instance]
        if parameter_name == "Error Number":
            return self.error_number[parameter_instance]
        if parameter_name == "Object Temperature":
            return self.object_temperature_c[parameter_instance]
        if parameter_name == "Output Enable Status":
            return self.output_enabled[parameter_instance]
        key = (parameter_name, parameter_instance)
        if key in self.extra_readable_parameters:
            return self.extra_readable_parameters[key]
        raise AssertionError(f"fake has no configured value for read of {parameter_name!r}")

    def set_parameter(self, value=None, parameter_name=None, parameter_instance=1, **_kwargs):
        self.calls.append(("set_parameter", parameter_name, parameter_instance, value))
        if parameter_name not in self.WRITABLE_PARAMETER_NAMES:
            raise AssertionError(f"unexpected parameter write: {parameter_name!r}")
        if parameter_name == "Output Enable Status":
            self.output_enabled[parameter_instance] = value
        elif parameter_name == "Target Object Temperature":
            self.object_temperature_c[parameter_instance] = value

    def get_parameter_raw(self, *args, **kwargs):
        raise AssertionError("_PyMeComTecClient must never call get_parameter_raw()")

    def set_parameter_raw(self, *args, **kwargs):
        raise AssertionError("_PyMeComTecClient must never call set_parameter_raw()")


def test_tec_parameter_name_constants_match_the_real_installed_pymecom_table():
    # Regression test for the real-hardware-verification finding
    # (2026-08-04): _MECOM_PARAM_TARGET_TEMP was "Target Object Temp",
    # but the real installed pyMeCom package's own parameter table names
    # ID 3000 "Target Object Temperature" -- every real write raised
    # UnknownParameter until this was caught against physical hardware.
    # Compares directly against mecom.commands.TEC_PARAMETERS (the
    # actually-installed package), not a second hand-typed string, so a
    # future mismatch can't hide behind two wrong strings agreeing with
    # each other. Skipped (not failed) when `mecom` isn't installed --
    # matching this project's real-vendor-SDK convention of never
    # requiring a real-hardware package for the rest of the suite to run.
    pytest.importorskip("mecom")
    from mecom.commands import TEC_PARAMETERS

    real_names_by_id = {param["id"]: param["name"] for param in TEC_PARAMETERS}
    expected = {
        2010: _MECOM_PARAM_OUTPUT_ENABLE,
        3000: _MECOM_PARAM_TARGET_TEMP,
        1000: _MECOM_PARAM_OBJECT_TEMP,
        104: _MECOM_PARAM_DEVICE_STATUS,
        105: _MECOM_PARAM_ERROR_NUMBER,
    }
    for parameter_id, constant_name in expected.items():
        assert real_names_by_id[parameter_id] == constant_name, (
            f"tec.py's constant for parameter {parameter_id} ({constant_name!r}) no longer matches "
            f"the real installed pyMeCom name ({real_names_by_id[parameter_id]!r})"
        )


def test_writable_parameter_names_are_exactly_output_enable_and_target_temp():
    assert _MECOM_WRITABLE_PARAMETER_NAMES == {_MECOM_PARAM_OUTPUT_ENABLE, _MECOM_PARAM_TARGET_TEMP}


def test_temperature_series_parses_comma_and_semicolon_text():
    series = TemperatureSeries.from_text("20.0, 21.5; 23")

    assert series.temperature_points_c == [20.0, 21.5, 23.0]
    assert series.enabled is True


def test_temperature_series_rejects_targets_outside_local_safety_range():
    with pytest.raises(ValueError, match="local safety range"):
        TemperatureSeries.from_text(str(TEC_TARGET_MIN_C - 0.1))

    with pytest.raises(ValueError, match="local safety range"):
        TemperatureSeries(temperature_points_c=[TEC_TARGET_MAX_C + 0.1])


def test_temperature_series_locked_by_default_ch2_is_none():
    series = TemperatureSeries.from_text("20.0, 25.0")

    assert series.unlocked is False
    assert series.temperature_points_ch2_c is None
    assert series.target_at(0) == pytest.approx(20.0)
    assert series.target_at(1) == pytest.approx(25.0)


def test_temperature_series_from_text_with_text_ch2_is_unlocked():
    series = TemperatureSeries.from_text("20.0, 25.0", text_ch2="18.0, 22.0")

    assert series.unlocked is True
    assert series.temperature_points_ch2_c == [18.0, 22.0]
    assert series.target_at(0) == {1: 20.0, 2: 18.0}
    assert series.target_at(1) == {1: 25.0, 2: 22.0}


def test_temperature_series_from_text_with_blank_text_ch2_stays_locked():
    series = TemperatureSeries.from_text("20.0", text_ch2="   ")

    assert series.unlocked is False
    assert series.temperature_points_ch2_c is None


def test_temperature_series_rejects_mismatched_ch2_length():
    with pytest.raises(ValueError, match="same length"):
        TemperatureSeries(temperature_points_c=[20.0, 25.0], temperature_points_ch2_c=[18.0])


def test_temperature_series_validates_ch2_targets_against_safety_range():
    with pytest.raises(ValueError, match="local safety range"):
        TemperatureSeries(temperature_points_c=[20.0], temperature_points_ch2_c=[TEC_TARGET_MAX_C + 0.1])


def test_temperature_series_post_stable_hold_s_defaults_to_zero():
    series = TemperatureSeries(temperature_points_c=[20.0])

    assert series.post_stable_hold_s == 0.0


def test_temperature_series_rejects_negative_post_stable_hold_s():
    with pytest.raises(ValueError, match="post_stable_hold_s"):
        TemperatureSeries(temperature_points_c=[20.0], post_stable_hold_s=-1.0)


def test_temperature_series_from_text_accepts_post_stable_hold_s():
    series = TemperatureSeries.from_text("20.0", post_stable_hold_s=3.5)

    assert series.post_stable_hold_s == pytest.approx(3.5)


def test_tec_controller_defaults_to_disabled_simulation_without_hardware():
    controller = TecController()

    assert controller.enabled is False
    assert controller.simulate is True
    assert isinstance(controller._backend(), SimulatedTecBackend)


def test_tec_controller_applies_static_setpoint_and_writes_config():
    backend = RecordingTecBackend()
    controller = TecController(enabled=True, simulate=True, backend=backend, channels=(1,))

    controller.initialize()
    result = controller.apply_static_setpoint(18.5)

    status = result[1]
    assert status.target_temperature_c == pytest.approx(18.5)
    assert status.current_temperature_c == pytest.approx(18.5)
    assert backend.calls == [
        ("connect",),
        ("read_status", (1,)),
        ("set_output_stage_static_on", 1),
        ("set_target_temperature", 1, 18.5),
        ("write_config",),
        ("read_status", (1,)),
    ]


def test_tec_controller_initialize_closes_backend_when_status_read_fails():
    backend = FailingStatusTecBackend()
    controller = TecController(enabled=True, simulate=True, backend=backend)

    with pytest.raises(TecError, match="status read failed"):
        controller.initialize()

    assert controller.initialized is False
    assert backend.calls == [("connect",), ("read_status", (1, 2)), ("close",)]


def test_tec_controller_failed_initialize_bounds_a_stuck_backend_close():
    close_started = threading.Event()

    class HangingCloseBackend(FailingStatusTecBackend):
        def close(self) -> None:
            self.calls.append(("close",))
            close_started.set()
            threading.Event().wait()

    backend = HangingCloseBackend()
    controller = TecController(
        enabled=True,
        simulate=True,
        backend=backend,
        cleanup_timeout_s=0.02,
    )
    started = time.perf_counter()

    with pytest.raises(TecError) as exc_info:
        controller.initialize()

    assert time.perf_counter() - started < 0.5
    assert close_started.is_set()
    assert "status read failed" in str(exc_info.value)
    assert "TEC failed-initialize cleanup timed out" in str(exc_info.value)
    assert controller.initialized is False


def test_tec_controller_cleanup_bounds_a_stuck_backend_close():
    close_started = threading.Event()

    class HangingCloseBackend(RecordingTecBackend):
        def close(self) -> None:
            self.calls.append(("close",))
            close_started.set()
            threading.Event().wait()

    backend = HangingCloseBackend()
    controller = TecController(
        enabled=True,
        simulate=True,
        backend=backend,
        initialized=True,
        cleanup_timeout_s=0.02,
    )
    started = time.perf_counter()

    with pytest.raises(TecError, match="TEC cleanup timed out"):
        controller.cleanup()

    assert time.perf_counter() - started < 0.5
    assert close_started.is_set()
    assert controller.initialized is True


def test_tec_controller_waits_for_stable_status_without_hardware_sleep():
    backend = SimulatedTecBackend()
    controller = TecController(enabled=True, simulate=True, backend=backend)
    controller.initialize()
    controller.apply_static_setpoint(20.0)

    result = controller.wait_until_stable(
        20.0,
        tolerance_c=0.1,
        min_settle_s=0.0,
        max_wait_s=0.1,
        poll_interval_s=0.001,
    )

    assert set(result.keys()) == {1, 2}
    for channel_status in result.values():
        assert channel_status.ready is True
        assert channel_status.current_temperature_c == pytest.approx(20.0)


def test_tec_controller_wait_until_stable_supports_abort(monkeypatch):
    backend = RecordingTecBackend()
    backend.status = TecStatus(
        current_temperature_c=10.0,
        target_temperature_c=20.0,
        output_stage_static_on=True,
        ready=False,
    )
    controller = TecController(enabled=True, simulate=True, backend=backend)
    controller.initialize()
    monkeypatch.setattr("thermo_acoustic.tec.time.sleep", lambda _seconds: None)

    calls = 0

    def should_abort() -> bool:
        nonlocal calls
        calls += 1
        return calls >= 2

    with pytest.raises(TecAbortedError, match="aborted"):
        controller.wait_until_stable(
            20.0,
            tolerance_c=0.1,
            min_settle_s=0.0,
            max_wait_s=10.0,
            poll_interval_s=1.0,
            should_abort=should_abort,
        )


def test_tec_controller_wait_until_stable_times_out_explicitly(monkeypatch):
    backend = RecordingTecBackend()
    backend.status = TecStatus(
        current_temperature_c=10.0,
        target_temperature_c=20.0,
        output_stage_static_on=True,
        ready=False,
    )
    controller = TecController(enabled=True, simulate=True, backend=backend)
    controller.initialize()
    monkeypatch.setattr("thermo_acoustic.tec.time.sleep", lambda _seconds: None)

    with pytest.raises(TimeoutError, match="did not stabilize"):
        controller.wait_until_stable(
            20.0,
            tolerance_c=0.1,
            min_settle_s=0.0,
            max_wait_s=0.0,
            poll_interval_s=0.001,
        )


def test_tec_controller_addresses_both_channels_independently():
    backend = ChannelAwareRecordingTecBackend()
    controller = TecController(enabled=True, simulate=True, backend=backend, channels=(1, 2))
    controller.initialize()

    controller.apply_static_setpoint(18.0, channels=(1,))
    controller.apply_static_setpoint(24.0, channels=(2,))

    assert backend.target_temperature_c == {1: 18.0, 2: 24.0}
    set_temperature_calls = [call for call in backend.calls if call[0] == "set_target_temperature"]
    assert set_temperature_calls == [
        ("set_target_temperature", 1, 18.0),
        ("set_target_temperature", 2, 24.0),
    ]


def test_tec_controller_apply_static_setpoint_defaults_to_all_configured_channels():
    backend = ChannelAwareRecordingTecBackend()
    controller = TecController(enabled=True, simulate=True, backend=backend, channels=(1, 2))
    controller.initialize()

    result = controller.apply_static_setpoint(20.0)

    assert set(result.keys()) == {1, 2}
    assert backend.target_temperature_c == {1: 20.0, 2: 20.0}


def test_tec_controller_apply_static_setpoint_accepts_per_channel_dict_targets():
    # Added for unlocked dual-channel temperature scans (2026-08-04): both
    # channels move to their OWN target in a single call, not one after
    # the other.
    backend = ChannelAwareRecordingTecBackend()
    controller = TecController(enabled=True, simulate=True, backend=backend, channels=(1, 2))
    controller.initialize()

    result = controller.apply_static_setpoint({1: 18.0, 2: 24.0})

    assert backend.target_temperature_c == {1: 18.0, 2: 24.0}
    assert result[1].target_temperature_c == pytest.approx(18.0)
    assert result[2].target_temperature_c == pytest.approx(24.0)
    set_temp_calls = [call for call in backend.calls if call[0] == "set_target_temperature"]
    assert set_temp_calls == [
        ("set_target_temperature", 1, 18.0),
        ("set_target_temperature", 2, 24.0),
    ]


def test_tec_controller_apply_static_setpoint_rejects_dict_with_mismatched_channels():
    backend = ChannelAwareRecordingTecBackend()
    controller = TecController(enabled=True, simulate=True, backend=backend, channels=(1, 2))
    controller.initialize()

    with pytest.raises(ValueError, match="must exactly match"):
        controller.apply_static_setpoint({1: 18.0})


def test_tec_controller_wait_until_stable_accepts_per_channel_dict_targets():
    backend = ChannelAwareRecordingTecBackend()
    controller = TecController(enabled=True, simulate=True, backend=backend, channels=(1, 2))
    controller.initialize()
    controller.apply_static_setpoint({1: 18.0, 2: 24.0})

    result = controller.wait_until_stable(
        {1: 18.0, 2: 24.0},
        tolerance_c=0.1,
        min_settle_s=0.0,
        max_wait_s=0.1,
        poll_interval_s=0.001,
    )

    assert result[1].current_temperature_c == pytest.approx(18.0)
    assert result[2].current_temperature_c == pytest.approx(24.0)


def test_tec_controller_wait_until_stable_dict_targets_checked_per_channel_not_shared():
    # Regression test for the actual bug the dict extension fixes: a
    # single shared target would incorrectly compare channel 2's
    # temperature against channel 1's target (or vice versa). Channel 1
    # sits exactly on its own target (18.0) but far from channel 2's
    # target (24.0); channel 2 sits exactly on its own target (24.0) but
    # far from channel 1's. A shared-target implementation would never
    # see both as simultaneously "within tolerance" -- this must succeed
    # immediately since each channel is compared only against its own
    # target.
    backend = ChannelAwareRecordingTecBackend()
    backend.target_temperature_c = {1: 18.0, 2: 24.0}
    backend.output_stage_static_on = {1: True, 2: True}
    controller = TecController(enabled=True, simulate=True, backend=backend, channels=(1, 2))
    controller.initialize()

    result = controller.wait_until_stable(
        {1: 18.0, 2: 24.0},
        tolerance_c=0.05,
        min_settle_s=0.0,
        max_wait_s=0.1,
        poll_interval_s=0.001,
    )

    assert result[1].ready is True
    assert result[2].ready is True


def test_real_meerstetter_backend_without_reviewed_client_refuses_to_connect():
    backend = MeerstetterTecBackend(port="COM9")

    with pytest.raises(TecError, match="No Meerstetter TEC client is configured") as error:
        backend.connect()

    assert "no device connection was attempted" in str(error.value)


def test_factory_wires_real_tec_client_factory_without_connecting():
    bundle = build_hardware_bundle(
        HardwareRuntimeConfig(
            ad2_enabled=False,
            sim_ad2=True,
            camera_enabled=False,
            sim_camera=True,
            pump_enabled=False,
            sim_pump=True,
            valve_enabled=False,
            sim_valve=True,
            z_enabled=False,
            thorlabs_apt_serial="44533854",
            valve_resource="COM9",
            cetoni_config_path="unused",
            tec_enabled=True,
            sim_tec=False,
            tec_port="COM9",
        )
    )

    assert isinstance(bundle.tec.backend, MeerstetterTecBackend)
    assert bundle.tec.backend.client_factory is _real_tec_client_factory
    # Building the bundle performs no I/O: the real client is constructed
    # lazily inside connect() (itself only called from
    # TecController.initialize()), which this test deliberately never
    # calls -- no real serial connection is attempted in this pass.
    assert bundle.tec.backend.client is None


def test_real_tec_client_factory_returns_unconnected_client_for_configured_port():
    client = _real_tec_client_factory("COM9")

    assert isinstance(client, _PyMeComTecClient)
    assert client._port == "COM9"
    assert client._mc is None


def test_real_tec_client_only_touches_its_own_four_parameters_during_normal_operation():
    fake = FakeMeComSerial()
    client = _PyMeComTecClient(port="COM9")
    client._mc = fake

    client.set_output_stage_static_on(1)
    client.set_target_temperature(1, 21.75)
    result = client.read_status((1,))
    status = result[1]

    assert status.channel == 1
    assert status.output_stage_static_on is True
    # This fake models "Target Object Temperature" writes as taking effect
    # on "Object Temperature" immediately, purely to keep the fake simple
    # -- it's not a claim about real device thermal settling time.
    assert status.current_temperature_c == pytest.approx(21.75)
    touched_names = {call[1] for call in fake.calls}
    # Not a "must never touch anything else" allow-list check anymore
    # (reads are unrestricted project-wide) -- this documents what
    # _PyMeComTecClient's own methods actually do during their normal
    # enable/set-target/read-status operation.
    assert touched_names == {"Output Enable Status", "Target Object Temperature", "Object Temperature", "Device Status"}


def test_real_tec_client_reads_device_status_once_for_multiple_channels():
    # Regression test for the real-hardware finding (2026-08-04): Device
    # Status/Error Number are device-wide "Common Product Parameters" on
    # this hardware -- querying them at parameter_instance=2 raised
    # "Instance is not available" on the real device, even though Object
    # Temperature/Output Enable Status/Target Object Temperature all held
    # real, independent state at instance 2 (confirmed with a controlled
    # write test: enabling + retargeting channel 2 alone produced a
    # genuine, independent closed-loop thermal response). read_status()
    # must read Device Status ONCE (at instance 1), not once per channel,
    # or it would break exactly the way the original bug did.
    fake = FakeMeComSerial()
    client = _PyMeComTecClient(port="COM9")
    client._mc = fake

    result = client.read_status((1, 2))

    assert set(result.keys()) == {1, 2}
    device_status_reads = [call for call in fake.calls if call[1] == "Device Status"]
    assert device_status_reads == [("get_parameter", "Device Status", 1)]


def test_real_tec_client_write_is_restricted_to_the_two_writable_parameters():
    fake = FakeMeComSerial()

    fake.set_parameter(value=1, parameter_name="Output Enable Status", parameter_instance=1)
    fake.set_parameter(value=21.75, parameter_name="Target Object Temperature", parameter_instance=1)

    with pytest.raises(AssertionError, match="unexpected parameter write"):
        fake.set_parameter(value=0, parameter_name="PID Kp", parameter_instance=1)


def test_fake_mecom_serial_reads_are_not_restricted_to_the_writable_parameters():
    fake = FakeMeComSerial()
    fake.extra_readable_parameters[("Device Type", 1)] = 1121
    fake.extra_readable_parameters[("General Operating Mode", 1)] = 0

    # A read of a parameter outside the 2 writable names (or the client's
    # own 4 read parameters) must not raise -- reads are unrestricted
    # project-wide (2026-08-04 scope update); only writes are restricted.
    assert fake.get_parameter(parameter_name="Device Type", parameter_instance=1) == 1121
    assert fake.get_parameter(parameter_name="General Operating Mode", parameter_instance=1) == 0


def test_real_tec_client_surfaces_error_number_only_when_device_status_is_error():
    fake = FakeMeComSerial()
    fake.device_status[1] = 3
    fake.error_number[1] = 42
    client = _PyMeComTecClient(port="COM9")
    client._mc = fake

    status = client.read_status((1,))[1]

    assert status.error_state is not None
    assert "42" in status.error_state
    assert ("get_parameter", "Error Number", 1) in fake.calls


def test_real_tec_client_does_not_read_error_number_when_status_is_not_error():
    fake = FakeMeComSerial()
    client = _PyMeComTecClient(port="COM9")
    client._mc = fake

    client.read_status((1,))

    assert all(call[1] != "Error Number" for call in fake.calls)


def test_real_tec_client_addresses_channels_independently():
    fake = FakeMeComSerial()
    client = _PyMeComTecClient(port="COM9")
    client._mc = fake

    client.set_target_temperature(1, 18.0)
    client.set_target_temperature(2, 24.0)

    assert fake.object_temperature_c == {1: 18.0, 2: 24.0}
    set_temp_calls = [call for call in fake.calls if call[0] == "set_parameter" and call[1] == "Target Object Temperature"]
    assert set_temp_calls == [
        ("set_parameter", "Target Object Temperature", 1, 18.0),
        ("set_parameter", "Target Object Temperature", 2, 24.0),
    ]


def test_real_tec_client_write_config_is_a_true_noop():
    fake = FakeMeComSerial()
    client = _PyMeComTecClient(port="COM9")
    client._mc = fake

    client.write_config()

    assert fake.calls == []


def test_application_temperature_series_sets_each_target_then_runs_group(tmp_path):
    backend = RecordingTecBackend()

    class TemperatureRunApplication(Application):
        def __init__(self) -> None:
            super().__init__(tec=TecController(enabled=True, simulate=True, backend=backend))
            self.run_calls = []

        def run_experiment2(self, progress=None) -> bool:
            experiment, timed_out = self.experiment_series.dequeue_experiment()
            assert not timed_out
            assert experiment is not None
            self.run_calls.append((str(self.experiment_series.series_path), experiment.repeat_id))
            return True

    app = TemperatureRunApplication()
    series = TemperatureSeries(
        temperature_points_c=[20.0, 25.0],
        tolerance_c=0.1,
        min_settle_s=0.0,
        max_wait_s=0.1,
        poll_interval_s=0.001,
    )
    groups = [
        ExperimentSeries2(tmp_path / "t1", [Experiment2(repeat_id=0)]),
        ExperimentSeries2(tmp_path / "t2", [Experiment2(repeat_id=0), Experiment2(repeat_id=1)]),
    ]

    assert app.run_temperature_series(series, groups) is True
    # TecController's default channels=(1, 2): the single "Temperature
    # points (C)" UI field broadcasts each target to both channels.
    assert [call for call in backend.calls if call[0] == "set_target_temperature"] == [
        ("set_target_temperature", 1, 20.0),
        ("set_target_temperature", 2, 20.0),
        ("set_target_temperature", 1, 25.0),
        ("set_target_temperature", 2, 25.0),
    ]
    assert app.run_calls == [
        (str(tmp_path / "t1"), 0),
        (str(tmp_path / "t2"), 0),
        (str(tmp_path / "t2"), 1),
    ]


def test_application_temperature_series_unlocked_drives_independent_per_channel_targets(tmp_path):
    # Unlocked dual-channel scan (Item 1, 2026-08-04): each step moves both
    # channels to their OWN target in one call, not two sequential per-
    # channel waits -- TemperatureSeries.target_at() returns a
    # {1: ..., 2: ...} dict for each step when temperature_points_ch2_c is
    # set, and TecController.apply_static_setpoint()/wait_until_stable()
    # both accept that dict directly.
    backend = ChannelAwareRecordingTecBackend()

    class TemperatureRunApplication(Application):
        def __init__(self) -> None:
            super().__init__(tec=TecController(enabled=True, simulate=True, backend=backend, channels=(1, 2)))
            self.run_calls = []

        def run_experiment2(self, progress=None) -> bool:
            experiment, timed_out = self.experiment_series.dequeue_experiment()
            assert not timed_out
            assert experiment is not None
            self.run_calls.append(experiment.repeat_id)
            return True

    app = TemperatureRunApplication()
    series = TemperatureSeries(
        temperature_points_c=[20.0, 25.0],
        temperature_points_ch2_c=[30.0, 35.0],
        tolerance_c=0.1,
        min_settle_s=0.0,
        max_wait_s=0.1,
        poll_interval_s=0.001,
    )
    groups = [
        ExperimentSeries2(tmp_path / "t1", [Experiment2(repeat_id=0)]),
        ExperimentSeries2(tmp_path / "t2", [Experiment2(repeat_id=0)]),
    ]

    assert app.run_temperature_series(series, groups) is True
    set_temp_calls = [call for call in backend.calls if call[0] == "set_target_temperature"]
    assert set_temp_calls == [
        ("set_target_temperature", 1, 20.0),
        ("set_target_temperature", 2, 30.0),
        ("set_target_temperature", 1, 25.0),
        ("set_target_temperature", 2, 35.0),
    ]
    assert app.run_calls == [0, 0]


def test_run_temperature_series_abort_during_wait_until_stable_completes_current_point(tmp_path, monkeypatch):
    # Safety-behavior change (2026-08-04, closing a gap Session 78's
    # non-TEC abort fix didn't reach): the real Abort button
    # (qt_ui.py's _abort()) only ever calls Application.fire_stop_event()
    # -- never a mocked listen_abort() override. Confirms the REAL path:
    # fire_stop_event() fired mid-wait_until_stable() must NOT interrupt
    # the temperature point already in flight -- that point's target
    # must still be reached and its full experiment group must still run.
    # Only the *next* temperature point must be prevented from starting.
    backend = RecordingTecBackend()

    class TemperatureRunApplication(Application):
        def __init__(self) -> None:
            super().__init__(tec=TecController(enabled=True, simulate=True, backend=backend))
            self.run_calls: list[str] = []

        def run_experiment2(self, progress=None) -> bool:
            experiment, timed_out = self.experiment_series.dequeue_experiment()
            assert not timed_out
            assert experiment is not None
            self.run_calls.append(str(self.experiment_series.series_path))
            return True

    app = TemperatureRunApplication()

    real_wait_until_stable = TecController.wait_until_stable

    def wait_until_stable_with_abort_injected(self, *args, **kwargs):
        # Simulates the operator clicking Abort while this point's
        # TEC wait is genuinely in progress.
        app.fire_stop_event()
        return real_wait_until_stable(self, *args, **kwargs)

    monkeypatch.setattr(TecController, "wait_until_stable", wait_until_stable_with_abort_injected)

    series = TemperatureSeries(
        temperature_points_c=[20.0, 25.0],
        tolerance_c=0.1,
        min_settle_s=0.0,
        max_wait_s=0.1,
        poll_interval_s=0.001,
    )
    groups = [
        ExperimentSeries2(tmp_path / "t1", [Experiment2(repeat_id=0)]),
        ExperimentSeries2(tmp_path / "t2", [Experiment2(repeat_id=0)]),
    ]

    assert app.run_temperature_series(series, groups) is False
    assert app.status == "TemperatureSeriesAborted"
    assert app.run_calls == [str(tmp_path / "t1")], (
        "point 1 must have completed fully (target reached, group run) despite the abort signaled "
        "mid-wait; point 2 must never have started"
    )


def test_run_temperature_series_abort_during_post_stable_hold_completes_current_point(tmp_path):
    backend = RecordingTecBackend()

    class TemperatureRunApplication(Application):
        def __init__(self) -> None:
            super().__init__(tec=TecController(enabled=True, simulate=True, backend=backend))
            self.run_calls: list[str] = []

        def wait(self, seconds: float):
            # Simulates the real Abort button being clicked during the
            # post-stable hold -- fire_stop_event() directly, exactly
            # what qt_ui.py's _abort() does, not a mocked listen_abort().
            self.fire_stop_event()
            return None

        def run_experiment2(self, progress=None) -> bool:
            experiment, timed_out = self.experiment_series.dequeue_experiment()
            assert not timed_out
            assert experiment is not None
            self.run_calls.append(str(self.experiment_series.series_path))
            return True

    app = TemperatureRunApplication()
    series = TemperatureSeries(
        temperature_points_c=[20.0, 25.0],
        tolerance_c=0.1,
        min_settle_s=0.0,
        max_wait_s=0.1,
        poll_interval_s=0.001,
        post_stable_hold_s=5.0,
    )
    groups = [
        ExperimentSeries2(tmp_path / "t1", [Experiment2(repeat_id=0)]),
        ExperimentSeries2(tmp_path / "t2", [Experiment2(repeat_id=0)]),
    ]

    assert app.run_temperature_series(series, groups) is False
    assert app.status == "TemperatureSeriesAborted"
    assert app.run_calls == [str(tmp_path / "t1")], (
        "point 1 must have completed fully (hold finished, group run) despite the abort signaled "
        "mid-hold; point 2 must never have started"
    )


def test_run_temperature_series_abort_during_a_repeat_completes_the_whole_point(tmp_path):
    backend = RecordingTecBackend()

    class TemperatureRunApplication(Application):
        def __init__(self) -> None:
            super().__init__(tec=TecController(enabled=True, simulate=True, backend=backend))
            self.run_calls: list[int] = []

        def run_experiment2(self, progress=None) -> bool:
            experiment, timed_out = self.experiment_series.dequeue_experiment()
            assert not timed_out
            assert experiment is not None
            self.run_calls.append(experiment.repeat_id)
            if experiment.repeat_id == 0:
                # Simulate Abort clicked partway through point 1's own
                # repeats -- must not prevent point 1's REMAINING repeats
                # from running; "the whole group including all repeats"
                # must still complete.
                self.fire_stop_event()
            return True

    app = TemperatureRunApplication()
    series = TemperatureSeries(
        temperature_points_c=[20.0, 25.0],
        tolerance_c=0.1,
        min_settle_s=0.0,
        max_wait_s=0.1,
        poll_interval_s=0.001,
    )
    groups = [
        ExperimentSeries2(
            tmp_path / "t1", [Experiment2(repeat_id=0), Experiment2(repeat_id=1), Experiment2(repeat_id=2)]
        ),
        ExperimentSeries2(tmp_path / "t2", [Experiment2(repeat_id=0)]),
    ]

    assert app.run_temperature_series(series, groups) is False
    assert app.status == "TemperatureSeriesAborted"
    assert app.run_calls == [0, 1, 2], "all of point 1's repeats must run despite abort firing mid-point"


def test_run_temperature_series_default_post_stable_hold_adds_no_wait(tmp_path):
    # post_stable_hold_s defaults to 0.0 -- must preserve existing
    # behavior exactly, no extra wait introduced.
    backend = RecordingTecBackend()
    wait_calls: list[float] = []

    class TemperatureRunApplication(Application):
        def __init__(self) -> None:
            super().__init__(tec=TecController(enabled=True, simulate=True, backend=backend))

        def wait(self, seconds: float):
            wait_calls.append(seconds)
            return None

        def run_experiment2(self, progress=None) -> bool:
            experiment, timed_out = self.experiment_series.dequeue_experiment()
            assert not timed_out
            assert experiment is not None
            return True

    app = TemperatureRunApplication()
    series = TemperatureSeries(
        temperature_points_c=[20.0],
        tolerance_c=0.1,
        min_settle_s=0.0,
        max_wait_s=0.1,
        poll_interval_s=0.001,
    )
    groups = [ExperimentSeries2(tmp_path / "t1", [Experiment2(repeat_id=0)])]

    assert app.run_temperature_series(series, groups) is True
    assert wait_calls == [], "post_stable_hold_s=0.0 (default) must not introduce any extra wait"


def test_run_temperature_series_post_stable_hold_delays_group_start(tmp_path):
    backend = RecordingTecBackend()
    call_order: list[tuple] = []

    class TemperatureRunApplication(Application):
        def __init__(self) -> None:
            super().__init__(tec=TecController(enabled=True, simulate=True, backend=backend))

        def wait(self, seconds: float):
            call_order.append(("wait", seconds))
            return None

        def run_experiment2(self, progress=None) -> bool:
            call_order.append(("run_experiment2",))
            experiment, timed_out = self.experiment_series.dequeue_experiment()
            assert not timed_out
            assert experiment is not None
            return True

    app = TemperatureRunApplication()
    series = TemperatureSeries(
        temperature_points_c=[20.0],
        tolerance_c=0.1,
        min_settle_s=0.0,
        max_wait_s=0.1,
        poll_interval_s=0.001,
        post_stable_hold_s=2.5,
    )
    groups = [ExperimentSeries2(tmp_path / "t1", [Experiment2(repeat_id=0)])]

    assert app.run_temperature_series(series, groups) is True
    assert call_order == [("wait", 2.5), ("run_experiment2",)], (
        "the hold must happen exactly once, for the configured duration, strictly before the "
        "experiment group starts"
    )


def test_application_temperature_series_rejects_mismatched_group_count(tmp_path):
    app = Application()
    series = TemperatureSeries(temperature_points_c=[20.0, 25.0])
    groups = [ExperimentSeries2(tmp_path / "t1", [Experiment2()])]

    with pytest.raises(ValueError, match="group count"):
        app.run_temperature_series(series, groups)


# -- Phase 1 of the v2 sequence-visualization feature: SetTecTarget/
# WaitTecStable wrap run_temperature_series()'s own TEC calls, once per
# temperature point (not folded into run_experiment2()'s own per-repeat
# steps -- see application.py's STEP_* design note for why). These tests
# confirm that placement precisely; run_experiment2()'s own step events are
# already covered exhaustively in test_full_flow_dry_run.py, so
# run_experiment2() is stubbed here rather than duplicated.


def _record_progress():
    calls: list[tuple[str, object]] = []

    def progress(kind: str, value: object) -> None:
        calls.append((kind, value))

    return progress, calls


def test_run_temperature_series_fires_set_tec_target_and_wait_tec_stable_per_point(tmp_path):
    backend = RecordingTecBackend()

    class TemperatureRunApplication(Application):
        def __init__(self) -> None:
            super().__init__(tec=TecController(enabled=True, simulate=True, backend=backend))
            self.run_calls: list[str | None] = []

        def run_experiment2(self, progress=None) -> bool:
            experiment, timed_out = self.experiment_series.dequeue_experiment()
            assert not timed_out
            assert experiment is not None
            self.run_calls.append(progress)
            return True

    app = TemperatureRunApplication()
    series = TemperatureSeries(
        temperature_points_c=[20.0, 25.0],
        tolerance_c=0.1,
        min_settle_s=0.0,
        max_wait_s=0.1,
        poll_interval_s=0.001,
    )
    groups = [
        ExperimentSeries2(tmp_path / "t1", [Experiment2(repeat_id=0)]),
        ExperimentSeries2(tmp_path / "t2", [Experiment2(repeat_id=0)]),
    ]
    progress, progress_calls = _record_progress()

    assert app.run_temperature_series(series, groups, progress=progress) is True

    started = [value for kind, value in progress_calls if kind == "step_started"]
    completed = [value for kind, value in progress_calls if kind == "step_completed"]
    # One SetTecTarget/WaitTecStable pair per temperature point (2 points),
    # not one per repeat, and not folded into run_experiment2()'s own steps
    # (run_experiment2() is stubbed to fire none itself here).
    assert started == ["SetTecTarget", "WaitTecStable", "SetTecTarget", "WaitTecStable"]
    assert completed == started
    assert progress_calls == [] or all(kind != "step_failed" for kind, _ in progress_calls)
    # The same progress callable was threaded down into run_experiment2()
    # for both repeats, not silently dropped.
    assert app.run_calls == [progress, progress]


def test_run_temperature_series_step_failure_in_set_tec_target(tmp_path):
    class BrokenTecController(TecController):
        def apply_static_setpoint(self, temperature_c: float):
            raise RuntimeError("boom: apply_static_setpoint")

    class TemperatureRunApplication(Application):
        def __init__(self) -> None:
            super().__init__(tec=BrokenTecController(enabled=True, simulate=True, backend=SimulatedTecBackend()))

        def run_experiment2(self, progress=None) -> bool:
            raise AssertionError("run_experiment2 must not run after SetTecTarget fails")

    app = TemperatureRunApplication()
    series = TemperatureSeries(temperature_points_c=[20.0])
    groups = [ExperimentSeries2(tmp_path / "t1", [Experiment2(repeat_id=0)])]
    progress, progress_calls = _record_progress()

    with pytest.raises(RuntimeError, match="boom: apply_static_setpoint"):
        app.run_temperature_series(series, groups, progress=progress)

    assert [value for kind, value in progress_calls if kind == "step_started"] == ["SetTecTarget"]
    assert [value for kind, value in progress_calls if kind == "step_completed"] == []
    assert progress_calls[-1] == ("step_failed", ("SetTecTarget", "boom: apply_static_setpoint"))


def test_run_temperature_series_step_failure_in_wait_tec_stable(tmp_path):
    class BrokenTecController(TecController):
        def wait_until_stable(self, *args, **kwargs):
            raise RuntimeError("boom: wait_until_stable")

    class TemperatureRunApplication(Application):
        def __init__(self) -> None:
            super().__init__(tec=BrokenTecController(enabled=True, simulate=True, backend=SimulatedTecBackend()))

        def run_experiment2(self, progress=None) -> bool:
            raise AssertionError("run_experiment2 must not run after WaitTecStable fails")

    app = TemperatureRunApplication()
    series = TemperatureSeries(temperature_points_c=[20.0])
    groups = [ExperimentSeries2(tmp_path / "t1", [Experiment2(repeat_id=0)])]
    progress, progress_calls = _record_progress()

    with pytest.raises(RuntimeError, match="boom: wait_until_stable"):
        app.run_temperature_series(series, groups, progress=progress)

    assert [value for kind, value in progress_calls if kind == "step_started"] == ["SetTecTarget", "WaitTecStable"]
    assert [value for kind, value in progress_calls if kind == "step_completed"] == ["SetTecTarget"]
    assert progress_calls[-1] == ("step_failed", ("WaitTecStable", "boom: wait_until_stable"))
