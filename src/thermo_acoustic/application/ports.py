from __future__ import annotations

from typing import Any, Protocol

from ..domain import DeviceId, DeviceState, OperatingMode


class DevicePort(Protocol):
    """Narrow boundary between application actions and a device adapter."""

    device_id: DeviceId
    mode: OperatingMode

    def connect(self) -> None: ...

    def disconnect(self) -> None: ...

    def execute(self, command: str, parameters: dict[str, Any]) -> None: ...

    def state(self) -> DeviceState: ...
