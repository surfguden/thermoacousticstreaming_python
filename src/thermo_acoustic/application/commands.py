from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import math
from typing import Any, Generic, TypeVar
from uuid import uuid4

from ..domain.models import DeviceId


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
    CAMERA_SEQUENCE_CONFIGURE = "camera.sequence.configure"
    CAMERA_SEQUENCE_CAPTURE = "camera.sequence.capture"
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


class Ad2DigitalOutputType(str, Enum):
    PULSE = "Pulse"
    CUSTOM = "Custom"
    RANDOM = "Random"


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
class Ad2ConfigureWaveformArgs:
    frequency_hz: float = 1000.0
    amplitude_v: float = 1.0
    trigger: Ad2TriggerSettingsArgs = field(default_factory=Ad2TriggerSettingsArgs)


@dataclass(frozen=True, slots=True)
class Ad2ConfigureScopeArgs:
    sample_count: int
    channels: tuple[int, ...] = (0,)
    trigger_source: Ad2TriggerSource = Ad2TriggerSource.NONE


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


@dataclass(frozen=True, slots=True)
class CameraConfigureExposureArgs:
    exposure_ms: float


@dataclass(frozen=True, slots=True)
class CameraConfigureRoiArgs:
    horizontal_offset: int
    vertical_offset: int
    horizontal_size: int
    vertical_size: int


def _require_finite_nonnegative(name: str, value: float) -> None:
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and non-negative")


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


@dataclass(frozen=True, slots=True)
class PumpSetFillLevelArgs:
    fill_level_ml: float
    flow_rate_ul_min: float | None = None


@dataclass(frozen=True, slots=True)
class PumpConfigureSyringeArgs:
    preset: PumpSyringePreset | None = None
    inner_diameter_mm: float | None = None
    max_piston_stroke_mm: float | None = None


@dataclass(frozen=True, slots=True)
class PumpConfigureFlowUnitArgs:
    unit: PumpFlowUnit


@dataclass(frozen=True, slots=True)
class PumpMoveArgs:
    flow_rate_ul_min: float | None = None
    timeout_s: float = 120.0
    poll_interval_s: float = 0.1

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
class CameraSnapshotResult:
    frame: object


@dataclass(frozen=True, slots=True)
class CameraSequenceResult:
    frames: tuple[object, ...]
    timestamps: tuple[str, ...] = ()


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
    argument_type: type
    result_type: type | tuple[type, ...]


_ALL_DEVICES = frozenset(DeviceId)
_NONE_RESULT = type(None)


def _only(device: DeviceId) -> frozenset[DeviceId]:
    return frozenset({device})

