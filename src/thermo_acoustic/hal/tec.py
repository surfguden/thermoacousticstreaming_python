from __future__ import annotations

from collections.abc import Callable

from ..domain.models import DeviceId
from .base import DriverDeviceWorker


class TecWorker(DriverDeviceWorker):
    def __init__(self, driver_factory: Callable[[], object], parent=None) -> None:
        super().__init__(DeviceId.TEC, driver_factory, parent=parent)
        self.register("set-temperature", self.set_temperature)
        self.register("outputs-off", self.safe_stop)

    def set_temperature(self, temperature_c: float) -> None:
        if not -20 <= temperature_c <= 120:
            raise ValueError("temperature_c out of range")
        self.driver.apply_static_setpoint({1: temperature_c})
        self.state.readings["temperature_c"] = temperature_c
        self.state.active = True

    def safe_stop(self) -> None:
        if self.driver_constructed and self.state.connected:
            self.driver.set_output_stage_static_off()
        self.state.active = False
