from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, TypeAlias


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
    DISCONNECTING = "disconnecting"
    ERROR = "error"


class ExperimentState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class ValvePosition(int, Enum):
    POSITION_1 = 1
    POSITION_2 = 2


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


# Backward-compatible name for callers that consumed the first UI increment.
DeviceState = DeviceStatus


@dataclass(frozen=True, slots=True)
class WaveformConfig:
    channel: int = 0
    frequency_hz: float = 1_000.0
    amplitude_v: float = 1.0
    offset_v: float = 0.0
    phase_deg: float = 0.0
    function: str = "sine"

    def __post_init__(self) -> None:
        _bounded("channel", self.channel, 0, 1)
        _bounded("frequency_hz", self.frequency_hz, 0.001, 100_000_000)
        _bounded("amplitude_v", self.amplitude_v, 0, 5)
        _bounded("offset_v", self.offset_v, -5, 5)
        _bounded("phase_deg", self.phase_deg, -360, 360)


@dataclass(frozen=True, slots=True)
class DigitalOutputConfig:
    channel: int = 0
    clock_divider: int = 1
    high_bits: int = 1
    low_bits: int = 1
    output_type: str = "pulse"

    def __post_init__(self) -> None:
        _bounded("channel", self.channel, 0, 15)
        _bounded("clock_divider", self.clock_divider, 1, 2**31 - 1)
        _bounded("high_bits", self.high_bits, 0, 2**31 - 1)
        _bounded("low_bits", self.low_bits, 0, 2**31 - 1)


@dataclass(frozen=True, slots=True)
class ScopeCaptureRequest:
    channels: tuple[int, ...] = (0,)
    sample_frequency_hz: float = 10_000.0
    sample_count: int = 4_096
    range_v: float = 1.0
    offset_v: float = 0.0
    trigger_source: str = "none"

    def __post_init__(self) -> None:
        if not self.channels:
            raise ValueError("At least one scope channel is required")
        if any(channel < 0 for channel in self.channels):
            raise ValueError("Scope channel indices cannot be negative")
        _positive("sample_frequency_hz", self.sample_frequency_hz)
        _bounded("sample_count", self.sample_count, 1, 10_000_000)
        _positive("range_v", self.range_v)


@dataclass(frozen=True, slots=True)
class ScopeCapture:
    samples_by_channel: dict[int, tuple[float, ...]]
    sample_frequency_hz: float


@dataclass(frozen=True, slots=True)
class PumpConfig:
    inner_diameter_mm: float
    piston_stroke_mm: float
    flow_unit: str = "uL/min"

    def __post_init__(self) -> None:
        _positive("inner_diameter_mm", self.inner_diameter_mm)
        _positive("piston_stroke_mm", self.piston_stroke_mm)


@dataclass(frozen=True, slots=True)
class PumpStatus:
    device: DeviceStatus
    fill_volume_ul: float | None = None
    flow_ul_min: float | None = None
    maximum_volume_ul: float | None = None
    referenced: bool = False


@dataclass(frozen=True, slots=True)
class ValveStatus:
    device: DeviceStatus
    position: ValvePosition | None = None


@dataclass(frozen=True, slots=True)
class RegionOfInterest:
    horizontal_offset: int = 0
    vertical_offset: int = 0
    horizontal_size: int = 0
    vertical_size: int = 0


@dataclass(frozen=True, slots=True)
class CameraConfig:
    exposure_ms: float = 1.0
    frame_count: int = 1
    roi: RegionOfInterest | None = None
    global_exposure_trigger: bool = False

    def __post_init__(self) -> None:
        _bounded("exposure_ms", self.exposure_ms, 0.001, 60_000)
        _bounded("frame_count", self.frame_count, 1, 100_000)


@dataclass(frozen=True, slots=True)
class CameraCapabilities:
    buffer_frames: int = 0
    readout_time_s: float | None = None
    minimum_trigger_interval_s: float | None = None


@dataclass(frozen=True, slots=True)
class CaptureRequest:
    frame_count: int
    partial_capture_folder: Path | None = None

    def __post_init__(self) -> None:
        _bounded("frame_count", self.frame_count, 1, 100_000)


@dataclass(frozen=True, slots=True)
class CaptureResult:
    frames: tuple[Any, ...]
    timestamps: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TecChannelStatus:
    channel: int
    current_temperature_c: float | None = None
    target_temperature_c: float | None = None
    output_enabled: bool = False
    ready: bool = False
    fault: str | None = None


@dataclass(frozen=True, slots=True)
class TemperatureSetpoints:
    by_channel_c: dict[int, float]

    def __post_init__(self) -> None:
        if not self.by_channel_c:
            raise ValueError("At least one TEC channel setpoint is required")
        for channel, temperature in self.by_channel_c.items():
            _bounded(f"channel {channel} temperature_c", temperature, -20, 120)


@dataclass(frozen=True, slots=True)
class ZStageCapabilities:
    maximum_travel_um: float | None = None
    minimum_output_voltage_v: float | None = None
    maximum_output_voltage_v: float | None = None
    closed_loop: bool = False


@dataclass(frozen=True, slots=True)
class ConnectDevice:
    device: DeviceId


@dataclass(frozen=True, slots=True)
class DisconnectDevice:
    device: DeviceId


@dataclass(frozen=True, slots=True)
class ConfigureWaveform:
    config: WaveformConfig


@dataclass(frozen=True, slots=True)
class StartWaveform:
    pass


@dataclass(frozen=True, slots=True)
class StopWaveform:
    pass


@dataclass(frozen=True, slots=True)
class TriggerWaveform:
    pass


@dataclass(frozen=True, slots=True)
class ConfigureDigitalOutput:
    config: DigitalOutputConfig


