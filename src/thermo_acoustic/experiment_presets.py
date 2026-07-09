from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


LABVIEW_SCREENSHOT_PRESET_NAME = "labview-screenshot"


@dataclass(frozen=True, slots=True)
class LabviewCameraPreset:
    roi_horizontal_offset: int = 0
    roi_vertical_offset: int = 792
    roi_horizontal_size: int = 2304
    roi_vertical_size: int = 740
    exposure_ms: float = 40.0
    camera_fps: float = 20.0
    experiment_frames: int = 1000
    dcam_trigger_source_camera_only: str = "internal"
    capture_mode: str = "Snap"
    sequence_mode: str = "Continuous"
    sequence_source: str = "External"
    interval_s: float = 1.0
    burst: int = 0
    external_polarity: str = "Negative"
    external_delay_s: float = 0.0

    def roi_dict(self) -> dict[str, int]:
        return {
            "horizontal_offset": self.roi_horizontal_offset,
            "vertical_offset": self.roi_vertical_offset,
            "horizontal_size": self.roi_horizontal_size,
            "vertical_size": self.roi_vertical_size,
        }


@dataclass(frozen=True, slots=True)
class LabviewExperimentPreset:
    repeats: int = 1
    frames: int = 1000
    exposure_ms: float = 40.0
    camera_start_s: float = 0.0
    ch1_frequency_hz: float = 1.975e6
    ch1_amplitude_v: float = 2.0
    ch1_start_s: float = 0.0
    ch1_run_s: float = 60.0
    ch2_start_s: float = 0.0
    ch2_run_s: float = 60.0
    dynamic_frequency: bool = False
    dynamic_camera_start_time: bool = False
    global_exposure: bool = False
    average_fps_observed: float = 20.099


@dataclass(frozen=True, slots=True)
class LabviewWfgChannelPreset:
    index: int
    frequency_hz: float
    amplitude_v: float
    offset_v: float = 0.0
    symmetry_percent: float = 50.0
    phase_deg: float = 0.0
    function: str = "Sine"


@dataclass(frozen=True, slots=True)
class LabviewAd2Preset:
    ch1: LabviewWfgChannelPreset = field(
        default_factory=lambda: LabviewWfgChannelPreset(index=0, frequency_hz=1.975e6, amplitude_v=2.0)
    )
    ch2: LabviewWfgChannelPreset = field(
        default_factory=lambda: LabviewWfgChannelPreset(index=1, frequency_hz=1000.0, amplitude_v=1.0)
    )
    trigger_source: str = "trigsrcNone"
    wfg_sec_run_s: float = 0.0
    wfg_sec_wait_s: float = 0.0
    wfg_repeat_count: int = 0
    experiment_ch1_run_s: float = 60.0
    experiment_ch2_run_s: float = 60.0


@dataclass(frozen=True, slots=True)
class LabviewFlushPreset:
    syringe: str = "BD 5 ml"
    manual_flow_rate: float = -5000.0
    experiment_flush_flowrate_ul: float = 1000.0
    experiment_flush_volume_ml: float = 0.01
    experiment_wait_after_flush_s: float = 2.0
    pump_tab_wait_after_flush_s: float = 5.0
    number_of_flushes: int = 2
    wait_after_flush_conflict_note: str = (
        "LabVIEW screenshots show Experiment WaitAfterFlush = 2 s and Pump&Valve WaitAfterFlush = 5 s."
    )


@dataclass(frozen=True, slots=True)
class LabviewInitializationPreset:
    analog_discovery_on: bool = True
    hamamatsu_on: bool = True
    cetoni_pump_on: bool = True
    mx_valve_on: bool = True
    z_stage_on: bool = False
    simulate_camera: bool = False
    simulate_pump: bool = False
    simulate_valve: bool = False
    prior_resource_candidate: str = "COM7"
    valve_resource_candidate: str = "COM5"
    qmix_config_path_candidate: Path = Path(r"C:\Users\Lab user\Desktop\Franzi\Cetoni_1pump_config_FM")
    candidate_note: str = (
        "Screenshot COM5 and Qmix path are candidates only; keep validated current defaults unless selected explicitly."
    )


@dataclass(frozen=True, slots=True)
class LabviewWorkingPreset:
    name: str = LABVIEW_SCREENSHOT_PRESET_NAME
    camera: LabviewCameraPreset = field(default_factory=LabviewCameraPreset)
    experiment: LabviewExperimentPreset = field(default_factory=LabviewExperimentPreset)
    ad2: LabviewAd2Preset = field(default_factory=LabviewAd2Preset)
    flush: LabviewFlushPreset = field(default_factory=LabviewFlushPreset)
    initialization: LabviewInitializationPreset = field(default_factory=LabviewInitializationPreset)
    source: str = "Manually confirmed values from original working LabVIEW front-panel screenshots."


def labview_screenshot_working_preset() -> LabviewWorkingPreset:
    return LabviewWorkingPreset()
