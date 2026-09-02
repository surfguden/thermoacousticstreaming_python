from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from copy import deepcopy
from enum import Enum
from pathlib import Path
from typing import Any

from .ad2 import FmSweepSettings, coerce_do_config, coerce_wfg_config
from .camera import SubRegion
from .runtime_truth import RuntimeEvidenceSnapshot, VerificationScope
from .workflows import Experiment2, ExperimentSeries2, FlushSettings, TemperatureSeries


class CameraFieldOwnership(str, Enum):
    EXPERIMENT_DEFAULT = "experiment_default"
    EXPERIMENT_OVERRIDE = "experiment_override"
    APPLIED_DEVICE_STATE = "applied_device_state"
    MANUAL_ONLY = "manual_only"
    DISPLAY_ONLY = "display_only"


CAMERA_FIELD_OWNERSHIP: dict[str, CameraFieldOwnership] = {
    "masterpulse_mode": CameraFieldOwnership.EXPERIMENT_DEFAULT,
    "masterpulse_source": CameraFieldOwnership.EXPERIMENT_DEFAULT,
    "masterpulse_interval_s": CameraFieldOwnership.EXPERIMENT_DEFAULT,
    "masterpulse_burst_times": CameraFieldOwnership.EXPERIMENT_DEFAULT,
    "trigger_polarity": CameraFieldOwnership.EXPERIMENT_DEFAULT,
    "trigger_delay_s": CameraFieldOwnership.EXPERIMENT_DEFAULT,
    "manual_trigger_source": CameraFieldOwnership.MANUAL_ONLY,
    "automated_trigger_source": CameraFieldOwnership.EXPERIMENT_OVERRIDE,
    "frames": CameraFieldOwnership.EXPERIMENT_OVERRIDE,
    "roi": CameraFieldOwnership.MANUAL_ONLY,
    "manual_exposure_ms": CameraFieldOwnership.MANUAL_ONLY,
    "experiment_exposure_ms": CameraFieldOwnership.EXPERIMENT_OVERRIDE,
    "applied_exposure_ms": CameraFieldOwnership.APPLIED_DEVICE_STATE,
    "timing_feasibility_summary": CameraFieldOwnership.DISPLAY_ONLY,
}


@dataclass(frozen=True, slots=True)
class ExperimentCameraDefaults:
    masterpulse_mode: str
    masterpulse_source: str
    masterpulse_interval_s: float
    masterpulse_burst_times: int
    trigger_source: str
    trigger_polarity: str
    trigger_delay_s: float
    roi: SubRegion | dict[str, Any] | None = None

    def sequence_settings(
        self,
        *,
        frames: int,
        trigger_source_override: str | None = None,
    ) -> dict[str, object]:
        return {
            "masterpulse_mode": self.masterpulse_mode,
            "masterpulse_source": self.masterpulse_source,
            "masterpulse_interval_s": self.masterpulse_interval_s,
            "masterpulse_burst_times": self.masterpulse_burst_times,
            "frames": int(frames),
            "trigger_source": trigger_source_override or self.trigger_source,
            "trigger_polarity": self.trigger_polarity,
            "trigger_delay_s": self.trigger_delay_s,
        }


@dataclass(frozen=True, slots=True)
class FrozenSequence:
    """An immutable representation of a list used in static plan recipes."""

    values: tuple[Any, ...]


@dataclass(frozen=True, slots=True)
class FrozenMapping:
    """An immutable, recursively frozen mapping for request/plan recipes."""

    items: tuple[tuple[str, Any], ...]

    def value_for(self, key: str, default: Any = None) -> Any:
        return dict(self.items).get(key, default)


