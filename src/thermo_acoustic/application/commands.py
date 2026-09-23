from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import math
from pathlib import Path
from typing import Any, Generic, TypeVar
from uuid import uuid4

from ..domain.models import DeviceId
from .configuration import validate_pump_configuration_dir


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DeviceOperation(str, Enum):
    CONNECT = "lifecycle.connect"
    DISCONNECT = "lifecycle.disconnect"
    SAFE_STOP = "lifecycle.safe_stop"
    ABORT_ACTIVE = "lifecycle.abort_active"
    AD2_WAVEFORM_CONFIGURE = "ad2.waveform.configure"
    AD2_WAVEFORM_START = "ad2.waveform.start"
    AD2_WAVEFORM_STOP = "ad2.waveform.stop"
    AD2_SOFTWARE_TRIGGER = "ad2.software_trigger"
    AD2_SCOPE_CONFIGURE = "ad2.scope.configure"
    AD2_SCOPE_READ = "ad2.scope.read"
    AD2_DIGITAL_OUTPUT_CONFIGURE = "ad2.digital_output.configure"
    AD2_DIGITAL_OUTPUT_START = "ad2.digital_output.start"
    AD2_DIGITAL_OUTPUT_STOP = "ad2.digital_output.stop"
    AD2_DIGITAL_OUTPUT_RESET = "ad2.digital_output.reset"
    CAMERA_SNAPSHOT_CONFIGURE = "camera.snapshot.configure"
    CAMERA_SNAPSHOT_CAPTURE = "camera.snapshot.capture"
    CAMERA_CONTINUOUS_CAPTURE = "camera.continuous.capture"
    CAMERA_SEQUENCE_CONFIGURE = "camera.sequence.configure"
    CAMERA_SEQUENCE_CAPTURE = "camera.sequence.capture"
    CAMERA_SEQUENCE_SAVE = "camera.sequence.save"
    CAMERA_CAPTURE_STOP = "camera.capture.stop"
    CAMERA_TIMING_READ = "camera.timing.read"
    CAMERA_EXPOSURE_CONFIGURE = "camera.exposure.configure"
    CAMERA_ROI_CONFIGURE = "camera.roi.configure"
    PUMP_FLOW_SET = "pump.flow.set"
    PUMP_FLOW_STOP = "pump.flow.stop"
    PUMP_FILL_LEVEL_READ = "pump.fill_level.read"
    PUMP_FILL_LEVEL_SET = "pump.fill_level.set"
    PUMP_STATUS_READ = "pump.status.read"
    PUMP_SYRINGE_CONFIGURE = "pump.syringe.configure"
    PUMP_FLOW_UNIT_CONFIGURE = "pump.flow_unit.configure"
    PUMP_FAULT_RECOVER = "pump.fault.recover"
    PUMP_REFILL = "pump.refill"
    PUMP_EMPTY = "pump.empty"
    PUMP_REFERENCE_MOVE = "pump.reference_move"
    VALVE_POSITION_SET = "valve.position.set"
    VALVE_POSITION_READ = "valve.position.read"
    VALVE_WAIT_READY = "valve.wait_ready"
    TEC_SETPOINTS_APPLY = "tec.setpoints.apply"
    TEC_OUTPUTS_OFF = "tec.outputs.off"
    TEC_STATUS_READ = "tec.status.read"
    TEC_WAIT_STABLE = "tec.wait_stable"
    Z_STAGE_CLOSED_LOOP_REQUIREMENT_READ = "z_stage.closed_loop.requirement.read"
    Z_STAGE_CLOSED_LOOP_ENABLE = "z_stage.closed_loop.enable"
    Z_STAGE_POSITION_SET = "z_stage.position.set"
    Z_STAGE_POSITION_READ = "z_stage.position.read"


class Ad2TriggerSource(str, Enum):
    NONE = "trigsrcNone"
    PC = "trigsrcPC"
    DETECTOR_ANALOG_IN = "trigsrcDetectorAnalogIn"
    DETECTOR_DIGITAL_IN = "trigsrcDetectorDigitalIn"
    ANALOG_IN = "trigsrcAnalogIn"
    DIGITAL_IN = "trigsrcDigitalIn"
    DIGITAL_OUT = "trigsrcDigitalOut"
    ANALOG_OUT_1 = "trigsrcAnalogOut1"
    ANALOG_OUT_2 = "trigsrcAnalogOut2"
    ANALOG_OUT_3 = "trigsrcAnalogOut3"
    ANALOG_OUT_4 = "trigsrcAnalogOut4"