OPERATION_SPECS: dict[DeviceOperation, OperationSpec] = {
    DeviceOperation.CONNECT: OperationSpec(_ALL_DEVICES, NoArguments, _NONE_RESULT),
    DeviceOperation.DISCONNECT: OperationSpec(_ALL_DEVICES, NoArguments, _NONE_RESULT),
    DeviceOperation.SAFE_STOP: OperationSpec(_ALL_DEVICES, NoArguments, _NONE_RESULT),
    DeviceOperation.ABORT_ACTIVE: OperationSpec(_ALL_DEVICES, NoArguments, _NONE_RESULT),
    DeviceOperation.AD2_WAVEFORM_CONFIGURE: OperationSpec(_only(DeviceId.AD2), Ad2ConfigureWaveformArgs, _NONE_RESULT),
    DeviceOperation.AD2_WAVEFORM_START: OperationSpec(_only(DeviceId.AD2), NoArguments, _NONE_RESULT),
    DeviceOperation.AD2_WAVEFORM_STOP: OperationSpec(_only(DeviceId.AD2), NoArguments, _NONE_RESULT),
    DeviceOperation.AD2_SOFTWARE_TRIGGER: OperationSpec(_only(DeviceId.AD2), NoArguments, _NONE_RESULT),
    DeviceOperation.AD2_SCOPE_CONFIGURE: OperationSpec(_only(DeviceId.AD2), Ad2ConfigureScopeArgs, _NONE_RESULT),
    DeviceOperation.AD2_SCOPE_READ: OperationSpec(_only(DeviceId.AD2), NoArguments, Ad2ScopeReadResult),
    DeviceOperation.AD2_DIGITAL_OUTPUT_CONFIGURE: OperationSpec(_only(DeviceId.AD2), Ad2ConfigureDigitalOutputArgs, _NONE_RESULT),
    DeviceOperation.AD2_DIGITAL_OUTPUT_START: OperationSpec(_only(DeviceId.AD2), NoArguments, _NONE_RESULT),
    DeviceOperation.AD2_DIGITAL_OUTPUT_STOP: OperationSpec(_only(DeviceId.AD2), NoArguments, _NONE_RESULT),
    DeviceOperation.AD2_DIGITAL_OUTPUT_RESET: OperationSpec(_only(DeviceId.AD2), NoArguments, _NONE_RESULT),
    DeviceOperation.CAMERA_SNAPSHOT_CONFIGURE: OperationSpec(_only(DeviceId.CAMERA), CameraConfigureSnapshotArgs, _NONE_RESULT),
    DeviceOperation.CAMERA_SNAPSHOT_CAPTURE: OperationSpec(_only(DeviceId.CAMERA), NoArguments, CameraSnapshotResult),
    DeviceOperation.CAMERA_SEQUENCE_CONFIGURE: OperationSpec(_only(DeviceId.CAMERA), CameraConfigureSequenceArgs, _NONE_RESULT),
    DeviceOperation.CAMERA_SEQUENCE_CAPTURE: OperationSpec(_only(DeviceId.CAMERA), NoArguments, CameraSequenceResult),
    DeviceOperation.CAMERA_CAPTURE_STOP: OperationSpec(_only(DeviceId.CAMERA), NoArguments, _NONE_RESULT),
    DeviceOperation.CAMERA_TIMING_READ: OperationSpec(_only(DeviceId.CAMERA), NoArguments, CameraTimingResult),
    DeviceOperation.CAMERA_EXPOSURE_CONFIGURE: OperationSpec(_only(DeviceId.CAMERA), CameraConfigureExposureArgs, CameraExposureResult),
    DeviceOperation.CAMERA_ROI_CONFIGURE: OperationSpec(_only(DeviceId.CAMERA), CameraConfigureRoiArgs, CameraRoiResult),
    DeviceOperation.PUMP_FLOW_SET: OperationSpec(_only(DeviceId.PUMP), PumpSetFlowArgs, _NONE_RESULT),
    DeviceOperation.PUMP_FLOW_STOP: OperationSpec(_only(DeviceId.PUMP), NoArguments, _NONE_RESULT),
    DeviceOperation.PUMP_FILL_LEVEL_READ: OperationSpec(_only(DeviceId.PUMP), NoArguments, PumpFillLevelResult),
    DeviceOperation.PUMP_FILL_LEVEL_SET: OperationSpec(_only(DeviceId.PUMP), PumpSetFillLevelArgs, _NONE_RESULT),
    DeviceOperation.PUMP_STATUS_READ: OperationSpec(_only(DeviceId.PUMP), NoArguments, PumpStatusResult),
    DeviceOperation.PUMP_SYRINGE_CONFIGURE: OperationSpec(_only(DeviceId.PUMP), PumpConfigureSyringeArgs, PumpConfigurationResult),
    DeviceOperation.PUMP_FLOW_UNIT_CONFIGURE: OperationSpec(_only(DeviceId.PUMP), PumpConfigureFlowUnitArgs, PumpConfigurationResult),
    DeviceOperation.PUMP_FAULT_RECOVER: OperationSpec(_only(DeviceId.PUMP), NoArguments, PumpRecoveryResult),
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
    if not isinstance(arguments, spec.argument_type):
        raise TypeError(
            f"{operation.value} requires {spec.argument_type.__name__}, "
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


@dataclass(frozen=True, slots=True)
class CommandEvent:
    request_id: str
    state: str
    device: DeviceId | None
    operation: DeviceOperation
    source: str
    message: str = ""
    result: Any = None


@dataclass(frozen=True, slots=True)
class ConfirmationRequest:
    command: DeviceCommand[Any]
    prompt: str
