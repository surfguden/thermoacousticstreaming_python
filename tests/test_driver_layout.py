from __future__ import annotations

from thermo_acoustic.drivers.ad2 import AD2Sdk, WaveFormsDriver
from thermo_acoustic.drivers.camera import HamamatsuDcamDriver
from thermo_acoustic.drivers.pump import CetoniPump, QmixPumpDriver
from thermo_acoustic.drivers.tec import MeerstetterTecDriver, TecController
from thermo_acoustic.drivers.valve import SerialTextCommandTransport, Valve
from thermo_acoustic.drivers.z_stage import PiezoStage
from thermo_acoustic.hal import DeviceRegistry, DeviceWorker


def test_public_hal_and_driver_imports_are_available() -> None:
    assert DeviceRegistry is not None
    assert DeviceWorker is not None
    assert all(
        item is not None
        for item in (
            AD2Sdk,
            HamamatsuDcamDriver,
            CetoniPump,
            QmixPumpDriver,
            TecController,
            Valve,
            PiezoStage,
        )
    )


def test_retained_driver_construction_performs_no_hardware_io() -> None:
    dependency = object()
    assert AD2Sdk(driver=dependency, enabled=False).driver is dependency
    assert CetoniPump(driver=dependency, enabled=False).driver is dependency
    assert TecController(driver=dependency, enabled=False).driver is dependency
    assert Valve(transport=dependency, enabled=False).transport is dependency
    assert WaveFormsDriver.is_available() in (True, False)
    assert HamamatsuDcamDriver().dcam is None
    assert QmixPumpDriver().pump is None
    assert MeerstetterTecDriver().client is None
    assert SerialTextCommandTransport().port is None
    assert PiezoStage().connected is False
