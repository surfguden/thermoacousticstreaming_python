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

DEVICE_LABELS = {DeviceId.AD2: "Waveform generator", DeviceId.PUMP: "CETONI pump", DeviceId.VALVE: "Selector valve", DeviceId.CAMERA: "Hamamatsu camera", DeviceId.TEC: "Temperature controller", DeviceId.Z_STAGE: "Piezo Z-stage"}

class ConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    ERROR = "error"

@dataclass(frozen=True, slots=True)
class DeviceStatus:
    device: DeviceId
    connection: ConnectionState = ConnectionState.DISCONNECTED
    busy: bool = False
    configured: bool = False
    active: bool = False
    summary: str = "Not connected"
    readings: dict[str, Any] = field(default_factory=dict)
    fault: str | None = None
