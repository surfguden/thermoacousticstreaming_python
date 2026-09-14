from __future__ import annotations
from typing import Callable
from PySide6.QtCore import QThread, Qt
from ..domain.models import DeviceId, OperatingMode
from .base import DeviceWorker
from .simulated import SimulatedAD2Worker, SimulatedCameraWorker, SimulatedPumpWorker, SimulatedTecWorker, SimulatedValveWorker, SimulatedZStageWorker
from .ad2 import AD2Worker
from .camera import CameraWorker
from .pump import PumpWorker
from .tec import TecWorker
from .valve import ValveWorker
from .z_stage import ZStageWorker

class DeviceRegistry:
    def __init__(self, mode: OperatingMode = OperatingMode.SIMULATION, factories: dict[DeviceId, Callable[[], object]] | None = None) -> None:
        self.mode = mode; self.workers: dict[DeviceId, DeviceWorker] = {}; factories = factories or {}
        classes = {DeviceId.AD2: (SimulatedAD2Worker, AD2Worker), DeviceId.PUMP: (SimulatedPumpWorker, PumpWorker), DeviceId.VALVE: (SimulatedValveWorker, ValveWorker), DeviceId.CAMERA: (SimulatedCameraWorker, CameraWorker), DeviceId.TEC: (SimulatedTecWorker, TecWorker), DeviceId.Z_STAGE: (SimulatedZStageWorker, ZStageWorker)}
        for device, (simulated, real) in classes.items():
            driver = factories[device]() if mode is OperatingMode.REAL and device in factories else None
            worker = simulated() if mode is OperatingMode.SIMULATION else real(driver)
            thread = QThread(); worker.moveToThread(thread); thread.started.connect(worker.start_polling); worker.stopped.connect(thread.quit, Qt.DirectConnection); worker._thread = thread; self.workers[device] = worker
    def by_id(self, device: DeviceId) -> DeviceWorker: return self.workers[device]
    def all(self): return tuple(self.workers.values())
