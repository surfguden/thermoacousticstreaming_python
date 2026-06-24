from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


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
    global_exposure_ms: float = 0.0
    sequence_settings: dict[str, Any] | None = None
    wfg_config: dict[str, Any] | None = None
    do_clock_settings: dict[str, Any] | None = None

    def create_folder_and_tdms(self) -> Path:
        self.experiment_folder.mkdir(parents=True, exist_ok=True)
        return self.experiment_folder

    def save_settings(self) -> None:
        self.experiment_folder.mkdir(parents=True, exist_ok=True)

    def save_camera_settings(self, settings: dict[str, Any]) -> None:
        _ = settings
        self.experiment_folder.mkdir(parents=True, exist_ok=True)

    def save_image_data(self, image_data: Any) -> None:
        _ = image_data
        self.experiment_folder.mkdir(parents=True, exist_ok=True)

    def cleanup(self) -> None:
        pass


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
