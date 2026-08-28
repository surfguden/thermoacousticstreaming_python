from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .ad2 import coerce_do_config, coerce_wfg_config
from .camera import SubRegion
from .runtime_truth import RuntimeEvidenceSnapshot, VerificationScope
from .workflows import Experiment2, ExperimentSeries2


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
class ExperimentRequest:
    output_path: Path
    repeats_per_group: int
    frequency_scan_enabled: bool
    frequency_values_hz: tuple[float, ...]
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


@dataclass(frozen=True, slots=True)
class RunPlan:
    output_path: Path
    experiment_groups: tuple[tuple[Experiment2, ...], ...]
    total_frames: int

    @property
    def experiments(self) -> tuple[Experiment2, ...]:
        return tuple(experiment for group in self.experiment_groups for experiment in group)

    def normalized_experiments(self) -> tuple[dict[str, Any], ...]:
        return tuple(normalize_experiment(experiment) for experiment in self.experiments)

    def normalized_groups(self) -> tuple[tuple[dict[str, Any], ...], ...]:
        return tuple(
            tuple(normalize_experiment(experiment) for experiment in group)
            for group in self.experiment_groups
        )


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
    return RunPlan(
        output_path=Path(output_path),
        experiment_groups=tuple(tuple(group.experiments or ()) for group in groups),
        total_frames=total_frames,
    )


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
                not request.frequency_scan_enabled
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
    compatible = not request.frequency_scan_enabled or len(request.frequency_values_hz) == request.repeats_per_group
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
    if request.fm_sweep_enabled and not request.channel0_output_selected:
        issues.append(
            PreflightIssue(
                code="fm_enables_channel0",
                message="FM sweep enables channel 0 in the authoritative builder although Channel output is unchecked.",
                blocking=False,
            )
        )
    if request.flush_enabled:
        first = plan.experiments[0] if plan.experiments else None
        if first is not None and first.flush_settings.flush_volume_ml > first.flush_settings.syringe_volume_ml:
            issues.append(
                PreflightIssue(
                    code="flush_capacity",
                    message="Flush volume exceeds selected syringe capacity.",
                    blocking=False,
                )
            )
        pump_fill = evidence.pump.values.get("fill_level_ml")
        if first is not None and pump_fill is not None and pump_fill.value is not None:
            if first.flush_settings.flush_volume_ml > float(pump_fill.value):
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