@dataclass(frozen=True, slots=True)
class ExperimentRequest:
    output_path: Path
    repeats_per_group: int
    frequency_scan_enabled: bool
    frequency_values_hz: tuple[float, ...]
    channel0_waveform_function: str
    camera_fps: float
    frames: int
    camera_start_s: tuple[float, ...]
    dynamic_camera_start: bool
    fm_sweep_enabled: bool
    channel0_output_selected: bool
    flush_enabled: bool
    tec_scan_enabled: bool
    temperature_targets_c: tuple[tuple[tuple[int, float], ...], ...]
    device_modes: tuple[tuple[str, bool, bool], ...]
    tec_settle_settings: tuple[float, float, float, float, float] = (0.1, 5.0, 300.0, 1.0, 0.0)
    fixed_camera_start_s: float | None = None
    # Static execution semantics only. UI extractors populate these plain
    # values; the independent planner never reads widgets or legacy builders.
    wfg_templates: tuple[FrozenMapping | dict[str, Any], ...] = ()
    do_template: FrozenMapping | dict[str, Any] | None = None
    sequence_settings: tuple[tuple[str, Any], ...] = ()
    flush_settings: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 60.0)
    exposure_ms: float = 0.0
    trigger_global_exposure: bool = False
    fm_sweep: tuple[float, float, float, str] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "wfg_templates", tuple(_freeze_mapping(item) for item in self.wfg_templates))
        if self.do_template is not None:
            object.__setattr__(self, "do_template", _freeze_mapping(self.do_template))
        object.__setattr__(
            self,
            "sequence_settings",
            tuple((key, _freeze_value(value)) for key, value in self.sequence_settings),
        )


@dataclass(frozen=True, slots=True)
class RunPlan:
    output_path: Path
    conditions: tuple["RunCondition", ...]
    group_sizes: tuple[int, ...]
    total_frames: int
    @property
    def experiments(self) -> tuple["RunCondition", ...]:
        return self.conditions

    def normalized_experiments(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            normalize_experiment(experiment)
            for group in legacy_series_from_run_plan(self)
            for experiment in (group.experiments or ())
        )

    def normalized_groups(self) -> tuple[tuple[dict[str, Any], ...], ...]:
        return tuple(
            tuple(normalize_experiment(experiment) for experiment in (group.experiments or ()))
            for group in legacy_series_from_run_plan(self)
        )

    @property
    def experiment_groups(self) -> tuple[tuple["RunCondition", ...], ...]:
        """Independent condition grouping; it never exposes Experiment2."""
        cursor = 0
        groups = []
        for size in self.group_sizes:
            groups.append(self.conditions[cursor:cursor + size])
            cursor += size
        return tuple(groups)


@dataclass(frozen=True, slots=True)
class RunCondition:
    group_index: int
    repeat_id: int
    output_root: Path
    experiment_folder: Path
    temperature_targets_c: tuple[tuple[int, float], ...]
    selected_frequency_hz: float | None
    wfg_config: FrozenMapping
    do_config: FrozenMapping
    sequence_settings: tuple[tuple[str, Any], ...]
    flush_settings: tuple[float, float, float, float]
    flush_enabled: bool
    exposure_ms: float
    trigger_global_exposure: bool
    fm_sweep: tuple[float, float, float, str] | None

    def normalized(self) -> dict[str, Any]:
        return _stable_value(asdict(self))


@dataclass(frozen=True, slots=True)
class PreflightIssue:
    code: str
    message: str
    blocking: bool
    verification: VerificationScope = VerificationScope.SOFTWARE


@dataclass(frozen=True, slots=True)
class PreflightResult:
    required_devices: tuple[str, ...]
    selected_devices: tuple[str, ...]
    simulated_devices: tuple[str, ...]
    disabled_devices: tuple[str, ...]
    experiment_axes: tuple[tuple[str, int], ...]
    frequency_repeat_compatible: bool
    camera_timing_valid: bool
    output_path_state: str
    fluidics_required: bool
    tec_required: bool
    issues: tuple[PreflightIssue, ...]

    @property
    def blocking_issues(self) -> tuple[PreflightIssue, ...]:
        return tuple(issue for issue in self.issues if issue.blocking)

    @property
    def warnings(self) -> tuple[PreflightIssue, ...]:
        return tuple(issue for issue in self.issues if not issue.blocking)


@dataclass(frozen=True, slots=True)
class BuildResult:
    request: ExperimentRequest
    plan: RunPlan | None
    preflight: PreflightResult


