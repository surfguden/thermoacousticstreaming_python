"""Connect several chosen devices one after another, reporting each device on its own.

Only coordination lives here: every device is connected with the same typed CONNECT command a
single Connect button would send (the caller builds it from the device's own inputs), through the
normal command queue. Nothing is retried, rolled back or disconnected, and no other device
operation is sent. A device that is already connected, or whose Connect is already queued or
running, is skipped. When Panic or closing starts, devices not yet submitted are not started;
a Connect already running is left to the existing cancel/timeout handling (a blocked SDK call
cannot be interrupted from here).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QObject, Signal

from ..domain.models import ConnectionState, DeviceId
from .commands import DeviceCommand, DeviceOperation

TERMINAL_STATES = frozenset({"connected", "already_connected", "already_connecting", "failed",
                             "not_started", "cancelled"})


@dataclass(frozen=True)
class ConnectOutcome:
    state: str  # waiting | connecting | one of TERMINAL_STATES
    detail: str = ""


class DeviceConnector(QObject):
    changed = Signal(object)   # {DeviceId: ConnectOutcome}, for the whole group
    finished = Signal(object)

    def __init__(self, controller, submit: Callable[[DeviceCommand], str] | None = None, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._submit = submit or controller.submit
        self._queue: deque[tuple[DeviceId, DeviceCommand]] = deque()
        self._outcomes: dict[DeviceId, ConnectOutcome] = {}
        self._current: tuple[DeviceId, str] | None = None
        self._halt_reason: str | None = None
        self._active = False
        controller.command_event.connect(self._event)
        controller.panic_changed.connect(self._panic_changed)

    @property
    def active(self) -> bool:
        return self._active

    def outcomes(self) -> dict[DeviceId, ConnectOutcome]:
        return dict(self._outcomes)

    def blocked_reason(self) -> str | None:
        """Why no new Connect can be started now (same conditions the command queue enforces)."""
        controller = self.controller
        if controller.close_requested or controller.shutdown_started:
            return "The application is closing"
        if controller.panic_status()["state"] == "stopping":
            return "Panic safe stop is in progress"
        if controller.experiments.batch_active:
            return "An experiment batch owns the instruments"
        if controller.z_stack.state == "running":
            return "A Z stack is running"
        if controller.count_preflight_active:
            return "A count preflight is running"
        return None

    def connect_devices(self, requests: dict[DeviceId, DeviceCommand | str]) -> None:
        """`requests`: one entry per chosen device, either its CONNECT command or a message saying why
        its inputs are not valid. The set and the commands are fixed here; later edits do not change them."""
        if self._active:
            raise RuntimeError("A device connection group is already running")
        if not requests:
            raise ValueError("Select at least one device")
        reason = self.blocked_reason()
        if reason:
            raise RuntimeError(reason)
        self._outcomes = {}
        self._halt_reason = None
        self._current = None
        self._queue.clear()
        for device in DeviceId:
            if device not in requests:
                continue
            request = requests[device]
            if isinstance(request, str):
                self._outcomes[device] = ConnectOutcome("failed", request)
            else:
                if request.operation is not DeviceOperation.CONNECT or request.device is not device:
                    raise ValueError(f"Not a CONNECT command for {device.value}")
                self._outcomes[device] = ConnectOutcome("waiting")
                self._queue.append((device, request))
        self._active = True
        self.changed.emit(self.outcomes())
        self._next()

    def _set(self, device: DeviceId, state: str, detail: str = "") -> None:
        self._outcomes[device] = ConnectOutcome(state, detail)

    def _next(self) -> None:
        while self._queue:
            device, command = self._queue.popleft()
            reason = self._halt_reason or self.blocked_reason()
            if reason:
                self._halt_reason = reason
                self._set(device, "not_started", reason)
                continue
            if self.controller.statuses()[device].connection is ConnectionState.CONNECTED:
                self._set(device, "already_connected", "Already connected; not opened again")
                continue
            if self.controller.has_pending_command(device, DeviceOperation.CONNECT):
                self._set(device, "already_connecting", "A Connect for this device is already in progress")
                continue
            # Set before submitting: the command's own events must find the current request.
            self._current = (device, command.request_id)
            try:
                self._submit(command)
            except Exception as exc:
                self._current = None
                self._set(device, "failed", f"Not submitted: {exc}")
                continue
            self._set(device, "connecting")
            self.changed.emit(self.outcomes())
            return
        self._active = False
        self._current = None
        self.changed.emit(self.outcomes())
        self.finished.emit(self.outcomes())

    def _panic_changed(self, status: dict) -> None:
        if self._active and status.get("state") == "stopping":
            self._halt_reason = "Panic safe stop started; this device was not connected"

    def _event(self, event) -> None:
        if self._current is None or event.request_id != self._current[1]:
            return
        if event.state not in {"completed", "failed", "cancelled"}:
            return
        device = self._current[0]
        self._current = None
        if event.state == "completed":
            self._set(device, "connected")
        elif event.state == "cancelled":
            self._set(device, "cancelled", event.message or "Cancelled")
        else:
            self._set(device, "failed", event.message or "Connect failed")
        self._next()
