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
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QPlainTextEdit,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QToolButton,
    QToolTip,
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


# A systematic offscreen sweep (Session 38) found nearly every QDoubleSpinBox
# in the app had a real sizeHint() up to 252px while capped at
# setMaximumWidth(125) -- about half the width actually needed, so a value
# like "1900.000" rendered as "1900." (the trailing digits had nowhere to
# go). 260px comfortably covers every sizeHint measured across every tab at
# the time of that sweep, with a small margin.
_SPIN_MAX_WIDTH = 260


def _spin(value: float = 0.0, *, decimals: int = 3, minimum: float = -1e12, maximum: float = 1e12) -> QDoubleSpinBox:
    widget = QDoubleSpinBox()
    widget.setDecimals(decimals)
    widget.setRange(minimum, maximum)
    widget.setValue(value)
    widget.setKeyboardTracking(False)
    widget.setMaximumWidth(_SPIN_MAX_WIDTH)
    return widget


def _int_spin(value: int = 0, *, minimum: int = -1_000_000, maximum: int = 1_000_000) -> QSpinBox:
    widget = QSpinBox()
    widget.setRange(minimum, maximum)
    widget.setValue(value)
    widget.setKeyboardTracking(False)
    widget.setMaximumWidth(_SPIN_MAX_WIDTH)
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


