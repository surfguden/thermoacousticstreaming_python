from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class CameraMode(str, Enum):
    """Acquisition mode selected for the next camera operation."""

    SNAPSHOT = "snapshot"
    SEQUENCE = "sequence"


@dataclass(slots=True)
class IntegerRange:
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
    horizontal_offset: IntegerRange = field(default_factory=IntegerRange)
    vertical_offset: IntegerRange = field(default_factory=IntegerRange)
    horizontal_size: IntegerRange = field(default_factory=IntegerRange)
    vertical_size: IntegerRange = field(default_factory=IntegerRange)
