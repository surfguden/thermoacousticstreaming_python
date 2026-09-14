from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class OperatingMode(str, Enum):
    SIMULATION = "simulation"
    REAL = "real"


class DeviceId(str, Enum):
    AD2 = "ad2"
    PUMP = "pump"
    VALVE = "valve"
    CAMERA = "camera"
    TEC = "tec"
    Z_STAGE = "z_stage"


DEVICE_LABELS: dict[DeviceId, str] = {
    DeviceId.AD2: "Waveform generator",
    DeviceId.PUMP: "CETONI pump",
    DeviceId.VALVE: "Selector valve",
    DeviceId.CAMERA: "Hamamatsu camera",
    DeviceId.TEC: "Temperature controller",
    DeviceId.Z_STAGE: "Piezo Z-stage",
}


class ConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


class ExperimentState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class DeviceState:
    device: DeviceId
    connection: ConnectionState = ConnectionState.DISCONNECTED
    summary: str = "Not connected"
    values: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ExperimentStep:
    device: DeviceId
    command: str
    parameters: dict[str, Any] = field(default_factory=dict)
    delay_after_s: float = 0.0
    label: str = ""


@dataclass(frozen=True, slots=True)
class ExperimentPlan:
    name: str
    steps: tuple[ExperimentStep, ...]


@dataclass(frozen=True, slots=True)
class LabSnapshot:
    mode: OperatingMode
    devices: dict[DeviceId, DeviceState]
    experiment_state: ExperimentState = ExperimentState.IDLE
    experiment_step: int = 0
    experiment_total: int = 0
    message: str = "Ready"
