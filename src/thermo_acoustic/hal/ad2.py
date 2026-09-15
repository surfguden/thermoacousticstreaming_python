from __future__ import annotations

from collections.abc import Callable

from ..domain.models import DeviceId
from .base import DriverDeviceWorker


class AD2Worker(DriverDeviceWorker):
    def __init__(self, driver_factory: Callable[[], object], parent=None) -> None:
        super().__init__(DeviceId.AD2, driver_factory, parent=parent)
        self.register("configure", self.configure)
        self.register("start", self.start)
        self.register("stop", self.safe_stop)

    def configure(self, frequency_hz: float = 1000.0, amplitude_v: float = 1.0) -> None:
        if frequency_hz <= 0 or not 0 <= amplitude_v <= 5:
            raise ValueError("frequency_hz must be positive and amplitude_v must be 0..5")
        self.driver.wfg_configure({})
        self.state.configured = True
        self.state.readings.update(frequency_hz=frequency_hz, amplitude_v=amplitude_v)

    def start(self) -> None:
        if not self.state.configured:
            raise RuntimeError("Configure AD2 before starting")
        self.driver.wfg_start_stop_all_ch(True)
        self.state.active = True

    def safe_stop(self) -> None:
        if self.driver_constructed and self.state.connected:
            self.driver.wfg_start_stop_all_ch(False)
        self.state.active = False
