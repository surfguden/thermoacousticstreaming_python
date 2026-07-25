from __future__ import annotations

import json
import logging
import math
import queue
import sys
import threading
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import QEvent, QObject, QPointF, QThread, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QPlainTextEdit,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .ad2 import (
    CarrierSettings,
    DigitalOutIdleState,
    DigitalOutType,
    DoConfig,
    DoSingleChannelConfig,
    FmSweepSettings,
    TriggerSettings,
    TriggerSource,
    WaveformFunction,
    WfgChannelConfig,
    WfgConfig,
)
from .application import Application
from .camera import SubRegion
from .hardware_factory import HardwareRuntimeConfig, apply_hardware_bundle, build_hardware_bundle
from .hardware_config import ZStageBackend, default_hardware_config
from .instruments import SimulatedAD2Sdk
from .workflows import Experiment2, ExperimentSeries2, FlushSettings


logger = logging.getLogger(__name__)

SETTINGS_PATH = Path(__file__).resolve().parents[2] / ".thermo_acoustic_ui.json"
WFG_TRIGGER_SOURCE_OPTIONS = ["trigsrcNone", "trigsrcPC", "trigsrcAnalogIn", "trigsrcDigitalIn"]
CONVERSION_METHOD_OPTIONS = ["Full Dynamic", "90% Dynamic", "Downshift"]


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


def _set_combo_text(widget: QComboBox, value: str) -> None:
    index = widget.findText(value)
    if index >= 0:
        widget.setCurrentIndex(index)


class FocusWheelGuard(QObject):
    """Let scroll pages handle wheel events unless numeric/dropdown widgets are focused."""

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt API name
        if event.type() != QEvent.Type.Wheel:
            return super().eventFilter(obj, event)
        if not isinstance(obj, (QSpinBox, QDoubleSpinBox, QComboBox)):
            return super().eventFilter(obj, event)
        if obj.hasFocus():
            return super().eventFilter(obj, event)

        parent = obj.parentWidget()
        while parent is not None and not isinstance(parent, QScrollArea):
            parent = parent.parentWidget()
        if isinstance(parent, QScrollArea):
            QApplication.sendEvent(parent.viewport(), event)
        event.ignore()
        return True


def install_focus_wheel_guard(app: QApplication | None) -> None:
    if app is None or getattr(app, "_thermo_acoustic_focus_wheel_guard", None) is not None:
        return
    guard = FocusWheelGuard(app)
    app.installEventFilter(guard)
    app._thermo_acoustic_focus_wheel_guard = guard


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


