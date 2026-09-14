from __future__ import annotations

from collections.abc import Mapping
import threading

from ..domain import DeviceId
from .ports import HardwarePorts


class SafetyCoordinator:
    """Best-effort stop and cleanup policy independent of the UI."""

    def __init__(self, ports: HardwarePorts, device_locks: Mapping[DeviceId, threading.RLock]) -> None:
        self._ports = ports
        self._device_locks = device_locks

    def safe_stop(self) -> list[str]:
        actions = (
            ("AD2 waveform stop", DeviceId.AD2, self._ports.ad2.stop_waveform),
            ("AD2 digital-output stop", DeviceId.AD2, self._ports.ad2.stop_digital_output),
            ("Pump stop", DeviceId.PUMP, self._ports.pump.stop_pump),
            ("Camera stop", DeviceId.CAMERA, self._ports.camera.stop_camera),
            ("TEC outputs off", DeviceId.TEC, self._ports.tec.disable_tec_outputs),
        )
        errors: list[str] = []
        for label, device, action in actions:
            try:
                with self._device_locks[device]:
                    action()
            except Exception as exc:
                errors.append(f"{label}: {exc}")
        return errors

    def shutdown(self) -> list[str]:
        errors = self.safe_stop()
        for port in reversed(self._ports.all()):
            try:
                with self._device_locks[port.device_id]:
                    port.disconnect()
            except Exception as exc:
                errors.append(f"{port.device_id.value} disconnect: {exc}")
        return errors
