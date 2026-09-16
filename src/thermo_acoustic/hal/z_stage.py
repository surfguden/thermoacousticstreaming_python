from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from ..application.commands import (
    DeviceOperation,
    NoArguments,
    ZStageClosedLoopRequirementResult,
    ZStagePositionResult,
    ZStageSetPositionArgs,
)
from ..domain.models import DeviceId, ZStageReadback
from .base import DeviceWorker


class ZStageWorker(DeviceWorker):
    def __init__(self, device_factory: Callable[[], object], parent=None) -> None:
        super().__init__(DeviceId.Z_STAGE, device_factory, readback_factory=ZStageReadback, parent=parent)
        self.register(
            DeviceOperation.Z_STAGE_CLOSED_LOOP_REQUIREMENT_READ,
            self.read_closed_loop_requirement,
        )
        self.register(DeviceOperation.Z_STAGE_CLOSED_LOOP_ENABLE, self.enable_closed_loop)
        self.register(DeviceOperation.Z_STAGE_POSITION_SET, self.set_position)
        self.register(DeviceOperation.Z_STAGE_POSITION_READ, self.read_position)

    def initialize_device(self) -> None:
        self.device.connect()

    def cleanup_device(self) -> None:
        self.device.disconnect()

    def read_closed_loop_requirement(
        self, _args: NoArguments
    ) -> ZStageClosedLoopRequirementResult:
        required = bool(self.device.needs_closed_loop_confirmation())
        result = ZStageClosedLoopRequirementResult(required)
        self.state.readback = replace(
            self.state.readback,
            closed_loop_confirmation_required=required,
            closed_loop=not required,
        )
        self.state.configured = not required
        return result

    def enable_closed_loop(self, _args: NoArguments) -> None:
        self.device.switch_to_closed_loop()
        self.state.configured = True
        self.state.readback = replace(
            self.state.readback,
            closed_loop_confirmation_required=False,
            closed_loop=True,
        )

    def set_position(self, args: ZStageSetPositionArgs) -> ZStagePositionResult:
        if not self.state.readback.closed_loop:
            raise RuntimeError("Enable closed-loop before moving")
        result = ZStagePositionResult(float(self.device.set_position(args.position_um)))
        self.state.readback = replace(self.state.readback, position_um=result.position_um)
        return result

    def read_position(self, _args: NoArguments) -> ZStagePositionResult:
        result = ZStagePositionResult(float(self.device.get_position()))
        self.state.readback = replace(self.state.readback, position_um=result.position_um)
        return result