class Ad2ScopeTriggerType(str, Enum):
    EDGE = "Edge"
    PULSE = "Pulse"
    TRANSITION = "Transition"


class Ad2ScopeTriggerCondition(str, Enum):
    RISING_POSITIVE = "Rising/Positive"
    FALLING_NEGATIVE = "Falling/Negative"


class Ad2ScopeTriggerFilter(str, Enum):
    DECIMATE = "Decimate"
    AVERAGE = "Average"


class Ad2ScopeTriggerLengthCondition(str, Enum):
    LESS = "Less"
    TIMEOUT = "Timeout"
    MORE = "More"


class Ad2DigitalOutputType(str, Enum):
    PULSE = "Pulse"
    CUSTOM = "Custom"
    RANDOM = "Random"


class Ad2WaveformFunction(str, Enum):
    SINE = "Sine"
    SQUARE = "Square"
    TRIANGLE = "Triangle"
    RAMP_UP = "RampUp"
    RAMP_DOWN = "RampDown"
    DC = "DC"


class Ad2AnalogOutputIdle(str, Enum):
    DISABLED = "Disabled"
    OFFSET = "Offset"
    INITIAL = "Initial"


class CameraMasterPulseMode(str, Enum):
    CONTINUOUS = "continuous"
    START = "start"
    BURST = "burst"


class CameraMasterPulseSource(str, Enum):
    EXTERNAL = "external"
    SOFTWARE = "software"


class CameraTriggerSource(str, Enum):
    INTERNAL = "internal"
    EXTERNAL = "external"
    SOFTWARE = "software"
    MASTERPULSE = "masterpulse"


class CameraTriggerPolarity(str, Enum):
    NEGATIVE = "negative"
    POSITIVE = "positive"


class CameraTriggerActive(str, Enum):
    EDGE = "edge"
    LEVEL = "level"


class CameraSequenceSaveFormat(str, Enum):
    FRAMES = "frames"
    STACKED = "stacked"


class PumpFlowUnit(str, Enum):
    MICROLITRE_PER_MINUTE = "ul/min"
    MILLILITRE_PER_MINUTE = "ml/min"
    MICROLITRE_PER_SECOND = "ul/s"
    MILLILITRE_PER_SECOND = "ml/s"


class PumpSyringePreset(str, Enum):
    BD_1_ML = "BD 1ml"
    BD_5_ML = "BD 5ml"
    BD_10_ML = "BD 10ml"


@dataclass(frozen=True, slots=True)
class NoArguments:
    pass


@dataclass(frozen=True, slots=True)
class PumpConnectArgs:
    configuration_dir: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "configuration_dir", validate_pump_configuration_dir(self.configuration_dir))


@dataclass(frozen=True, slots=True)
class Ad2TriggerSettingsArgs:
    source: Ad2TriggerSource = Ad2TriggerSource.NONE
    wait_s: float = 0.0
    run_s: float = 0.0
    repeat_count: int = 0
    repeat_trigger: bool = False

    def __post_init__(self) -> None:
        _require_finite_nonnegative("wait_s", self.wait_s)
        _require_finite_nonnegative("run_s", self.run_s)
        if self.repeat_count < 0:
            raise ValueError("repeat_count must be non-negative")


@dataclass(frozen=True, slots=True)
class Ad2WaveformChannelArgs:
    channel_index: int
    enabled: bool = True
    function: Ad2WaveformFunction = Ad2WaveformFunction.SINE
    frequency_hz: float = 1000.0
    amplitude_v: float = 1.0
    offset_v: float = 0.0
    symmetry_percent: float = 50.0
    phase_deg: float = 0.0
    fm_enabled: bool = False
    fm_function: Ad2WaveformFunction = Ad2WaveformFunction.SINE
    fm_frequency_hz: float = 1000.0
    fm_modulation_index_percent: float = 0.0
    fm_offset_percent: float = 0.0
    fm_symmetry_percent: float = 50.0
    fm_phase_deg: float = 0.0
    idle_state: Ad2AnalogOutputIdle = Ad2AnalogOutputIdle.INITIAL
    trigger: Ad2TriggerSettingsArgs = field(default_factory=Ad2TriggerSettingsArgs)

    def __post_init__(self) -> None:
        if self.channel_index not in (0, 1):
            raise ValueError("AD2 waveform channel_index must be 0 or 1")
        _require_finite_positive("frequency_hz", self.frequency_hz)
        _require_finite_nonnegative("amplitude_v", self.amplitude_v)
        _require_finite_value("offset_v", self.offset_v)
        _require_percentage("symmetry_percent", self.symmetry_percent)
        _require_finite_value("phase_deg", self.phase_deg)
        _require_finite_positive("fm_frequency_hz", self.fm_frequency_hz)
        _require_finite_value("fm_modulation_index_percent", self.fm_modulation_index_percent)
        _require_finite_value("fm_offset_percent", self.fm_offset_percent)
        _require_percentage("fm_symmetry_percent", self.fm_symmetry_percent)
        _require_finite_value("fm_phase_deg", self.fm_phase_deg)


