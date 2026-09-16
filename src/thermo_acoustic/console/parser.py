from __future__ import annotations

import shlex

from ..application.commands import (
    Ad2ConfigureDigitalOutputArgs,
    Ad2DigitalOutputType,
    CameraConfigureExposureArgs,
    CameraConfigureRoiArgs,
    CameraConfigureSnapshotArgs,
    CameraConfigureSequenceArgs,
    DeviceCommand,
    DeviceOperation,
    PumpSetFlowArgs,
    PumpConfigureFlowUnitArgs,
    PumpConfigureSyringeArgs,
    PumpFlowUnit,
    PumpSetFillLevelArgs,
    PumpMoveArgs,
    PumpReferenceMoveArgs,
    PumpSyringePreset,
    TecApplySetpointsArgs,
    TecReadStatusArgs,
    TecWaitStableArgs,
    ValveSetPositionArgs,
    ValveWaitReadyArgs,
    ZStageSetPositionArgs,
)
from ..domain.models import DeviceId


_DEVICES = {device.value: device for device in DeviceId}
_SYRINGE_PRESETS = {
    "bd-1ml": PumpSyringePreset.BD_1_ML,
    "bd-5ml": PumpSyringePreset.BD_5_ML,
    "bd-10ml": PumpSyringePreset.BD_10_ML,
}


def help_text() -> str:
    return (
        "status | devices | connect DEVICE | disconnect DEVICE | abort DEVICE | "
        "pump set-flow UL_MIN | pump stop | pump read-fill-level | pump read-status | "
        "pump set-fill-level ML [UL_MIN] | pump configure-syringe bd-1ml|bd-5ml|bd-10ml | "
        "pump configure-syringe custom DIAMETER_MM STROKE_MM | "
        "pump configure-flow-unit ul/min|ml/min|ul/s|ml/s | pump recover-fault | "
        "pump refill [UL_MIN] | pump empty [UL_MIN] | pump reference-move | "
        "valve set-position 1|2 | valve read-position | valve wait-ready | "
        "camera configure-snapshot [EXPOSURE_MS] | camera snapshot | camera read-timing | "
        "camera configure-sequence FRAMES [EXPOSURE_MS] | camera sequence | "
        "camera set-exposure EXPOSURE_MS | camera set-roi X Y WIDTH HEIGHT | "
        "ad2 configure-do CHANNEL FREQUENCY_HZ [BIT_PATTERN] | ad2 start-do|stop-do|reset-do | "
        "tec set-temperature C | tec read-status | tec wait-stable C TOLERANCE SETTLE_S MAX_WAIT_S | tec outputs-off | "
        "z-stage check-closed-loop | z-stage enable-closed-loop | "
        "z-stage move UM | z-stage read-position | quit"
    )


