from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ZStageLimits:
    minimum_um: float = 0.0
    maximum_um: float = 450.0

    def clamp(self, position_um: float) -> float:
        return max(self.minimum_um, min(float(position_um), self.maximum_um))
