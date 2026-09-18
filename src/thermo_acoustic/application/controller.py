from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from time import monotonic
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal, Slot

from ..domain.models import DeviceStatus, OperatingMode, ZStageReadback
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
    validate_command,
)


@dataclass(slots=True)
class _Pending:
    command: DeviceCommand[Any]
    queued_at: float


class ApplicationController(QObject):
    command_event = Signal(object)
    command_result = Signal(object)
    status_changed = Signal(object)
    message = Signal(str)

    def __init__(
        self,
        registry: DeviceRegistry,
        *,
        mode: OperatingMode,
        audit: AuditLogger | None = None,
        confirm_real_connection: Callable[[object], bool] | None = None,
        confirm_operation: Callable[[ConfirmationRequest], bool] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.registry = registry
        self.mode = mode
        self.audit = audit or AuditLogger()
        self.confirm_real_connection = confirm_real_connection or (lambda _: False)
        self.confirm_operation = confirm_operation or (lambda _: False)
        self._queue: deque[_Pending] = deque()
        self._active: _Pending | None = None
        self._urgent: dict[str, DeviceCommand[Any]] = {}
        self._closing = False
        self._statuses = {worker.device_id: worker.status() for worker in registry.all()}
        for worker in registry.all():
            worker.command_succeeded.connect(self._worker_succeeded)
            worker.command_failed.connect(self._worker_failed)
            worker.command_cancelled.connect(self._worker_cancelled)
            worker.status_changed.connect(self._status_received)

    def start(self) -> None:
        for worker in self.registry.all():
            worker._thread.start()
        self.status_changed.emit(dict(self._statuses))

    def submit(self, command: DeviceCommand[Any]) -> str:
        if self._closing:
            raise RuntimeError("Application shutdown has started")
        if not isinstance(command, DeviceCommand):
            raise TypeError("submit() requires a DeviceCommand")
        validate_command(command.device, command.operation, command.arguments)
        if (
            command.operation is DeviceOperation.CONNECT
            and self.mode is OperatingMode.REAL
            and not self.confirm_real_connection(command.device)
        ):
            self._emit(command, "failed", "Real device connection requires operator confirmation")
            return command.request_id
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
            if requirement and not self.confirm_operation(
                ConfirmationRequest(command, "Switch the Z-stage from open-loop to closed-loop control?")
            ):
                self._emit(command, "failed", "Z-stage closed-loop switch requires operator confirmation")
                return command.request_id
        if self._is_urgent(command.operation):
            self._urgent[command.request_id] = command
            self._emit(command, "queued")
            self._emit(command, "running")
            self.audit.write(
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
        self._active = self._queue.popleft()
        command = self._active.command
        self._emit(command, "running")
        self.audit.write(
            "execution_start",
            request_id=command.request_id,
            source=command.source,
            device=command.device.value,
            operation=command.operation.value,
        )
        self.registry.by_id(command.device).command_requested.emit(
            command.request_id, command.operation, command.arguments
        )

    def _emit(
        self,
        command: DeviceCommand[Any],
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
        self.audit.write(
            state,
            request_id=command.request_id,
            source=command.source,
            device=command.device.value,
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
        if self._finish_urgent(request_id, True, value):
            return
        self._finish(request_id, True, value)

    @Slot(str, str)
    def _worker_failed(self, request_id: str, error: str) -> None:
        if self._finish_urgent(request_id, False, error=error):
            return
        self._finish(request_id, False, error=error)

    @Slot(str, str)
    def _worker_cancelled(self, request_id: str, reason: str) -> None:
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
        self.audit.write("shutdown", errors=errors)
        return errors
