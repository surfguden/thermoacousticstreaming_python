from __future__ import annotations


class SimulatedZStage:
    def __init__(self) -> None:
        self.connected = False
        self.closed_loop = False
        self.position_um = 0.0

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def switch_to_closed_loop(self) -> None:
        self.closed_loop = True

    def set_position(self, position_um: float) -> float:
        if not self.closed_loop:
            raise RuntimeError("Enable closed-loop before moving")
        self.position_um = position_um
        return self.position_um
