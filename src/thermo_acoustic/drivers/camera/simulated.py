from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from .roi import CameraMode, IntegerRange, SubRegion, SubRegionLimits


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
        self.trigger_global_exposure: bool | None = None
        self.sensor_width = 2048
        self.sensor_height = 1024

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
        limits, _current = self.read_subregion_limits_and_value()
        values = (
            ("horizontal offset", roi.horizontal_offset, limits.horizontal_offset),
            ("vertical offset", roi.vertical_offset, limits.vertical_offset),
            ("horizontal size", roi.horizontal_size, limits.horizontal_size),
            ("vertical size", roi.vertical_size, limits.vertical_size),
        )
        for name, value, limit in values:
            if not limit.minimum <= value <= limit.maximum:
                raise ValueError(f"camera ROI {name} is outside {limit.minimum}..{limit.maximum}")
            if (value - limit.minimum) % limit.increment:
                raise ValueError(f"camera ROI {name} must use increment {limit.increment}")
        if roi.horizontal_offset + roi.horizontal_size > self.sensor_width:
            raise ValueError("camera ROI horizontal offset + size exceeds sensor width")
        if roi.vertical_offset + roi.vertical_size > self.sensor_height:
            raise ValueError("camera ROI vertical offset + size exceeds sensor height")
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

    def configure_trigger_global_exposure(self, enabled: bool) -> None:
        self._require_initialized()
        self.trigger_global_exposure = bool(enabled)

    def start_capture(self) -> None:
        self._require_initialized()
        self.mode = CameraMode.SEQUENCE
        self.capture_active = True

    def capture_snapshot(self) -> np.ndarray:
        self._require_initialized()
        self.mode = CameraMode.SNAPSHOT
        self.capture_active = True
        self.frame_count += 1
        try:
            return self._simulated_frame()
        finally:
            self.capture_active = False

    def image_sequence(self, frame_count: int = 0) -> list[np.ndarray]:
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

    def read_subregion_limits_and_value(self) -> tuple[SubRegionLimits, SubRegion]:
        self._require_initialized()
        limits = SubRegionLimits(
            horizontal_offset=IntegerRange(0, self.sensor_width - 4, 4),
            vertical_offset=IntegerRange(0, self.sensor_height - 4, 4),
            horizontal_size=IntegerRange(4, self.sensor_width, 4),
            vertical_size=IntegerRange(4, self.sensor_height, 4),
        )
        roi = self.roi or SubRegion(
            horizontal_offset=0,
            vertical_offset=0,
            horizontal_size=self.sensor_width,
            vertical_size=self.sensor_height,
        )
        return limits, roi

    def stop_capture(self) -> None:
        self.capture_active = False

    def begin_buffered_sequence(self, frame_count: int) -> None:
        self._require_initialized()
        self.sequence_settings = {"frames": max(int(frame_count), 1)}
        self.start_capture()

    def poll_buffered_sequence_frame(self, timeout_ms: int) -> np.ndarray | None:
        del timeout_ms
        if not self.capture_active:
            raise RuntimeError("Buffered sequence is not active")
        return self._next_sequence_frame()

    def finish_buffered_sequence(self) -> tuple[str, ...]:
        self.stop_capture()
        return ()

    def begin_continuous_capture(self) -> None:
        self._require_initialized()
        self.start_capture()

    def poll_continuous_frame(self, timeout_ms: int) -> np.ndarray | None:
        return self.poll_buffered_sequence_frame(timeout_ms)

    def finish_continuous_capture(self) -> None:
        self.stop_capture()

    def read_all_settings(self) -> dict[str, Any]:
        self._require_initialized()
        _limits, roi = self.read_subregion_limits_and_value()
        return {
            "device": {"MODEL": "SimulatedCamera"},
            "properties": [
                {"name": "EXPOSURE TIME MS", "value": self.exposure_ms, "value_text": None},
                {"name": "SUBARRAY HPOS", "value": roi.horizontal_offset, "value_text": None},
                {"name": "SUBARRAY VPOS", "value": roi.vertical_offset, "value_text": None},
                {"name": "SUBARRAY HSIZE", "value": roi.horizontal_size, "value_text": None},
                {"name": "SUBARRAY VSIZE", "value": roi.vertical_size, "value_text": None},
            ],
        }

    def save_sequence(
        self,
        image_data: object,
        folder: Path,
        *,
        image_format: str = "frames",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        from PIL import Image

        folder.mkdir(parents=True, exist_ok=True)
        frames = list(image_data) if isinstance(image_data, (list, tuple)) else [image_data]
        arrays = [
            frame if isinstance(frame, np.ndarray) else np.full((8, 8), int(frame.get("frame_number", 0)), dtype=np.uint16)
            for frame in frames
        ]
        images = [Image.fromarray(frame) for frame in arrays]
        if image_format == "stacked":
            images[0].save(folder / "sequence.tiff", format="TIFF", save_all=True, append_images=images[1:])
        elif image_format == "frames":
            for index, image in enumerate(images):
                image.save(folder / f"frame_{index:05d}.tiff", format="TIFF")
        else:
            raise ValueError(f"Unsupported camera sequence format: {image_format}")
        (folder / "camera_settings.json").write_text(
            json.dumps(metadata or {}, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    def _next_sequence_frame(self) -> np.ndarray:
        self.frame_count += 1
        return self._simulated_frame()

    def _simulated_frame(self) -> np.ndarray:
        height = min((self.roi.vertical_size if self.roi else self.sensor_height), 128)
        width = min((self.roi.horizontal_size if self.roi else self.sensor_width), 128)
        y, x = np.indices((height, width), dtype=np.uint16)
        return (x + y + self.frame_count * 64).astype(np.uint16)

    def _require_initialized(self) -> None:
        if not self.initialized:
            raise RuntimeError("camera is not initialized")
