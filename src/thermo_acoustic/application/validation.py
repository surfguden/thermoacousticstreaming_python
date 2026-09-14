from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..domain import DeviceId, ExperimentPlan


class ActionValidationError(ValueError):
    pass


COMMANDS: dict[DeviceId, set[str]] = {
    DeviceId.AD2: {"configure_waveform", "start", "stop", "trigger"},
    DeviceId.PUMP: {"set_flow", "refill", "empty", "stop"},
    DeviceId.VALVE: {"set_position"},
    DeviceId.CAMERA: {"configure", "snapshot", "start", "stop"},
    DeviceId.TEC: {"set_temperature", "outputs_off"},
    DeviceId.Z_STAGE: {"move_um"},
}


def _number(parameters: Mapping[str, Any], name: str, low: float, high: float) -> float:
    try:
        value = float(parameters[name])
    except (KeyError, TypeError, ValueError) as exc:
        raise ActionValidationError(f"{name} must be a number") from exc
    if not low <= value <= high:
        raise ActionValidationError(f"{name} must be between {low:g} and {high:g}")
    return value


def validate_action(device: DeviceId, command: str, parameters: Mapping[str, Any]) -> None:
    if command not in COMMANDS[device]:
        raise ActionValidationError(f"Unsupported {device.value} command: {command}")
    if device is DeviceId.AD2 and command == "configure_waveform":
        _number(parameters, "frequency_hz", 0.001, 100_000_000)
        _number(parameters, "amplitude_v", 0, 5)
    elif device is DeviceId.PUMP and command == "set_flow":
        _number(parameters, "flow_ul_min", -10_000, 10_000)
    elif device is DeviceId.VALVE and command == "set_position":
        position = int(_number(parameters, "position", 1, 2))
        if float(parameters["position"]) != position:
            raise ActionValidationError("position must be 1 or 2")
    elif device is DeviceId.CAMERA and command == "configure":
        _number(parameters, "exposure_ms", 0.001, 60_000)
        _number(parameters, "frame_count", 1, 100_000)
    elif device is DeviceId.TEC and command == "set_temperature":
        _number(parameters, "temperature_c", -20, 120)
    elif device is DeviceId.Z_STAGE and command == "move_um":
        _number(parameters, "position_um", 0, 450)


def validate_plan(plan: ExperimentPlan) -> None:
    if not plan.name.strip():
        raise ActionValidationError("Experiment name is required")
    if not plan.steps:
        raise ActionValidationError("Experiment plan has no steps")
    for index, step in enumerate(plan.steps, start=1):
        if step.delay_after_s < 0:
            raise ActionValidationError(f"Step {index} delay cannot be negative")
        try:
            validate_action(step.device, step.command, step.parameters)
        except ActionValidationError as exc:
            raise ActionValidationError(f"Step {index}: {exc}") from exc
