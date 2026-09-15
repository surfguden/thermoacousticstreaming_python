from __future__ import annotations

from collections.abc import Callable

from ..domain.models import DeviceId
from .base import DriverDeviceWorker


class CameraWorker(DriverDeviceWorker):
    def __init__(self, driver_factory: Callable[[], object], parent=None) -> None:
        super().__init__(DeviceId.CAMERA, driver_factory, parent=parent)
        self.register("snapshot", self.snapshot)

    def initialize_driver(self) -> None:
        self.driver.open_camera()

    def cleanup_driver(self) -> None:
        self.driver.close()

    def snapshot(self) -> object:
        return self.driver.capture_snapshot()

    def safe_stop(self) -> None:
        if self.driver_constructed and self.state.connected:
            self.driver.stop_capture()
        self.state.active = False
