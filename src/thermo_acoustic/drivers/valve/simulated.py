from __future__ import annotations


class SimulatedValve:
    def __init__(self) -> None:
        self.initialized = False
        self.position = 1

    def initialize(self) -> None:
        self.initialized = True

    def cleanup(self) -> None:
        self.initialized = False

    def set_position(self, position: int) -> None:
        if position not in (1, 2):
            raise ValueError("position must be 1 or 2")
        self.position = position
