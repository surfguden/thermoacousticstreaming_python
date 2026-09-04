from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from functools import lru_cache
import json
import os
from pathlib import Path
import subprocess
from typing import Any

import numpy as np

from .ad2 import DoConfig, FmSweepSettings, WfgConfig, coerce_do_config, coerce_wfg_config, waveform_parameter_policy
from .tec import validate_tec_target_temperature

# Cheap sanity floor for _verify_tdms_write() -- not a rigorous size model,
# just enough to catch a silently-empty/header-only write. A real TDMS file
# with the "Experiment" group's properties is comfortably larger than this.
_MIN_TDMS_FILE_SIZE_BYTES = 128


@dataclass(slots=True)
class SeriesLifecycleManifest:
    """Small, series-local aggregate record for execution lifecycle truth.

    Per-repeat TDMS remains the authoritative record for requested settings,
    runtime evidence, and detailed failures.  This record only makes the
    requested-versus-started aggregate visible when a series stops early.
    """

    series_path: Path
    requested_repeats: int
    tec_points_requested: int | None = None
    started_repeats: int = 0
    completed_repeats: int = 0
    failed_repeats: int = 0
    graceful_abort_requested: bool = False
    outcome: str = "IN_PROGRESS"
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finalized_at: str | None = None
    tec_points_started: int = 0
    tec_points_completed: int = 0

    @property
    def path(self) -> Path:
        return self.series_path / "series_manifest.json"

    @classmethod
    def create(
        cls,
        series_path: Path,
        *,
        requested_repeats: int,
        tec_points_requested: int | None = None,
    ) -> "SeriesLifecycleManifest":
        manifest = cls(Path(series_path), requested_repeats, tec_points_requested)
        manifest._write()
        return manifest

    def repeat_started(self) -> None:
        self.started_repeats += 1
        self._write()

    def repeat_completed(self) -> None:
        self.completed_repeats += 1
        self._write()

    def repeat_failed(self) -> None:
        self.failed_repeats += 1
        self._write()

    def tec_point_started(self) -> None:
        if self.tec_points_requested is None:
            return
        self.tec_points_started += 1
        self._write()

    def tec_point_completed(self) -> None:
        if self.tec_points_requested is None:
            return
        self.tec_points_completed += 1
        self._write()

    def finalize(self, outcome: str, *, graceful_abort_requested: bool = False) -> None:
        if outcome not in {"COMPLETED", "FAILED", "GRACEFULLY_ABORTED"}:
            raise ValueError(f"Unsupported series lifecycle outcome: {outcome!r}")
        self.outcome = outcome
        self.graceful_abort_requested = graceful_abort_requested
        self.finalized_at = datetime.now(timezone.utc).isoformat()
        self._write()

    def _payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": 1,
            "series_id": self.series_path.name,
            "series_path": str(self.series_path),
            "output_path": str(self.series_path),
            "action_log_path": str(self.series_path / "action_log.jsonl"),
            "requested_repeats": self.requested_repeats,
            "started_repeats": self.started_repeats,
            "completed_repeats": self.completed_repeats,
            "failed_repeats": self.failed_repeats,
            "graceful_abort_requested": self.graceful_abort_requested,
            "outcome": self.outcome,
            "started_at": self.started_at,
            "finalized_at": self.finalized_at,
        }
        if self.tec_points_requested is not None:
            payload["tec_points"] = {
                "requested": self.tec_points_requested,
                "started": self.tec_points_started,
                "completed": self.tec_points_completed,
            }
        return payload

    def _write(self) -> None:
        self.series_path.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_name(f"{self.path.name}.tmp")
        with temporary_path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(self._payload(), handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, self.path)


@lru_cache(maxsize=1)
def _git_commit_hash() -> str:
    repo_root = Path(__file__).resolve().parents[2]
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout.strip()
    except Exception:
        return "unknown"
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout
        if status.strip():
            commit += "-dirty"
    except Exception:
        pass
    return commit


@dataclass(slots=True)
class FlushSettings:
    flush_flowrate: float
    flush_volume_ml: float
    wait_after_flush_s: float
    syringe_volume_ml: float = 60.0

    @property
    def timeout_s(self) -> float:
        if self.flush_flowrate <= 0:
            return 0.0
        # flush_flowrate is uL/min on the real device (QmixPumpBackend.initialize()
        # calls configure_flow_unit("ul/min")). Convert flush_volume_ml -> uL
        # (x1000), divide by the uL/min flow rate to get minutes, then x60 for
        # seconds, plus a fixed safety margin. The previous formula omitted the
        # x60 minutes-to-seconds conversion, making the computed timeout ~60x
        # too short at realistic flow rates -- confirmed on real Qmix hardware,
        # where a 0.05 ml / 200 uL/min flush (needing ~15s) was declared failed
        # after only ~5.25s while the real pump was still successfully moving.
        return (self.flush_volume_ml * 1000.0 / self.flush_flowrate) * 60.0 + 5.0


