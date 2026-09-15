from __future__ import annotations


class SimulatedTec:
    def __init__(self) -> None:
        self.initialized = False
        self.outputs_enabled = False
        self.targets_c: dict[int, float] = {}

    def initialize(self) -> None:
        self.initialized = True

    def cleanup(self) -> None:
        self.set_output_stage_static_off()
        self.initialized = False

    def apply_static_setpoint(self, targets_c: dict[int, float]) -> None:
        self.targets_c = dict(targets_c)
        self.outputs_enabled = True

    def set_output_stage_static_off(self) -> None:
        self.outputs_enabled = False
