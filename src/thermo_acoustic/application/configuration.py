from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..domain.models import OperatingMode


DEFAULT_PUMP_CONFIGURATION_DIR = Path(__file__).resolve().parents[3] / "Cetoni_Config"


def validate_pump_configuration_dir(value: str | Path) -> Path:
    if not str(value).strip():
        raise ValueError("Choose a Qmix configuration folder before connecting")
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise ValueError(f"Qmix configuration folder does not exist: {path}")
    if not (path / "qmixdevices.xml").is_file():
        raise ValueError(f"Qmix configuration folder must contain qmixdevices.xml: {path}")
    return path


@dataclass(frozen=True, slots=True)
class ApplicationConfiguration:
    mode: OperatingMode = OperatingMode.SIMULATION
    audit_path: Path | None = None
    worker_poll_intervals_s: dict[str, float] | None = None
