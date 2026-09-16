from __future__ import annotations

import shlex

from ..application.commands import (
    CameraConfigureSnapshotArgs,
    DeviceCommand,
    DeviceOperation,
    PumpSetFlowArgs,
    TecApplySetpointsArgs,
    TecReadStatusArgs,
    ValveSetPositionArgs,
    ValveWaitReadyArgs,
    ZStageSetPositionArgs,
)
from ..domain.models import DeviceId


_DEVICES = {device.value: device for device in DeviceId}


def help_text() -> str:
    return (
        "status | devices | connect DEVICE | disconnect DEVICE | "
        "pump set-flow UL_MIN | pump stop | pump read-fill-level | pump read-status | "
        "valve set-position 1|2 | valve read-position | valve wait-ready | "
        "camera configure-snapshot [EXPOSURE_MS] | camera snapshot | camera read-timing | "
        "tec set-temperature C | tec read-status | tec outputs-off | "
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
    if words == ["camera", "read-timing"]:
        return DeviceCommand(DeviceId.CAMERA, DeviceOperation.CAMERA_TIMING_READ, source=source)
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
