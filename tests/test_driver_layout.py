from __future__ import annotations

import pytest

from thermo_acoustic.drivers.ad2 import (
    AnalogDiscovery2,
    AnalogDiscoveryError,
    ScopeConfig,
    ScopeState,
    SimulatedAD2,
)
from thermo_acoustic.drivers.ad2.configuration import TriggerSource
from thermo_acoustic.drivers.camera import (
    CameraMode,
    HamamatsuDcamDriver,
    IntegerRange,
    SimulatedCamera,
    SubRegion,
    SubRegionLimits,
)
from thermo_acoustic.drivers.pump import CetoniPump, SimulatedPump
from thermo_acoustic.drivers.tec import MeerstetterTecDriver, SimulatedTec, TecController
from thermo_acoustic.drivers.valve import SerialTextCommandTransport, SimulatedValve, Valve
from thermo_acoustic.drivers.z_stage import PiezoStage, SimulatedZStage, ZStageLimits
from thermo_acoustic.hal import DeviceRegistry, DeviceWorker


def test_public_hal_and_driver_imports_are_available() -> None:
    assert DeviceRegistry is not None
    assert DeviceWorker is not None
    assert all(
        item is not None
        for item in (
            AnalogDiscovery2,
            SimulatedAD2,
            HamamatsuDcamDriver,
            SimulatedCamera,
            CetoniPump,
            SimulatedPump,
            SimulatedTec,
            SimulatedValve,
            SimulatedZStage,
            TecController,
            Valve,
            PiezoStage,
        )
    )


def test_retained_driver_construction_performs_no_hardware_io() -> None:
    dependency = object()
    assert AnalogDiscovery2(enabled=False).device_handle is None
    assert CetoniPump().pump is None
    assert TecController(driver=dependency, enabled=False).driver is dependency
    assert Valve(transport=dependency, enabled=False).transport is dependency
    assert AnalogDiscovery2.is_available() in (True, False)
    assert HamamatsuDcamDriver().dcam is None
    assert MeerstetterTecDriver().client is None
    assert SerialTextCommandTransport().port is None
    assert PiezoStage().connected is False


def test_simulated_devices_are_reusable_without_the_hal() -> None:
    pump = SimulatedPump()
    pump.initialize()
    pump.configure_syringe({"volume_ml": 5.0})
    pump.refill(100.0)
    assert pump.read_fill_level() == 5.0
    pump.generate_flow(25.0)
    assert pump.flow_ul_min == 25.0
    assert pump.read_status()
    with pytest.raises(ValueError, match="within"):
        pump.generate_flow(10001.0)
    pump.cleanup()
    assert pump.flow_ul_min == 0.0
    pump.clear_fault_and_reinitialize()
    assert pump.initialized
    pump.cleanup()

    z_stage = SimulatedZStage()
    z_stage.connect()
    z_stage.switch_to_closed_loop()
    assert z_stage.set_position(50.0) == 50.0
    assert z_stage.get_position() == 50.0
    assert z_stage.set_position(999.0) == z_stage.travel_limits.maximum_um
    z_stage.disconnect()

    assert ZStageLimits(maximum_um=100.0).clamp(-5.0) == 0.0

    valve = SimulatedValve()
    valve.initialize()
    valve.set_position(2)
    assert "pending" in valve.status_note
    with pytest.raises(RuntimeError, match="not confirmed"):
        valve.read_position()
    assert valve.wait_until_ready()
    assert valve.status_note == "confirmed"
    assert valve.read_position() == 2
    valve.cleanup()

    tec = SimulatedTec()
    tec.initialize()
    status = tec.apply_static_setpoint({1: 25.0, 2: 26.0})
    assert status[1].target_temperature_c == 25.0
    assert status[2].target_temperature_c == 26.0
    with pytest.raises(ValueError, match="outside the local safety range"):
        tec.apply_static_setpoint({1: -1.0, 2: 26.0})
    with pytest.raises(ValueError, match="must exactly match"):
        tec.apply_static_setpoint({1: 25.0}, channels=(1, 2))
    tec.set_output_stage_static_off()


def test_camera_roi_can_be_centered_with_integer_limits() -> None:
    limits = SubRegionLimits(
        horizontal_size=IntegerRange(minimum=4, maximum=2048, increment=4),
        vertical_size=IntegerRange(minimum=4, maximum=1024, increment=4),
    )
    assert SubRegion(horizontal_size=512, vertical_size=256).centered(limits) == SubRegion(
        horizontal_offset=768,
        vertical_offset=384,
        horizontal_size=512,
        vertical_size=256,
    )