@dataclass(frozen=True, slots=True)
class Ad2ConfigureWaveformArgs:
    frequency_hz: float = 1000.0
    amplitude_v: float = 1.0
    trigger: Ad2TriggerSettingsArgs = field(default_factory=Ad2TriggerSettingsArgs)
    channels: tuple[Ad2WaveformChannelArgs, ...] = ()

    def __post_init__(self) -> None:
        _require_finite_positive("frequency_hz", self.frequency_hz)
        _require_finite_nonnegative("amplitude_v", self.amplitude_v)
        if self.channels:
            indices = tuple(channel.channel_index for channel in self.channels)
            if len(indices) != 2 or set(indices) != {0, 1}:
                raise ValueError("waveform configuration requires channels 0 and 1 exactly once")

    def resolved_channels(self) -> tuple[Ad2WaveformChannelArgs, ...]:
        if self.channels:
            return tuple(sorted(self.channels, key=lambda channel: channel.channel_index))
        return (
            Ad2WaveformChannelArgs(
                0,
                frequency_hz=self.frequency_hz,
                amplitude_v=self.amplitude_v,
                trigger=self.trigger,
            ),
            Ad2WaveformChannelArgs(1, enabled=False),
        )


@dataclass(frozen=True, slots=True)
class Ad2ScopeChannelArgs:
    channel_index: int
    range_v: float = 5.0
    offset_v: float = 0.0

    def __post_init__(self) -> None:
        if self.channel_index not in (0, 1):
            raise ValueError("scope channel_index must be 0 or 1")
        _require_finite_positive("range_v", self.range_v)
        _require_finite_value("offset_v", self.offset_v)


@dataclass(frozen=True, slots=True)
class Ad2ScopeTriggerArgs:
    source: Ad2TriggerSource = Ad2TriggerSource.NONE
    channel_index: int = 0
    trigger_type: Ad2ScopeTriggerType = Ad2ScopeTriggerType.EDGE
    condition: Ad2ScopeTriggerCondition = Ad2ScopeTriggerCondition.RISING_POSITIVE
    filter: Ad2ScopeTriggerFilter = Ad2ScopeTriggerFilter.DECIMATE
    level_v: float = 0.0
    hysteresis_v: float = 0.1
    length_condition: Ad2ScopeTriggerLengthCondition = Ad2ScopeTriggerLengthCondition.MORE
    length_s: float = 0.0
    holdoff_s: float = 0.0
    auto_timeout_s: float = 0.0

    def __post_init__(self) -> None:
        if self.channel_index not in (0, 1):
            raise ValueError("scope trigger channel_index must be 0 or 1")
        _require_finite_value("level_v", self.level_v)
        for name, value in (
            ("hysteresis_v", self.hysteresis_v),
            ("length_s", self.length_s),
            ("holdoff_s", self.holdoff_s),
            ("auto_timeout_s", self.auto_timeout_s),
        ):
            _require_finite_nonnegative(name, value)


