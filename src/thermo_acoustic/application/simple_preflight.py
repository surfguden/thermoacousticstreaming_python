"""Operator-requested, count-only preflight for fixed-form series."""

from __future__ import annotations

from collections import deque
import json
from time import monotonic
from typing import Any, Callable

from PySide6.QtCore import QObject, QTimer, Signal

from ..domain.models import ConnectionState, DeviceId, PumpReadback
from .commands import (
    Ad2ExperimentDigitalArgs, CameraConfigureRoiArgs, CameraConfigureSequenceArgs,
    CameraConfigureSnapshotArgs, CameraSequenceTriggerArgs, CameraTriggerActive,
    CameraTriggerPolarity,
    CameraTriggerSource, DeviceCommand, DeviceOperation, NoArguments, PumpUnitArgs,
)
from .experiments import validate_definition


class SimpleSeriesPreflight(QObject):
    finished = Signal(bool, str, str)

    def __init__(self, controller, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._pending: dict[str, Callable[[Any], None]] = {}
        self._pairs: deque[tuple[dict, dict]] = deque()
        self._fingerprint = ""
        self._active = False
        self._recovery_pending: dict[str, str] = {}
        self._recovery_errors: list[str] = []
        self._recovery_message = ""
        self._recovery_camera_stopped = False
        self._recovery_preview_requested = False
        self._recovery_preview_restored = False
        self._guard = QTimer(self)
        self._guard.setSingleShot(True)
        self._guard.timeout.connect(lambda: self._finish(False, "Count preflight timed out"))
        controller.command_result.connect(self._result)

    def run(self, definition: dict) -> None:
        if self._active or self._recovery_message:
            raise RuntimeError("A count preflight is already running")
        if self.controller.count_preflight_active:
            raise RuntimeError("A count preflight is already running")
        if self.controller.experiments.status()["state"] == "running":
            raise RuntimeError("Stop the experiment batch before count preflight")
        expansion = validate_definition(definition)
        statuses = self.controller.statuses()
        for device in (DeviceId.CAMERA, DeviceId.AD2, DeviceId.PUMP, DeviceId.VALVE):
            if statuses[device].connection is not ConnectionState.CONNECTED:
                raise RuntimeError(f"Required device is not connected: {device.value}")
        ad2 = statuses[DeviceId.AD2].readback
        if ad2 is not None and (getattr(ad2, "waveform_running", False)
                                or getattr(ad2, "digital_output_running", False)):
            raise RuntimeError("Stop manual AD2 outputs before count preflight")
        fingerprint = json.dumps(definition, sort_keys=True, allow_nan=False)
        unique: dict[str, tuple[dict, dict]] = {}
        for item in expansion.experiments:
            camera = next(step["args"] for step in item.steps if step["type"] == "camera_configure")
            dio = next(step["args"]["dio"] for step in item.steps if step["type"] == "ad2_configure")
            unique[repr((camera, dio))] = camera, dio
        self._pairs = deque(unique.values())
        self._fingerprint = fingerprint
        self._active = True
        self.controller.count_preflight_active = True
        flushes: dict[int, float] = {}
        def visit(steps: Any) -> None:
            for step in steps:
                if step["type"] == "flush":
                    args = step["args"]
                    index = args["unit_index"]
                    flushes[index] = flushes.get(index, 0) + args["volume_ml"]
                elif step["type"] == "experiment":
                    visit(step["steps"])
                elif step["type"] == "parallel":
                    for branch in step["branches"]:
                        visit(branch)
        visit(expansion.steps)
        tasks = deque(index for index in sorted(flushes))
        def refresh() -> None:
            if not tasks:
                readback = self.controller.statuses()[DeviceId.PUMP].readback
                units = {unit.unit_index: unit for unit in readback.units} if isinstance(readback, PumpReadback) else {}
                for index, total in flushes.items():
                    unit = units.get(index)
                    if unit is None or unit.fill_level_ml is None or unit.is_pumping:
                        self._finish(False, f"Pump unit {index + 1} has no idle, readable syringe level")
                        return
                    if unit.fill_level_ml < total:
                        self._finish(False, f"Pump unit {index + 1} needs {total:g} mL; available {unit.fill_level_ml:g} mL")
                        return
                self._next_pair()
                return
            index = tasks.popleft()
            self._send(DeviceId.PUMP, DeviceOperation.PUMP_STATUS_READ, PumpUnitArgs(index),
                       lambda _value: self._send(DeviceId.PUMP, DeviceOperation.PUMP_FILL_LEVEL_READ,
                                                 PumpUnitArgs(index), lambda _value: refresh()))
        refresh()

    def abort_for_panic(self) -> None:
        """Relinquish camera/AD2 ownership; the controller performs urgent stops."""
        if not self._active and not self._recovery_message:
            return
        self._active = False
        self._guard.stop()
        self._pending.clear()
        self._recovery_pending.clear()
        self._recovery_message = ""
        self.controller.count_preflight_active = False
        self.finished.emit(False, "Cancelled by Panic; instrument stops are in progress", self._fingerprint)

    def _next_pair(self) -> None:
        if not self._active:
            return
        if not self._pairs:
            self._finish(True, "All planned exposure settings collected N timestamped frames.")
            return
        camera, dio = self._pairs.popleft()
        roi = camera.get("roi")
        def configure(_value=None) -> None:
            trigger = CameraSequenceTriggerArgs(source=CameraTriggerSource.EXTERNAL,
                polarity=CameraTriggerPolarity.POSITIVE, active=CameraTriggerActive.EDGE,
                global_exposure=camera["global_exposure"])
            expected = dio["camera_delay_s"] + dio["frame_count"] / dio["frame_rate_hz"]
            args = CameraConfigureSequenceArgs(camera["frame_count"], camera["exposure_ms"],
                max(0.5, dio["camera_delay_s"] + 2 / dio["frame_rate_hz"]), trigger=trigger)
            self._send(DeviceId.CAMERA, DeviceOperation.CAMERA_SEQUENCE_CONFIGURE, args,
                lambda _value: self._send(DeviceId.AD2, DeviceOperation.AD2_EXPERIMENT_DIGITAL_CONFIGURE,
                    Ad2ExperimentDigitalArgs(dio["frame_count"], dio["frame_rate_hz"],
                                             dio["camera_delay_s"], led_enabled=False),
                    lambda _value: self._send(DeviceId.CAMERA, DeviceOperation.CAMERA_SEQUENCE_ARM,
                        NoArguments(), lambda _value: self._send(DeviceId.AD2,
                            DeviceOperation.AD2_DIGITAL_OUTPUT_START, NoArguments(),
                            lambda _value: self._send(DeviceId.AD2,
                                DeviceOperation.AD2_SOFTWARE_TRIGGER, NoArguments(),
                                lambda _value: self._collect(camera, expected))))))
        if roi is None:
            configure()
        else:
            self._send(DeviceId.CAMERA, DeviceOperation.CAMERA_ROI_CONFIGURE,
                       CameraConfigureRoiArgs(roi["x"], roi["y"], roi["width"], roi["height"]), configure)

    def _collect(self, camera: dict, expected_window: float) -> None:
        started = monotonic()
        self._guard.start(round(max(2.0, expected_window * 1.5 + 1) * 1000))
        def check(value: Any) -> None:
            self._guard.stop()
            count = camera["frame_count"]
            if (len(value.frames) != count or len(value.timestamps) != count
                    or any(not stamp for stamp in value.timestamps)):
                self._finish(False, f"Count preflight received {len(value.frames)} of {count} timestamped frames")
                return
            if monotonic() - started > max(2.0, expected_window * 1.5 + 1):
                self._finish(False, "Count preflight exceeded its expected frame window")
                return
            self._send(DeviceId.AD2, DeviceOperation.AD2_DIGITAL_OUTPUT_STOP, NoArguments(),
                       lambda _value: self._next_pair())
        self._send(DeviceId.CAMERA, DeviceOperation.CAMERA_SEQUENCE_COLLECT, NoArguments(), check)

    def _send(self, device: DeviceId, operation: DeviceOperation, args: Any,
              callback: Callable[[Any], None]) -> None:
        if not self._active:
            return
        command = DeviceCommand(device, operation, args, source="experiment-preflight")
        self._pending[command.request_id] = callback
        try:
            self.controller.submit(command)
        except Exception as exc:
            self._pending.pop(command.request_id, None)
            self._finish(False, str(exc))

    def _result(self, result: Any) -> None:
        recovery = self._recovery_pending.pop(result.request_id, None)
        if recovery is not None:
            if not result.ok:
                self._recovery_errors.append(f"{recovery}: {result.error or 'command failed'}")
            elif recovery == "camera stop":
                self._recovery_camera_stopped = True
            elif recovery == "camera preview":
                self._recovery_preview_restored = True
            self._continue_recovery()
            return
        callback = self._pending.pop(result.request_id, None)
        if callback is None or not self._active:
            return
        if result.ok:
            callback(result.value)
        else:
            self._finish(False, result.error or "Count preflight command failed")

    def _finish(self, ok: bool, message: str) -> None:
        if not self._active:
            return
        self._active = False
        self._guard.stop()
        self._pending.clear()
        if not ok:
            self._recovery_message = message
            self._recovery_errors = []
            self._recovery_camera_stopped = False
            self._recovery_preview_requested = False
            self._recovery_preview_restored = False
            for device in (DeviceId.AD2, DeviceId.CAMERA):
                # A failed worker command changes its status to ERROR while the
                # hardware is still connected. It must still receive SAFE_STOP.
                if self.controller.statuses()[device].connection is ConnectionState.DISCONNECTED:
                    continue
                command = DeviceCommand(device, DeviceOperation.SAFE_STOP,
                                        NoArguments(), source="experiment-preflight")
                self._recovery_pending[command.request_id] = f"{device.value} stop"
                try:
                    self.controller.submit(command)
                except Exception as exc:
                    self._recovery_pending.pop(command.request_id, None)
                    self._recovery_errors.append(f"{device.value} stop: {exc}")
            self._continue_recovery()
            return
        self.controller.count_preflight_active = False
        if self.controller.statuses()[DeviceId.CAMERA].connection is ConnectionState.CONNECTED:
            try:
                self.controller.submit(DeviceCommand(DeviceId.CAMERA,
                    DeviceOperation.CAMERA_CONTINUOUS_CAPTURE, CameraConfigureSnapshotArgs(),
                    source="experiment-preflight"))
            except RuntimeError:
                pass
        self.finished.emit(ok, message, self._fingerprint)

    def _continue_recovery(self) -> None:
        if self._recovery_pending:
            return
        if not self._recovery_preview_requested and self._recovery_camera_stopped:
            self._recovery_preview_requested = True
            if self.controller.statuses()[DeviceId.CAMERA].connection is ConnectionState.CONNECTED:
                command = DeviceCommand(DeviceId.CAMERA, DeviceOperation.CAMERA_CONTINUOUS_CAPTURE,
                                        CameraConfigureSnapshotArgs(), source="experiment-preflight")
                self._recovery_pending[command.request_id] = "camera preview"
                try:
                    self.controller.submit(command)
                except Exception as exc:
                    self._recovery_pending.pop(command.request_id, None)
                    self._recovery_errors.append(f"camera preview: {exc}")
                    self._continue_recovery()
                return
            self._recovery_errors.append("camera remains unavailable after stop")
        if self._recovery_errors:
            detail = f"; recovery errors: {'; '.join(self._recovery_errors)}"
        elif self._recovery_preview_restored:
            detail = "; camera preview restored"
        else:
            detail = "; camera preview not restored"
        message = self._recovery_message + detail
        self._recovery_message = ""
        self.controller.count_preflight_active = False
        self.finished.emit(False, message, self._fingerprint)
