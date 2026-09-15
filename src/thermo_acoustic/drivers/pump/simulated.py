from __future__ import annotations

import math


class SimulatedPump:
    def __init__(self) -> None:
        self.initialized = False
        self.flow_ul_min = 0.0
        self.fill_level_ml = 0.0
        self.max_volume_ml = 1.0
        self.max_flow_rate_ul_min = 10000.0
        self.syringe_config: dict | None = None
        self.flow_unit: str | None = None
        self.referenced = False

    def initialize(self) -> None:
        self.initialized = True

    def cleanup(self) -> None:
        self.stop()
        self.initialized = False

    def clear_fault_and_reinitialize(self) -> None:
        self.initialize()

    def generate_flow(self, flow_rate: float) -> None:
        flow_rate = float(flow_rate)
        if not math.isfinite(flow_rate) or abs(flow_rate) > self.max_flow_rate_ul_min:
            raise ValueError(
                f"flow_rate must be finite and within +/-{self.max_flow_rate_ul_min} ul/min"
            )
        self.flow_ul_min = flow_rate

    def stop(self) -> None:
        self.flow_ul_min = 0.0

    def refill(self, flow_rate: float | None = None) -> None:
        self.fill_level_ml = self.max_volume_ml
        self.flow_ul_min = 0.0

    def empty(self, flow_rate: float | None = None) -> None:
        self.fill_level_ml = 0.0
        self.flow_ul_min = 0.0

    def set_fill_level(self, fill_level: float, flow_rate: float | None = None) -> None:
        self.fill_level_ml = fill_level
        self.flow_ul_min = 0.0

    def read_fill_level(self) -> float:
        return self.fill_level_ml

    def configure_syringe(self, config: dict | None) -> None:
        self.syringe_config = config
        if config and config.get("volume_ml") is not None:
            self.max_volume_ml = float(config["volume_ml"])

    def configure_flow_unit(self, unit: str | None) -> None:
        self.flow_unit = unit

    def reference_move(self) -> None:
        self.referenced = True

    def read_status(self) -> bool:
        return self.flow_ul_min != 0.0