@dataclass(frozen=True, slots=True)
class Ad2ConfigureScopeArgs:
    sample_count: int
    channels: tuple[Ad2ScopeChannelArgs | int, ...] = field(
        default_factory=lambda: (Ad2ScopeChannelArgs(0),)
    )
    trigger_source: Ad2TriggerSource = Ad2TriggerSource.NONE
    sample_frequency_hz: float = 10_000.0
    pretrigger_samples: int = 0
    timeout_s: float = 5.0
    poll_interval_s: float = 0.01
    trigger: Ad2ScopeTriggerArgs | None = None

    def __post_init__(self) -> None:
        if self.sample_count < 1:
            raise ValueError("sample_count must be at least one")
        _require_finite_positive("sample_frequency_hz", self.sample_frequency_hz)
        _require_finite_positive("timeout_s", self.timeout_s)
        _require_finite_positive("poll_interval_s", self.poll_interval_s)
        if self.poll_interval_s > self.timeout_s:
            raise ValueError("poll_interval_s must not exceed timeout_s")
        if not 0 <= self.pretrigger_samples < self.sample_count:
            raise ValueError("pretrigger_samples must be within 0..sample_count-1")
        normalized = tuple(
            item if isinstance(item, Ad2ScopeChannelArgs) else Ad2ScopeChannelArgs(item)
            for item in self.channels
        )
        indices = tuple(item.channel_index for item in normalized)
        if not indices:
            raise ValueError("choose at least one scope channel")
        if len(indices) != len(set(indices)):
            raise ValueError("scope channels must be unique")
        object.__setattr__(self, "channels", normalized)
        trigger = self.trigger or Ad2ScopeTriggerArgs(source=self.trigger_source)
        if self.trigger is not None and self.trigger_source is not Ad2TriggerSource.NONE:
            trigger = Ad2ScopeTriggerArgs(
                source=self.trigger_source,
                channel_index=trigger.channel_index,
                trigger_type=trigger.trigger_type,
                condition=trigger.condition,
                filter=trigger.filter,
                level_v=trigger.level_v,
                hysteresis_v=trigger.hysteresis_v,
                length_condition=trigger.length_condition,
                length_s=trigger.length_s,
                holdoff_s=trigger.holdoff_s,
                auto_timeout_s=trigger.auto_timeout_s,
            )
        object.__setattr__(self, "trigger", trigger)
        object.__setattr__(self, "trigger_source", trigger.source)


@dataclass(frozen=True, slots=True)
class Ad2ConfigureDigitalOutputArgs:
    channel_index: int = 0
    enabled: bool = True
    output_type: Ad2DigitalOutputType = Ad2DigitalOutputType.PULSE
    clock_frequency_hz: float | None = None
    counter_high_bits: int = 1
    counter_low_bits: int = 1
    start_high: bool = True
    bits: tuple[int, ...] = ()
    frame_count: int | None = None
    trigger: Ad2TriggerSettingsArgs = field(default_factory=Ad2TriggerSettingsArgs)


@dataclass(frozen=True, slots=True)
class CameraConfigureSnapshotArgs:
    exposure_ms: float | None = None
    poll_interval_s: float = 0.05

    def __post_init__(self) -> None:
        if self.exposure_ms is not None:
            _require_finite_nonnegative("exposure_ms", self.exposure_ms)
        _require_finite_positive("poll_interval_s", self.poll_interval_s)


@dataclass(frozen=True, slots=True)
class CameraConfigureExposureArgs:
    exposure_ms: float


@dataclass(frozen=True, slots=True)
class CameraConfigureRoiArgs:
    horizontal_offset: int
    vertical_offset: int
    horizontal_size: int
    vertical_size: int


@dataclass(frozen=True, slots=True)
class CameraSaveSequenceArgs:
    folder: str
    format: CameraSequenceSaveFormat = CameraSequenceSaveFormat.FRAMES

    def __post_init__(self) -> None:
        if not self.folder.strip():
            raise ValueError("camera sequence save folder must not be empty")


def _require_finite_nonnegative(name: str, value: float) -> None:
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and non-negative")


def _require_finite_value(name: str, value: float) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")


def _require_percentage(name: str, value: float) -> None:
    if not math.isfinite(value) or not 0 <= value <= 100:
        raise ValueError(f"{name} must be finite and within 0..100")


def _require_finite_positive(name: str, value: float) -> None:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")


@dataclass(frozen=True, slots=True)
class CameraSequenceTriggerArgs:
    source: CameraTriggerSource = CameraTriggerSource.INTERNAL
    polarity: CameraTriggerPolarity = CameraTriggerPolarity.POSITIVE
    active: CameraTriggerActive = CameraTriggerActive.EDGE
    trigger_times: int = 1
    delay_s: float = 0.0
    masterpulse_mode: CameraMasterPulseMode = CameraMasterPulseMode.CONTINUOUS
    masterpulse_source: CameraMasterPulseSource = CameraMasterPulseSource.SOFTWARE
    masterpulse_interval_s: float = 0.01
    masterpulse_burst_times: int = 1
    global_exposure: bool | None = None

    def __post_init__(self) -> None:
        if not 1 <= self.trigger_times <= 10_000:
            raise ValueError("trigger_times must be within 1..10000")
        if not math.isfinite(self.delay_s) or not 0 <= self.delay_s <= 10.000002:
            raise ValueError("delay_s must be finite and within 0..10.000002")
        if not math.isfinite(self.masterpulse_interval_s) or not 0.000005 <= self.masterpulse_interval_s <= 10:
            raise ValueError("masterpulse_interval_s must be finite and within 0.000005..10")
        if not 1 <= self.masterpulse_burst_times <= 65_535:
            raise ValueError("masterpulse_burst_times must be within 1..65535")


