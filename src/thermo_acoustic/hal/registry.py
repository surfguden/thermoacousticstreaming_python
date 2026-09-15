from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QThread, Qt

from ..domain.models import DeviceId, OperatingMode
from .ad2 import AD2Worker
from .base import DeviceWorker
from .camera import CameraWorker
from .pump import PumpWorker
from .simulated import (
    SimulatedAD2Worker,
    SimulatedCameraWorker,
    SimulatedPumpWorker,
    SimulatedTecWorker,
    SimulatedValveWorker,
    SimulatedZStageWorker,
)
from .tec import TecWorker
from .valve import ValveWorker
from .z_stage import ZStageWorker


DriverFactory = Callable[[], object]


def _create_ad2_driver() -> object:
    from ..drivers.ad2 import AD2Sdk, WaveFormsDriver

    return AD2Sdk(driver=WaveFormsDriver())


def _create_pump_driver() -> object:
    from ..drivers.pump import CetoniPump, QmixPumpDriver

    return CetoniPump(driver=QmixPumpDriver())


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


_DEFAULT_REAL_FACTORIES: dict[DeviceId, DriverFactory] = {
    DeviceId.AD2: _create_ad2_driver,
    DeviceId.PUMP: _create_pump_driver,
    DeviceId.VALVE: _create_valve_driver,
    DeviceId.CAMERA: _create_camera_driver,
    DeviceId.TEC: _create_tec_driver,
    DeviceId.Z_STAGE: _create_z_stage_driver,
}


class DeviceRegistry:
    """Construct and own the HAL workers and their persistent Qt threads."""

    def __init__(
        self,
        mode: OperatingMode = OperatingMode.SIMULATION,
        factories: dict[DeviceId, DriverFactory] | None = None,
    ) -> None:
        self.mode = mode
        self.workers: dict[DeviceId, DeviceWorker] = {}
        real_factories = dict(_DEFAULT_REAL_FACTORIES)
        if factories:
            real_factories.update(factories)

        worker_classes = {
            DeviceId.AD2: (SimulatedAD2Worker, AD2Worker),
            DeviceId.PUMP: (SimulatedPumpWorker, PumpWorker),
            DeviceId.VALVE: (SimulatedValveWorker, ValveWorker),
            DeviceId.CAMERA: (SimulatedCameraWorker, CameraWorker),
            DeviceId.TEC: (SimulatedTecWorker, TecWorker),
            DeviceId.Z_STAGE: (SimulatedZStageWorker, ZStageWorker),
        }
        for device, (simulation_worker, real_worker) in worker_classes.items():
            worker = (
                simulation_worker()
                if mode is OperatingMode.SIMULATION
                else real_worker(real_factories[device])
            )
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
