"""Passive summary of controller readbacks and experiment progress."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from ..domain.models import DeviceId
from .temperature_plot import TemperaturePlot


def _value(value: object, unit: str = "") -> str:
    return "unknown" if value is None else f"{value:g}{unit}" if isinstance(value, (int, float)) else str(value)


def camera_summary(data: object) -> str:
    """Camera readback as mode, exposure, ROI and frames; a value the camera did not report is 'unknown'."""
    pieces = [f"mode {_value(getattr(data, 'mode', None))}",
              f"exposure {_value(getattr(data, 'exposure_ms', None), ' ms')}"]
    roi = getattr(data, "roi", None)
    pieces.append("ROI unknown" if roi is None else
                  f"ROI {roi.horizontal_size}×{roi.vertical_size} at ({roi.horizontal_offset}, {roi.vertical_offset})")
    if getattr(data, "capture_active", None):
        pieces.append("capturing")
    if getattr(data, "sequence_frame_count", None) is not None:
        pieces.append(f"frames {_value(getattr(data, 'captured_frame_count', None))}/{data.sequence_frame_count}")
    return " · ".join(pieces)


def z_stage_summary(data: object) -> str:
    """Measured position and last commanded target are different facts and are labelled as such."""
    pieces = [f"measured position {_value(getattr(data, 'position_um', None), ' µm')} (last read)"]
    commanded = getattr(data, "commanded_position_um", None)
    pieces.append("no move commanded yet" if commanded is None else
                  f"last commanded target {_value(commanded, ' µm')} (arrival is not confirmed by this)")
    pieces.append("closed loop on" if getattr(data, "closed_loop", False) else "closed loop off")
    maximum = getattr(data, "max_travel_um", None)
    if maximum is not None:
        pieces.append(f"travel 0–{_value(maximum, ' µm')}")
    return " · ".join(pieces)


# Same parameter names as the compiled plan; anything not listed is shown as key=value.
_PARAMETER_LABELS = (("frequency_hz", "frequency", " Hz"), ("amplitude_v", "amplitude", " V"),
                     ("exposure_ms", "exposure", " ms"), ("sweep_width_hz", "sweep width", " Hz"),
                     ("temperature_c", "temperature", " °C"))


def describe_condition(parameters: dict | None) -> str:
    """Current experiment's own parameters as stored in the plan; nothing is derived."""
    if not parameters:
        return "—"
    pieces = []
    known = set()
    for key, label, unit in _PARAMETER_LABELS:
        if key in parameters:
            known.add(key)
            if parameters[key] != "NaN":  # the plan's marker for a disabled sweep/temperature axis
                pieces.append(f"{label} {_value(parameters[key], unit)}")
    pieces.extend(f"{key}={_value(value)}" for key, value in parameters.items() if key not in known)
    return " · ".join(pieces) if pieces else "—"


