from __future__ import annotations

from collections.abc import Callable

from ..domain.models import DeviceId
from .base import DeviceWorker


class ZStageWorker(DeviceWorker):
    def __init__(self, device_factory: Callable[[], object], parent=None) -> None:
        super().__init__(DeviceId.Z_STAGE, device_factory, parent=parent)
        self.register("enable-closed-loop", self.enable_closed_loop)
        self.register("move", self.move)

    def initialize_device(self) -> None:
        self.device.connect()

    def cleanup_device(self) -> None:
        self.device.disconnect()

    def enable_closed_loop(self) -> None:
        self.device.switch_to_closed_loop()
        self.state.configured = True
        self.state.readings["closed_loop"] = True

    def move(self, position_um: float) -> None:
        if not self.state.readings.get("closed_loop"):
            raise RuntimeError("Enable closed-loop before moving")
        confirmed_position_um = self.device.set_position(position_um)
        self.state.readings["position_um"] = confirmed_position_um
