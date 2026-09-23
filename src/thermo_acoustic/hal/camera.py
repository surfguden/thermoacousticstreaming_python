from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from time import monotonic

from ..application.commands import (
    CameraConfigureExposureArgs,
    CameraConfigureRoiArgs,
    CameraConfigureSequenceArgs,
    CameraConfigureSnapshotArgs,
    CameraExposureResult,
    CameraFrameProgress,
    CameraRoiResult,
    CameraSaveSequenceArgs,
    CameraSequenceSaveResult,
    CameraSnapshotResult,
    CameraSequenceResult,
    CameraTimingResult,
    DeviceOperation,
    NoArguments,
)
from ..domain.models import (
    CameraReadback,
    CameraRoiLimitsReadback,
    CameraRoiReadback,
    DeviceId,
    IntegerRange,
)
from .base import DeferredProgress, DeviceWorker


class CameraWorker(DeviceWorker):
    def __init__(self, device_factory: Callable[[], object], parent=None) -> None:
        super().__init__(DeviceId.CAMERA, device_factory, readback_factory=CameraReadback, parent=parent)
        self.register(DeviceOperation.CAMERA_SNAPSHOT_CONFIGURE, self.configure_snapshot)
        self.register(DeviceOperation.CAMERA_SNAPSHOT_CAPTURE, self.capture_snapshot)
        self.register(DeviceOperation.CAMERA_CONTINUOUS_CAPTURE, self.capture_continuous)
        self.register(DeviceOperation.CAMERA_SEQUENCE_CONFIGURE, self.configure_sequence)
        self.register(DeviceOperation.CAMERA_SEQUENCE_CAPTURE, self.capture_sequence)
        self.register(DeviceOperation.CAMERA_SEQUENCE_SAVE, self.save_sequence)
        self.register(DeviceOperation.CAMERA_CAPTURE_STOP, self.stop_capture)
        self.register(DeviceOperation.CAMERA_TIMING_READ, self.read_timing)
        self.register(DeviceOperation.CAMERA_EXPOSURE_CONFIGURE, self.configure_exposure)
        self.register(DeviceOperation.CAMERA_ROI_CONFIGURE, self.configure_roi)
        self._sequence_args: CameraConfigureSequenceArgs | None = None
        self._last_sequence_frames: tuple[object, ...] = ()
        self._last_sequence_metadata: dict[str, object] | None = None

    def initialize_device(self) -> None:
        self.device.open_camera()
        self._refresh_roi_readback()

    def cleanup_device(self) -> None:
        self.device.close()

    def configure_snapshot(self, args: CameraConfigureSnapshotArgs) -> None:
        settings = None if args.exposure_ms is None else {"exposure_ms": args.exposure_ms}
        self.device.configure_snapshot(settings)
        self.state.configured = True
        self.state.readback = replace(
            self.state.readback, mode="snapshot", exposure_ms=args.exposure_ms
        )

    def capture_snapshot(
        self, args: NoArguments | CameraConfigureSnapshotArgs
    ) -> CameraSnapshotResult:
        if isinstance(args, CameraConfigureSnapshotArgs):
            self.configure_snapshot(args)
        self.state.active = True
        self.state.readback = replace(self.state.readback, mode="snapshot", capture_active=True)
        try:
            return CameraSnapshotResult(self.device.capture_snapshot())
        finally:
            self.state.active = False
            self.state.readback = replace(self.state.readback, capture_active=False)

    def capture_continuous(self, args: CameraConfigureSnapshotArgs) -> object:
        self.configure_snapshot(args)
        self.device.begin_continuous_capture()
        self.state.active = True
        self.state.readback = replace(
            self.state.readback,
            mode="continuous",
            capture_active=True,
            captured_frame_count=0,
            sequence_frame_count=None,
        )
        request_id = self._executing_request_id
        captured = 0

        def cancel() -> None:
            self.device.finish_continuous_capture()
            self.state.active = False
            self.state.readback = replace(self.state.readback, capture_active=False)

        def step() -> DeferredProgress:
            nonlocal captured
            frame = self.device.poll_continuous_frame(
                max(1, min(100, int(args.poll_interval_s * 1000)))
            )
            if frame is not None:
                captured += 1
                self.state.readback = replace(
                    self.state.readback, captured_frame_count=captured
                )
                self._emit_status()
                if request_id is not None:
                    self.command_progress.emit(
                        request_id,
                        CameraFrameProgress(frame, captured, mode="continuous"),
                    )
            return DeferredProgress()

        return self.defer_operation(
            step, cancel=cancel, poll_interval_s=args.poll_interval_s
        )

    def configure_sequence(self, args: CameraConfigureSequenceArgs) -> None:
        settings = {"frames": args.frame_count}
        if args.exposure_ms is not None:
            settings["exposure_ms"] = args.exposure_ms
        if args.trigger is not None:
            trigger = args.trigger
            settings.update(
                trigger_source=trigger.source.value,
                trigger_polarity=trigger.polarity.value,
                trigger_active=trigger.active.value,
                trigger_mode="normal",
                trigger_times=trigger.trigger_times,
                trigger_delay_s=trigger.delay_s,
                masterpulse_mode=trigger.masterpulse_mode.value,
                masterpulse_source=trigger.masterpulse_source.value,
                masterpulse_interval_s=trigger.masterpulse_interval_s,
                masterpulse_burst_times=trigger.masterpulse_burst_times,
            )
            if trigger.global_exposure is not None:
                self.device.configure_trigger_global_exposure(trigger.global_exposure)
        self.device.configure_sequence(settings)
        self._sequence_args = args
        self.state.configured = True
        self.state.readback = replace(
            self.state.readback,
            mode="sequence",
            exposure_ms=(
                args.exposure_ms
                if args.exposure_ms is not None
                else self.state.readback.exposure_ms
            ),
            sequence_frame_count=args.frame_count,
            captured_frame_count=0,
        )

    def capture_sequence(
        self, command_args: NoArguments | CameraConfigureSequenceArgs
    ) -> object:
        if isinstance(command_args, CameraConfigureSequenceArgs):
            self.configure_sequence(command_args)
        if self._sequence_args is None:
            raise RuntimeError("Configure the camera sequence before capture")
        args = self._sequence_args
        frames: list[object] = []
        frame_deadline = monotonic() + args.frame_timeout_s
        self.device.begin_buffered_sequence(args.frame_count)
        self.state.active = True
        self.state.readback = replace(
            self.state.readback, capture_active=True, captured_frame_count=0
        )
        request_id = self._executing_request_id

        def cancel() -> None:
            self.device.finish_buffered_sequence()
            self.state.active = False
            self.state.readback = replace(self.state.readback, capture_active=False)

        def step() -> DeferredProgress:
            nonlocal frame_deadline
            timeout_ms = max(1, min(100, int(args.poll_interval_s * 1000)))
            frame = self.device.poll_buffered_sequence_frame(timeout_ms)
            if frame is None:
                if monotonic() >= frame_deadline:
                    raise TimeoutError(
                        f"Camera frame {len(frames) + 1}/{args.frame_count} timed out "
                        f"after {args.frame_timeout_s:.3f}s"
                    )
                return DeferredProgress()
            frames.append(frame)
            frame_deadline = monotonic() + args.frame_timeout_s
            self.state.readback = replace(
                self.state.readback, captured_frame_count=len(frames)
            )
            self._emit_status()
            if request_id is not None:
                self.command_progress.emit(
                    request_id,
                    CameraFrameProgress(
                        frame,
                        len(frames),
                        args.frame_count,
                        mode="sequence",
                    ),
                )
            if len(frames) < args.frame_count:
                return DeferredProgress()
            timestamps = self.device.finish_buffered_sequence()
            self._last_sequence_frames = tuple(frames)
            settings = self.device.read_all_settings()
            settings["sequence"] = {
                "frame_count": args.frame_count,
                "timestamps": list(timestamps),
            }
            self._last_sequence_metadata = settings
            self.state.active = False
            self.state.readback = replace(self.state.readback, capture_active=False)
            return DeferredProgress(
                True, CameraSequenceResult(tuple(frames), tuple(timestamps))
            )

        return self.defer_operation(
            step,
            cancel=cancel,
            poll_interval_s=args.poll_interval_s,
        )

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

    def configure_exposure(
        self, args: CameraConfigureExposureArgs
    ) -> CameraExposureResult:
        applied_ms = float(self.device.configure_exposure_time(args.exposure_ms))
        result = CameraExposureResult(applied_ms)
        self.state.configured = True
        self.state.readback = replace(self.state.readback, exposure_ms=applied_ms)
        return result

    def configure_roi(self, args: CameraConfigureRoiArgs) -> CameraRoiResult:
        if args.horizontal_offset < 0 or args.vertical_offset < 0:
            raise ValueError("camera ROI offsets must be non-negative")
        if args.horizontal_size <= 0 or args.vertical_size <= 0:
            raise ValueError("camera ROI dimensions must be positive")
        limits, current = self.device.read_subregion_limits_and_value()
        requested = {
            "horizontal_offset": args.horizontal_offset,
            "vertical_offset": args.vertical_offset,
            "horizontal_size": args.horizontal_size,
            "vertical_size": args.vertical_size,
        }
        if limits is not None:
            self._validate_roi(args, limits, current)
        self.device.configure_roi(requested)
        _limits, applied = self.device.read_subregion_limits_and_value()
        if isinstance(applied, dict):
            values = applied
        else:
            values = {
                "horizontal_offset": applied.horizontal_offset,
                "vertical_offset": applied.vertical_offset,
                "horizontal_size": applied.horizontal_size,
                "vertical_size": applied.vertical_size,
            }
        result = CameraRoiResult(
            horizontal_offset=int(values["horizontal_offset"]),
            vertical_offset=int(values["vertical_offset"]),
            horizontal_size=int(values["horizontal_size"]),
            vertical_size=int(values["vertical_size"]),
        )
        self.state.configured = True
        self.state.readback = replace(
            self.state.readback,
            roi=CameraRoiReadback(
                result.horizontal_offset,
                result.vertical_offset,
                result.horizontal_size,
                result.vertical_size,
            ),
        )
        return result

    def save_sequence(self, args: CameraSaveSequenceArgs) -> CameraSequenceSaveResult:
        if not self._last_sequence_frames or self._last_sequence_metadata is None:
            raise RuntimeError("No completed camera sequence is available to save")
        folder = Path(args.folder).expanduser()
        self.device.save_sequence(
            self._last_sequence_frames,
            folder,
            image_format=args.format.value,
            metadata=self._last_sequence_metadata,
        )
        return CameraSequenceSaveResult(
            str(folder), args.format, len(self._last_sequence_frames)
        )

    def _refresh_roi_readback(self) -> None:
        reader = getattr(self.device, "read_subregion_limits_and_value", None)
        if not callable(reader):
            return
        limits, roi = reader()
        if isinstance(roi, dict):
            roi_values = roi
        else:
            roi_values = {
                "horizontal_offset": roi.horizontal_offset,
                "vertical_offset": roi.vertical_offset,
                "horizontal_size": roi.horizontal_size,
                "vertical_size": roi.vertical_size,
            }
        if limits is None:
            self.state.readback = replace(
                self.state.readback,
                roi=CameraRoiReadback(
                    int(roi_values["horizontal_offset"]),
                    int(roi_values["vertical_offset"]),
                    int(roi_values["horizontal_size"]),
                    int(roi_values["vertical_size"]),
                ),
            )
            return
        self.state.readback = replace(
            self.state.readback,
            roi=CameraRoiReadback(
                int(roi_values["horizontal_offset"]), int(roi_values["vertical_offset"]),
                int(roi_values["horizontal_size"]), int(roi_values["vertical_size"]),
            ),
            roi_limits=CameraRoiLimitsReadback(
                self._range_readback(limits.horizontal_offset),
                self._range_readback(limits.vertical_offset),
                self._range_readback(limits.horizontal_size),
                self._range_readback(limits.vertical_size),
            ),
        )

    @staticmethod
    def _range_readback(value: object) -> IntegerRange:
        return IntegerRange(
            int(value.minimum), int(value.maximum), max(int(value.increment), 1)
        )

    @staticmethod
    def _validate_roi(args: CameraConfigureRoiArgs, limits: object, current: object) -> None:
        del current
        entries = (
            ("horizontal offset", args.horizontal_offset, limits.horizontal_offset),
            ("vertical offset", args.vertical_offset, limits.vertical_offset),
            ("horizontal size", args.horizontal_size, limits.horizontal_size),
            ("vertical size", args.vertical_size, limits.vertical_size),
        )
        for name, value, limit in entries:
            if not int(limit.minimum) <= value <= int(limit.maximum):
                raise ValueError(
                    f"camera ROI {name} must be within {limit.minimum}..{limit.maximum}"
                )
            increment = max(int(limit.increment), 1)
            if (value - int(limit.minimum)) % increment:
                raise ValueError(
                    f"camera ROI {name} must follow increment {increment} from {limit.minimum}"
                )
        if args.horizontal_offset + args.horizontal_size > int(limits.horizontal_size.maximum):
            raise ValueError("camera ROI horizontal offset + width exceeds the sensor")
        if args.vertical_offset + args.vertical_size > int(limits.vertical_size.maximum):
            raise ValueError("camera ROI vertical offset + height exceeds the sensor")

    def safe_stop(self) -> None:
        if self.device_constructed and self.state.connected:
            self.device.stop_capture()
        self.state.active = False
        self.state.readback = replace(self.state.readback, capture_active=False)
