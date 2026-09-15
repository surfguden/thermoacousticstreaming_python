from __future__ import annotations

from thermo_acoustic.drivers.ad2 import AD2Sdk, SimulatedAD2Sdk
from thermo_acoustic.drivers.camera import HamamatsuCamera
from thermo_acoustic.drivers.pump import CetoniPump, QmixPumpBackend
from thermo_acoustic.drivers.tec import TecController
from thermo_acoustic.drivers.valve import Valve
from thermo_acoustic.drivers.z_stage import ZStage
from thermo_acoustic.hal import DeviceRegistry, DeviceWorker


def test_public_hal_and_driver_imports_are_available() -> None:
    assert DeviceRegistry is not None
    assert DeviceWorker is not None
    assert all(
        item is not None
        for item in (
            AD2Sdk,
            SimulatedAD2Sdk,
            HamamatsuCamera,
            CetoniPump,
            QmixPumpBackend,
            TecController,
            Valve,
            ZStage,
        )
    )


def test_retained_driver_construction_performs_no_hardware_io() -> None:
    assert AD2Sdk(enabled=False).enabled is False
    assert HamamatsuCamera(enabled=False).enabled is False
    assert CetoniPump(enabled=False).enabled is False
    assert TecController(enabled=False).enabled is False
    assert Valve(enabled=False).enabled is False
    assert ZStage(enabled=False).enabled is False
