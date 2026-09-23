from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from ..domain.models import ConnectionState, DeviceId, DeviceStatus
from ..application.commands import DeviceOperation, NoArguments


@dataclass(slots=True)
class WorkerState:
    connected: bool = False
    busy: bool = False
    configured: bool = False
    active: bool = False
    fault: str | None = None
    readback: object | None = None


@dataclass(frozen=True, slots=True)
class DeferredProgress:
    done: bool = False
    value: object = None


class _DeferredMarker:
    pass


_DEFERRED = _DeferredMarker()


class DeviceWorker(QObject):
    command_requested = Signal(str, object, object)
    urgent_command_requested = Signal(str, object, object)
    shutdown_requested = Signal()
    command_succeeded = Signal(str, object)
    command_failed = Signal(str, str)
    command_cancelled = Signal(str, str)
    command_progress = Signal(str, object)
    status_changed = Signal(object)
    stopped = Signal()

    def __init__(
        self,
        device_id: DeviceId,
        device_factory: Callable[[], object],
        *,
        readback_factory: Callable[[], object] | None = None,
        poll_interval_s: float = 0.0,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.device_id = device_id
        self._device_factory = device_factory
        self._device: object | None = None
        self.poll_interval_s = poll_interval_s
        self._readback_factory = readback_factory or (lambda: None)
        self.state = WorkerState(readback=self._readback_factory())
        self._operations: dict[DeviceOperation, Callable[[object], Any]] = {}
        self._timer: QTimer | None = None
        self._operation_timer: QTimer | None = None
        self._executing_request_id: str | None = None
        self._deferred_request_id: str | None = None
        self._deferred_step: Callable[[], DeferredProgress] | None = None
        self._deferred_cancel: Callable[[], None] | None = None
        self._deferred_interval_ms = 0
        self.command_requested.connect(self.execute)
        self.urgent_command_requested.connect(self.execute_urgent)
        self.shutdown_requested.connect(self.shutdown_in_thread)

    def register(self, name: DeviceOperation, handler: Callable[[object], Any]) -> None:
        self._operations[name] = handler

    def status(self) -> DeviceStatus:
        connection = ConnectionState.CONNECTED if self.state.connected else ConnectionState.DISCONNECTED
        if self.state.fault:
            connection = ConnectionState.ERROR
        return DeviceStatus(
            self.device_id,
            connection,
            self.state.busy,
            self.state.configured,
            self.state.active,
            self._summary(),
            self.state.readback,
            self.state.fault,
        )

    def _summary(self) -> str:
        if self.state.fault:
            return self.state.fault
        return "Connected" if self.state.connected else "Not connected"

    def _require_connected(self) -> None:
        if not self.state.connected:
            raise RuntimeError(f"{self.device_id.value} is not connected")

    def _emit_status(self) -> None:
        self.status_changed.emit(self.status())

    @property
    def device(self) -> object:
        if self._device is None:
            raise RuntimeError(f"{self.device_id.value} device is not constructed")
        return self._device

    @property
    def device_constructed(self) -> bool:
        return self._device is not None

    def initialize_device(self) -> None:
        initialize = getattr(self.device, "initialize", None)
        if not callable(initialize):
            raise RuntimeError(f"{self.device_id.value} device has no initialize() method")
        initialize()

    def cleanup_device(self) -> None:
        cleanup = getattr(self.device, "cleanup", None)
        if not callable(cleanup):
            raise RuntimeError(f"{self.device_id.value} device has no cleanup() method")
        cleanup()

    def prepare_connection(self, device: object, arguments: object) -> None:
        """Validate/apply connection inputs before initializing a device."""
        del device, arguments

    def connect_device(self, arguments: object = NoArguments()) -> None:
        if self.state.connected:
            return
        if self._device is None:
            device = self._device_factory()
            if device is None:
                raise RuntimeError(f"{self.device_id.value} device factory returned no device")
            self._device = device
        try:
            self.prepare_connection(self._device, arguments)
            self.initialize_device()
        except Exception:
            self._device = None
            raise
        self.state.connected = True
        self.state.fault = None
        self._emit_status()

    def disconnect_device(self) -> None:
        if self._device is None:
            self.state = WorkerState(readback=self._readback_factory())
            self._emit_status()
            return
        try:
            self.cleanup_device()
        except Exception as exc:
            raise RuntimeError(f"device cleanup failed: {exc}") from exc
        self._device = None
        self.state = WorkerState(readback=self._readback_factory())
        self._emit_status()

    def safe_stop(self) -> None:
        self.state.active = False

    def defer_operation(
        self,
        step: Callable[[], DeferredProgress],
        *,
        cancel: Callable[[], None],
        poll_interval_s: float,
    ) -> _DeferredMarker:
        if self._executing_request_id is None or self._deferred_request_id is not None:
            raise RuntimeError("A deferred operation is already active")
        self._deferred_request_id = self._executing_request_id
        self._deferred_step = step
        self._deferred_cancel = cancel
        self._deferred_interval_ms = max(1, int(poll_interval_s * 1000))
        if self._operation_timer is None:
            self._operation_timer = QTimer(self)
            self._operation_timer.setSingleShot(True)
            self._operation_timer.timeout.connect(self._advance_deferred)
        self._operation_timer.start(0)
        return _DEFERRED

    def _clear_deferred(self) -> None:
        if self._operation_timer:
            self._operation_timer.stop()
        self._deferred_request_id = None
        self._deferred_step = None
        self._deferred_cancel = None

    @Slot()
    def _advance_deferred(self) -> None:
        request_id = self._deferred_request_id
        step = self._deferred_step
        if request_id is None or step is None:
            return
        try:
            progress = step()
            if not isinstance(progress, DeferredProgress):
                raise TypeError("Deferred operation step must return DeferredProgress")
            if not progress.done:
                self._operation_timer.start(self._deferred_interval_ms)
                return
            self._clear_deferred()
            self.state.busy = False
            self.state.fault = None
            self._emit_status()
            self.command_succeeded.emit(request_id, progress.value)
        except Exception as exc:
            cancel = self._deferred_cancel
            self._clear_deferred()
            if cancel is not None:
                try:
                    cancel()
                except Exception as cleanup_exc:
                    exc = RuntimeError(f"{exc}; cleanup failed: {cleanup_exc}")
            self.state.busy = False
            self.state.fault = str(exc)
            self._emit_status()
            self.command_failed.emit(request_id, str(exc))

    @Slot(str, object, object)
    def execute(
        self,
        request_id: str,
        operation: DeviceOperation,
        arguments: object = NoArguments(),
    ) -> None:
        self._executing_request_id = request_id
        self.state.busy = True
        self._emit_status()
        try:
            if operation is DeviceOperation.CONNECT:
                value = self.connect_device(arguments)
            elif operation is DeviceOperation.DISCONNECT:
                value = self.disconnect_device()
            elif operation is DeviceOperation.SAFE_STOP:
                value = self.safe_stop()
            else:
                self._require_connected()
                handler = self._operations.get(operation)
                if handler is None:
                    raise ValueError(
                        f"Unsupported {self.device_id.value} operation: {operation.value}"
                    )
                value = handler(arguments)
            if value is _DEFERRED:
                return
            self.state.busy = False
            self.state.fault = None
            self._emit_status()
            self.command_succeeded.emit(request_id, value)
        except Exception as exc:
            self.state.busy = False
            self.state.fault = str(exc)
            self._emit_status()
            self.command_failed.emit(request_id, str(exc))
        finally:
            self._executing_request_id = None

    @Slot(str, object, object)
    def execute_urgent(
        self,
        request_id: str,
        operation: DeviceOperation,
        arguments: object = NoArguments(),
    ) -> None:
        active_request_id = self._deferred_request_id
        if operation is DeviceOperation.ABORT_ACTIVE and active_request_id is None:
            self.command_failed.emit(request_id, f"{self.device_id.value} has no abortable operation")
            return

        cancel_error: Exception | None = None
        if active_request_id is not None:
            cancel = self._deferred_cancel
            self._clear_deferred()
            try:
                if cancel is not None:
                    cancel()
            except Exception as exc:
                cancel_error = exc
            self.state.busy = False

        urgent_error: Exception | None = cancel_error
        urgent_value: object = None
        try:
            if operation is DeviceOperation.ABORT_ACTIVE:
                pass
            elif operation is DeviceOperation.SAFE_STOP:
                urgent_value = self.safe_stop()
            else:
                self._require_connected()
                handler = self._operations.get(operation)
                if handler is None:
                    raise ValueError(
                        f"Unsupported urgent {self.device_id.value} operation: {operation.value}"
                    )
                urgent_value = handler(arguments)
        except Exception as exc:
            urgent_error = exc if urgent_error is None else RuntimeError(
                f"{urgent_error}; urgent action failed: {exc}"
            )

        self.state.fault = None if urgent_error is None else str(urgent_error)
        self._emit_status()
        if urgent_error is None:
            self.command_succeeded.emit(request_id, urgent_value)
        else:
            self.command_failed.emit(request_id, str(urgent_error))
        if active_request_id is not None:
            self.command_cancelled.emit(
                active_request_id,
                f"Cancelled by {operation.value} ({request_id})",
            )

    @Slot()
    def start_polling(self) -> None:
        if self.poll_interval_s <= 0:
            return
        self._timer = QTimer(self)
        self._timer.setInterval(max(50, int(self.poll_interval_s * 1000)))
        self._timer.timeout.connect(self.poll_once)
        self._timer.start()

    @Slot()
    def poll_once(self) -> None:
        # Polling is intentionally passive until a concrete worker opts in.
        if self.state.connected:
            self._emit_status()

    @Slot()
    def stop_worker(self) -> None:
        if self._timer:
            self._timer.stop()
        self.stopped.emit()

    @Slot()
    def shutdown_in_thread(self) -> None:
        try:
            if self._deferred_request_id is not None:
                active_request_id = self._deferred_request_id
                cancel = self._deferred_cancel
                self._clear_deferred()
                if cancel is not None:
                    cancel()
                self.command_cancelled.emit(active_request_id, "Application shutdown")
            self.disconnect_device()
        finally:
            self.stopped.emit()