@dataclass(frozen=True, slots=True)
class StartDigitalOutput:
    pass


@dataclass(frozen=True, slots=True)
class StopDigitalOutput:
    pass


@dataclass(frozen=True, slots=True)
class CaptureScope:
    request: ScopeCaptureRequest


@dataclass(frozen=True, slots=True)
class ConfigurePump:
    config: PumpConfig


@dataclass(frozen=True, slots=True)
class ReferencePump:
    pass


@dataclass(frozen=True, slots=True)
class SetPumpFlow:
    flow_ul_min: float

    def __post_init__(self) -> None:
        _bounded("flow_ul_min", self.flow_ul_min, -10_000, 10_000)


@dataclass(frozen=True, slots=True)
class StopPump:
    pass


@dataclass(frozen=True, slots=True)
class MovePumpToVolume:
    volume_ul: float
    flow_ul_min: float

    def __post_init__(self) -> None:
        _positive("volume_ul", self.volume_ul)
        _positive("flow_ul_min", self.flow_ul_min)


@dataclass(frozen=True, slots=True)
class RefillPump:
    flow_ul_min: float | None = None

    def __post_init__(self) -> None:
        if self.flow_ul_min is not None:
            _positive("flow_ul_min", self.flow_ul_min)


@dataclass(frozen=True, slots=True)
class EmptyPump:
    flow_ul_min: float | None = None

    def __post_init__(self) -> None:
        if self.flow_ul_min is not None:
            _positive("flow_ul_min", self.flow_ul_min)


@dataclass(frozen=True, slots=True)
class SetValvePosition:
    position: ValvePosition


@dataclass(frozen=True, slots=True)
class ConfigureCamera:
    config: CameraConfig


@dataclass(frozen=True, slots=True)
class CaptureSnapshot:
    pass


@dataclass(frozen=True, slots=True)
class CaptureCameraSequence:
    request: CaptureRequest


@dataclass(frozen=True, slots=True)
class StopCamera:
    pass


@dataclass(frozen=True, slots=True)
class SetTemperature:
    setpoints: TemperatureSetpoints


@dataclass(frozen=True, slots=True)
class DisableTecOutputs:
    pass


@dataclass(frozen=True, slots=True)
class EnableZStageClosedLoop:
    pass


@dataclass(frozen=True, slots=True)
class MoveZStage:
    position_um: float

    def __post_init__(self) -> None:
        _bounded("position_um", self.position_um, 0, 450)


LabCommand: TypeAlias = (
    ConnectDevice
    | DisconnectDevice
    | ConfigureWaveform
    | StartWaveform
    | StopWaveform
    | TriggerWaveform
    | ConfigureDigitalOutput
    | StartDigitalOutput
    | StopDigitalOutput
    | CaptureScope
    | ConfigurePump
    | ReferencePump
    | SetPumpFlow
    | StopPump
    | MovePumpToVolume
    | RefillPump
    | EmptyPump
    | SetValvePosition
    | ConfigureCamera
    | CaptureSnapshot
    | CaptureCameraSequence
    | StopCamera
    | SetTemperature
    | DisableTecOutputs
    | EnableZStageClosedLoop
    | MoveZStage
)


@dataclass(frozen=True, slots=True)
class ExperimentStep:
    command: LabCommand
    delay_after_s: float = 0.0
    label: str = ""

    def __post_init__(self) -> None:
        if self.delay_after_s < 0:
            raise ValueError("Experiment step delay cannot be negative")


@dataclass(frozen=True, slots=True)
class ExperimentPlan:
    name: str
    steps: tuple[ExperimentStep, ...]

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Experiment name is required")
        if not self.steps:
            raise ValueError("Experiment plan has no steps")


@dataclass(frozen=True, slots=True)
class ExperimentStatus:
    state: ExperimentState = ExperimentState.IDLE
    completed_steps: int = 0
    total_steps: int = 0
    fault: str | None = None


@dataclass(frozen=True, slots=True)
class LabSnapshot:
    mode: OperatingMode
    devices: dict[DeviceId, DeviceStatus]
    experiment: ExperimentStatus = field(default_factory=ExperimentStatus)
    message: str = "Ready"

    @property
    def experiment_state(self) -> ExperimentState:
        return self.experiment.state

    @property
    def experiment_step(self) -> int:
        return self.experiment.completed_steps

    @property
    def experiment_total(self) -> int:
        return self.experiment.total_steps


def command_device(command: LabCommand) -> DeviceId:
    if isinstance(command, (ConnectDevice, DisconnectDevice)):
        return command.device
    if isinstance(command, (ConfigureWaveform, StartWaveform, StopWaveform, TriggerWaveform, ConfigureDigitalOutput, StartDigitalOutput, StopDigitalOutput, CaptureScope)):
        return DeviceId.AD2
    if isinstance(command, (ConfigurePump, ReferencePump, SetPumpFlow, StopPump, MovePumpToVolume, RefillPump, EmptyPump)):
        return DeviceId.PUMP
    if isinstance(command, SetValvePosition):
        return DeviceId.VALVE
    if isinstance(command, (ConfigureCamera, CaptureSnapshot, CaptureCameraSequence, StopCamera)):
        return DeviceId.CAMERA
    if isinstance(command, (SetTemperature, DisableTecOutputs)):
        return DeviceId.TEC
    if isinstance(command, (EnableZStageClosedLoop, MoveZStage)):
        return DeviceId.Z_STAGE
    raise TypeError(f"Unsupported command type: {type(command).__name__}")


def _bounded(name: str, value: float, minimum: float, maximum: float) -> None:
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum:g} and {maximum:g}")


def _positive(name: str, value: float) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be positive")
