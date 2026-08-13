from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from functools import lru_cache
from pathlib import Path
import subprocess
from typing import Any

import numpy as np

from .ad2 import DoConfig, FmSweepSettings, WfgConfig, coerce_do_config, coerce_wfg_config
from .tec import validate_tec_target_temperature

# Cheap sanity floor for _verify_tdms_write() -- not a rigorous size model,
# just enough to catch a silently-empty/header-only write. A real TDMS file
# with the "Experiment" group's properties is comfortably larger than this.
_MIN_TDMS_FILE_SIZE_BYTES = 128


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
    flush_settings: FlushSettings = field(default_factory=lambda: FlushSettings(0.0, 0.0, 0.0))
    flush_enabled: bool = False
    global_exposure_ms: float = 0.0
    trigger_global_exposure: bool = False
    sequence_settings: dict[str, Any] | None = None
    wfg_config: WfgConfig | dict[str, Any] | None = None
    do_clock_settings: DoConfig | dict[str, Any] | None = None
    fm_sweep: FmSweepSettings | None = None
    tec_target_c: float | None = None
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
    # Session 104: whether Application.clear_pump_fault_and_retry() -- the
    # manual, operator-initiated pump fault-clear escape hatch -- had been
    # used at any point in the session by the time this repeat ran. Set by
    # Application.run_experiment2() from live Application state, same
    # pattern as sim_*/*_enabled above. See docs/hardware_repair_plan.md.
    pump_fault_manually_cleared: bool = False
    _tdms_properties: dict[str, Any] = field(default_factory=dict, init=False)
    _tdms_image_names: list[str] = field(default_factory=list, init=False)
    _tdms_timestamps: list[str] = field(default_factory=list, init=False)

    def create_folder_and_tdms(self) -> Path:
        self.experiment_folder.mkdir(parents=True, exist_ok=True)
        self._tdms_properties.setdefault("Experiment started", datetime.now(timezone.utc).isoformat())
        self._write_tdms()
        return self.experiment_folder

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

    def _settings_properties(self) -> dict[str, Any]:
        wfg = coerce_wfg_config(self.wfg_config)
        do_clock = coerce_do_config(self.do_clock_settings)
        wfg_channels = {channel.channel_index: channel for channel in wfg.channels}
        ch1 = wfg_channels.get(0)
        ch2 = wfg_channels.get(1)
        do_channel = next((channel for channel in do_clock.channels if channel.enable), None)
        if do_channel is None and do_clock.channels:
            do_channel = do_clock.channels[0]
        properties = {
            "Repeat ID": self.repeat_id,
            "ExposureTime": self.global_exposure_ms,
            "GlobalExposure": self.trigger_global_exposure,
            "FlushFlowrate": self.flush_settings.flush_flowrate,
            "FlushVolume": self.flush_settings.flush_volume_ml,
            "WaitAfterFlush": self.flush_settings.wait_after_flush_s,
            # Default "not attempted" -- both save_settings() calls in
            # run_experiment2() happen before flush() ever runs, so this is
            # always the correct value here; save_flush_result() overwrites
            # it with the real True/False once flush() actually completes.
            "FlushCompleted": "",
            "GitCommitHash": _git_commit_hash(),
            "TECTarget": "" if self.tec_target_c is None else self.tec_target_c,
        }
        properties.update(self._wfg_properties("Ch1", ch1))
        properties.update(self._wfg_properties("Ch2", ch2))
        properties.update(
            {
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
                "AD2Enabled": self.ad2_enabled,
                "CameraEnabled": self.camera_enabled,
                "PumpEnabled": self.pump_enabled,
                "ValveEnabled": self.valve_enabled,
                "PumpFaultManuallyCleared": self.pump_fault_manually_cleared,
            }
        )
        return properties

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
        return {
            "TriggerSource": settings.get("trigger_source", ""),
            "MasterPulseMode": settings.get("masterpulse_mode", ""),
            "MasterPulseSource": settings.get("masterpulse_source", ""),
            "MasterPulseInterval": settings.get("masterpulse_interval_s", ""),
            "MasterPulseBurstTimes": settings.get("masterpulse_burst_times", ""),
            "TriggerPolarity": settings.get("trigger_polarity", ""),
            "TriggerDelay": settings.get("trigger_delay_s", ""),
        }

    def _fm_sweep_properties(self) -> dict[str, Any]:
        if self.fm_sweep is None:
            return {
                "FMSweepEnabled": False,
                "FMSweepCenterHz": "",
                "FMSweepWidthKHz": "",
                "FMSweepTimeMs": "",
                "FMSweepType": "",
            }
        return {
            "FMSweepEnabled": True,
            "FMSweepCenterHz": self.fm_sweep.center_hz,
            "FMSweepWidthKHz": self.fm_sweep.width_hz / 1000.0,
            "FMSweepTimeMs": self.fm_sweep.sweep_time_ms,
            "FMSweepType": str(self.fm_sweep.sweep_type),
        }

    def _wfg_properties(self, suffix: str, channel: Any | None) -> dict[str, Any]:
        if channel is None:
            properties = {
                f"WFGFreq{suffix}": "",
                f"WFGAmp{suffix}": "",
                f"WFGRun{suffix}": "",
                f"WFGWait{suffix}": "",
                f"Repeat{suffix}": "",
                f"WFGOutOfRange{suffix}": "",
                f"WFGFunction{suffix}": "",
                f"WFGOffset{suffix}": "",
                f"WFGSymmetry{suffix}": "",
                f"WFGPhase{suffix}": "",
                f"WFGTriggerSource{suffix}": "",
            }
            properties.update(self._wfg_fm_mod_properties(suffix, None))
            return properties
        properties = {
            f"WFGFreq{suffix}": channel.carrier.frequency_hz,
            f"WFGAmp{suffix}": channel.carrier.amplitude_v,
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
        properties.update(self._wfg_fm_mod_properties(suffix, channel.fm_mod))
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

    def _camera_properties(self, settings: dict[str, Any]) -> dict[str, Any]:
        sub_region = settings.get("sub_region", {}) if isinstance(settings, dict) else {}
        return {
            "ReadoutTime": self._setting_value(settings, "readout_time"),
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
