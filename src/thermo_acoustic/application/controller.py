from __future__ import annotations
from collections import deque
from dataclasses import dataclass
from time import monotonic
from PySide6.QtCore import QObject, Signal, Slot
from ..devices.registry import DeviceRegistry
from ..domain.models import DeviceStatus, OperatingMode
from .audit import AuditLogger
from .commands import CommandEvent, CommandResult, DeviceCommand

@dataclass(slots=True)
class _Pending:
    command: DeviceCommand
    queued_at: float

class ApplicationController(QObject):
    command_event = Signal(object); command_result = Signal(object); status_changed = Signal(object); message = Signal(str)
    def __init__(self, registry: DeviceRegistry, *, mode: OperatingMode, audit: AuditLogger | None = None, confirm_real_connection=None, parent=None) -> None:
        super().__init__(parent); self.registry, self.mode = registry, mode; self.audit = audit or AuditLogger(); self.confirm_real_connection = confirm_real_connection or (lambda _: False); self._queue: deque[_Pending] = deque(); self._active: _Pending | None = None; self._closing = False; self._statuses = {w.device_id: w.status() for w in registry.all()}
        for worker in registry.all(): worker.command_succeeded.connect(self._worker_succeeded); worker.command_failed.connect(self._worker_failed); worker.status_changed.connect(self._status_received)
    def start(self) -> None:
        for worker in self.registry.all(): worker._thread.start()
        self.status_changed.emit(dict(self._statuses))
    def submit(self, command: DeviceCommand) -> str:
        if self._closing: raise RuntimeError("Application shutdown has started")
        if command.operation == "connect" and self.mode is OperatingMode.REAL and not self.confirm_real_connection(command.device): self._emit(command, "failed", "Real device connection requires operator confirmation"); return command.request_id
        self._queue.append(_Pending(command, monotonic())); self._emit(command, "queued"); self._dispatch_next(); return command.request_id
    def _dispatch_next(self) -> None:
        if self._closing or self._active or not self._queue: return
        self._active = self._queue.popleft(); c = self._active.command; self._emit(c, "running"); self.audit.write("execution_start", request_id=c.request_id, source=c.source, device=c.device.value, operation=c.operation); self.registry.by_id(c.device).command_requested.emit(c.request_id, c.operation, c.args)
    def _emit(self, c: DeviceCommand, state: str, message: str = "", result=None) -> None:
        self.command_event.emit(CommandEvent(c.request_id, state, c.device, c.operation, c.source, message, result)); self.audit.write(state, request_id=c.request_id, source=c.source, device=c.device.value, operation=c.operation, message=message)
    @Slot(object)
    def _status_received(self, status: DeviceStatus) -> None: self._statuses[status.device] = status; self.status_changed.emit(dict(self._statuses))
    def _finish(self, request_id: str, ok: bool, value=None, error=None) -> None:
        if not self._active or self._active.command.request_id != request_id: return
        c = self._active.command; self.command_result.emit(CommandResult(request_id, c.device, c.operation, ok, value, error)); self._emit(c, "completed" if ok else "failed", error or "", value); self._active = None; self._dispatch_next()
    @Slot(str, object)
    def _worker_succeeded(self, request_id: str, value) -> None: self._finish(request_id, True, value)
    @Slot(str, str)
    def _worker_failed(self, request_id: str, error: str) -> None: self._finish(request_id, False, error=error)
    def statuses(self): return dict(self._statuses)
    def shutdown(self) -> list[str]:
        self._closing = True; errors = []
        while self._queue: self._emit(self._queue.popleft().command, "cancelled", "Shutdown started")
        for worker in self.registry.all():
            worker.shutdown_requested.emit()
            if not worker._thread.wait(2000): errors.append(f"{worker.device_id.value}: thread did not terminate")
        self.audit.write("shutdown", errors=errors); return errors