def parse_command(line: str, *, source: str = "console") -> DeviceCommand | str | None:
    words = shlex.split(line.strip())
    if not words:
        return None
    if words[0] in ("help", "status", "devices", "quit"):
        return words[0]
    if words[0] in ("connect", "disconnect") and len(words) == 2 and words[1] in _DEVICES:
        operation = (
            DeviceOperation.CONNECT if words[0] == "connect" else DeviceOperation.DISCONNECT
        )
        return DeviceCommand(_DEVICES[words[1]], operation, source=source)
    if words[0] == "abort" and len(words) == 2 and words[1] in _DEVICES:
        return DeviceCommand(
            _DEVICES[words[1]], DeviceOperation.ABORT_ACTIVE, source=source
        )
    if len(words) == 3 and words[:2] == ["pump", "set-flow"]:
        return DeviceCommand(
            DeviceId.PUMP,
            DeviceOperation.PUMP_FLOW_SET,
            PumpSetFlowArgs(float(words[2])),
            source=source,
        )
    if words == ["pump", "stop"]:
        return DeviceCommand(DeviceId.PUMP, DeviceOperation.PUMP_FLOW_STOP, source=source)
    if words == ["pump", "read-fill-level"]:
        return DeviceCommand(DeviceId.PUMP, DeviceOperation.PUMP_FILL_LEVEL_READ, source=source)
    if words == ["pump", "read-status"]:
        return DeviceCommand(DeviceId.PUMP, DeviceOperation.PUMP_STATUS_READ, source=source)
    if words[:2] == ["pump", "set-fill-level"] and len(words) in (3, 4):
        flow_rate = None if len(words) == 3 else float(words[3])
        return DeviceCommand(
            DeviceId.PUMP,
            DeviceOperation.PUMP_FILL_LEVEL_SET,
            PumpSetFillLevelArgs(float(words[2]), flow_rate),
            source=source,
        )
    if words[:2] == ["pump", "configure-syringe"] and len(words) == 3:
        preset = _SYRINGE_PRESETS.get(words[2].lower())
        if preset is None:
            raise ValueError(f"Unknown syringe preset: {words[2]}")
        return DeviceCommand(
            DeviceId.PUMP,
            DeviceOperation.PUMP_SYRINGE_CONFIGURE,
            PumpConfigureSyringeArgs(preset=preset),
            source=source,
        )
    if words[:3] == ["pump", "configure-syringe", "custom"] and len(words) == 5:
        return DeviceCommand(
            DeviceId.PUMP,
            DeviceOperation.PUMP_SYRINGE_CONFIGURE,
            PumpConfigureSyringeArgs(
                inner_diameter_mm=float(words[3]),
                max_piston_stroke_mm=float(words[4]),
            ),
            source=source,
        )
    if words[:2] == ["pump", "configure-flow-unit"] and len(words) == 3:
        return DeviceCommand(
            DeviceId.PUMP,
            DeviceOperation.PUMP_FLOW_UNIT_CONFIGURE,
            PumpConfigureFlowUnitArgs(PumpFlowUnit(words[2].lower())),
            source=source,
        )
    if words == ["pump", "recover-fault"]:
        return DeviceCommand(DeviceId.PUMP, DeviceOperation.PUMP_FAULT_RECOVER, source=source)
    if words[:2] in (["pump", "refill"], ["pump", "empty"]) and len(words) in (2, 3):
        flow_rate = None if len(words) == 2 else float(words[2])
        operation = (
            DeviceOperation.PUMP_REFILL
            if words[1] == "refill"
            else DeviceOperation.PUMP_EMPTY
        )
        return DeviceCommand(
            DeviceId.PUMP, operation, PumpMoveArgs(flow_rate), source=source
        )
    if words == ["pump", "reference-move"]:
        return DeviceCommand(
            DeviceId.PUMP,
            DeviceOperation.PUMP_REFERENCE_MOVE,
            PumpReferenceMoveArgs(),
            source=source,
        )
    if len(words) == 3 and words[:2] == ["valve", "set-position"]:
        return DeviceCommand(
            DeviceId.VALVE,
            DeviceOperation.VALVE_POSITION_SET,
            ValveSetPositionArgs(int(words[2])),
            source=source,
        )
    if words == ["valve", "read-position"]:
        return DeviceCommand(DeviceId.VALVE, DeviceOperation.VALVE_POSITION_READ, source=source)
    if words[:2] == ["valve", "wait-ready"] and len(words) in (2, 3):
        args = ValveWaitReadyArgs() if len(words) == 2 else ValveWaitReadyArgs(float(words[2]))
        return DeviceCommand(DeviceId.VALVE, DeviceOperation.VALVE_WAIT_READY, args, source=source)
    if words == ["camera", "snapshot"]:
        return DeviceCommand(DeviceId.CAMERA, DeviceOperation.CAMERA_SNAPSHOT_CAPTURE, source=source)
    if words[:2] == ["camera", "configure-snapshot"] and len(words) in (2, 3):
        exposure = None if len(words) == 2 else float(words[2])
        return DeviceCommand(
            DeviceId.CAMERA,
            DeviceOperation.CAMERA_SNAPSHOT_CONFIGURE,
            CameraConfigureSnapshotArgs(exposure),
            source=source,
        )
    if words[:2] == ["camera", "configure-sequence"] and len(words) in (3, 4):
        exposure = None if len(words) == 3 else float(words[3])
        return DeviceCommand(
            DeviceId.CAMERA,
            DeviceOperation.CAMERA_SEQUENCE_CONFIGURE,
            CameraConfigureSequenceArgs(int(words[2]), exposure),
            source=source,
        )
    if words == ["camera", "sequence"]:
        return DeviceCommand(
            DeviceId.CAMERA, DeviceOperation.CAMERA_SEQUENCE_CAPTURE, source=source
        )
    if words == ["camera", "read-timing"]:
        return DeviceCommand(DeviceId.CAMERA, DeviceOperation.CAMERA_TIMING_READ, source=source)
    if words[:2] == ["camera", "set-exposure"] and len(words) == 3:
        return DeviceCommand(
            DeviceId.CAMERA,
            DeviceOperation.CAMERA_EXPOSURE_CONFIGURE,
            CameraConfigureExposureArgs(float(words[2])),
            source=source,
        )
    if words[:2] == ["camera", "set-roi"] and len(words) == 6:
        return DeviceCommand(
            DeviceId.CAMERA,
            DeviceOperation.CAMERA_ROI_CONFIGURE,
            CameraConfigureRoiArgs(*(int(value) for value in words[2:])),
            source=source,
        )
    if words[:2] == ["ad2", "configure-do"] and len(words) in (4, 5):
        bits = tuple(int(bit) for bit in words[4]) if len(words) == 5 else ()
        output_type = Ad2DigitalOutputType.CUSTOM if bits else Ad2DigitalOutputType.PULSE
        return DeviceCommand(
            DeviceId.AD2,
            DeviceOperation.AD2_DIGITAL_OUTPUT_CONFIGURE,
            Ad2ConfigureDigitalOutputArgs(
                channel_index=int(words[2]),
                output_type=output_type,
                clock_frequency_hz=float(words[3]),
                bits=bits,
            ),
            source=source,
        )
    ad2_digital_commands = {
        ("ad2", "start-do"): DeviceOperation.AD2_DIGITAL_OUTPUT_START,
        ("ad2", "stop-do"): DeviceOperation.AD2_DIGITAL_OUTPUT_STOP,
        ("ad2", "reset-do"): DeviceOperation.AD2_DIGITAL_OUTPUT_RESET,
    }
    if tuple(words) in ad2_digital_commands:
        return DeviceCommand(DeviceId.AD2, ad2_digital_commands[tuple(words)], source=source)
    if len(words) == 3 and words[:2] == ["tec", "set-temperature"]:
        return DeviceCommand(
            DeviceId.TEC,
            DeviceOperation.TEC_SETPOINTS_APPLY,
            TecApplySetpointsArgs(float(words[2])),
            source=source,
        )
    if words == ["tec", "read-status"]:
        return DeviceCommand(
            DeviceId.TEC,
            DeviceOperation.TEC_STATUS_READ,
            TecReadStatusArgs(),
            source=source,
        )
    if words == ["tec", "outputs-off"]:
        return DeviceCommand(DeviceId.TEC, DeviceOperation.TEC_OUTPUTS_OFF, source=source)
    if words[:2] == ["tec", "wait-stable"] and len(words) == 6:
        return DeviceCommand(
            DeviceId.TEC,
            DeviceOperation.TEC_WAIT_STABLE,
            TecWaitStableArgs(
                target_temperature_c=float(words[2]),
                tolerance_c=float(words[3]),
                min_settle_s=float(words[4]),
                max_wait_s=float(words[5]),
            ),
            source=source,
        )
    if words == ["z-stage", "check-closed-loop"]:
        return DeviceCommand(
            DeviceId.Z_STAGE,
            DeviceOperation.Z_STAGE_CLOSED_LOOP_REQUIREMENT_READ,
            source=source,
        )
    if words == ["z-stage", "enable-closed-loop"]:
        return DeviceCommand(
            DeviceId.Z_STAGE, DeviceOperation.Z_STAGE_CLOSED_LOOP_ENABLE, source=source
        )
    if len(words) == 3 and words[:2] == ["z-stage", "move"]:
        return DeviceCommand(
            DeviceId.Z_STAGE,
            DeviceOperation.Z_STAGE_POSITION_SET,
            ZStageSetPositionArgs(float(words[2])),
            source=source,
        )
    if words == ["z-stage", "read-position"]:
        return DeviceCommand(DeviceId.Z_STAGE, DeviceOperation.Z_STAGE_POSITION_READ, source=source)
    raise ValueError(f"Invalid command. Type help for supported commands: {line}")