@dataclass(frozen=True, slots=True)
class CameraConfigureSequenceArgs:
    frame_count: int
    exposure_ms: float | None = None
    frame_timeout_s: float = 30.0
    poll_interval_s: float = 0.05
    trigger: CameraSequenceTriggerArgs | None = None

    def __post_init__(self) -> None:
        if self.frame_count <= 0:
            raise ValueError("frame_count must be positive")
        if self.exposure_ms is not None:
            _require_finite_nonnegative("exposure_ms", self.exposure_ms)
        _require_finite_positive("frame_timeout_s", self.frame_timeout_s)
        _require_finite_positive("poll_interval_s", self.poll_interval_s)
        if self.poll_interval_s > self.frame_timeout_s:
            raise ValueError("poll_interval_s must not exceed frame_timeout_s")


@dataclass(frozen=True, slots=True)
class PumpSetFlowArgs:
    flow_ul_min: float
    unit_index: int = 0


@dataclass(frozen=True, slots=True)
class PumpSetFillLevelArgs:
    fill_level_ml: float
    flow_rate_ul_min: float | None = None
    unit_index: int = 0


@dataclass(frozen=True, slots=True)
class PumpConfigureSyringeArgs:
    preset: PumpSyringePreset | None = None
    inner_diameter_mm: float | None = None
    max_piston_stroke_mm: float | None = None
    unit_index: int = 0


@dataclass(frozen=True, slots=True)
class PumpConfigureFlowUnitArgs:
    unit: PumpFlowUnit
    unit_index: int = 0


@dataclass(frozen=True, slots=True)
class PumpUnitArgs:
    unit_index: int = 0


@dataclass(frozen=True, slots=True)
class PumpMoveArgs:
    flow_rate_ul_min: float | None = None
    timeout_s: float = 120.0
    poll_interval_s: float = 0.1
    unit_index: int = 0

    def __post_init__(self) -> None:
        if self.flow_rate_ul_min is not None and not math.isfinite(self.flow_rate_ul_min):
            raise ValueError("flow_rate_ul_min must be finite")
        _require_finite_positive("timeout_s", self.timeout_s)
        _require_finite_positive("poll_interval_s", self.poll_interval_s)
        if self.poll_interval_s > self.timeout_s:
            raise ValueError("poll_interval_s must not exceed timeout_s")


@dataclass(frozen=True, slots=True)
class PumpReferenceMoveArgs:
    timeout_s: float = 60.0
    poll_interval_s: float = 0.1
    unit_index: int = 0

    def __post_init__(self) -> None:
        _require_finite_positive("timeout_s", self.timeout_s)
        _require_finite_positive("poll_interval_s", self.poll_interval_s)
        if self.poll_interval_s > self.timeout_s:
            raise ValueError("poll_interval_s must not exceed timeout_s")


@dataclass(frozen=True, slots=True)
class ValveSetPositionArgs:
    position: int


@dataclass(frozen=True, slots=True)
class ValveWaitReadyArgs:
    timeout_s: float = 1.0
    poll_interval_s: float = 0.05


@dataclass(frozen=True, slots=True)
class TecApplySetpointsArgs:
    target_temperature_c: float | dict[int, float]
    channels: tuple[int, ...] | None = None


@dataclass(frozen=True, slots=True)
class TecReadStatusArgs:
    channels: tuple[int, ...] | None = None


@dataclass(frozen=True, slots=True)
class TecWaitStableArgs:
    target_temperature_c: float | dict[int, float]
    tolerance_c: float
    min_settle_s: float
    max_wait_s: float
    poll_interval_s: float = 1.0
    channels: tuple[int, ...] | None = None

    def __post_init__(self) -> None:
        targets = tuple(
            self.target_temperature_c.values()
            if isinstance(self.target_temperature_c, dict)
            else (self.target_temperature_c,)
        )
        if not targets or any(not math.isfinite(value) for value in targets):
            raise ValueError("target_temperature_c values must be finite")
        _require_finite_nonnegative("tolerance_c", self.tolerance_c)
        _require_finite_nonnegative("min_settle_s", self.min_settle_s)
        _require_finite_positive("max_wait_s", self.max_wait_s)
        _require_finite_positive("poll_interval_s", self.poll_interval_s)
        if self.poll_interval_s > self.max_wait_s:
            raise ValueError("poll_interval_s must not exceed max_wait_s")


@dataclass(frozen=True, slots=True)
class ZStageSetPositionArgs:
    position_um: float


@dataclass(frozen=True, slots=True)
class Ad2ScopeReadResult:
    samples_by_channel: dict[int, list[float]]


