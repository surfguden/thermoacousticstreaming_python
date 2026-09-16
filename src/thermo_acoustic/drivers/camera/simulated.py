from __future__ import annotations

from typing import Any

from .roi import CameraMode, SubRegion


class SimulatedCamera:
    def __init__(self, buffer_frames: int = 3) -> None:
        self.initialized = False
        self.capture_active = False
        self.frame_count = 0
        self.buffer_frames = max(int(buffer_frames), 1)
        self.mode = CameraMode.SNAPSHOT
        self.sequence_settings: dict[str, Any] | None = None
        self.exposure_ms = 0.0
        self.roi: SubRegion | None = None
        self.readout_time_s = 0.001
        self.minimum_trigger_interval_s = 0.002

    def open_camera(self) -> object:
        self.initialized = True
        return self

    def close(self) -> None:
        self.stop_capture()
        self.initialized = False

    def configure_exposure_time(self, exposure_ms: float) -> float:
        self._require_initialized()
        self.exposure_ms = max(float(exposure_ms), 0.0)
        return self.exposure_ms

    def configure_roi(self, roi: SubRegion | dict | None) -> None:
        self._require_initialized()
        if roi is None:
            return
        if isinstance(roi, dict):
            roi = SubRegion(
                horizontal_offset=int(roi.get("horizontal_offset", roi.get("x", 0)) or 0),
                vertical_offset=int(roi.get("vertical_offset", roi.get("y", 0)) or 0),
                horizontal_size=int(roi.get("horizontal_size", roi.get("width", 0)) or 0),
                vertical_size=int(roi.get("vertical_size", roi.get("height", 0)) or 0),
            )
        self.roi = roi

    def configure_snapshot(self, settings: dict | None = None) -> None:
        self._require_initialized()
        if settings and "exposure_ms" in settings:
            self.configure_exposure_time(float(settings["exposure_ms"]))
        self.sequence_settings = None
        self.mode = CameraMode.SNAPSHOT

    def configure_sequence(self, settings: dict | None = None) -> None:
        self._require_initialized()
        self.sequence_settings = dict(settings or {})
        if "exposure_ms" in self.sequence_settings:
            self.configure_exposure_time(float(self.sequence_settings["exposure_ms"]))
        self.mode = CameraMode.SEQUENCE

    def start_capture(self) -> None:
        self._require_initialized()
        self.mode = CameraMode.SEQUENCE
        self.capture_active = True

    def capture_snapshot(self) -> dict[str, int]:
        self._require_initialized()
        self.mode = CameraMode.SNAPSHOT
        self.capture_active = True
        self.frame_count += 1
        try:
            return {"frames": 1, "frame_number": self.frame_count}
        finally:
            self.capture_active = False

    def image_sequence(self, frame_count: int = 0) -> list[dict[str, int]]:
        self._require_initialized()
        count = max(int(frame_count), 1)
        self.mode = CameraMode.SEQUENCE
        started_here = not self.capture_active
        if started_here:
            self.start_capture()
        try:
            return [self._next_sequence_frame() for _ in range(count)]
        finally:
            if started_here:
                self.stop_capture()

    def read_frame_timestamps(self) -> list[str]:
        return []

    def get_camera_buffer_size(self) -> int:
        return self.buffer_frames

    def read_readout_time(self) -> float:
        self._require_initialized()
        return self.readout_time_s

    def read_min_trigger_interval(self) -> float:
        self._require_initialized()
        return self.minimum_trigger_interval_s

    def stop_capture(self) -> None:
        self.capture_active = False

    def _next_sequence_frame(self) -> dict[str, int]:
        self.frame_count += 1
        return {"frames": 1, "frame_number": self.frame_count}

    def _require_initialized(self) -> None:
        if not self.initialized:
            raise RuntimeError("camera is not initialized")
