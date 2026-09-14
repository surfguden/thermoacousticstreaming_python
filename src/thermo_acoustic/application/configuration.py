from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..domain.models import OperatingMode


@dataclass(frozen=True, slots=True)
class ApplicationConfiguration:
    mode: OperatingMode = OperatingMode.SIMULATION
    audit_path: Path | None = None
    worker_poll_intervals_s: dict[str, float] | None = None

