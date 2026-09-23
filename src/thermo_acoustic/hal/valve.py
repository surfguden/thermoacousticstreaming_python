from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from ..application.commands import (
    DeviceOperation,
    NoArguments,
    ValveConnectArgs,
    ValvePositionResult,
    ValveReadyResult,
    ValveSetPositionArgs,
    ValveWaitReadyArgs,
)
from ..domain.models import DeviceId, ValveReadback
from .base import DeviceWorker


class ValveWorker(DeviceWorker):
    def __init__(self, device_factory: Callable[[], object], parent=None) -> None:
        super().__init__(DeviceId.VALVE, device_factory, readback_factory=ValveReadback, poll_interval_s=0.5, parent=parent)
        self.register(DeviceOperation.VALVE_POSITION_SET, self.set_position)
        self.register(DeviceOperation.VALVE_POSITION_READ, self.read_position)
        self.register(DeviceOperation.VALVE_WAIT_READY, self.wait_until_ready)

    def prepare_connection(self, device: object, arguments: object) -> None:
        if hasattr(device, "visa_resource"):
            if not isinstance(arguments, ValveConnectArgs):
                raise ValueError("Select a valve COM port before connecting")
            device.visa_resource = arguments.port

    def connect_device(self, arguments: object = NoArguments()) -> None:
        super().connect_device(arguments)
        self._refresh_state()

    def _refresh_state(self) -> None:
        ready, position = self.device.read_state()
        self.state.readback = replace(
            self.state.readback,
            confirmed_position=position,
            ready=ready,
            status_note=self.device.status_note,
        )
        self.state.active = not ready

    def poll_once(self) -> None:
        if not self.state.connected or self.state.busy:
            return
        try:
            self._refresh_state()
            self.state.fault = None
        except Exception as exc:
            self.state.fault = str(exc)
            self.state.readback = replace(
                self.state.readback, confirmed_position=None, ready=False,
                status_note=str(exc),
            )
        self._emit_status()

    def set_position(self, args: ValveSetPositionArgs) -> None:
        self.device.set_position(args.position)
        self.state.active = True
        self.state.readback = replace(
            self.state.readback,
            requested_position=args.position,
            confirmed_position=None,
            ready=False,
            status_note=self.device.status_note,
        )

    def read_position(self, _args: NoArguments) -> ValvePositionResult:
        self._refresh_state()
        if self.state.readback.confirmed_position is None:
            raise RuntimeError("Valve position is not currently confirmed")
        result = ValvePositionResult(int(self.state.readback.confirmed_position))
        return result

    def wait_until_ready(self, args: ValveWaitReadyArgs) -> ValveReadyResult:
        ready = bool(self.device.wait_until_ready(args.timeout_s, args.poll_interval_s))
        position = int(self.device.read_position()) if ready else None
        result = ValveReadyResult(ready, position)
        self.state.readback = replace(
            self.state.readback, confirmed_position=position, ready=ready,
            status_note=self.device.status_note,
        )
        self.state.active = not ready
        return result
