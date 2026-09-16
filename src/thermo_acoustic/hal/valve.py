from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from ..application.commands import (
    DeviceOperation,
    NoArguments,
    ValvePositionResult,
    ValveReadyResult,
    ValveSetPositionArgs,
    ValveWaitReadyArgs,
)
from ..domain.models import DeviceId, ValveReadback
from .base import DeviceWorker


class ValveWorker(DeviceWorker):
    def __init__(self, device_factory: Callable[[], object], parent=None) -> None:
        super().__init__(DeviceId.VALVE, device_factory, readback_factory=ValveReadback, parent=parent)
        self.register(DeviceOperation.VALVE_POSITION_SET, self.set_position)
        self.register(DeviceOperation.VALVE_POSITION_READ, self.read_position)
        self.register(DeviceOperation.VALVE_WAIT_READY, self.wait_until_ready)

    def set_position(self, args: ValveSetPositionArgs) -> None:
        self.device.set_position(args.position)
        self.state.active = True
        self.state.readback = replace(
            self.state.readback,
            requested_position=args.position,
            confirmed_position=None,
            ready=False,
        )

    def read_position(self, _args: NoArguments) -> ValvePositionResult:
        result = ValvePositionResult(int(self.device.read_position()))
        self.state.readback = replace(
            self.state.readback, confirmed_position=result.position, ready=True
        )
        self.state.active = False
        return result

    def wait_until_ready(self, args: ValveWaitReadyArgs) -> ValveReadyResult:
        ready = bool(self.device.wait_until_ready(args.timeout_s, args.poll_interval_s))
        position = int(self.device.read_position()) if ready else None
        result = ValveReadyResult(ready, position)
        self.state.readback = replace(
            self.state.readback, confirmed_position=position, ready=ready
        )
        self.state.active = not ready
        return result
