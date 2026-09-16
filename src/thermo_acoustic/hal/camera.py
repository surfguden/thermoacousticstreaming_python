from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from ..application.commands import (
    CameraConfigureSnapshotArgs,
    CameraSnapshotResult,
    CameraTimingResult,
    DeviceOperation,
    NoArguments,
)
from ..domain.models import CameraReadback, DeviceId
from .base import DeviceWorker


class CameraWorker(DeviceWorker):
    def __init__(self, device_factory: Callable[[], object], parent=None) -> None:
        super().__init__(DeviceId.CAMERA, device_factory, readback_factory=CameraReadback, parent=parent)
        self.register(DeviceOperation.CAMERA_SNAPSHOT_CONFIGURE, self.configure_snapshot)
        self.register(DeviceOperation.CAMERA_SNAPSHOT_CAPTURE, self.capture_snapshot)
        self.register(DeviceOperation.CAMERA_CAPTURE_STOP, self.stop_capture)
        self.register(DeviceOperation.CAMERA_TIMING_READ, self.read_timing)

    def initialize_device(self) -> None:
        self.device.open_camera()

    def cleanup_device(self) -> None:
        self.device.close()

    def configure_snapshot(self, args: CameraConfigureSnapshotArgs) -> None:
        settings = None if args.exposure_ms is None else {"exposure_ms": args.exposure_ms}
        self.device.configure_snapshot(settings)
        self.state.configured = True
        self.state.readback = replace(
            self.state.readback, mode="snapshot", exposure_ms=args.exposure_ms
        )

    def capture_snapshot(self, _args: NoArguments) -> CameraSnapshotResult:
        self.state.active = True
        self.state.readback = replace(self.state.readback, mode="snapshot", capture_active=True)
        try:
            return CameraSnapshotResult(self.device.capture_snapshot())
        finally:
            self.state.active = False
            self.state.readback = replace(self.state.readback, capture_active=False)

    def stop_capture(self, _args: NoArguments) -> None:
        self.safe_stop()

    def read_timing(self, _args: NoArguments) -> CameraTimingResult:
        result = CameraTimingResult(
            buffer_frame_capacity=int(self.device.get_camera_buffer_size()),
            readout_time_s=self.device.read_readout_time(),
            minimum_trigger_interval_s=self.device.read_min_trigger_interval(),
        )
        self.state.readback = replace(
            self.state.readback,
            buffer_frame_capacity=result.buffer_frame_capacity,
            readout_time_s=result.readout_time_s,
            minimum_trigger_interval_s=result.minimum_trigger_interval_s,
        )
        return result

    def safe_stop(self) -> None:
        if self.device_constructed and self.state.connected:
            self.device.stop_capture()
        self.state.active = False
        self.state.readback = replace(self.state.readback, capture_active=False)
