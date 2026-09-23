"""Timer-driven, application-owned workflows spanning multiple device workers."""

from __future__ import annotations

from enum import Enum
from time import monotonic
from typing import Callable

from PySide6.QtCore import QObject, QTimer

from .commands import (
    DeviceOperation,
    FlushArgs,
    PumpFillLevelResult,
    PumpSetFillLevelArgs,
    PumpStatusResult,
    PumpUnitArgs,
    ValvePosition,
    ValveSetPositionArgs,
    WorkflowProgress,
)
from ..domain.models import ConnectionState, DeviceId, PumpReadback, ValveReadback


class FlushState(str, Enum):
    OPEN_COMMAND = "open_command"
    OPEN_WAIT = "open_wait"
    OPEN_SETTLE = "open_settle"
    LEVEL_READ = "level_read"
    PUMP_COMMAND = "pump_command"
    PUMP_POLL_DELAY = "pump_poll_delay"
    PUMP_STATUS = "pump_status"
    CLOSE_COMMAND = "close_command"
    CLOSE_WAIT = "close_wait"
    CLOSE_SETTLE = "close_settle"
    AFTER_WAIT = "after_wait"
    RECOVERY_STOP = "recovery_stop"
    RECOVERY_POLL_DELAY = "recovery_poll_delay"
    RECOVERY_STATUS = "recovery_status"
    RECOVERY_CLOSE_COMMAND = "recovery_close_command"
    RECOVERY_CLOSE_WAIT = "recovery_close_wait"
    FINISHED = "finished"


