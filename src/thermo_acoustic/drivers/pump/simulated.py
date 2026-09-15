from __future__ import annotations


class SimulatedPump:
    def __init__(self) -> None:
        self.initialized = False
        self.flow_ul_min = 0.0

    def initialize(self) -> None:
        self.initialized = True

    def cleanup(self) -> None:
        self.stop()
        self.initialized = False

    def generate_flow(self, flow_ul_min: float) -> None:
        self.flow_ul_min = flow_ul_min

    def stop(self) -> None:
        self.flow_ul_min = 0.0