class ImagePreviewWindow(QDialog):
    closed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Camera Preview")
        self.setModal(False)
        self.resize(820, 620)
        self._last_qimage: QImage | None = None
        self._last_display_range: tuple[float, float] | None = None
        layout = QVBoxLayout(self)
        self.image_label = QLabel("No image captured yet")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(640, 480)
        self.image_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.image_label)

    def show_frame(self, frame: np.ndarray, *, method: str = "Full Dynamic", shifts: int = 0) -> tuple[float, float] | None:
        self._last_qimage = self._convert_to_display_image(frame, method=method, shifts=shifts)
        self._update_pixmap()
        return self._last_display_range

    def show_message(self, message: str) -> None:
        self._last_qimage = None
        self._last_display_range = None
        self.image_label.setPixmap(QPixmap())
        self.image_label.setText(message)

    def _convert_to_display_image(self, frame: np.ndarray, *, method: str = "Full Dynamic", shifts: int = 0) -> QImage:
        array = np.asarray(frame)
        if array.size == 0:
            raise ValueError("empty camera frame")
        if array.ndim > 2:
            array = array[..., 0]
        if method == "Full Dynamic":
            display, display_range = self._display_full_dynamic(array)
        elif method == "90% Dynamic":
            display, display_range = self._display_90_percent_dynamic(array)
        elif method == "Downshift":
            display, display_range = self._display_downshift(array, shifts)
        else:
            raise ValueError(f"unknown conversion method: {method}")
        self._last_display_range = display_range
        display = np.ascontiguousarray(display)
        height, width = display.shape
        image = QImage(display.data, width, height, display.strides[0], QImage.Format.Format_Grayscale8)
        return image.copy()

    def _finite_display_array(self, array: np.ndarray) -> np.ndarray:
        if array.size == 0:
            raise ValueError("empty camera frame")
        finite = array[np.isfinite(array)]
        if finite.size == 0:
            raise ValueError("camera frame contains no finite display range")
        return finite

    def _display_full_dynamic(self, array: np.ndarray) -> tuple[np.ndarray, tuple[float, float]]:
        finite = self._finite_display_array(array)
        minimum = float(np.min(finite))
        maximum = float(np.max(finite))
        return self._linear_stretch(array, minimum, maximum), (minimum, maximum)

    def _display_90_percent_dynamic(self, array: np.ndarray) -> tuple[np.ndarray, tuple[float, float]]:
        finite = self._finite_display_array(array)
        minimum, maximum = self._middle_percentile_range(finite, 0.90)
        return self._linear_stretch(array, minimum, maximum), (minimum, maximum)

    def _display_downshift(self, array: np.ndarray, shifts: int) -> tuple[np.ndarray, tuple[float, float] | None]:
        clipped_shifts = max(int(shifts), 0)
        shifted = np.right_shift(np.clip(array, 0, np.iinfo(np.uint16).max).astype(np.uint16), clipped_shifts)
        return np.clip(shifted, 0, 255).astype(np.uint8), None

    def _middle_percentile_range(self, values: np.ndarray, fraction: float) -> tuple[float, float]:
        lower_fraction = (1.0 - fraction) / 2.0
        upper_fraction = 1.0 - lower_fraction
        if np.issubdtype(values.dtype, np.integer) and values.size:
            minimum = int(np.min(values))
            maximum = int(np.max(values))
            if minimum >= 0 and maximum <= 65535:
                counts = np.bincount(values.astype(np.uint16), minlength=maximum + 1)
                cumulative = np.cumsum(counts)
                total = int(cumulative[-1])
                lower_count = max(int(np.floor(total * lower_fraction + 1e-12)) + 1, 1)
                upper_count = max(int(np.ceil(total * upper_fraction)), 1)
                lower = int(np.searchsorted(cumulative, lower_count, side="left"))
                upper = int(np.searchsorted(cumulative, upper_count, side="left"))
                return float(lower), float(upper)
        return (
            float(np.quantile(values.astype(np.float64), lower_fraction)),
            float(np.quantile(values.astype(np.float64), upper_fraction)),
        )

    def _linear_stretch(self, array: np.ndarray, minimum: float, maximum: float) -> np.ndarray:
        minimum = float(minimum)
        maximum = float(maximum)
        if not np.isfinite(minimum) or not np.isfinite(maximum):
            raise ValueError("camera frame contains no finite display range")
        if maximum > minimum:
            scaled = (array.astype(np.float32) - minimum) * (255.0 / (maximum - minimum))
            return np.clip(scaled, 0, 255).astype(np.uint8)
        return np.zeros(array.shape, dtype=np.uint8)

    def _update_pixmap(self) -> None:
        if self._last_qimage is None:
            return
        pixmap = QPixmap.fromImage(self._last_qimage)
        self.image_label.setText("")
        self.image_label.setPixmap(
            pixmap.scaled(
                self.image_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API name
        super().resizeEvent(event)
        self._update_pixmap()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API name
        self.closed.emit()
        super().closeEvent(event)


class ActionWorker(QObject):
    finished = Signal(bool, str, str)
    progress = Signal(str, object)

    def __init__(self, action) -> None:
        super().__init__()
        self.action = action

    def run(self) -> None:
        try:
            result = self.action(self.progress.emit)
            status = str(result) if result is not None else "Ready"
            self.finished.emit(True, status, "")
        except Exception as exc:  # pragma: no cover - Qt worker feedback path
            self.finished.emit(False, "Error", str(exc))


class MainWindow(QMainWindow):
    def __init__(self, app: Application | None = None) -> None:
        super().__init__()
        install_focus_wheel_guard(QApplication.instance())
        self.app = app or Application(ad2=SimulatedAD2Sdk())
        self.setWindowTitle("Thermo Acoustic Streaming")
        self.resize(1280, 820)
        self.setMinimumSize(980, 680)
        self._threads: list[QThread] = []
        self._workers: list[ActionWorker] = []
        self._busy_count = 0
        self._shutdown_in_progress = False
        self._close_after_shutdown = False
        self._shutdown_thread: threading.Thread | None = None
        self._shutdown_result_queue: queue.Queue[tuple[bool, str, str]] | None = None
        self._shutdown_poll_timer = QTimer(self)
        self._shutdown_poll_timer.timeout.connect(self._poll_shutdown_cleanup)
        self._shutdown_timeout_timer = QTimer(self)
        self._shutdown_timeout_timer.setSingleShot(True)
        self._shutdown_timeout_timer.timeout.connect(self._handle_shutdown_timeout)
        self._shutdown_timeout_s = 30.0
        self._cleanup_complete_for_close = False
        self._controls_disabled_for_action = False
        self._timed_out_threads: dict[QThread, str] = {}
        self._window_was_shown = False
        self._last_camera_image_data: object | None = None
        self._camera_preview: ImagePreviewWindow | None = None
        self._camera_preview_active = False
        self._camera_preview_timer = QTimer(self)
        self._camera_preview_timer.setInterval(100)
        self._camera_preview_timer.timeout.connect(self._capture_camera_image_continuous)

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
        self.custom_syringe_volume_ml = _spin(1.0, decimals=3, minimum=0.001)
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
        self.image_continuous.setChecked(False)
        self.conversion_method = _combo(CONVERSION_METHOD_OPTIONS, "Full Dynamic")
        self.conversion_min = _spin(0.0, decimals=3)
        self.conversion_min.setReadOnly(True)
        self.conversion_max = _spin(0.0, decimals=3)
        self.conversion_max.setReadOnly(True)
        self.conversion_shifts = _int_spin(0, minimum=0, maximum=16)
        self.sequence_path = QLineEdit("")
        self.sequence_mode = _combo(["Continuous", "Start (single)", "Burst"], "Continuous")
        self.sequence_source = _combo(["External", "Software"], "External")
        self.sequence_interval = _spin(1.0, decimals=6, minimum=0.000005, maximum=10.0)
        self.sequence_burst = _int_spin(1, minimum=1, maximum=65535)
        self.capture_mode = _combo(["Snap", "Sequence"], "Snap")
        self.capture_mode.setEnabled(False)
        self.capture_mode.setToolTip("Not wired to a real backend: never read by _camera_sequence_settings() or any capture path (confirmed dead, Session 11).")
        self.sequence_frames = _int_spin(0, minimum=0)
        self.dcam_source = _combo(["Internal", "External", "Software", "MasterPulse"], "Internal")
        self.external_polarity = _combo(["Negative", "Positive"], "Negative")
        self.external_delay = _spin(0.0, decimals=6, minimum=0.0, maximum=10.000002)
        self.sequence_exposure_ms = _spin(0.0, decimals=3, minimum=0.0)

        self.series_path = QLineEdit(r"C:\test\firstrunpulsed")
        self.exp_camera_fps = _spin(0.0, decimals=3, minimum=0.0)
        self.exp_camera_start = _spin(0.0, decimals=3, minimum=0.0)
        self.exp_ch1_freq = _spin(0.0, decimals=3, minimum=0.0)
        self.exp_ch1_amp = _spin(0.0, decimals=3)
        self.exp_ch1_offset = _spin(0.0, decimals=3)
        self.exp_ch1_function = _combo([item.value for item in WaveformFunction], WaveformFunction.SINE.value)
        self.exp_ch1_enable = QCheckBox("Enable")
        self.exp_ch1_start = _spin(0.0, decimals=3, minimum=0.0)
        self.exp_ch1_run = _spin(0.0, decimals=3, minimum=0.0)
        self.exp_ch1_repeat = _int_spin(0, minimum=0)
        self.exp_ch1_trigger_source = _combo(WFG_TRIGGER_SOURCE_OPTIONS, "trigsrcNone")
        self.exp_ch1_symmetry = _spin(50.0, decimals=3, minimum=0.0, maximum=100.0)
        self.exp_ch1_phase = _spin(0.0, decimals=3)
        self.exp_ch1_repeat_trigger = QCheckBox("Repeat Trigger")
        self.exp_sweep_enable = QCheckBox("Enable Frequency Sweep During Experiment")
        self.exp_sweep_center_khz = _spin(1934.0, decimals=3, minimum=0.0)
        self.exp_sweep_width_khz = _spin(50.0, decimals=3, minimum=0.0)
        self.exp_sweep_time_ms = _spin(1.0, decimals=3, minimum=0.0)
        self.exp_sweep_type = _combo(["Symmetric", "RampUp", "RampDown"], "Symmetric")
        self.exp_ch2_freq = _spin(1.0, decimals=3, minimum=0.0)
        self.exp_ch2_amp = _spin(1.0, decimals=3)
        self.exp_ch2_offset = _spin(0.0, decimals=3)
        self.exp_ch2_function = _combo([item.value for item in WaveformFunction], WaveformFunction.SINE.value)
        self.exp_ch2_enable = QCheckBox("Enable")
        self.exp_ch2_start = _spin(0.0, decimals=3, minimum=0.0)
        self.exp_ch2_run = _spin(0.0, decimals=3, minimum=0.0)
        self.exp_ch2_repeat = _int_spin(0, minimum=0)
        self.exp_ch2_trigger_source = _combo(WFG_TRIGGER_SOURCE_OPTIONS, "trigsrcNone")
        self.exp_ch2_symmetry = _spin(50.0, decimals=3, minimum=0.0, maximum=100.0)
        self.exp_ch2_phase = _spin(0.0, decimals=3)
        self.exp_ch2_repeat_trigger = QCheckBox("Repeat Trigger")
        self.exp_ad2_channels = [
            {
                "frequency": self.exp_ch1_freq,
                "amplitude": self.exp_ch1_amp,
                "offset": self.exp_ch1_offset,
                "function": self.exp_ch1_function,
                "enable": self.exp_ch1_enable,
                "sec_wait": self.exp_ch1_start,
                "sec_run": self.exp_ch1_run,
                "repeat": self.exp_ch1_repeat,
                "trigger_source": self.exp_ch1_trigger_source,
                "symmetry": self.exp_ch1_symmetry,
                "phase": self.exp_ch1_phase,
                "repeat_trigger": self.exp_ch1_repeat_trigger,
            },
            {
                "frequency": self.exp_ch2_freq,
                "amplitude": self.exp_ch2_amp,
                "offset": self.exp_ch2_offset,
                "function": self.exp_ch2_function,
                "enable": self.exp_ch2_enable,
                "sec_wait": self.exp_ch2_start,
                "sec_run": self.exp_ch2_run,
                "repeat": self.exp_ch2_repeat,
                "trigger_source": self.exp_ch2_trigger_source,
                "symmetry": self.exp_ch2_symmetry,
                "phase": self.exp_ch2_phase,
                "repeat_trigger": self.exp_ch2_repeat_trigger,
            },
        ]
        self._experiment_ad2_seeded = False
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
        # Frequency Scanning / Dynamic Frequency (LabVIEW's FrequencyHelper.vi +
        # CreateExperiments.vi "Dynamic Frequency"/"Frequency List" inputs,
        # investigated in a prior session, implemented here). Discrete per-repeat
        # substitution of Channel 1's carrier frequency -- architecturally
        # parallel to Dynamic Camera Start Time above, but the frequency list
        # is generated from Start/Stop/Count rather than entered per-slot.
        # Start/Stop use kHz, matching the Session-29 kHz unification for every
        # other WFG Carrier frequency field on this tab (not Hz, as the
        # original LabVIEW-only investigation assumed before that unification).
        self.exp_freq_scan_enable = QCheckBox("Enable Frequency Scanning During Experiment")
        self.exp_freq_scan_start_khz = _spin(1900.0, decimals=3, minimum=0.0)
        self.exp_freq_scan_stop_khz = _spin(1975.0, decimals=3, minimum=0.0)
        self.exp_freq_scan_count = _int_spin(2, minimum=1)
        self.average_fps = QLabel("0")

    def _make_wfg_channel_state(self, index: int, frequency: float, amplitude: float) -> dict[str, object]:
        # frequency/amplitude are passed in Hz (caller-facing default values);
        # all frequency-class widgets below display/store kHz -- see the
        # kHz-unification note in _channel_config().
        return {
            "idx": _int_spin(index, minimum=0, maximum=1),
            "frequency": _spin(frequency / 1000.0, decimals=3, minimum=0.0),
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
            "trigger_source": _combo(WFG_TRIGGER_SOURCE_OPTIONS, "trigsrcNone"),
            "fm_frequency": _spin(1.0, decimals=3, minimum=0.0),
            "fm_amplitude": _spin(1.0, decimals=3),
            "fm_offset": _spin(0.0, decimals=3),
            "fm_symmetry": _spin(50.0, decimals=3, minimum=0.0, maximum=100.0),
            "fm_phase": _spin(0.0, decimals=3),
            "fm_function": _combo([item.value for item in WaveformFunction], WaveformFunction.SINE.value),
            "fm_enable": QCheckBox("Enable"),
            "sweep_enable": QCheckBox("Enable Sweep"),
            "sweep_center_khz": _spin(frequency / 1000.0, decimals=3, minimum=0.0),
            "sweep_width_khz": _spin(50.0, decimals=3, minimum=0.0),
            "sweep_time_ms": _spin(1.0, decimals=3, minimum=0.0),
            "sweep_type": _combo(["Symmetric", "RampUp", "RampDown"], "Symmetric"),
            "sweep_top_khz": QLabel("--"),
            "sweep_bottom_khz": QLabel("--"),
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
        self.tabs.currentChanged.connect(self._seed_experiment_ad2_if_experiment_tab)
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
        note = QLabel("Manual AD2 test tool -- independent from Experiment tab. Settings here do NOT affect experiment runs.")
        note.setWordWrap(True)
        layout.addWidget(note)
        header = QHBoxLayout()
        header.addWidget(QLabel("WFGConfig"))
        header.addWidget(self.wfg_running)
        header.addStretch()
        header.addWidget(QLabel("SynchronizeState"))
        self.wfg_sync.setEnabled(False)
        self.wfg_sync.setToolTip("Not implemented: SynchronizeState is currently a non-functional stub.")
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
        # Live-use labeling: the Experiment tab seeds its own separate CH0/CH1
        # widgets from these ONCE (on first tab switch) and is independent of
        # this tab after that -- confirmed by tracing _experiment_channel_config()
        # (reads self.exp_ad2_channels[i], never these state[...] widgets) for
        # every field below, on BOTH channels. The task that requested this
        # labeling described Frequency/Amplitude as CH0-only-overridden and
        # Symmetry/Phase/Enable/Function/Trigger source/CH1 Frequency/Amplitude
        # as "remaining active" from this tab -- that second claim did not hold
        # up: _experiment_channel_config() reads exp_ch2_freq/exp_ch2_amp for
        # CH1 exactly like exp_ch1_freq/exp_ch1_amp for CH0, and every other
        # field listed there also has its own confirmed Experiment-tab widget.
        # Labeled uniformly and accurately here instead of per that assumption.
        overridden = " (overridden during experiment run)"
        # This tab's Ch1/Ch2 groups (Carrier+Trigger+FM Mod+Sweep, ~25 rows) are
        # squeezed below their own minimumSizeHint in both width and height when
        # shown inside MainWindow's fixed-size tab page (confirmed offscreen:
        # 541x626 actual vs 1092x820 required) -- the same collapse-risk class as
        # _ad_settings_group() before its Session 28 fix, made measurably worse by
        # this session's longer live-use labels. Both dimensions are short here
        # (unlike _ad_settings_group(), where only height was short), so this uses
        # setWidgetResizable(False) with both scrollbars as-needed -- the same
        # pattern already proven for qt_ui_v2.py's AD2 Output Parameters table --
        # rather than setWidgetResizable(True), which would still try to compress
        # the width.
        group = QGroupBox(title)
        outer = QVBoxLayout(group)
        content = QWidget()
        layout = QVBoxLayout(content)
        form = QFormLayout()
        for label, key in (
            ("Channel index", "idx"),
            (f"Frequency (kHz) Carrier{overridden}", "frequency"),
            (f"Amplitude (V){overridden}", "amplitude"),
            (f"Offset(V){overridden}", "offset"),
            (f"Symmetry(%){overridden}", "symmetry"),
            (f"Phase(Deg){overridden}", "phase"),
            (f"Function{overridden}", "function"),
        ):
            form.addRow(label, state[key])
        state["enable"].setText(f"Enable{overridden}")
        form.addRow(state["enable"])
        layout.addLayout(form)
        trigger = QFormLayout()
        for label, key in (
            (f"Run duration (s)   [0 = continuous]{overridden}", "sec_run"),
            (f"secWait{overridden}", "sec_wait"),
            (f"Repeat count   [0 = infinite]{overridden}", "repeat"),
        ):
            trigger.addRow(label, state[key])
        state["repeat_trigger"].setText(f"Repeat Trigger{overridden}")
        trigger.addRow(state["repeat_trigger"])
        trigger.addRow(f"Trigger source{overridden}", state["trigger_source"])
        layout.addWidget(QLabel("Trigger"))
        layout.addLayout(trigger)
        fm = QFormLayout()
        # FM Mod: traced _experiment_channel_config() -- when FM Sweep is off,
        # fm_mod is a hardcoded-disabled CarrierSettings; when FM Sweep is on
        # (Ch1/CH0 only), fm_mod comes entirely from the Experiment tab's own
        # Sweep fields. Either way, these FM Mod widgets are never read by an
        # automated run -- not "active", not "overridden", simply unused.
        fm_note = " (not used by automated experiment runs)"
        for label, key in (
            (f"Frequency (kHz){fm_note}", "fm_frequency"),
            (f"Amplitude (%){fm_note}", "fm_amplitude"),
            (f"Offset(V){fm_note}", "fm_offset"),
            (f"Symmetry(%){fm_note}", "fm_symmetry"),
            (f"Phase(Deg){fm_note}", "fm_phase"),
            (f"Function 2{fm_note}", "fm_function"),
        ):
            fm.addRow(label, state[key])
        fm.addRow(state["fm_enable"])
        layout.addWidget(QLabel("FM Mod"))
        layout.addLayout(fm)
        sweep = QFormLayout()
        for label, key in (
            ("Center Frequency (kHz)", "sweep_center_khz"),
            ("Sweep Width (kHz)", "sweep_width_khz"),
            ("Sweep Time (ms)", "sweep_time_ms"),
            ("Sweep Type", "sweep_type"),
        ):
            sweep.addRow(label, state[key])
        sweep.addRow(state["sweep_enable"])
        sweep.addRow("Top Frequency (kHz)", state["sweep_top_khz"])
        sweep.addRow("Bottom Frequency (kHz)", state["sweep_bottom_khz"])
        layout.addWidget(QLabel("Sweep (FM modulation calibration -- distinct from Frequency Scanning)"))
        layout.addLayout(sweep)
        self._connect_sweep_bounds_refresh(state)
        self._refresh_sweep_bounds(state)

        scroll = QScrollArea()
        scroll.setWidgetResizable(False)
        scroll.setMaximumHeight(500)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        return group

    def _connect_sweep_bounds_refresh(self, state: dict[str, object]) -> None:
        for key in ("sweep_center_khz", "sweep_width_khz"):
            state[key].valueChanged.connect(lambda _value, state=state: self._refresh_sweep_bounds(state))

    def _refresh_sweep_bounds(self, state: dict[str, object]) -> None:
        center_khz = state["sweep_center_khz"].value()
        width_khz = state["sweep_width_khz"].value()
        state["sweep_top_khz"].setText(f"{center_khz + width_khz / 2.0:.3f}")
        state["sweep_bottom_khz"].setText(f"{center_khz - width_khz / 2.0:.3f}")

    def _fm_sweep_settings_from_state(self, state: dict[str, object]) -> FmSweepSettings:
        return FmSweepSettings(
            center_hz=state["sweep_center_khz"].value() * 1000.0,
            width_hz=state["sweep_width_khz"].value() * 1_000.0,
            sweep_time_ms=state["sweep_time_ms"].value(),
            sweep_type=state["sweep_type"].currentText(),
        )

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
        ref.clicked.connect(self._start_reference_move)
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
        grid.addWidget(QLabel("Custom Volume (ml)"), 2, 3)
        grid.addWidget(self.custom_syringe_volume_ml, 3, 3)
        grid.addWidget(QLabel("ConfigureSyringe"), 2, 4)
        grid.addWidget(configure, 3, 4)
        grid.addWidget(QLabel("Flow Rate (-=aspirate, +=dispense)"), 5, 2)
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
        image.clicked.connect(self._start_capture_camera_image)
        self.image_continuous.toggled.connect(self._set_image_continuous)
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
        adjust.clicked.connect(self._adjust_camera_preview)
        self.conversion_method.currentTextChanged.connect(lambda _value: self._update_conversion_controls())
        layout.addLayout(form)
        layout.addWidget(QLabel("Adjust Intensity in image"))
        layout.addWidget(adjust, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addStretch()
        self._update_conversion_controls()
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
        settings.addRow("Capture mode (unused)", self.capture_mode)
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
        sequence_note = QLabel(
            "These Sequence Settings (Mode/Source/Interval/Burst/Polarity/Delay) are "
            "applied to every automated Experiment run -- unlike the WFG tab, changes "
            "made here DO affect experiment runs."
        )
        sequence_note.setWordWrap(True)
        grid.addWidget(QLabel("Sequence Settings"), 0, 2)
        grid.addWidget(sequence_note, 1, 2)
        grid.addLayout(settings, 2, 2, 7, 1)
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
        grid.addWidget(QLabel("Series path"), 5, 0)
        grid.addWidget(self.series_path, 6, 0, 1, 5)
        grid.addWidget(browse, 6, 5)
        grid.addWidget(self._ad_settings_group(), 7, 0, 1, 2)
        grid.addWidget(self._experiment_settings_column(), 7, 2, 2, 1)
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
        outer = QVBoxLayout(group)

        # This group's natural content height (~1000px across both channels'
        # Carrier/Trigger/Sweep sections) far exceeds what the Experiment tab's
        # grid can give it -- previously this squeezed the whole QVBoxLayout
        # below its minimumSizeHint, collapsing individual field rows to 0-1px
        # tall (visible header labels stacked with no visible values beneath
        # them). Giving the content its own QScrollArea lets it lay out at its
        # real size internally and scroll, instead of being compressed.
        content = QWidget()
        layout = QVBoxLayout(content)
        note = QLabel("These settings fully control AD2 output during experiment runs, independent of the WFG tab.")
        note.setWordWrap(True)
        layout.addWidget(note)

        top = QFormLayout()
        top.addRow("Camera FPS", self.exp_camera_fps)
        top.addRow("Camera Start (s)", self.exp_camera_start)
        layout.addLayout(top)

        self._add_experiment_channel_sections(layout, "CH0")
        self._add_experiment_channel_sections(layout, "CH1")

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(360)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        return group

    def _add_experiment_channel_sections(self, layout: QVBoxLayout, channel_label: str) -> None:
        # Mirrors the manual WFG tab's own Carrier/Trigger/(FM Mod)/Sweep
        # sub-grouping convention (_wfg_channel_group()) -- same QLabel +
        # QFormLayout structure, applied here since this form's fields
        # (unlike the WFG tab's) aren't otherwise visually distinguished.
        if channel_label == "CH0":
            enable, function, freq, amp, offset = (
                self.exp_ch1_enable, self.exp_ch1_function, self.exp_ch1_freq, self.exp_ch1_amp, self.exp_ch1_offset,
            )
            symmetry, phase = self.exp_ch1_symmetry, self.exp_ch1_phase
            start, run, repeat, trigger_source, repeat_trigger = (
                self.exp_ch1_start, self.exp_ch1_run, self.exp_ch1_repeat,
                self.exp_ch1_trigger_source, self.exp_ch1_repeat_trigger,
            )
        else:
            enable, function, freq, amp, offset = (
                self.exp_ch2_enable, self.exp_ch2_function, self.exp_ch2_freq, self.exp_ch2_amp, self.exp_ch2_offset,
            )
            symmetry, phase = self.exp_ch2_symmetry, self.exp_ch2_phase
            start, run, repeat, trigger_source, repeat_trigger = (
                self.exp_ch2_start, self.exp_ch2_run, self.exp_ch2_repeat,
                self.exp_ch2_trigger_source, self.exp_ch2_repeat_trigger,
            )

        # Live-use labeling (mirrors the WFG tab's "(overridden during
        # experiment run)" labels -- see _wfg_channel_group() for the trace
        # confirming every one of these fields is independently read here,
        # not from the WFG tab, once an automated run starts).
        overrides = " (overrides WFG tab)"
        carrier = QFormLayout()
        carrier.addRow(f"{channel_label} Enable{overrides}", enable)
        carrier.addRow(f"{channel_label} Function{overrides}", function)
        carrier.addRow(f"{channel_label} Frequency (kHz){overrides}", freq)
        carrier.addRow(f"{channel_label} Amplitude (V){overrides}", amp)
        carrier.addRow(f"{channel_label} Offset (V){overrides}", offset)
        carrier.addRow(f"{channel_label} Symmetry (%){overrides}", symmetry)
        carrier.addRow(f"{channel_label} Phase (Deg){overrides}", phase)
        layout.addWidget(QLabel("Carrier"))
        layout.addLayout(carrier)

        trigger = QFormLayout()
        run_label = "Run (s) (0=Cont)" if channel_label == "CH0" else "Run (s)(0=Cont)"
        trigger.addRow(f"{channel_label} Start (s){overrides}", start)
        trigger.addRow(f"{channel_label} {run_label}{overrides}", run)
        trigger.addRow(f"{channel_label} cRepeat (0=inf){overrides}", repeat)
        trigger.addRow(f"{channel_label} Trigger Source{overrides}", trigger_source)
        repeat_trigger.setText(f"Repeat Trigger{overrides}")
        trigger.addRow(repeat_trigger)
        layout.addWidget(QLabel("Trigger"))
        layout.addLayout(trigger)

        if channel_label == "CH0":
            sweep = QFormLayout()
            sweep.addRow(self.exp_sweep_enable)
            sweep.addRow(f"{channel_label} Sweep Center Frequency (kHz)", self.exp_sweep_center_khz)
            sweep.addRow(f"{channel_label} Sweep Width (kHz)", self.exp_sweep_width_khz)
            sweep.addRow(f"{channel_label} Sweep Time (ms)", self.exp_sweep_time_ms)
            sweep.addRow(f"{channel_label} Sweep Type", self.exp_sweep_type)
            layout.addWidget(QLabel("Sweep (FM modulation calibration -- distinct from Frequency Scanning)"))
            layout.addLayout(sweep)

    def _experiment_settings_column(self) -> QScrollArea:
        # Adding the Frequency Scanning group as a third box stacked in this
        # column (alongside the existing Experiment/Flush settings groups)
        # squeezed all three below their minimumSizeHint at the app's default
        # window size -- the same 0-1px row-collapse failure mode fixed for
        # _ad_settings_group() in an earlier session. Same fix here: give the
        # stack its own QScrollArea instead of forcing the grid to compress it.
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.addWidget(self._experiment_numbers_group())
        layout.addWidget(self._experiment_flush_group())
        layout.addWidget(self._experiment_frequency_scan_group())
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(360)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setWidget(content)
        return scroll

    def _experiment_numbers_group(self) -> QGroupBox:
        group = QGroupBox("Experiment")
        form = QFormLayout(group)
        form.addRow("Repeats", self.exp_repeats)
        form.addRow("Frames", self.exp_frames)
        form.addRow("Exposure time (ms)", self.exp_exposure_ms)
        return group

    def _experiment_flush_group(self) -> QGroupBox:
        group = QGroupBox("Flush settings")
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

    def _experiment_frequency_scan_group(self) -> QGroupBox:
        group = QGroupBox("Frequency Scanning (Dynamic Frequency, Ch1 only)")
        form = QFormLayout(group)
        form.addRow(self.exp_freq_scan_enable)
        form.addRow("Start Frequency (kHz)", self.exp_freq_scan_start_khz)
        form.addRow("Stop Frequency (kHz)", self.exp_freq_scan_stop_khz)
        form.addRow("Number of Frequencies", self.exp_freq_scan_count)
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
        # Frequency-class widgets (Carrier/FM Mod "Frequency", Sweep "Center/Top/
        # Bottom Frequency") display and store kHz -- matches the SeriesPath naming
        # convention (e.g. "1975kHz\..."). CarrierSettings.frequency_hz and the
        # actual hardware-writing calls remain in Hz internally, so widget values
        # are multiplied by 1000 here at the point they leave the UI layer.
        carrier = CarrierSettings(
            frequency_hz=state["frequency"].value() * 1000.0,
            amplitude_v=state["amplitude"].value(),
            offset_v=state["offset"].value(),
            symmetry_percent=state["symmetry"].value(),
            phase_deg=state["phase"].value(),
            function=WaveformFunction(state["function"].currentText()),
            enable=state["enable"].isChecked(),
        )
        fm_mod = CarrierSettings(
            frequency_hz=state["fm_frequency"].value() * 1000.0,
            amplitude_v=state["fm_amplitude"].value(),
            offset_v=state["fm_offset"].value(),
            symmetry_percent=state["fm_symmetry"].value(),
            phase_deg=state["fm_phase"].value(),
            function=WaveformFunction(state["fm_function"].currentText()),
            enable=state["fm_enable"].isChecked(),
        )
        if state["sweep_enable"].isChecked():
            sweep = self._fm_sweep_settings_from_state(state)
            carrier.frequency_hz = sweep.center_hz
            carrier.enable = True
            fm_mod = sweep.fm_mod_settings()
        return WfgChannelConfig(
            channel_index=state["idx"].value(),
            carrier=carrier,
            trigger=TriggerSettings(
                sec_run=state["sec_run"].value(),
                sec_wait=state["sec_wait"].value(),
                repeat_count=state["repeat"].value(),
                repeat_trigger=state["repeat_trigger"].isChecked(),
                source=state["trigger_source"].currentText(),
            ),
            fm_mod=fm_mod,
        )

    def _wfg_config(self) -> WfgConfig:
        return WfgConfig(
            running=self.wfg_running.isChecked(),
            channels=[self._channel_config(item) for item in self.wfg_channels],
            synchronize_state=self.wfg_sync.currentText(),
        )

    def _seed_experiment_ad2_from_wfg_once(self) -> None:
        if self._experiment_ad2_seeded:
            return
        for experiment_state, wfg_state in zip(self.exp_ad2_channels, self.wfg_channels):
            experiment_state["frequency"].setValue(wfg_state["frequency"].value())
            experiment_state["amplitude"].setValue(wfg_state["amplitude"].value())
            experiment_state["offset"].setValue(wfg_state["offset"].value())
            _set_combo_text(experiment_state["function"], wfg_state["function"].currentText())
            experiment_state["enable"].setChecked(wfg_state["enable"].isChecked())
            experiment_state["sec_wait"].setValue(wfg_state["sec_wait"].value())
            experiment_state["sec_run"].setValue(wfg_state["sec_run"].value())
            experiment_state["repeat"].setValue(wfg_state["repeat"].value())
            _set_combo_text(experiment_state["trigger_source"], wfg_state["trigger_source"].currentText())
            experiment_state["symmetry"].setValue(wfg_state["symmetry"].value())
            experiment_state["phase"].setValue(wfg_state["phase"].value())
            experiment_state["repeat_trigger"].setChecked(wfg_state["repeat_trigger"].isChecked())
        self._experiment_ad2_seeded = True

    def _seed_experiment_ad2_if_experiment_tab(self, index: int) -> None:
        if self.tabs.tabText(index) == "Experiment":
            self._seed_experiment_ad2_from_wfg_once()

    def _experiment_channel_config(
        self, index: int, state: dict[str, object], *, frequency_override_hz: float | None = None
    ) -> WfgChannelConfig:
        # state["frequency"] displays/stores kHz (Experiment tab's own Frequency
        # field) -- converted to Hz here, matching _channel_config()'s manual-tab
        # equivalent conversion.
        carrier = CarrierSettings(
            frequency_hz=state["frequency"].value() * 1000.0,
            amplitude_v=state["amplitude"].value(),
            offset_v=state["offset"].value(),
            symmetry_percent=state["symmetry"].value(),
            phase_deg=state["phase"].value(),
            function=WaveformFunction(state["function"].currentText()),
            enable=state["enable"].isChecked(),
        )
        fm_mod = CarrierSettings(
            frequency_hz=1000.0,
            amplitude_v=1.0,
            offset_v=0.0,
            symmetry_percent=50.0,
            phase_deg=0.0,
            function=WaveformFunction.SINE,
            enable=False,
        )
        # FM sweep calibration only applies to CH0 (index 0), matching
        # WfgConfigureSweepCh1.vi's own hardcoded-Ch1 scope. Toggle off
        # leaves carrier/fm_mod exactly as computed above, unchanged.
        if index == 0 and self.exp_sweep_enable.isChecked():
            sweep = self._experiment_fm_sweep_settings()
            carrier.frequency_hz = sweep.center_hz
            carrier.enable = True
            fm_mod = sweep.fm_mod_settings()
        # Frequency Scanning / Dynamic Frequency: per-repeat discrete carrier
        # frequency substitution (LabVIEW's CreateExperiments.vi "Dynamic
        # Frequency"/"Frequency List" inputs), applied only to Channel 1
        # (index 0) -- Channel 2 is never touched, matching the original
        # investigation's finding that this is architecturally parallel to
        # Dynamic Camera Start Time (a per-repeat substitution keyed on
        # repeat index), not a new experiment-count expansion. Applied after
        # FM Sweep's own override above so the two (unrelated, both Ch1-only)
        # features don't silently fight if both were somehow enabled at
        # once -- the per-repeat scan value wins.
        if index == 0 and frequency_override_hz is not None:
            carrier.frequency_hz = frequency_override_hz
        return WfgChannelConfig(
            channel_index=index,
            carrier=carrier,
            trigger=TriggerSettings(
                sec_run=state["sec_run"].value(),
                sec_wait=state["sec_wait"].value(),
                repeat_count=state["repeat"].value(),
                repeat_trigger=state["repeat_trigger"].isChecked(),
                source=state["trigger_source"].currentText(),
            ),
            fm_mod=fm_mod,
        )

    def _experiment_frequency_scan_list_hz(self) -> list[float]:
        # LabVIEW's FrequencyHelper.vi generates a linear array of frequencies
        # from Start/Stop/Number-of-Frequencies inputs (prior investigation,
        # C:\git\thermacoustics, commit 8f8e255, "Updated with Frequency
        # Scanning"). Linear (not log) spacing is inferred from that
        # investigation's reading of the VI, not independently re-derived
        # from its compiled block-diagram wiring -- flagged there as an
        # assumption, not a confirmed fact, and left as such here.
        start_hz = self.exp_freq_scan_start_khz.value() * 1000.0
        stop_hz = self.exp_freq_scan_stop_khz.value() * 1000.0
        count = self.exp_freq_scan_count.value()
        if count <= 1:
            return [start_hz] * count
        step = (stop_hz - start_hz) / (count - 1)
        return [start_hz + step * index for index in range(count)]

    def _experiment_fm_sweep_settings(self) -> FmSweepSettings:
        return FmSweepSettings(
            center_hz=self.exp_sweep_center_khz.value() * 1000.0,
            width_hz=self.exp_sweep_width_khz.value() * 1_000.0,
            sweep_time_ms=self.exp_sweep_time_ms.value(),
            sweep_type=self.exp_sweep_type.currentText(),
        )

    _SYRINGE_VOLUMES_ML = {
        "BD 1ml": 1.0,
        "BD 5ml": 5.0,
        "BD 10ml": 10.0,
    }

    def _syringe_volume_ml(self) -> float:
        name = self.syringe.currentText()
        return self._SYRINGE_VOLUMES_ML.get(name, float(self.custom_syringe_volume_ml.value()))

    def _flush_settings(self, *, experiment: bool = False) -> FlushSettings:
        syringe_volume_ml = self._syringe_volume_ml()
        if experiment:
            return FlushSettings(
                flush_flowrate=self.exp_flush_flowrate.value(),
                flush_volume_ml=self.exp_flush_volume.value(),
                wait_after_flush_s=self.exp_wait_after_flush.value(),
                syringe_volume_ml=syringe_volume_ml,
            )
        return FlushSettings(
            flush_flowrate=self.flush_flowrate.value(),
            flush_volume_ml=self.flush_volume.value(),
            wait_after_flush_s=self.wait_after_flush.value(),
            syringe_volume_ml=syringe_volume_ml,
        )

    def _start_initialize(self) -> None:
        self._seed_experiment_ad2_from_wfg_once()
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
        flow_rate = self.flow_rate.value()
        self._run_action(lambda progress: self.app.pump.set_fill_level(level, flow_rate), "Setting pump level")

    def _start_reference_move(self) -> None:
        answer = QMessageBox.question(
            self,
            "Confirm Reference Move",
            "This will run the pump's reference/calibration move. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._run_action(lambda progress: self.app.pump.reference_move(), "Reference move")

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
        sequence_settings = self._camera_sequence_settings()
        self._run_action(
            lambda progress: self._configure_camera(roi, exposure_ms, center, sequence_settings),
            "Configuring Camera",
        )

    def _camera_sequence_settings(self) -> dict[str, object]:
        return {
            "masterpulse_mode": self.sequence_mode.currentText(),
            "masterpulse_source": self.sequence_source.currentText(),
            "masterpulse_interval_s": self.sequence_interval.value(),
            "masterpulse_burst_times": self.sequence_burst.value(),
            "frames": self.sequence_frames.value(),
            "trigger_source": self.dcam_source.currentText(),
            "trigger_polarity": self.external_polarity.currentText(),
            "trigger_delay_s": self.external_delay.value(),
        }

    def _configure_camera(self, roi: SubRegion, exposure_ms: float, center: bool, sequence_settings: dict[str, object] | None = None) -> str:
        self.app.camera.configure_exposure_time(exposure_ms)
        self.app.camera.configure_roi(roi)
        self.app.camera.configure_sequence(sequence_settings)
        if center:
            self.app.camera.center_roi()
        return "Camera configured"

    def _start_save_sequence(self) -> None:
        folder = Path(self.sequence_path.text() or ".")
        self._run_action(lambda progress: self._save_sequence(folder), "Saving sequence")

    def _save_sequence(self, folder: Path) -> str:
        if self._last_camera_image_data is None:
            return "No image captured yet"
        self.app.camera.save_sequence(self._last_camera_image_data, folder)
        return "Sequence saved"

    def _start_capture_camera_image(self) -> None:
        self._ensure_camera_preview()
        self._run_action(lambda progress: self._capture_camera_image(progress), "Capturing image")

    def _capture_camera_image_continuous(self) -> None:
        if not self._camera_preview_active or not self.image_continuous.isChecked():
            self._camera_preview_timer.stop()
            return
        if self._busy_count:
            return
        self._ensure_camera_preview()
        self._run_action(lambda progress: self._capture_camera_image(progress), "Capturing image")

    def _set_image_continuous(self, checked: bool) -> None:
        if checked:
            self._ensure_camera_preview()
            self._camera_preview_timer.start()
            self._capture_camera_image_continuous()
        else:
            self._camera_preview_timer.stop()

    def _ensure_camera_preview(self) -> ImagePreviewWindow:
        self._camera_preview_active = True
        should_show = False
        if self._camera_preview is None:
            self._camera_preview = ImagePreviewWindow(self)
            self._camera_preview.closed.connect(self._camera_preview_closed)
            should_show = True
        elif not self._camera_preview.isVisible():
            should_show = True
        if should_show:
            self._camera_preview.show()
            self._camera_preview.raise_()
        return self._camera_preview

    def _camera_preview_closed(self) -> None:
        self._camera_preview_active = False
        self._camera_preview = None
        self._camera_preview_timer.stop()
        if self.image_continuous.isChecked():
            self.image_continuous.blockSignals(True)
            self.image_continuous.setChecked(False)
            self.image_continuous.blockSignals(False)

    def _conversion_policy(self) -> tuple[str, int]:
        return self.conversion_method.currentText(), self.conversion_shifts.value()

    def _update_conversion_controls(self) -> None:
        method = self.conversion_method.currentText()
        dynamic_range = method in {"Full Dynamic", "90% Dynamic"}
        self.conversion_min.setReadOnly(True)
        self.conversion_max.setReadOnly(True)
        self.conversion_min.setEnabled(dynamic_range)
        self.conversion_max.setEnabled(dynamic_range)
        self.conversion_shifts.setEnabled(method == "Downshift")

    def _set_conversion_range(self, display_range: tuple[float, float] | None) -> None:
        if display_range is None:
            return
        minimum, maximum = display_range
        self.conversion_min.setValue(float(minimum))
        self.conversion_max.setValue(float(maximum))

    def _adjust_camera_preview(self) -> None:
        if not self._last_camera_image_data:
            self._set_status("No image captured yet")
            return
        self._ensure_camera_preview()
        method, shifts = self._conversion_policy()
        try:
            display_range = self._camera_preview.show_frame(
                np.asarray(self._last_camera_image_data[-1]),
                method=method,
                shifts=shifts,
            )
            self._set_conversion_range(display_range)
            self._set_status("Image intensity adjusted")
        except Exception as exc:
            self._camera_preview.show_message(f"Capture display failed: {exc}")
            self._set_status("Image intensity adjustment failed")

    def _show_camera_preview(self, image: object) -> None:
        if not self._camera_preview_active or self._camera_preview is None:
            return
        preview = self._camera_preview
        method, shifts = self._conversion_policy()
        try:
            display_range = preview.show_frame(np.asarray(image), method=method, shifts=shifts)
            self._set_conversion_range(display_range)
        except Exception as exc:
            preview.show_message(f"Capture display failed: {exc}")

    def _show_camera_capture_failed(self) -> None:
        if not self._camera_preview_active or self._camera_preview is None:
            return
        self._camera_preview.show_message("Capture failed")

    def _capture_camera_image(self, progress=None) -> object:
        image = self.app.camera.capture_snapshot()
        if image is None:
            self._last_camera_image_data = None
            if progress:
                progress("camera_capture_failed", "Capture failed")
            return "Capture failed"
        self._last_camera_image_data = [image]
        if progress:
            progress("camera_image", image)
        return image

    def _start_experiment(self) -> None:
        series_path = Path(self.series_path.text())
        if self._series_path_has_existing_data(series_path):
            answer = QMessageBox.question(
                self,
                "Confirm Overwrite",
                f"The series path already contains experiment data:\n{series_path}\n\n"
                "Continuing will overwrite existing data.tdms/frame files. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        series, total_frames, config = self._build_experiment_series()
        self.queue_count.setText(str(series.see_elements_left()))
        self.waveform_graph.set_points(self._preview_points(config))
        self._run_action(
            lambda progress: self._run_experiment_series(series, total_frames, config, progress),
            "Running experiment",
        )

    @staticmethod
    def _series_path_has_existing_data(series_path: Path) -> bool:
        if not series_path.exists():
            return False
        return any(series_path.rglob("data.tdms")) or any(series_path.rglob("frame_*.tiff"))

    def _build_experiment_series(self) -> tuple[ExperimentSeries2, int, WfgConfig]:
        repeats = self.exp_repeats.value()
        frequency_scan_hz: list[float] | None = None
        if self.exp_freq_scan_enable.isChecked():
            frequency_scan_hz = self._experiment_frequency_scan_list_hz()
            if len(frequency_scan_hz) != repeats:
                raise ValueError(
                    f"Frequency Scanning is enabled with {len(frequency_scan_hz)} frequencies "
                    f"(Number of Frequencies) but Repeats is set to {repeats}; they must match "
                    "before starting this experiment."
                )
        fm_sweep = self._experiment_fm_sweep_settings() if self.exp_sweep_enable.isChecked() else None
        started_at = time.monotonic()
        _ = started_at
        experiments = []
        preview_config: WfgConfig | None = None
        for repeat in range(repeats):
            # WFG config is built fresh per repeat (like _experiment_do_clock_config(repeat)
            # below) rather than once outside this loop -- required for Frequency Scanning's
            # per-repeat Ch1 frequency substitution to actually differ between repeats; with
            # Frequency Scanning off this produces the same values every repeat, just as a
            # single shared config object did before.
            config = self._experiment_wfg_config(
                frequency_override_hz=frequency_scan_hz[repeat] if frequency_scan_hz is not None else None
            )
            if preview_config is None:
                preview_config = config
            folder = Path(self.series_path.text()) / f"repeat_{repeat + 1:03d}"
            experiments.append(
                Experiment2(
                    repeat_id=repeat,
                    experiment_folder=folder,
                    flush_settings=self._flush_settings(experiment=True),
                    flush_enabled=self.exp_flush_enabled.isChecked(),
                    global_exposure_ms=self.exp_exposure_ms.value(),
                    trigger_global_exposure=self.global_exposure.isChecked(),
                    sequence_settings={
                        # Start from the manual Camera tab's own sequence settings so
                        # masterpulse_mode/masterpulse_source/masterpulse_interval_s/
                        # masterpulse_burst_times/trigger_polarity/trigger_delay_s --
                        # which have no separate Experiment-tab controls -- carry
                        # through to the automated path every run instead of being
                        # silently omitted, matching RunExperiment2.vi's own behavior
                        # of always applying the whole SequenceSettings cluster.
                        **self._camera_sequence_settings(),
                        "frames": self.exp_frames.value(),
                        "camera_start_s": [widget.value() for widget in self.camera_start_array],
                        # Explicit and deterministic so experiment runs never inherit
                        # whatever trigger source a prior manual Camera tab session left
                        # the DCAM device in. Whether this should be "External" (paced by
                        # the AD2 DIO pulse train, matching the DIO0/DIO1-triggered
                        # transducer and LED) instead of "Internal" is still an open
                        # question pending oscilloscope verification -- this only removes
                        # the undefined-leftover-state risk, it does not answer that.
                        "trigger_source": "Internal",
                    },
                    wfg_config=config,
                    do_clock_settings=self._experiment_do_clock_config(repeat),
                    fm_sweep=fm_sweep,
                )
            )
        return ExperimentSeries2(Path(self.series_path.text()), experiments), self.exp_frames.value() * repeats, preview_config

    def _experiment_do_clock_config(self, repeat_index: int) -> DoConfig:
        camera_fps = float(self.exp_camera_fps.value())
        if camera_fps <= 0:
            raise ValueError("Camera FPS must be greater than 0 to derive the AD2 DIO1 LED clock.")
        frames = int(self.exp_frames.value())
        if self.dynamic_camera_start.isChecked():
            if repeat_index >= len(self.camera_start_array):
                raise ValueError("Dynamic Camera Start Time has more repeats than Camera Start Array entries.")
            camera_start_s = float(self.camera_start_array[repeat_index].value())
        else:
            camera_start_s = float(self.exp_camera_start.value())
        # LabVIEW CreateExperiments only wires DO secRun/secWait. Repeat count,
        # repeat-trigger, and trigger source intentionally remain AD2 SDK defaults.
        trigger = TriggerSettings(sec_run=frames / camera_fps, sec_wait=camera_start_s)
        return DoConfig(
            running=True,
            channels=[
                DoSingleChannelConfig(
                    channel_index=1,
                    enable=True,
                    clock_frequency_hz=camera_fps,
                    output_type=DigitalOutType.PULSE,
                    output_mode="PushPull",
                    idle_state=DigitalOutIdleState.INITIAL,
                    counter_high_bits=1,
                    counter_low_bits=1,
                    counter_initial_bits=0,
                    start_high=True,
                    trigger=trigger,
                )
            ],
        )

    def _run_experiment_series(
        self,
        series: ExperimentSeries2,
        total_frames: int,
        config: WfgConfig,
        progress=None,
    ) -> str:
        started_at = time.monotonic()
        self.app.set_experiment_series_general(series)
        # Clear any abort flag left over from a previous run before starting
        # this one, so a fresh "Start exp" click isn't immediately treated as
        # already-aborted.
        self.app.create_stop_event()
        if progress:
            progress("queue_count", self.app.experiment_series.see_elements_left())
            progress("waveform", self._preview_points(config))
        repeat_index = 0
        while self.app.experiment_series.see_elements_left():
            if self.app.stop_fired:
                # Abort was triggered (qt_ui.py:_abort()). The in-progress
                # repeat, if any, has already run to completion or been
                # disrupted by _abort_hardware()'s concurrent hardware stop --
                # we deliberately do not attempt to interrupt a repeat that is
                # mid-flight (camera/AD2/pump/valve state is safer left to
                # finish or fail on its own than cut off partway through a
                # flush or capture). What this check guarantees is that no
                # *further* queued repeat starts after Abort was pressed.
                remaining = self.app.experiment_series.see_elements_left()
                logger.info(
                    f"Experiment series stopped after {repeat_index} repeat(s): Abort was triggered; "
                    f"{remaining} repeat(s) remain queued and will not run."
                )
                self.app.fire_status_event("ExperimentSeriesAborted")
                if progress:
                    progress("queue_count", remaining)
                return "ExperimentSeriesAborted"
            completed = self.app.run_experiment2()
            repeat_index += 1
            if progress:
                progress("queue_count", self.app.experiment_series.see_elements_left())
                progress("status", self.app.status)
            if not completed:
                message = (
                    f"Experiment series stopped at repeat {repeat_index}: "
                    f"run_experiment2 did not complete (status={self.app.status!r})."
                )
                logger.error(message)
                raise RuntimeError(message)
        elapsed = max(time.monotonic() - started_at, 0.001)
        if progress:
            fps = total_frames / elapsed
            progress("average_fps", f"{fps:.2f}")
        return "ExperimentComplete"

    def _experiment_wfg_config(self, frequency_override_hz: float | None = None) -> WfgConfig:
        return WfgConfig(
            running=any(state["enable"].isChecked() for state in self.exp_ad2_channels),
            channels=[
                self._experiment_channel_config(
                    0, self.exp_ad2_channels[0], frequency_override_hz=frequency_override_hz
                ),
                self._experiment_channel_config(1, self.exp_ad2_channels[1]),
            ],
            # Not sourced from a live control: the manual WFG tab's own
            # self.wfg_sync widget is disabled ("Not implemented:
            # SynchronizeState is currently a non-functional stub") because
            # WaveFormsBackend.configure_wfg() never calls FDwfAnalogOutMasterSet
            # -- synchronize_state has no real hardware effect anywhere in this
            # codebase, manual or automated. Matches the manual tab's own default.
            synchronize_state="Independent",
        )

    def _browse_folder(self, target: QLineEdit) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Select folder", target.text() or str(Path.cwd()))
        if selected:
            target.setText(selected)

    def _abort(self) -> None:
        self.app.fire_stop_event()
        self._run_action(
            lambda progress: self._abort_hardware(),
            "Aborting...",
            force=True,
            timeout_s=10.0,
            disable_controls=True,
        )

    def _abort_hardware(self) -> str:
        errors: list[str] = []
        for name, action in (
            ("pump stop", self.app.pump.stop),
            ("camera stop_capture", self.app.camera.stop_capture),
            ("AD2 WFG stop", lambda: self.app.ad2.wfg_start_stop_all_ch(False)),
        ):
            try:
                action()
            except Exception as exc:  # pragma: no cover - hardware failure path
                message = f"{name} failed during abort: {exc}"
                self.app.check_loop_error(message)
                errors.append(message)
        if errors:
            raise RuntimeError("; ".join(errors))
        return "Aborted"

    def _exit_app(self) -> None:
        self._start_shutdown(close_after=True)

    def _start_shutdown(self, *, close_after: bool) -> None:
        if self._shutdown_in_progress:
            self._close_after_shutdown = self._close_after_shutdown or close_after
            self._set_status("Shutdown already in progress")
            return
        self._shutdown_in_progress = True
        self._close_after_shutdown = close_after
        self.app.fire_stop_event()
        self._set_status("Shutting down...")
        self._set_controls_enabled(False)
        self._shutdown_result_queue = queue.Queue(maxsize=1)

        def run_cleanup() -> None:
            try:
                self.app.cleanup()
            except Exception as exc:  # pragma: no cover - hardware cleanup failure path
                self._shutdown_result_queue.put((False, "Error", str(exc)))
            else:
                self._shutdown_result_queue.put((True, "System Not Initialized", ""))

        self._shutdown_thread = threading.Thread(target=run_cleanup, name="hardware-shutdown", daemon=True)
        self._shutdown_thread.start()
        self._shutdown_poll_timer.start(50)
        self._shutdown_timeout_timer.start(max(int(self._shutdown_timeout_s * 1000), 1))

    def _poll_shutdown_cleanup(self) -> None:
        if self._shutdown_result_queue is None:
            return
        try:
            ok, status, error = self._shutdown_result_queue.get_nowait()
        except queue.Empty:
            return
        self._shutdown_poll_timer.stop()
        self._shutdown_timeout_timer.stop()
        self._handle_shutdown_finished(ok, status, error)

    def _handle_shutdown_timeout(self) -> None:
        message = f"Shutdown timed out after {self._shutdown_timeout_s:.1f}s; forcing window close."
        self.app.check_loop_error(message)
        self.error_status.setText("ERROR")
        self.error_code.setText("1")
        self.error_source.setText(message)
        self._set_status(message)
        self._shutdown_poll_timer.stop()
        self._handle_shutdown_finished(False, "Error", message, force_close=True)

    def _run_action(
        self,
        action,
        starting_status: str,
        *,
        force: bool = False,
        timeout_s: float | None = None,
        disable_controls: bool = False,
        shutdown: bool = False,
    ) -> None:
        if self._busy_count and not force:
            self._set_status("Busy")
            return
        self._busy_count += 1
        self._set_status(starting_status)
        if disable_controls:
            self._set_controls_enabled(False)
        thread = QThread(self)
        worker = ActionWorker(action)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._handle_worker_progress)
        worker.finished.connect(
            lambda ok, status, error, thread=thread, shutdown=shutdown: self._handle_worker_finished_for_thread(
                thread,
                ok,
                status,
                error,
                shutdown=shutdown,
            )
        )
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(lambda: self._threads.remove(thread) if thread in self._threads else None)
        thread.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)
        thread.finished.connect(thread.deleteLater)
        self._threads.append(thread)
        self._workers.append(worker)
        if timeout_s is not None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda: self._handle_action_timeout(thread, starting_status, timeout_s))
            worker.finished.connect(timer.stop)
            worker.finished.connect(timer.deleteLater)
            timer.start(max(int(timeout_s * 1000), 1))
        thread.start()

    def _set_controls_enabled(self, enabled: bool) -> None:
        self._controls_disabled_for_action = not enabled
        widget = self.centralWidget()
        if widget is not None:
            widget.setEnabled(enabled)

    def _handle_action_timeout(self, thread: QThread, starting_status: str, timeout_s: float) -> None:
        if not thread.isRunning():
            return
        message = f"{starting_status} timed out after {timeout_s:.1f}s; hardware worker is still running."
        self._timed_out_threads[thread] = message
        self.app.check_loop_error(message)
        self.error_status.setText("ERROR")
        self.error_code.setText("1")
        self.error_source.setText(message)
        self._set_status(message)

    def _handle_worker_finished_for_thread(
        self,
        thread: QThread,
        ok: bool,
        status: str,
        error: str,
        *,
        shutdown: bool,
    ) -> None:
        timeout_error = self._timed_out_threads.pop(thread, None)
        effective_ok = ok and timeout_error is None
        effective_status = status
        effective_error = error
        if timeout_error is not None:
            effective_status = "Error"
            effective_error = timeout_error if ok else f"{timeout_error}; worker later failed: {error}"
        self._handle_worker_finished(effective_ok, effective_status, effective_error)
        if shutdown:
            self._handle_shutdown_finished(effective_ok, effective_status, effective_error)

    def _handle_shutdown_finished(self, ok: bool, status: str, error: str, *, force_close: bool = False) -> None:
        self._shutdown_in_progress = False
        if ok:
            self.error_status.setText("OK")
            self.error_code.setText("0")
            self.error_source.setText("")
            self._set_status(status)
        else:
            self.error_status.setText("ERROR")
            self.error_code.setText("1")
            self.error_source.setText(error)
            self._set_status("Error")
        if (ok or force_close) and self._close_after_shutdown:
            self._cleanup_complete_for_close = True
            self.close()
        elif not ok:
            self._close_after_shutdown = False
        if self._busy_count == 0 and self._controls_disabled_for_action and not self._shutdown_in_progress:
            self._set_controls_enabled(True)

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
        elif kind == "camera_image":
            self._show_camera_preview(value)
        elif kind == "camera_capture_failed":
            self._show_camera_capture_failed()

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
        if self._busy_count == 0 and self._controls_disabled_for_action and not self._shutdown_in_progress:
            self._set_controls_enabled(True)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API name
        self._window_was_shown = True
        super().showEvent(event)

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
            # Bumped from the implicit version-1 (unversioned) format in the
            # session that switched WFG/Experiment carrier frequency fields
            # from Hz to kHz -- see the legacy-scaling branch in
            # _load_settings() that upgrades files saved without this key.
            "schema_version": 2,
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
                "ch1_offset": self.exp_ch1_offset.value(),
                "ch1_function": self.exp_ch1_function.currentText(),
                "ch1_enable": self.exp_ch1_enable.isChecked(),
                "ch1_start": self.exp_ch1_start.value(),
                "ch1_run": self.exp_ch1_run.value(),
                "ch1_repeat": self.exp_ch1_repeat.value(),
                "ch1_trigger_source": self.exp_ch1_trigger_source.currentText(),
                "ch1_symmetry": self.exp_ch1_symmetry.value(),
                "ch1_phase": self.exp_ch1_phase.value(),
                "ch1_repeat_trigger": self.exp_ch1_repeat_trigger.isChecked(),
                "ch2_frequency": self.exp_ch2_freq.value(),
                "ch2_amplitude": self.exp_ch2_amp.value(),
                "ch2_offset": self.exp_ch2_offset.value(),
                "ch2_function": self.exp_ch2_function.currentText(),
                "ch2_enable": self.exp_ch2_enable.isChecked(),
                "ch2_start": self.exp_ch2_start.value(),
                "ch2_run": self.exp_ch2_run.value(),
                "ch2_repeat": self.exp_ch2_repeat.value(),
                "ch2_trigger_source": self.exp_ch2_trigger_source.currentText(),
                "ch2_symmetry": self.exp_ch2_symmetry.value(),
                "ch2_phase": self.exp_ch2_phase.value(),
                "ch2_repeat_trigger": self.exp_ch2_repeat_trigger.isChecked(),
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
        legacy_hz_scale = data.get("schema_version", 1) < 2
        if legacy_hz_scale:
            # Pre-version-2 files were saved before WFG/Experiment carrier
            # frequency fields switched from Hz to kHz; the raw numbers are
            # still Hz-scale, so scale them down once to match the now-kHz
            # widgets they're about to be loaded into.
            for item in data.get("wfg", []):
                if "frequency" in item:
                    item["frequency"] = item["frequency"] / 1000.0
            experiment_legacy = data.get("experiment")
            if isinstance(experiment_legacy, dict):
                for key in ("ch1_frequency", "ch2_frequency"):
                    if key in experiment_legacy:
                        experiment_legacy[key] = experiment_legacy[key] / 1000.0
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
                "ch1_offset": self.exp_ch1_offset,
                "ch1_start": self.exp_ch1_start,
                "ch1_run": self.exp_ch1_run,
                "ch1_repeat": self.exp_ch1_repeat,
                "ch1_symmetry": self.exp_ch1_symmetry,
                "ch1_phase": self.exp_ch1_phase,
                "ch2_frequency": self.exp_ch2_freq,
                "ch2_amplitude": self.exp_ch2_amp,
                "ch2_offset": self.exp_ch2_offset,
                "ch2_start": self.exp_ch2_start,
                "ch2_run": self.exp_ch2_run,
                "ch2_repeat": self.exp_ch2_repeat,
                "ch2_symmetry": self.exp_ch2_symmetry,
                "ch2_phase": self.exp_ch2_phase,
                "flush_flowrate": self.exp_flush_flowrate,
                "flush_volume": self.exp_flush_volume,
                "wait_after_flush": self.exp_wait_after_flush,
            }
            for key, widget in mapping.items():
                if key in experiment:
                    widget.setValue(experiment[key])
            for key, widget in (
                ("ch1_function", self.exp_ch1_function),
                ("ch1_trigger_source", self.exp_ch1_trigger_source),
                ("ch2_function", self.exp_ch2_function),
                ("ch2_trigger_source", self.exp_ch2_trigger_source),
            ):
                if key in experiment:
                    _set_combo_text(widget, str(experiment[key]))
            for key, widget in (
                ("ch1_enable", self.exp_ch1_enable),
                ("ch2_enable", self.exp_ch2_enable),
                ("ch1_repeat_trigger", self.exp_ch1_repeat_trigger),
                ("ch2_repeat_trigger", self.exp_ch2_repeat_trigger),
            ):
                if key in experiment:
                    widget.setChecked(bool(experiment[key]))
            if "flush_enabled" in experiment:
                self.exp_flush_enabled.setChecked(bool(experiment["flush_enabled"]))
            if any(
                key in experiment
                for key in (
                    "ch1_frequency",
                    "ch1_amplitude",
                    "ch1_offset",
                    "ch1_function",
                    "ch1_enable",
                    "ch1_start",
                    "ch1_run",
                    "ch1_repeat",
                    "ch1_trigger_source",
                    "ch1_symmetry",
                    "ch1_phase",
                    "ch1_repeat_trigger",
                    "ch2_frequency",
                    "ch2_amplitude",
                    "ch2_offset",
                    "ch2_function",
                    "ch2_enable",
                    "ch2_start",
                    "ch2_run",
                    "ch2_repeat",
                    "ch2_trigger_source",
                    "ch2_symmetry",
                    "ch2_phase",
                    "ch2_repeat_trigger",
                )
            ):
                self._experiment_ad2_seeded = True
        if legacy_hz_scale:
            self._set_status(
                "Settings loaded (legacy file: WFG/Experiment carrier frequencies "
                "auto-converted from Hz to kHz -- verify values before running)"
            )
        else:
            self._set_status("Settings loaded")

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API name
        if not self._cleanup_complete_for_close:
            if not self._window_was_shown:
                try:
                    self.app.cleanup()
                except Exception as exc:  # pragma: no cover - hidden-window teardown path
                    self.app.check_loop_error(exc)
                    self.error_status.setText("ERROR")
                    self.error_code.setText("1")
                    self.error_source.setText(str(exc))
                self._cleanup_complete_for_close = True
            else:
                event.ignore()
                self._start_shutdown(close_after=True)
                return
        self._camera_preview_active = False
        self._camera_preview_timer.stop()
        if self._camera_preview is not None:
            self._camera_preview.close()
            self._camera_preview = None
        self._save_settings()
        self._cleanup_complete_for_close = False
        super().closeEvent(event)


# Standalone entry point for the day-to-day application (see tools/run_ui.py
# and launch_gui.bat). qt_ui_v2.MainWindowV2 subclasses MainWindow and reuses
# its tab-building methods (WFG, MSO, Pump&Valve, Camera) as sidebar dialogs,
# but is an in-development preview and not yet the default launch target.
def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
