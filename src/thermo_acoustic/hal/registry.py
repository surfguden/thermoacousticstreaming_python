from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QThread, Qt

from ..domain.models import DeviceId, OperatingMode
from .ad2 import AD2Worker
from .base import DeviceWorker
from .camera import CameraWorker
from .pump import PumpWorker
from .tec import TecWorker
from .valve import ValveWorker
from .z_stage import ZStageWorker


DeviceFactory = Callable[[], object]


def _create_ad2_driver() -> object:
    from ..drivers.ad2 import AnalogDiscovery2

    return AnalogDiscovery2()


def _create_pump_driver() -> object:
    from ..drivers.pump import CetoniPumpBank

    return CetoniPumpBank()


def _create_valve_driver() -> object:
    from ..drivers.valve import SerialTextCommandTransport, Valve

    return Valve(transport=SerialTextCommandTransport(device_name="valve"))


def _create_camera_driver() -> object:
    from ..drivers.camera import HamamatsuDcamDriver

    return HamamatsuDcamDriver()


def _create_tec_driver() -> object:
    from ..drivers.tec import MeerstetterTecDriver, TecController

    return TecController(driver=MeerstetterTecDriver(), enabled=True)


def _create_z_stage_driver() -> object:
    from ..drivers.z_stage import PiezoStage

    return PiezoStage()


def _create_simulated_ad2() -> object:
    from ..drivers.ad2 import SimulatedAD2

    return SimulatedAD2()


def _create_simulated_pump() -> object:
    from ..drivers.pump import SimulatedPumpBank

    return SimulatedPumpBank()


def _create_simulated_valve() -> object:
    from ..drivers.valve import SimulatedValve

    return SimulatedValve()


def _create_simulated_camera() -> object:
    from ..drivers.camera import SimulatedCamera

    return SimulatedCamera()


def _create_simulated_tec() -> object:
    from ..drivers.tec import SimulatedTec

    return SimulatedTec()


def _create_simulated_z_stage() -> object:
    from ..drivers.z_stage import SimulatedZStage

    return SimulatedZStage()


_DEFAULT_REAL_FACTORIES: dict[DeviceId, DeviceFactory] = {
    DeviceId.AD2: _create_ad2_driver,
    DeviceId.PUMP: _create_pump_driver,
    DeviceId.VALVE: _create_valve_driver,
    DeviceId.CAMERA: _create_camera_driver,
    DeviceId.TEC: _create_tec_driver,
    DeviceId.Z_STAGE: _create_z_stage_driver,
}

_DEFAULT_SIMULATION_FACTORIES: dict[DeviceId, DeviceFactory] = {
    DeviceId.AD2: _create_simulated_ad2,
    DeviceId.PUMP: _create_simulated_pump,
    DeviceId.VALVE: _create_simulated_valve,
    DeviceId.CAMERA: _create_simulated_camera,
    DeviceId.TEC: _create_simulated_tec,
    DeviceId.Z_STAGE: _create_simulated_z_stage,
}


class DeviceRegistry:
    """Construct and own the HAL workers and their persistent Qt threads."""

    def __init__(
        self,
        mode: OperatingMode = OperatingMode.SIMULATION,
        factories: dict[DeviceId, DeviceFactory] | None = None,
    ) -> None:
        self.mode = mode
        self.workers: dict[DeviceId, DeviceWorker] = {}
        selected_factories = dict(
            _DEFAULT_SIMULATION_FACTORIES
            if mode is OperatingMode.SIMULATION
            else _DEFAULT_REAL_FACTORIES
        )
        if factories:
            selected_factories.update(factories)

        worker_classes = {
            DeviceId.AD2: AD2Worker,
            DeviceId.PUMP: PumpWorker,
            DeviceId.VALVE: ValveWorker,
            DeviceId.CAMERA: CameraWorker,
            DeviceId.TEC: TecWorker,
            DeviceId.Z_STAGE: ZStageWorker,
        }
        for device, worker_class in worker_classes.items():
            worker = worker_class(selected_factories[device])
            thread = QThread()
            worker.moveToThread(thread)
            thread.started.connect(worker.start_polling)
            worker.stopped.connect(thread.quit, Qt.DirectConnection)
            worker._thread = thread
            self.workers[device] = worker

    def by_id(self, device: DeviceId) -> DeviceWorker:
        return self.workers[device]

    def all(self) -> tuple[DeviceWorker, ...]:
        return tuple(self.workers.values())
