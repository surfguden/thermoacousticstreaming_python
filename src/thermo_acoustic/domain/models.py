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
    DeviceId.AD2: "Analog Discovery 2",
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
class Ad2WaveformChannelReadback:
    channel_index: int
    enabled: bool
    function: str
    frequency_hz: float
    amplitude_v: float
    offset_v: float
    symmetry_percent: float
    phase_deg: float
    fm_enabled: bool
    fm_function: str
    fm_frequency_hz: float
    fm_modulation_index_percent: float
    fm_offset_percent: float
    fm_symmetry_percent: float
    fm_phase_deg: float
    idle_state: str
    trigger_source: str
    trigger_wait_s: float
    trigger_run_s: float
    trigger_repeat_count: int
    trigger_repeat: bool


@dataclass(frozen=True, slots=True)
class FloatRange:
    minimum: float
    maximum: float
    step: float | None = None


@dataclass(frozen=True, slots=True)
class IntegerRange:
    minimum: int
    maximum: int
    increment: int = 1


@dataclass(frozen=True, slots=True)
class Ad2WaveformNodeCapabilities:
    functions: tuple[str, ...]
    frequency_hz: FloatRange
    amplitude: FloatRange
    offset: FloatRange
    symmetry_percent: FloatRange
    phase_deg: FloatRange


@dataclass(frozen=True, slots=True)
class Ad2WaveformChannelCapabilities:
    channel_index: int
    carrier: Ad2WaveformNodeCapabilities
    fm: Ad2WaveformNodeCapabilities
    wait_s: FloatRange
    run_s: FloatRange
    repeat_count: IntegerRange


@dataclass(frozen=True, slots=True)
class Ad2ScopeCapabilities:
    sample_frequency_hz: FloatRange
    sample_count: IntegerRange
    input_ranges_v: tuple[float, ...]
    input_offset_v: FloatRange
    trigger_channel: IntegerRange
    trigger_level_v: FloatRange
    trigger_hysteresis_v: FloatRange
    trigger_holdoff_s: FloatRange
    trigger_auto_timeout_s: FloatRange


@dataclass(frozen=True, slots=True)
class Ad2DigitalOutputCapabilities:
    channel_count: int
    clock_frequency_hz: FloatRange
    counter_bits: IntegerRange
    custom_data_bits_max: int
    wait_s: FloatRange
    run_s: FloatRange
    repeat_count: IntegerRange


@dataclass(frozen=True, slots=True)
class Ad2Capabilities:
    waveform_channels: tuple[Ad2WaveformChannelCapabilities, ...]
    scope: Ad2ScopeCapabilities
    digital_output: Ad2DigitalOutputCapabilities


@dataclass(frozen=True, slots=True)
class Ad2Readback:
    waveform_frequency_hz: float | None = None
    waveform_amplitude_v: float | None = None
    waveform_running: bool = False
    waveform_channels: tuple[Ad2WaveformChannelReadback, ...] = ()
    scope_state: str = "idle"
    digital_output_configured: bool = False
    digital_output_running: bool = False
    digital_output_channel: int | None = None
    digital_output_clock_frequency_hz: float | None = None
    capabilities: Ad2Capabilities | None = None


@dataclass(frozen=True, slots=True)
class CameraRoiReadback:
    horizontal_offset: int
    vertical_offset: int
    horizontal_size: int
    vertical_size: int


@dataclass(frozen=True, slots=True)
class CameraRoiLimitsReadback:
    horizontal_offset: IntegerRange
    vertical_offset: IntegerRange
    horizontal_size: IntegerRange
    vertical_size: IntegerRange


@dataclass(frozen=True, slots=True)
class CameraReadback:
    mode: str = "snapshot"
    capture_active: bool = False
    exposure_ms: float | None = None
    buffer_frame_capacity: int | None = None
    readout_time_s: float | None = None
    minimum_trigger_interval_s: float | None = None
    roi: CameraRoiReadback | None = None
    roi_limits: CameraRoiLimitsReadback | None = None
    sequence_frame_count: int | None = None
    captured_frame_count: int = 0


@dataclass(frozen=True, slots=True)
class PumpUnitReadback:
    unit_index: int
    fill_level_ml: float | None = None
    current_flow_ul_min: float = 0.0
    is_pumping: bool | None = None
    max_volume_ml: float | None = None
    max_flow_rate_ul_min: float | None = None
    syringe_name: str | None = None


@dataclass(frozen=True, slots=True)
class PumpReadback:
    units: tuple[PumpUnitReadback, ...] = ()
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
    movement: str | None = None
    referenced: bool | None = None


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
