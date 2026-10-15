"""Compile the fixed-form experiment series into the portable v1 definition."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import math
from typing import Any

from .experiments import validate_definition
from ..drivers.tec.controller import validate_tec_target_temperature


@dataclass(frozen=True)
class NumericRange:
    start: float
    stop: float
    steps: int

    def values(self, name: str) -> list[float]:
        if not math.isfinite(self.start):
            raise ValueError(f"{name} start must be finite")
        if self.steps < 1:
            raise ValueError(f"{name} steps must be positive")
        if self.steps == 1:
            return [self.start]
        if not math.isfinite(self.stop):
            raise ValueError(f"{name} stop must be finite")
        return [self.start + (self.stop - self.start) * index / (self.steps - 1)
                for index in range(self.steps)]


@dataclass(frozen=True)
class SimpleSeriesSettings:
    repeats: int
    frame_count: int
    camera_fps: float
    sound_start_s: float
    sound_run_s: float
    laser_start_s: float
    laser_run_s: float
    camera_start_s: float
    frequency_hz: NumericRange
    amplitude_v: NumericRange
    exposure_ms: NumericRange
    roi: tuple[int, int, int, int]
    flush_unit_index: int
    flush_volume_ml: float
    flush_flow_ul_min: float
    description: str = ""
    flush_wait_after_s: float = 0.0
    sweep_enabled: bool = False
    sweep_width_hz: NumericRange = NumericRange(0, 0, 1)
    sweep_period_ms: float = 1.0
    temperature_control: bool = False
    tec_channel: int = 1
    temperature_c: NumericRange = NumericRange(25, 25, 1)
    temperature_wait_s: float = 0.0
    temperature_logging: bool = False
    tiff_format: str = "frames"
    # Additive, optional capability: when False (the default), every existing
    # series compiles exactly as before -- tec_set followed by a fixed
    # temperature_wait_s. When True, a tec_wait_stable step is inserted
    # between them, gating on the controller's own reading rather than a
    # guessed duration; temperature_wait_s then becomes an additional hold
    # applied only after stability is confirmed (distinct from min_settle_s,
    # which is how long the reading must already have been within tolerance
    # to call it "stable" in the first place).
    temperature_wait_for_stability: bool = False
    temperature_tolerance_c: float = 0.2
    temperature_min_settle_s: float = 5.0
    temperature_max_wait_s: float = 300.0


_NUMERIC_RANGE_FIELDS = ("frequency_hz", "amplitude_v", "exposure_ms", "sweep_width_hz", "temperature_c")


def simple_series_settings_to_profile(settings: SimpleSeriesSettings) -> dict[str, Any]:
    """JSON-safe dict for every fixed-form experiment-tab input. Saved
    alongside the existing per-device settings profile (same file, a
    sibling top-level key) -- paired with simple_series_settings_from_profile()
    for the round trip. `roi` becomes a list (JSON has no tuple type);
    `NumericRange` fields become plain start/stop/steps objects via asdict()."""
    data = asdict(settings)
    data["roi"] = list(data["roi"])
    return data


def simple_series_settings_from_profile(data: object) -> SimpleSeriesSettings:
    """Inverse of simple_series_settings_to_profile(); raises ValueError on
    anything that isn't a well-formed experiment-settings object, matching
    the device-settings profile's own validation style."""
    if not isinstance(data, dict):
        raise ValueError("Experiment settings must be an object")
    known = {field.name for field in fields(SimpleSeriesSettings)}
    unknown = set(data) - known
    if unknown:
        raise ValueError(f"Unknown experiment setting(s): {', '.join(sorted(unknown))}")
    values = dict(data)
    for key in _NUMERIC_RANGE_FIELDS:
        if key not in values:
            continue
        range_value = values[key]
        if not isinstance(range_value, dict) or set(range_value) != {"start", "stop", "steps"}:
            raise ValueError(f"{key} must be a start/stop/steps object")
        try:
            values[key] = NumericRange(**range_value)
        except TypeError as exc:
            raise ValueError(f"{key} is not a valid start/stop/steps object: {exc}") from exc
    if "roi" in values:
        roi = values["roi"]
        if not (isinstance(roi, (list, tuple)) and len(roi) == 4):
            raise ValueError("roi must be a 4-element array")
        values["roi"] = tuple(roi)
    try:
        return SimpleSeriesSettings(**values)
    except TypeError as exc:
        raise ValueError(f"Experiment settings are missing a required field: {exc}") from exc


