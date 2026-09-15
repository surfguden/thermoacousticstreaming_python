from __future__ import annotations

from collections.abc import Callable

from ..domain.models import DeviceId
from .base import DriverDeviceWorker


class ZStageWorker(DriverDeviceWorker):
    def __init__(self, driver_factory: Callable[[], object], parent=None) -> None:
        super().__init__(DeviceId.Z_STAGE, driver_factory, parent=parent)
        self.register("enable-closed-loop", self.enable_closed_loop)
        self.register("move", self.move)

    def initialize_driver(self) -> None:
        self.driver.connect()

    def cleanup_driver(self) -> None:
        self.driver.disconnect()

    def enable_closed_loop(self) -> None:
        self.driver.switch_to_closed_loop()
        self.state.configured = True
        self.state.readings["closed_loop"] = True

    def move(self, position_um: float) -> None:
        if not 0 <= position_um <= 450:
            raise ValueError("position_um must be between 0 and 450")
        if not self.state.readings.get("closed_loop"):
            raise RuntimeError("Enable closed-loop before moving")
        confirmed_position_um = self.driver.set_position(position_um)
        self.state.readings["position_um"] = confirmed_position_um