class _TooltipIconButton(QToolButton):
    """Small "ⓘ" marker placed next to a field that has a tooltip
    (Session 41, Part 2 -- replaces Session 40's label-underline marker).
    Deliberately click-triggered, not hover-triggered (explicit user
    confirmation): no native Qt tooltip is set on this button itself, so
    hovering it alone shows nothing -- only an actual click calls
    QToolTip.showText() to display the explanation, reusing Qt's own
    tooltip rendering (auto-wrap, native look, dismisses when the mouse
    leaves the button's area) rather than inventing a new popup widget."""

    def __init__(self, explanation: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText("ⓘ")
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.setAutoRaise(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedSize(18, 18)
        self._explanation = explanation
        self.clicked.connect(self._show_explanation)

    def _show_explanation(self) -> None:
        QToolTip.showText(self.mapToGlobal(self.rect().bottomLeft()), self._explanation, self)


class _TooltipIconWrapper(QWidget):
    """Marker container class (not just a bare QWidget) so tests/tooling can
    reliably recognize "this widget's parent is a tooltip-icon wrapper" via
    isinstance() instead of guessing from layout contents -- holds exactly
    one field widget plus one _TooltipIconButton, built by
    MainWindow._wrap_with_tooltip_icon()."""


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


class HistoryLogWidget(QListWidget):
    """Append-only, timestamped history log for Status / Error Out.

    Replaces a single-value display that a later message would silently
    overwrite. `add_entry()` is the only write API -- deliberately not
    named `setText()`, since "append a new row" and "replace the
    displayed text" are different operations and conflating them would
    be misleading to a future reader. Consecutive entries with identical
    text are deduped (compared on the raw message, not the timestamped
    display string), since several existing call sites -- e.g.
    `_handle_worker_finished()`'s "OK" branch, `_safe_call()`'s success
    path -- re-report the same status/error state on every successful
    action, not just on a genuine change; without dedup this would
    flood the log with redundant identical rows on every button click.
    Auto-scrolls to the newest entry only when the view was already at
    (or near) the bottom before the entry was added -- if the user has
    scrolled up to review history, a new entry does not yank the view
    back down.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def add_entry(self, text: str) -> None:
        if self.count() > 0 and self.item(self.count() - 1).data(Qt.ItemDataRole.UserRole) == text:
            return
        at_bottom = self._is_scrolled_to_bottom()
        timestamp = time.strftime("%H:%M:%S", time.localtime())
        item = QListWidgetItem(f"[{timestamp}] {text}")
        item.setData(Qt.ItemDataRole.UserRole, text)
        self.addItem(item)
        if at_bottom:
            self.scrollToBottom()

    def latest_text(self) -> str:
        if self.count() == 0:
            return ""
        return str(self.item(self.count() - 1).data(Qt.ItemDataRole.UserRole))

    def _is_scrolled_to_bottom(self) -> bool:
        bar = self.verticalScrollBar()
        return self.count() == 0 or bar.value() >= bar.maximum() - 2


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
        # Tracks whether _run_experiment_series()'s while loop is currently
        # executing (set/cleared via the "experiment_series_active" progress
        # kind below, not read directly from a worker thread -- see
        # _run_experiment_series()). Distinct from `self.app.status` string
        # matching, which qt_ui_v2.py's "Experiment running" indicator used
        # to rely on and which was found to go stale the instant Abort is
        # clicked (its own "Aborting..." status overwrites app.status while
        # the series' current repeat may still genuinely be in flight).
        self._experiment_series_active = False
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
        # Checked once per position inside ZScanCalibration.run() (Phase 4) --
        # set True by _abort_zscan(), reset False at the start of each new
        # _start_zscan() call.
        self._zscan_abort_requested = False

        self._build_state()
        self._build_layout()
        self._load_settings()
        self._refresh_status()

    def _build_state(self) -> None:
        hardware_defaults = default_hardware_config()
        # Enable/Simulate pairing (Session 40, Category B): traced
        # hardware_factory.build_hardware_bundle() -- each instrument's own
        # Enable checkbox and its matching Simulate checkbox are independent
        # but combine: Enable=Off skips the instrument entirely regardless of
        # Simulate; Enable=On + Simulate=On builds a fake in-memory backend
        # (SimulatedAD2Sdk / HamamatsuCamera(simulate=True) / etc., safe, no
        # real hardware touched); Enable=On + Simulate=Off builds the real
        # hardware backend (AD2Sdk / HamamatsuDcamBackend / QmixPumpBackend /
        # SerialTextCommandBackend) and genuinely opens/writes to the device
        # on Initialize. Both tooltips name the other explicitly since
        # forgetting to check Simulate before Initialize is the single
        # easiest way to accidentally drive real hardware from this tab.
        enable_tip_template = (
            "Whether {name} is included at all when Initialize is clicked. Off skips it entirely, "
            "regardless of the matching Simulate checkbox below/right. On + Simulate=On builds a "
            "safe in-memory fake backend; On + Simulate=Off builds the real hardware backend and "
            "genuinely opens/writes to the device."
        )
        simulate_tip_template = (
            "Only matters when {name} above/left is On. Checked = safe in-memory fake backend, no "
            "real hardware touched. Unchecked = the real hardware backend is built and Initialize "
            "genuinely opens/writes to the device."
        )
        self.ad2_enabled = QCheckBox("Off/On")
        self.ad2_enabled.setChecked(True)
        self.ad2_enabled.setToolTip(enable_tip_template.format(name="Analog Discovery"))
        self.z_enabled = QCheckBox("Off/On")
        self.z_enabled.setToolTip(
            "Whether the Z stage is included at all when Initialize is clicked -- there is no "
            "matching Simulate checkbox for Z stage (only AD2/Camera/Pump/Valve have one); when On, "
            "hardware_factory.build_hardware_bundle() always builds a real Prior-serial backend "
            "(see prior_resource's own tooltip -- Z stage backend selection has no real effect)."
        )
        self.camera_enabled = QCheckBox("Off/On")
        self.camera_enabled.setChecked(True)
        self.camera_enabled.setToolTip(enable_tip_template.format(name="the Hamamatsu camera"))
        self.pump_enabled = QCheckBox("Off/On")
        self.pump_enabled.setChecked(True)
        self.pump_enabled.setToolTip(enable_tip_template.format(name="the Cetoni pump"))
        self.valve_enabled = QCheckBox("Off/On")
        self.valve_enabled.setChecked(True)
        self.valve_enabled.setToolTip(enable_tip_template.format(name="the MX valve"))
        self.sim_camera = QCheckBox("Off/On")
        self.sim_camera.setChecked(True)
        self.sim_camera.setToolTip(simulate_tip_template.format(name="Hamamatsu"))
        self.sim_pump = QCheckBox("Off/On")
        self.sim_pump.setChecked(True)
        self.sim_pump.setToolTip(simulate_tip_template.format(name="Cetoni Pump"))
        self.sim_valve = QCheckBox("Off/On")
        self.sim_valve.setChecked(True)
        self.sim_valve.setToolTip(simulate_tip_template.format(name="MX Valve"))
        self.sim_ad2 = QCheckBox("Off/On")
        self.sim_ad2.setChecked(True)
        self.sim_ad2.setToolTip(simulate_tip_template.format(name="Analog Discovery 3"))

        self.z_backend = _combo([item.value for item in ZStageBackend], hardware_defaults.z_stage.backend.value)
        self.prior_resource = QLineEdit(hardware_defaults.z_stage.prior_resource)
        self.prior_resource.setToolTip(
            "The real VISA/COM resource for the Prior Z-motor controller; passed to "
            "HardwareRuntimeConfig and genuinely used, unlike the disabled Z stage backend/"
            "Thorlabs fields above. Traced hardware_factory.build_hardware_bundle(): checking "
            "'Z stage' always builds a Prior-serial Z-motor when enabled, regardless of what "
            "the (unwired) Z stage backend combo shows -- selecting 'thorlabs_apt' there has no "
            "effect on which backend is actually built. Low current risk only because this path "
            "is separately documented as legacy/obsolete (Session 18) -- current Z hardware is "
            "Thorlabs/APT, which has no real backend at all yet."
        )
        self.thorlabs_apt_serial = QLineEdit(hardware_defaults.z_stage.thorlabs_apt_serial)
        self.thorlabs_apt_backend = QLineEdit(hardware_defaults.z_stage.thorlabs_apt_backend)
        self.thorlabs_apt_discovery_only = QCheckBox("Discovery only")
        self.thorlabs_apt_discovery_only.setChecked(hardware_defaults.z_stage.thorlabs_apt_discovery_only)
        self.valve_resource = QLineEdit("COM5")  # real-hardware-confirmed default -- see Valve.visa_resource (instruments.py)
        # Relocated here from _instrument_group() (Session 40): that method
        # is v1-tab-only -- qt_ui_v2.py's InitializationDialog builds its own
        # separate form around this same widget without ever calling
        # _instrument_group(), so a tooltip set there never reached v2 users
        # at all. Every other tooltip in this codebase lives in _build_state()
        # for exactly this reason (guaranteed to apply regardless of which
        # UI's layout method runs).
        self.valve_resource.setToolTip(
            "The real COM port; passed to HardwareRuntimeConfig and genuinely used, unlike the "
            "disabled Z stage backend/Thorlabs/Qmix path fields on this same tab."
        )
        self.qmix_sdk_python_path = QLineEdit(str(hardware_defaults.qmix.sdk_python_path))
        self.qmix_qmixsdk_path = QLineEdit(str(hardware_defaults.qmix.qmixsdk_path))
        self.cetoni_config_path = QLineEdit(str(hardware_defaults.qmix.config_path))
        # Relocated here from _instrument_group() for the same reason as
        # valve_resource above.
        self.cetoni_config_path.setToolTip(
            "Read by CetoniPump.initialize() -- genuinely used, unlike the Qmix SDK/QMIXSDK path "
            "fields above (Session 3: confirmed never read by hardware_factory.build_hardware_bundle())."
        )

        self.wfg_running = QCheckBox("ON")
        self.wfg_running.setChecked(True)
        self.wfg_running.setToolTip(
            "Master on/off for both WFG channels' real hardware output, applied by Apply WFG "
            "(WfgConfig.running -> ad2.wfg_start_stop_all_ch()). Each channel also has its own "
            "per-channel Enable checkbox below -- this is the shared master switch on top of those."
        )
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
        self.mso_trigger_source.setToolTip(
            "AD2 SDK trigger source enum for this scope capture -- what starts sampling. "
            "'None' captures immediately on Capture click with no external/PC trigger wait, "
            "matching the same trigsrcNone/trigsrcPC/etc. vocabulary the WFG tab's own Trigger "
            "source fields use."
        )
        self.mso_sample_frequency = _spin(10_000.0, decimals=1, minimum=1.0, maximum=100_000_000.0)
        self.mso_sample_frequency.setToolTip(
            "AD2 analog-in sample rate. 100 MS/s (the max above) is the Analog Discovery 2's "
            "published spec, but this has not been independently re-verified against this "
            "specific device (Session 18 audit: classified UNCONFIRMED, treat as a reasonable "
            "default, not a confirmed one). Combines with Sample Count to set the capture's real "
            "duration: duration_s = Sample Count / this value (_set_mso_stats())."
        )
        self.mso_sample_count = _int_spin(4096, minimum=1, maximum=1_000_000)
        self.mso_sample_count.setToolTip(
            "Number of samples captured per channel. Combines with Sample Frequency to set the "
            "capture's real duration: duration_s = this value / Sample Frequency (_set_mso_stats())."
        )
        self.mso_range = _spin(1.0, decimals=3, minimum=0.001, maximum=50.0)
        self.mso_range.setToolTip(
            "Analog-in voltage range. The 1 V default is below the documented real acoustic "
            "drive signal (up to 2 V on CH0) -- scoping at this default risks clipping "
            "(Session 18 audit: classified SUSPECTED-PLACEHOLDER). Widen before scoping CH0. "
            "Combines with Offset below to set the actual voltage window the ADC reads."
        )
        self.mso_offset = _spin(0.0, decimals=3, minimum=-50.0, maximum=50.0)
        self.mso_stats = QLabel("No capture")
        self.mso_samples: list[float] = []

        self.syringe = _combo(["BD 1ml", "BD 5ml", "BD 10ml", "Custom"], "BD 1ml")
        self.syringe.setToolTip(
            "BD inner diameters confirmed against BD's published spec (Session 17: "
            "1ml=4.78mm, 5ml=12.07mm, 10ml=14.5mm). Stroke length is a derived value "
            "(volume / cross-sectional area assuming full nominal volume over full piston "
            "travel), not an independently-sourced BD spec figure. 'Custom' has no known "
            "geometry of its own -- Configure Syringe sends the real Custom Inner Diameter/"
            "Max Piston Stroke fields below for it (Session 44), not a derived guess. This "
            "selection's nominal capacity (or Custom Volume, when 'Custom' is picked) is also "
            "what Flush Volume's own safety check is measured against (Application.flush(), "
            "Session 10)."
        )
        self.custom_syringe_volume_ml = _spin(1.0, decimals=3, minimum=0.001)
        # Task 4 investigation (Session 38): traced _syringe_volume_ml() --
        # this value is only ever read as a fallback when Syringe="Custom"
        # (ignored/inert for the three named BD presets, which have their
        # own known volumes). It feeds only the flush-volume-vs-syringe-
        # capacity safety check, never ConfigureSyringe's real geometry
        # call -- that is a deliberate, separate decision (Session 44): a
        # volume alone can't determine both inner diameter and stroke (an
        # infinite family of diameter/stroke pairs share the same volume),
        # so geometry is supplied explicitly via the two new fields below
        # instead of derived from this one. Disabled whenever a named
        # preset is active, matching this project's established
        # stub-marking convention, so its value can't be mistaken for
        # something currently being read.
        self.custom_syringe_volume_ml.setToolTip(
            "Only used when Syringe = 'Custom' (feeds the flush-volume-vs-syringe-capacity "
            "safety check in Application.flush()). Deliberately has no effect on the real "
            "syringe geometry Configure Syringe sends to the pump (Session 44) -- a volume "
            "alone can't determine both inner diameter and stroke length, so geometry is "
            "supplied explicitly via Custom Inner Diameter/Max Piston Stroke below instead."
        )
        # Range-constrained to the same conservative, plausible-syringe bounds
        # QmixPumpBackend.configure_syringe() itself now enforces (Session 51)
        # -- imported directly, not duplicated as separate literals, so the
        # two can't silently drift apart. No live device readback exists for
        # syringe geometry (unlike PiezoStage.max_travel_um), so these bounds
        # are the qmix_backend module's own hardcoded, documented values --
        # inner_diameter_mm from BD's published 1mL-60mL product-line range,
        # max_piston_stroke_mm from this specific pump module's own real
        # mechanical travel ceiling (CETONI Low Pressure Hardware Manual
        # Section 5.1, NEM-B101-02 E: "up to 65 mm", independent of whatever
        # syringe is mounted -- not a BD-range-derived estimate). Real-time
        # input constraint here is a UI-layer backstop in front of that same
        # hardcoded backend rejection, exactly mirroring the Z-scan tab's
        # [0, max_travel_um] pattern in spirit even though the underlying
        # limit here isn't itself live-read.
        from .qmix_backend import (
            MAX_SYRINGE_INNER_DIAMETER_MM,
            MAX_SYRINGE_STROKE_MM,
            MIN_SYRINGE_INNER_DIAMETER_MM,
            MIN_SYRINGE_STROKE_MM,
        )

        self.custom_syringe_inner_diameter_mm = _spin(
            4.78, decimals=3, minimum=MIN_SYRINGE_INNER_DIAMETER_MM, maximum=MAX_SYRINGE_INNER_DIAMETER_MM
        )
        self.custom_syringe_inner_diameter_mm.setToolTip(
            "Only used when Syringe = 'Custom'. The real inner (bore) diameter of the "
            "physical syringe, in mm -- sent directly to the Qmix SDK's set_syringe_param() "
            "as inner_diameter_mm (QmixPumpBackend.configure_syringe(), Session 44). Not "
            "derived from Custom Volume above; supply the syringe's actual spec value, the "
            "same way the three named BD presets use their own published inner diameters "
            "(Session 17), not a value back-calculated from volume. Range-limited to "
            f"[{MIN_SYRINGE_INNER_DIAMETER_MM}, {MAX_SYRINGE_INNER_DIAMETER_MM}] mm (Session 51) -- "
            "configure_syringe() rejects the same range again server-side, since no live device "
            "readback exists to validate against instead."
        )
        self.custom_syringe_stroke_mm = _spin(
            55.75, decimals=3, minimum=MIN_SYRINGE_STROKE_MM, maximum=MAX_SYRINGE_STROKE_MM
        )
        self.custom_syringe_stroke_mm.setToolTip(
            "Only used when Syringe = 'Custom'. The real maximum piston stroke (full travel "
            "length) of the physical syringe, in mm -- sent directly to the Qmix SDK's "
            "set_syringe_param() as max_piston_stroke_mm (QmixPumpBackend.configure_syringe(), "
            "Session 44). Not derived from Custom Volume above; supply the syringe's actual "
            "spec value. The three named BD presets instead derive this value from their "
            "nominal volume (an unconfirmed assumption, Session 17) because no authoritative "
            "BD stroke figure was available -- Custom deliberately does not repeat that "
            "assumption on unknown hardware, and asks for the real value instead. Range-limited "
            f"to [{MIN_SYRINGE_STROKE_MM}, {MAX_SYRINGE_STROKE_MM}] mm (Session 51) -- the upper "
            "bound is this pump module's own real mechanical piston-travel ceiling (CETONI Low "
            "Pressure Hardware Manual Section 5.1, NEM-B101-02 E: up to 65mm, independent of "
            "syringe), not a padded BD-range estimate; configure_syringe() rejects the same range "
            "again server-side, since no live device readback exists to validate against instead."
        )
        self._update_custom_syringe_volume_enabled()
        self.syringe.currentTextChanged.connect(lambda _text: self._update_custom_syringe_volume_enabled())
        self.flow_rate = _spin(-5000.0, decimals=1)
        self.flow_rate.setToolTip(
            "Flow rate in uL/min: negative values aspirate/withdraw, positive values dispense/infuse."
        )
        self.level_ml = _spin(0.0, decimals=3, minimum=0.0)
        self.level_ml.setToolTip(
            "Absolute mL target for 'Go to Level' (not a fraction of syringe capacity -- Session "
            "13 removed an earlier 0.0-1.0 fraction-vs-absolute-mL ambiguity)."
        )
        self.flush_flowrate = _spin(0.0, decimals=3)
        self.flush_flowrate.setToolTip(
            "uL/min on the real device (QmixPumpBackend.initialize() configures the pump's flow "
            "unit as uL/min, confirmed via the FlushSettings.timeout_s fix, Session 31/32) -- "
            "this row's label omits the unit shown on its Experiment-tab twin "
            "('Flush Flowrate(uL)'); same field, same unit, just not spelled out here. Combines "
            "with Flush Volume below to compute the real pump-move timeout: "
            "(flush_volume_ml*1000/this_value)*60+5 seconds (FlushSettings.timeout_s) -- too low "
            "a flowrate for a given volume risks the flush being declared failed before the pump "
            "physically finishes (the exact bug Session 31/32 fixed)."
        )
        self.flush_volume = _spin(0.0, decimals=3, minimum=0.0)
        self.flush_volume.setToolTip(
            "Application.flush() raises before touching hardware if this exceeds the selected "
            "Syringe's capacity (or Custom Volume, when Syringe='Custom') -- Session 10. Also "
            "combines with Flush Flowrate above to compute the real pump-move timeout "
            "(FlushSettings.timeout_s, Session 31/32)."
        )
        self.wait_after_flush = _spin(0.0, decimals=3, minimum=0.0)
        self.wait_after_flush.setToolTip(
            "Seconds to wait after the flush's second valve move (Closed) before considering the "
            "flush complete -- lets the system settle after fluid movement stops."
        )
        self.flush_count = _int_spin(1, minimum=1)

        self.roi_h_offset = _int_spin(0, minimum=0)
        self.roi_v_offset = _int_spin(900, minimum=0)
        self.roi_v_offset.setToolTip(
            "These startup defaults diverge from this repo's own validated-on-real-hardware "
            "combination (vertical_offset=792, vertical_size=740, exposure=40.0ms; C15440-20UP; "
            "see docs/current_workflow_audit.md and experiment_presets.py) -- Session 18 audit: "
            "classified SUSPECTED-PLACEHOLDER, never wired into these live defaults. Combines with "
            "Vertical Size below (the two together set DCAM SUBARRAYVPOS/SUBARRAYVSIZE) and with "
            "Exposure Time to determine the real DCAM readout time _check_camera_timing_budget() "
            "checks against Camera FPS on the Experiment tab."
        )
        self.roi_h_size = _int_spin(2304, minimum=0)
        self.roi_v_size = _int_spin(500, minimum=0)
        self.roi_v_size.setToolTip(self.roi_v_offset.toolTip())
        self.exposure_ms = _spin(50.0, decimals=3, minimum=0.0)
        self.exposure_ms.setToolTip(
            "Applied to real DCAM hardware via Configure Camera (configure_exposure_time()). "
            "Automated Experiment runs use their own Exposure time (ms) field instead and enforce "
            "a timing budget: Application._check_camera_timing_budget() rejects a configured "
            "Camera FPS the current exposure + real DCAM readout time (itself set by the ROI size "
            "above) can't sustain."
        )
        self.center_roi = QCheckBox("Off/On")
        self.center_roi.setChecked(True)
        self.center_roi.setToolTip(
            "When On, clicking Configure Camera also centers the ROI (HamamatsuCamera.center_roi(), "
            "Session 22 fix -- now genuinely re-applies the centered coordinates to real hardware, "
            "not just local Python state) using the current Horizontal/Vertical Size above."
        )
        self.image_continuous = QCheckBox("Off/On")
        self.image_continuous.setChecked(False)
        self.conversion_method = _combo(CONVERSION_METHOD_OPTIONS, "Full Dynamic")
        self.conversion_method.setToolTip(
            "How a captured 16-bit frame is stretched to 8-bit for on-screen preview only -- "
            "traced ImagePreviewWindow's own conversion methods: 'Full Dynamic' linearly stretches "
            "the frame's real min/max to 0-255; '90% Dynamic' stretches the middle 90th-percentile "
            "range instead (clips the outer 5% at each tail); 'Downshift' right-bit-shifts the raw "
            "16-bit value by '# Shifts' bits and clips to 0-255, no min/max computation. Display-"
            "only -- does not affect the saved TIFF data."
        )
        self.conversion_min = _spin(0.0, decimals=3)
        self.conversion_min.setReadOnly(True)
        self.conversion_max = _spin(0.0, decimals=3)
        self.conversion_max.setReadOnly(True)
        self.conversion_shifts = _int_spin(0, minimum=0, maximum=16)
        self.conversion_shifts.setToolTip(
            "Only used when Conversion Method = 'Downshift': the raw pixel value is right-shifted "
            "by this many bits before clipping to 0-255 (e.g. 8 shifts converts a 16-bit range "
            "down to roughly its top byte)."
        )
        self.sequence_path = QLineEdit("")
        self.sequence_mode = _combo(["Continuous", "Start (single)", "Burst"], "Continuous")
        sequence_cluster_tip = (
            "Part of the DCAM SequenceSettings cluster. Since Session 22, these Sequence "
            "fields (Mode/Source/Interval/Burst/Polarity/Delay) are carried from this manual "
            "tab into every automated Experiment run -- unlike most manual-tab widgets, "
            "changing these DOES affect automated runs, matching RunExperiment2.vi's own "
            "behavior of always applying the whole cluster."
        )
        self.sequence_mode.setToolTip(
            "DCAM MASTERPULSE_MODE: Continuous/Start (single)/Burst pulse pattern for the camera's "
            "internal master-pulse generator. Interval below is the pulse period (all modes); "
            "Burst below is only physically meaningful for the 'Burst' mode, though Python passes "
            "it to the device unconditionally regardless of which Mode is selected (traced "
            "configure_sequence(): no conditional gating on Mode's value). " + sequence_cluster_tip
        )
        self.sequence_source = _combo(["External", "Software"], "External")
        self.sequence_source.setToolTip(
            "DCAM MASTERPULSE_TRIGGERSOURCE: what starts the master-pulse generator (an external "
            "signal vs. a software/API call). " + sequence_cluster_tip
        )
        self.sequence_interval = _spin(1.0, decimals=6, minimum=0.000005, maximum=10.0)
        self.sequence_interval.setToolTip(
            "DCAM MASTERPULSE_INTERVAL in seconds -- the master-pulse period, paired with Mode "
            "above. " + sequence_cluster_tip
        )
        self.sequence_burst = _int_spin(1, minimum=1, maximum=65535)
        self.sequence_burst.setToolTip(
            "DCAM MASTERPULSE_BURSTTIMES -- pulse count per burst, only physically meaningful when "
            "Mode above = 'Burst' (see Mode's own tooltip for the unconditional-application caveat). "
            + sequence_cluster_tip
        )
        self.capture_mode = _combo(["Snap", "Sequence"], "Snap")
        self.capture_mode.setEnabled(False)
        self.capture_mode.setToolTip("Not wired to a real backend: never read by _camera_sequence_settings() or any capture path (confirmed dead, Session 11).")
        self.sequence_frames = _int_spin(0, minimum=0)
        self.sequence_frames.setToolTip(
            "Unlike its six siblings in this Sequence group (Mode/Source/Interval/Burst/Polarity/"
            "Delay, Session 22), this one is NOT carried into automated Experiment runs -- "
            "_build_experiment_series() always overrides it with the Experiment tab's own Frames "
            "count. Only reaches real hardware via this manual tab's own Configure Camera click, "
            "where it sizes the DCAM capture buffer (HamamatsuDcamBackend._sequence_buffer_frame_count())."
        )
        self.dcam_source = _combo(["Internal", "External", "Software", "MasterPulse"], "Internal")
        self.dcam_source.setToolTip(
            "DCAM TRIGGERSOURCE -- what starts each camera frame. Automated Experiment runs "
            "hardcode this to 'Internal' (Session 13) purely to remove undefined leftover-state "
            "risk -- whether it should instead be 'External' (paced by the AD2 DIO pulse train) "
            "remains genuinely unresolved: Session 19 traced the real LabVIEW call chain but the "
            "actual wired value is compiled block-diagram wiring, not recoverable from the "
            "exported VI diagrams. Still needs oscilloscope verification. Polarity/Delay below are "
            "only physically meaningful when this is 'External'."
        )
        self.external_polarity = _combo(["Negative", "Positive"], "Negative")
        self.external_polarity.setToolTip(
            "DCAM TRIGGERPOLARITY -- only physically meaningful when Dcam Trigger Source above is "
            "'External' (which edge of the external trigger signal starts a frame). " + sequence_cluster_tip
        )
        self.external_delay = _spin(0.0, decimals=6, minimum=0.0, maximum=10.000002)
        self.external_delay.setToolTip(
            "DCAM TRIGGERDELAY in seconds -- only physically meaningful when Dcam Trigger Source "
            "above is 'External' (delay from the external trigger edge to the actual frame start). "
            + sequence_cluster_tip
        )
        # Confirmed dead since Session 11 ("constructed and displayed but
        # never read"), same bug class as capture_mode (fixed Session 24) --
        # but this one was flagged, never actually fixed. _camera_sequence_settings()
        # never includes an "exposure_ms" key, so this value is never read by
        # configure_sequence() or anything else; the real exposure control is
        # self.exposure_ms in the ROI group (Configure Camera ->
        # configure_exposure_time()), which shares this same "ExposureTime(ms)"
        # row label on the same tab -- a live/dead label collision identical to
        # the one already fixed for "Mode"/"Capture mode" in Session 24.
        # Disabled here, matching that precedent, instead of removing the
        # widget outright.
        self.sequence_exposure_ms = _spin(0.0, decimals=3, minimum=0.0)
        self.sequence_exposure_ms.setEnabled(False)
        self.sequence_exposure_ms.setToolTip(
            "Not wired to a real backend: never included in _camera_sequence_settings(), so "
            "never read by configure_sequence() or any capture path (confirmed dead, Session "
            "11; same bug class as capture_mode, fixed Session 24, but this field was never "
            "actually fixed then). The real exposure control is ExposureTime(ms) in the ROI "
            "group above (self.exposure_ms), applied via Configure Camera."
        )

        self.series_path = QLineEdit(r"C:\test\firstrunpulsed")
        self.series_path.setToolTip(
            "Root folder for this experiment series -- each repeat gets its own "
            "repeat_NNN subfolder containing that repeat's data.tdms + TIFF frames "
            "(_build_experiment_series()). Start exp blocks with a confirmation dialog if "
            "data.tdms/frame_*.tiff already exist under this path (Session 10)."
        )
        self.exp_camera_fps = _spin(0.0, decimals=3, minimum=0.0)
        self.exp_camera_fps.setToolTip(
            "Must be > 0 -- used to derive the AD2 DIO1 LED clock (Experiment2's DO clock "
            "channel) and checked against the real DCAM readout time + exposure by "
            "Application._check_camera_timing_budget() before capture starts. Combines with "
            "Frames below: the DO clock's run duration = Frames / this value "
            "(_experiment_do_clock_config()); combines with Exposure time (ms) in the "
            "Experiment group below: this FPS must be achievable given that exposure + the real "
            "DCAM readout time, or the timing-budget check rejects the run before it starts "
            "(Session 19)."
        )
        self.exp_camera_start = _spin(0.0, decimals=3, minimum=0.0)
        self.exp_camera_start.setToolTip(
            "Seconds after the AD2 PC trigger before the DO clock (LED) starts, used for every "
            "repeat. Ignored whenever Dynamic Camera Start Time (below, in Camera Start Array(s)) "
            "is checked -- each repeat then uses its own per-repeat value from that array instead."
        )
        self.exp_ch1_freq = _spin(0.0, decimals=3, minimum=0.0)
        self.exp_ch1_freq.setToolTip(
            "CH0 carrier frequency in kHz, converted to Hz at the UI boundary (_experiment_channel_config()). "
            "Overridden per-repeat when Frequency Scanning (below) is enabled, and overridden "
            "entirely (Center=(Start+Stop)/2) when Enable Frequency Sweep (below) is checked -- "
            "the sweep override wins if both happen to be enabled at once."
        )
        self.exp_ch1_amp = _spin(0.0, decimals=3)
        self.exp_ch1_offset = _spin(0.0, decimals=3)
        self.exp_ch1_function = _combo([item.value for item in WaveformFunction], WaveformFunction.SINE.value)
        self.exp_ch1_enable = QCheckBox("Enable")
        self.exp_ch1_enable.setToolTip(
            "Whether CH0's real AD2 output is active for this run. If neither channel is enabled, "
            "WfgConfig.running is False and the AD2 WFG is not started at all (_experiment_wfg_config())."
        )
        self.exp_ch1_start = _spin(0.0, decimals=3, minimum=0.0)
        self.exp_ch1_start.setToolTip("Delay in seconds after the AD2 PC trigger before this channel's output starts.")
        self.exp_ch1_run = _spin(0.0, decimals=3, minimum=0.0)
        self.exp_ch1_run.setToolTip(
            "Output duration in seconds. 0 = continuous/free-running (no defined stop time) -- "
            "Application._ad2_trigger_completion_seconds() raises before starting if this is 0, "
            "since flush/save can't safely proceed without a known completion time."
        )
        self.exp_ch1_repeat = _int_spin(0, minimum=0)
        self.exp_ch1_trigger_source = _combo(WFG_TRIGGER_SOURCE_OPTIONS, "trigsrcNone")
        self.exp_ch1_trigger_source.setToolTip(
            "AD2 SDK trigger source enum. The automated Experiment path always arms via config "
            "then fires one shared PC trigger (Application.run_experiment2() -> ad2.pc_trigger())."
        )
        self.exp_ch1_symmetry = _spin(50.0, decimals=3, minimum=0.0, maximum=100.0)
        self.exp_ch1_symmetry.setToolTip(
            "Duty-cycle-like shape control for the carrier waveform (percent of each period "
            "spent in the 'high' phase for Square, or skew for Triangle/Sine). 50% is symmetric."
        )
        self.exp_ch1_phase = _spin(0.0, decimals=3)
        self.exp_ch1_phase.setToolTip("Starting phase offset of the carrier waveform, in degrees.")
        self.exp_ch1_repeat_trigger = QCheckBox("Repeat Trigger")
        self.exp_ch1_repeat_trigger.setToolTip("Whether the trigger source re-arms automatically after each repeat.")
        self.exp_sweep_enable = QCheckBox("Enable Frequency Sweep During Experiment")
        self.exp_sweep_enable.setToolTip(
            "When checked, overrides CH0 Frequency above with this group's own Center Frequency "
            "(and enables the FM node) for every repeat -- CH0's own Frequency field above is "
            "ignored while this is on. CH1 is never affected (Ch1-only, matching "
            "WfgConfigureSweepCh1.vi's own hardcoded scope). Distinct from Frequency Scanning "
            "below: this is a continuous ms-scale sweep within one drive, Frequency Scanning is a "
            "discrete per-repeat frequency substitution."
        )
        # Start/Stop Frequency are the user-facing inputs (see the manual WFG
        # tab's matching sweep_start_khz/sweep_stop_khz note) -- defaults are
        # the Martens et al. reference case (center 1.934 MHz, width 50 kHz)
        # re-expressed as Start=1909.0/Stop=1959.0 kHz: (1909+1959)/2=1934,
        # |1959-1909|=50, exactly reproducing the original Session-16 values.
        self.exp_sweep_start_khz = _spin(1909.0, decimals=3, minimum=0.0)
        self.exp_sweep_stop_khz = _spin(1959.0, decimals=3, minimum=0.0)
        # Dual-mode input (see the manual WFG tab's matching note): Center/
        # Width restored alongside Start/Stop, kept in sync, neither removed.
        self.exp_sweep_center_khz = _spin(1934.0, decimals=3, minimum=0.0)
        self.exp_sweep_width_khz = _spin(50.0, decimals=3, minimum=0.0)
        self.exp_sweep_time_ms = _spin(1.0, decimals=3, minimum=0.0)
        self.exp_sweep_time_ms.setToolTip(
            "Time for one full sweep repetition -- FmSweepSettings.fm_frequency_hz = 1000/this "
            "value (ad2.py), i.e. the FM node's own modulation frequency. Martens et al. "
            "reference case (Session 16) uses 1 ms (-> 1 kHz FM modulation rate)."
        )
        self.exp_sweep_type = _combo(["Symmetric", "RampUp", "RampDown"], "Symmetric")
        exp_sweep_dual_mode_tip = (
            "Start/Stop and Center/Width are both live inputs for the same underlying value -- "
            "editing either pair updates the other to match (center_hz=(start+stop)/2, "
            "width_hz=|stop-start|). Unlike the manual WFG tab's own Sweep group, enabling this "
            "one DOES apply to real automated Experiment runs (Session 16)."
        )
        for widget in (self.exp_sweep_start_khz, self.exp_sweep_stop_khz, self.exp_sweep_center_khz, self.exp_sweep_width_khz):
            widget.setToolTip(exp_sweep_dual_mode_tip)
        self.exp_sweep_type.setToolTip(
            "Symmetric->Triangle, RampUp->RampUp, RampDown->RampDown is the most architecturally "
            "plausible Function-2 enum mapping given the shared AD2 SDK enum, not independently "
            "confirmed against WfgConfigureSweepCh1.vi's actual wiring (Session 16)."
        )
        self.exp_ch2_freq = _spin(1.0, decimals=3, minimum=0.0)
        self.exp_ch2_freq.setToolTip(
            "CH1 carrier frequency in kHz, converted to Hz at the UI boundary "
            "(_experiment_channel_config()), applied to real AD2 hardware every run. Never "
            "touched by Frequency Scanning or Frequency Sweep -- both are Ch1(CH0)-only."
        )
        self.exp_ch2_amp = _spin(1.0, decimals=3)
        self.exp_ch2_offset = _spin(0.0, decimals=3)
        self.exp_ch2_function = _combo([item.value for item in WaveformFunction], WaveformFunction.SINE.value)
        self.exp_ch2_enable = QCheckBox("Enable")
        self.exp_ch2_enable.setToolTip(
            "Whether CH1's real AD2 output is active for this run. If neither channel is enabled, "
            "WfgConfig.running is False and the AD2 WFG is not started at all (_experiment_wfg_config())."
        )
        self.exp_ch2_start = _spin(0.0, decimals=3, minimum=0.0)
        self.exp_ch2_start.setToolTip(self.exp_ch1_start.toolTip())
        self.exp_ch2_run = _spin(0.0, decimals=3, minimum=0.0)
        self.exp_ch2_run.setToolTip(self.exp_ch1_run.toolTip())
        self.exp_ch2_repeat = _int_spin(0, minimum=0)
        self.exp_ch2_trigger_source = _combo(WFG_TRIGGER_SOURCE_OPTIONS, "trigsrcNone")
        self.exp_ch2_trigger_source.setToolTip(self.exp_ch1_trigger_source.toolTip())
        self.exp_ch2_symmetry = _spin(50.0, decimals=3, minimum=0.0, maximum=100.0)
        self.exp_ch2_symmetry.setToolTip(self.exp_ch1_symmetry.toolTip())
        self.exp_ch2_phase = _spin(0.0, decimals=3)
        self.exp_ch2_phase.setToolTip(self.exp_ch1_phase.toolTip())
        self.exp_ch2_repeat_trigger = QCheckBox("Repeat Trigger")
        self.exp_ch2_repeat_trigger.setToolTip(self.exp_ch1_repeat_trigger.toolTip())
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
        self.exp_repeats.setToolTip(
            "Number of Experiment2 runs in this series (_build_experiment_series() builds one "
            "repeat_NNN folder per unit). Two hard constraints tie this to other fields: (1) when "
            "Frequency Scanning below is enabled, its resulting frequency count must exactly equal "
            "this value or _build_experiment_series() raises before starting; (2) when Dynamic "
            "Camera Start Time is checked, this cannot exceed Camera Start Array(s)'s 10 fixed "
            "slots, or _experiment_do_clock_config() raises mid-run on the first repeat past slot 10."
        )
        self.exp_frames = _int_spin(1, minimum=0)
        self.exp_frames.setToolTip(
            "Frames captured per repeat. Combines with Camera FPS above: the DO clock's run "
            "duration = this value / Camera FPS (_experiment_do_clock_config()) -- the real "
            "duration the LED/camera trigger stays active each repeat."
        )
        self.exp_exposure_ms = _spin(0.0, decimals=3, minimum=0.0)
        self.exp_exposure_ms.setToolTip(
            "Applied to real DCAM hardware every run via configure_exposure_time() (Session 20 "
            "fix -- a prior bug called a Python-side bookkeeping setter instead, silently leaving "
            "the camera at whatever exposure a previous manual session had set). Combines with "
            "Camera FPS above: Application._check_camera_timing_budget() rejects the run before "
            "capture starts if this exposure plus the real DCAM readout time (set by the ROI size, "
            "Camera tab) can't sustain the configured Camera FPS (Session 19)."
        )
        self.exp_flush_flowrate = _spin(0.0, decimals=3)
        self.exp_flush_flowrate.setToolTip(
            "uL/min on the real device (QmixPumpBackend.initialize() configures the pump's flow "
            "unit as uL/min, Session 31/32). Combines with flush volume (ml) below to compute the "
            "real pump-move timeout: (flush_volume_ml*1000/this_value)*60+5 seconds "
            "(FlushSettings.timeout_s) -- too low a flowrate for a given volume risks the flush "
            "being declared failed before the pump physically finishes (the exact bug Session "
            "31/32 fixed)."
        )
        self.exp_flush_volume = _spin(0.0, decimals=3, minimum=0.0)
        self.exp_flush_volume.setToolTip(
            "Application.flush() raises before touching hardware if this exceeds the selected "
            "Syringe's capacity (or Custom Volume, Pump&Valve tab, when Syringe='Custom') -- "
            "Session 10. Also combines with flush Flowrate(uL) above to compute the real pump-"
            "move timeout (FlushSettings.timeout_s, Session 31/32)."
        )
        self.exp_wait_after_flush = _spin(0.0, decimals=3, minimum=0.0)
        self.exp_wait_after_flush.setToolTip(
            "Seconds to wait after the flush's second valve move (Closed) before considering the "
            "flush complete -- lets the system settle after fluid movement stops."
        )
        self.exp_flush_enabled = QCheckBox("Enable")
        self.camera_start_array = [_spin(0.0, decimals=3, minimum=0.0) for _ in range(10)]
        for index, widget in enumerate(self.camera_start_array):
            widget.setToolTip(
                f"Camera Start Time (s) for repeat {index + 1}, used only when Dynamic Camera "
                "Start Time above is checked -- otherwise the single Camera Start (s) field above "
                "is used for every repeat instead. Fixed at 10 slots: Repeats above cannot exceed "
                "10 while Dynamic Camera Start Time is checked, or _experiment_do_clock_config() "
                "raises on the first repeat past slot 10."
            )
        self.global_exposure = QCheckBox("Off/On")
        self.global_exposure.setToolTip(
            "Experiment2.trigger_global_exposure -- passed to camera.configure_trigger_global_exposure(); "
            "may only take effect with compatible DCAM trigger source settings (Dcam Trigger "
            "Source, Camera tab)."
        )
        self.dynamic_camera_start = QCheckBox("Off/On")
        self.dynamic_camera_start.setToolTip(
            "When on, each repeat's Camera Start Time comes from its own slot in Camera Start "
            "Array(s) below instead of the single Camera Start (s) field above -- and Repeats "
            "above cannot then exceed the array's 10 fixed slots."
        )
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
        self.exp_freq_scan_enable.setToolTip(
            "Discrete per-repeat substitution of Channel 1's carrier frequency only (Channel 2 "
            "unaffected) -- one full experiment per frequency point, distinct from FM Sweep's "
            "continuous ms-scale sweep within a single drive. Linear spacing between Start and "
            "Stop is inferred from the LabVIEW investigation, not confirmed from its compiled "
            "block-diagram wiring. Repeats (top of this tab) must equal the resulting frequency "
            "count (Number of Frequencies, or the count Step Size derives) or this raises before "
            "starting."
        )
        self.exp_freq_scan_start_khz = _spin(1900.0, decimals=3, minimum=0.0)
        self.exp_freq_scan_start_khz.setToolTip(
            "First frequency point (kHz) in the linear-spaced scan -- combines with Stop Frequency "
            "and Number of Frequencies/Step Size below to generate the full per-repeat list "
            "(_experiment_frequency_scan_list_hz())."
        )
        self.exp_freq_scan_stop_khz = _spin(1975.0, decimals=3, minimum=0.0)
        self.exp_freq_scan_stop_khz.setToolTip(
            "Last frequency point (kHz) in the linear-spaced scan -- combines with Start Frequency "
            "and Number of Frequencies/Step Size below to generate the full per-repeat list "
            "(_experiment_frequency_scan_list_hz())."
        )
        self.exp_freq_scan_count = _int_spin(2, minimum=1)
        self.exp_freq_scan_count.setToolTip(
            "Must equal Repeats (top of this tab) when Frequency Scanning is enabled. Overridden "
            "by Step Size when that field is set above 0 -- this field's own displayed value then "
            "auto-updates to show the real count Step Size produces."
        )
        # Alternative to Number of Frequencies: when > 0, Step Size drives the
        # point count instead (count derived and rounded to the nearest whole
        # point); 0 means "not used," matching this codebase's existing
        # zero-means-disabled convention (e.g. custom_syringe_volume_ml only
        # applies when "Custom" is selected). Not part of the LabVIEW spec
        # (which only exposes Number of Frequencies) -- a Python-only
        # convenience addition.
        self.exp_freq_scan_step_khz = _spin(0.0, decimals=3, minimum=0.0)
        self.exp_freq_scan_step_khz.setToolTip(
            "0 = not used (Number of Frequencies drives the point count instead). When set above "
            "0, this takes precedence: point count = round(|Stop-Start| / Step) + 1. Not part of "
            "the original LabVIEW FrequencyHelper.vi spec -- a Python-only convenience addition."
        )
        self.average_fps = QLabel("0")

        # --- Z-scan calibration tab (Phase 4): piezo_zscan.ZScanCalibration's
        # own run() parameters, exposed 1:1 -- no hidden/derived values.
        # z_start/z_end are range-constrained to the piezo's own live-read
        # MaxTravel (matching PiezoStage's own no-hardcoded-limit convention,
        # Session 46) rather than left to the generic +/-1e12 _spin() default
        # -- PiezoStage.set_position() still clamps as a second line of
        # defense, but this UI now also constrains input in real time instead
        # of relying on that clamp as the only guard. Disabled with range
        # [0, 0] until _apply_zscan_range() is called (via Query Piezo Range
        # or Start Z-Scan's own connect step) -- see zscan_range_status.
        self.zscan_z_start_um = _spin(0.0, decimals=2, minimum=0.0, maximum=0.0)
        self.zscan_z_start_um.setEnabled(False)
        self.zscan_z_start_um.setToolTip(
            "Start Z position in micrometers -- ZScanCalibration.run()'s z_start_um. Inclusive: the "
            "first captured frame targets this position (Session 47). Range-limited to [0, MaxTravel] "
            "read live from the connected piezo (Session 46) -- disabled until Query Piezo Range or "
            "Start Z-Scan has connected at least once."
        )
        self.zscan_z_end_um = _spin(0.0, decimals=2, minimum=0.0, maximum=0.0)
        self.zscan_z_end_um.setEnabled(False)
        self.zscan_z_end_um.setToolTip(
            "End Z position in micrometers -- ZScanCalibration.run()'s z_end_um, must be >= Z Start. "
            "Inclusive: round((Z End - Z Start) / Step Size) + 1 positions are captured (Session 47's "
            "_build_targets()); the real per-frame position embedded in each filename is the "
            "closed-loop readback, not this nominal target. Range-limited to [0, MaxTravel] read live "
            "from the connected piezo (Session 46) -- disabled until Query Piezo Range or Start "
            "Z-Scan has connected at least once."
        )
        self.zscan_range_status = QLabel("Connect device to see valid range")
        self.zscan_range_status.setWordWrap(True)
        self.zscan_step_size_um = _spin(1.0, decimals=3, minimum=0.001)
        self.zscan_step_size_um.setToolTip(
            "Step size in micrometers between consecutive Z positions -- must be > 0. If (Z End - Z "
            "Start) isn't an exact multiple of this value, the step count is rounded to the nearest "
            "whole number (Session 47); the saved filename still reflects the real measured position, "
            "not the nominal target."
        )
        self.zscan_exposure_ms = _spin(40.0, decimals=3, minimum=0.001)
        self.zscan_exposure_ms.setToolTip(
            "Camera exposure time in milliseconds, applied once via configure_exposure_time() at the "
            "start of the scan (Session 47) -- independent of whatever the manual Camera tab's own "
            "ExposureTime(ms) is currently set to."
        )
        self.zscan_output_dir = QLineEdit(r"C:\test\zscan_calibration")
        self.zscan_output_dir.setToolTip(
            "Folder where each frame is saved as z_<measured_um>um.tif (real closed-loop readback, "
            "not the commanded target -- Session 47). Created if it doesn't already exist."
        )

    def _make_wfg_channel_state(self, index: int, frequency: float, amplitude: float) -> dict[str, object]:
        # frequency/amplitude are passed in Hz (caller-facing default values);
        # all frequency-class widgets below display/store kHz -- see the
        # kHz-unification note in _channel_config().
        state = {
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
            # Dual-mode input, corrected in a later session after Session 35
            # removed Center+Width entirely instead of adding Start/Stop
            # alongside it: Start/Stop Frequency (Digilent's own WaveForms
            # sweep tool convention) and Center/Width (this feature's
            # original Session-16 paper-narrative framing) are both live
            # inputs for the same underlying value, kept in sync by
            # _connect_sweep_dual_mode_refresh() -- neither is ever hidden or
            # removed, matching the same "offer both, replace neither"
            # principle already used for Frequency Scanning's Number of
            # Frequencies vs. Step Size. The FM-node hardware math
            # (FmSweepSettings, fm_mod_settings()) is unchanged from Session
            # 16 either way -- only the UI input path(s) changed.
            "sweep_start_khz": _spin(frequency / 1000.0 - 25.0, decimals=3, minimum=0.0),
            "sweep_stop_khz": _spin(frequency / 1000.0 + 25.0, decimals=3, minimum=0.0),
            "sweep_center_khz": _spin(frequency / 1000.0, decimals=3, minimum=0.0),
            "sweep_width_khz": _spin(50.0, decimals=3, minimum=0.0),
            "sweep_time_ms": _spin(1.0, decimals=3, minimum=0.0),
            "sweep_type": _combo(["Symmetric", "RampUp", "RampDown"], "Symmetric"),
        }
        # Category re-narrowing (Session 41): idx/frequency/amplitude/offset/
        # function/enable removed here -- self-evident given their unit-
        # labeled row text and the label's own "(overridden)" suffix already
        # states the key relationship; sec_run/repeat removed since their row
        # labels already spell out "[0 = continuous]"/"[0 = infinite]" inline.
        # symmetry/phase kept (shape/skew control is genuinely more than a
        # plain duty-cycle percentage), as are sec_wait/trigger_source/
        # repeat_trigger (SDK-jargon/non-obvious semantics).
        state["symmetry"].setToolTip(
            "Duty-cycle-like shape control for the carrier waveform (percent of each period "
            "spent in the 'high' phase for Square, or skew for Triangle/Sine). 50% is symmetric."
        )
        state["phase"].setToolTip("Starting phase offset of the carrier waveform, in degrees.")
        state["sec_wait"].setToolTip("Delay in seconds after the AD2 PC trigger before this channel's output starts.")
        state["trigger_source"].setToolTip(
            "AD2 SDK trigger source enum (trigsrcNone/trigsrcPC/etc.) controlling what starts this "
            "channel's output. The automated Experiment path always arms via config then fires a "
            "single shared PC trigger (Application.run_experiment2() -> ad2.pc_trigger())."
        )
        state["repeat_trigger"].setToolTip("Whether the trigger source re-arms automatically after each repeat.")
        # frequency/amplitude/offset/function removed here (Session 41 re-
        # narrowing) -- self-evident by unit, and the "(unused)" label suffix
        # already states the key fact; symmetry/phase kept for the same
        # shape/skew reasoning as Carrier's own symmetry/phase above.
        fm_mod_tip = (
            "AD2 FM modulation node (waveforms.py node=1). Never read by an automated Experiment "
            "run (see this group's own 'FM Mod (unused)' header) -- only reachable via this manual "
            "tab's own Apply WFG, and only takes effect if FM Mod's own Enable is checked below."
        )
        for key in ("fm_symmetry", "fm_phase"):
            state[key].setToolTip(fm_mod_tip)
        state["fm_enable"].setToolTip(
            "Whether the FM modulation node above is active when Apply WFG is clicked. When "
            "Enable Sweep below is checked instead, these FM Mod fields are entirely bypassed -- "
            "Sweep computes and writes its own FM node settings directly (_channel_config())."
        )
        state["sweep_enable"].setToolTip(
            "When checked, overrides this channel's own FM Mod fields above (bypassed entirely) "
            "and this channel's own Frequency above (Carrier.frequency_hz becomes Sweep's own "
            "Center Frequency) with values computed from the Sweep fields below, applied by Apply "
            "WFG. Independent of the Experiment tab's own Enable Frequency Sweep checkbox -- see "
            "this section's own header note."
        )
        sweep_dual_mode_tip = (
            "Start/Stop and Center/Width are both live inputs for the same underlying value -- "
            "editing either pair updates the other to match (center_hz=(start+stop)/2, "
            "width_hz=|stop-start|). Continuous ms-scale sweep within a single acoustic drive, "
            "distinct from Frequency Scanning's discrete per-repeat substitution."
        )
        for key in ("sweep_start_khz", "sweep_stop_khz", "sweep_center_khz", "sweep_width_khz"):
            state[key].setToolTip(sweep_dual_mode_tip)
        state["sweep_time_ms"].setToolTip(
            "Time for one full sweep repetition -- FmSweepSettings.fm_frequency_hz = 1000/this "
            "value (ad2.py), i.e. the FM node's own modulation frequency. Martens et al. "
            "reference case (Session 16) uses 1 ms (-> 1 kHz FM modulation rate)."
        )
        state["sweep_type"].setToolTip(
            "Symmetric->Triangle, RampUp->RampUp, RampDown->RampDown is the most architecturally "
            "plausible Function-2 enum mapping given the shared AD2 SDK enum, not independently "
            "confirmed against WfgConfigureSweepCh1.vi's actual wiring (Session 16)."
        )
        return state

    def _build_layout(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        top = QGridLayout()
        exit_button = QPushButton("Exit")
        exit_button.clicked.connect(self._exit_app)
        abort_button = QPushButton("Abort")
        abort_button.clicked.connect(self._abort)
        self.status = HistoryLogWidget()
        self.status.setMinimumWidth(280)
        self.status.setMaximumHeight(80)
        self.status.setToolTip(
            "Full session history of every status change, newest at the bottom -- "
            "not just the most recent one. Scroll up to review; scroll back to the "
            "bottom (or wait for the next update while already at the bottom) to "
            "resume auto-scrolling."
        )
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
        self.tabs.addTab(self._zscan_tab(), "Z-Scan")
        self.tabs.currentChanged.connect(self._seed_experiment_ad2_if_experiment_tab)
        body.addWidget(self.tabs, 1)
        body.addWidget(self._error_panel())
        layout.addLayout(body, 1)

    def _init_tab(self) -> QWidget:
        tab = QWidget()
        grid = QGridLayout(tab)
        grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        grid.addWidget(self._instrument_group(), 0, 0)
        # Without an explicit alignment, QGridLayout stretches a cell's widget
        # to fill the full row height -- Simulation (4 simple checkboxes,
        # ~125px natural) was being inflated to match Hardware's much taller
        # ~395px (12 real fields), leaving a large empty region inside the
        # Simulation box itself. AlignTop keeps it at its own natural size.
        grid.addWidget(self._simulation_group(), 0, 1, Qt.AlignmentFlag.AlignTop)
        initialize = QPushButton("Initialize!")
        initialize.setMinimumWidth(230)
        initialize.clicked.connect(self._start_initialize)
        grid.addWidget(QLabel("Initialize System"), 1, 0)
        grid.addWidget(initialize, 2, 0)
        grid.setColumnStretch(2, 1)
        # Note: the remaining gap between this tab's own natural content
        # height (~457px) and its actual rendered height inside the running
        # app is a QTabWidget characteristic, not a per-tab layout defect --
        # every tab page shares one viewport sized to the tallest tab
        # (Experiment), so a much sparser tab like this one is stretched to
        # match regardless of its own layout. Eliminating that fully would
        # mean resizing the whole window on every tab switch, which is worse
        # UX than the current dead space and out of scope for a label/layout
        # pass; not attempted here.
        return tab

    def _instrument_group(self) -> QGroupBox:
        # qt_ui_v2.py's InitializationDialog already disables these same six
        # fields with "Not wired to a real backend" (Session 3, confirmed
        # against hardware_factory.build_hardware_bundle(), which never reads
        # them) -- this tab never got that same treatment, so it still shows
        # them as if they were live, editable settings. Applied here too for
        # consistency between the two UIs' Initialization surfaces.
        group = QGroupBox("Hardware")
        form = QFormLayout(group)
        form.addRow("Analog Discovery 3", self.ad2_enabled)
        form.addRow("Z stage", self.z_enabled)
        form.addRow("Z stage backend", self._mark_unwired_stub(self.z_backend))
        form.addRow("Prior VISA resource name", self.prior_resource)
        form.addRow("Thorlabs/APT serial", self._mark_unwired_stub(self.thorlabs_apt_serial))
        form.addRow("Thorlabs/APT backend", self._mark_unwired_stub(self.thorlabs_apt_backend))
        form.addRow("Thorlabs/APT discovery only", self._mark_unwired_stub(self.thorlabs_apt_discovery_only))
        form.addRow("Hamamatsu", self.camera_enabled)
        form.addRow("Cetoni Pump", self.pump_enabled)
        form.addRow("Qmix SDK Python Path", self._mark_unwired_stub(self.qmix_sdk_python_path))
        form.addRow("Qmix QMIXSDK Path", self._mark_unwired_stub(self.qmix_qmixsdk_path))
        form.addRow("Cetoni Device Configuration Path", self.cetoni_config_path)
        form.addRow("MX Valve", self.valve_enabled)
        form.addRow("Valve VISA resource name", self.valve_resource)
        self._add_tooltip_icons(form)
        return group

    @staticmethod
    def _mark_unwired_stub(widget: QWidget) -> QWidget:
        widget.setEnabled(False)
        widget.setToolTip(
            "Not wired to a real backend: never read by hardware_factory.build_hardware_bundle() "
            "(Session 3)."
        )
        return widget

    @staticmethod
    def _stale_static_display(widget: QWidget, description: str) -> QWidget:
        # Category 4 (Session 39): "Elapsed Time"/"Time Left" were found
        # constructed as bare QLabel("00:00:00") -- not even assigned to a
        # `self.` attribute -- in both qt_ui.py and qt_ui_v2.py, meaning no
        # code anywhere could ever update them even if it tried. They render
        # exactly like a live countdown/stopwatch readout (mirroring
        # LabVIEW's own Elapsed Time/Time Left front-panel indicators) but
        # have been 100% static placeholders for this display's entire
        # history -- never flagged in any of the 38 prior sessions' audits.
        # Implementing a real timer is a new feature (out of this pass's
        # scope); marked as a non-functional stub instead, the same
        # disabled+tooltip convention already used for every other
        # confirmed-dead widget in this codebase, so it stops silently
        # implying a live value that was never wired.
        widget.setEnabled(False)
        widget.setToolTip(
            f"Not wired to a real backend: this {description} display is never updated by any "
            "code path -- a static placeholder mirroring a LabVIEW front-panel indicator that "
            "was never ported (confirmed dead, Session 39)."
        )
        return widget

    def _elapsed_time_label(self) -> QLabel:
        self.elapsed_time_label = QLabel("00:00:00")
        return self._stale_static_display(self.elapsed_time_label, "Elapsed Time")

    def _time_left_label(self) -> QLabel:
        self.time_left_label = QLabel("00:00:00")
        return self._stale_static_display(self.time_left_label, "Time Left")

    # Requirement C, revised (Session 41): replaces Session 40's style-based
    # marker (underline + link color applied to the row label itself) with a
    # separate small "info" icon widget next to the field -- per explicit
    # correction, since a style change to the label was judged too easy to
    # miss/too tightly coupled to the label's own appearance. This version
    # touches neither the label's text NOR its styling at all: a field with
    # a tooltip gets wrapped in a small container alongside a
    # _TooltipIconButton; a field with none is left completely untouched
    # (same widget instance stays directly in its original layout slot).
    # Click-triggered per explicit user confirmation (not hover): the icon
    # itself carries no native Qt tooltip (hovering it alone does nothing);
    # clicking calls QToolTip.showText() manually, reusing Qt's own
    # tooltip rendering (auto-wrap, native look) for the actual explanation.
    @classmethod
    def _wrap_with_tooltip_icon(cls, widget: QWidget) -> QWidget:
        tip = widget.toolTip()
        if not tip:
            return widget
        container = _TooltipIconWrapper()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(widget)
        layout.addWidget(_TooltipIconButton(tip))
        return container

    @classmethod
    def _add_tooltip_icons(cls, form: QFormLayout) -> None:
        """Walk every row of a QFormLayout and, wherever the row's field
        widget (or single-widget spanning row, e.g. form.addRow(checkbox))
        already carries a tooltip, replace it in-place with a small
        [field, icon] container via QFormLayout.setWidget() -- the row's
        own label (string or QLabel) is never touched, so every existing
        label-text assertion in this codebase's own tests stays valid
        unchanged. Reused across every tab/group builder in both UIs (same
        call sites Session 40's _mark_tooltip_rows() used), so coverage can
        never drift out of sync with whichever widget actually has a
        tooltip (checked live every call, not tracked separately)."""
        for row in range(form.rowCount()):
            field_item = form.itemAt(row, QFormLayout.ItemRole.FieldRole)
            spanning_item = form.itemAt(row, QFormLayout.ItemRole.SpanningRole)
            if spanning_item is not None:
                widget = spanning_item.widget()
                if widget is not None and widget.toolTip():
                    form.setWidget(row, QFormLayout.ItemRole.SpanningRole, cls._wrap_with_tooltip_icon(widget))
                continue
            widget = field_item.widget() if field_item is not None else None
            if widget is not None and widget.toolTip():
                form.setWidget(row, QFormLayout.ItemRole.FieldRole, cls._wrap_with_tooltip_icon(widget))

    def _simulation_group(self) -> QGroupBox:
        group = QGroupBox("Simulation")
        form = QFormLayout(group)
        form.addRow("Simulate Camera", self.sim_camera)
        form.addRow("Simulate Pump", self.sim_pump)
        form.addRow("Simulate Valve", self.sim_valve)
        form.addRow("Simulate AD2", self.sim_ad2)
        self._add_tooltip_icons(form)
        return group

    def _wfg_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        note = QLabel("Manual AD2 test tool -- independent from Experiment tab. Settings here do NOT affect experiment runs.")
        note.setWordWrap(True)
        layout.addWidget(note)
        header = QHBoxLayout()
        header.addWidget(QLabel("WFGConfig"))
        header.addWidget(self._wrap_with_tooltip_icon(self.wfg_running))
        header.addStretch()
        header.addWidget(QLabel("SynchronizeState"))
        self.wfg_sync.setEnabled(False)
        self.wfg_sync.setToolTip("Not implemented: SynchronizeState is currently a non-functional stub.")
        header.addWidget(self._wrap_with_tooltip_icon(self.wfg_sync))
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
        # Chose option (a) -- shorten the repeated suffix itself -- over
        # option (b) (single sentence + per-field marker/icon): the tab's own
        # top-level note already states the general rule ("Settings here do
        # NOT affect experiment runs"), but "overridden" vs "unused" are two
        # genuinely different reasons (an active Experiment-tab analog exists
        # vs. none exists at all) worth keeping distinguishable per field: a
        # single generic marker would lose that distinction, and Qt doesn't
        # have a built-in compact form-row annotation widget cheaper than a
        # short text suffix. Cuts each repeated phrase from 30-40 characters
        # to 10-12, which is what was actually cramping the value fields.
        overridden = " (overridden)"
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
        # _add_tooltip_icons() must run AFTER layout.addLayout() here, not
        # before -- confirmed empirically (Session 41): QLayout.addLayout()
        # reparents a still-detached QFormLayout's row widgets to the new
        # parent using its OWN row bookkeeping, which "unwraps" any row
        # already replaced via QFormLayout.setWidget() (the tooltip-icon
        # wrap), silently discarding the wrapper. A QFormLayout constructed
        # with a parent widget up front (`QFormLayout(some_widget)`, used
        # everywhere else in this file) never hits this, since it's never
        # "added" to another layout afterward.
        layout.addLayout(form)
        self._add_tooltip_icons(form)
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
        self._add_tooltip_icons(trigger)
        fm = QFormLayout()
        # FM Mod: traced _experiment_channel_config() -- when FM Sweep is off,
        # fm_mod is a hardcoded-disabled CarrierSettings; when FM Sweep is on
        # (Ch1/CH0 only), fm_mod comes entirely from the Experiment tab's own
        # Sweep fields. Either way, these FM Mod widgets are never read by an
        # automated run -- not "active", not "overridden", simply unused.
        fm_note = " (unused)"
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
        self._add_tooltip_icons(fm)
        sweep = QFormLayout()
        for label, key in (
            ("Start Frequency (kHz)", "sweep_start_khz"),
            ("Stop Frequency (kHz)", "sweep_stop_khz"),
            ("Center Frequency (kHz)", "sweep_center_khz"),
            ("Width (kHz)", "sweep_width_khz"),
            ("Sweep Time (ms)", "sweep_time_ms"),
            ("Sweep Type", "sweep_type"),
        ):
            sweep.addRow(label, state[key])
        sweep.addRow(state["sweep_enable"])
        # Sweep (FM modulation): this manual tab's own state is independent
        # of the Experiment tab and does not affect automated runs -- matches
        # the WFG tab's other live-use labels (Session 29), correcting the
        # prior "calibration" framing, which was ambiguous about whether it
        # meant "manual/independent" or "not real hardware."
        # Measured offscreen (Session 38): unwrapped, this label demanded
        # 1332px on its own -- the dominant reason this whole group needed
        # horizontal scrolling, and since the scroll position starts at the
        # left edge, only the label's opening words were visible without
        # scrolling right, with "no visible closing context" (the reported
        # symptom). Wrapping at a width matching the group's own per-field
        # rows fixes both: the caption is now fully visible, and the group's
        # natural width driven by this label drops substantially.
        sweep_header = QLabel(
            "Sweep (FM modulation, manual tab only -- independent from the Experiment tab, "
            "distinct from Frequency Scanning)"
        )
        sweep_header.setWordWrap(True)
        sweep_header.setMaximumWidth(450)
        layout.addWidget(sweep_header)
        layout.addLayout(sweep)
        self._add_tooltip_icons(sweep)
        self._connect_sweep_dual_mode_refresh(
            state["sweep_start_khz"], state["sweep_stop_khz"],
            state["sweep_center_khz"], state["sweep_width_khz"],
        )

        scroll = QScrollArea()
        scroll.setWidgetResizable(False)
        scroll.setMaximumHeight(500)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        return group

    def _connect_sweep_dual_mode_refresh(self, start_widget, stop_widget, center_widget, width_widget) -> None:
        # Start/Stop and Center/Width are two live input paths for the same
        # underlying value -- editing either pair updates the other to match,
        # neither is ever hidden or removed (same "offer both, replace
        # neither" principle as Frequency Scanning's Number of Frequencies
        # vs. Step Size). `guard` prevents the two directions' valueChanged
        # signals from re-triggering each other in a loop.
        guard = {"active": False}

        def sync_center_width_from_start_stop(_value=None) -> None:
            if guard["active"]:
                return
            guard["active"] = True
            try:
                start_khz = start_widget.value()
                stop_khz = stop_widget.value()
                center_widget.setValue((start_khz + stop_khz) / 2.0)
                width_widget.setValue(abs(stop_khz - start_khz))
            finally:
                guard["active"] = False

        def sync_start_stop_from_center_width(_value=None) -> None:
            if guard["active"]:
                return
            guard["active"] = True
            try:
                center_khz = center_widget.value()
                width_khz = width_widget.value()
                start_widget.setValue(center_khz - width_khz / 2.0)
                stop_widget.setValue(center_khz + width_khz / 2.0)
            finally:
                guard["active"] = False

        start_widget.valueChanged.connect(sync_center_width_from_start_stop)
        stop_widget.valueChanged.connect(sync_center_width_from_start_stop)
        center_widget.valueChanged.connect(sync_start_stop_from_center_width)
        width_widget.valueChanged.connect(sync_start_stop_from_center_width)
        # Seed Center/Width from the initial Start/Stop defaults so all four
        # widgets agree before any user edit.
        sync_center_width_from_start_stop()

    def _fm_sweep_settings_from_state(self, state: dict[str, object]) -> FmSweepSettings:
        # Start/Stop and Center/Width are kept in sync (see
        # _connect_sweep_dual_mode_refresh()); reading Start/Stop here is
        # equivalent to reading Center/Width. FmSweepSettings' own FM-node
        # math is unchanged from Session 16 either way.
        start_hz = state["sweep_start_khz"].value() * 1000.0
        stop_hz = state["sweep_stop_khz"].value() * 1000.0
        return FmSweepSettings(
            center_hz=(start_hz + stop_hz) / 2.0,
            width_hz=abs(stop_hz - start_hz),
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
        # Self-evident (Session 41 re-narrowing): "CH1"/"CH2" checkboxes
        # under "Analog In Channels" need no further explanation.
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
        self._add_tooltip_icons(form)

        self.mso_graph = WaveformGraph()
        graph_box = QGroupBox("Waveform")
        graph_layout = QVBoxLayout(graph_box)
        graph_layout.addWidget(self.mso_graph)
        self.mso_text = QPlainTextEdit()
        self.mso_text.setReadOnly(True)
        self.mso_text.setMaximumHeight(90)
        graph_layout.addWidget(self.mso_text)

        # Without an explicit alignment, QHBoxLayout stretches each widget to
        # fill the row's full height -- both boxes were being inflated to
        # 356px even though their own natural content only needs 270px
        # (MSO Configuration) / 305px (Waveform), the same class of dead
        # space as the Initialization tab's Simulation group. AlignTop keeps
        # each at its own natural height instead.
        content.addWidget(controls, 0, Qt.AlignmentFlag.AlignTop)
        content.addWidget(graph_box, 1, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(content)
        layout.addStretch()
        return tab

    def _pump_tab(self) -> QWidget:
        # Restructured from a sparse QGridLayout with individual widgets
        # scattered at hand-picked row/col coordinates (which left large,
        # uneven dead-space regions -- rows/columns with nothing in them --
        # while Flush Settings and STOP sat isolated at the far edges) into
        # balanced group-box columns matching the tab's actual content,
        # eliminating that dead space instead of just capping group sizes
        # (there were no oversized group boxes here to cap -- only one
        # existed, Flush Settings, and it was already naturally sized).
        # This tab's four columns' combined natural width (~2200px, offscreen-
        # measured) is well over the app's default window width (1280px) --
        # WrapLongRows alone (already applied to every column below) still
        # leaves it oversized, and tightening any one column's wrap further
        # was tried and reverted: it shrank that column's width but grew its
        # row heights just enough to squeeze a sibling group below its own
        # minimumSizeHint elsewhere in the same dialog (Session 42 -- caught
        # by test_v2_no_group_box_is_squeezed_below_its_minimum_size_hint).
        # Same fix as every other width/height-constrained group in this file
        # (_wfg_channel_group(), _sequence_group(), _ad_settings_group()):
        # give the content its own QScrollArea instead of force-compressing
        # it, so surplus width scrolls instead of squeezing rows.
        tab = QWidget()
        outer = QVBoxLayout(tab)
        content = QWidget()
        columns = QHBoxLayout(content)
        columns.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Position 1 = Open, Position 2 = Closed (confirmed physical mapping,
        # see instruments.py's Valve class) -- safety-relevant, so spelled out
        # explicitly rather than left for the operator to remember.
        pos1 = QPushButton("Pos1 (Open)")
        pos1.setToolTip("Confirmed physical mapping: position 1 = Open (Valve.set_position(1), instruments.py).")
        pos1.clicked.connect(lambda: self._run_action(lambda progress: self.app.valve.set_position(1), "Valve Pos1 (Open)"))
        pos2 = QPushButton("Pos2 (Closed)")
        pos2.setToolTip("Confirmed physical mapping: position 2 = Closed (Valve.set_position(2), instruments.py).")
        pos2.clicked.connect(lambda: self._run_action(lambda progress: self.app.valve.set_position(2), "Valve Pos2 (Closed)"))
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

        # WrapLongRows on every column's QFormLayout: an offscreen truncation
        # sweep (Session 38) found several row labels here clipped (e.g.
        # "Number of flushes" at 60px actual vs. 204px required) because each
        # column is narrower than a single-row form normally assumes. Wrapping
        # the label onto its own line above the field when needed avoids
        # clipping without widening the columns themselves.
        valve_group = QGroupBox("Valve")
        valve_form = QFormLayout(valve_group)
        valve_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        valve_form.addRow("Valve Pos1 (Open)", pos1)
        valve_form.addRow("ValvePos2 (Closed)", pos2)
        self._add_tooltip_icons(valve_form)
        column1 = QVBoxLayout()
        column1.addWidget(valve_group)
        column1.addWidget(QLabel("Stop Syringe"))
        column1.addWidget(stop)
        column1.addStretch()

        pump_group = QGroupBox("Pump")
        pump_form = QFormLayout(pump_group)
        pump_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        pump_form.addRow("Refill", refill)
        pump_form.addRow("Empty", empty)
        self._add_tooltip_icons(pump_form)
        syringe_group = QGroupBox("Syringe")
        syringe_form = QFormLayout(syringe_group)
        syringe_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        syringe_form.addRow("Syringe", self.syringe)
        syringe_form.addRow("Custom Volume (ml)", self.custom_syringe_volume_ml)
        syringe_form.addRow("Custom Inner Diameter (mm)", self.custom_syringe_inner_diameter_mm)
        syringe_form.addRow("Custom Max Piston Stroke (mm)", self.custom_syringe_stroke_mm)
        syringe_form.addRow("ConfigureSyringe", configure)
        self._add_tooltip_icons(syringe_form)
        column2 = QVBoxLayout()
        column2.addWidget(pump_group)
        column2.addWidget(syringe_group)
        column2.addStretch()

        flow_group = QGroupBox("Flow Control")
        flow_form = QFormLayout(flow_group)
        flow_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        flow_form.addRow("Flow Rate (-=aspirate, +=dispense)", self.flow_rate)
        flow_form.addRow("Generate Flow", generate)
        flow_form.addRow("Level(ml)", self.level_ml)
        flow_form.addRow("Go to Level", go)
        flow_form.addRow("Reference move", ref)
        self._add_tooltip_icons(flow_form)
        column3 = QVBoxLayout()
        column3.addWidget(flow_group)
        column3.addStretch()

        flush_count_group = QGroupBox("Flush")
        flush_count_form = QFormLayout(flush_count_group)
        flush_count_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        flush_count_form.addRow("Number of flushes", self.flush_count)
        flush_count_form.addRow("Flush", flush)
        self._add_tooltip_icons(flush_count_form)
        column4 = QVBoxLayout()
        column4.addWidget(flush_count_group)
        column4.addWidget(self._flush_group())
        column4.addStretch()

        columns.addLayout(column1)
        columns.addLayout(column2)
        columns.addLayout(column3)
        columns.addLayout(column4)
        columns.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(False)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        return tab

    def _flush_group(self) -> QGroupBox:
        group = QGroupBox("Flush Settings")
        form = QFormLayout(group)
        form.addRow("Flush Flowrate(uL)", self.flush_flowrate)
        form.addRow("flush volume (ml)", self.flush_volume)
        form.addRow("WaitAfterFlush", self.wait_after_flush)
        self._add_tooltip_icons(form)
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
        image_continuous = self._live_image_continuous_checkbox()
        image_continuous.toggled.connect(self._set_image_continuous)
        row.addWidget(image)
        row.addWidget(QLabel("Image Continous"))
        row.addWidget(image_continuous)
        # word-wrap: this HBoxLayout row has no wrap-long-rows equivalent
        # (that's a QFormLayout-only policy) -- an offscreen truncation
        # sweep (Session 38) found this label clipped at 324px actual vs.
        # 744px required. Give it a fixed width to wrap into instead of one
        # long unbroken line.
        hint_label = QLabel("If the button is grayed out, press the configure camera button")
        hint_label.setWordWrap(True)
        hint_label.setMaximumWidth(260)
        row.addWidget(hint_label)
        row.addStretch()
        return group

    def _live_image_continuous_checkbox(self) -> QCheckBox:
        try:
            self.image_continuous.isChecked()
        except RuntimeError:
            # v2 opens the validated v1 Camera tab as a late-created manual
            # dialog. Under offscreen Qt, the unparented checkbox created
            # during _build_state() can occasionally lose its C++ object
            # before that dialog is built; recreate only that dead widget.
            self.image_continuous = QCheckBox("Off/On")
            self.image_continuous.setChecked(False)
        return self.image_continuous

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
        self._add_tooltip_icons(form)
        grid.addWidget(QLabel("ExposureTime(ms)"), 0, 1)
        grid.addWidget(self._wrap_with_tooltip_icon(self.exposure_ms), 1, 1)
        grid.addWidget(QLabel("Configure Camera"), 0, 2)
        grid.addWidget(configure, 1, 2)
        grid.addWidget(QLabel("Center ROI"), 2, 1)
        grid.addWidget(self._wrap_with_tooltip_icon(self.center_roi), 3, 1)
        # Removed (Session 36): a static "476 is Vertical is max for 100 fps"
        # label, confirmed stale/hardcoded since Session 19 -- the real,
        # live-computed equivalent check is Application._check_camera_timing_budget(),
        # which reads the actual DCAM readout time and current exposure. No
        # replacement hint added here: this manual Camera tab has no "Camera
        # FPS" field of its own to compare against (that's an Experiment-tab
        # concept), and this tab may be shown before the camera is connected,
        # so a live query isn't reliably available here without adding a new
        # hardcoded fallback in its place -- exactly what was asked to avoid.
        return group

    def _conversion_group(self) -> QGroupBox:
        group = QGroupBox("Conversion Policy (Default)")
        layout = QVBoxLayout(group)
        form = QFormLayout()
        # WrapLongRows: wrap a row's label onto its own line above the field
        # instead of clipping it when the column is narrower than the label
        # needs (found via an offscreen truncation sweep, Session 38).
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.addRow("Conversion Method", self.conversion_method)
        form.addRow("Minimum Value", self.conversion_min)
        form.addRow("Maximum Value", self.conversion_max)
        form.addRow("# Shifts", self.conversion_shifts)
        adjust = QPushButton("Adjust")
        adjust.clicked.connect(self._adjust_camera_preview)
        self.conversion_method.currentTextChanged.connect(lambda _value: self._update_conversion_controls())
        layout.addLayout(form)
        self._add_tooltip_icons(form)
        layout.addWidget(QLabel("Adjust Intensity in image"))
        layout.addWidget(adjust, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addStretch()
        self._update_conversion_controls()
        return group

    def _sequence_group(self) -> QGroupBox:
        # Giving sequence_note below enough row-span to render its wrapped
        # text in full (Session 38 fix) pushed this group's own
        # minimumSizeHint past what the Camera tab's grid can give it,
        # tripping the same 0-1px row-collapse failure mode fixed for
        # _ad_settings_group() in an earlier session. Same fix here: the
        # grid goes on its own content widget, wrapped in a QScrollArea,
        # instead of directly on the group.
        group = QGroupBox("Sequence")
        outer = QVBoxLayout(group)
        content = QWidget()
        grid = QGridLayout(content)
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
        settings.addRow("ExposureTime(ms) (unused)", self.sequence_exposure_ms)
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
        # Wrapped text needs more height than a single un-spanned grid row
        # gave it (found via an offscreen sweep, Session 38: 48px actual vs.
        # 68px required at this width) -- span 3 rows so the wrapped label
        # has room to render in full.
        grid.addWidget(sequence_note, 1, 2, 3, 1)
        grid.addLayout(settings, 4, 2, 7, 1)
        self._add_tooltip_icons(settings)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(460)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        return group

    # --- Z-scan calibration tab (Phase 4) ---

    def _zscan_tab(self) -> QWidget:
        tab = QWidget()
        grid = QGridLayout(tab)
        grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        grid.addWidget(self._zscan_parameters_group(), 0, 0)
        grid.addWidget(self._zscan_control_group(), 0, 1)
        grid.setColumnStretch(2, 1)
        return tab

    def _zscan_parameters_group(self) -> QGroupBox:
        group = QGroupBox("Z-Scan Calibration Parameters")
        outer = QVBoxLayout(group)
        form = QFormLayout()
        form.addRow("Z Start (um)", self.zscan_z_start_um)
        form.addRow("Z End (um)", self.zscan_z_end_um)
        form.addRow("Step Size (um)", self.zscan_step_size_um)
        form.addRow("Exposure Time (ms)", self.zscan_exposure_ms)
        output_row = QHBoxLayout()
        output_row.setContentsMargins(0, 0, 0, 0)
        output_row.addWidget(self._wrap_with_tooltip_icon(self.zscan_output_dir))
        browse = QPushButton("...")
        browse.clicked.connect(lambda: self._browse_folder(self.zscan_output_dir))
        output_row.addWidget(browse)
        output_container = QWidget()
        output_container.setLayout(output_row)
        form.addRow("Output Directory", output_container)
        outer.addLayout(form)
        self._add_tooltip_icons(form)
        outer.addWidget(self.zscan_range_status)
        return group

    def _zscan_control_group(self) -> QGroupBox:
        group = QGroupBox("Scan Control")
        layout = QVBoxLayout(group)
        query_range = QPushButton("Query Piezo Range")
        query_range.clicked.connect(self._query_zscan_range)
        start = QPushButton("Start Z-Scan")
        start.clicked.connect(self._start_zscan)
        abort = QPushButton("Abort Z-Scan")
        abort.clicked.connect(self._abort_zscan)
        layout.addWidget(query_range)
        layout.addWidget(start)
        layout.addWidget(abort)
        hint = QLabel(
            "Requires the Camera tab's own Configure Camera to have already been run this session -- "
            "this scan reuses the existing camera connection, it does not open one of its own. Query "
            "Piezo Range connects briefly to read the device's live MaxTravel before you commit to a "
            "scan; Start Z-Scan also does this on its own connect if you skip that step."
        )
        hint.setWordWrap(True)
        hint.setMaximumWidth(260)
        layout.addWidget(hint)
        layout.addStretch()
        return group

    def _query_zscan_range(self) -> None:
        from .thorlabs_piezo import PiezoStage, PiezoStageError

        piezo = PiezoStage()
        try:
            piezo.connect()
        except PiezoStageError as exc:
            self.app.check_loop_error(str(exc))
            self._set_status(f"Z-scan error: piezo connect failed: {exc}")
            return
        max_travel_um = piezo.max_travel_um
        try:
            piezo.disconnect()
        except Exception:  # pragma: no cover - defensive cleanup path
            pass
        self._apply_zscan_range(max_travel_um)
        self._set_status("Piezo range queried.")

    def _apply_zscan_range(self, max_travel_um: float | None) -> None:
        if max_travel_um is None:
            return
        self.zscan_z_start_um.setRange(0.0, max_travel_um)
        self.zscan_z_end_um.setRange(0.0, max_travel_um)
        self.zscan_z_start_um.setEnabled(True)
        self.zscan_z_end_um.setEnabled(True)
        self.zscan_range_status.setText(f"Valid range: 0.00 - {max_travel_um:.2f} um (live-read from device MaxTravel)")

    def _start_zscan(self) -> None:
        if self._busy_count:
            self._set_status("Busy")
            return
        from .thorlabs_piezo import PiezoStage, PiezoStageError

        if getattr(self.app.camera, "handle", None) is None:
            self._set_status("Z-scan error: camera is not initialized -- run Configure Camera on the Camera tab first.")
            return

        output_dir = Path(self.zscan_output_dir.text())
        step_size_um = float(self.zscan_step_size_um.value())
        exposure_ms = float(self.zscan_exposure_ms.value())

        piezo = PiezoStage()
        try:
            piezo.connect()
        except PiezoStageError as exc:
            self.app.check_loop_error(str(exc))
            self._set_status(f"Z-scan error: piezo connect failed: {exc}")
            return

        # Apply/refresh the live MaxTravel-based range before reading Z
        # Start/End -- on a first click (fields still disabled from a fresh
        # tab, never queried) this both enables the fields and means the
        # values read below are 0.0/0.0 (safe, just a degenerate single-frame
        # scan); Query Piezo Range lets a user populate real values before
        # ever clicking Start.
        self._apply_zscan_range(piezo.max_travel_um)
        z_start_um = float(self.zscan_z_start_um.value())
        z_end_um = float(self.zscan_z_end_um.value())

        # Real ClosedLoop confirmation dialog (Session 45/46's design
        # decision), shown synchronously here -- before the scan's own
        # background QThread starts -- since a QMessageBox must be shown
        # from the UI thread, not from inside _run_action()'s worker thread.
        if piezo.needs_closed_loop_confirmation():
            answer = QMessageBox.question(
                self,
                "Confirm ClosedLoop Switch",
                f"Piezo stage is currently in {piezo.position_control_mode} mode. Z-scan requires "
                "ClosedLoop mode for position accuracy. Switch now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                piezo.disconnect()
                self._set_status("Z-scan cancelled: ClosedLoop switch declined.")
                return
            try:
                piezo.switch_to_closed_loop()
            except PiezoStageError as exc:
                piezo.disconnect()
                self.app.check_loop_error(str(exc))
                self._set_status(f"Z-scan error: ClosedLoop switch failed: {exc}")
                return

        self._zscan_abort_requested = False
        # ClosedLoop is a control-mode prerequisite, not permission to move.
        # Ask separately and synchronously in the GUI thread before the
        # background scan worker can configure the camera or move the PPC001.
        answer = QMessageBox.question(
            self,
            "Confirm PPC001 Motion",
            f"This will move the PPC001 piezo from {z_start_um:.2f} to {z_end_um:.2f} um "
            f"in {step_size_um:.2f} um steps and capture calibration images. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            piezo.disconnect()
            self._set_status("Z-scan cancelled: PPC001 motion not authorized.")
            return

        self._run_action(
            lambda progress: self._run_zscan(piezo, z_start_um, z_end_um, step_size_um, exposure_ms, output_dir),
            "Running Z-scan",
        )

    def _run_zscan(
        self,
        piezo,
        z_start_um: float,
        z_end_um: float,
        step_size_um: float,
        exposure_ms: float,
        output_dir: Path,
    ) -> str:
        from .piezo_zscan import ZScanCalibration

        scan = ZScanCalibration(
            piezo=piezo,
            camera=self.app.camera,
            confirm_motion=lambda: True,
            should_abort=lambda: self._zscan_abort_requested,
        )
        try:
            results = scan.run(
                z_start_um=z_start_um,
                z_end_um=z_end_um,
                step_size_um=step_size_um,
                output_dir=output_dir,
                exposure_ms=exposure_ms,
            )
        finally:
            try:
                piezo.disconnect()
            except Exception:  # pragma: no cover - defensive cleanup path
                pass
        return f"Z-scan complete: {len(results)} frames written to {output_dir}"

    def _abort_zscan(self) -> None:
        self._zscan_abort_requested = True
        self._set_status("Z-scan abort requested")

    def _experiment_tab(self) -> QWidget:
        tab = QWidget()
        grid = QGridLayout(tab)
        grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        grid.addWidget(QLabel("Elapsed Time"), 0, 0)
        grid.addWidget(self._elapsed_time_label(), 1, 0)
        grid.addWidget(QLabel("Time Left"), 0, 1)
        grid.addWidget(self._time_left_label(), 1, 1)
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
        grid.addWidget(self._wrap_with_tooltip_icon(self.series_path), 6, 0, 1, 5)
        grid.addWidget(browse, 6, 5)
        grid.addWidget(self._ad_settings_group(), 7, 0, 1, 2)
        grid.addWidget(self._experiment_settings_column(), 7, 2, 2, 1)
        grid.addWidget(self._camera_start_group(), 7, 4, 2, 1)
        grid.addWidget(QLabel("Average FPS"), 10, 5)
        grid.addWidget(self.average_fps, 11, 5)
        # Measured offscreen (Session 38): only a ~5px safety margin between
        # this label's required text width (168px) and its actual rendered
        # width (173px) at the app's own minimum window size (980x680) --
        # not conclusively clipped in this environment, but fragile enough to
        # explain a reported "first character cut off" screenshot at a
        # slightly narrower real window. setMinimumWidth gives real headroom.
        waveform_graph_label = QLabel("Waveform Graph")
        waveform_graph_label.setMinimumWidth(200)
        grid.addWidget(waveform_graph_label, 10, 0)
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
        self._add_tooltip_icons(top)

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
        self._add_tooltip_icons(carrier)

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
        self._add_tooltip_icons(trigger)

        if channel_label == "CH0":
            sweep = QFormLayout()
            sweep.addRow(self.exp_sweep_enable)
            sweep.addRow(f"{channel_label} Sweep Start Frequency (kHz)", self.exp_sweep_start_khz)
            sweep.addRow(f"{channel_label} Sweep Stop Frequency (kHz)", self.exp_sweep_stop_khz)
            sweep.addRow(f"{channel_label} Sweep Center Frequency (kHz)", self.exp_sweep_center_khz)
            sweep.addRow(f"{channel_label} Sweep Width (kHz)", self.exp_sweep_width_khz)
            sweep.addRow(f"{channel_label} Sweep Time (ms)", self.exp_sweep_time_ms)
            sweep.addRow(f"{channel_label} Sweep Type", self.exp_sweep_type)
            # Unlike the manual WFG tab's own Sweep group, enabling this one
            # DOES apply to real automated Experiment runs (Session 16) --
            # the prior "calibration" wording here was misleading about that.
            # Wrapped for the same reason as the manual WFG tab's matching
            # header (Session 38): unwrapped this needed 1356px on its own,
            # leaving "no visible closing context" without scrolling right.
            experiment_sweep_header = QLabel(
                "Sweep (FM modulation, applied to real automated Experiment runs when enabled -- "
                "distinct from Frequency Scanning)"
            )
            experiment_sweep_header.setWordWrap(True)
            experiment_sweep_header.setMaximumWidth(450)
            layout.addWidget(experiment_sweep_header)
            layout.addLayout(sweep)
            self._add_tooltip_icons(sweep)
            self._connect_sweep_dual_mode_refresh(
                self.exp_sweep_start_khz, self.exp_sweep_stop_khz,
                self.exp_sweep_center_khz, self.exp_sweep_width_khz,
            )

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
        # Moved here from an isolated spot elsewhere in the tab's grid --
        # GlobalExposure belongs next to the exposure setting it modifies.
        form.addRow("GlobalExposure", self.global_exposure)
        self._add_tooltip_icons(form)
        return group

    def _experiment_flush_group(self) -> QGroupBox:
        group = QGroupBox("Flush settings")
        form = QFormLayout(group)
        form.addRow("Flush after capture", self.exp_flush_enabled)
        form.addRow("Flush Flowrate(uL)", self.exp_flush_flowrate)
        form.addRow("flush volume (ml)", self.exp_flush_volume)
        form.addRow("WaitAfterFlush", self.exp_wait_after_flush)
        self._add_tooltip_icons(form)
        return group

    def _camera_start_group(self) -> QGroupBox:
        # Offscreen sweep at the app's own documented minimum window size
        # (980x680, self.setMinimumSize()) -- not just the 1280x820 default
        # the existing generic squeeze guard happened to check -- found this
        # group squeezed to 252px actual vs. 346px required (11 rows: the
        # Dynamic Camera Start Time toggle + 10 array fields). Same fix as
        # every other group hitting this failure mode (Sessions 28/29/34/38):
        # content moves onto its own QScrollArea instead of laying directly
        # into the group, so it can lay out at full natural height internally
        # and scroll rather than being compressed.
        group = QGroupBox("Camera Start Array(s)")
        outer = QVBoxLayout(group)
        content = QWidget()
        form = QFormLayout(content)
        # Moved here from an isolated spot elsewhere in the tab's grid --
        # Dynamic Camera Start Time is the toggle that controls whether this
        # array is used at all (see _experiment_do_clock_config()), so it
        # belongs directly above the array it controls.
        form.addRow("Dynamic Camera Start Time", self.dynamic_camera_start)
        for widget in self.camera_start_array:
            form.addRow(widget)
        self._add_tooltip_icons(form)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(360)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        return group

    def _experiment_frequency_scan_group(self) -> QGroupBox:
        group = QGroupBox("Frequency Scanning (Dynamic Frequency, Ch1 only)")
        form = QFormLayout(group)
        form.addRow(self.exp_freq_scan_enable)
        form.addRow("Start Frequency (kHz)", self.exp_freq_scan_start_khz)
        form.addRow("Stop Frequency (kHz)", self.exp_freq_scan_stop_khz)
        form.addRow("Number of Frequencies", self.exp_freq_scan_count)
        form.addRow("Step Size (kHz) (0 = use Number of Frequencies)", self.exp_freq_scan_step_khz)
        self._connect_frequency_scan_count_display_refresh()
        self._add_tooltip_icons(form)
        return group

    def _experiment_fm_sweep_group(self) -> QGroupBox:
        # Category 7 (Session 39): binds the exact same self.exp_sweep_*
        # widgets already used by _add_experiment_channel_sections()'s CH0
        # inline Sweep section (qt_ui.py's own Experiment tab) -- not new
        # widgets, not new state, just a second, standalone QGroupBox surface
        # for qt_ui_v2.py to reach them from, since v2 never calls
        # _experiment_tab()/_add_experiment_channel_sections() at all (its
        # own AD2 Output Parameters table is a separately-built view). This
        # is the same "no controls at all in v2" gap Session 24 already found
        # and fixed once for Symmetry/Phase/Repeat Trigger -- FM Sweep and
        # Frequency Scanning (below) were the two remaining Experiment-tab
        # features never carried into v2's own view, flagged since Session 25
        # (FM Sweep) but never fixed, and never even flagged for Frequency
        # Scanning (added later, Session 34, after v2's own AD2 table was
        # last touched). v1's existing inline CH0 section is left completely
        # unchanged -- this is an additive, independent builder, not a
        # refactor of v1's tested layout.
        group = QGroupBox(
            "Sweep (FM modulation, applied to real automated Experiment runs when enabled -- "
            "distinct from Frequency Scanning) -- CH0 only"
        )
        form = QFormLayout(group)
        form.addRow(self.exp_sweep_enable)
        form.addRow("Sweep Start Frequency (kHz)", self.exp_sweep_start_khz)
        form.addRow("Sweep Stop Frequency (kHz)", self.exp_sweep_stop_khz)
        form.addRow("Sweep Center Frequency (kHz)", self.exp_sweep_center_khz)
        form.addRow("Sweep Width (kHz)", self.exp_sweep_width_khz)
        form.addRow("Sweep Time (ms)", self.exp_sweep_time_ms)
        form.addRow("Sweep Type", self.exp_sweep_type)
        # v1's own call lives inside _add_experiment_channel_sections(), which
        # qt_ui_v2.MainWindowV2 never invokes -- this window needs its own
        # independent wiring of the same widgets, exactly like
        # _v2_acquisition_group() independently builds its own Camera Start
        # Array(s) group rather than calling qt_ui.py's _camera_start_group().
        self._connect_sweep_dual_mode_refresh(
            self.exp_sweep_start_khz, self.exp_sweep_stop_khz,
            self.exp_sweep_center_khz, self.exp_sweep_width_khz,
        )
        self._add_tooltip_icons(form)
        return group

    def _connect_frequency_scan_count_display_refresh(self) -> None:
        # Category 5 (Session 39): Step Size (when > 0) silently overrode the
        # actual point count used by _experiment_frequency_scan_list_hz()
        # without ever updating what "Number of Frequencies" displayed --
        # unlike FM Sweep's Start/Stop<->Center/Width, which Session 38
        # fixed to stay genuinely in sync in both directions, this field
        # could show a stale, misleading count. Not made fully bidirectional
        # like FM Sweep: doing so (auto-deriving a nonzero Step Size from an
        # edited Count) would silently flip Step Size from "0 = not used" to
        # "active", changing which field drives future edits without the
        # user asking for that -- a real behavior change, not just a display
        # fix. Instead, this is one-directional and honest: whenever
        # Start/Stop/Step change and Step Size is actively driving the count
        # (> 0), "Number of Frequencies" is updated to show the real
        # resulting count. Editing "Number of Frequencies" directly continues
        # to work exactly as before when Step Size is 0 (unchanged).
        def refresh_count_display(_value=None) -> None:
            step_khz = self.exp_freq_scan_step_khz.value()
            if step_khz <= 0:
                return
            start_khz = self.exp_freq_scan_start_khz.value()
            stop_khz = self.exp_freq_scan_stop_khz.value()
            count = max(round(abs(stop_khz - start_khz) / step_khz) + 1, 1)
            if self.exp_freq_scan_count.value() != count:
                self.exp_freq_scan_count.setValue(count)

        self.exp_freq_scan_start_khz.valueChanged.connect(refresh_count_display)
        self.exp_freq_scan_stop_khz.valueChanged.connect(refresh_count_display)
        self.exp_freq_scan_step_khz.valueChanged.connect(refresh_count_display)
        refresh_count_display()

    def _error_panel(self) -> QGroupBox:
        group = QGroupBox("Error Out")
        group.setMaximumWidth(280)
        layout = QVBoxLayout(group)
        self.error_log = HistoryLogWidget()
        self.error_log.setToolTip(
            "Full session history of every status/code/source event, newest at the "
            "bottom -- not just the most recent one. code is always '0' when "
            "status='OK', '1' on any caught exception -- not a real DCAM/AD2/Qmix "
            "error code, just a boolean flag (_handle_worker_finished())."
        )
        layout.addWidget(self.error_log)
        return group

    def _append_error_entry(self, status: str, code: str, source: str) -> None:
        text = f"{status} | code={code}"
        if source:
            text += f" | {source}"
        self.error_log.add_entry(text)

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
        step_khz = self.exp_freq_scan_step_khz.value()
        if step_khz > 0:
            # Step Size is a Python-only alternative to Number of Frequencies
            # (not part of the LabVIEW spec): when set, it takes precedence
            # and the point count is derived from it instead of read directly
            # from the count widget, rounded to the nearest whole point.
            count = max(round(abs(stop_hz - start_hz) / (step_khz * 1000.0)) + 1, 1)
        else:
            count = self.exp_freq_scan_count.value()
        if count <= 1:
            return [start_hz] * count
        step = (stop_hz - start_hz) / (count - 1)
        return [start_hz + step * index for index in range(count)]

    def _experiment_fm_sweep_settings(self) -> FmSweepSettings:
        # Start/Stop and Center/Width are kept in sync by
        # _connect_sweep_dual_mode_refresh(); reading Start/Stop here is
        # equivalent to reading Center/Width. FmSweepSettings and everything
        # downstream of it are unchanged from Session 16.
        start_hz = self.exp_sweep_start_khz.value() * 1000.0
        stop_hz = self.exp_sweep_stop_khz.value() * 1000.0
        return FmSweepSettings(
            center_hz=(start_hz + stop_hz) / 2.0,
            width_hz=abs(stop_hz - start_hz),
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

    def _update_custom_syringe_volume_enabled(self) -> None:
        is_custom = self.syringe.currentText() == "Custom"
        self.custom_syringe_volume_ml.setEnabled(is_custom)
        self.custom_syringe_inner_diameter_mm.setEnabled(is_custom)
        self.custom_syringe_stroke_mm.setEnabled(is_custom)

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
        # Session 51: config_wfg()/wfg_start_stop_all_ch() -> WaveFormsBackend.
        # configure_wfg() now sets channel.out_of_range=True per channel
        # whenever the real device's own live AnalogOutNodeFrequencyInfo()/
        # AmplitudeInfo() range required clamping the requested amplitude/
        # frequency -- surfaced here so an operator never unknowingly runs
        # with a silently-substituted value (the WaveForms SDK itself never
        # errors on this, it just clamps and reports success).
        if not config.check_valid():
            # channel_index is 0-based internally; this project's own UI/TDMS
            # labeling convention (Ch1/Ch2, _wfg_properties()) is 1-based.
            out_of_range_channels = [
                f"Ch{channel.channel_index + 1}" for channel in config.channels if channel.out_of_range
            ]
            return f"WFG configured -- WARNING: amplitude/frequency clamped to device limits on {', '.join(out_of_range_channels)}"
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
        # Widget values must be read here, on the main/UI thread, before
        # handing off to _run_action()'s background QThread -- Session 44:
        # "Custom" now also sends real geometry (inner_diameter_mm/
        # max_piston_stroke_mm), not just {"name": syringe}, since
        # configure_syringe() has no preset to fall back on for it.
        syringe = self.syringe.currentText()
        config: dict[str, object] = {"name": syringe}
        if syringe == "Custom":
            config["inner_diameter_mm"] = float(self.custom_syringe_inner_diameter_mm.value())
            config["max_piston_stroke_mm"] = float(self.custom_syringe_stroke_mm.value())
        self._run_action(lambda progress: self._configure_syringe(config), "Configuring syringe")

    def _configure_syringe(self, config: dict[str, object]) -> str:
        self.app.pump.configure_syringe(config)
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
                # Attribute the count to whichever field actually produced it --
                # Step Size overrides Number of Frequencies when set above 0
                # (see _experiment_frequency_scan_list_hz()); the "Number of
                # Frequencies" display is kept in sync with that real count
                # (_connect_frequency_scan_count_display_refresh()), but the
                # error text itself must name the true source too, not always
                # blame the same field regardless of which one is driving.
                count_source = (
                    "Step Size" if self.exp_freq_scan_step_khz.value() > 0 else "Number of Frequencies"
                )
                raise ValueError(
                    f"Frequency Scanning is enabled with {len(frequency_scan_hz)} frequencies "
                    f"({count_source}) but Repeats is set to {repeats}; they must match "
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
        # "experiment_series_active" progress kind brackets the entire method
        # body (try/finally, so it clears on every exit path: normal
        # completion, ExperimentSeriesAborted, or a raised RuntimeError) --
        # this is the ground truth qt_ui_v2.py's "Experiment running"
        # indicator now reads (see _handle_worker_progress()), instead of
        # its old "experiment" in self.app.status.lower() heuristic, which
        # went stale the instant Abort was clicked (Abort's own "Aborting..."
        # status overwrites app.status while the current repeat, if any, may
        # still genuinely be in flight). Emitted via the existing
        # progress-signal mechanism (not set directly) since this method
        # runs on a background QThread (ActionWorker) and progress.emit()
        # is the established way this codebase marshals state back to the
        # main/UI thread.
        if progress:
            progress("experiment_series_active", True)
        try:
            return self._run_experiment_series_body(series, total_frames, config, progress)
        finally:
            if progress:
                progress("experiment_series_active", False)

    def _run_experiment_series_body(
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
        self._append_error_entry("ERROR", "1", message)
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
        self._append_error_entry("ERROR", "1", message)
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
            self._append_error_entry("OK", "0", "")
            self._set_status(status)
        else:
            self._append_error_entry("ERROR", "1", error)
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
        elif kind == "experiment_series_active":
            self._experiment_series_active = bool(value)
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
            self._append_error_entry("OK", "0", "")
            if status and status != "Ready":
                self._set_status(status)
            else:
                self._refresh_status()
        else:
            self.app.check_loop_error(error)
            self._append_error_entry("ERROR", "1", error)
            self._set_status("Error")
        if self._busy_count == 0 and self._controls_disabled_for_action and not self._shutdown_in_progress:
            self._set_controls_enabled(True)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API name
        self._window_was_shown = True
        super().showEvent(event)

    def _safe_call(self, action) -> None:
        try:
            action()
            self._append_error_entry("OK", "0", "")
        except Exception as exc:  # pragma: no cover - UI feedback path
            self.app.check_loop_error(exc)
            self._append_error_entry("ERROR", "1", str(exc))
        finally:
            self._refresh_status()

    def _set_status(self, status: str) -> None:
        self.app.fire_status_event(status)
        self._refresh_status()

    def _refresh_status(self) -> None:
        self.status.add_entry(self.app.status)

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
                # Frequency Scanning (Session 44): added as new, purely
                # additive keys under the same "experiment" dict every other
                # Experiment-tab field already lives in -- no schema_version
                # bump needed (matches how Symmetry/Phase/Repeat Trigger were
                # added in Session 22 without one; the version-2 bump was
                # only ever for the Hz->kHz *meaning* change of an existing
                # key, not for adding new ones). "freq_scan_enable" is
                # included alongside the task's named four fields (Start/
                # Stop/Number of Frequencies/Step Size) so the feature's
                # on/off state persists along with its values, matching
                # every other toggle+values group in this dict (wfg
                # "enable", mso "ch1_enabled", experiment "ch1_enable").
                "freq_scan_enable": self.exp_freq_scan_enable.isChecked(),
                "freq_scan_start_khz": self.exp_freq_scan_start_khz.value(),
                "freq_scan_stop_khz": self.exp_freq_scan_stop_khz.value(),
                "freq_scan_count": self.exp_freq_scan_count.value(),
                "freq_scan_step_khz": self.exp_freq_scan_step_khz.value(),
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
                "freq_scan_start_khz": self.exp_freq_scan_start_khz,
                "freq_scan_stop_khz": self.exp_freq_scan_stop_khz,
                "freq_scan_count": self.exp_freq_scan_count,
                "freq_scan_step_khz": self.exp_freq_scan_step_khz,
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
                ("freq_scan_enable", self.exp_freq_scan_enable),
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
                    self._append_error_entry("ERROR", "1", str(exc))
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
