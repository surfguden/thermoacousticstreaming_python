from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Generic, TypeVar
from uuid import uuid4

from ..domain.models import DeviceId


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DeviceOperation(str, Enum):
    CONNECT = "lifecycle.connect"
    DISCONNECT = "lifecycle.disconnect"
    SAFE_STOP = "lifecycle.safe_stop"
    AD2_WAVEFORM_CONFIGURE = "ad2.waveform.configure"
    AD2_WAVEFORM_START = "ad2.waveform.start"
    AD2_WAVEFORM_STOP = "ad2.waveform.stop"
    AD2_SOFTWARE_TRIGGER = "ad2.software_trigger"
    AD2_SCOPE_CONFIGURE = "ad2.scope.configure"
    AD2_SCOPE_READ = "ad2.scope.read"
    CAMERA_SNAPSHOT_CONFIGURE = "camera.snapshot.configure"
    CAMERA_SNAPSHOT_CAPTURE = "camera.snapshot.capture"
    CAMERA_CAPTURE_STOP = "camera.capture.stop"
    CAMERA_TIMING_READ = "camera.timing.read"
    PUMP_FLOW_SET = "pump.flow.set"
    PUMP_FLOW_STOP = "pump.flow.stop"
    PUMP_FILL_LEVEL_READ = "pump.fill_level.read"
    PUMP_STATUS_READ = "pump.status.read"
    VALVE_POSITION_SET = "valve.position.set"
    VALVE_POSITION_READ = "valve.position.read"
    VALVE_WAIT_READY = "valve.wait_ready"
    TEC_SETPOINTS_APPLY = "tec.setpoints.apply"
    TEC_OUTPUTS_OFF = "tec.outputs.off"
    TEC_STATUS_READ = "tec.status.read"
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


@dataclass(frozen=True, slots=True)
class NoArguments:
    pass


@dataclass(frozen=True, slots=True)
class Ad2ConfigureWaveformArgs:
    frequency_hz: float = 1000.0
    amplitude_v: float = 1.0


@dataclass(frozen=True, slots=True)
class Ad2ConfigureScopeArgs:
    sample_count: int
    channels: tuple[int, ...] = (0,)
    trigger_source: Ad2TriggerSource = Ad2TriggerSource.NONE


@dataclass(frozen=True, slots=True)
class CameraConfigureSnapshotArgs:
    exposure_ms: float | None = None


@dataclass(frozen=True, slots=True)
class PumpSetFlowArgs:
    flow_ul_min: float


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
class ZStageSetPositionArgs:
    position_um: float


@dataclass(frozen=True, slots=True)
class Ad2ScopeReadResult:
    samples_by_channel: dict[int, list[float]]


@dataclass(frozen=True, slots=True)
class CameraSnapshotResult:
    frame: object


@dataclass(frozen=True, slots=True)
class CameraTimingResult:
    buffer_frame_capacity: int
    readout_time_s: float | None
    minimum_trigger_interval_s: float | None


@dataclass(frozen=True, slots=True)
class PumpFillLevelResult:
    fill_level_ml: float


@dataclass(frozen=True, slots=True)
class PumpStatusResult:
    is_pumping: bool


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
    DeviceOperation.AD2_WAVEFORM_CONFIGURE: OperationSpec(_only(DeviceId.AD2), Ad2ConfigureWaveformArgs, _NONE_RESULT),
    DeviceOperation.AD2_WAVEFORM_START: OperationSpec(_only(DeviceId.AD2), NoArguments, _NONE_RESULT),
    DeviceOperation.AD2_WAVEFORM_STOP: OperationSpec(_only(DeviceId.AD2), NoArguments, _NONE_RESULT),
    DeviceOperation.AD2_SOFTWARE_TRIGGER: OperationSpec(_only(DeviceId.AD2), NoArguments, _NONE_RESULT),
    DeviceOperation.AD2_SCOPE_CONFIGURE: OperationSpec(_only(DeviceId.AD2), Ad2ConfigureScopeArgs, _NONE_RESULT),
    DeviceOperation.AD2_SCOPE_READ: OperationSpec(_only(DeviceId.AD2), NoArguments, Ad2ScopeReadResult),
    DeviceOperation.CAMERA_SNAPSHOT_CONFIGURE: OperationSpec(_only(DeviceId.CAMERA), CameraConfigureSnapshotArgs, _NONE_RESULT),
    DeviceOperation.CAMERA_SNAPSHOT_CAPTURE: OperationSpec(_only(DeviceId.CAMERA), NoArguments, CameraSnapshotResult),
    DeviceOperation.CAMERA_CAPTURE_STOP: OperationSpec(_only(DeviceId.CAMERA), NoArguments, _NONE_RESULT),
    DeviceOperation.CAMERA_TIMING_READ: OperationSpec(_only(DeviceId.CAMERA), NoArguments, CameraTimingResult),
    DeviceOperation.PUMP_FLOW_SET: OperationSpec(_only(DeviceId.PUMP), PumpSetFlowArgs, _NONE_RESULT),
    DeviceOperation.PUMP_FLOW_STOP: OperationSpec(_only(DeviceId.PUMP), NoArguments, _NONE_RESULT),
    DeviceOperation.PUMP_FILL_LEVEL_READ: OperationSpec(_only(DeviceId.PUMP), NoArguments, PumpFillLevelResult),
    DeviceOperation.PUMP_STATUS_READ: OperationSpec(_only(DeviceId.PUMP), NoArguments, PumpStatusResult),
    DeviceOperation.VALVE_POSITION_SET: OperationSpec(_only(DeviceId.VALVE), ValveSetPositionArgs, _NONE_RESULT),
    DeviceOperation.VALVE_POSITION_READ: OperationSpec(_only(DeviceId.VALVE), NoArguments, ValvePositionResult),
    DeviceOperation.VALVE_WAIT_READY: OperationSpec(_only(DeviceId.VALVE), ValveWaitReadyArgs, ValveReadyResult),
    DeviceOperation.TEC_SETPOINTS_APPLY: OperationSpec(_only(DeviceId.TEC), TecApplySetpointsArgs, TecStatusResult),
    DeviceOperation.TEC_OUTPUTS_OFF: OperationSpec(_only(DeviceId.TEC), NoArguments, TecStatusResult),
    DeviceOperation.TEC_STATUS_READ: OperationSpec(_only(DeviceId.TEC), TecReadStatusArgs, TecStatusResult),
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
