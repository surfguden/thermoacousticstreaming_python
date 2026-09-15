from __future__ import annotations

from collections.abc import Callable

from ..domain.models import DeviceId
from .base import DriverDeviceWorker


class PumpWorker(DriverDeviceWorker):
    def __init__(self, driver_factory: Callable[[], object], parent=None) -> None:
        super().__init__(DeviceId.PUMP, driver_factory, parent=parent)
        self.register("set-flow", self.set_flow)
        self.register("stop", self.safe_stop)

    def set_flow(self, flow_ul_min: float) -> None:
        if not -10000 <= flow_ul_min <= 10000:
            raise ValueError("flow_ul_min out of range")
        self.driver.generate_flow(flow_ul_min)
        self.state.readings["flow_ul_min"] = flow_ul_min
        self.state.active = flow_ul_min != 0

    def safe_stop(self) -> None:
        if self.driver_constructed and self.state.connected:
            self.driver.stop()
        self.state.active = False