def normalize_experiment(experiment: Experiment2) -> dict[str, Any]:
    wfg = coerce_wfg_config(experiment.wfg_config)
    do_config = coerce_do_config(experiment.do_clock_settings)
    return {
        "repeat_id": experiment.repeat_id,
        "output_root": str(experiment.output_root) if experiment.output_root is not None else "",
        "planned_repeat_count": experiment.planned_repeat_count,
        "temperature_point_index": experiment.temperature_point_index,
        "frequency_scan_selected_hz": experiment.frequency_scan_selected_hz,
        "output_path": str(experiment.experiment_folder),
        "global_exposure_ms": experiment.global_exposure_ms,
        "trigger_global_exposure": experiment.trigger_global_exposure,
        "wfg": _stable_value(wfg),
        "do_clock": _stable_value(do_config),
        "fm_sweep": _stable_value(experiment.fm_sweep),
        "wfg_frequencies_hz": tuple(channel.carrier.frequency_hz for channel in wfg.channels),
        "wfg_wait_run_s": tuple(
            (channel.trigger.sec_wait, channel.trigger.sec_run) for channel in wfg.channels
        ),
        "do_channels": tuple(
            (
                channel.channel_index,
                channel.enable,
                channel.clock_frequency_hz,
                channel.trigger.sec_wait,
                channel.trigger.sec_run,
            )
            for channel in do_config.channels
        ),
        "sequence_settings": dict(experiment.sequence_settings or {}),
        "flush_enabled": experiment.flush_enabled,
        "flush": (
            experiment.flush_settings.flush_flowrate,
            experiment.flush_settings.flush_volume_ml,
            experiment.flush_settings.wait_after_flush_s,
            experiment.flush_settings.syringe_volume_ml,
        ),
        "tec_target_c": experiment.tec_target_c,
        "tec_targets_c": dict(experiment.tec_targets_c or {}),
    }


