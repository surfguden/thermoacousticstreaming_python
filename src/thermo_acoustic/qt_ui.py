from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QThread, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QPlainTextEdit,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .ad2 import CarrierSettings, TriggerSettings, TriggerSource, WaveformFunction, WfgChannelConfig, WfgConfig
from .application import Application
from .camera import SubRegion
from .hardware_factory import HardwareRuntimeConfig, apply_hardware_bundle, build_hardware_bundle
from .hardware_config import ZStageBackend, default_hardware_config
from .instruments import SimulatedAD2Sdk
from .workflows import Experiment2, ExperimentSeries2, FlushSettings


SETTINGS_PATH = Path(__file__).resolve().parents[2] / ".thermo_acoustic_ui.json"


def _spin(value: float = 0.0, *, decimals: int = 3, minimum: float = -1e12, maximum: float = 1e12) -> QDoubleSpinBox:
    widget = QDoubleSpinBox()
    widget.setDecimals(decimals)
    widget.setRange(minimum, maximum)
    widget.setValue(value)
    widget.setKeyboardTracking(False)
    widget.setMaximumWidth(125)
    return widget


def _int_spin(value: int = 0, *, minimum: int = -1_000_000, maximum: int = 1_000_000) -> QSpinBox:
    widget = QSpinBox()
    widget.setRange(minimum, maximum)
    widget.setValue(value)
    widget.setKeyboardTracking(False)
    widget.setMaximumWidth(125)
    return widget


def _combo(values: list[str], value: str) -> QComboBox:
    widget = QComboBox()
    widget.addItems(values)
    index = widget.findText(value)
    if index >= 0:
        widget.setCurrentIndex(index)
    return widget


class WaveformGraph(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(170)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._points = [math.sin(index / 100.0 * math.tau * 3.0) * 5.0 for index in range(101)]
        self._sample_frequency_hz = 1.0
        self._series: dict[str, list[float]] = {"": self._points}

    def set_points(self, points: list[float]) -> None:
        self._points = list(points)
        self._series = {"": self._points}
        self.update()

    def set_samples(self, samples: list[float], sample_frequency_hz: float) -> None:
        self._points = list(samples)
        self._sample_frequency_hz = max(float(sample_frequency_hz), 1.0)
        self._series = {"": self._points}
        self.update()

    def set_series(self, series: dict[str, list[float]], sample_frequency_hz: float) -> None:
        self._series = {label: list(samples) for label, samples in series.items() if samples}
        self._points = next(iter(self._series.values()), [])
        self._sample_frequency_hz = max(float(sample_frequency_hz), 1.0)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API name
        _ = event
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(3, 14, 8))
        grid_pen = QPen(QColor(0, 90, 20), 1)
        painter.setPen(grid_pen)
        for i in range(0, 11):
            x = int(i * self.width() / 10)
            y = int(i * self.height() / 10)
            painter.drawLine(x, 0, x, self.height())
            painter.drawLine(0, y, self.width(), y)

        all_values = [value for samples in self._series.values() for value in samples]
        if len(all_values) < 2:
            return
        vmin = min(all_values)
        vmax = max(all_values)
        span = vmax - vmin or 1.0
        pad_l = 58
        pad_r = 16
        pad_t = 14
        pad_b = 30
        plot_w = max(self.width() - pad_l - pad_r, 1)
        plot_h = max(self.height() - pad_t - pad_b, 1)
        painter.fillRect(self.rect(), QColor(3, 14, 8))
        painter.setPen(QPen(QColor(0, 90, 20), 1))
        for i in range(0, 11):
            x = int(pad_l + i * plot_w / 10)
            y = int(pad_t + i * plot_h / 10)
            painter.drawLine(x, pad_t, x, pad_t + plot_h)
            painter.drawLine(pad_l, y, pad_l + plot_w, y)
        painter.setPen(QColor(185, 205, 185))
        duration = (max(len(samples) for samples in self._series.values()) - 1) / self._sample_frequency_hz
        for i in range(0, 6):
            value = vmax - i * span / 5
            y = int(pad_t + i * plot_h / 5)
            painter.drawText(4, y + 4, f"{value:.3g} V")
            x = int(pad_l + i * plot_w / 5)
            painter.drawText(x - 15, self.height() - 8, f"{duration * i / 5:.3g}s")
        colors = [QColor(210, 240, 210), QColor(80, 170, 255), QColor(255, 210, 80)]
        for series_index, (label, samples) in enumerate(self._series.items()):
            if len(samples) < 2:
                continue
            painter.setPen(QPen(colors[series_index % len(colors)], 2))
            points = []
            for index, value in enumerate(samples):
                x = pad_l + index / (len(samples) - 1) * plot_w
                y = pad_t + (1.0 - ((value - vmin) / span)) * plot_h
                points.append(QPointF(x, y))
            for left, right in zip(points, points[1:]):
                painter.drawLine(left, right)
            painter.drawText(pad_l + 8, pad_t + 18 + series_index * 18, label)


class ActionWorker(QObject):
    finished = Signal(bool, str, str)
    progress = Signal(str, object)

    def __init__(self, action) -> None:
        super().__init__()
        self.action = action

    def run(self) -> None:
        try:
            result = self.action(self.progress.emit)
            status = str(result) if result else "Ready"
            self.finished.emit(True, status, "")
        except Exception as exc:  # pragma: no cover - Qt worker feedback path
            self.finished.emit(False, "Error", str(exc))


