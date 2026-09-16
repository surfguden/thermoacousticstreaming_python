from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


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


DEVICE_LABELS = {
    DeviceId.AD2: "Waveform generator",
    DeviceId.PUMP: "CETONI pump",
    DeviceId.VALVE: "Selector valve",
    DeviceId.CAMERA: "Hamamatsu camera",
    DeviceId.TEC: "Temperature controller",
    DeviceId.Z_STAGE: "Piezo Z-stage",
}


class ConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class Ad2Readback:
    waveform_frequency_hz: float | None = None
    waveform_amplitude_v: float | None = None
    waveform_running: bool = False
    scope_state: str = "idle"
    digital_output_configured: bool = False
    digital_output_running: bool = False
    digital_output_channel: int | None = None
    digital_output_clock_frequency_hz: float | None = None


@dataclass(frozen=True, slots=True)
class CameraRoiReadback:
    horizontal_offset: int
    vertical_offset: int
    horizontal_size: int
    vertical_size: int


@dataclass(frozen=True, slots=True)
class CameraReadback:
    mode: str = "snapshot"
    capture_active: bool = False
    exposure_ms: float | None = None
    buffer_frame_capacity: int | None = None
    readout_time_s: float | None = None
    minimum_trigger_interval_s: float | None = None
    roi: CameraRoiReadback | None = None


@dataclass(frozen=True, slots=True)
class PumpReadback:
    requested_flow_ul_min: float = 0.0
    fill_level_ml: float | None = None
    requested_fill_level_ml: float | None = None
    is_pumping: bool | None = None
    flow_unit: str | None = None
    syringe_name: str | None = None
    syringe_inner_diameter_mm: float | None = None
    syringe_max_piston_stroke_mm: float | None = None
    max_volume_ml: float | None = None
    max_flow_rate_ul_min: float | None = None
    last_recovery_succeeded: bool | None = None


@dataclass(frozen=True, slots=True)
class ValveReadback:
    requested_position: int | None = None
    confirmed_position: int | None = None
    ready: bool | None = None


@dataclass(frozen=True, slots=True)
class TecChannelReadback:
    channel: int
    current_temperature_c: float | None = None
    target_temperature_c: float | None = None
    output_enabled: bool = False
    ready: bool = False
    fault: str | None = None


@dataclass(frozen=True, slots=True)
class TecReadback:
    channels: tuple[TecChannelReadback, ...] = ()


@dataclass(frozen=True, slots=True)
class ZStageReadback:
    closed_loop_confirmation_required: bool | None = None
    closed_loop: bool = False
    position_um: float | None = None


DeviceReadback = Ad2Readback | CameraReadback | PumpReadback | ValveReadback | TecReadback | ZStageReadback


@dataclass(frozen=True, slots=True)
class DeviceStatus:
    device: DeviceId
    connection: ConnectionState = ConnectionState.DISCONNECTED
    busy: bool = False
    configured: bool = False
    active: bool = False
    summary: str = "Not connected"
    readback: DeviceReadback | None = None
    fault: str | None = None