def _stable_value(value: Any) -> Any:
    """Normalize dataclass/enum/path values without dropping parameters."""

    if is_dataclass(value) and not isinstance(value, type):
        return _stable_value(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: _stable_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return tuple(_stable_value(item) for item in value)
    return value


def run_plan_from_existing_series(
    output_path: Path,
    series: ExperimentSeries2 | list[ExperimentSeries2],
    *,
    total_frames: int,
) -> RunPlan:
    groups = [series] if isinstance(series, ExperimentSeries2) else list(series)
    conditions = tuple(_condition_from_experiment(experiment, group_index)
                       for group_index, group in enumerate(groups, start=1)
                       for experiment in (group.experiments or ()))
    return RunPlan(
        Path(output_path), conditions,
        tuple(len(group.experiments or ()) for group in groups), total_frames,
    )


def build_independent_run_plan(request: ExperimentRequest) -> RunPlan:
    """Pure static planner: no UI, legacy builder, runtime, or hardware access."""
    if request.repeats_per_group < 1:
        raise ValueError("Repeats must be at least one.")
    if request.camera_fps <= 0:
        raise ValueError("Camera FPS must be greater than zero.")
    scan_effective = _frequency_scan_is_effective(request)
    if scan_effective and len(request.frequency_values_hz) != request.repeats_per_group:
        raise ValueError("Frequency-list count must match repeats.")
    targets = request.temperature_targets_c if request.tec_scan_enabled else ((),)
    if request.tec_scan_enabled and not targets:
        raise ValueError("Enable TEC temperature scan with at least one temperature point.")
    if request.dynamic_camera_start and len(request.camera_start_s) < request.repeats_per_group:
        raise ValueError("Dynamic Camera Start Time has more repeats than Camera Start Array entries.")
    conditions: list[RunCondition] = []
    for group_index, target in enumerate(targets, start=1):
        temperature_c = dict(target).get(1, next(iter(dict(target).values()), None))
        root = (
            request.output_path / _temperature_folder_name(group_index, float(temperature_c))
            if request.tec_scan_enabled and temperature_c is not None
            else request.output_path
        )
        for repeat_id in range(request.repeats_per_group):
            start = (
                request.camera_start_s[repeat_id]
                if request.dynamic_camera_start
                else (request.fixed_camera_start_s if request.fixed_camera_start_s is not None else request.camera_start_s[0])
            )
            do = _freeze_mapping(_do_config_recipe(request.camera_fps, request.frames, start))
            wfg = _thaw(request.wfg_templates[0]) if request.wfg_templates else {}
            selected = request.frequency_values_hz[repeat_id] if scan_effective else None
            if selected is not None:
                wfg["channels"][0]["carrier"]["frequency_hz"] = selected
            sequence = {key: _thaw(value) for key, value in request.sequence_settings}
            sequence["camera_start_s"] = list(request.camera_start_s)
            sequence["camera_start_mode"] = "dynamic" if request.dynamic_camera_start else "fixed"
            sequence["camera_start_selected_s"] = start
            conditions.append(RunCondition(group_index, repeat_id, request.output_path,
                root / f"repeat_{repeat_id + 1:03d}", tuple(target), selected, _freeze_mapping(wfg), do,
                tuple((key, _freeze_value(value)) for key, value in sequence.items()),
                request.flush_settings, request.flush_enabled,
                request.exposure_ms, request.trigger_global_exposure,
                request.fm_sweep if request.fm_sweep_enabled and request.channel0_waveform_function != "DC" else None))
    return RunPlan(request.output_path, tuple(conditions), tuple([request.repeats_per_group] * len(targets)), request.frames * len(conditions))


def legacy_series_from_run_plan(plan: RunPlan) -> list[ExperimentSeries2]:
    """Explicit offline compatibility adapter; it never reads UI or hardware."""
    groups: list[ExperimentSeries2] = []
    cursor = 0
    for size in plan.group_sizes:
        experiments = []
        for condition in plan.conditions[cursor:cursor + size]:
            experiments.append(Experiment2(repeat_id=condition.repeat_id, experiment_folder=condition.experiment_folder,
                output_root=condition.output_root, planned_repeat_count=size,
                temperature_point_index=condition.group_index if len(plan.group_sizes) > 1 else None,
                frequency_scan_selected_hz=condition.selected_frequency_hz,
                flush_settings=FlushSettings(*condition.flush_settings),
                flush_enabled=condition.flush_enabled, global_exposure_ms=condition.exposure_ms,
                trigger_global_exposure=condition.trigger_global_exposure,
                sequence_settings={key: _thaw(value) for key, value in condition.sequence_settings},
                wfg_config=_thaw(condition.wfg_config),
                do_clock_settings=coerce_do_config(_thaw(condition.do_config)),
                fm_sweep=(FmSweepSettings(*condition.fm_sweep) if condition.fm_sweep is not None else None),
                tec_target_c=dict(condition.temperature_targets_c).get(1),
                tec_targets_c=dict(condition.temperature_targets_c) or None,
            ))
        series_path = experiments[0].experiment_folder.parent if experiments else plan.output_path
        groups.append(ExperimentSeries2(series_path, experiments)); cursor += size
    return groups


def temperature_series_from_request(request: ExperimentRequest) -> TemperatureSeries:
    """Explicit compatibility adapter for the legacy TEC settling workflow."""
    if not request.tec_scan_enabled:
        return TemperatureSeries()
    targets = request.temperature_targets_c
    if not targets:
        return TemperatureSeries()
    points_ch1 = [dict(target)[1] for target in targets]
    points_ch2 = [dict(target).get(2) for target in targets]
    unlocked = any(point is not None and point != points_ch1[index] for index, point in enumerate(points_ch2))
    tolerance, min_settle, max_wait, poll, hold = request.tec_settle_settings
    return TemperatureSeries(
        temperature_points_c=points_ch1,
        temperature_points_ch2_c=([float(point) for point in points_ch2] if unlocked else None),
        tolerance_c=tolerance, min_settle_s=min_settle, max_wait_s=max_wait,
        poll_interval_s=poll, post_stable_hold_s=hold,
    )


def _condition_from_experiment(experiment: Experiment2, group_index: int) -> RunCondition:
    return RunCondition(group_index, experiment.repeat_id, experiment.output_root or experiment.experiment_folder.parent,
        experiment.experiment_folder, tuple(sorted((experiment.tec_targets_c or {}).items())), experiment.frequency_scan_selected_hz,
        _freeze_mapping(asdict(coerce_wfg_config(experiment.wfg_config))),
        _freeze_mapping(asdict(coerce_do_config(experiment.do_clock_settings))),
        tuple((key, _freeze_value(value)) for key, value in (experiment.sequence_settings or {}).items()),
        (experiment.flush_settings.flush_flowrate, experiment.flush_settings.flush_volume_ml, experiment.flush_settings.wait_after_flush_s, experiment.flush_settings.syringe_volume_ml), experiment.flush_enabled, experiment.global_exposure_ms, experiment.trigger_global_exposure, _stable_value(experiment.fm_sweep))


def _temperature_folder_name(index: int, temperature_c: float) -> str:
    label = f"{temperature_c:.3f}".replace("-", "m").replace(".", "p")
    return f"temperature_{index:03d}_{label}C"


def _do_config_recipe(camera_fps: float, frames: int, camera_start_s: float) -> dict[str, Any]:
    """The legacy CreateExperiments DIO1 recipe, expressed as static data."""
    return {
        "running": True,
        "channels": [{
            "channel_index": 1, "enable": True, "clock_frequency_hz": camera_fps,
            "output_type": "Pulse", "output_mode": "PushPull", "idle_state": "Initial",
            "counter_high_bits": 1, "counter_low_bits": 1, "counter_initial_bits": 0,
            "start_high": True,
            "trigger": {"sec_run": frames / camera_fps, "sec_wait": camera_start_s},
        }],
    }


def _freeze_mapping(value: FrozenMapping | dict[str, Any]) -> FrozenMapping:
    if isinstance(value, FrozenMapping):
        return value
    return FrozenMapping(tuple(sorted((str(key), _freeze_value(item)) for key, item in value.items())))


def _freeze_value(value: Any) -> Any:
    if isinstance(value, FrozenMapping | FrozenSequence):
        return value
    if is_dataclass(value) and not isinstance(value, type):
        return _freeze_mapping(asdict(value))
    if isinstance(value, dict):
        return _freeze_mapping(value)
    if isinstance(value, (list, tuple)):
        return FrozenSequence(tuple(_freeze_value(item) for item in value))
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, FrozenMapping):
        return {key: _thaw(item) for key, item in value.items}
    if isinstance(value, FrozenSequence):
        return [_thaw(item) for item in value.values]
    return deepcopy(value)


