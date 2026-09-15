from __future__ import annotations

from typing import Any

from .base import DeviceWorker
from ..domain.models import DeviceId


class SimulatedWorker(DeviceWorker):
    def __init__(self, device_id: DeviceId, *, parent=None) -> None:
        super().__init__(device_id, parent=parent)
        self.register("status", lambda: self.status())


class SimulatedAD2Worker(SimulatedWorker):
    def __init__(self, parent=None) -> None:
        super().__init__(DeviceId.AD2, parent=parent)
        self.register("configure", self.configure)
        self.register("start", self.start)
        self.register("stop", self.safe_stop)
        self.register("trigger", lambda: None)
    def configure(self, frequency_hz: float = 1000.0, amplitude_v: float = 1.0) -> None:
        if frequency_hz <= 0 or not 0 <= amplitude_v <= 5: raise ValueError("frequency_hz must be positive and amplitude_v must be 0..5")
        self.state.configured = True
        self.state.readings.update(frequency_hz=frequency_hz, amplitude_v=amplitude_v)
    def start(self) -> None:
        if not self.state.configured: raise RuntimeError("Configure AD2 before starting")
        self.state.active = True


class SimulatedPumpWorker(SimulatedWorker):
    def __init__(self, parent=None) -> None:
        super().__init__(DeviceId.PUMP, parent=parent)
        self.register("set-flow", self.set_flow); self.register("stop", self.safe_stop)
        self.register("configure", lambda: self._configure())
        self.state.readings.update(flow_ul_min=0.0)
    def _configure(self): self.state.configured = True
    def set_flow(self, flow_ul_min: float) -> None:
        if not -10000 <= flow_ul_min <= 10000: raise ValueError("flow_ul_min out of range")
        self.state.readings["flow_ul_min"] = flow_ul_min; self.state.active = flow_ul_min != 0


class SimulatedValveWorker(SimulatedWorker):
    def __init__(self, parent=None) -> None:
        super().__init__(DeviceId.VALVE, parent=parent); self.register("set-position", self.set_position)
    def set_position(self, position: int) -> None:
        if position not in (1, 2): raise ValueError("position must be 1 or 2")
        self.state.readings["position"] = position


class SimulatedCameraWorker(SimulatedWorker):
    def __init__(self, parent=None) -> None:
        super().__init__(DeviceId.CAMERA, parent=parent); self.register("snapshot", lambda: {"frames": 1})


class SimulatedTecWorker(SimulatedWorker):
    def __init__(self, parent=None) -> None:
        super().__init__(DeviceId.TEC, parent=parent); self.register("set-temperature", self.set_temperature); self.register("outputs-off", self.safe_stop)
    def set_temperature(self, temperature_c: float) -> None:
        if not -20 <= temperature_c <= 120: raise ValueError("temperature_c out of range")
        self.state.readings["temperature_c"] = temperature_c; self.state.active = True


class SimulatedZStageWorker(SimulatedWorker):
    def __init__(self, parent=None) -> None:
        super().__init__(DeviceId.Z_STAGE, parent=parent); self.register("enable-closed-loop", self.enable); self.register("move", self.move)
    def enable(self): self.state.configured = True; self.state.readings["closed_loop"] = True
    def move(self, position_um: float) -> None:
        if not 0 <= position_um <= 450: raise ValueError("position_um must be between 0 and 450")
        if not self.state.readings.get("closed_loop"): raise RuntimeError("Enable closed-loop before moving")
        self.state.readings["position_um"] = position_um