def test_simulated_camera_supports_snapshot_and_buffered_sequence_modes() -> None:
    camera = SimulatedCamera(buffer_frames=4)
    camera.open_camera()

    camera.configure_sequence({"frames": 3, "exposure_ms": 2.5})
    assert camera.mode is CameraMode.SEQUENCE
    camera.start_capture()
    frames = camera.image_sequence(3)
    assert [frame["frame_number"] for frame in frames] == [1, 2, 3]
    assert camera.capture_active
    camera.stop_capture()

    camera.configure_snapshot()
    assert camera.mode is CameraMode.SNAPSHOT
    assert camera.sequence_settings is None
    assert camera.capture_snapshot()["frame_number"] == 4


def test_analog_discovery_configures_directly_without_an_inner_driver() -> None:
    device = AnalogDiscovery2(enabled=False)
    configured: list[tuple[int, object]] = []
    device.enabled = True
    device._open_device = lambda _index: 7
    device._configure_wfg = lambda handle, config: configured.append((handle, config))

    device.wfg_configure({"frequency_hz": 2500.0, "amplitude_v": 0.5})

    assert device.device_handle == 7
    assert configured == [(7, device.wfg_config)]


def test_analog_discovery_do_config_keeps_custom_pattern_and_clock_settings() -> None:
    device = AnalogDiscovery2(enabled=False)
    configured: list[tuple[int, object]] = []
    device.enabled = True
    device._open_device = lambda _index: 11
    device._configure_do = lambda handle, config: configured.append((handle, config))

    device.do_configure(
        {
            "enabled": True,
            "output_type": "Custom",
            "clock_frequency_hz": 500.0,
            "bits": [1, 1, 0, 0],
        }
    )

    channel = device.do_config.channels[0]
    assert configured == [(11, device.do_config)]
    assert channel.clock_frequency_hz == 500.0
    assert channel.custom_data.bits == [1, 1, 0, 0]


def test_analog_discovery_cleanup_stops_resets_and_closes_directly() -> None:
    device = AnalogDiscovery2(enabled=False)
    operations: list[tuple[object, ...]] = []
    device.device_handle = 13
    device.scope_state = ScopeState.ARMED
    device._stop_analog_output = lambda handle, channel: operations.append(
        ("stop", handle, channel)
    )
    device._reset_analog_output = lambda handle, channel: operations.append(
        ("reset", handle, channel)
    )
    device._stop_digital_output = lambda handle: operations.append(("stop-do", handle))
    device._reset_digital_output = lambda handle: operations.append(("reset-do", handle))
    device._reset_scope = lambda handle: operations.append(("reset-scope", handle))
    device._close = lambda handle: operations.append(("close", handle))

    device.cleanup()

    assert operations == [
        ("stop", 13, 0),
        ("reset", 13, 0),
        ("stop", 13, 1),
        ("reset", 13, 1),
        ("stop-do", 13),
        ("reset-do", 13),
        ("reset-scope", 13),
        ("close", 13),
    ]
    assert device.device_handle is None
    assert device.scope_state is ScopeState.IDLE


def test_analog_discovery_scope_can_arm_trigger_and_read_in_sequence() -> None:
    device = AnalogDiscovery2(enabled=False)
    operations: list[tuple[object, ...]] = []
    device.enabled = True
    device._open_device = lambda _index: 17
    device._configure_scope = lambda handle, config: operations.append(
        ("configure-scope", handle, config)
    )
    device._trigger_pc = lambda handle: operations.append(("trigger", handle))
    device._read_scope = lambda handle, config: (
        operations.append(("read-scope", handle, config)) or {0: [1.0, 2.0]}
    )

    configuration = ScopeConfig(
        sample_count=2,
        trigger_source=TriggerSource.DIGITAL_OUT,
    )
    device.scope_configure(configuration)
    assert device.scope_state is ScopeState.ARMED

    device.pc_trigger()
    samples = device.scope_read()

    assert samples == {0: [1.0, 2.0]}
    assert [operation[0] for operation in operations] == [
        "configure-scope",
        "trigger",
        "read-scope",
    ]
    assert device.scope_state is ScopeState.IDLE


def test_analog_discovery_scope_read_requires_an_armed_scope() -> None:
    with pytest.raises(AnalogDiscoveryError, match="requires an armed scope"):
        AnalogDiscovery2(enabled=False).scope_read()


def test_simulated_scope_uses_the_same_arm_and_read_lifecycle() -> None:
    device = SimulatedAD2()
    device.initialize()

    device.scope_configure({"channels": [0, 1], "sample_count": 3})
    device.pc_trigger()
    samples = device.scope_read()

    assert samples == {0: [0.0, 0.0, 0.0], 1: [0.0, 0.0, 0.0]}
    assert device.triggered
    assert not device.scope_armed