def blocking_build_result(request: ExperimentRequest, error: BaseException | str) -> BuildResult:
    issue = PreflightIssue(code="build_error", message=str(error), blocking=True)
    return BuildResult(
        request=request,
        plan=None,
        preflight=PreflightResult(
            required_devices=_required_devices(request),
            selected_devices=_selected_devices(request),
            simulated_devices=_simulated_devices(request),
            disabled_devices=_disabled_devices(request),
            experiment_axes=(("temperature", len(request.temperature_targets_c) or 1), ("repeat", request.repeats_per_group)),
            frequency_repeat_compatible=(
                not _frequency_scan_is_effective(request)
                or len(request.frequency_values_hz) == request.repeats_per_group
            ),
            camera_timing_valid=request.camera_fps > 0,
            output_path_state="configured" if str(request.output_path) not in ("", ".") else "implicit_working_directory",
            fluidics_required=request.flush_enabled,
            tec_required=request.tec_scan_enabled,
            issues=(issue,),
        ),
    )


def build_result_from_existing_plan(
    request: ExperimentRequest,
    plan: RunPlan,
    evidence: RuntimeEvidenceSnapshot,
) -> BuildResult:
    issues: list[PreflightIssue] = []
    scan_effective = _frequency_scan_is_effective(request)
    compatible = not scan_effective or len(request.frequency_values_hz) == request.repeats_per_group
    if not compatible:
        issues.append(
            PreflightIssue(
                code="frequency_repeat_mismatch",
                message="Frequency-list count must match repeats.",
                blocking=True,
            )
        )
    if request.camera_fps <= 0:
        issues.append(PreflightIssue(code="camera_fps", message="Camera FPS must be greater than zero.", blocking=True))
    if request.dynamic_camera_start and len(request.camera_start_s) < request.repeats_per_group:
        issues.append(
            PreflightIssue(
                code="camera_start_slots",
                message="Per-repeat DIO1 start slots are insufficient.",
                blocking=True,
            )
        )
    output_state = "configured" if str(request.output_path) not in ("", ".") else "implicit_working_directory"
    if output_state != "configured":
        issues.append(
            PreflightIssue(
                code="implicit_output_path",
                message="Blank output path resolves to the current working directory; writeability is not yet proven.",
                blocking=False,
            )
        )
    else:
        issues.append(
            PreflightIssue(
                code="output_writeability_unverified",
                message="Output path is configured; writeability is verified only when the run creates its record.",
                blocking=False,
                verification=VerificationScope.UNVERIFIED,
            )
        )
    for name in _disabled_devices(request):
        issues.append(
            PreflightIssue(
                code=f"{name}_disabled",
                message=f"{name.upper()} is disabled; the current runtime will skip its hardware actions.",
                blocking=False,
            )
        )
    if request.tec_scan_enabled and "tec" in _simulated_devices(request):
        issues.append(
            PreflightIssue(
                code="tec_simulated",
                message="TEC scan is selected but TEC evidence is simulated, not physical.",
                blocking=False,
            )
        )
    if request.frequency_scan_enabled and not scan_effective:
        issues.append(
            PreflightIssue(
                code="frequency_scan_ignored_for_dc",
                message="Frequency scan is selected but has no effect while Channel 0 uses DC.",
                blocking=False,
            )
        )
    if request.fm_sweep_enabled and request.channel0_waveform_function == "DC":
        issues.append(
            PreflightIssue(
                code="fm_sweep_ignored_for_dc",
                message="FM sweep is selected but has no effect while Channel 0 uses DC.",
                blocking=False,
            )
        )
    if request.fm_sweep_enabled and request.channel0_waveform_function != "DC" and not request.channel0_output_selected:
        issues.append(
            PreflightIssue(
                code="fm_enables_channel0",
                message="FM sweep enables channel 0 in the authoritative builder although Channel output is unchecked.",
                blocking=False,
            )
        )
    if request.flush_enabled:
        first = plan.experiments[0] if plan.experiments else None
        if first is not None and first.flush_settings[1] > first.flush_settings[3]:
            issues.append(
                PreflightIssue(
                    code="flush_capacity",
                    message="Flush volume exceeds selected syringe capacity.",
                    blocking=False,
                )
            )
        pump_fill = evidence.pump.values.get("fill_level_ml")
        if first is not None and pump_fill is not None and pump_fill.value is not None:
            if first.flush_settings[1] > float(pump_fill.value):
                issues.append(
                    PreflightIssue(
                        code="flush_tracked_fill",
                        message="Flush volume exceeds the pump's cached tracked fill level.",
                        blocking=False,
                        verification=pump_fill.verification,
                    )
                )
        issues.append(
            PreflightIssue(
                code="valve_route_unverified",
                message="P01/P02 physical fluid routing remains bench-unverified.",
                blocking=False,
                verification=VerificationScope.UNVERIFIED,
            )
        )
        issues.append(
            PreflightIssue(
                code="syringe_application_manual",
                message="Selected syringe geometry must still be applied through the explicit pump action.",
                blocking=False,
                verification=VerificationScope.UNVERIFIED,
            )
        )
    issues.append(
        PreflightIssue(
            code="dio_camera_timing_unverified",
            message="DIO1-to-camera exposure synchronization remains bench-unverified.",
            blocking=False,
            verification=VerificationScope.UNVERIFIED,
        )
    )
    # Force the evidence dependency to remain explicit even before every
    # subsystem contributes preflight fields. This is an in-memory read only.
    _ = evidence.experiment.values.get("status")
    return BuildResult(
        request=request,
        plan=plan,
        preflight=PreflightResult(
            required_devices=_required_devices(request),
            selected_devices=_selected_devices(request),
            simulated_devices=_simulated_devices(request),
            disabled_devices=_disabled_devices(request),
            experiment_axes=(("temperature", len(request.temperature_targets_c) or 1), ("repeat", request.repeats_per_group)),
            frequency_repeat_compatible=compatible,
            camera_timing_valid=request.camera_fps > 0,
            output_path_state=output_state,
            fluidics_required=request.flush_enabled,
            tec_required=request.tec_scan_enabled,
            issues=tuple(issues),
        ),
    )


def _device_modes(request: ExperimentRequest) -> dict[str, tuple[bool, bool]]:
    return {name: (enabled, simulated) for name, enabled, simulated in request.device_modes}


def _frequency_scan_is_effective(request: ExperimentRequest) -> bool:
    """Match the legacy builder, which intentionally skips scan for DC."""

    return request.frequency_scan_enabled and request.channel0_waveform_function != "DC"


def _required_devices(request: ExperimentRequest) -> tuple[str, ...]:
    required = ["ad2", "camera"]
    if request.flush_enabled:
        required.extend(("pump", "valve"))
    if request.tec_scan_enabled:
        required.append("tec")
    return tuple(required)


def _selected_devices(request: ExperimentRequest) -> tuple[str, ...]:
    modes = _device_modes(request)
    return tuple(name for name in _required_devices(request) if modes.get(name, (False, False))[0])


def _simulated_devices(request: ExperimentRequest) -> tuple[str, ...]:
    modes = _device_modes(request)
    return tuple(name for name in _required_devices(request) if modes.get(name, (False, False))[1])


def _disabled_devices(request: ExperimentRequest) -> tuple[str, ...]:
    modes = _device_modes(request)
    return tuple(name for name in _required_devices(request) if not modes.get(name, (False, False))[0])
