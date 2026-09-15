from __future__ import annotations

from collections.abc import Callable

from ..domain.models import DeviceId
from .base import DriverDeviceWorker


class ValveWorker(DriverDeviceWorker):
    def __init__(self, driver_factory: Callable[[], object], parent=None) -> None:
        super().__init__(DeviceId.VALVE, driver_factory, parent=parent)
        self.register("set-position", self.set_position)

    def set_position(self, position: int) -> None:
        if position not in (1, 2):
            raise ValueError("position must be 1 or 2")
        self.driver.set_position(position)
        self.state.readings["position"] = position