@dataclass(slots=True)
class TemperatureSeries:
    # Channel 1's series when unlocked; the single shared series (both
    # channels) when locked (temperature_points_ch2_c is None).
    temperature_points_c: list[float] = field(default_factory=list)
    # None = locked, channel 2 mirrors temperature_points_c exactly (this
    # project's original, still-default behavior). A list = unlocked,
    # channel 2 has its own independent per-step targets -- must be the
    # same length as temperature_points_c: the scan is one sequence of
    # steps, each step moving both channels to their own target
    # simultaneously before the shared experiment group at that step
    # runs, so there is no coherent meaning for the two channels to have
    # different step counts.
    temperature_points_ch2_c: list[float] | None = None
    tolerance_c: float = 0.1
    min_settle_s: float = 5.0
    max_wait_s: float = 300.0
    poll_interval_s: float = 1.0
    # Distinct from min_settle_s (which is part of HOW wait_until_stable()
    # itself decides the TEC sensor reading is "stable" -- continuous time
    # within tolerance). This is a SEPARATE, additional hold applied AFTER
    # stability is already confirmed, before the temperature point's
    # experiment group runs -- for real sample thermal equilibration,
    # which can lag behind the TEC's own sensor stabilizing. Default 0.0:
    # no extra wait, exactly today's existing behavior, unless explicitly
    # set.
    post_stable_hold_s: float = 0.0

    def __post_init__(self) -> None:
        self.temperature_points_c = [validate_tec_target_temperature(point) for point in self.temperature_points_c]
        if self.temperature_points_ch2_c is not None:
            self.temperature_points_ch2_c = [
                validate_tec_target_temperature(point) for point in self.temperature_points_ch2_c
            ]
            if len(self.temperature_points_ch2_c) != len(self.temperature_points_c):
                raise ValueError(
                    "TEC temperature_points_ch2_c must be the same length as temperature_points_c "
                    f"({len(self.temperature_points_ch2_c)} vs {len(self.temperature_points_c)})."
                )
        if self.tolerance_c < 0:
            raise ValueError("TEC tolerance_c must be >= 0.")
        if self.min_settle_s < 0:
            raise ValueError("TEC min_settle_s must be >= 0.")
        if self.max_wait_s < 0:
            raise ValueError("TEC max_wait_s must be >= 0.")
        if self.poll_interval_s <= 0:
            raise ValueError("TEC poll_interval_s must be > 0.")
        if self.post_stable_hold_s < 0:
            raise ValueError("TEC post_stable_hold_s must be >= 0.")

    @property
    def enabled(self) -> bool:
        return bool(self.temperature_points_c)

    @property
    def unlocked(self) -> bool:
        return self.temperature_points_ch2_c is not None

    def target_at(self, step_index: int) -> float | dict[int, float]:
        """The target for run_temperature_series()'s step `step_index`:
        a plain float when locked (broadcasts to whichever channels
        TecController is configured for), or a {1: ..., 2: ...} dict
        when unlocked."""
        if self.temperature_points_ch2_c is None:
            return self.temperature_points_c[step_index]
        return {1: self.temperature_points_c[step_index], 2: self.temperature_points_ch2_c[step_index]}

    @classmethod
    def from_text(
        cls,
        text: str,
        *,
        text_ch2: str | None = None,
        tolerance_c: float = 0.1,
        min_settle_s: float = 5.0,
        max_wait_s: float = 300.0,
        poll_interval_s: float = 1.0,
        post_stable_hold_s: float = 0.0,
    ) -> "TemperatureSeries":
        # text_ch2 unset or blank -> locked (temperature_points_ch2_c stays
        # None, channel 2 mirrors channel 1). A non-blank text_ch2 ->
        # unlocked, parsed the same comma/semicolon-separated way.
        points = cls._parse_points(text)
        points_ch2 = cls._parse_points(text_ch2) if text_ch2 and text_ch2.strip() else None
        return cls(
            temperature_points_c=points,
            temperature_points_ch2_c=points_ch2,
            tolerance_c=tolerance_c,
            min_settle_s=min_settle_s,
            max_wait_s=max_wait_s,
            poll_interval_s=poll_interval_s,
            post_stable_hold_s=post_stable_hold_s,
        )

    @staticmethod
    def _parse_points(text: str) -> list[float]:
        points = []
        for item in text.replace(";", ",").split(","):
            item = item.strip()
            if item:
                points.append(float(item))
        return points


