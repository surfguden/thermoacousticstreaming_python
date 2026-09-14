from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..application import LabApplication
from ..domain import ConnectionState, DEVICE_LABELS, DeviceId, DeviceState, OperatingMode


@dataclass(slots=True)
class SimulatedDevice:
    device_id: DeviceId
    mode: OperatingMode = OperatingMode.SIMULATION
    connection: ConnectionState = ConnectionState.DISCONNECTED
    values: dict[str, Any] = field(default_factory=dict)
    last_command: str | None = None

    def connect(self) -> None:
        self.connection = ConnectionState.CONNECTED

    def disconnect(self) -> None:
        self.connection = ConnectionState.DISCONNECTED

    def execute(self, command: str, parameters: dict[str, Any]) -> None:
        self.last_command = command
        self.values.update(parameters)
        if command == "start":
            self.values["running"] = True
        elif command in {"stop", "outputs_off"}:
            self.values["running"] = False
        elif command == "set_position":
            self.values["position"] = int(parameters["position"])
        elif command == "snapshot":
            self.values["snapshots"] = int(self.values.get("snapshots", 0)) + 1

    def state(self) -> DeviceState:
        if self.connection is ConnectionState.CONNECTED:
            detail = "Simulated and ready"
            if self.last_command:
                detail = f"Simulated · last action: {self.last_command.replace('_', ' ')}"
        else:
            detail = "Not connected"
        return DeviceState(
            device=self.device_id,
            connection=self.connection,
            summary=detail,
            values=dict(self.values),
        )


def build_simulated_application() -> LabApplication:
    devices = {device: SimulatedDevice(device) for device in DEVICE_LABELS}
    return LabApplication(devices, OperatingMode.SIMULATION)