@dataclass(frozen=True, slots=True)
class Ad2ScopeAppliedResult:
    sample_count: int
    sample_frequency_hz: float
    pretrigger_samples: int
    channels: tuple[Ad2ScopeChannelArgs, ...]
    trigger: Ad2ScopeTriggerArgs
    evidence_scope: str = "SDK_REPORTED_CONFIGURATION_NOT_MEASURED_INPUT"


@dataclass(frozen=True, slots=True)
class Ad2WaveformAppliedResult:
    channels: tuple[Ad2WaveformChannelArgs, ...]
    running: bool = False
    evidence_scope: str = "SDK_REPORTED_CONFIGURATION_NOT_MEASURED_OUTPUT"


@dataclass(frozen=True, slots=True)
class CameraSnapshotResult:
    frame: object


@dataclass(frozen=True, slots=True)
class CameraSequenceResult:
    frames: tuple[object, ...]
    timestamps: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CameraFrameProgress:
    frame: object
    captured_frame_count: int
    requested_frame_count: int | None = None
    mode: str = "continuous"


@dataclass(frozen=True, slots=True)
class CameraSequenceSaveResult:
    folder: str
    format: CameraSequenceSaveFormat
    frame_count: int


@dataclass(frozen=True, slots=True)
class CameraTimingResult:
    buffer_frame_capacity: int
    readout_time_s: float | None
    minimum_trigger_interval_s: float | None


@dataclass(frozen=True, slots=True)
class CameraExposureResult:
    exposure_ms: float


@dataclass(frozen=True, slots=True)
class CameraRoiResult:
    horizontal_offset: int
    vertical_offset: int
    horizontal_size: int
    vertical_size: int


@dataclass(frozen=True, slots=True)
class PumpFillLevelResult:
    fill_level_ml: float


@dataclass(frozen=True, slots=True)
class PumpStatusResult:
    is_pumping: bool


@dataclass(frozen=True, slots=True)
class PumpConfigurationResult:
    flow_unit: PumpFlowUnit | None
    max_volume_ml: float | None
    max_flow_rate_ul_min: float | None


@dataclass(frozen=True, slots=True)
class PumpRecoveryResult:
    recovered: bool


@dataclass(frozen=True, slots=True)
class PumpMovementResult:
    fill_level_ml: float | None = None
    referenced: bool = False


@dataclass(frozen=True, slots=True)
class ValvePositionResult:
    position: int


@dataclass(frozen=True, slots=True)
class ValveReadyResult:
    ready: bool
    confirmed_position: int | None = None


@dataclass(frozen=True, slots=True)
class TecChannelStatusResult:
    channel: int
    current_temperature_c: float | None
    target_temperature_c: float | None
    output_enabled: bool
    ready: bool
    fault: str | None


@dataclass(frozen=True, slots=True)
class TecStatusResult:
    channels: tuple[TecChannelStatusResult, ...]


@dataclass(frozen=True, slots=True)
class ZStageClosedLoopRequirementResult:
    confirmation_required: bool


@dataclass(frozen=True, slots=True)
class ZStagePositionResult:
    position_um: float


@dataclass(frozen=True, slots=True)
class OperationSpec:
    devices: frozenset[DeviceId]
    argument_type: type | tuple[type, ...]
    result_type: type | tuple[type, ...]


_ALL_DEVICES = frozenset(DeviceId)
_NONE_RESULT = type(None)


def _only(device: DeviceId) -> frozenset[DeviceId]:
    return frozenset({device})

