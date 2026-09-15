from __future__ import annotations

from collections.abc import Callable

from ..domain.models import DeviceId
from .base import DeviceWorker


class TecWorker(DeviceWorker):
    def __init__(self, device_factory: Callable[[], object], parent=None) -> None:
        super().__init__(DeviceId.TEC, device_factory, parent=parent)
        self.register("set-temperature", self.set_temperature)
        self.register("outputs-off", self.safe_stop)

    def set_temperature(self, temperature_c: float) -> None:
        self.device.apply_static_setpoint(temperature_c)
        self.state.readings["temperature_c"] = temperature_c
        self.state.active = True

    def safe_stop(self) -> None:
        if self.device_constructed and self.state.connected:
            self.device.set_output_stage_static_off()
        self.state.active = False
