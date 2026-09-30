"""Application-owned software-triggered Z-stack acquisition."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
import math

import numpy as np
from PIL import Image
from PySide6.QtCore import QObject, QTimer, Signal

from ..domain.models import ConnectionState, DeviceId, ZStageReadback
from .commands import (CameraConfigureRoiArgs, CameraConfigureSnapshotArgs,
                       DeviceCommand, DeviceOperation, NoArguments,
                       ZStageRelativeMoveArgs, ZStageSetPositionArgs)
from .experiment_storage import write_json


@dataclass(frozen=True)
class ZStackSettings:
    start_um: float
    stop_um: float
    points: int
    exposure_ms: float
    roi: tuple[int, int, int, int]
    folder: Path
    tolerance_um: float = 1.0
    position_timeout_s: float = 10.0

    def __post_init__(self) -> None:
        if not all(math.isfinite(value) for value in (
            self.start_um, self.stop_um, self.exposure_ms,
            self.tolerance_um, self.position_timeout_s,
        )):
            raise ValueError("Z stack numeric settings must be finite")
        if self.points < 2:
            raise ValueError("Z stack needs at least two points")
        if self.start_um == self.stop_um:
            raise ValueError("Z start and stop must differ")
        if self.exposure_ms <= 0 or self.tolerance_um <= 0 or self.position_timeout_s <= 0:
            raise ValueError("Exposure, position tolerance and timeout must be positive")
        if min(self.roi[:2]) < 0 or min(self.roi[2:]) < 1:
            raise ValueError("Camera ROI is invalid")

    def positions(self) -> tuple[float, ...]:
        return tuple(self.start_um + (self.stop_um - self.start_um) * i / (self.points - 1)
                     for i in range(self.points))


class ZStackRunner(QObject):
    changed = Signal(object)
    notice = Signal(str)

    def __init__(self, controller, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.state = "idle"
        self.detail = "Idle"
        self.current_index = -1
        self._settings: ZStackSettings | None = None
        self._pending = {}
        self._preview_active = False
        self._stop_requested = False
        self._deadline = 0.0
        self._records: list[dict] = []
        self._writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="z-stack-save")
        self._save_future: Future | None = None
        controller.command_result.connect(self._result)

    def status(self) -> dict:
        return {"state": self.state, "detail": self.detail,
                "current_index": self.current_index,
                "total": self._settings.points if self._settings else 0}

    def _publish(self, detail: str) -> None:
        self.detail = detail
        self.changed.emit(self.status())

    def _send(self, device, operation, args, done) -> None:
        command = DeviceCommand(device, operation, args, source="z-stack")
        self._pending[command.request_id] = done
        try:
            self.controller.submit(command)
        except Exception as exc:
            self._pending.pop(command.request_id, None)
            self._fail(str(exc))

    def _result(self, result) -> None:
        done = self._pending.pop(result.request_id, None)
        if done is None:
            return
        if not result.ok:
            self._fail(result.error or "Z stack device command failed")
            return
        done(result.value)

    def _require_devices(self) -> ZStageReadback:
        statuses = self.controller.statuses()
        if statuses[DeviceId.CAMERA].connection is not ConnectionState.CONNECTED:
            raise RuntimeError("Connect the camera before using Z stack")
        if statuses[DeviceId.Z_STAGE].connection is not ConnectionState.CONNECTED:
            raise RuntimeError("Connect the Z stage before using Z stack")
        stage = statuses[DeviceId.Z_STAGE].readback
        if not isinstance(stage, ZStageReadback) or not stage.closed_loop:
            raise RuntimeError("Confirm and enable closed-loop stage control first")
        return stage

    def start_preview(self, exposure_ms: float) -> None:
        if self.state == "running":
            raise RuntimeError("Z stack is running")
        self._require_devices()
        self._send(DeviceId.CAMERA, DeviceOperation.CAMERA_CONTINUOUS_CAPTURE,
                   CameraConfigureSnapshotArgs(exposure_ms), self._preview_started)

    def _preview_started(self, _value) -> None:
        self._preview_active = True
        self.state = "preview"
        self._publish("Live preview active")

    def stop_preview(self) -> None:
        if self.state == "running":
            raise RuntimeError("Stop the Z stack before stopping preview")
        self._send(DeviceId.CAMERA, DeviceOperation.CAMERA_CAPTURE_STOP,
                   NoArguments(), self._preview_stopped)

    def _preview_stopped(self, _value) -> None:
        self._preview_active = False
        self.state = "idle"
        self._publish("Live preview stopped")

    def move_to(self, position_um: float) -> None:
        if self.state == "running":
            raise RuntimeError("Manual Z moves are unavailable during acquisition")
        stage = self._require_devices()
        if stage.max_travel_um is not None and not 0 <= position_um <= stage.max_travel_um:
            raise ValueError("Requested Z position exceeds the controller's reported travel")
        self._send(DeviceId.Z_STAGE, DeviceOperation.Z_STAGE_POSITION_SET,
                   ZStageSetPositionArgs(position_um),
                   lambda _value: self._send(DeviceId.Z_STAGE, DeviceOperation.Z_STAGE_POSITION_READ,
                                             NoArguments(), lambda result: self._publish(f"Z = {result.position_um:.3f} µm")))

    def move_relative(self, delta_um: float) -> None:
        if self.state == "running":
            raise RuntimeError("Manual Z moves are unavailable during acquisition")
        self._require_devices()
        self._send(DeviceId.Z_STAGE, DeviceOperation.Z_STAGE_POSITION_RELATIVE,
                   ZStageRelativeMoveArgs(delta_um),
                   lambda _value: self._send(DeviceId.Z_STAGE, DeviceOperation.Z_STAGE_POSITION_READ,
                                             NoArguments(), lambda result: self._publish(f"Z = {result.position_um:.3f} µm")))

    def start(self, settings: ZStackSettings) -> None:
        if self.state == "running" or self.controller.experiments.status()["state"] == "running":
            raise RuntimeError("Another acquisition is running")
        if self.controller.count_preflight_active or self.controller.experiments.status()["syringe_preflight_active"]:
            raise RuntimeError("Wait for experiment preflight to finish")
        stage = self._require_devices()
        if stage.max_travel_um is not None and any(
            not 0 <= value <= stage.max_travel_um for value in settings.positions()
        ):
            raise ValueError("Z stack endpoints exceed the stage's reported travel")
        folder = settings.folder.expanduser().resolve()
        if not folder.is_dir() or any(folder.iterdir()):
            raise ValueError("Z stack output folder must exist and be empty")
        settings = replace(settings, folder=folder)
        self._settings = settings
        self._records = []
        self.current_index = -1
        self._stop_requested = False
        self.state = "running"
        write_json(folder / "metadata.json", {"state": "running", "settings": settings,
                                               "points": self._records})
        self._publish("Configuring Z stack camera")
        self._send(DeviceId.CAMERA, DeviceOperation.CAMERA_ROI_CONFIGURE,
                   CameraConfigureRoiArgs(*settings.roi),
                   lambda _value: self._send(DeviceId.CAMERA,
                       DeviceOperation.CAMERA_SNAPSHOT_CONFIGURE,
                       CameraConfigureSnapshotArgs(settings.exposure_ms),
                       lambda _value: self._send(DeviceId.CAMERA,
                           DeviceOperation.CAMERA_SETTINGS_READ, NoArguments(), self._camera_ready)))

    def _camera_ready(self, readback) -> None:
        if self._settings is None:
            return
        self._camera_settings = readback
        write_json(self._settings.folder / "metadata.json", {
            "state": "running", "settings": self._settings,
            "applied_camera_settings": readback, "points": self._records})
        self._resume_preview()

    def _resume_preview(self) -> None:
        self._send(DeviceId.CAMERA, DeviceOperation.CAMERA_CONTINUOUS_CAPTURE,
                   CameraConfigureSnapshotArgs(self._settings.exposure_ms),
                   lambda _value: self._preview_ready())

    def _preview_ready(self) -> None:
        self._preview_active = True
        self._next_point()

    def _next_point(self) -> None:
        if self._settings is None:
            return
        if self._stop_requested or self.current_index + 1 >= self._settings.points:
            self._finish("stopped" if self._stop_requested else "completed")
            return
        self.current_index += 1
        target = self._settings.positions()[self.current_index]
        self._deadline = monotonic() + self._settings.position_timeout_s
        self._publish(f"Moving to point {self.current_index + 1}/{self._settings.points}: {target:.3f} µm")
        self._send(DeviceId.Z_STAGE, DeviceOperation.Z_STAGE_POSITION_SET,
                   ZStageSetPositionArgs(target), self._move_accepted)

    def _move_accepted(self, result) -> None:
        target = self._settings.positions()[self.current_index]
        if abs(result.position_um - target) > self._settings.tolerance_um:
            self._fail("Stage clamped the requested point outside the position tolerance")
            return
        self._verify_position()

    def _verify_position(self) -> None:
        self._send(DeviceId.Z_STAGE, DeviceOperation.Z_STAGE_POSITION_READ,
                   NoArguments(), self._position_read)

    def _position_read(self, result) -> None:
        if self._stop_requested:
            self._finish("stopped")
            return
        target = self._settings.positions()[self.current_index]
        if abs(result.position_um - target) <= self._settings.tolerance_um:
            self._observed_position = result.position_um
            self._publish(f"Point {self.current_index + 1}: Z confirmed at {result.position_um:.3f} µm; capturing")
            self._send(DeviceId.CAMERA, DeviceOperation.CAMERA_SNAPSHOT_CAPTURE,
                       CameraConfigureSnapshotArgs(self._settings.exposure_ms), self._captured)
        elif monotonic() >= self._deadline:
            self._fail(f"Z did not reach {target:.3f} µm within the position timeout")
        else:
            QTimer.singleShot(100, self._verify_position)

    def _captured(self, result) -> None:
        frame = np.array(result.frame, copy=True)
        index = self.current_index
        record = {"index": index, "target_um": self._settings.positions()[index],
                  "observed_um": self._observed_position,
                  "captured_utc": datetime.now(timezone.utc).isoformat(),
                  "file": f"point_{index + 1:04d}.tif"}
        self._publish(f"Saving point {index + 1}/{self._settings.points}")
        self._save_future = self._writer.submit(self._save_frame, self._settings.folder / record["file"], frame)
        def check() -> None:
            if self._save_future is None:
                return
            if not self._save_future.done():
                QTimer.singleShot(20, check)
                return
            try:
                self._save_future.result()
            except Exception as exc:
                self._fail(f"Z stack image save failed: {exc}")
                return
            self._records.append(record)
            self._write_metadata(self.state)
            if self.state != "running":
                return
            self._resume_preview()
        check()

    @staticmethod
    def _save_frame(path: Path, frame: np.ndarray) -> None:
        Image.fromarray(frame).save(path)

    def _write_metadata(self, state: str) -> None:
        if self._settings is not None:
            write_json(self._settings.folder / "metadata.json", {
                "state": state, "settings": self._settings,
                "applied_camera_settings": getattr(self, "_camera_settings", None),
                "points": self._records})

    def stop(self) -> None:
        if self.state == "running":
            self._stop_requested = True
            self._publish("Stopping after the current device command")

    def abort_for_panic(self) -> None:
        if self.state == "running":
            self._stop_requested = True
            self._pending.clear()
            self._finish("aborted")

    def close(self) -> None:
        self.abort_for_panic()
        self._writer.shutdown(wait=True)

    def _finish(self, state: str) -> None:
        self._write_metadata(state)
        self.state = state
        self._publish(f"Z stack {state}; {len(self._records)} images saved")

    def _fail(self, message: str) -> None:
        if self.state == "running":
            self._write_metadata("failed")
        self.state = "failed"
        self._publish(message)
        self.notice.emit(message)
