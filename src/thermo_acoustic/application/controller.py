from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from time import monotonic
from typing import Any, Callable

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from ..domain.models import ConnectionState, DeviceId, DeviceStatus, OperatingMode, ZStageReadback
from ..hal.registry import DeviceRegistry
from .audit import AuditLogger
from .commands import (
    CommandEvent,
    CommandResult,
    ConfirmationRequest,
    DeviceCommand,
    DeviceOperation,
    NoArguments,
    OPERATION_SPECS,
    FlushArgs,
    WorkflowCommand,
    WorkflowOperation,
    WorkflowProgress,
    validate_command,
)
from .workflows import FlushWorkflow
from .experiment_runner import ExperimentManager
from .temperature_monitor import TemperatureMonitor


@dataclass(slots=True)
class _Pending:
    command: DeviceCommand[Any] | WorkflowCommand
    queued_at: float


class ApplicationController(QObject):
    command_event = Signal(object)
    command_result = Signal(object)
    command_progress = Signal(str, object)
    status_changed = Signal(object)
    message = Signal(str)
    panic_changed = Signal(object)

    def __init__(
        self,
        registry: DeviceRegistry,
        *,
        mode: OperatingMode,
        audit: AuditLogger | None = None,
        confirm_operation: Callable[[ConfirmationRequest], bool] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.registry = registry
        self.mode = mode
        self.audit = audit or AuditLogger()
        self.confirm_operation = confirm_operation or (lambda _: False)
        self._last_audit_error: str | None = None
        self.experiments = ExperimentManager(self, parent=self)
        self._queue: deque[_Pending] = deque()
        self._active: _Pending | None = None
        self._flush: FlushWorkflow | None = None
        self._flush_command: WorkflowCommand | None = None
        self._wait_timer = QTimer(self)
        self._wait_timer.setSingleShot(True)
        self._wait_timer.timeout.connect(self._finish_wait)
        self._urgent: dict[str, DeviceCommand[Any]] = {}
        self._observations: dict[str, DeviceCommand[Any]] = {}
        self._closing = False
        self._panic_pending: dict[str, DeviceId] = {}
        self._panic_errors: list[str] = []
        self._panic_state = "idle"
        self._panic_dispatching = False
        self.count_preflight_active = False
        self._statuses = {worker.device_id: worker.status() for worker in registry.all()}
        self.temperature_monitor = TemperatureMonitor(self, parent=self)
        self.experiments.attach_temperature_monitor(self.temperature_monitor)
        self.command_result.connect(self._panic_result)
        for worker in registry.all():
            worker.command_succeeded.connect(self._worker_succeeded)
            worker.command_failed.connect(self._worker_failed)
            worker.command_cancelled.connect(self._worker_cancelled)
            worker.command_progress.connect(self.command_progress)
            worker.status_changed.connect(self._status_received)

    def start(self) -> None:
        for worker in self.registry.all():
            worker._thread.start()
        self.status_changed.emit(dict(self._statuses))
        self.temperature_monitor.start()

    def panic_status(self) -> dict[str, object]:
        return {"state": self._panic_state, "pending": len(self._panic_pending),
                "errors": tuple(self._panic_errors)}

    def panic_stop(self) -> None:
        """Urgently stop active outputs without scheduling a valve or stage move."""
        if self._panic_state == "stopping":
            raise RuntimeError("Panic stop is already in progress")
        self._panic_state = "stopping"
        self._panic_dispatching = True
        self._panic_errors.clear()
        self.panic_changed.emit(self.panic_status())
        if self._flush is not None:
            self._flush.dispose()
            self._flush.deleteLater()
            self._flush = None
            command = self._flush_command
            self._flush_command = None
            if command is not None:
                self.command_result.emit(CommandResult(
                    command.request_id, None, command.operation, False,
                    error="Cancelled by Panic", command=command))
                self._emit(command, "cancelled", "Cancelled by Panic")
        if self._active is not None and isinstance(self._active.command, WorkflowCommand):
            self._wait_timer.stop()
            command = self._active.command
            self._active = None
            self.command_result.emit(CommandResult(
                command.request_id, None, command.operation, False,
                error="Cancelled by Panic", command=command))
            self._emit(command, "cancelled", "Cancelled by Panic")
        while self._queue:
            self._emit(self._queue.popleft().command, "cancelled", "Cancelled by Panic")
        self.experiments.panic_abort()
        # The valve holds its current position; moving it while flow stops may
        # be unsafe. The Z-stage has no physical stop primitive yet.
        for device in (DeviceId.AD2, DeviceId.PUMP, DeviceId.CAMERA, DeviceId.TEC):
            if self._statuses[device].connection is ConnectionState.DISCONNECTED:
                continue
            command = DeviceCommand(device, DeviceOperation.SAFE_STOP, NoArguments(), source="panic")
            self._panic_pending[command.request_id] = device
            try:
                self.submit(command)
            except Exception as exc:
                self._panic_pending.pop(command.request_id, None)
                self._panic_errors.append(f"{device.value}: {exc}")
        self._panic_dispatching = False
        self._finish_panic_if_ready()

    def _panic_result(self, result: CommandResult) -> None:
        device = self._panic_pending.pop(result.request_id, None)
        if device is None:
            return
        if not result.ok:
            self._panic_errors.append(f"{device.value}: {result.error or 'safe stop failed'}")
        self._finish_panic_if_ready()

    def _finish_panic_if_ready(self) -> None:
        if self._panic_state != "stopping" or self._panic_dispatching or self._panic_pending:
            return
        self._panic_state = "failed" if self._panic_errors else "completed"
        self.panic_changed.emit(self.panic_status())

    def observe_tec(self) -> str:
        """Read TEC without occupying the global experiment command lane."""
        from .commands import TecReadStatusArgs
        if self._closing or self._statuses[DeviceId.TEC].connection is not ConnectionState.CONNECTED:
            raise RuntimeError("TEC is not connected")
        command = DeviceCommand(DeviceId.TEC, DeviceOperation.TEC_STATUS_READ,
                                TecReadStatusArgs(), source="temperature-monitor")
        self._observations[command.request_id] = command
        self.registry.by_id(DeviceId.TEC).command_requested.emit(
            command.request_id, command.operation, command.arguments)
        return command.request_id

    def _finish_observation(self, request_id: str, ok: bool, value=None, error=None) -> bool:
        command = self._observations.pop(request_id, None)
        if command is None:
            return False
        if ok and not isinstance(value, OPERATION_SPECS[command.operation].result_type):
            ok = False
            error = f"{command.operation.value} returned an unexpected result type"
            value = None
        self.command_result.emit(CommandResult(request_id, command.device, command.operation,
                                               ok, value, error, command))
        return True

    def submit(self, command: DeviceCommand[Any] | WorkflowCommand) -> str:
        if self._closing:
            raise RuntimeError("Application shutdown has started")
        if self._panic_state == "stopping" and command.source != "panic":
            raise RuntimeError("Panic safe stop is in progress")
        if self.count_preflight_active and command.source != "experiment-preflight":
            observations = {DeviceOperation.CAMERA_TIMING_READ, DeviceOperation.PUMP_FILL_LEVEL_READ,
                            DeviceOperation.PUMP_STATUS_READ, DeviceOperation.VALVE_POSITION_READ,
                            DeviceOperation.TEC_STATUS_READ, DeviceOperation.AD2_OUTPUT_STATUS_READ}
            if isinstance(command, WorkflowCommand) or (
                command.operation not in observations and not self._is_urgent(command.operation)
            ):
                raise RuntimeError("Count preflight owns camera and AD2; wait for it to finish")
        if (self.experiments.status()["state"] in {"running", "stopping"}
                and command.source != "experiment"):
            safe_observations = {
                DeviceOperation.CAMERA_SEQUENCE_SAVE,
                DeviceOperation.CAMERA_TIMING_READ,
                DeviceOperation.PUMP_FILL_LEVEL_READ,
                DeviceOperation.PUMP_STATUS_READ,
                DeviceOperation.VALVE_POSITION_READ,
                DeviceOperation.TEC_STATUS_READ,
                DeviceOperation.Z_STAGE_POSITION_READ,
                DeviceOperation.AD2_OUTPUT_STATUS_READ,
            }
            if isinstance(command, WorkflowCommand) or (
                command.operation not in safe_observations
                and not self._is_urgent(command.operation)
            ):
                raise RuntimeError("Experiment owns the active instruments; use status, save, or abort")
        if isinstance(command, WorkflowCommand):
            self._queue.append(_Pending(command, monotonic()))
            self._emit(command, "queued")
            self._dispatch_next()
            return command.request_id
        if not isinstance(command, DeviceCommand):
            raise TypeError("submit() requires a DeviceCommand or WorkflowCommand")
        validate_command(command.device, command.operation, command.arguments)
        if command.operation is DeviceOperation.Z_STAGE_CLOSED_LOOP_ENABLE:
            readback = self._statuses[command.device].readback
            requirement = (
                readback.closed_loop_confirmation_required
                if isinstance(readback, ZStageReadback)
                else None
            )
            if requirement is None:
                self._emit(command, "failed", "Read the Z-stage closed-loop confirmation requirement first")
                return command.request_id
        if command.operation is DeviceOperation.PUMP_REFERENCE_MOVE:
            unit_number = command.arguments.unit_index + 1
            if not self.confirm_operation(ConfirmationRequest(
                command,
                f"Pump {unit_number} is about to perform a reference move. Remove the syringe before continuing. Start reference move?",
            )):
                self._emit(command, "failed", "Pump reference move requires operator confirmation")
                return command.request_id
        if self._is_urgent(command.operation):
            if (
                self._flush is not None
                and command.device in {DeviceId.PUMP, DeviceId.VALVE}
                and command.operation in {
                    DeviceOperation.ABORT_ACTIVE, DeviceOperation.SAFE_STOP,
                    DeviceOperation.PUMP_FLOW_STOP,
                }
            ):
                self._flush.abort(f"Flush interrupted by {command.operation.value}")
            self._urgent[command.request_id] = command
            self._emit(command, "queued")
            self._emit(command, "running")
            self._audit(
                "execution_start",
                request_id=command.request_id,
                source=command.source,
                device=command.device.value,
                operation=command.operation.value,
                urgent=True,
            )
            self.registry.by_id(command.device).urgent_command_requested.emit(
                command.request_id, command.operation, command.arguments
            )
            return command.request_id
        self._queue.append(_Pending(command, monotonic()))
        self._emit(command, "queued")
        self._dispatch_next()
        return command.request_id

    @staticmethod
    def _is_urgent(operation: DeviceOperation) -> bool:
        return operation in {
            DeviceOperation.ABORT_ACTIVE,
            DeviceOperation.SAFE_STOP,
            DeviceOperation.CAMERA_CAPTURE_STOP,
            DeviceOperation.PUMP_FLOW_STOP,
            DeviceOperation.TEC_OUTPUTS_OFF,
        }

    def _dispatch_next(self) -> None:
        if self._closing or self._active or not self._queue:
            return
        selected: int | None = None
        for index, pending in enumerate(self._queue):
            command = pending.command
            if isinstance(command, WorkflowCommand):
                if command.operation is WorkflowOperation.WAIT:
                    if index == 0 and self._flush is None:
                        selected = index
                    break  # A queued wait is a global ordering barrier.
                if self._flush is not None:
                    continue
                selected = index
                break
            if self._blocked_by_flush(command):
                continue
            selected = index
            break
        if selected is None:
            return
        pending = self._queue[selected]
        del self._queue[selected]
        command = pending.command
        if isinstance(command, WorkflowCommand):
            self._emit(command, "running")
            if command.operation is WorkflowOperation.WAIT:
                self._active = pending
                self.command_progress.emit(command.request_id, WorkflowProgress("wait", f"Waiting {command.arguments.seconds:g} s"))
                self._wait_timer.start(round(command.arguments.seconds * 1000))
            else:
                self._start_flush(command)
                self._dispatch_next()
            return
        self._active = pending
        self._emit(command, "running")
        self._audit(
            "execution_start",
            request_id=command.request_id,
            source=command.source,
            device=command.device.value,
            operation=command.operation.value,
        )
        self.registry.by_id(command.device).command_requested.emit(
            command.request_id, command.operation, command.arguments
        )

    def _blocked_by_flush(self, command: DeviceCommand[Any]) -> bool:
        if self._flush is None:
            return False
        if command.device is DeviceId.VALVE:
            return True
        if command.device is not DeviceId.PUMP:
            return False
        if command.operation in {
            DeviceOperation.CONNECT, DeviceOperation.DISCONNECT,
            DeviceOperation.PUMP_FAULT_RECOVER, DeviceOperation.PUMP_REFERENCE_MOVE,
        }:
            return True
        return getattr(command.arguments, "unit_index", 0) == self._flush.args.unit_index

    def _start_flush(self, command: WorkflowCommand) -> None:
        self._flush_command = command
        self._flush = FlushWorkflow(
            command.arguments,
            statuses=self.statuses,
            send=self._send_workflow_step,
            progress=lambda progress: self.command_progress.emit(command.request_id, progress),
            failure_started=self._cancel_queued_after_flush_failure,
            finished=self._finish_flush,
            parent=self,
        )
        self._flush.start()

    def _send_workflow_step(
        self, device: DeviceId, operation: DeviceOperation, arguments: object, urgent: bool,
    ) -> str:
        step = DeviceCommand(device, operation, arguments, source="workflow")
        self._audit(
            "workflow_step", request_id=step.request_id, device=device.value,
            operation=operation.value,
        )
        worker = self.registry.by_id(device)
        signal = worker.urgent_command_requested if urgent else worker.command_requested
        signal.emit(step.request_id, operation, arguments)
        return step.request_id

    def _cancel_queued_after_flush_failure(self, error: str) -> None:
        while self._queue:
            self._emit(self._queue.popleft().command, "cancelled", f"Flush failed: {error}")

    def _finish_flush(self, ok: bool, error: str) -> None:
        command = self._flush_command
        workflow = self._flush
        self._flush = None
        self._flush_command = None
        if workflow is not None:
            workflow.deleteLater()
        if command is None:
            return
        if not ok:
            self._cancel_queued_after_flush_failure(error)
        self.command_result.emit(CommandResult(
            command.request_id, None, command.operation, ok, error=error or None, command=command,
        ))
        self._emit(command, "completed" if ok else "failed", error)
        self._dispatch_next()

    def _finish_wait(self) -> None:
        pending = self._active
        if pending is None or not isinstance(pending.command, WorkflowCommand):
            return
        command = pending.command
        self.command_result.emit(CommandResult(command.request_id, None, command.operation, True, command=command))
        self._emit(command, "completed")
        self._active = None
        self._dispatch_next()

    def cancel_active_workflow(self) -> None:
        if self._flush is not None:
            self._flush.abort("Flush aborted by operator")
        elif self._active is not None and isinstance(self._active.command, WorkflowCommand):
            self._wait_timer.stop()
            command = self._active.command
            self.command_result.emit(CommandResult(command.request_id, None, command.operation, False, error="Wait aborted", command=command))
            self._emit(command, "cancelled", "Wait aborted by operator")
            self._active = None
            self._dispatch_next()

    def _audit(self, event: str, **fields: object) -> None:
        error = self.audit.write(event, **fields)
        if error is None:
            self._last_audit_error = None
        elif error != self._last_audit_error:
            self._last_audit_error = error
            self.message.emit(error)

    def _emit(
        self,
        command: DeviceCommand[Any] | WorkflowCommand,
        state: str,
        message: str = "",
        result: object = None,
    ) -> None:
        self.command_event.emit(
            CommandEvent(
                request_id=command.request_id,
                state=state,
                device=command.device,
                operation=command.operation,
                source=command.source,
                message=message,
                result=result,
                arguments=command.arguments,
            )
        )
        self._audit(
            state,
            request_id=command.request_id,
            source=command.source,
            device=command.device.value if command.device is not None else "workflow",
            operation=command.operation.value,
            message=message,
        )

    @Slot(object)
    def _status_received(self, status: DeviceStatus) -> None:
        self._statuses[status.device] = status
        self.status_changed.emit(dict(self._statuses))

    def _finish(
        self,
        request_id: str,
        ok: bool,
        value: object = None,
        error: str | None = None,
    ) -> None:
        if not self._active or self._active.command.request_id != request_id:
            return
        command = self._active.command
        if ok:
            expected = OPERATION_SPECS[command.operation].result_type
            if not isinstance(value, expected):
                ok = False
                error = (
                    f"{command.operation.value} returned {type(value).__name__}; "
                    f"expected {getattr(expected, '__name__', expected)}"
                )
                value = None
        self.command_result.emit(
            CommandResult(request_id, command.device, command.operation, ok, value, error, command)
        )
        self._emit(command, "completed" if ok else "failed", error or "", value)
        self._active = None
        self._dispatch_next()

    def _finish_urgent(
        self,
        request_id: str,
        ok: bool,
        value: object = None,
        error: str | None = None,
    ) -> bool:
        command = self._urgent.pop(request_id, None)
        if command is None:
            return False
        if ok:
            expected = OPERATION_SPECS[command.operation].result_type
            if not isinstance(value, expected):
                ok = False
                error = (
                    f"{command.operation.value} returned {type(value).__name__}; "
                    f"expected {getattr(expected, '__name__', expected)}"
                )
                value = None
        self.command_result.emit(
            CommandResult(request_id, command.device, command.operation, ok, value, error, command)
        )
        self._emit(command, "completed" if ok else "failed", error or "", value)
        return True

    @Slot(str, object)
    def _worker_succeeded(self, request_id: str, value: object) -> None:
        if self._flush is not None and self._flush.on_step(request_id, True, value):
            return
        if self._finish_urgent(request_id, True, value):
            return
        if self._finish_observation(request_id, True, value):
            return
        self._finish(request_id, True, value)

    @Slot(str, str)
    def _worker_failed(self, request_id: str, error: str) -> None:
        if self._flush is not None and self._flush.on_step(request_id, False, error=error):
            return
        if self._finish_urgent(request_id, False, error=error):
            return
        if self._finish_observation(request_id, False, error=error):
            return
        self._finish(request_id, False, error=error)

    @Slot(str, str)
    def _worker_cancelled(self, request_id: str, reason: str) -> None:
        if self._flush is not None and self._flush.on_step(request_id, False, error=reason):
            return
        if self._finish_observation(request_id, False, error=reason):
            return
        if not self._active or self._active.command.request_id != request_id:
            return
        command = self._active.command
        self.command_result.emit(
            CommandResult(request_id, command.device, command.operation, False, error=reason, command=command)
        )
        self._emit(command, "cancelled", reason)
        self._active = None
        self._dispatch_next()

    def statuses(self) -> dict:
        return dict(self._statuses)

    def shutdown(self) -> list[str]:
        self._closing = True
        self.temperature_monitor.stop()
        self._wait_timer.stop()
        if self._active is not None and isinstance(self._active.command, WorkflowCommand):
            self._emit(self._active.command, "cancelled", "Application shutdown")
            self._active = None
        if self._flush is not None:
            self._flush.dispose()
            if self._flush_command is not None:
                self._emit(self._flush_command, "cancelled", "Application shutdown")
            self._flush = None
            self._flush_command = None
        errors = []
        while self._queue:
            self._emit(self._queue.popleft().command, "cancelled", "Shutdown started")
        for worker in self.registry.all():
            worker.urgent_command_requested.emit(
                f"shutdown-{worker.device_id.value}",
                DeviceOperation.SAFE_STOP,
                NoArguments(),
            )
            worker.shutdown_requested.emit()
            if not worker._thread.wait(2000):
                errors.append(f"{worker.device_id.value}: thread did not terminate")
        self.experiments.close()
        self._audit("shutdown", errors=errors)
        return errors
