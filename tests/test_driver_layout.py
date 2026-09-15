from __future__ import annotations

from thermo_acoustic.drivers.ad2 import AD2Sdk, SimulatedAD2, WaveFormsDriver
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
            AD2Sdk,
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
    assert AD2Sdk(driver=dependency, enabled=False).driver is dependency
    assert CetoniPump().pump is None
    assert TecController(driver=dependency, enabled=False).driver is dependency
    assert Valve(transport=dependency, enabled=False).transport is dependency
    assert WaveFormsDriver.is_available() in (True, False)
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
