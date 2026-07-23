from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np

from .ad2 import DoConfig, WfgConfig, coerce_do_config, coerce_wfg_config


@dataclass(slots=True)
class FlushSettings:
    flush_flowrate: float
    flush_volume_ml: float
    wait_after_flush_s: float
    syringe_volume_ml: float = 60.0

    @property
    def fill_level_delta(self) -> float:
        if self.syringe_volume_ml <= 0:
            return 0.0
        return self.flush_volume_ml / self.syringe_volume_ml

    @property
    def timeout_s(self) -> float:
        if self.flush_flowrate <= 0:
            return 0.0
        return (self.flush_volume_ml / self.flush_flowrate) * 1000.0 + 5.0


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
        }
        properties.update(self._wfg_properties("Ch1", ch1))
        properties.update(self._wfg_properties("Ch2", ch2))
        properties.update(
            {
                "DORun": do_channel.trigger.sec_run if do_channel is not None else "",
                "DOWait": do_channel.trigger.sec_wait if do_channel is not None else "",
                "DOFreq": do_channel.clock_frequency_hz if do_channel is not None and do_channel.clock_frequency_hz is not None else "",
            }
        )
        return properties

    def _wfg_properties(self, suffix: str, channel: Any | None) -> dict[str, Any]:
        if channel is None:
            return {
                f"WFGFreq{suffix}": "",
                f"WFGAmp{suffix}": "",
                f"WFGRun{suffix}": "",
                f"WFGWait{suffix}": "",
                f"Repeat{suffix}": "",
            }
        return {
            f"WFGFreq{suffix}": channel.carrier.frequency_hz,
            f"WFGAmp{suffix}": channel.carrier.amplitude_v,
            f"WFGRun{suffix}": channel.trigger.sec_run,
            f"WFGWait{suffix}": channel.trigger.sec_wait,
            f"Repeat{suffix}": channel.trigger.repeat_count,
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
            from nptdms import ChannelObject, GroupObject, RootObject, TdmsWriter
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
