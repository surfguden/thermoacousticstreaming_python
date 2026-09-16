from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from ..application.commands import (
    DeviceOperation,
    NoArguments,
    PumpFillLevelResult,
    PumpSetFlowArgs,
    PumpStatusResult,
)
from ..domain.models import DeviceId, PumpReadback
from .base import DeviceWorker


class PumpWorker(DeviceWorker):
    def __init__(self, device_factory: Callable[[], object], parent=None) -> None:
        super().__init__(DeviceId.PUMP, device_factory, readback_factory=PumpReadback, parent=parent)
        self.register(DeviceOperation.PUMP_FLOW_SET, self.set_flow)
        self.register(DeviceOperation.PUMP_FLOW_STOP, self.stop_flow)
        self.register(DeviceOperation.PUMP_FILL_LEVEL_READ, self.read_fill_level)
        self.register(DeviceOperation.PUMP_STATUS_READ, self.read_status)

    def set_flow(self, args: PumpSetFlowArgs) -> None:
        self.device.generate_flow(args.flow_ul_min)
        self.state.active = args.flow_ul_min != 0
        self.state.readback = replace(
            self.state.readback,
            requested_flow_ul_min=args.flow_ul_min,
            is_pumping=self.state.active,
        )

    def stop_flow(self, _args: NoArguments) -> None:
        self.safe_stop()

    def read_fill_level(self, _args: NoArguments) -> PumpFillLevelResult:
        result = PumpFillLevelResult(float(self.device.read_fill_level()))
        self.state.readback = replace(self.state.readback, fill_level_ml=result.fill_level_ml)
        return result

    def read_status(self, _args: NoArguments) -> PumpStatusResult:
        result = PumpStatusResult(bool(self.device.read_status()))
        self.state.active = result.is_pumping
        self.state.readback = replace(self.state.readback, is_pumping=result.is_pumping)
        return result

    def safe_stop(self) -> None:
        if self.device_constructed and self.state.connected:
            self.device.stop()
        self.state.active = False
        self.state.readback = replace(
            self.state.readback, requested_flow_ul_min=0.0, is_pumping=False
        )