class FlushWorkflow(QObject):
    """Hold pump/valve resources while independent devices continue to work."""

    def __init__(
        self,
        args: FlushArgs,
        *,
        statuses: Callable[[], dict],
        send: Callable[[DeviceId, DeviceOperation, object, bool], str],
        progress: Callable[[WorkflowProgress], None],
        failure_started: Callable[[str], None],
        finished: Callable[[bool, str], None],
        parent: QObject,
    ) -> None:
        super().__init__(parent)
        self.args = args
        self._statuses = statuses
        self._send_step = send
        self._progress = progress
        self._failure_started = failure_started
        self._finished = finished
        self.state = FlushState.OPEN_COMMAND
        self.pending_id: str | None = None
        self._deadline = 0.0
        self._idle_samples = 0
        self._error = ""
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timer)

    def start(self) -> None:
        try:
            statuses = self._statuses()
            pump = statuses[DeviceId.PUMP]
            valve = statuses[DeviceId.VALVE]
            if pump.connection is not ConnectionState.CONNECTED or valve.connection is not ConnectionState.CONNECTED:
                raise RuntimeError("Connect both pump and valve before flushing")
            readback = pump.readback
            if not isinstance(readback, PumpReadback) or self.args.unit_index >= len(readback.units):
                raise ValueError("Selected pump unit is not loaded from the configuration")
            unit = readback.units[self.args.unit_index]
            if unit.is_faulted or unit.is_pumping:
                raise RuntimeError("Selected pump unit must be idle and fault-free before flushing")
            if unit.max_flow_rate_ul_min is None or self.args.flow_ul_min > unit.max_flow_rate_ul_min:
                raise ValueError(f"Flush flow exceeds pump {self.args.unit_index + 1} limit")
        except Exception as exc:
            self._complete(False, str(exc))
            return
        self._command(
            FlushState.OPEN_COMMAND, DeviceId.VALVE,
            DeviceOperation.VALVE_POSITION_SET,
            ValveSetPositionArgs(ValvePosition.OPEN.value),
            "Opening valve",
        )

    def _command(
        self, state: FlushState, device: DeviceId, operation: DeviceOperation,
        arguments: object, detail: str, *, urgent: bool = False,
    ) -> None:
        self.state = state
        self._progress(WorkflowProgress(state.value, detail))
        try:
            self.pending_id = self._send_step(device, operation, arguments, urgent)
        except Exception as exc:
            if state.name.startswith("RECOVERY_"):
                self._complete(False, f"{self._error}; cleanup failed: {exc}")
            else:
                self._fail(str(exc))

    def on_step(self, request_id: str, ok: bool, value: object = None, error: str = "") -> bool:
        if request_id != self.pending_id:
            return False
        self.pending_id = None
        if not ok:
            if self.state.name.startswith("RECOVERY_"):
                self._complete(False, f"{self._error}; cleanup failed: {error}")
            else:
                self._fail(error)
            return True

        state = self.state
        if state is FlushState.OPEN_COMMAND:
            self._wait_for_valve(ValvePosition.OPEN.value, recovering=False)
        elif state is FlushState.LEVEL_READ:
            if not isinstance(value, PumpFillLevelResult):
                self._fail("Pump did not return a fill level")
            else:
                target = value.fill_level_ml - self.args.volume_ml
                if target < 0:
                    self._fail(
                        f"Pump {self.args.unit_index + 1} has {value.fill_level_ml:g} mL; "
                        f"cannot flush {self.args.volume_ml:g} mL"
                    )
                else:
                    self._command(
                        FlushState.PUMP_COMMAND, DeviceId.PUMP,
                        DeviceOperation.PUMP_FILL_LEVEL_SET,
                        PumpSetFillLevelArgs(target, self.args.flow_ul_min, self.args.unit_index),
                        f"Moving pump {self.args.unit_index + 1} to {target:g} mL",
                    )
        elif state is FlushState.PUMP_COMMAND:
            travel_s = self.args.volume_ml * 1000.0 / self.args.flow_ul_min * 60.0
            self._deadline = monotonic() + travel_s + 10.0
            self._idle_samples = 0
            self.state = FlushState.PUMP_POLL_DELAY
            self._timer.start(250)
        elif state is FlushState.PUMP_STATUS:
            if not isinstance(value, PumpStatusResult):
                self._fail("Pump did not return a pumping status")
            elif self._pump_faulted():
                self._fail("Pump reported a fault during flush")
            else:
                self._idle_samples = 0 if value.is_pumping else self._idle_samples + 1
                if self._idle_samples >= 2:
                    self._close_valve(recovering=False)
                elif monotonic() >= self._deadline:
                    self._fail("Pump did not become idle before the flush deadline")
                else:
                    self.state = FlushState.PUMP_POLL_DELAY
                    self._timer.start(250)
        elif state is FlushState.CLOSE_COMMAND:
            self._wait_for_valve(ValvePosition.CLOSED.value, recovering=False)
        elif state is FlushState.RECOVERY_STOP:
            self._deadline = monotonic() + 10.0
            self.state = FlushState.RECOVERY_POLL_DELAY
            self._timer.start(250)
        elif state is FlushState.RECOVERY_STATUS:
            if not isinstance(value, PumpStatusResult):
                self._complete(False, f"{self._error}; pump idle could not be confirmed")
            elif not value.is_pumping:
                self._close_valve(recovering=True)
            elif monotonic() >= self._deadline:
                self._complete(False, f"{self._error}; pump did not stop, valve left unchanged")
            else:
                self.state = FlushState.RECOVERY_POLL_DELAY
                self._timer.start(250)
        elif state is FlushState.RECOVERY_CLOSE_COMMAND:
            self._wait_for_valve(ValvePosition.CLOSED.value, recovering=True)
        else:
            self._fail(f"Unexpected flush response in state {state.value}")
        return True

    def _pump_faulted(self) -> bool:
        pump = self._statuses()[DeviceId.PUMP]
        readback = pump.readback
        return (
            pump.connection is ConnectionState.ERROR
            or isinstance(readback, PumpReadback)
            and self.args.unit_index < len(readback.units)
            and readback.units[self.args.unit_index].is_faulted is True
        )

    def _wait_for_valve(self, position: int, *, recovering: bool) -> None:
        self.state = (
            FlushState.RECOVERY_CLOSE_WAIT if recovering else
            FlushState.OPEN_WAIT if position == ValvePosition.OPEN.value else FlushState.CLOSE_WAIT
        )
        self._deadline = monotonic() + 10.0
        self._timer.start(0)

    def _close_valve(self, *, recovering: bool) -> None:
        self._command(
            FlushState.RECOVERY_CLOSE_COMMAND if recovering else FlushState.CLOSE_COMMAND,
            DeviceId.VALVE, DeviceOperation.VALVE_POSITION_SET,
            ValveSetPositionArgs(ValvePosition.CLOSED.value), "Closing valve",
        )

    def _on_timer(self) -> None:
        state = self.state
        if state in (FlushState.OPEN_WAIT, FlushState.CLOSE_WAIT, FlushState.RECOVERY_CLOSE_WAIT):
            valve = self._statuses()[DeviceId.VALVE]
            desired = ValvePosition.OPEN.value if state is FlushState.OPEN_WAIT else ValvePosition.CLOSED.value
            readback = valve.readback
            if isinstance(readback, ValveReadback) and readback.ready and readback.confirmed_position == desired:
                if state is FlushState.OPEN_WAIT:
                    self.state = FlushState.OPEN_SETTLE
                    self._progress(WorkflowProgress(self.state.value, "Valve open; settling for 1 s"))
                    self._timer.start(1000)
                elif state is FlushState.CLOSE_WAIT:
                    self.state = FlushState.CLOSE_SETTLE
                    self._progress(WorkflowProgress(self.state.value, "Valve closed; settling for 1 s"))
                    self._timer.start(1000)
                else:
                    self._complete(False, self._error)
            elif valve.connection is ConnectionState.ERROR or monotonic() >= self._deadline:
                reason = f"Valve did not confirm position {desired} within 10 s"
                if state is FlushState.RECOVERY_CLOSE_WAIT:
                    self._complete(False, f"{self._error}; {reason}")
                else:
                    self._fail(reason)
            else:
                self._timer.start(250)
        elif state is FlushState.OPEN_SETTLE:
            self._command(
                FlushState.LEVEL_READ, DeviceId.PUMP, DeviceOperation.PUMP_FILL_LEVEL_READ,
                PumpUnitArgs(self.args.unit_index), "Reading current pump level",
            )
        elif state is FlushState.PUMP_POLL_DELAY:
            if monotonic() >= self._deadline:
                self._fail("Pump did not become idle before the flush deadline")
            else:
                self._command(
                    FlushState.PUMP_STATUS, DeviceId.PUMP, DeviceOperation.PUMP_STATUS_READ,
                    PumpUnitArgs(self.args.unit_index), "Waiting for pump idle",
                )
        elif state is FlushState.CLOSE_SETTLE:
            self.state = FlushState.AFTER_WAIT
            self._progress(WorkflowProgress(self.state.value, f"Waiting {self.args.wait_after_s:g} s after flush"))
            self._timer.start(round(self.args.wait_after_s * 1000))
        elif state is FlushState.AFTER_WAIT:
            self._complete(True, "")
        elif state is FlushState.RECOVERY_POLL_DELAY:
            if monotonic() >= self._deadline:
                self._complete(False, f"{self._error}; pump idle could not be confirmed, valve left unchanged")
            else:
                self._command(
                    FlushState.RECOVERY_STATUS, DeviceId.PUMP, DeviceOperation.PUMP_STATUS_READ,
                    PumpUnitArgs(self.args.unit_index), "Confirming pump idle before valve cleanup",
                )

    def _fail(self, error: str) -> None:
        if self.state is FlushState.FINISHED or self.state.name.startswith("RECOVERY_"):
            return
        self._timer.stop()
        self.pending_id = None
        self._error = error
        self._failure_started(error)
        self._command(
            FlushState.RECOVERY_STOP, DeviceId.PUMP, DeviceOperation.PUMP_FLOW_STOP,
            PumpUnitArgs(self.args.unit_index), "Stopping pump after flush failure", urgent=True,
        )

    def abort(self, reason: str = "Flush aborted") -> None:
        self._fail(reason)

    def dispose(self) -> None:
        self._timer.stop()
        self.pending_id = None
        self.state = FlushState.FINISHED

    def _complete(self, ok: bool, error: str) -> None:
        self._timer.stop()
        self.pending_id = None
        self.state = FlushState.FINISHED
        self._finished(ok, error)
