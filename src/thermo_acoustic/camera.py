from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class MinMaxInc:
    minimum: int = 0
    maximum: int = 0
    increment: int = 1


@dataclass(slots=True)
class SubRegion:
    horizontal_offset: int = 0
    vertical_offset: int = 0
    horizontal_size: int = 0
    vertical_size: int = 0

    def centered(self, limits: "SubRegionLimits") -> "SubRegion":
        width = self.horizontal_size or limits.horizontal_size.maximum
        height = self.vertical_size or limits.vertical_size.maximum
        x = max((limits.horizontal_size.maximum - width) // 2, 0)
        y = max((limits.vertical_size.maximum - height) // 2, 0)
        return SubRegion(x, y, width, height)


@dataclass(slots=True)
class SubRegionLimits:
    horizontal_offset: MinMaxInc = field(default_factory=MinMaxInc)
    vertical_offset: MinMaxInc = field(default_factory=MinMaxInc)
    horizontal_size: MinMaxInc = field(default_factory=MinMaxInc)
    vertical_size: MinMaxInc = field(default_factory=MinMaxInc)