OPERATION_SPECS: dict[DeviceOperation, OperationSpec] = {
    DeviceOperation.CONNECT: OperationSpec(_ALL_DEVICES, (NoArguments, PumpConnectArgs), _NONE_RESULT),
    DeviceOperation.DISCONNECT: OperationSpec(_ALL_DEVICES, NoArguments, _NONE_RESULT),
    DeviceOperation.SAFE_STOP: OperationSpec(_ALL_DEVICES, NoArguments, _NONE_RESULT),
    DeviceOperation.ABORT_ACTIVE: OperationSpec(_ALL_DEVICES, NoArguments, _NONE_RESULT),
    DeviceOperation.AD2_WAVEFORM_CONFIGURE: OperationSpec(_only(DeviceId.AD2), Ad2ConfigureWaveformArgs, Ad2WaveformAppliedResult),
    DeviceOperation.AD2_WAVEFORM_START: OperationSpec(_only(DeviceId.AD2), NoArguments, _NONE_RESULT),
    DeviceOperation.AD2_WAVEFORM_STOP: OperationSpec(_only(DeviceId.AD2), NoArguments, _NONE_RESULT),
    DeviceOperation.AD2_SOFTWARE_TRIGGER: OperationSpec(_only(DeviceId.AD2), NoArguments, _NONE_RESULT),
    DeviceOperation.AD2_SCOPE_CONFIGURE: OperationSpec(_only(DeviceId.AD2), Ad2ConfigureScopeArgs, Ad2ScopeAppliedResult),
    DeviceOperation.AD2_SCOPE_READ: OperationSpec(_only(DeviceId.AD2), NoArguments, Ad2ScopeReadResult),
    DeviceOperation.AD2_DIGITAL_OUTPUT_CONFIGURE: OperationSpec(_only(DeviceId.AD2), Ad2ConfigureDigitalOutputArgs, _NONE_RESULT),
    DeviceOperation.AD2_DIGITAL_OUTPUT_START: OperationSpec(_only(DeviceId.AD2), NoArguments, _NONE_RESULT),
    DeviceOperation.AD2_DIGITAL_OUTPUT_STOP: OperationSpec(_only(DeviceId.AD2), NoArguments, _NONE_RESULT),
    DeviceOperation.AD2_DIGITAL_OUTPUT_RESET: OperationSpec(_only(DeviceId.AD2), NoArguments, _NONE_RESULT),
    DeviceOperation.CAMERA_SNAPSHOT_CONFIGURE: OperationSpec(_only(DeviceId.CAMERA), CameraConfigureSnapshotArgs, _NONE_RESULT),
    DeviceOperation.CAMERA_SNAPSHOT_CAPTURE: OperationSpec(_only(DeviceId.CAMERA), (NoArguments, CameraConfigureSnapshotArgs), CameraSnapshotResult),
    DeviceOperation.CAMERA_CONTINUOUS_CAPTURE: OperationSpec(_only(DeviceId.CAMERA), CameraConfigureSnapshotArgs, _NONE_RESULT),
    DeviceOperation.CAMERA_SEQUENCE_CONFIGURE: OperationSpec(_only(DeviceId.CAMERA), CameraConfigureSequenceArgs, _NONE_RESULT),
    DeviceOperation.CAMERA_SEQUENCE_CAPTURE: OperationSpec(_only(DeviceId.CAMERA), (NoArguments, CameraConfigureSequenceArgs), CameraSequenceResult),
    DeviceOperation.CAMERA_SEQUENCE_SAVE: OperationSpec(_only(DeviceId.CAMERA), CameraSaveSequenceArgs, CameraSequenceSaveResult),
    DeviceOperation.CAMERA_CAPTURE_STOP: OperationSpec(_only(DeviceId.CAMERA), NoArguments, _NONE_RESULT),
    DeviceOperation.CAMERA_TIMING_READ: OperationSpec(_only(DeviceId.CAMERA), NoArguments, CameraTimingResult),
    DeviceOperation.CAMERA_EXPOSURE_CONFIGURE: OperationSpec(_only(DeviceId.CAMERA), CameraConfigureExposureArgs, CameraExposureResult),
    DeviceOperation.CAMERA_ROI_CONFIGURE: OperationSpec(_only(DeviceId.CAMERA), CameraConfigureRoiArgs, CameraRoiResult),
    DeviceOperation.PUMP_FLOW_SET: OperationSpec(_only(DeviceId.PUMP), PumpSetFlowArgs, _NONE_RESULT),
    DeviceOperation.PUMP_FLOW_STOP: OperationSpec(_only(DeviceId.PUMP), (NoArguments, PumpUnitArgs), _NONE_RESULT),
    DeviceOperation.PUMP_FILL_LEVEL_READ: OperationSpec(_only(DeviceId.PUMP), (NoArguments, PumpUnitArgs), PumpFillLevelResult),
    DeviceOperation.PUMP_FILL_LEVEL_SET: OperationSpec(_only(DeviceId.PUMP), PumpSetFillLevelArgs, _NONE_RESULT),
    DeviceOperation.PUMP_STATUS_READ: OperationSpec(_only(DeviceId.PUMP), (NoArguments, PumpUnitArgs), PumpStatusResult),
    DeviceOperation.PUMP_SYRINGE_CONFIGURE: OperationSpec(_only(DeviceId.PUMP), PumpConfigureSyringeArgs, PumpConfigurationResult),
    DeviceOperation.PUMP_FLOW_UNIT_CONFIGURE: OperationSpec(_only(DeviceId.PUMP), PumpConfigureFlowUnitArgs, PumpConfigurationResult),
    DeviceOperation.PUMP_FAULT_RECOVER: OperationSpec(_only(DeviceId.PUMP), (NoArguments, PumpUnitArgs), PumpRecoveryResult),
    DeviceOperation.PUMP_REFILL: OperationSpec(_only(DeviceId.PUMP), PumpMoveArgs, PumpMovementResult),
    DeviceOperation.PUMP_EMPTY: OperationSpec(_only(DeviceId.PUMP), PumpMoveArgs, PumpMovementResult),
    DeviceOperation.PUMP_REFERENCE_MOVE: OperationSpec(_only(DeviceId.PUMP), PumpReferenceMoveArgs, PumpMovementResult),
    DeviceOperation.VALVE_POSITION_SET: OperationSpec(_only(DeviceId.VALVE), ValveSetPositionArgs, _NONE_RESULT),
    DeviceOperation.VALVE_POSITION_READ: OperationSpec(_only(DeviceId.VALVE), NoArguments, ValvePositionResult),
    DeviceOperation.VALVE_WAIT_READY: OperationSpec(_only(DeviceId.VALVE), ValveWaitReadyArgs, ValveReadyResult),
    DeviceOperation.TEC_SETPOINTS_APPLY: OperationSpec(_only(DeviceId.TEC), TecApplySetpointsArgs, TecStatusResult),
    DeviceOperation.TEC_OUTPUTS_OFF: OperationSpec(_only(DeviceId.TEC), NoArguments, TecStatusResult),
    DeviceOperation.TEC_STATUS_READ: OperationSpec(_only(DeviceId.TEC), TecReadStatusArgs, TecStatusResult),
    DeviceOperation.TEC_WAIT_STABLE: OperationSpec(_only(DeviceId.TEC), TecWaitStableArgs, TecStatusResult),
    DeviceOperation.Z_STAGE_CLOSED_LOOP_REQUIREMENT_READ: OperationSpec(_only(DeviceId.Z_STAGE), NoArguments, ZStageClosedLoopRequirementResult),
    DeviceOperation.Z_STAGE_CLOSED_LOOP_ENABLE: OperationSpec(_only(DeviceId.Z_STAGE), NoArguments, _NONE_RESULT),
    DeviceOperation.Z_STAGE_POSITION_SET: OperationSpec(_only(DeviceId.Z_STAGE), ZStageSetPositionArgs, ZStagePositionResult),
    DeviceOperation.Z_STAGE_POSITION_READ: OperationSpec(_only(DeviceId.Z_STAGE), NoArguments, ZStagePositionResult),
}


