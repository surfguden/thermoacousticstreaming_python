"""Passive summary of controller readbacks and experiment progress."""

from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from ..domain.models import DeviceId
from .temperature_plot import TemperaturePlot


def _value(value: object, unit: str = "") -> str:
    return "unknown" if value is None else f"{value:g}{unit}" if isinstance(value, (int, float)) else str(value)


class StatusDashboard(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        self.experiment = QLabel("Experiment batch: idle")
        self.experiment.setWordWrap(True)
        root.addWidget(self.experiment)
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
        scroll.setWidget(body)
        root.addWidget(scroll, 1)
        root.addWidget(QLabel("TEC temperatures · latest rolling samples"))
        self.temperature_plot = TemperaturePlot()
        root.addWidget(self.temperature_plot)

    def update_experiment(self, status: dict) -> None:
        count = status.get("planned_experiments", 0)
        completed = status.get("batch_completed_experiments", 0)
        self.experiment.setText(
            f"Batch: {status['state']} · completed {completed}/{count} · "
            f"remaining {max(0, count - completed)} · {status.get('phase', 'unknown')}")

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
                pieces.append(f"position {_value(getattr(data, 'position_um', None), ' µm')}")
            elif device is DeviceId.CAMERA and data is not None:
                pieces.append(f"{data.mode} · exposure {_value(data.exposure_ms, ' ms')}")
                if data.sequence_frame_count is not None:
                    pieces.append(f"frames {data.captured_frame_count}/{data.sequence_frame_count}")
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
