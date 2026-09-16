from __future__ import annotations

from collections.abc import Callable

from ..application.commands import (
    DeviceOperation,
    NoArguments,
    TecApplySetpointsArgs,
    TecChannelStatusResult,
    TecReadStatusArgs,
    TecStatusResult,
)
from ..domain.models import DeviceId, TecChannelReadback, TecReadback
from .base import DeviceWorker


class TecWorker(DeviceWorker):
    def __init__(self, device_factory: Callable[[], object], parent=None) -> None:
        super().__init__(DeviceId.TEC, device_factory, readback_factory=TecReadback, parent=parent)
        self.register(DeviceOperation.TEC_SETPOINTS_APPLY, self.apply_setpoints)
        self.register(DeviceOperation.TEC_OUTPUTS_OFF, self.outputs_off)
        self.register(DeviceOperation.TEC_STATUS_READ, self.read_status)

    @staticmethod
    def _result(statuses: dict[int, object]) -> TecStatusResult:
        return TecStatusResult(
            tuple(
                TecChannelStatusResult(
                    channel=channel,
                    current_temperature_c=status.current_temperature_c,
                    target_temperature_c=status.target_temperature_c,
                    output_enabled=status.output_stage_static_on,
                    ready=status.ready,
                    fault=status.error_state,
                )
                for channel, status in sorted(statuses.items())
            )
        )

    def _update(self, result: TecStatusResult) -> None:
        self.state.readback = TecReadback(
            tuple(
                TecChannelReadback(
                    channel=item.channel,
                    current_temperature_c=item.current_temperature_c,
                    target_temperature_c=item.target_temperature_c,
                    output_enabled=item.output_enabled,
                    ready=item.ready,
                    fault=item.fault,
                )
                for item in result.channels
            )
        )
        self.state.active = any(item.output_enabled for item in result.channels)

    def apply_setpoints(self, args: TecApplySetpointsArgs) -> TecStatusResult:
        result = self._result(
            self.device.apply_static_setpoint(args.target_temperature_c, args.channels)
        )
        self._update(result)
        self.state.configured = True
        return result

    def outputs_off(self, _args: NoArguments) -> TecStatusResult:
        result = self._result(self.device.set_output_stage_static_off())
        self._update(result)
        return result

    def read_status(self, args: TecReadStatusArgs) -> TecStatusResult:
        result = self._result(self.device.read_status(args.channels))
        self._update(result)
        return result

    def safe_stop(self) -> None:
        if self.device_constructed and self.state.connected:
            self._update(self._result(self.device.set_output_stage_static_off()))
        else:
            self.state.active = False