class MainWindow(QMainWindow):
    def __init__(self, app: Application | None = None) -> None:
        super().__init__()
        self.app = app or Application(ad2=SimulatedAD2Sdk())
        self.setWindowTitle("Thermo Acoustic Streaming")
        self.resize(1280, 820)
        self.setMinimumSize(980, 680)
        self._threads: list[QThread] = []
        self._workers: list[ActionWorker] = []
        self._busy_count = 0

        self._build_state()
        self._build_layout()
        self._load_settings()
        self._refresh_status()

    def _build_state(self) -> None:
        hardware_defaults = default_hardware_config()
        self.ad2_enabled = QCheckBox("Off/On")
        self.ad2_enabled.setChecked(True)
        self.z_enabled = QCheckBox("Off/On")
        self.camera_enabled = QCheckBox("Off/On")
        self.camera_enabled.setChecked(True)
        self.pump_enabled = QCheckBox("Off/On")
        self.pump_enabled.setChecked(True)
        self.valve_enabled = QCheckBox("Off/On")
        self.valve_enabled.setChecked(True)
        self.sim_camera = QCheckBox("Off/On")
        self.sim_camera.setChecked(True)
        self.sim_pump = QCheckBox("Off/On")
        self.sim_pump.setChecked(True)
        self.sim_valve = QCheckBox("Off/On")
        self.sim_valve.setChecked(True)
        self.sim_ad2 = QCheckBox("Off/On")
        self.sim_ad2.setChecked(True)

        self.z_backend = _combo([item.value for item in ZStageBackend], hardware_defaults.z_stage.backend.value)
        self.prior_resource = QLineEdit(hardware_defaults.z_stage.prior_resource)
        self.thorlabs_apt_serial = QLineEdit(hardware_defaults.z_stage.thorlabs_apt_serial)
        self.thorlabs_apt_backend = QLineEdit(hardware_defaults.z_stage.thorlabs_apt_backend)
        self.thorlabs_apt_discovery_only = QCheckBox("Discovery only")
        self.thorlabs_apt_discovery_only.setChecked(hardware_defaults.z_stage.thorlabs_apt_discovery_only)
        self.valve_resource = QLineEdit("COM6")
        self.qmix_sdk_python_path = QLineEdit(str(hardware_defaults.qmix.sdk_python_path))
        self.qmix_qmixsdk_path = QLineEdit(str(hardware_defaults.qmix.qmixsdk_path))
        self.cetoni_config_path = QLineEdit(str(hardware_defaults.qmix.config_path))

        self.wfg_running = QCheckBox("ON")
        self.wfg_running.setChecked(True)
        self.wfg_sync = _combo(["Independent", "Synchronized"], "Independent")
        self.wfg_channels = [
            self._make_wfg_channel_state(0, 1.9e6, 2.0),
            self._make_wfg_channel_state(1, 1000.0, 1.0),
        ]

        self.mso_ch1_enabled = QCheckBox("CH1")
        self.mso_ch1_enabled.setChecked(True)
        self.mso_ch2_enabled = QCheckBox("CH2")
        self.mso_ch2_enabled.setChecked(True)
        self.mso_trigger_source = _combo([item.value for item in TriggerSource], TriggerSource.NONE.value)
        self.mso_sample_frequency = _spin(10_000.0, decimals=1, minimum=1.0, maximum=100_000_000.0)
        self.mso_sample_count = _int_spin(4096, minimum=1, maximum=1_000_000)
        self.mso_range = _spin(1.0, decimals=3, minimum=0.001, maximum=50.0)
        self.mso_offset = _spin(0.0, decimals=3, minimum=-50.0, maximum=50.0)
        self.mso_stats = QLabel("No capture")
        self.mso_samples: list[float] = []

        self.syringe = _combo(["BD 1ml", "BD 5ml", "BD 10ml", "Custom"], "BD 1ml")
        self.flow_rate = _spin(-5000.0, decimals=1)
        self.level_ml = _spin(0.0, decimals=3, minimum=0.0)
        self.flush_flowrate = _spin(0.0, decimals=3)
        self.flush_volume = _spin(0.0, decimals=3, minimum=0.0)
        self.wait_after_flush = _spin(0.0, decimals=3, minimum=0.0)
        self.flush_count = _int_spin(1, minimum=1)

        self.roi_h_offset = _int_spin(0, minimum=0)
        self.roi_v_offset = _int_spin(900, minimum=0)
        self.roi_h_size = _int_spin(2304, minimum=0)
        self.roi_v_size = _int_spin(500, minimum=0)
        self.exposure_ms = _spin(50.0, decimals=3, minimum=0.0)
        self.center_roi = QCheckBox("Off/On")
        self.center_roi.setChecked(True)
        self.image_continuous = QCheckBox("Off/On")
        self.image_continuous.setChecked(True)
        self.conversion_method = _combo(["Default", "Minimum/Maximum", "Shift"], "Default")
        self.conversion_min = _spin(0.0, decimals=3)
        self.conversion_max = _spin(0.0, decimals=3)
        self.conversion_shifts = _int_spin(0)
        self.sequence_path = QLineEdit("")
        self.sequence_mode = _combo(["Continuous", "Finite"], "Continuous")
        self.sequence_source = _combo(["External", "Internal"], "External")
        self.sequence_interval = _spin(1.0, decimals=3, minimum=0.0)
        self.sequence_burst = _int_spin(0, minimum=0)
        self.capture_mode = _combo(["Snap", "Sequence"], "Snap")
        self.sequence_frames = _int_spin(0, minimum=0)
        self.dcam_source = _combo(["Internal", "External"], "Internal")
        self.external_polarity = _combo(["Negative", "Positive"], "Negative")
        self.external_delay = _spin(0.0, decimals=3, minimum=0.0)
        self.sequence_exposure_ms = _spin(0.0, decimals=3, minimum=0.0)

        self.series_path = QLineEdit(r"C:\test\firstrunpulsed")
        self.exp_camera_fps = _spin(0.0, decimals=3, minimum=0.0)
        self.exp_camera_start = _spin(0.0, decimals=3, minimum=0.0)
        self.exp_ch1_freq = _spin(0.0, decimals=3, minimum=0.0)
        self.exp_ch1_amp = _spin(0.0, decimals=3)
        self.exp_ch1_start = _spin(0.0, decimals=3, minimum=0.0)
        self.exp_ch1_run = _spin(0.0, decimals=3, minimum=0.0)
        self.exp_ch2_start = _spin(0.0, decimals=3, minimum=0.0)
        self.exp_ch2_run = _spin(0.0, decimals=3, minimum=0.0)
        self.exp_repeats = _int_spin(1, minimum=1)
        self.exp_frames = _int_spin(1, minimum=0)
        self.exp_exposure_ms = _spin(0.0, decimals=3, minimum=0.0)
        self.exp_flush_flowrate = _spin(0.0, decimals=3)
        self.exp_flush_volume = _spin(0.0, decimals=3, minimum=0.0)
        self.exp_wait_after_flush = _spin(0.0, decimals=3, minimum=0.0)
        self.exp_flush_enabled = QCheckBox("Enable")
        self.camera_start_array = [_spin(0.0, decimals=3, minimum=0.0) for _ in range(10)]
        self.global_exposure = QCheckBox("Off/On")
        self.dynamic_camera_start = QCheckBox("Off/On")
        self.average_fps = QLabel("0")

    def _make_wfg_channel_state(self, index: int, frequency: float, amplitude: float) -> dict[str, object]:
        return {
            "idx": _int_spin(index, minimum=0, maximum=1),
            "frequency": _spin(frequency, decimals=3, minimum=0.0),
            "amplitude": _spin(amplitude, decimals=3),
            "offset": _spin(0.0, decimals=3),
            "symmetry": _spin(50.0, decimals=3, minimum=0.0, maximum=100.0),
            "phase": _spin(0.0, decimals=3),
            "function": _combo([item.value for item in WaveformFunction], WaveformFunction.SINE.value),
            "enable": QCheckBox("Enable"),
            "sec_run": _spin(0.0, decimals=3, minimum=0.0),
            "sec_wait": _spin(0.0, decimals=3, minimum=0.0),
            "repeat": _int_spin(0, minimum=0),
            "repeat_trigger": QCheckBox("Repeat Trigger"),
            "trigger_source": _combo(["trigsrcNone", "trigsrcPC", "trigsrcAnalogIn", "trigsrcDigitalIn"], "trigsrcNone"),
            "fm_frequency": _spin(1000.0, decimals=3, minimum=0.0),
            "fm_amplitude": _spin(1.0, decimals=3),
            "fm_offset": _spin(0.0, decimals=3),
            "fm_symmetry": _spin(50.0, decimals=3, minimum=0.0, maximum=100.0),
            "fm_phase": _spin(0.0, decimals=3),
            "fm_function": _combo([item.value for item in WaveformFunction], WaveformFunction.SINE.value),
            "fm_enable": QCheckBox("Enable"),
        }

    def _build_layout(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        top = QGridLayout()
        exit_button = QPushButton("Exit")
        exit_button.clicked.connect(self._exit_app)
        abort_button = QPushButton("Abort")
        abort_button.clicked.connect(self._abort)
        self.status = QLineEdit("System Not Initialized")
        self.status.setReadOnly(True)
        self.status.setMinimumWidth(280)
        save_settings = QPushButton("Save Settings")
        save_settings.clicked.connect(self._save_settings)
        load_settings = QPushButton("Load Settings")
        load_settings.clicked.connect(self._load_settings)
        top.addWidget(QLabel("Exit"), 0, 0)
        top.addWidget(exit_button, 1, 0)
        top.addWidget(QLabel("Abort"), 0, 1)
        top.addWidget(abort_button, 1, 1)
        top.addWidget(save_settings, 1, 2)
        top.addWidget(load_settings, 1, 3)
        top.addWidget(QLabel("Status"), 0, 4)
        top.addWidget(self.status, 1, 4)
        top.setColumnStretch(3, 1)
        layout.addLayout(top)

        body = QHBoxLayout()
        self.tabs = QTabWidget()
        self.tabs.addTab(self._init_tab(), "Initialization")
        self.tabs.addTab(self._wfg_tab(), "WFG")
        self.tabs.addTab(self._mso_tab(), "MSO")
        self.tabs.addTab(self._pump_tab(), "Pump&Valve")
        self.tabs.addTab(self._camera_tab(), "Camera")
        self.tabs.addTab(self._experiment_tab(), "Experiment")
        body.addWidget(self.tabs, 1)
        body.addWidget(self._error_panel())
        layout.addLayout(body, 1)

    def _init_tab(self) -> QWidget:
        tab = QWidget()
        grid = QGridLayout(tab)
        grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        grid.addWidget(self._instrument_group(), 0, 0)
        grid.addWidget(self._simulation_group(), 0, 1)
        initialize = QPushButton("Initialize!")
        initialize.setMinimumWidth(230)
        initialize.clicked.connect(self._start_initialize)
        grid.addWidget(QLabel("Initialize System"), 1, 0)
        grid.addWidget(initialize, 2, 0)
        grid.setColumnStretch(2, 1)
        return tab

    def _instrument_group(self) -> QGroupBox:
        group = QGroupBox("Hardware")
        form = QFormLayout(group)
        form.addRow("Analog Discovery 3", self.ad2_enabled)
        form.addRow("Z stage", self.z_enabled)
        form.addRow("Z stage backend", self.z_backend)
        form.addRow("Prior VISA resource name", self.prior_resource)
        form.addRow("Thorlabs/APT serial", self.thorlabs_apt_serial)
        form.addRow("Thorlabs/APT backend", self.thorlabs_apt_backend)
        form.addRow("Thorlabs/APT discovery only", self.thorlabs_apt_discovery_only)
        form.addRow("Hamamatsu", self.camera_enabled)
        form.addRow("Cetoni Pump", self.pump_enabled)
        form.addRow("Qmix SDK Python Path", self.qmix_sdk_python_path)
        form.addRow("Qmix QMIXSDK Path", self.qmix_qmixsdk_path)
        form.addRow("Cetoni Device Configuration Path", self.cetoni_config_path)
        form.addRow("MX Valve 2", self.valve_enabled)
        form.addRow("Valve VISA resource name", self.valve_resource)
        return group

    def _simulation_group(self) -> QGroupBox:
        group = QGroupBox("Simulation")
        form = QFormLayout(group)
        form.addRow("Simulate Camera", self.sim_camera)
        form.addRow("Simulate Pump", self.sim_pump)
        form.addRow("Simulate Valve", self.sim_valve)
        form.addRow("Simulate AD2", self.sim_ad2)
        return group

    def _wfg_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        header = QHBoxLayout()
        header.addWidget(QLabel("WFGConfig"))
        header.addWidget(self.wfg_running)
        header.addStretch()
        header.addWidget(QLabel("SynchronizeState"))
        header.addWidget(self.wfg_sync)
        layout.addLayout(header)
        channels = QHBoxLayout()
        channels.addWidget(self._wfg_channel_group("Ch1", self.wfg_channels[0]))
        channels.addWidget(self._wfg_channel_group("Ch2", self.wfg_channels[1]))
        channels.addStretch()
        layout.addLayout(channels)
        apply = QPushButton("Apply WFG")
        apply.clicked.connect(self._start_apply_wfg)
        layout.addWidget(apply, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addStretch()
        return tab

    def _wfg_channel_group(self, title: str, state: dict[str, object]) -> QGroupBox:
        group = QGroupBox(title)
        layout = QVBoxLayout(group)
        form = QFormLayout()
        for label, key in (
            ("idxChannel", "idx"),
            ("Frequency (Hz) Carrier", "frequency"),
            ("Amplitude (V)", "amplitude"),
            ("Offset(V)", "offset"),
            ("Symmetry(%)", "symmetry"),
            ("Phase(Deg)", "phase"),
            ("Function", "function"),
        ):
            form.addRow(label, state[key])
        form.addRow(state["enable"])
        layout.addLayout(form)
        trigger = QFormLayout()
        for label, key in (
            ("secRun(0=Cont)", "sec_run"),
            ("secWait", "sec_wait"),
            ("cRepeat(0=inf)", "repeat"),
        ):
            trigger.addRow(label, state[key])
        trigger.addRow(state["repeat_trigger"])
        trigger.addRow("TrigrSrc", state["trigger_source"])
        layout.addWidget(QLabel("Trigger"))
        layout.addLayout(trigger)
        fm = QFormLayout()
        for label, key in (
            ("Frequency (Hz)", "fm_frequency"),
            ("Amplitude (%)", "fm_amplitude"),
            ("Offset(V)", "fm_offset"),
            ("Symmetry(%)", "fm_symmetry"),
            ("Phase(Deg)", "fm_phase"),
            ("Function 2", "fm_function"),
        ):
            fm.addRow(label, state[key])
        fm.addRow(state["fm_enable"])
        layout.addWidget(QLabel("FM Mod"))
        layout.addLayout(fm)
        return group

    def _mso_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        content = QHBoxLayout()
        controls = QGroupBox("MSO Configuration")
        form = QFormLayout(controls)
        channel_row = QHBoxLayout()
        channel_row.addWidget(self.mso_ch1_enabled)
        channel_row.addWidget(self.mso_ch2_enabled)
        channel_row.addStretch()
        form.addRow("Analog In Channels", channel_row)
        form.addRow("Trigger Source", self.mso_trigger_source)
        form.addRow("Sample Frequency (Hz)", self.mso_sample_frequency)
        form.addRow("Sample Count", self.mso_sample_count)
        form.addRow("Range (V)", self.mso_range)
        form.addRow("Offset (V)", self.mso_offset)
        init = QPushButton("Initialize MSO")
        init.clicked.connect(self._start_mso_init)
        capture = QPushButton("Capture")
        capture.clicked.connect(self._start_mso_capture)
        form.addRow(init)
        form.addRow(capture)
        form.addRow("Stats", self.mso_stats)

        self.mso_graph = WaveformGraph()
        graph_box = QGroupBox("Waveform")
        graph_layout = QVBoxLayout(graph_box)
        graph_layout.addWidget(self.mso_graph)
        self.mso_text = QPlainTextEdit()
        self.mso_text.setReadOnly(True)
        self.mso_text.setMaximumHeight(90)
        graph_layout.addWidget(self.mso_text)

        content.addWidget(controls)
        content.addWidget(graph_box, 1)
        layout.addLayout(content)
        layout.addStretch()
        return tab

    def _pump_tab(self) -> QWidget:
        tab = QWidget()
        grid = QGridLayout(tab)
        grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        pos1 = QPushButton("Pos1")
        pos1.clicked.connect(lambda: self._run_action(lambda progress: self.app.valve.set_position(1), "Valve Pos1"))
        pos2 = QPushButton("Pos2")
        pos2.clicked.connect(lambda: self._run_action(lambda progress: self.app.valve.set_position(2), "Valve Pos2"))
        refill = QPushButton("Refill")
        refill.clicked.connect(lambda: self._run_action(lambda progress: self.app.pump.refill(), "Refilling"))
        empty = QPushButton("Empty")
        empty.clicked.connect(lambda: self._run_action(lambda progress: self.app.pump.empty(), "Emptying"))
        configure = QPushButton("Configure")
        configure.clicked.connect(self._start_configure_syringe)
        generate = QPushButton("Generate")
        generate.clicked.connect(self._start_generate_flow)
        go = QPushButton("GO")
        go.clicked.connect(self._start_go_level)
        ref = QPushButton("Ref Move")
        ref.clicked.connect(lambda: self._run_action(lambda progress: self.app.pump.reference_move(), "Reference move"))
        flush = QPushButton("Flush")
        flush.clicked.connect(self._start_flush)
        stop = QPushButton("STOP")
        stop.setMinimumSize(200, 70)
        stop.clicked.connect(lambda: self._run_action(lambda progress: self.app.pump.stop(), "Pump stopped"))

        grid.addWidget(QLabel("Valve Pos1"), 0, 0)
        grid.addWidget(pos1, 1, 0)
        grid.addWidget(QLabel("ValvePos2"), 2, 0)
        grid.addWidget(pos2, 3, 0)
        grid.addWidget(QLabel("Refill"), 0, 2)
        grid.addWidget(refill, 1, 2)
        grid.addWidget(QLabel("Empty"), 0, 3)
        grid.addWidget(empty, 1, 3)
        grid.addWidget(QLabel("Syringe"), 2, 2)
        grid.addWidget(self.syringe, 3, 2)
        grid.addWidget(QLabel("ConfigureSyringe"), 2, 4)
        grid.addWidget(configure, 3, 4)
        grid.addWidget(QLabel("Flow Rate"), 5, 2)
        grid.addWidget(self.flow_rate, 6, 2)
        grid.addWidget(QLabel("Generate Flow"), 5, 4)
        grid.addWidget(generate, 6, 4)
        grid.addWidget(QLabel("Level(ml)"), 8, 3)
        grid.addWidget(self.level_ml, 9, 3)
        grid.addWidget(QLabel("Go to Level"), 8, 4)
        grid.addWidget(go, 9, 4)
        grid.addWidget(QLabel("Reference move"), 10, 4)
        grid.addWidget(ref, 11, 4)
        grid.addWidget(QLabel("Number of flushes"), 12, 3)
        grid.addWidget(self.flush_count, 13, 3)
        grid.addWidget(QLabel("Flush"), 12, 4)
        grid.addWidget(flush, 13, 4)
        grid.addWidget(QLabel("Stop Syringe"), 10, 0)
        grid.addWidget(stop, 11, 0, 3, 2)
        grid.addWidget(self._flush_group(), 9, 5, 5, 2)
        grid.setColumnStretch(7, 1)
        return tab

    def _flush_group(self) -> QGroupBox:
        group = QGroupBox("Flush Settings")
        form = QFormLayout(group)
        form.addRow("Flush Flowrate", self.flush_flowrate)
        form.addRow("flush volume (ml)", self.flush_volume)
        form.addRow("WaitAfterFlush", self.wait_after_flush)
        return group

    def _camera_tab(self) -> QWidget:
        tab = QWidget()
        grid = QGridLayout(tab)
        grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        grid.addWidget(self._image_group(), 0, 0, 1, 2)
        grid.addWidget(self._roi_group(), 1, 0, 1, 2)
        grid.addWidget(self._conversion_group(), 0, 2, 2, 1)
        grid.addWidget(self._sequence_group(), 2, 0, 1, 2)
        grid.setColumnStretch(3, 1)
        return tab

    def _image_group(self) -> QGroupBox:
        group = QGroupBox("Image")
        row = QHBoxLayout(group)
        image = QPushButton("Image")
        image.clicked.connect(lambda: self._run_action(lambda progress: self.app.camera.capture_snapshot(), "Capturing image"))
        row.addWidget(image)
        row.addWidget(QLabel("Image Continous"))
        row.addWidget(self.image_continuous)
        row.addWidget(QLabel("If the button is grayed out, press the configure camera button"))
        row.addStretch()
        return group

    def _roi_group(self) -> QGroupBox:
        group = QGroupBox("ROI")
        grid = QGridLayout(group)
        form = QFormLayout()
        form.addRow("Horizontal Offset", self.roi_h_offset)
        form.addRow("Vertical Offset", self.roi_v_offset)
        form.addRow("Horizontal Size", self.roi_h_size)
        form.addRow("Vertical Size", self.roi_v_size)
        configure = QPushButton("Configure")
        configure.clicked.connect(self._start_configure_camera)
        grid.addLayout(form, 0, 0, 3, 1)
        grid.addWidget(QLabel("ExposureTime(ms)"), 0, 1)
        grid.addWidget(self.exposure_ms, 1, 1)
        grid.addWidget(QLabel("Configure Camera"), 0, 2)
        grid.addWidget(configure, 1, 2)
        grid.addWidget(QLabel("Center ROI"), 2, 1)
        grid.addWidget(self.center_roi, 3, 1)
        grid.addWidget(QLabel("476 is Vertical is max for 100 fps"), 4, 1, 1, 2)
        return group

    def _conversion_group(self) -> QGroupBox:
        group = QGroupBox("Conversion Policy (Default)")
        layout = QVBoxLayout(group)
        form = QFormLayout()
        form.addRow("Conversion Method", self.conversion_method)
        form.addRow("Minimum Value", self.conversion_min)
        form.addRow("Maximum Value", self.conversion_max)
        form.addRow("# Shifts", self.conversion_shifts)
        adjust = QPushButton("Adjust")
        adjust.clicked.connect(lambda: self._set_status("Image intensity adjusted"))
        layout.addLayout(form)
        layout.addWidget(QLabel("Adjust Intensity in image"))
        layout.addWidget(adjust, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addStretch()
        return group

    def _sequence_group(self) -> QGroupBox:
        group = QGroupBox("Sequence")
        grid = QGridLayout(group)
        start = QPushButton("Start")
        start.clicked.connect(lambda: self._run_action(lambda progress: self.app.camera.start_capture(), "Camera capture started"))
        trig = QPushButton("Trigg")
        trig.setMinimumSize(120, 60)
        trig.clicked.connect(lambda: self._run_action(lambda progress: self.app.camera.sw_trigg(), "Camera triggered"))
        save = QPushButton("Save")
        save.clicked.connect(self._start_save_sequence)
        browse = QPushButton("...")
        browse.clicked.connect(lambda: self._browse_folder(self.sequence_path))
        settings = QFormLayout()
        settings.addRow("Mode", self.sequence_mode)
        settings.addRow("Source", self.sequence_source)
        settings.addRow("Interval", self.sequence_interval)
        settings.addRow("Burst", self.sequence_burst)
        settings.addRow("Capture mode", self.capture_mode)
        settings.addRow("Frames", self.sequence_frames)
        settings.addRow("Dcam Trigger Source", self.dcam_source)
        settings.addRow("Polarity", self.external_polarity)
        settings.addRow("Delay", self.external_delay)
        settings.addRow("ExposureTime(ms)", self.sequence_exposure_ms)
        grid.addWidget(QLabel("StartSequence"), 0, 0)
        grid.addWidget(start, 1, 0)
        grid.addWidget(QLabel("Trigg"), 2, 0)
        grid.addWidget(trig, 3, 0)
        grid.addWidget(QLabel("Sequence path"), 4, 0)
        grid.addWidget(self.sequence_path, 5, 0)
        grid.addWidget(browse, 5, 1)
        grid.addWidget(QLabel("SaveSequence"), 6, 0)
        grid.addWidget(save, 7, 0)
        grid.addWidget(QLabel("Sequence Settings"), 0, 2)
        grid.addLayout(settings, 1, 2, 7, 1)
        return group

    def _experiment_tab(self) -> QWidget:
        tab = QWidget()
        grid = QGridLayout(tab)
        grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        grid.addWidget(QLabel("Elapsed Time"), 0, 0)
        grid.addWidget(QLabel("00:00:00"), 1, 0)
        grid.addWidget(QLabel("Time Left"), 0, 1)
        grid.addWidget(QLabel("00:00:00"), 1, 1)
        grid.addWidget(QLabel("# elements in queue"), 0, 2)
        self.queue_count = QLabel("0")
        grid.addWidget(self.queue_count, 1, 2)
        start = QPushButton("Start exp")
        start.clicked.connect(self._start_experiment)
        browse = QPushButton("...")
        browse.clicked.connect(lambda: self._browse_folder(self.series_path))
        grid.addWidget(QLabel("Start Experiment series"), 3, 0)
        grid.addWidget(start, 4, 0)
        grid.addWidget(QLabel("SeriesPath 2"), 5, 0)
        grid.addWidget(self.series_path, 6, 0, 1, 5)
        grid.addWidget(browse, 6, 5)
        grid.addWidget(self._ad_settings_group(), 7, 0, 1, 2)
        grid.addWidget(self._experiment_numbers_group(), 7, 2)
        grid.addWidget(self._experiment_flush_group(), 8, 2)
        grid.addWidget(self._camera_start_group(), 7, 4, 2, 1)
        grid.addWidget(QLabel("GlobalExposure"), 7, 5)
        grid.addWidget(self.global_exposure, 7, 6)
        grid.addWidget(QLabel("Dynamic Camera Start Time"), 8, 5)
        grid.addWidget(self.dynamic_camera_start, 8, 6)
        grid.addWidget(QLabel("Average FPS"), 10, 5)
        grid.addWidget(self.average_fps, 11, 5)
        grid.addWidget(QLabel("Waveform Graph"), 10, 0)
        self.waveform_graph = WaveformGraph()
        grid.addWidget(self.waveform_graph, 11, 0, 1, 5)
        grid.setColumnStretch(6, 1)
        return tab

    def _ad_settings_group(self) -> QGroupBox:
        group = QGroupBox("Analog Discovery Settings")
        form = QFormLayout(group)
        form.addRow("Camera FPS", self.exp_camera_fps)
        form.addRow("Camera Start (s)", self.exp_camera_start)
        form.addRow("Ch1 Frequency (Hz)", self.exp_ch1_freq)
        form.addRow("Ch1.Carrier.Amplitude (V)", self.exp_ch1_amp)
        form.addRow("Ch1 Start (s)", self.exp_ch1_start)
        form.addRow("Ch1 Run (s) (0=Cont)", self.exp_ch1_run)
        form.addRow("Ch2 Start(s)", self.exp_ch2_start)
        form.addRow("Ch2 Run (s)(0=Cont)", self.exp_ch2_run)
        return group

    def _experiment_numbers_group(self) -> QGroupBox:
        group = QGroupBox("Experiment")
        form = QFormLayout(group)
        form.addRow("Repeats", self.exp_repeats)
        form.addRow("Frames", self.exp_frames)
        form.addRow("ExposureTime(ms) 2", self.exp_exposure_ms)
        return group

    def _experiment_flush_group(self) -> QGroupBox:
        group = QGroupBox("Flush Settings 2")
        form = QFormLayout(group)
        form.addRow("Flush after capture", self.exp_flush_enabled)
        form.addRow("Flush Flowrate(uL)", self.exp_flush_flowrate)
        form.addRow("flush volume (ml)", self.exp_flush_volume)
        form.addRow("WaitAfterFlush", self.exp_wait_after_flush)
        return group

    def _camera_start_group(self) -> QGroupBox:
        group = QGroupBox("Camera Start Array(s)")
        form = QFormLayout(group)
        for widget in self.camera_start_array:
            form.addRow(widget)
        return group

    def _error_panel(self) -> QGroupBox:
        group = QGroupBox("Error Out")
        group.setMaximumWidth(240)
        form = QFormLayout(group)
        self.error_status = QLabel("OK")
        self.error_code = QLineEdit("0")
        self.error_code.setReadOnly(True)
        self.error_source = QLineEdit("")
        self.error_source.setReadOnly(True)
        form.addRow("status", self.error_status)
        form.addRow("code", self.error_code)
        form.addRow("source", self.error_source)
        return group

    def _channel_config(self, state: dict[str, object]) -> WfgChannelConfig:
        return WfgChannelConfig(
            channel_index=state["idx"].value(),
            carrier=CarrierSettings(
                frequency_hz=state["frequency"].value(),
                amplitude_v=state["amplitude"].value(),
                offset_v=state["offset"].value(),
                symmetry_percent=state["symmetry"].value(),
                phase_deg=state["phase"].value(),
                function=WaveformFunction(state["function"].currentText()),
                enable=state["enable"].isChecked(),
            ),
            trigger=TriggerSettings(
                sec_run=state["sec_run"].value(),
                sec_wait=state["sec_wait"].value(),
                repeat_count=state["repeat"].value(),
                repeat_trigger=state["repeat_trigger"].isChecked(),
                source=state["trigger_source"].currentText(),
            ),
            fm_mod=CarrierSettings(
                frequency_hz=state["fm_frequency"].value(),
                amplitude_v=state["fm_amplitude"].value(),
                offset_v=state["fm_offset"].value(),
                symmetry_percent=state["fm_symmetry"].value(),
                phase_deg=state["fm_phase"].value(),
                function=WaveformFunction(state["fm_function"].currentText()),
                enable=state["fm_enable"].isChecked(),
            ),
        )

    def _wfg_config(self) -> WfgConfig:
        return WfgConfig(
            running=self.wfg_running.isChecked(),
            channels=[self._channel_config(item) for item in self.wfg_channels],
            synchronize_state=self.wfg_sync.currentText(),
        )

    def _flush_settings(self, *, experiment: bool = False) -> FlushSettings:
        if experiment:
            return FlushSettings(
                flush_flowrate=self.exp_flush_flowrate.value(),
                flush_volume_ml=self.exp_flush_volume.value(),
                wait_after_flush_s=self.exp_wait_after_flush.value(),
            )
        return FlushSettings(
            flush_flowrate=self.flush_flowrate.value(),
            flush_volume_ml=self.flush_volume.value(),
            wait_after_flush_s=self.wait_after_flush.value(),
        )

    def _start_initialize(self) -> None:
        config = HardwareRuntimeConfig(
            ad2_enabled=self.ad2_enabled.isChecked(),
            sim_ad2=self.sim_ad2.isChecked(),
            camera_enabled=self.camera_enabled.isChecked(),
            sim_camera=self.sim_camera.isChecked(),
            pump_enabled=self.pump_enabled.isChecked(),
            sim_pump=self.sim_pump.isChecked(),
            valve_enabled=self.valve_enabled.isChecked(),
            sim_valve=self.sim_valve.isChecked(),
            z_enabled=self.z_enabled.isChecked(),
            prior_resource=self.prior_resource.text(),
            valve_resource=self.valve_resource.text(),
            cetoni_config_path=self.cetoni_config_path.text(),
        )
        self._run_action(lambda progress: self._initialize_system(config, progress), "Initializing")

    def _initialize_system(self, config: HardwareRuntimeConfig, progress=None) -> str:
        if progress:
            progress("status", "Opening selected hardware")
        try:
            self.app.cleanup()
        except Exception as exc:
            self.app.check_loop_error(exc)
        apply_hardware_bundle(self.app, build_hardware_bundle(config))
        self.app.initialize()
        return "System Initialized"

    def _start_apply_wfg(self) -> None:
        config = self._wfg_config()
        self.waveform_graph.set_points(self._preview_points(config))
        self._run_action(lambda progress: self._apply_wfg(config, progress), "Configuring WFG")

    def _apply_wfg(self, config: WfgConfig, progress=None) -> str:
        if progress:
            progress("waveform", self._preview_points(config))
            progress("status", "Writing WFG settings")
        self.app.ad2.config_wfg(config)
        self.app.ad2.wfg_start_stop_all_ch(config.running)
        return "WFG configured"

    def _mso_config_values(self) -> dict[str, object]:
        channels = []
        if self.mso_ch1_enabled.isChecked():
            channels.append(0)
        if self.mso_ch2_enabled.isChecked():
            channels.append(1)
        return {
            "channel_indices": channels,
            "trigger_source": self.mso_trigger_source.currentText(),
            "sample_frequency_hz": self.mso_sample_frequency.value(),
            "sample_count": self.mso_sample_count.value(),
            "range_v": self.mso_range.value(),
            "offset_v": self.mso_offset.value(),
        }

    def _start_mso_init(self) -> None:
        self._run_action(lambda progress: self._mso_init(progress), "Initializing MSO")

    def _mso_init(self, progress=None) -> str:
        self.app.ad2.mso_init()
        if progress:
            progress("mso_stats", "MSO initialized")
        return "MSO initialized"

    def _start_mso_capture(self) -> None:
        config = self._mso_config_values()
        self._run_action(lambda progress: self._mso_capture(config, progress), "Capturing MSO")

    def _mso_capture(self, config: dict[str, object], progress=None) -> str:
        channel_indices = [int(index) for index in config["channel_indices"]]
        if not channel_indices:
            raise ValueError("Select at least one MSO channel.")
        captures = self.app.ad2.capture_scope_channels(
            channel_indices=channel_indices,
            sample_frequency_hz=float(config["sample_frequency_hz"]),
            sample_count=int(config["sample_count"]),
            range_v=float(config["range_v"]),
            offset_v=float(config["offset_v"]),
            trigger_source=str(config["trigger_source"]),
        )
        if progress:
            progress(
                "mso_capture",
                {
                    "captures": captures,
                    "sample_frequency_hz": float(config["sample_frequency_hz"]),
                    "trigger_source": str(config["trigger_source"]),
                },
            )
        sample_count = max((len(samples) for samples in captures.values()), default=0)
        channels = ", ".join(f"CH{index + 1}" for index in sorted(captures))
        return f"MSO captured {sample_count} samples on {channels}"

    def _start_configure_syringe(self) -> None:
        syringe = self.syringe.currentText()
        self._run_action(lambda progress: self._configure_syringe(syringe), "Configuring syringe")

    def _configure_syringe(self, syringe: str) -> str:
        self.app.pump.configure_syringe({"name": syringe})
        return "Syringe configured"

    def _start_generate_flow(self) -> None:
        flow_rate = self.flow_rate.value()
        self._run_action(lambda progress: self.app.pump.generate_flow(flow_rate), "Generating flow")

    def _start_go_level(self) -> None:
        level = self.level_ml.value()
        self._run_action(lambda progress: self.app.pump.set_fill_level(level), "Setting pump level")

    def _start_flush(self) -> None:
        settings = self._flush_settings()
        count = self.flush_count.value()
        self._run_action(lambda progress: self._flush(settings, count, progress), "Flushing")

    def _flush(self, settings: FlushSettings, count: int, progress=None) -> str:
        for index in range(count):
            if progress:
                progress("status", f"Flush {index + 1} of {count}")
            self.app.flush(settings)
        return "FlushComplete"

    def _start_configure_camera(self) -> None:
        roi = SubRegion(
            horizontal_offset=self.roi_h_offset.value(),
            vertical_offset=self.roi_v_offset.value(),
            horizontal_size=self.roi_h_size.value(),
            vertical_size=self.roi_v_size.value(),
        )
        exposure_ms = self.exposure_ms.value()
        center = self.center_roi.isChecked()
        self._run_action(lambda progress: self._configure_camera(roi, exposure_ms, center), "Configuring Camera")

    def _configure_camera(self, roi: SubRegion, exposure_ms: float, center: bool) -> str:
        self.app.camera.configure_exposure_time(exposure_ms)
        self.app.camera.configure_roi(roi)
        if center:
            self.app.camera.center_roi()
        return "Camera configured"

    def _start_save_sequence(self) -> None:
        folder = Path(self.sequence_path.text() or ".")
        self._run_action(lambda progress: self._save_sequence(folder), "Saving sequence")

    def _save_sequence(self, folder: Path) -> str:
        self.app.camera.save_sequence([], folder)
        return "Sequence saved"

    def _start_experiment(self) -> None:
        series, total_frames, config = self._build_experiment_series()
        self.queue_count.setText(str(series.see_elements_left()))
        self.waveform_graph.set_points(self._preview_points(config))
        self._run_action(
            lambda progress: self._run_experiment_series(series, total_frames, config, progress),
            "Running experiment",
        )

    def _build_experiment_series(self) -> tuple[ExperimentSeries2, int, WfgConfig]:
        config = self._experiment_wfg_config()
        started_at = time.monotonic()
        _ = started_at
        experiments = []
        for repeat in range(self.exp_repeats.value()):
            folder = Path(self.series_path.text()) / f"repeat_{repeat + 1:03d}"
            experiments.append(
                Experiment2(
                    repeat_id=repeat,
                    experiment_folder=folder,
                    flush_settings=self._flush_settings(experiment=True),
                    flush_enabled=self.exp_flush_enabled.isChecked(),
                    global_exposure_ms=self.exp_exposure_ms.value(),
                    sequence_settings={
                        "frames": self.exp_frames.value(),
                        "camera_start_s": [widget.value() for widget in self.camera_start_array],
                    },
                    wfg_config=config,
                    do_clock_settings={},
                )
            )
        return ExperimentSeries2(Path(self.series_path.text()), experiments), self.exp_frames.value() * self.exp_repeats.value(), config

    def _run_experiment_series(
        self,
        series: ExperimentSeries2,
        total_frames: int,
        config: WfgConfig,
        progress=None,
    ) -> str:
        started_at = time.monotonic()
        self.app.set_experiment_series_general(series)
        if progress:
            progress("queue_count", self.app.experiment_series.see_elements_left())
            progress("waveform", self._preview_points(config))
        while self.app.experiment_series.see_elements_left():
            self.app.run_experiment2()
            if progress:
                progress("queue_count", self.app.experiment_series.see_elements_left())
                progress("status", self.app.status)
        elapsed = max(time.monotonic() - started_at, 0.001)
        if progress:
            fps = total_frames / elapsed
            progress("average_fps", f"{fps:.2f}")
        return "ExperimentComplete"

    def _experiment_wfg_config(self) -> WfgConfig:
        config = self._wfg_config()
        config.channels[0].carrier.frequency_hz = self.exp_ch1_freq.value()
        config.channels[0].carrier.amplitude_v = self.exp_ch1_amp.value()
        config.channels[0].trigger.sec_wait = self.exp_ch1_start.value()
        config.channels[0].trigger.sec_run = self.exp_ch1_run.value()
        config.channels[1].trigger.sec_wait = self.exp_ch2_start.value()
        config.channels[1].trigger.sec_run = self.exp_ch2_run.value()
        return config

    def _browse_folder(self, target: QLineEdit) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Select folder", target.text() or str(Path.cwd()))
        if selected:
            target.setText(selected)

    def _abort(self) -> None:
        self.app.fire_stop_event()
        try:
            self.app.pump.stop()
            self.app.camera.stop_capture()
            self.app.ad2.wfg_start_stop_all_ch(False)
        except Exception as exc:  # pragma: no cover - best-effort emergency path
            self.app.check_loop_error(exc)
        self._set_status("Aborted")

    def _exit_app(self) -> None:
        if self._busy_count:
            self._abort()
        else:
            try:
                self.app.cleanup()
            except Exception as exc:  # pragma: no cover - shutdown cleanup path
                self.app.check_loop_error(exc)
        self.close()

    def _run_action(self, action, starting_status: str) -> None:
        if self._busy_count:
            self._set_status("Busy")
            return
        self._busy_count += 1
        self._set_status(starting_status)
        thread = QThread(self)
        worker = ActionWorker(action)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._handle_worker_progress)
        worker.finished.connect(self._handle_worker_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(lambda: self._threads.remove(thread) if thread in self._threads else None)
        thread.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)
        thread.finished.connect(thread.deleteLater)
        self._threads.append(thread)
        self._workers.append(worker)
        thread.start()

    def _handle_worker_progress(self, kind: str, value: object) -> None:
        if kind == "status":
            self._set_status(str(value))
        elif kind == "queue_count":
            self.queue_count.setText(str(value))
        elif kind == "average_fps":
            self.average_fps.setText(str(value))
        elif kind == "waveform":
            self.waveform_graph.set_points([float(item) for item in value])
        elif kind == "mso_capture" and isinstance(value, dict):
            captures = {
                int(index): [float(item) for item in samples]
                for index, samples in value.get("captures", {}).items()
            }
            sample_frequency_hz = float(value.get("sample_frequency_hz", 1.0))
            self.mso_samples = captures.get(0) or captures.get(1) or []
            self.mso_graph.set_series({f"CH{index + 1}": samples for index, samples in captures.items()}, sample_frequency_hz)
            self._set_mso_stats(captures, sample_frequency_hz, str(value.get("trigger_source", "")))
        elif kind == "mso_stats":
            self.mso_stats.setText(str(value))

    def _handle_worker_finished(self, ok: bool, status: str, error: str) -> None:
        self._busy_count = max(self._busy_count - 1, 0)
        if ok:
            self.error_status.setText("OK")
            self.error_code.setText("0")
            self.error_source.setText("")
            if status and status != "Ready":
                self._set_status(status)
            else:
                self._refresh_status()
        else:
            self.app.check_loop_error(error)
            self.error_status.setText("ERROR")
            self.error_code.setText("1")
            self.error_source.setText(error)
            self._set_status("Error")

    def _safe_call(self, action) -> None:
        try:
            action()
            self.error_status.setText("OK")
            self.error_code.setText("0")
            self.error_source.setText("")
        except Exception as exc:  # pragma: no cover - UI feedback path
            self.app.check_loop_error(exc)
            self.error_status.setText("ERROR")
            self.error_code.setText("1")
            self.error_source.setText(str(exc))
        finally:
            self._refresh_status()

    def _set_status(self, status: str) -> None:
        self.app.fire_status_event(status)
        self._refresh_status()

    def _refresh_status(self) -> None:
        self.status.setText(self.app.status)

    def _preview_points(self, config: WfgConfig) -> list[float]:
        channel = config.channels[0]
        amplitude = channel.carrier.amplitude_v if channel.carrier.enable else 0.0
        offset = channel.carrier.offset_v
        phase = math.radians(channel.carrier.phase_deg)
        values = []
        for index in range(101):
            x = index / 100.0
            if channel.carrier.function == WaveformFunction.SQUARE:
                raw = 1.0 if math.sin(math.tau * x + phase) >= 0 else -1.0
            elif channel.carrier.function == WaveformFunction.TRIANGLE:
                raw = 2.0 * abs(2.0 * (x - math.floor(x + 0.5))) - 1.0
            elif channel.carrier.function == WaveformFunction.DC:
                raw = 0.0
            else:
                raw = math.sin(math.tau * x + phase)
            values.append(offset + amplitude * raw)
        return values

    def _set_mso_stats(self, captures: dict[int, list[float]], sample_frequency_hz: float, trigger_source: str) -> None:
        if not captures:
            self.mso_stats.setText("No samples")
            self.mso_text.setPlainText("")
            return
        lines = []
        preview_lines = []
        for channel_index, samples in sorted(captures.items()):
            if not samples:
                continue
            vmin = min(samples)
            vmax = max(samples)
            mean = sum(samples) / len(samples)
            rms = math.sqrt(sum((sample - mean) ** 2 for sample in samples) / len(samples))
            duration = (len(samples) - 1) / max(sample_frequency_hz, 1.0)
            lines.append(
                f"CH{channel_index + 1}: {len(samples)} samples, {duration:.6f}s, "
                f"min {vmin:.6g} V, max {vmax:.6g} V, Vpp {vmax - vmin:.6g} V, RMS(ac) {rms:.6g} V"
            )
            for index, value in enumerate(samples[:6]):
                preview_lines.append(f"CH{channel_index + 1}\t{index / sample_frequency_hz:.9f}s\t{value:.9f} V")
        self.mso_stats.setText(f"{sample_frequency_hz:g} S/s | trigger {trigger_source} | " + " | ".join(lines))
        preview = "\n".join(preview_lines)
        self.mso_text.setPlainText(preview)

    def _settings_dict(self) -> dict[str, object]:
        return {
            "ad2_enabled": self.ad2_enabled.isChecked(),
            "z_enabled": self.z_enabled.isChecked(),
            "camera_enabled": self.camera_enabled.isChecked(),
            "pump_enabled": self.pump_enabled.isChecked(),
            "valve_enabled": self.valve_enabled.isChecked(),
            "sim_ad2": self.sim_ad2.isChecked(),
            "sim_camera": self.sim_camera.isChecked(),
            "sim_pump": self.sim_pump.isChecked(),
            "sim_valve": self.sim_valve.isChecked(),
            "z_backend": self.z_backend.currentText(),
            "prior_resource": self.prior_resource.text(),
            "thorlabs_apt_serial": self.thorlabs_apt_serial.text(),
            "thorlabs_apt_backend": self.thorlabs_apt_backend.text(),
            "thorlabs_apt_discovery_only": self.thorlabs_apt_discovery_only.isChecked(),
            "valve_resource": self.valve_resource.text(),
            "qmix_sdk_python_path": self.qmix_sdk_python_path.text(),
            "qmix_qmixsdk_path": self.qmix_qmixsdk_path.text(),
            "cetoni_config_path": self.cetoni_config_path.text(),
            "series_path": self.series_path.text(),
            "sequence_path": self.sequence_path.text(),
            "wfg": [
                {
                    "idx": item["idx"].value(),
                    "frequency": item["frequency"].value(),
                    "amplitude": item["amplitude"].value(),
                    "offset": item["offset"].value(),
                    "symmetry": item["symmetry"].value(),
                    "phase": item["phase"].value(),
                    "function": item["function"].currentText(),
                    "enable": item["enable"].isChecked(),
                }
                for item in self.wfg_channels
            ],
            "mso": {
                "ch1_enabled": self.mso_ch1_enabled.isChecked(),
                "ch2_enabled": self.mso_ch2_enabled.isChecked(),
                "trigger_source": self.mso_trigger_source.currentText(),
                "sample_frequency_hz": self.mso_sample_frequency.value(),
                "sample_count": self.mso_sample_count.value(),
                "range_v": self.mso_range.value(),
                "offset_v": self.mso_offset.value(),
            },
            "experiment": {
                "repeats": self.exp_repeats.value(),
                "frames": self.exp_frames.value(),
                "exposure_ms": self.exp_exposure_ms.value(),
                "ch1_frequency": self.exp_ch1_freq.value(),
                "ch1_amplitude": self.exp_ch1_amp.value(),
                "flush_enabled": self.exp_flush_enabled.isChecked(),
                "flush_flowrate": self.exp_flush_flowrate.value(),
                "flush_volume": self.exp_flush_volume.value(),
                "wait_after_flush": self.exp_wait_after_flush.value(),
            },
        }

    def _save_settings(self) -> None:
        SETTINGS_PATH.write_text(json.dumps(self._settings_dict(), indent=2), encoding="utf-8")
        self._set_status(f"Settings saved: {SETTINGS_PATH.name}")

    def _load_settings(self) -> None:
        if not SETTINGS_PATH.exists():
            return
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        for name, widget in (
            ("ad2_enabled", self.ad2_enabled),
            ("z_enabled", self.z_enabled),
            ("camera_enabled", self.camera_enabled),
            ("pump_enabled", self.pump_enabled),
            ("valve_enabled", self.valve_enabled),
            ("sim_ad2", self.sim_ad2),
            ("sim_camera", self.sim_camera),
            ("sim_pump", self.sim_pump),
            ("sim_valve", self.sim_valve),
            ("thorlabs_apt_discovery_only", self.thorlabs_apt_discovery_only),
        ):
            if name in data:
                widget.setChecked(bool(data[name]))
        if "z_backend" in data:
            index = self.z_backend.findText(str(data["z_backend"]))
            if index >= 0:
                self.z_backend.setCurrentIndex(index)
        for name, widget in (
            ("prior_resource", self.prior_resource),
            ("thorlabs_apt_serial", self.thorlabs_apt_serial),
            ("thorlabs_apt_backend", self.thorlabs_apt_backend),
            ("valve_resource", self.valve_resource),
            ("qmix_sdk_python_path", self.qmix_sdk_python_path),
            ("qmix_qmixsdk_path", self.qmix_qmixsdk_path),
            ("cetoni_config_path", self.cetoni_config_path),
            ("series_path", self.series_path),
            ("sequence_path", self.sequence_path),
        ):
            if name in data:
                widget.setText(str(data[name]))
        for item, saved in zip(self.wfg_channels, data.get("wfg", [])):
            for key in ("idx", "frequency", "amplitude", "offset", "symmetry", "phase"):
                if key in saved:
                    item[key].setValue(saved[key])
            if "function" in saved:
                index = item["function"].findText(str(saved["function"]))
                if index >= 0:
                    item["function"].setCurrentIndex(index)
            if "enable" in saved:
                item["enable"].setChecked(bool(saved["enable"]))
        mso = data.get("mso", {})
        if isinstance(mso, dict):
            if "ch1_enabled" in mso:
                self.mso_ch1_enabled.setChecked(bool(mso["ch1_enabled"]))
            if "ch2_enabled" in mso:
                self.mso_ch2_enabled.setChecked(bool(mso["ch2_enabled"]))
            if "trigger_source" in mso:
                index = self.mso_trigger_source.findText(str(mso["trigger_source"]))
                if index >= 0:
                    self.mso_trigger_source.setCurrentIndex(index)
            elif "channel" in mso:
                channel = str(mso["channel"])
                self.mso_ch1_enabled.setChecked(channel == "1")
                self.mso_ch2_enabled.setChecked(channel == "2")
            for key, widget in (
                ("sample_frequency_hz", self.mso_sample_frequency),
                ("sample_count", self.mso_sample_count),
                ("range_v", self.mso_range),
                ("offset_v", self.mso_offset),
            ):
                if key in mso:
                    widget.setValue(mso[key])
        experiment = data.get("experiment", {})
        if isinstance(experiment, dict):
            mapping = {
                "repeats": self.exp_repeats,
                "frames": self.exp_frames,
                "exposure_ms": self.exp_exposure_ms,
                "ch1_frequency": self.exp_ch1_freq,
                "ch1_amplitude": self.exp_ch1_amp,
                "flush_flowrate": self.exp_flush_flowrate,
                "flush_volume": self.exp_flush_volume,
                "wait_after_flush": self.exp_wait_after_flush,
            }
            for key, widget in mapping.items():
                if key in experiment:
                    widget.setValue(experiment[key])
            if "flush_enabled" in experiment:
                self.exp_flush_enabled.setChecked(bool(experiment["flush_enabled"]))
        self._set_status("Settings loaded")

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API name
        if self._busy_count:
            self.app.fire_stop_event()
        self._save_settings()
        super().closeEvent(event)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
