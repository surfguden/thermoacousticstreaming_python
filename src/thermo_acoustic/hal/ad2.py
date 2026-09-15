from __future__ import annotations

from collections.abc import Callable

from ..domain.models import DeviceId
from .base import DeviceWorker


class AD2Worker(DeviceWorker):
    def __init__(self, device_factory: Callable[[], object], parent=None) -> None:
        super().__init__(DeviceId.AD2, device_factory, parent=parent)
        self.register("configure", self.configure)
        self.register("start", self.start)
        self.register("stop", self.safe_stop)
        self.register("trigger", self.trigger)
        self.register("scope-configure", self.scope_configure)
        self.register("scope-read", self.scope_read)

    def configure(self, frequency_hz: float = 1000.0, amplitude_v: float = 1.0) -> None:
        if frequency_hz <= 0 or not 0 <= amplitude_v <= 5:
            raise ValueError("frequency_hz must be positive and amplitude_v must be 0..5")
        self.device.wfg_configure(
            {"frequency_hz": frequency_hz, "amplitude_v": amplitude_v}
        )
        self.state.configured = True
        self.state.readings.update(frequency_hz=frequency_hz, amplitude_v=amplitude_v)

    def start(self) -> None:
        if not self.state.configured:
            raise RuntimeError("Configure AD2 before starting")
        self.device.wfg_start_stop_all_ch(True)
        self.state.active = True

    def safe_stop(self) -> None:
        if self.device_constructed and self.state.connected:
            self.device.wfg_start_stop_all_ch(False)
        self.state.active = False

    def trigger(self) -> None:
        self.device.pc_trigger()

    def scope_configure(self, configuration: object = None) -> None:
        self.device.scope_configure(configuration)
        self.state.active = True
        self.state.readings["scope_state"] = "armed"

    def scope_read(self) -> dict[int, list[float]]:
        try:
            return self.device.scope_read()
        finally:
            self.state.active = False
            self.state.readings["scope_state"] = "idle"
