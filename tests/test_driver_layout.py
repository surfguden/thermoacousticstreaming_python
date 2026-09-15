from __future__ import annotations

from thermo_acoustic.drivers.ad2 import AnalogDiscovery2, SimulatedAD2
from thermo_acoustic.drivers.camera import (
    HamamatsuDcamDriver,
    IntegerRange,
    SimulatedCamera,
    SubRegion,
    SubRegionLimits,
)
from thermo_acoustic.drivers.pump import CetoniPump, SimulatedPump
from thermo_acoustic.drivers.tec import MeerstetterTecDriver, SimulatedTec, TecController
from thermo_acoustic.drivers.valve import SerialTextCommandTransport, SimulatedValve, Valve
from thermo_acoustic.drivers.z_stage import PiezoStage, SimulatedZStage
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
    pump.cleanup()
    assert pump.flow_ul_min == 0.0

    z_stage = SimulatedZStage()
    z_stage.connect()
    z_stage.switch_to_closed_loop()
    assert z_stage.set_position(50.0) == 50.0
    z_stage.disconnect()


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
    device._stop_analog_output = lambda handle, channel: operations.append(
        ("stop", handle, channel)
    )
    device._reset_analog_output = lambda handle, channel: operations.append(
        ("reset", handle, channel)
    )
    device._stop_digital_output = lambda handle: operations.append(("stop-do", handle))
    device._reset_digital_output = lambda handle: operations.append(("reset-do", handle))
    device._close = lambda handle: operations.append(("close", handle))

    device.cleanup()

    assert operations == [
        ("stop", 13, 0),
        ("reset", 13, 0),
        ("stop", 13, 1),
        ("reset", 13, 1),
        ("stop-do", 13),
        ("reset-do", 13),
        ("close", 13),
    ]
    assert device.device_handle is None