def validate_command(device: DeviceId, operation: DeviceOperation, arguments: object) -> None:
    if not isinstance(operation, DeviceOperation):
        raise TypeError("operation must be a DeviceOperation")
    spec = OPERATION_SPECS[operation]
    if device not in spec.devices:
        raise ValueError(f"{operation.value} is not valid for {device.value}")
    if operation is DeviceOperation.CONNECT and isinstance(arguments, PumpConnectArgs) and device is not DeviceId.PUMP:
        raise ValueError("PumpConnectArgs is only valid for the pump")
    if not isinstance(arguments, spec.argument_type):
        expected = (
            spec.argument_type.__name__
            if isinstance(spec.argument_type, type)
            else "/".join(kind.__name__ for kind in spec.argument_type)
        )
        raise TypeError(
            f"{operation.value} requires {expected}, "
            f"got {type(arguments).__name__}"
        )


ArgumentsT = TypeVar("ArgumentsT")
ResultT = TypeVar("ResultT")


@dataclass(frozen=True, slots=True)
class DeviceCommand(Generic[ArgumentsT]):
    device: DeviceId
    operation: DeviceOperation
    arguments: ArgumentsT = field(default_factory=NoArguments)
    request_id: str = field(default_factory=lambda: uuid4().hex[:12])
    source: str = "ui"
    received_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        validate_command(self.device, self.operation, self.arguments)


@dataclass(frozen=True, slots=True)
class CommandResult(Generic[ResultT]):
    request_id: str
    device: DeviceId | None
    operation: DeviceOperation
    ok: bool
    value: ResultT | None = None
    error: str | None = None
    command: DeviceCommand[Any] | None = None


@dataclass(frozen=True, slots=True)
class CommandEvent:
    request_id: str
    state: str
    device: DeviceId | None
    operation: DeviceOperation
    source: str
    message: str = ""
    result: Any = None
    arguments: Any = None
    timestamp: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class ConfirmationRequest:
    command: DeviceCommand[Any]
    prompt: str