@dataclass(slots=True)
class Experiment2:
    repeat_id: int = 0
    experiment_folder: Path = Path()
    # Explicit planned identity, populated by the legacy UI builder. These
    # fields retain the condition that produced one saved repeat without
    # requiring a later reader to infer it from folder names.
    output_root: Path | None = None
    planned_repeat_count: int | None = None
    temperature_point_index: int | None = None
    frequency_scan_selected_hz: float | None = None
    flush_settings: FlushSettings = field(default_factory=lambda: FlushSettings(0.0, 0.0, 0.0))
    flush_enabled: bool = False
    global_exposure_ms: float = 0.0
    trigger_global_exposure: bool = False
    sequence_settings: dict[str, Any] | None = None
    wfg_config: WfgConfig | dict[str, Any] | None = None
    do_clock_settings: DoConfig | dict[str, Any] | None = None
    fm_sweep: FmSweepSettings | None = None
    # Backward-compatible single-target field retained for existing TDMS
    # readers. For unlocked scans it remains channel 1's target; the explicit
    # per-channel mapping below preserves channel 2 as well.
    tec_target_c: float | None = None
    tec_targets_c: dict[int, float] | None = None
    # Whether each instrument was a Simulated*/simulate=True backend for this
    # run, not requested/enabled state -- set by Application.run_experiment2()
    # from the live instrument instances right before the settings snapshot,
    # since Experiment2 itself has no reference to Application/hardware.
    # Without this, a simulated dry-run and a real experiment produce
    # structurally identical data.tdms files with no way to tell them apart
    # after the fact.
    sim_ad2: bool = False
    sim_camera: bool = False
    sim_pump: bool = False
    sim_valve: bool = False
    # TEC defaults deliberately match HardwareRuntimeConfig's safe default:
    # simulated and disabled until Application snapshots the live controller.
    sim_tec: bool = True
    # Real requested enabled/disabled state for this run, set alongside the
    # sim_* flags above from the same live instrument instances. A distinct
    # concept from sim_*: an instrument can be real (not simulated) and still
    # disabled for this run -- previously that combination was invisible in
    # data.tdms, so a run where e.g. AD2 was genuinely disabled (its
    # per-step hardware calls skipped entirely by run_experiment2(), not
    # attempted) looked structurally identical to a run where AD2 was fully
    # active. See known_open_items.md.
    ad2_enabled: bool = True
    camera_enabled: bool = True
    pump_enabled: bool = True
    valve_enabled: bool = True
    tec_enabled: bool = False
    # Session 104: whether Application.clear_pump_fault_and_retry() -- the
    # manual, operator-initiated pump fault-clear escape hatch -- had been
    # used at any point in the session by the time this repeat ran. Set by
    # Application.run_experiment2() from live Application state, same
    # pattern as sim_*/*_enabled above. See docs/hardware_repair_plan.md.
    pump_fault_manually_cleared: bool = False
    # Set only after Application successfully configures the canonical
    # DigitalOut program. It is API configuration evidence, never an
    # electrical-edge or optical-emission claim.
    do_configured_by_runtime: bool = False
    # Preserve the canonical request separately from DCAM's applied readback.
    # These are appended after the established public constructor fields so
    # older positional Experiment2 callers retain their existing argument
    # order. global_exposure_ms remains the compatibility/effective field and
    # is updated to the applied value after camera configuration.
    requested_exposure_ms: float | None = None
    applied_exposure_ms: float | None = None
    _tdms_properties: dict[str, Any] = field(default_factory=dict, init=False)
    _tdms_image_names: list[str] = field(default_factory=list, init=False)
    _tdms_timestamps: list[str] = field(default_factory=list, init=False)
    _record_created: bool = field(default=False, init=False)

    def create_folder_and_tdms(self) -> Path:
        self.experiment_folder.mkdir(parents=True, exist_ok=True)
        self._tdms_properties.setdefault("Experiment started", datetime.now(timezone.utc).isoformat())
        self._tdms_properties.setdefault("RecordOutcome", "IN_PROGRESS")
        self._tdms_properties.setdefault("PrimaryFailure", "")
        self._tdms_properties.setdefault("CleanupFailure", "")
        self._write_tdms()
        self._record_created = True
        return self.experiment_folder

    def finalize_record(
        self,
        outcome: str,
        *,
        primary_failure: BaseException | str | None = None,
        cleanup_failure: BaseException | str | None = None,
    ) -> None:
        """Persist the terminal truth for a repeat that already has a TDMS record.

        This deliberately records only what the workflow reached. A FAILED
        record does not claim that requested settings were applied; a cleanup
        error stays distinct from the primary workflow error.
        """
        self.experiment_folder.mkdir(parents=True, exist_ok=True)
        self._tdms_properties.update(
            {
                "RecordOutcome": outcome,
                "RecordFinalized": datetime.now(timezone.utc).isoformat(),
                "PrimaryFailure": "" if primary_failure is None else str(primary_failure),
                "CleanupFailure": "" if cleanup_failure is None else str(cleanup_failure),
            }
        )
        self._write_tdms()

    def save_settings(self) -> None:
        self.experiment_folder.mkdir(parents=True, exist_ok=True)
        self._tdms_properties.update(self._settings_properties())
        self._write_tdms()

    def save_camera_settings(self, settings: dict[str, Any]) -> None:
        self.experiment_folder.mkdir(parents=True, exist_ok=True)
        self._tdms_properties.update(self._camera_properties(settings))
        self._write_tdms()

    def save_flush_result(self, completed: bool) -> None:
        # Session 7 already made a failed flush surface loudly (status event,
        # log, Application.errors) -- but that visibility is process-level,
        # not recorded into this repeat's own data.tdms. Someone inspecting
        # data.tdms in isolation, without cross-referencing the live app log
        # (not persisted per-experiment), previously had no way to tell a
        # flush ever failed for that repeat -- FlushVolume/FlushFlowrate look
        # equally plausible either way. Called separately from save_settings()
        # because flush happens after both save_settings() calls in
        # run_experiment2(), on both the success and early-return-on-failure
        # paths.
        self.experiment_folder.mkdir(parents=True, exist_ok=True)
        self._tdms_properties["FlushCompleted"] = completed
        self._write_tdms()

    def save_image_data(self, image_data: Any, frame_timestamps: list[str] | None = None) -> None:
        self.experiment_folder.mkdir(parents=True, exist_ok=True)
        frames = [] if image_data is None else list(image_data)
        self._tdms_image_names = [f"frame_{index:05d}.tiff" for index, _frame in enumerate(frames)]
        if frame_timestamps and len(frame_timestamps) == len(frames):
            # Real per-frame acquisition timestamps from the Hamamatsu DCAM
            # frame buffer (DCAMBUF_FRAME.timestamp via HamamatsuDcamBackend),
            # only populated when the camera/driver reports hardware
            # timestamp support. These are in the camera driver's own clock
            # domain, not verified against host wall-clock or AD2 trigger
            # timing -- see hamamatsu_dcam.py's _last_frame_copy().
            self._tdms_timestamps = list(frame_timestamps)
        else:
            # Python frames do not yet carry camera acquisition timestamps, so keep
            # LabVIEW's Timestamp field using metadata write-time values for now.
            self._tdms_timestamps = [datetime.now(timezone.utc).isoformat() for _frame in frames]
        self._write_tdms()

    def cleanup(self) -> None:
        pass

    @property
    def tdms_path(self) -> Path:
        return self.experiment_folder / "data.tdms"

    @property
    def action_log_path(self) -> Path | None:
        series_root = Path(self.output_root or self.experiment_folder.parent)
        return None if series_root == Path() else series_root / "action_log.jsonl"

    @property
    def action_run_id(self) -> str:
        series_root = Path(self.output_root or self.experiment_folder.parent)
        return series_root.name or "unscoped_run"

    @property
    def action_condition(self) -> str:
        if self.temperature_point_index is not None:
            return f"temperature_point_{self.temperature_point_index + 1}:{self.experiment_folder.parent.name}"
        if self.frequency_scan_selected_hz is not None:
            return f"frequency_hz={self.frequency_scan_selected_hz:g}"
        return "default"

    def _settings_properties(self) -> dict[str, Any]:
        wfg = coerce_wfg_config(self.wfg_config)
        do_clock = coerce_do_config(self.do_clock_settings)
        wfg_channels = {channel.channel_index: channel for channel in wfg.channels}
        ch1 = wfg_channels.get(0)
        ch2 = wfg_channels.get(1)
        do_channel = next((channel for channel in do_clock.channels if channel.enable), None)
        if do_channel is None and do_clock.channels:
            do_channel = do_clock.channels[0]
        requested_exposure_ms = (
            self.global_exposure_ms
            if self.requested_exposure_ms is None
            else self.requested_exposure_ms
        )
        effective_exposure_ms = (
            self.global_exposure_ms
            if self.applied_exposure_ms is None
            else self.applied_exposure_ms
        )
        properties = {
            "Repeat ID": self.repeat_id,
            "RepeatIndex": self.repeat_id,
            "RepeatIndexBase": 0,
            "RepeatNumber": self.repeat_id + 1,
            "RepeatNumberBase": 1,
            "RequestedRepeatCount": "" if self.planned_repeat_count is None else self.planned_repeat_count,
            "OutputRoot": "" if self.output_root is None else str(self.output_root),
            "ExperimentFolder": str(self.experiment_folder),
            "TDMSPath": str(self.tdms_path),
            "ActionLogPath": "" if self.action_log_path is None else str(self.action_log_path),
            "ActionLogRunID": self.action_run_id,
            "ActionLogCondition": self.action_condition,
            "TemperaturePointIndex": "" if self.temperature_point_index is None else self.temperature_point_index,
            "FrequencyScanSelectedHz": (
                "" if self.frequency_scan_selected_hz is None else self.frequency_scan_selected_hz
            ),
            # ExposureTime is retained for existing readers. Before camera
            # configuration it contains the request; after a confirmed DCAM
            # readback it contains the applied value.
            "ExposureTime": effective_exposure_ms,
            "RequestedExposureMs": requested_exposure_ms,
            "AppliedExposureMs": "" if self.applied_exposure_ms is None else self.applied_exposure_ms,
            "GlobalExposure": self.trigger_global_exposure,
            "FlushFlowrate": self.flush_settings.flush_flowrate,
            "FlushFlowrateUnit": "uL/min",
            "FlushVolume": self.flush_settings.flush_volume_ml,
            "FlushVolumeUnit": "mL",
            "WaitAfterFlush": self.flush_settings.wait_after_flush_s,
            "WaitAfterFlushUnit": "s",
            # Default "not attempted" -- both save_settings() calls in
            # run_experiment2() happen before flush() ever runs, so this is
            # always the correct value here; save_flush_result() overwrites
            # it with the real True/False once flush() actually completes.
            "FlushCompleted": "",
            "GitCommitHash": _git_commit_hash(),
            "TECRequested": self.tec_target_c is not None or bool(self.tec_targets_c),
            "TECTarget": "" if self.tec_target_c is None else self.tec_target_c,
            "TECTargetCh1": self._tec_target_for_channel(1),
            "TECTargetCh2": self._tec_target_for_channel(2),
        }
        properties.update(self._wfg_properties("Ch1", ch1))
        properties.update(self._wfg_properties("Ch2", ch2))
        properties.update(
            {
                "WFGPhysicalRoleCh1": "AD2 API 0 / W1 / acoustic amplifier and transducer",
                "WFGPhysicalRoleCh2": "AD2 API 1 / W2 / laser Analog In",
                "WFGCarrierAmplitudeConvention": "AD2_SOURCE_PEAK_VOLTS_NOT_LOADED_OR_DOWNSTREAM",
                "CameraDIO0TriggerRequested": bool(
                    do_clock.running
                    and any(channel.channel_index == 0 and channel.enable for channel in do_clock.channels)
                ),
                "CameraDIO0TriggerUsed": bool(
                    self.do_configured_by_runtime
                    and do_clock.running
                    and any(channel.channel_index == 0 and channel.enable for channel in do_clock.channels)
                ),
                "LEDDIO1TimingRequested": bool(
                    do_clock.running
                    and any(channel.channel_index == 1 and channel.enable for channel in do_clock.channels)
                ),
                "LEDDIO1TimingConfiguredByProductionRuntime": bool(
                    self.do_configured_by_runtime
                    and
                    do_clock.running
                    and any(channel.channel_index == 1 and channel.enable for channel in do_clock.channels)
                ),
                "DIO1Role": "LED_TIMING_CONTROL_NOT_LASER_DIGITAL_IN",
                "DORun": do_channel.trigger.sec_run if do_channel is not None else "",
                "DOWait": do_channel.trigger.sec_wait if do_channel is not None else "",
                "DOFreq": do_channel.clock_frequency_hz if do_channel is not None and do_channel.clock_frequency_hz is not None else "",
                # Finding E: the real achieved frequency after WaveFormsBackend.
                # configure_do()'s integer clock-divider rounding -- set by
                # config_do_clock_special() before this second save_settings()
                # call (see run_experiment2()'s ordering comment above "Finding
                # A"), so this is the post-hardware-configuration value, not
                # the pre-configure default.
                "DOFreqActual": (
                    do_channel.achieved_clock_frequency_hz
                    if do_channel is not None and do_channel.achieved_clock_frequency_hz is not None
                    else ""
                ),
            }
        )
        properties.update(self._fm_sweep_properties())
        properties.update(self._sequence_properties())
        properties.update(
            {
                "SimAD2": self.sim_ad2,
                "SimCamera": self.sim_camera,
                "SimPump": self.sim_pump,
                "SimValve": self.sim_valve,
                "SimTEC": self.sim_tec,
                "AD2Enabled": self.ad2_enabled,
                "CameraEnabled": self.camera_enabled,
                "PumpEnabled": self.pump_enabled,
                "ValveEnabled": self.valve_enabled,
                "TECEnabled": self.tec_enabled,
                "PumpFaultManuallyCleared": self.pump_fault_manually_cleared,
            }
        )
        return properties

    def _tec_target_for_channel(self, channel: int) -> float | str:
        if self.tec_targets_c is not None:
            return self.tec_targets_c.get(channel, "")
        # Historical TECTarget semantics are a broadcast target. Preserve
        # that meaning for callers that have not adopted tec_targets_c yet.
        return "" if self.tec_target_c is None else self.tec_target_c

    def _sequence_properties(self) -> dict[str, Any]:
        # Session 22 made this cluster (masterpulse mode/source/interval/
        # burst + trigger source/polarity/delay) genuinely load-bearing for
        # automated runs -- carried in from the manual Camera tab's own live
        # widgets into _build_experiment_series()'s sequence_settings dict --
        # but none of it was ever recorded into data.tdms, so a repeat's
        # actual DCAM trigger configuration was unrecoverable after the fact.
        # This project's own most-cited unresolved open item is whether
        # camera trigger source should be Internal or External; without this,
        # even confirming *which one was used* for a given saved dataset was
        # impossible from the data alone.
        settings = self.sequence_settings or {}
        do_clock = coerce_do_config(self.do_clock_settings)
        do_channel = next((channel for channel in do_clock.channels if channel.enable), None)
        camera_fps = settings.get("camera_fps")
        if camera_fps is None:
            # Compatibility only for historical records in which Camera FPS
            # lived exclusively on an enabled DO clock channel.
            camera_fps = (
                do_channel.clock_frequency_hz
                if do_channel is not None and do_channel.clock_frequency_hz is not None
                else ""
            )
        return {
            "CameraFrames": settings.get("frames", ""),
            "CameraFPS": camera_fps,
            "CameraFPSUnit": "frames/s",
            "CameraStartMode": settings.get("camera_start_mode", ""),
            "CameraStartRequested": settings.get("camera_start_selected_s", ""),
            "CameraStartRequestedSeconds": settings.get("camera_start_selected_s", ""),
            "TriggerSource": settings.get("trigger_source", ""),
            "MasterPulseMode": settings.get("masterpulse_mode", ""),
            "MasterPulseSource": settings.get("masterpulse_source", ""),
            "MasterPulseInterval": settings.get("masterpulse_interval_s", ""),
            "MasterPulseIntervalSeconds": settings.get("masterpulse_interval_s", ""),
            "MasterPulseBurstTimes": settings.get("masterpulse_burst_times", ""),
            "TriggerPolarity": settings.get("trigger_polarity", ""),
            "TriggerDelay": settings.get("trigger_delay_s", ""),
            "TriggerDelaySeconds": settings.get("trigger_delay_s", ""),
        }

    def _fm_sweep_properties(self) -> dict[str, Any]:
        if self.fm_sweep is None:
            return {
                "FMSweepEnabled": False,
                "FMSweepCenterHz": "",
                "FMSweepWidthKHz": "",
                "FMSweepStartHz": "",
                "FMSweepStopHz": "",
                "FMSweepTotalSpanHz": "",
                "FMSweepHalfDeviationHz": "",
                "FMSweepModulationIndexPercent": "",
                "FMSweepTimeMs": "",
                "FMSweepType": "",
                "FMSweepDirection": "",
                "FMSweepSymmetryPercent": "",
            }
        return {
            "FMSweepEnabled": True,
            "FMSweepCenterHz": self.fm_sweep.center_hz,
            # Retained compatibility field; Width means total start-to-stop span.
            "FMSweepWidthKHz": self.fm_sweep.total_span_hz / 1000.0,
            "FMSweepStartHz": self.fm_sweep.start_hz,
            "FMSweepStopHz": self.fm_sweep.stop_hz,
            "FMSweepTotalSpanHz": self.fm_sweep.total_span_hz,
            "FMSweepHalfDeviationHz": self.fm_sweep.half_deviation_hz,
            "FMSweepModulationIndexPercent": self.fm_sweep.fm_modulation_index_pct,
            "FMSweepTimeMs": self.fm_sweep.sweep_time_ms,
            "FMSweepType": str(self.fm_sweep.sweep_type),
            "FMSweepDirection": self.fm_sweep.sweep_direction,
            "FMSweepSymmetryPercent": self.fm_sweep.fm_mod_settings().symmetry_percent,
        }

    def _wfg_properties(self, suffix: str, channel: Any | None) -> dict[str, Any]:
        if channel is None:
            properties = {
                f"WFGFreq{suffix}": "",
                f"WFGAmp{suffix}": "",
                f"WFGEnabled{suffix}": "",
                f"WFGRun{suffix}": "",
                f"WFGWait{suffix}": "",
                f"Repeat{suffix}": "",
                f"WFGOutOfRange{suffix}": "",
                f"WFGFunction{suffix}": "",
                f"WFGOffset{suffix}": "",
                f"WFGSymmetry{suffix}": "",
                f"WFGPhase{suffix}": "",
                f"WFGTriggerSource{suffix}": "",
                f"WFGEffectiveFreq{suffix}": "",
                f"WFGEffectiveAmp{suffix}": "",
                f"WFGEffectiveOffset{suffix}": "",
                f"WFGEffectiveFunction{suffix}": "",
                f"WFGEffectiveSymmetry{suffix}": "",
                f"WFGEffectivePhase{suffix}": "",
            }
            properties.update(self._wfg_fm_mod_properties(suffix, None))
            properties.update(self._wfg_effective_fm_mod_properties(suffix, None, None))
            return properties
        properties = {
            f"WFGFreq{suffix}": channel.carrier.frequency_hz,
            f"WFGAmp{suffix}": channel.carrier.amplitude_v,
            f"WFGEnabled{suffix}": bool(channel.carrier.enable),
            f"WFGRun{suffix}": channel.trigger.sec_run,
            f"WFGWait{suffix}": channel.trigger.sec_wait,
            f"Repeat{suffix}": channel.trigger.repeat_count,
            # Session 51: True whenever WaveFormsBackend.configure_wfg() had to
            # clamp this channel's carrier/FM-mod frequency or amplitude to
            # the real device's own live AnalogOutNode*Info() range -- so a
            # silently-substituted drive value is recorded in the data itself,
            # not just surfaced transiently in the UI status line.
            f"WFGOutOfRange{suffix}": channel.out_of_range,
            # Finding 1 (workflows.py review, Session 68): these were never
            # recorded at all -- carrier.function/offset_v/symmetry_percent/
            # phase_deg and trigger.source are real, user-editable
            # Experiment-tab fields (qt_ui.py's exp_ch1_function/
            # exp_ch1_offset/exp_ch1_symmetry/exp_ch1_phase), so a saved
            # data.tdms previously could not confirm which waveform shape (or
            # trigger source) an experiment actually used.
            f"WFGFunction{suffix}": channel.carrier.function,
            f"WFGOffset{suffix}": channel.carrier.offset_v,
            f"WFGSymmetry{suffix}": channel.carrier.symmetry_percent,
            f"WFGPhase{suffix}": channel.carrier.phase_deg,
            f"WFGTriggerSource{suffix}": channel.trigger.source,
        }
        effective_carrier = channel.effective_carrier
        policy = waveform_parameter_policy(effective_carrier.function) if effective_carrier is not None else None
        carrier_active = bool(effective_carrier is not None and effective_carrier.enable)
        properties.update({
            f"WFGEffectiveFreq{suffix}": effective_carrier.frequency_hz if carrier_active and policy is not None and policy.is_effective("frequency") else "",
            f"WFGEffectiveAmp{suffix}": effective_carrier.amplitude_v if carrier_active and policy is not None and policy.is_effective("amplitude") else "",
            f"WFGEffectiveOffset{suffix}": effective_carrier.offset_v if carrier_active and policy is not None and policy.is_effective("offset") else "",
            f"WFGEffectiveFunction{suffix}": effective_carrier.function if carrier_active else "",
            f"WFGEffectiveSymmetry{suffix}": effective_carrier.symmetry_percent if carrier_active and policy is not None and policy.is_effective("symmetry") else "",
            f"WFGEffectivePhase{suffix}": effective_carrier.phase_deg if carrier_active and policy is not None and policy.is_effective("phase") else "",
        })
        properties.update(self._wfg_fm_mod_properties(suffix, channel.fm_mod))
        properties.update(
            self._wfg_effective_fm_mod_properties(
                suffix, channel.effective_fm_mod, effective_carrier
            )
        )
        return properties

    def _wfg_fm_mod_properties(self, suffix: str, fm_mod: Any | None) -> dict[str, Any]:
        # fm_mod is never actually None on a real WfgChannelConfig (its field
        # defaults to CarrierSettings(enable=False), not None) -- the None
        # guard here is defensive for duck-typed callers/tests. "Disabled" is
        # fm_mod.enable is False, not fm_mod is None; either way, reporting
        # the disabled CarrierSettings' own default frequency_hz/amplitude_v
        # would misleadingly look like real applied FM-mod settings, so this
        # degrades to the same "" unavailable-sentinel convention
        # _fm_sweep_properties() already uses for its own disabled case,
        # rather than a bare crash or a stale default.
        if fm_mod is None or not fm_mod.enable:
            return {
                f"WFGFMEnabled{suffix}": False,
                f"WFGFMFreq{suffix}": "",
                f"WFGFMAmp{suffix}": "",
                f"WFGFMFunction{suffix}": "",
                f"WFGFMOffset{suffix}": "",
                f"WFGFMSymmetry{suffix}": "",
                f"WFGFMPhase{suffix}": "",
            }
        return {
            f"WFGFMEnabled{suffix}": True,
            f"WFGFMFreq{suffix}": fm_mod.frequency_hz,
            f"WFGFMAmp{suffix}": fm_mod.amplitude_v,
            f"WFGFMFunction{suffix}": fm_mod.function,
            f"WFGFMOffset{suffix}": fm_mod.offset_v,
            f"WFGFMSymmetry{suffix}": fm_mod.symmetry_percent,
            f"WFGFMPhase{suffix}": fm_mod.phase_deg,
        }

    def _wfg_effective_fm_mod_properties(
        self, suffix: str, fm_mod: Any | None, carrier: Any | None
    ) -> dict[str, Any]:
        empty = {
            f"WFGEffectiveFMFreq{suffix}": "",
            f"WFGEffectiveFMModulationIndexPercent{suffix}": "",
            f"WFGEffectiveFMFunction{suffix}": "",
            f"WFGEffectiveFMOffset{suffix}": "",
            f"WFGEffectiveFMSymmetry{suffix}": "",
            f"WFGEffectiveFMPhase{suffix}": "",
            f"WFGEffectiveFMDirection{suffix}": "",
            f"WFGEffectiveFMDerivedStartHz{suffix}": "",
            f"WFGEffectiveFMDerivedStopHz{suffix}": "",
            f"WFGEffectiveFMDerivedTotalSpanHz{suffix}": "",
            f"WFGEffectiveFMDerivedHalfDeviationHz{suffix}": "",
            f"WFGEffectiveFMDerivationScope{suffix}": "",
        }
        if fm_mod is None or not fm_mod.enable or carrier is None:
            return empty
        half_deviation_hz = carrier.frequency_hz * abs(fm_mod.amplitude_v) / 100.0
        return {
            f"WFGEffectiveFMFreq{suffix}": fm_mod.frequency_hz,
            f"WFGEffectiveFMModulationIndexPercent{suffix}": fm_mod.amplitude_v,
            f"WFGEffectiveFMFunction{suffix}": fm_mod.function,
            f"WFGEffectiveFMOffset{suffix}": fm_mod.offset_v,
            f"WFGEffectiveFMSymmetry{suffix}": fm_mod.symmetry_percent,
            f"WFGEffectiveFMPhase{suffix}": fm_mod.phase_deg,
            f"WFGEffectiveFMDirection{suffix}": {
                "Triangle": "BIDIRECTIONAL_BETWEEN_START_AND_STOP",
                "RampUp": "START_TO_STOP_THEN_RESET",
                "RampDown": "STOP_TO_START_THEN_RESET",
            }.get(str(getattr(fm_mod.function, "value", fm_mod.function)), "FUNCTION_SPECIFIC"),
            f"WFGEffectiveFMDerivedStartHz{suffix}": carrier.frequency_hz - half_deviation_hz,
            f"WFGEffectiveFMDerivedStopHz{suffix}": carrier.frequency_hz + half_deviation_hz,
            f"WFGEffectiveFMDerivedTotalSpanHz{suffix}": 2.0 * half_deviation_hz,
            f"WFGEffectiveFMDerivedHalfDeviationHz{suffix}": half_deviation_hz,
            f"WFGEffectiveFMDerivationScope{suffix}": "SOFTWARE_FROM_EFFECTIVE_SDK_PARAMETERS_NOT_MEASURED",
        }

    def _camera_properties(self, settings: dict[str, Any]) -> dict[str, Any]:
        sub_region = settings.get("sub_region", {}) if isinstance(settings, dict) else {}
        return {
            "ReadoutTime": self._setting_value(settings, "readout_time"),
            "ReadoutTimeSeconds": self._setting_value(settings, "readout_time"),
            "HorizontalSize": self._setting_value(sub_region, "horizontal_size"),
            "VerticalSize": self._setting_value(sub_region, "vertical_size"),
            "HorizontalOffset": self._setting_value(sub_region, "horizontal_offset"),
            "VerticalOffset": self._setting_value(sub_region, "vertical_offset"),
        }

    def _setting_value(self, source: Any, name: str) -> Any:
        if isinstance(source, dict):
            return source.get(name, "")
        return getattr(source, name, "")

    def _write_tdms(self) -> None:
        self.experiment_folder.mkdir(parents=True, exist_ok=True)
        try:
            from nptdms import ChannelObject, GroupObject, RootObject, TdmsFile, TdmsWriter
        except ModuleNotFoundError as exc:
            raise RuntimeError("npTDMS is required to write LabVIEW-compatible data.tdms metadata.") from exc

        properties = {name: self._tdms_scalar(value) for name, value in self._tdms_properties.items()}
        objects: list[Any] = [
            RootObject(properties={}),
            GroupObject("Experiment", properties=properties),
        ]
        if self._tdms_image_names:
            objects.append(ChannelObject("ImageData", "ImageName", np.asarray(self._tdms_image_names, dtype=str)))
            objects.append(ChannelObject("ImageData", "Timestamp", np.asarray(self._tdms_timestamps, dtype=str)))
        with TdmsWriter(str(self.tdms_path)) as writer:
            writer.write_segment(objects)

        self._verify_tdms_write(TdmsFile, properties)

    def _verify_tdms_write(self, tdms_file_cls: Any, properties: dict[str, Any]) -> None:
        # Lightweight post-write sanity check -- previously the only "verification"
        # was that TdmsWriter.write_segment() didn't raise. Catches truncated/
        # corrupted writes and silently-empty files; not a full round-trip
        # equality check of every value (that would duplicate the write-path tests).
        try:
            file_size = self.tdms_path.stat().st_size
        except OSError as exc:
            raise RuntimeError(
                f"data.tdms write verification failed: {self.tdms_path} does not exist after write."
            ) from exc
        if file_size < _MIN_TDMS_FILE_SIZE_BYTES:
            raise RuntimeError(
                f"data.tdms write verification failed: {self.tdms_path} is only {file_size} bytes "
                f"(expected at least {_MIN_TDMS_FILE_SIZE_BYTES}) -- looks like a silently empty or "
                "truncated write."
            )

        try:
            read_back = tdms_file_cls.read(str(self.tdms_path))
        except Exception as exc:
            raise RuntimeError(
                f"data.tdms write verification failed: could not reopen {self.tdms_path} with npTDMS's own "
                "reader -- the file is likely corrupted or truncated."
            ) from exc

        try:
            group = read_back["Experiment"]
        except Exception as exc:
            raise RuntimeError(
                f"data.tdms write verification failed: {self.tdms_path} has no 'Experiment' group after write."
            ) from exc

        missing_properties = set(properties) - set(group.properties)
        if missing_properties:
            raise RuntimeError(
                f"data.tdms write verification failed: {self.tdms_path}'s 'Experiment' group is missing "
                f"properties that were just written: {sorted(missing_properties)}."
            )

        if self._tdms_image_names:
            try:
                image_group = read_back["ImageData"]
                image_names = image_group["ImageName"]
                timestamps = image_group["Timestamp"]
            except Exception as exc:
                raise RuntimeError(
                    f"data.tdms write verification failed: {self.tdms_path} is missing the expected "
                    "'ImageData' group/channels after writing image data."
                ) from exc
            if len(image_names) != len(self._tdms_image_names) or len(timestamps) != len(self._tdms_timestamps):
                raise RuntimeError(
                    f"data.tdms write verification failed: {self.tdms_path}'s ImageData channel lengths "
                    f"({len(image_names)} names, {len(timestamps)} timestamps) don't match what was written "
                    f"({len(self._tdms_image_names)} names, {len(self._tdms_timestamps)} timestamps)."
                )

    def _tdms_scalar(self, value: Any) -> Any:
        if value is None:
            return ""
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, np.generic):
            return value.item()
        if isinstance(value, (str, int, float, bool)):
            return value
        return str(value)


@dataclass(slots=True)
class ExperimentSeries2:
    series_path: Path = Path()
    experiments: list[Experiment2] | None = None

    def __post_init__(self) -> None:
        if self.experiments is None:
            self.experiments = []

    def see_elements_left(self) -> int:
        return len(self.experiments or [])

    def get_series_path(self) -> Path:
        return self.series_path

    def create_experiments(self, experiments: list[Experiment2] | None = None) -> list[Experiment2]:
        if experiments is None:
            experiments = []
        self.experiments = list(experiments)
        return self.experiments

    def dequeue_experiment(self) -> tuple[Experiment2 | None, bool]:
        if not self.experiments:
            return None, True
        return self.experiments.pop(0), False

    def enqueue_experiments(self, experiments: list[Experiment2]) -> None:
        if self.experiments is None:
            self.experiments = []
        self.experiments.extend(experiments)
