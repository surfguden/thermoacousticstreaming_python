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


class DeviceWorker(QObject):
    command_requested = Signal(str, object, object)
    shutdown_requested = Signal()
    command_succeeded = Signal(str, object)
    command_failed = Signal(str, str)
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
        self.command_requested.connect(self.execute)
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

    def connect_device(self) -> None:
        if self.state.connected:
            return
        if self._device is None:
            device = self._device_factory()
            if device is None:
                raise RuntimeError(f"{self.device_id.value} device factory returned no device")
            self._device = device
        try:
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

    @Slot(str, object, object)
    def execute(
        self,
        request_id: str,
        operation: DeviceOperation,
        arguments: object = NoArguments(),
    ) -> None:
        try:
            if operation is DeviceOperation.CONNECT:
                value = self.connect_device()
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
            self.state.fault = None
            self._emit_status()
            self.command_succeeded.emit(request_id, value)
        except Exception as exc:
            self.state.fault = str(exc)
            self._emit_status()
            self.command_failed.emit(request_id, str(exc))

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
            self.disconnect_device()
        finally:
            self.stopped.emit()
