from __future__ import annotations

from collections.abc import Callable

from ..domain.models import DeviceId
from .base import DeviceWorker


class PumpWorker(DeviceWorker):
    def __init__(self, device_factory: Callable[[], object], parent=None) -> None:
        super().__init__(DeviceId.PUMP, device_factory, parent=parent)
        self.register("set-flow", self.set_flow)
        self.register("stop", self.safe_stop)

    def set_flow(self, flow_ul_min: float) -> None:
        self.device.generate_flow(flow_ul_min)
        self.state.readings["flow_ul_min"] = flow_ul_min
        self.state.active = flow_ul_min != 0

    def safe_stop(self) -> None:
        if self.device_constructed and self.state.connected:
            self.device.stop()
        self.state.active = False
