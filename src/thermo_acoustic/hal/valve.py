from __future__ import annotations

from collections.abc import Callable

from ..domain.models import DeviceId
from .base import DeviceWorker


class ValveWorker(DeviceWorker):
    def __init__(self, device_factory: Callable[[], object], parent=None) -> None:
        super().__init__(DeviceId.VALVE, device_factory, parent=parent)
        self.register("set-position", self.set_position)

    def set_position(self, position: int) -> None:
        if position not in (1, 2):
            raise ValueError("position must be 1 or 2")
        self.device.set_position(position)
        self.state.readings["position"] = position