def compile_simple_series(settings: SimpleSeriesSettings) -> dict[str, Any]:
    """Return a validated definition; parameter nesting determines folder order."""
    frequencies = settings.frequency_hz.values("Frequency")
    amplitudes = settings.amplitude_v.values("Amplitude")
    exposures = settings.exposure_ms.values("Exposure")
    widths = settings.sweep_width_hz.values("Sweep width") if settings.sweep_enabled else ["NaN"]
    temperatures = settings.temperature_c.values("Temperature") if settings.temperature_control else ["NaN"]
    if settings.temperature_control:
        for temperature in temperatures:
            validate_tec_target_temperature(temperature)
    if settings.repeats < 1 or settings.frame_count < 1:
        raise ValueError("Repeats and frame count must be positive")
    if settings.temperature_wait_s < 0:
        raise ValueError("Temperature wait must be nonnegative")
    if settings.temperature_control and settings.temperature_wait_for_stability:
        if settings.temperature_tolerance_c < 0:
            raise ValueError("Temperature tolerance must be nonnegative")
        if settings.temperature_min_settle_s < 0:
            raise ValueError("Temperature minimum settle time must be nonnegative")
        if settings.temperature_max_wait_s <= 0:
            raise ValueError("Temperature maximum wait must be positive")
        # Deliberately no extra floor tied to TecWaitStableArgs' own
        # poll_interval_s default here: that default is a software polling
        # choice, not a device requirement, and experiment_runner.py's
        # _run_action() already reports an inconsistent combination as an
        # ordinary series failure at run time -- a second, compile-time
        # restriction duplicating that same software default as if it were
        # a rule this field must obey is exactly the kind of unnecessary
        # restriction worth not adding.
    if not 0 <= settings.flush_wait_after_s <= 100:
        raise ValueError("Wait after flush must be within 0..100 s")
    if settings.sweep_enabled and (settings.sweep_period_ms <= 0 or any(width <= 0 for width in widths)):
        raise ValueError("Sweep width and period must be positive")
    if settings.sweep_enabled and any(center - width / 2 <= 0 for center in frequencies for width in widths):
        raise ValueError("Sweep start frequency must be positive")
    x, y, width, height = settings.roi
    if min(x, y) < 0 or min(width, height) < 1:
        raise ValueError("ROI offsets must be nonnegative and dimensions positive")
    flush = {"type": "flush", "args": {"unit_index": settings.flush_unit_index,
                                         "volume_ml": settings.flush_volume_ml,
                                         "flow_ul_min": settings.flush_flow_ul_min,
                                         "wait_after_s": settings.flush_wait_after_s}}
    ultrasound = {"enabled": True, "start_s": settings.sound_start_s,
                  "run_s": settings.sound_run_s, "frequency_hz": {"$param": "frequency_hz"},
                  "amplitude_v": {"$param": "amplitude_v"}, "offset_v": 0}
    if settings.sweep_enabled:
        ultrasound["sweep_width_hz"] = {"$param": "sweep_width_hz"}
        ultrasound["sweep_period_ms"] = settings.sweep_period_ms
    window = max(settings.sound_start_s + settings.sound_run_s,
                 settings.laser_start_s + settings.laser_run_s,
                 settings.camera_start_s + settings.frame_count / settings.camera_fps)
    acquisition = {"type": "experiment", "steps": [
        {"type": "camera_configure", "args": {"frame_count": settings.frame_count,
             "exposure_ms": {"$param": "exposure_ms"}, "global_exposure": False,
             "roi": {"x": x, "y": y, "width": width, "height": height}}},
        {"type": "ad2_configure", "args": {"ultrasound": ultrasound,
             "laser": {"enabled": True, "start_s": settings.laser_start_s,
                       "run_s": settings.laser_run_s, "on_voltage_v": 5.0},
             "dio": {"frame_rate_hz": settings.camera_fps,
                     "camera_delay_s": settings.camera_start_s,
                     "frame_count": settings.frame_count},
             "output_timeout_s": window + max(5.0, window * 0.25)}},
        {"type": "camera_arm", "args": {}}, {"type": "ad2_arm", "args": {}},
        {"type": "pc_trigger", "args": {}}, {"type": "await_frames", "args": {}},
        {"type": "parallel", "branches": [
            [{"type": "save_frames", "args": {}}],
            [{"type": "wait_outputs", "args": {}}, flush],
        ]},
    ]}
    body: list[dict[str, Any]] = [{"type": "repeat", "count": settings.repeats,
                                   "steps": [acquisition]}]
    for name, values in reversed((("frequency_hz", frequencies),
                                  ("sweep_width_hz", widths),
                                  ("amplitude_v", amplitudes),
                                  ("exposure_ms", exposures))):
        if values:
            body = [{"type": "sweep", "parameters": {name: values}, "steps": body}]
    if settings.temperature_control and settings.temperature_wait_for_stability:
        temperature_steps = [
            {"type": "tec_set", "args": {"target_temperature_c":
                {"$param": "temperature_c"}, "channels": [settings.tec_channel]}},
            {"type": "tec_wait_stable", "args": {"target_temperature_c":
                {"$param": "temperature_c"}, "channels": [settings.tec_channel],
                "tolerance_c": settings.temperature_tolerance_c,
                "min_settle_s": settings.temperature_min_settle_s,
                "max_wait_s": settings.temperature_max_wait_s}},
            {"type": "wait", "args": {"seconds": settings.temperature_wait_s}},
        ]
    elif settings.temperature_control:
        temperature_steps = [
            {"type": "tec_set", "args": {"target_temperature_c":
                {"$param": "temperature_c"}, "channels": [settings.tec_channel]}},
            {"type": "wait", "args": {"seconds": settings.temperature_wait_s}},
        ]
    else:
        temperature_steps = []
    body = [{"type": "sweep", "parameters": {"temperature_c": temperatures},
             "steps": [*temperature_steps, *body]}]
    definition = {"version": 1, "name": "simple_series", "description": settings.description.strip(),
                  "preflight": False,
                  "simple_series": True,
                  "tiff_format": settings.tiff_format,
                  "temperature_logging": settings.temperature_logging,
                  "steps": [flush, *body]}
    validate_definition(definition)
    return definition
