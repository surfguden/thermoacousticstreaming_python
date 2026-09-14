from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from ..domain.models import ConnectionState, DeviceId, DeviceStatus


@dataclass(slots=True)
class WorkerState:
    connected: bool = False
    busy: bool = False
    configured: bool = False
    active: bool = False
    fault: str | None = None
    readings: dict[str, Any] = field(default_factory=dict)


class DeviceWorker(QObject):
    command_requested = Signal(str, str, object)
    shutdown_requested = Signal()
    command_succeeded = Signal(str, object)
    command_failed = Signal(str, str)
    status_changed = Signal(object)
    stopped = Signal()

    def __init__(self, device_id: DeviceId, *, poll_interval_s: float = 0.0, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.device_id = device_id
        self.poll_interval_s = poll_interval_s
        self.state = WorkerState()
        self._operations: dict[str, Callable[..., Any]] = {}
        self._timer: QTimer | None = None
        self.command_requested.connect(self.execute)
        self.shutdown_requested.connect(self.shutdown_in_thread)

    def register(self, name: str, handler: Callable[..., Any]) -> None:
        self._operations[name] = handler

    def status(self) -> DeviceStatus:
        connection = ConnectionState.CONNECTED if self.state.connected else ConnectionState.DISCONNECTED
        if self.state.fault:
            connection = ConnectionState.ERROR
        return DeviceStatus(self.device_id, connection, self.state.busy, self.state.configured,
                            self.state.active, self._summary(), dict(self.state.readings), self.state.fault)

    def _summary(self) -> str:
        if self.state.fault:
            return self.state.fault
        return "Connected" if self.state.connected else "Not connected"

    def _require_connected(self) -> None:
        if not self.state.connected:
            raise RuntimeError(f"{self.device_id.value} is not connected")

    def _emit_status(self) -> None:
        self.status_changed.emit(self.status())

    def connect_device(self) -> None:
        driver = getattr(self, "driver", None)
        if driver is not None and hasattr(driver, "initialize"):
            driver.initialize()
        self.state.connected = True
        self.state.fault = None
        self._emit_status()

    def disconnect_device(self) -> None:
        self.safe_stop()
        driver = getattr(self, "driver", None)
        if driver is not None and hasattr(driver, "cleanup"):
            driver.cleanup()
        self.state = WorkerState()
        self._emit_status()

    def safe_stop(self) -> None:
        self.state.active = False

    @Slot(str, object)
    def execute(self, request_id: str, operation: str, args: object = ()) -> None:
        try:
            if operation == "connect":
                value = self.connect_device()
            elif operation == "disconnect":
                value = self.disconnect_device()
            elif operation == "safe_stop":
                value = self.safe_stop()
            else:
                self._require_connected()
                handler = self._operations.get(operation)
                if handler is None:
                    raise ValueError(f"Unsupported {self.device_id.value} operation: {operation}")
                value = handler(*tuple(args))
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
            self.safe_stop()
            self.disconnect_device()
        finally:
            self.stopped.emit()
