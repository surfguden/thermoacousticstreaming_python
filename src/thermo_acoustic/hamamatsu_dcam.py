from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
from pathlib import Path
import sys
import time
from typing import Any

from .camera import MinMaxInc, SubRegion, SubRegionLimits
from .hw_logging import log_action, log_call, log_transaction


class HamamatsuDcamError(RuntimeError):
    pass


logger = logging.getLogger(__name__)


def _default_sdk_python_path() -> Path:
    return Path(__file__).resolve().parents[2] / "dcamsdk4" / "samples" / "python"


@dataclass(slots=True)
class HamamatsuDcamBackend:
    device_index: int = 0
    sdk_python_path: Path = field(default_factory=_default_sdk_python_path)
    buffer_frames: int = 3
    timeout_ms: int = 1000
    frame_total_timeout_s: float = 30.0
    dcamapi: Any = None
    dcam: Any = None
    dcam_module: Any = None
    initialized: bool = False
    sequence_settings: dict[str, Any] | None = None
    capture_active: bool = False
    allocated_buffer_frames: int = 0
    last_frame_timestamps: list[str] = field(default_factory=list)
    _timestamp_capability_checked: bool = False
    _timestamp_supported: bool = False

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
        with log_call("camera", "open_camera", command=self.device_index) as result:
            try:
                self._load_sdk()
                if not self.initialized:
                    self._check(self.dcamapi.init(), "Dcamapi.init")
                    self.initialized = True
                if self.dcam is None:
                    self.dcam = self.dcam_module.Dcam(self.device_index)
                if not self.dcam.is_opened():
                    self._check(self.dcam.dev_open(), "Dcam.dev_open")
            except Exception as exc:
                rollback_errors: list[str] = []
                if self.dcam is not None:
                    try:
                        if self.dcam.is_opened():
                            self._check(self.dcam.dev_close(), "Dcam.dev_close after failed open")
                        self.dcam = None
                    except Exception as rollback_exc:
                        rollback_errors.append(f"device rollback failed: {rollback_exc}")
                if self.initialized and self.dcamapi is not None:
                    try:
                        self._check(self.dcamapi.uninit(), "Dcamapi.uninit after failed open")
                        self.initialized = False
                    except Exception as rollback_exc:
                        rollback_errors.append(f"API rollback failed: {rollback_exc}")
                if rollback_errors:
                    raise HamamatsuDcamError(f"{exc}; {'; '.join(rollback_errors)}") from exc
                raise
            result["response"] = "opened"
        return self.dcam

    def configure_exposure_time(self, exposure_ms: float) -> float:
        # Finding E (silent-failure/data-integrity sweep): prop_setgetvalue()
        # returns the real value the device actually applied (it can differ
        # slightly from the request due to DCAM's own internal exposure
        # quantization), not just whether the call succeeded -- previously
        # discarded by routing through _check() alone, so the caller only
        # ever had the requested value to work with, never confirmation of
        # what was really applied.
        self.open_camera()
        with log_call(
            "camera", "configure_exposure_time", command=exposure_ms, response_stage="EFFECTIVE"
        ) as log_result:
            result = self.dcam.prop_setgetvalue(self.dcam_module.DCAM_IDPROP.EXPOSURETIME, max(exposure_ms, 0.0) / 1000.0)
            self._check(result, "set EXPOSURETIME")
            applied_ms = result * 1000.0
            log_result["response"] = applied_ms
            log_result["effective"] = applied_ms
        return applied_ms

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
        # Session 51: pre-flight check against the sensor's own real, live
        # limits -- DCAM's own SUBARRAY properties already reject an invalid
        # combination (INVALIDSUBARRAY, e.g. SUBARRAYHPOS + SUBARRAYHSIZE >
        # sensor width) via the existing _check()/prop_setgetvalue() calls
        # below, so this was never a silent-acceptance risk -- this just
        # catches the same condition earlier, with a clearer, ROI-specific
        # application-level message instead of a generic DCAM error surfacing
        # only after the SDK round-trip.
        limits, current_roi = self.read_subregion_limits_and_value()
        self._validate_roi_against_limits(roi, limits, current_roi)
        with log_call("camera", "configure_roi", command=roi) as log_result:
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
            log_result["response"] = "applied"

    def _validate_roi_against_limits(self, roi: SubRegion, limits: SubRegionLimits, current_roi: SubRegion) -> None:
        if roi.horizontal_size > 0 and not (limits.horizontal_size.minimum <= roi.horizontal_size <= limits.horizontal_size.maximum):
            raise HamamatsuDcamError(
                f"ROI horizontal_size={roi.horizontal_size} is outside the sensor's real "
                f"[{limits.horizontal_size.minimum}, {limits.horizontal_size.maximum}] range -- "
                "rejected before reaching the DCAM SDK."
            )
        if roi.vertical_size > 0 and not (limits.vertical_size.minimum <= roi.vertical_size <= limits.vertical_size.maximum):
            raise HamamatsuDcamError(
                f"ROI vertical_size={roi.vertical_size} is outside the sensor's real "
                f"[{limits.vertical_size.minimum}, {limits.vertical_size.maximum}] range -- "
                "rejected before reaching the DCAM SDK."
            )
        horizontal_offset = max(roi.horizontal_offset, 0)
        if not (limits.horizontal_offset.minimum <= horizontal_offset <= limits.horizontal_offset.maximum):
            raise HamamatsuDcamError(
                f"ROI horizontal_offset={horizontal_offset} is outside the sensor's real "
                f"[{limits.horizontal_offset.minimum}, {limits.horizontal_offset.maximum}] range -- "
                "rejected before reaching the DCAM SDK."
            )
        vertical_offset = max(roi.vertical_offset, 0)
        if not (limits.vertical_offset.minimum <= vertical_offset <= limits.vertical_offset.maximum):
            raise HamamatsuDcamError(
                f"ROI vertical_offset={vertical_offset} is outside the sensor's real "
                f"[{limits.vertical_offset.minimum}, {limits.vertical_offset.maximum}] range -- "
                "rejected before reaching the DCAM SDK."
            )
        # Combined check -- mirrors DCAM's own documented INVALIDSUBARRAY
        # condition ("SUBARRAYHPOS + SUBARRAYHSIZE is greater than the number
        # of horizontal pixel of sensor"). Uses whichever size will actually
        # be in effect after this call: the requested size if this call is
        # changing it, otherwise the size already in effect (configure_roi()
        # itself only calls SUBARRAYHSIZE/VSIZE's Set when size > 0).
        effective_horizontal_size = roi.horizontal_size if roi.horizontal_size > 0 else current_roi.horizontal_size
        if effective_horizontal_size and horizontal_offset + effective_horizontal_size > limits.horizontal_size.maximum:
            raise HamamatsuDcamError(
                f"ROI horizontal_offset({horizontal_offset}) + horizontal_size({effective_horizontal_size}) "
                f"= {horizontal_offset + effective_horizontal_size} exceeds the sensor's real horizontal "
                f"pixel count ({limits.horizontal_size.maximum}) -- rejected before reaching the DCAM SDK."
            )
        effective_vertical_size = roi.vertical_size if roi.vertical_size > 0 else current_roi.vertical_size
        if effective_vertical_size and vertical_offset + effective_vertical_size > limits.vertical_size.maximum:
            raise HamamatsuDcamError(
                f"ROI vertical_offset({vertical_offset}) + vertical_size({effective_vertical_size}) "
                f"= {vertical_offset + effective_vertical_size} exceeds the sensor's real vertical "
                f"pixel count ({limits.vertical_size.maximum}) -- rejected before reaching the DCAM SDK."
            )

    def configure_snapshot(self, settings: dict | None = None) -> None:
        if settings and "exposure_ms" in settings:
            self.configure_exposure_time(float(settings["exposure_ms"]))
        else:
            self.open_camera()

    def configure_sequence(self, settings: dict | None) -> None:
        # Session 65 (Finding 1, hamamatsu_dcam.py review): sequence_settings
        # is only committed to self after every property write below is
        # confirmed applied. Previously it was assigned up front, so a
        # mid-sequence failure (e.g. an out-of-range masterpulse_interval_s)
        # left sequence_settings reflecting the requested-but-never-applied
        # configuration -- read later by _sequence_buffer_frame_count() to
        # size the next capture's buffer. On failure here, sequence_settings
        # now stays at whatever configuration was last confirmed applied.
        self.open_camera()
        new_settings = settings or {}
        if "exposure_ms" in new_settings:
            self.configure_exposure_time(float(new_settings["exposure_ms"]))
        with log_call("camera", "configure_sequence", command=new_settings) as log_result:
            self._configure_sequence_properties(new_settings)
            log_result["response"] = "applied"
        self.sequence_settings = new_settings

    def _configure_sequence_properties(self, settings: dict[str, Any]) -> None:
        props = self.dcam_module.DCAM_IDPROP
        values = self.dcam_module.DCAMPROP
        if "masterpulse_mode" in settings:
            mode = self._mapped_value(
                settings["masterpulse_mode"],
                {
                    "continuous": values.MASTERPULSE_MODE.CONTINUOUS,
                    "start": values.MASTERPULSE_MODE.START,
                    "start (single)": values.MASTERPULSE_MODE.START,
                    "burst": values.MASTERPULSE_MODE.BURST,
                },
                "MASTERPULSE_MODE",
            )
            self._check(self.dcam.prop_setvalue(props.MASTERPULSE_MODE, mode), "set MASTERPULSE_MODE")
        if "masterpulse_source" in settings:
            source = self._mapped_value(
                settings["masterpulse_source"],
                {
                    "external": values.MASTERPULSE_TRIGGERSOURCE.EXTERNAL,
                    "software": values.MASTERPULSE_TRIGGERSOURCE.SOFTWARE,
                },
                "MASTERPULSE_TRIGGERSOURCE",
            )
            self._check(self.dcam.prop_setvalue(props.MASTERPULSE_TRIGGERSOURCE, source), "set MASTERPULSE_TRIGGERSOURCE")
        if "masterpulse_interval_s" in settings:
            interval_s = self._bounded_float(settings["masterpulse_interval_s"], 0.000005, 10.0, "MASTERPULSE_INTERVAL")
            self._check(self.dcam.prop_setgetvalue(props.MASTERPULSE_INTERVAL, interval_s), "set MASTERPULSE_INTERVAL")
        if "masterpulse_burst_times" in settings:
            burst_times = self._bounded_int(settings["masterpulse_burst_times"], 1, 65535, "MASTERPULSE_BURSTTIMES")
            self._check(self.dcam.prop_setgetvalue(props.MASTERPULSE_BURSTTIMES, burst_times), "set MASTERPULSE_BURSTTIMES")
        if "trigger_source" in settings:
            trigger_source_map = {
                "internal": values.TRIGGERSOURCE.INTERNAL,
                "external": values.TRIGGERSOURCE.EXTERNAL,
                "software": values.TRIGGERSOURCE.SOFTWARE,
            }
            masterpulse = getattr(values.TRIGGERSOURCE, "MASTERPULSE", None)
            if masterpulse is not None:
                trigger_source_map["masterpulse"] = masterpulse
                trigger_source_map["master pulse"] = masterpulse
            trigger_source = self._mapped_value(
                settings["trigger_source"],
                trigger_source_map,
                "TRIGGERSOURCE",
            )
            self._check(self.dcam.prop_setvalue(props.TRIGGERSOURCE, trigger_source), "set TRIGGERSOURCE")
        if "trigger_polarity" in settings:
            polarity = self._mapped_value(
                settings["trigger_polarity"],
                {
                    "negative": values.TRIGGERPOLARITY.NEGATIVE,
                    "positive": values.TRIGGERPOLARITY.POSITIVE,
                },
                "TRIGGERPOLARITY",
            )
            self._check(self.dcam.prop_setvalue(props.TRIGGERPOLARITY, polarity), "set TRIGGERPOLARITY")
        if "trigger_active" in settings:
            active = self._mapped_value(
                settings["trigger_active"],
                {"edge": values.TRIGGERACTIVE.EDGE, "level": values.TRIGGERACTIVE.LEVEL},
                "TRIGGERACTIVE",
            )
            self._check(self.dcam.prop_setvalue(props.TRIGGERACTIVE, active), "set TRIGGERACTIVE")
        if "trigger_mode" in settings:
            mode = self._mapped_value(
                settings["trigger_mode"],
                {"normal": values.TRIGGER_MODE.NORMAL},
                "TRIGGER_MODE",
            )
            self._check(self.dcam.prop_setvalue(props.TRIGGER_MODE, mode), "set TRIGGER_MODE")
        if "trigger_times" in settings:
            times = self._bounded_int(settings["trigger_times"], 1, 65535, "TRIGGERTIMES")
            self._check(self.dcam.prop_setgetvalue(props.TRIGGERTIMES, times), "set TRIGGERTIMES")
        if "trigger_delay_s" in settings:
            delay_s = self._bounded_float(settings["trigger_delay_s"], 0.0, 10.000002, "TRIGGERDELAY")
            self._check(self.dcam.prop_setgetvalue(props.TRIGGERDELAY, delay_s), "set TRIGGERDELAY")

    def configure_trigger_global_exposure(self, enabled: bool) -> None:
        self.open_camera()
        props = self.dcam_module.DCAM_IDPROP
        values = self.dcam_module.DCAMPROP.TRIGGER_GLOBALEXPOSURE
        # enabled=True -> GLOBALRESET: confirmed against the real LabVIEW
        # reference (Hamamatsu.lvclass:ConfigureSequence.vi's `globalshutter`
        # Select node picks numeric value 5 for its true case, an exact match
        # for DCAMPROP_TRIGGER_GLOBALEXPOSURE__GLOBALRESET=5 in the vendored
        # DCAM-API v4 header, dcamsdk4/inc/dcamprop.h).
        #
        # enabled=False -> deliberately does NOT call prop_setvalue() at all
        # (leaves the property at its prior/default state), rather than
        # picking a specific "off" mode. LabVIEW's own false-case value (0)
        # is not a valid TRIGGER_GLOBALEXPOSURE enum member (valid range is
        # 1-5) and the property-ID constant visible at that block-diagram
        # call site (2049680 / 0x1F4690) does not match
        # DCAM_IDPROP_TRIGGER_GLOBALEXPOSURE's real v4 value (2032384 /
        # 0x1F0300) or any other constant in the vendored header -- an
        # unresolved discrepancy (no DCAM-API v3 header or Hamamatsu
        # compatibility-note documentation could be found locally or via web
        # search to explain it; a second, independently-sourced v4 header
        # -- SLAC's EPICS ADOrcaUsb module -- has byte-identical constants
        # for this property, weakening but not disproving a version-drift
        # explanation). Actively setting a specific guessed "off" value
        # (the previous code used DELAYED) risked being systematically wrong
        # for every future experiment's exposure timing; not touching the
        # property when disabled is the safer choice until this can be
        # confirmed against the real LabVIEW application directly. See
        # docs/known_open_items.md.
        if not enabled:
            with log_call("camera", "configure_trigger_global_exposure", command="skip (disabled)") as result:
                result["response"] = "not applied -- disabled, property left untouched"
            return
        value = values.GLOBALRESET
        value_name = getattr(value, "name", str(value))
        with log_call("camera", "configure_trigger_global_exposure", command=value_name) as result:
            self._check(
                self.dcam.prop_setvalue(props.TRIGGER_GLOBALEXPOSURE, value),
                f"set TRIGGER_GLOBALEXPOSURE to {value_name}",
            )
            result["response"] = "applied"

    def start_capture(self) -> None:
        self.open_camera()
        with log_call("camera", "start_capture") as result:
            self._ensure_buffer(self._sequence_buffer_frame_count())
            self._check(self.dcam.cap_start(True), "Dcam.cap_start")
            self.capture_active = True
            result["response"] = "started"

    def stop_capture(self) -> None:
        with log_call("camera", "stop_capture") as result:
            self._stop_capture_if_active()
            result["response"] = "stopped"

    def capture_snapshot(self) -> object:
        self.open_camera()
        with log_call("camera", "capture_snapshot") as result:
            self._ensure_buffer(1)
            self._check(self.dcam.cap_snapshot(), "Dcam.cap_snapshot")
            self.capture_active = True
            try:
                self._wait_frame("capture_snapshot")
                pixel_copy, _timestamp = self._last_frame_copy()
                result["response"] = "1 frame captured"
                return pixel_copy
            finally:
                self._stop_capture_if_active()

    def image_sequence(self, frame_count: int = 0, partial_capture_folder: Path | None = None) -> list[object]:
        self.open_camera()
        count = max(int(frame_count), 1)
        with log_call(
            "camera", "image_sequence", command=count, response_stage="OBSERVED"
        ) as log_result:
            frames: list[object] = []
            timestamps: list[str | None] = []
            started_here = False
            if not self.capture_active:
                self._ensure_buffer(max(count, self.buffer_frames))
                self._check(self.dcam.cap_start(True), "Dcam.cap_start sequence")
                self.capture_active = True
                started_here = True
            try:
                for index in range(count):
                    self._wait_frame(f"image_sequence frame {index + 1}/{count}")
                    pixel_copy, timestamp = self._last_frame_copy()
                    frames.append(pixel_copy)
                    timestamps.append(timestamp)
            except Exception as exc:
                if frames and partial_capture_folder is not None:
                    log_action(
                        "camera",
                        "partial_acquisition",
                        evidence_stage="OBSERVED",
                        verification_scope="PROTOCOL",
                        status="FAILED",
                        result={
                            "captured_frames": len(frames),
                            "expected_frames": count,
                            "partial_folder": partial_capture_folder / f"partial_{len(frames)}_of_{count}",
                        },
                        error=str(exc),
                        source="hamamatsu_dcam.image_sequence",
                    )
                    self._save_partial_capture(frames, len(frames), count, partial_capture_folder)
                raise
            finally:
                if started_here:
                    self._stop_capture_if_active()
            # All-or-nothing: only trust the batch if every frame reported a real
            # hardware timestamp. save_image_data() falls back to write-time
            # metadata for the whole experiment otherwise (see workflows.py).
            self.last_frame_timestamps = timestamps if timestamps and all(ts is not None for ts in timestamps) else []
            log_result["response"] = f"{len(frames)}/{count} frames, timestamped={bool(self.last_frame_timestamps)}"
        return frames

    def _save_partial_capture(self, frames: list[object], captured: int, total: int, folder: Path) -> None:
        partial_folder = folder / f"partial_{captured}_of_{total}"
        logger.error(
            "Hamamatsu image_sequence faulted after %d/%d frames; saving already-captured frames to %s",
            captured,
            total,
            partial_folder,
        )
        try:
            self.save_sequence(frames, partial_folder)
        except Exception as exc:  # pragma: no cover - best-effort rescue path
            logger.error("Failed to save partial capture to %s: %s", partial_folder, exc)

    def read_frame_timestamps(self) -> list[str]:
        return list(self.last_frame_timestamps)

    def _timestamp_capability(self) -> bool:
        if not self._timestamp_capability_checked:
            self._timestamp_capability_checked = True
            capability = self.dcam.dev_getcapability()
            self._timestamp_supported = bool(capability) and capability.is_support_timestamp()
        return self._timestamp_supported

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
        with log_call(
            "camera", "read_subregion_limits_and_value", response_stage="OBSERVED"
        ) as log_result:
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
            log_result["response"] = roi
        return limits, roi

    def update_roi_limits(self, limits: SubRegionLimits | None = None) -> SubRegionLimits:
        if limits is not None:
            return limits
        return self.read_subregion_limits_and_value()[0]

    def read_readout_time(self) -> float | None:
        self.open_camera()
        props = self.dcam_module.DCAM_IDPROP
        if not hasattr(props, "TIMING_READOUTTIME"):
            with log_call("camera", "read_readout_time", command="unsupported") as result:
                result["response"] = 0.0
            return 0.0
        value = self.dcam.prop_getvalue(props.TIMING_READOUTTIME)
        if value is False:
            # Finding 3 (hamamatsu_dcam.py review, Session 65): a genuine
            # query failure (property exists but the live read failed) is
            # not the same as "unsupported on this camera" -- previously
            # both fell back to a plausible-looking 0.0, silently
            # corrupting permanent TDMS metadata (workflows.py writes this
            # straight through as ReadoutTime) and feeding
            # Application._check_camera_timing_budget()'s safety check an
            # artificially low readout time. None is this project's
            # existing "value unavailable" sentinel (_tdms_scalar() maps
            # None -> "", distinguishable in the written TDMS file from a
            # real 0.0 reading) -- logged as a failed transaction, not
            # silently swallowed, but not raised here since this is a
            # metadata read, not a command that leaves hardware in an
            # unconfirmed state; callers that need this value to be
            # trustworthy (the timing-budget safety check) must handle
            # None explicitly.
            err = self.dcam.lasterr()
            log_transaction("camera", "read_readout_time", success=False, error=str(err))
            return None
        with log_call("camera", "read_readout_time", response_stage="OBSERVED") as result:
            readout_s = float(value)
            result["response"] = readout_s
        return readout_s

    def read_min_trigger_interval(self) -> float | None:
        """Read the real external-trigger cadence limit; None means unavailable."""
        self.open_camera()
        props = self.dcam_module.DCAM_IDPROP
        if not hasattr(props, "TIMING_MINTRIGGERINTERVAL"):
            return None
        value = self.dcam.prop_getvalue(props.TIMING_MINTRIGGERINTERVAL)
        if value is False:
            log_transaction("camera", "read_min_trigger_interval", success=False, error=str(self.dcam.lasterr()))
            return None
        with log_call("camera", "read_min_trigger_interval", response_stage="OBSERVED") as result:
            interval_s = float(value)
            result["response"] = interval_s
        return interval_s

    def sw_trigger(self) -> None:
        self.open_camera()
        with log_call("camera", "sw_trigger") as result:
            self._check(self.dcam.cap_firetrigger(), "Dcam.cap_firetrigger")
            result["response"] = "triggered"

    def close(self) -> None:
        # Deliberately not wrapped in log_call() (which re-raises) -- this is
        # an intentionally best-effort cleanup path (Finding F, see below);
        # log_transaction() records the outcome without changing that
        # swallow-and-continue control flow.
        if self.dcam is not None:
            # Finding F (silent-failure/data-integrity sweep): these two
            # cleanup steps were silently swallowed with a bare `pass` --
            # unlike every other cleanup path in this codebase
            # (Application._cleanup_instruments logs; QmixPumpBackend.close()/
            # PiezoStage.disconnect() both re-raise with details). If the
            # camera genuinely failed to stop capture or release its buffer
            # here, Application.cleanup() would see a clean success (no
            # exception raised) with zero indication the device may still be
            # in an inconsistent internal state -- only surfacing later as a
            # confusing, seemingly-unrelated re-Initialize failure. Logged
            # (not raised) because this remains an intentionally best-effort
            # cleanup path, same as before -- only the silence is fixed.
            try:
                self._stop_capture_if_active()
            except Exception as exc:
                logger.error("Hamamatsu close(): failed to stop capture during cleanup: %s", exc)
                log_transaction("camera", "close.stop_capture", success=False, error=str(exc))
            try:
                self.dcam.buf_release()
            except Exception as exc:
                logger.error("Hamamatsu close(): failed to release buffer during cleanup: %s", exc)
                log_transaction("camera", "close.buf_release", success=False, error=str(exc))
            self.allocated_buffer_frames = 0
            self.dcam.dev_close()
            self.dcam = None
            log_transaction("camera", "close", success=True, response="closed")
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
        except Exception as exc:
            # Finding 2 (hamamatsu_dcam.py review, Session 65): same
            # silent-failure shape as close()'s Finding F -- logged (not
            # raised) because the buf_alloc() retry below is still the
            # right move regardless of whether this release actually
            # freed anything; only the silence was the bug.
            logger.error("Hamamatsu _ensure_buffer(): failed to release existing buffer before realloc: %s", exc)
            log_transaction("camera", "ensure_buffer.buf_release", success=False, error=str(exc))
        self.allocated_buffer_frames = 0
        self._check(self.dcam.buf_alloc(requested), f"Dcam.buf_alloc({requested})")
        self.allocated_buffer_frames = requested

    def _sequence_buffer_frame_count(self) -> int:
        frame_count = 0
        if self.sequence_settings:
            frame_count = int(self.sequence_settings.get("frames", 0) or 0)
        return max(frame_count, self.buffer_frames)

    def _wait_frame(self, context: str) -> None:
        started_at = time.monotonic()
        total_timeout_s = max(float(self.frame_total_timeout_s), self.timeout_ms / 1000.0)
        while True:
            if self.dcam.wait_capevent_frameready(self.timeout_ms):
                if not self.capture_active:
                    raise HamamatsuDcamError(f"Capture stopped while waiting for Hamamatsu frame during {context}.")
                return
            err = self.dcam.lasterr()
            if hasattr(err, "is_timeout") and err.is_timeout():
                if not self.capture_active:
                    raise HamamatsuDcamError(f"Capture stopped while waiting for Hamamatsu frame during {context}.")
                elapsed_s = time.monotonic() - started_at
                if elapsed_s < total_timeout_s:
                    continue
                self._stop_and_release_after_wait_timeout(context, elapsed_s, err)
                raise HamamatsuDcamError(
                    f"Timed out waiting for Hamamatsu frame during {context} "
                    f"after {elapsed_s:.3f}s; capture was stopped and buffers were released."
                )
            raise HamamatsuDcamError(f"wait frame ready failed: {err}")

    def _stop_capture_if_active(self) -> None:
        cleanup_error: Exception | None = None
        try:
            if self.capture_active and self.dcam is not None and self.dcam.is_opened():
                self.dcam.cap_stop()
        except Exception as exc:
            cleanup_error = exc
        finally:
            self.capture_active = False
        try:
            if self.allocated_buffer_frames and self.dcam is not None and self.dcam.is_opened():
                self.dcam.buf_release()
        except Exception as exc:
            if cleanup_error is None:
                cleanup_error = exc
            else:
                cleanup_error = HamamatsuDcamError(f"{cleanup_error}; buffer release failed: {exc}")
        finally:
            self.allocated_buffer_frames = 0
        if cleanup_error is not None:
            raise cleanup_error

    def _stop_and_release_after_wait_timeout(self, context: str, elapsed_s: float, err: object) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        logger.error(
            "Hamamatsu frame wait timed out at %s during %s after %.3fs; last DCAM error: %s",
            timestamp,
            context,
            elapsed_s,
            err,
            extra={
                "timestamp": timestamp,
                "context": context,
                "elapsed_s": elapsed_s,
                "dcam_error": str(err),
            },
        )
        stop_error: Exception | None = None
        try:
            self._stop_capture_if_active()
        except Exception as exc:  # pragma: no cover - defensive cleanup path
            stop_error = exc
        if stop_error is not None:
            logger.error(
                "Hamamatsu timeout cleanup had errors at %s during %s: %r",
                timestamp,
                context,
                stop_error,
                extra={
                    "timestamp": timestamp,
                    "context": context,
                    "cleanup_error": repr(stop_error),
                },
            )

    def _last_frame_copy(self) -> tuple[object, str | None]:
        if self._timestamp_capability():
            result = self.dcam.buf_getframe(-1)
            self._check(result is not False, "Dcam.buf_getframe")
            frame, image = result
            pixel_copy = image.copy()
            # DCAMBUF_FRAME.timestamp is in the camera/driver's own clock
            # domain (see DCAM_IDPROP.TIMESTAMP_PRODUCER), not verified
            # against host wall-clock or AD2 trigger timing (time.monotonic()
            # elsewhere in this codebase) -- kept as a raw sec.microsec pair
            # rather than reformatted as a UTC datetime to avoid asserting an
            # epoch that hasn't been confirmed against real hardware.
            if frame.timestamp.sec or frame.timestamp.microsec:
                return pixel_copy, f"dcam_clock:{frame.timestamp.sec}.{frame.timestamp.microsec:06d}"
            return pixel_copy, None
        frame = self.dcam.buf_getlastframedata()
        self._check(frame is not False, "Dcam.buf_getlastframedata")
        return frame.copy(), None

    def _minmaxinc(self, idprop: object) -> MinMaxInc:
        attr = self.dcam.prop_getattr(idprop)
        if attr is False:
            return MinMaxInc()
        return MinMaxInc(int(attr.valuemin), int(attr.valuemax), max(int(attr.valuestep), 1))

    def _mapped_value(self, value: object, mapping: dict[str, object], name: str) -> object:
        key = str(value).strip().lower().replace("_", " ")
        if key in mapping:
            return mapping[key]
        raise HamamatsuDcamError(f"Unsupported {name} value: {value!r}")

    def _bounded_float(self, value: object, minimum: float, maximum: float, name: str) -> float:
        numeric = float(value)
        if minimum <= numeric <= maximum:
            return numeric
        raise HamamatsuDcamError(f"{name} must be between {minimum} and {maximum}; got {numeric}")

    def _bounded_int(self, value: object, minimum: int, maximum: int, name: str) -> int:
        numeric = int(value)
        if minimum <= numeric <= maximum:
            return numeric
        raise HamamatsuDcamError(f"{name} must be between {minimum} and {maximum}; got {numeric}")
