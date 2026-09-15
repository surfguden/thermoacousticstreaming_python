from __future__ import annotations

from .models import ZStageLimits

class SimulatedZStage:
    def __init__(self) -> None:
        self.connected = False
        self.closed_loop = False
        self.position_um = 0.0
        self.travel_limits = ZStageLimits()

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def switch_to_closed_loop(self) -> None:
        self.closed_loop = True

    def set_position(self, position_um: float) -> float:
        if not self.closed_loop:
            raise RuntimeError("Enable closed-loop before moving")
        self.position_um = self.travel_limits.clamp(position_um)
        return self.position_um

    def get_position(self) -> float:
        if not self.connected:
            raise RuntimeError("Z-stage is not connected")
        if not self.closed_loop:
            raise RuntimeError("Enable closed-loop before reading position")
        return self.position_um
