from __future__ import annotations
import shlex
from ..application.commands import DeviceCommand
from ..domain.models import DeviceId

_DEVICES = {d.value: d for d in DeviceId}
def help_text() -> str:
    return "status | devices | connect DEVICE | disconnect DEVICE | pump set-flow UL_MIN | pump stop | valve set-position 1|2 | camera snapshot | tec set-temperature C | z-stage enable-closed-loop | z-stage move UM | quit"

def parse_command(line: str, *, source: str = "console") -> DeviceCommand | str | None:
    words = shlex.split(line.strip())
    if not words: return None
    if words[0] in ("help", "status", "devices", "quit"): return words[0]
    if words[0] in ("connect", "disconnect") and len(words) == 2 and words[1] in _DEVICES: return DeviceCommand(_DEVICES[words[1]], words[0], source=source)
    if len(words) == 3 and words[0] == "pump" and words[1] == "set-flow": return DeviceCommand(DeviceId.PUMP, "set-flow", (float(words[2]),), source=source)
    if words == ["pump", "stop"]: return DeviceCommand(DeviceId.PUMP, "stop", source=source)
    if len(words) == 3 and words[:2] == ["valve", "set-position"]: return DeviceCommand(DeviceId.VALVE, "set-position", (int(words[2]),), source=source)
    if words == ["camera", "snapshot"]: return DeviceCommand(DeviceId.CAMERA, "snapshot", source=source)
    if len(words) == 3 and words[:2] == ["tec", "set-temperature"]: return DeviceCommand(DeviceId.TEC, "set-temperature", (float(words[2]),), source=source)
    if words == ["z-stage", "enable-closed-loop"]: return DeviceCommand(DeviceId.Z_STAGE, "enable-closed-loop", source=source)
    if len(words) == 3 and words[:2] == ["z-stage", "move"]: return DeviceCommand(DeviceId.Z_STAGE, "move", (float(words[2]),), source=source)
    raise ValueError(f"Invalid command. Type help for supported commands: {line}")

