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
        self.state.connected = True
        self.state.fault = None
        self._emit_status()

    def disconnect_device(self) -> None:
        self.safe_stop()
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
            self.disconnect_device()
        finally:
            self.stopped.emit()


class DriverDeviceWorker(DeviceWorker):
    """Base for real HAL workers with worker-thread-owned driver lifetimes."""

    def __init__(
        self,
        device_id: DeviceId,
        driver_factory: Callable[[], object],
        *,
        poll_interval_s: float = 0.0,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(device_id, poll_interval_s=poll_interval_s, parent=parent)
        self._driver_factory = driver_factory
        self._driver: object | None = None

    @property
    def driver(self) -> object:
        if self._driver is None:
            raise RuntimeError(f"{self.device_id.value} driver is not constructed")
        return self._driver

    @property
    def driver_constructed(self) -> bool:
        return self._driver is not None

    def initialize_driver(self) -> None:
        initialize = getattr(self.driver, "initialize", None)
        if not callable(initialize):
            raise RuntimeError(f"{self.device_id.value} driver has no initialize() method")
        initialize()

    def cleanup_driver(self) -> None:
        cleanup = getattr(self.driver, "cleanup", None)
        if not callable(cleanup):
            raise RuntimeError(f"{self.device_id.value} driver has no cleanup() method")
        cleanup()

    def connect_device(self) -> None:
        if self.state.connected:
            return
        if self._driver is None:
            driver = self._driver_factory()
            if driver is None:
                raise RuntimeError(f"{self.device_id.value} driver factory returned no driver")
            self._driver = driver
        try:
            self.initialize_driver()
        except Exception:
            self._driver = None
            raise
        self.state.connected = True
        self.state.fault = None
        self._emit_status()

    def disconnect_device(self) -> None:
        if self._driver is None:
            self.state = WorkerState()
            self._emit_status()
            return
        try:
            self.cleanup_driver()
        except Exception as exc:
            raise RuntimeError(f"driver cleanup failed: {exc}") from exc
        self._driver = None
        self.state = WorkerState()
        self._emit_status()
