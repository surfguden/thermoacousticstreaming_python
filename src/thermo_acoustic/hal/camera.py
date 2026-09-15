from __future__ import annotations

from collections.abc import Callable

from ..domain.models import DeviceId
from .base import DeviceWorker


class CameraWorker(DeviceWorker):
    def __init__(self, device_factory: Callable[[], object], parent=None) -> None:
        super().__init__(DeviceId.CAMERA, device_factory, parent=parent)
        self.register("snapshot", self.snapshot)

    def initialize_device(self) -> None:
        self.device.open_camera()

    def cleanup_device(self) -> None:
        self.device.close()

    def snapshot(self) -> object:
        return self.device.capture_snapshot()

    def safe_stop(self) -> None:
        if self.device_constructed and self.state.connected:
            self.device.stop_capture()
        self.state.active = False
