from __future__ import annotations

from collections.abc import Callable
from time import monotonic

from ..application.commands import (
    DeviceOperation,
    NoArguments,
    TecApplySetpointsArgs,
    TecChannelStatusResult,
    TecReadStatusArgs,
    TecStatusResult,
    TecWaitStableArgs,
)
from ..domain.models import DeviceId, TecChannelReadback, TecReadback
from .base import DeferredProgress, DeviceWorker


class TecWorker(DeviceWorker):
    def __init__(self, device_factory: Callable[[], object], parent=None) -> None:
        super().__init__(DeviceId.TEC, device_factory, readback_factory=TecReadback, parent=parent)
        self.register(DeviceOperation.TEC_SETPOINTS_APPLY, self.apply_setpoints)
        self.register(DeviceOperation.TEC_OUTPUTS_OFF, self.outputs_off)
        self.register(DeviceOperation.TEC_STATUS_READ, self.read_status)
        self.register(DeviceOperation.TEC_WAIT_STABLE, self.wait_until_stable)

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

    def wait_until_stable(self, args: TecWaitStableArgs) -> object:
        channels = args.channels or tuple(self.device.channels)
        if isinstance(args.target_temperature_c, dict):
            if set(args.target_temperature_c) != set(channels):
                raise ValueError(
                    "TEC target-temperature keys must exactly match the selected channels"
                )
            targets = {
                channel: float(args.target_temperature_c[channel]) for channel in channels
            }
        else:
            targets = {channel: float(args.target_temperature_c) for channel in channels}
        deadline = monotonic() + args.max_wait_s
        stable_since: float | None = None

        def cancel() -> None:
            # Cancelling the wait does not turn regulation off. An urgent
            # TEC_OUTPUTS_OFF request performs that distinct safety action.
            return None

        def step() -> DeferredProgress:
            nonlocal stable_since
            result = self._result(self.device.read_status(channels))
            self._update(result)
            for item in result.channels:
                if item.fault:
                    raise RuntimeError(
                        f"TEC channel {item.channel} reported an error: {item.fault}"
                    )
            within_tolerance = all(
                item.current_temperature_c is not None
                and abs(item.current_temperature_c - targets[item.channel])
                <= args.tolerance_c
                and item.ready
                for item in result.channels
            )
            now = monotonic()
            if within_tolerance:
                if stable_since is None:
                    stable_since = now
                if now - stable_since >= args.min_settle_s:
                    return DeferredProgress(True, result)
            else:
                stable_since = None
            if now >= deadline:
                raise TimeoutError(
                    f"TEC did not stabilize within {args.max_wait_s:.3f}s"
                )
            self._emit_status()
            return DeferredProgress()

        return self.defer_operation(
            step, cancel=cancel, poll_interval_s=args.poll_interval_s
        )

    def safe_stop(self) -> None:
        if self.device_constructed and self.state.connected:
            self._update(self._result(self.device.set_output_stage_static_off()))
        else:
            self.state.active = False