class StatusDashboard(QWidget):
    review_requested = Signal(str)
    image_window_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        run = QGroupBox("Current run")
        run_grid = QGridLayout(run)
        self.experiment = QLabel("Experiment batch: idle")
        self.experiment.setWordWrap(True)
        self.condition = QLabel("—")
        self.condition.setWordWrap(True)
        self.series = QLabel("—")
        self.series.setWordWrap(True)
        self.output = QLabel("—")
        self.output.setWordWrap(True)
        self.output.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        run_grid.addWidget(self.experiment, 0, 0, 1, 2)
        for row, (caption, label) in enumerate((("Condition", self.condition), ("Series", self.series),
                                                ("Output folder", self.output)), 1):
            run_grid.addWidget(QLabel(caption), row, 0)
            run_grid.addWidget(label, row, 1)
        run_grid.setColumnStretch(1, 1)
        buttons = QHBoxLayout()
        self.open_output_button = QPushButton("Open output folder")
        self.review_button = QPushButton("Review saved frames…")
        self.image_window_button = QPushButton("Camera image window")
        self.open_output_button.setEnabled(False)
        self.open_output_button.clicked.connect(self.open_output_folder)
        self.image_window_button.clicked.connect(self.image_window_requested)
        self.review_button.clicked.connect(lambda: self.review_requested.emit(self._folder or ""))
        for button in (self.open_output_button, self.review_button, self.image_window_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        run_grid.addLayout(buttons, 4, 0, 1, 2)
        root.addWidget(run)
        self._folder: str | None = None

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        grid = QGridLayout(body)
        self.rows = {}
        for index, device in enumerate(DeviceId):
            grid.addWidget(QLabel(device.value), index, 0)
            label = QLabel("disconnected")
            label.setWordWrap(True)
            grid.addWidget(label, index, 1)
            self.rows[device] = label
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(len(DeviceId), 1)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)
        root.addWidget(QLabel("TEC temperatures · latest rolling samples"))
        self.temperature_plot = TemperaturePlot()
        root.addWidget(self.temperature_plot)

    @property
    def output_folder(self) -> str | None:
        return self._folder

    def open_output_folder(self) -> None:
        if self._folder and Path(self._folder).is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._folder))

    def update_experiment(self, status: dict) -> None:
        count = status.get("planned_experiments", 0)
        completed = status.get("batch_completed_experiments", 0)
        self.experiment.setText(
            f"Batch: {status['state']} · completed {completed}/{count} · "
            f"remaining {max(0, count - completed)} · {status.get('phase', 'unknown')}")
        number = status.get("current_experiment_number")
        repeat = status.get("current_repeat")
        if status.get("current_parameters"):
            prefix = f"Experiment {number}/{count}" if number else "Experiment"
            suffix = f" · repeat {repeat}" if repeat else ""
            self.condition.setText(f"{prefix}{suffix} · {describe_condition(status['current_parameters'])}")
        else:
            self.condition.setText("— (no experiment running)")
        current = status.get("current_series")
        if current:
            self._folder = current
        series = next((item for item in status.get("series", []) if item["folder"] == self._folder), None)
        self.series.setText("—" if series is None
                            else f"{series['description']} · {series['state']} · "
                                 f"{series['experiment_count']} experiments planned")
        self.output.setText(self._folder or "— (nothing has run yet in this session)")
        self.open_output_button.setEnabled(self._folder is not None)

    def add_temperature_sample(self, sample: dict) -> None:
        self.temperature_plot.add_sample(sample)

    def update_statuses(self, statuses: dict) -> None:
        for device, status in statuses.items():
            data = status.readback
            pieces = [status.connection.value]
            if status.fault:
                pieces.append(f"ERROR: {status.fault}")
            if device is DeviceId.PUMP and data is not None:
                for unit in getattr(data, "units", ()):
                    pieces.append(
                        f"Unit {unit.unit_index + 1}: {_value(unit.fill_level_ml, ' mL')} · "
                        f"flow {_value(unit.current_flow_ul_min, ' µL/min')} · "
                        f"{'pumping' if unit.is_pumping else 'idle' if unit.is_pumping is False else 'unknown'}")
            elif device is DeviceId.VALVE and data is not None:
                pieces.append(f"position {_value(getattr(data, 'confirmed_position', None))}")
            elif device is DeviceId.Z_STAGE and data is not None:
                pieces.append(z_stage_summary(data))
            elif device is DeviceId.CAMERA and data is not None:
                pieces.append(camera_summary(data))
            elif device is DeviceId.AD2 and data is not None:
                pieces.append("waveform running" if data.waveform_running else "waveform idle")
                pieces.append("digital output running" if data.digital_output_running else "digital output idle")
                for channel in data.waveform_channels:
                    detail = f"CH{channel.channel_index + 1}: {channel.function} center {_value(channel.frequency_hz, ' Hz')}"
                    if channel.fm_enabled:
                        width = 2 * channel.frequency_hz * channel.fm_modulation_index_percent / 100
                        detail += f" · sweep width {width:g} Hz"
                    detail += (f" · {_value(channel.amplitude_v, ' V')} · idle setting {channel.idle_state}"
                               " · live channel state unknown")
                    pieces.append(detail)
            elif device is DeviceId.TEC and data is not None:
                for channel in getattr(data, "channels", ()):
                    pieces.append(f"CH{channel.channel}: {_value(channel.current_temperature_c, ' °C')} "
                                  f"→ {_value(channel.target_temperature_c, ' °C')}")
            self.rows[device].setText(" · ".join(pieces))
