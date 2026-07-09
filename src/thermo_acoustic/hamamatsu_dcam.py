from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import sys
from typing import Any

from .camera import MinMaxInc, SubRegion, SubRegionLimits


class HamamatsuDcamError(RuntimeError):
    pass


def _default_sdk_python_path() -> Path:
    return Path(__file__).resolve().parents[2] / "dcamsdk4" / "samples" / "python"


@dataclass(slots=True)
class HamamatsuDcamBackend:
    device_index: int = 0
    sdk_python_path: Path = field(default_factory=_default_sdk_python_path)
    buffer_frames: int = 3
    timeout_ms: int = 1000
    dcamapi: Any = None
    dcam: Any = None
    dcam_module: Any = None
    initialized: bool = False
    sequence_settings: dict[str, Any] | None = None
    capture_active: bool = False
    allocated_buffer_frames: int = 0

    def _load_sdk(self) -> None:
        if self.dcam_module is not None:
            return
        path = str(self.sdk_python_path)
        if path not in sys.path:
            sys.path.insert(0, path)
        try:
            import dcam as dcam_module
        except Exception as exc:
            raise HamamatsuDcamError(
                f"Could not import Hamamatsu DCAM Python wrapper from {self.sdk_python_path}. "
                "Check that dcamsdk4 is present and dcamapi.dll is installed or on PATH."
            ) from exc
        self.dcam_module = dcam_module
        self.dcamapi = dcam_module.Dcamapi

    def _check(self, ok: Any, operation: str) -> None:
        if ok is False:
            err = None
            if self.dcam is not None:
                err = self.dcam.lasterr()
            elif self.dcamapi is not None:
                err = self.dcamapi.lasterr()
            raise HamamatsuDcamError(f"{operation} failed: {err}")

    def open_camera(self) -> object:
        self._load_sdk()
        if not self.initialized:
            self._check(self.dcamapi.init(), "Dcamapi.init")
            self.initialized = True
        if self.dcam is None:
            self.dcam = self.dcam_module.Dcam(self.device_index)
        if not self.dcam.is_opened():
            self._check(self.dcam.dev_open(), "Dcam.dev_open")
        return self.dcam

    def configure_exposure_time(self, exposure_ms: float) -> None:
        self.open_camera()
        self._check(
            self.dcam.prop_setgetvalue(self.dcam_module.DCAM_IDPROP.EXPOSURETIME, max(exposure_ms, 0.0) / 1000.0),
            "set EXPOSURETIME",
        )

    def configure_roi(self, roi: SubRegion | dict | None) -> None:
        if roi is None:
            return
        self.open_camera()
        if isinstance(roi, dict):
            roi = SubRegion(
                horizontal_offset=int(roi.get("horizontal_offset", roi.get("x", 0)) or 0),
                vertical_offset=int(roi.get("vertical_offset", roi.get("y", 0)) or 0),
                horizontal_size=int(roi.get("horizontal_size", roi.get("width", 0)) or 0),
                vertical_size=int(roi.get("vertical_size", roi.get("height", 0)) or 0),
            )
        props = self.dcam_module.DCAM_IDPROP
        mode = self.dcam_module.DCAMPROP.MODE
        self._check(self.dcam.prop_setvalue(props.SUBARRAYMODE, mode.OFF), "set SUBARRAYMODE off")
        if roi.horizontal_size > 0:
            self._check(self.dcam.prop_setgetvalue(props.SUBARRAYHSIZE, roi.horizontal_size), "set SUBARRAYHSIZE")
        if roi.vertical_size > 0:
            self._check(self.dcam.prop_setgetvalue(props.SUBARRAYVSIZE, roi.vertical_size), "set SUBARRAYVSIZE")
        self._check(self.dcam.prop_setgetvalue(props.SUBARRAYHPOS, max(roi.horizontal_offset, 0)), "set SUBARRAYHPOS")
        self._check(self.dcam.prop_setgetvalue(props.SUBARRAYVPOS, max(roi.vertical_offset, 0)), "set SUBARRAYVPOS")
        self._check(self.dcam.prop_setvalue(props.SUBARRAYMODE, mode.ON), "set SUBARRAYMODE on")

    def configure_snapshot(self, settings: dict | None = None) -> None:
        if settings and "exposure_ms" in settings:
            self.configure_exposure_time(float(settings["exposure_ms"]))
        else:
            self.open_camera()

    def configure_sequence(self, settings: dict | None) -> None:
        self.open_camera()
        self.sequence_settings = settings or {}
        if "exposure_ms" in self.sequence_settings:
            self.configure_exposure_time(float(self.sequence_settings["exposure_ms"]))
        trigger_source = str(self.sequence_settings.get("trigger_source", "")).lower()
        if trigger_source:
            source_map = {
                "internal": self.dcam_module.DCAMPROP.TRIGGERSOURCE.INTERNAL,
                "external": self.dcam_module.DCAMPROP.TRIGGERSOURCE.EXTERNAL,
                "software": self.dcam_module.DCAMPROP.TRIGGERSOURCE.SOFTWARE,
            }
            if trigger_source in source_map:
                self._check(
                    self.dcam.prop_setvalue(self.dcam_module.DCAM_IDPROP.TRIGGERSOURCE, source_map[trigger_source]),
                    "set TRIGGERSOURCE",
                )

    def start_capture(self) -> None:
        self.open_camera()
        self._ensure_buffer(self._sequence_buffer_frame_count())
        self._check(self.dcam.cap_start(True), "Dcam.cap_start")
        self.capture_active = True

    def stop_capture(self) -> None:
        if self.dcam is not None and self.dcam.is_opened():
            self.dcam.cap_stop()
        self.capture_active = False

    def capture_snapshot(self) -> object:
        self.open_camera()
        self._ensure_buffer(1)
        self._check(self.dcam.cap_snapshot(), "Dcam.cap_snapshot")
        self.capture_active = True
        try:
            self._wait_frame()
            return self._last_frame_copy()
        finally:
            self.dcam.cap_stop()
            self.capture_active = False

    def image_sequence(self, frame_count: int = 0) -> list[object]:
        self.open_camera()
        count = max(int(frame_count), 1)
        frames: list[object] = []
        started_here = False
        if not self.capture_active:
            self._ensure_buffer(max(count, self.buffer_frames))
            self._check(self.dcam.cap_start(True), "Dcam.cap_start sequence")
            self.capture_active = True
            started_here = True
        try:
            for _ in range(count):
                self._wait_frame()
                frames.append(self._last_frame_copy())
        finally:
            if started_here:
                self.dcam.cap_stop()
                self.capture_active = False
        return frames

    def save_sequence(self, image_data: object, folder: Path) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        frames = list(image_data) if isinstance(image_data, (list, tuple)) else [image_data]
        try:
            from PIL import Image
        except ImportError as exc:
            raise HamamatsuDcamError("Pillow is required to save Hamamatsu image arrays as TIFF files.") from exc
        for index, frame in enumerate(frames):
            if frame is None:
                continue
            Image.fromarray(frame).save(folder / f"frame_{index:05d}.tiff", format="TIFF")

    def get_camera_buffer_size(self) -> int:
        return self.buffer_frames

    def read_subregion_limits_and_value(self) -> tuple[SubRegionLimits, SubRegion | dict]:
        self.open_camera()
        props = self.dcam_module.DCAM_IDPROP
        limits = SubRegionLimits(
            horizontal_offset=self._minmaxinc(props.SUBARRAYHPOS),
            vertical_offset=self._minmaxinc(props.SUBARRAYVPOS),
            horizontal_size=self._minmaxinc(props.SUBARRAYHSIZE),
            vertical_size=self._minmaxinc(props.SUBARRAYVSIZE),
        )
        roi = SubRegion(
            horizontal_offset=int(self.dcam.prop_getvalue(props.SUBARRAYHPOS) or 0),
            vertical_offset=int(self.dcam.prop_getvalue(props.SUBARRAYVPOS) or 0),
            horizontal_size=int(self.dcam.prop_getvalue(props.SUBARRAYHSIZE) or self.dcam.prop_getvalue(props.IMAGE_WIDTH) or 0),
            vertical_size=int(self.dcam.prop_getvalue(props.SUBARRAYVSIZE) or self.dcam.prop_getvalue(props.IMAGE_HEIGHT) or 0),
        )
        return limits, roi

    def update_roi_limits(self, limits: SubRegionLimits | None = None) -> SubRegionLimits:
        if limits is not None:
            return limits
        return self.read_subregion_limits_and_value()[0]

    def read_readout_time(self) -> float:
        self.open_camera()
        props = self.dcam_module.DCAM_IDPROP
        value = self.dcam.prop_getvalue(props.TIMING_READOUTTIME) if hasattr(props, "TIMING_READOUTTIME") else False
        return float(value or 0.0)

    def sw_trigger(self) -> None:
        self.open_camera()
        self._check(self.dcam.cap_firetrigger(), "Dcam.cap_firetrigger")

    def close(self) -> None:
        if self.dcam is not None:
            try:
                if self.dcam.is_opened():
                    self.dcam.cap_stop()
            except Exception:
                pass
            self.capture_active = False
            try:
                self.dcam.buf_release()
            except Exception:
                pass
            self.allocated_buffer_frames = 0
            self.dcam.dev_close()
            self.dcam = None
        if self.initialized and self.dcamapi is not None:
            self.dcamapi.uninit()
            self.initialized = False

    def _ensure_buffer(self, frames: int) -> None:
        requested = max(int(frames), 1)
        if self.capture_active:
            if self.allocated_buffer_frames >= requested:
                return
            raise HamamatsuDcamError(
                "Cannot reallocate DCAM buffer while capture is active "
                f"(requested {requested}, allocated {self.allocated_buffer_frames})."
            )
        try:
            self.dcam.buf_release()
        except Exception:
            pass
        self.allocated_buffer_frames = 0
        self._check(self.dcam.buf_alloc(requested), f"Dcam.buf_alloc({requested})")
        self.allocated_buffer_frames = requested

    def _sequence_buffer_frame_count(self) -> int:
        frame_count = 0
        if self.sequence_settings:
            frame_count = int(self.sequence_settings.get("frames", 0) or 0)
        return max(frame_count, self.buffer_frames)

    def _wait_frame(self) -> None:
        while True:
            if self.dcam.wait_capevent_frameready(self.timeout_ms):
                return
            err = self.dcam.lasterr()
            if hasattr(err, "is_timeout") and err.is_timeout():
                continue
            raise HamamatsuDcamError(f"wait frame ready failed: {err}")

    def _last_frame_copy(self) -> object:
        frame = self.dcam.buf_getlastframedata()
        self._check(frame is not False, "Dcam.buf_getlastframedata")
        return frame.copy()

    def _minmaxinc(self, idprop: object) -> MinMaxInc:
        attr = self.dcam.prop_getattr(idprop)
        if attr is False:
            return MinMaxInc()
        return MinMaxInc(int(attr.valuemin), int(attr.valuemax), max(int(attr.valuestep), 1))
