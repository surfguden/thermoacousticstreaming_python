from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol
from .models import SubRegion, SubRegionLimits
from ..common.logging import log_call

class CameraBackend(Protocol):
    def open_camera(self) -> object: ...

    def configure_exposure_time(self, exposure_ms: float) -> float: ...

    def configure_roi(self, roi: SubRegion | dict | None) -> None: ...

    def configure_snapshot(self, settings: dict | None = None) -> None: ...

    def configure_sequence(self, settings: dict | None) -> None: ...

    def configure_trigger_global_exposure(self, enabled: bool) -> None: ...

    def start_capture(self) -> None: ...

    def stop_capture(self) -> None: ...

    def capture_snapshot(self) -> object: ...

    def image_sequence(self, frame_count: int = 0, partial_capture_folder: Path | None = None) -> list[object]: ...

    def read_frame_timestamps(self) -> list[str]: ...

    def save_sequence(self, image_data: object, folder: Path) -> None: ...

    def get_camera_buffer_size(self) -> int: ...

    def read_subregion_limits_and_value(self) -> tuple[SubRegionLimits, SubRegion | dict]: ...

    def update_roi_limits(self, limits: SubRegionLimits | None = None) -> SubRegionLimits: ...

    def read_readout_time(self) -> float | None: ...

    def read_min_trigger_interval(self) -> float | None: ...

    def sw_trigger(self) -> None: ...

    def close(self) -> None: ...

@dataclass(slots=True)
class HamamatsuCamera:
    enabled: bool = True
    simulate: bool = True
    backend: CameraBackend | None = None
    exposure_ms: float = 1.0
    capturing: bool = False
    sequence_config: dict | None = None
    roi: SubRegion | dict | None = None
    roi_limits: SubRegionLimits = field(default_factory=SubRegionLimits)
    handle: object | None = None

    def initialize(self) -> None:
        if self.enabled:
            self.open_camera()

    def open_camera(self) -> object | None:
        if not self.enabled:
            self.handle = None
        elif self.backend is not None:
            self.handle = self.backend.open_camera()
        elif self.handle is None:
            self.handle = object()
        return self.handle

    def get_handle_out(self) -> object | None:
        return self.handle

    def configure(self, exposure_ms: float | None = None) -> None:
        if exposure_ms is not None:
            self.exposure_ms = exposure_ms

    def configure_exposure_time(self, exposure_ms: float) -> float:
        # Finding E: when a real backend is attached, self.exposure_ms now
        # tracks what the device actually applied (which can differ slightly
        # from the request due to DCAM's own exposure quantization), not the
        # raw request -- _check_camera_timing_budget() (application.py)
        # already reads this attribute, so it benefits from the more accurate
        # value with no changes needed there. Simulated/no-backend case has no
        # real device to read back from, so the requested value is used as-is,
        # same as before.
        if self.backend is not None:
            self.exposure_ms = self.backend.configure_exposure_time(exposure_ms)
        else:
            self.exposure_ms = exposure_ms
        return self.exposure_ms

    def configure_roi(self, roi: SubRegion | dict | None) -> None:
        if self.backend is not None:
            self.backend.configure_roi(roi)
        self.roi = roi

    def configure_snapshot(self, settings: dict | None = None) -> None:
        if self.backend is not None:
            self.backend.configure_snapshot(settings)

    def configure_sequence(self, settings: dict | None) -> None:
        if self.backend is not None:
            self.backend.configure_sequence(settings)
        self.sequence_config = settings

    def configure_trigger_global_exposure(self, enabled: bool) -> None:
        if self.backend is not None:
            self.backend.configure_trigger_global_exposure(enabled)

    def start_capture(self) -> None:
        if self.backend is not None:
            self.backend.start_capture()
        self.capturing = True

    def stop_capture(self) -> None:
        if self.backend is not None:
            self.backend.stop_capture()
        self.capturing = False

    def image_sequence(self, frame_count: int = 0, partial_capture_folder: Path | None = None) -> list[object]:
        if self.backend is not None:
            return self.backend.image_sequence(frame_count, partial_capture_folder)
        count = max(frame_count, 0)
        return [object() for _ in range(count)]

    def read_frame_timestamps(self) -> list[str]:
        if self.backend is not None:
            return self.backend.read_frame_timestamps()
        return []

    def capture_snapshot(self) -> object:
        if self.backend is not None:
            return self.backend.capture_snapshot()
        return object()

    def center_roi(self) -> None:
        if isinstance(self.roi, SubRegion):
            centered: SubRegion | dict = self.roi.centered(self.roi_limits)
        elif self.roi is None:
            centered = {"centered": True}
        else:
            centered = dict(self.roi)
            centered["centered"] = True
        self.configure_roi(centered)

    def save_sequence(self, image_data: object, folder: Path) -> None:
        if self.backend is not None:
            self.backend.save_sequence(image_data, folder)
            return
        folder.mkdir(parents=True, exist_ok=True)

    def get_camera_buffer_size(self) -> int:
        if self.backend is not None:
            return self.backend.get_camera_buffer_size()
        return 0

    def get_sub_region(self) -> SubRegion | dict:
        return self.roi or {}

    def read_subregion_limits_and_value(self) -> tuple[SubRegionLimits, SubRegion | dict]:
        if self.backend is not None:
            limits, roi = self.backend.read_subregion_limits_and_value()
            self.roi_limits = limits
            self.roi = roi
            return limits, roi
        return self.roi_limits, self.get_sub_region()

    def update_roi_limits(self, limits: SubRegionLimits | None = None) -> SubRegionLimits:
        if self.backend is not None:
            self.roi_limits = self.backend.update_roi_limits(limits)
            return self.roi_limits
        if limits is not None:
            self.roi_limits = limits
        return self.roi_limits

    def read_readout_time(self) -> float | None:
        if self.backend is not None:
            return self.backend.read_readout_time()
        return 0.0

    def read_min_trigger_interval(self) -> float | None:
        if self.backend is not None:
            return self.backend.read_min_trigger_interval()
        # Simulated camera paths do not consult a hardware capability readback.
        return 0.0

    def sw_trigg(self) -> None:
        if self.backend is not None:
            self.backend.sw_trigger()

    def cleanup(self) -> None:
        errors: list[str] = []
        try:
            self.stop_capture()
        except Exception as exc:
            errors.append(f"stop capture failed: {exc}")

        backend_closed = self.backend is None
        if self.backend is not None:
            try:
                self.backend.close()
                backend_closed = True
            except Exception as exc:
                errors.append(f"close failed: {exc}")

        if backend_closed:
            self.handle = None
            self.capturing = False
        if errors:
            raise RuntimeError("Hamamatsu camera cleanup failed: " + "; ".join(errors))
