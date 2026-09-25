"""One nonblocking TEC observation stream for graphing and recording."""

from __future__ import annotations

from datetime import datetime, timezone
from time import monotonic

from PySide6.QtCore import QObject, QTimer, Signal

from ..domain.models import ConnectionState, DeviceId, TecReadback


class TemperatureMonitor(QObject):
    sample = Signal(object)

    def __init__(self, controller, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._pending: str | None = None
        self._requested_at = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        controller.command_result.connect(self._result)

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _tick(self) -> None:
        if self.controller.statuses()[DeviceId.TEC].connection is not ConnectionState.CONNECTED:
            self._pending = None
            return
        if self._pending is not None:
            if monotonic() - self._requested_at >= 2:
                self.sample.emit(self._row(None, "TEC read delayed"))
            return
        try:
            self._pending = self.controller.observe_tec()
            self._requested_at = monotonic()
        except RuntimeError as exc:
            self.sample.emit(self._row(None, str(exc)))

    def _result(self, result) -> None:
        if result.request_id != self._pending:
            return
        self._pending = None
        readback = self.controller.statuses()[DeviceId.TEC].readback
        self.sample.emit(self._row(readback if result.ok else None,
                                   "" if result.ok else (result.error or "TEC read failed")))

    @staticmethod
    def _row(readback: TecReadback | None, error: str) -> dict:
        channels = {item.channel: item for item in readback.channels} if isinstance(readback, TecReadback) else {}
        return {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "monotonic_s": monotonic(),
            "channel_1_c": getattr(channels.get(1), "current_temperature_c", None),
            "channel_2_c": getattr(channels.get(2), "current_temperature_c", None),
            "channel_1_target_c": getattr(channels.get(1), "target_temperature_c", None),
            "channel_2_target_c": getattr(channels.get(2), "target_temperature_c", None),
            "error": error,
        }
