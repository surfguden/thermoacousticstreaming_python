from __future__ import annotations

import html
import json
import logging
import math
import queue
import sys
import threading
import time
from dataclasses import asdict
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
    waveform_parameter_policy,
    coerce_do_config,
    coerce_wfg_config,
)
from .application import STEP_ORDER, STEP_SAVE_RESULTS, Application
from .camera import SubRegion
from .experiment_planning import (
    ExperimentCameraDefaults, ExperimentRequest, build_independent_run_plan,
    legacy_series_from_run_plan, temperature_series_from_request,
)
from .hardware_factory import HardwareRuntimeConfig, apply_hardware_bundle, build_hardware_bundle
from .hardware_config import ZStageBackend, default_hardware_config
from .hw_logging import action_scope
from .instruments import SimulatedAD2Sdk
from .tec import TEC_TARGET_MAX_C, TEC_TARGET_MIN_C
from .workflows import Experiment2, ExperimentSeries2, FlushSettings, SeriesLifecycleManifest, TemperatureSeries


logger = logging.getLogger(__name__)

SETTINGS_PATH = Path(__file__).resolve().parents[2] / ".thermo_acoustic_ui.json"
WFG_TRIGGER_SOURCE_OPTIONS = ["trigsrcNone", "trigsrcPC", "trigsrcAnalogIn", "trigsrcDigitalIn"]
CONVERSION_METHOD_OPTIONS = ["Native (No Auto Scaling)", "Full Dynamic", "90% Dynamic", "Fixed Range", "Downshift"]
LEGACY_AUTHORITY = "LEGACY_AUTHORITY"
SHARED_PLAN_VIA_ADAPTER = "SHARED_PLAN_VIA_ADAPTER"
# Internal migration seam; deliberately not an operator-facing setting.
EXPERIMENT_PLANNING_AUTHORITY = SHARED_PLAN_VIA_ADAPTER


def _format_duration_s(seconds: float, *, round_up: bool = False) -> str:
    """Format a non-negative duration for the experiment stopwatch displays."""
    bounded = max(float(seconds), 0.0)
    whole_seconds = math.ceil(bounded) if round_up else math.floor(bounded)
    hours, remainder = divmod(whole_seconds, 3600)
    minutes, seconds_part = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds_part:02d}"


def _programmed_repeat_duration_s(experiment: Experiment2) -> float:
    """Return the display-only programmed duration estimate for one repeat.

    Camera capture, WFG, and digital outputs overlap; the longest requested
    capture/output window is the acquisition contribution. Camera Start is
    currently metadata only and is therefore not added. A requested flush
    follows acquisition, so its programmed pump travel and post-flush wait are
    additive. Invalid/non-finite timing remains Application's concern: this
    estimator returns a conservative zero contribution instead of changing
    experiment validation or execution semantics.
    """
    ad2_duration_s = 0.0
    wfg_config = coerce_wfg_config(experiment.wfg_config)
    if wfg_config.running:
        for channel in wfg_config.channels:
            if not channel.carrier.enable:
                continue
            sec_run = float(channel.trigger.sec_run)
            sec_wait = float(channel.trigger.sec_wait)
            if math.isfinite(sec_run) and math.isfinite(sec_wait):
                ad2_duration_s = max(ad2_duration_s, max(sec_run, 0.0) + max(sec_wait, 0.0))

    do_config = coerce_do_config(experiment.do_clock_settings)
    if do_config.running:
        for channel in do_config.channels:
            if not channel.enable:
                continue
            sec_run = float(channel.trigger.sec_run)
            sec_wait = float(channel.trigger.sec_wait)
            if math.isfinite(sec_run) and math.isfinite(sec_wait):
                ad2_duration_s = max(ad2_duration_s, max(sec_run, 0.0) + max(sec_wait, 0.0))

    camera_duration_s = 0.0
    sequence = experiment.sequence_settings or {}
    if experiment.camera_enabled:
        frames = float(sequence.get("frames", 0.0) or 0.0)
        camera_fps = float(sequence.get("camera_fps", 0.0) or 0.0)
        if math.isfinite(frames) and math.isfinite(camera_fps) and frames > 0 and camera_fps > 0:
            camera_duration_s = frames / camera_fps

    acquisition_duration_s = max(ad2_duration_s, camera_duration_s)

    flush_duration_s = 0.0
    settings = experiment.flush_settings
    if experiment.flush_enabled and settings.flush_flowrate > 0:
        pump_travel_s = (settings.flush_volume_ml * 1000.0 / settings.flush_flowrate) * 60.0
        flush_duration_s = max(pump_travel_s, 0.0) + max(settings.wait_after_flush_s, 0.0)

    return acquisition_duration_s + flush_duration_s


def _programmed_series_duration_s(experiments: list[Experiment2]) -> float:
    try:
        return sum(_programmed_repeat_duration_s(experiment) for experiment in experiments)
    except Exception as exc:
        # This estimate must never become a new validation gate. The real
        # Application path remains responsible for rejecting malformed timing;
        # a display-only calculation failure simply starts from an unknown/zero
        # estimate and leaves elapsed time fully functional.
        logger.warning("Could not derive programmed series duration for the UI estimate: %s", exc)
        return 0.0


# A systematic offscreen sweep (Session 38) found nearly every QDoubleSpinBox
# in the app had a real sizeHint() up to 252px while capped at
# setMaximumWidth(125) -- about half the width actually needed, so a value
# like "1900.000" rendered as "1900." (the trailing digits had nowhere to
# go). 260px comfortably covers every sizeHint measured across every tab at
# the time of that sweep, with a small margin.
_SPIN_MAX_WIDTH = 260

# UI layout audit round 3, Step 1b/2b (2026-08-02): the WFG tab's and
# Experiment tab's Frequency/Amplitude/Offset/Symmetry/Phase fields (both
# channels, both tabs) sat at the shared _SPIN_MAX_WIDTH ceiling above,
# which was sized for this app's widest worst-case field elsewhere --
# these fields only ever display 3-5 digit values, measured at 114-150px
# of realistic content need (current value + 2 digits headroom) against
# an actual rendered width of 260px, an excess of 90-190px that visibly
# crowded these two dense per-channel blocks specifically (not flagged
# elsewhere, e.g. the MSO tab's spinboxes, whose content need is much
# closer to their actual width). Narrowed to a single shared width across
# all five fields per the LabVIEW Style Guide "consistent size for
# same-type controls" principle (already applied to the toolbar buttons).
_DENSE_NUMERIC_FIELD_WIDTH = 150
_DENSE_NUMERIC_FIELD_KEYS = frozenset({"frequency", "amplitude", "offset", "symmetry", "phase"})


class WheelSafeSpinBox(QSpinBox):
    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt API name
        event.ignore()


class WheelSafeDoubleSpinBox(QDoubleSpinBox):
    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt API name
        event.ignore()


class WheelSafeComboBox(QComboBox):
    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt API name
        event.ignore()


def _spin(value: float = 0.0, *, decimals: int = 3, minimum: float = -1e12, maximum: float = 1e12) -> QDoubleSpinBox:
    widget = WheelSafeDoubleSpinBox()
    widget.setDecimals(decimals)
    widget.setRange(minimum, maximum)
    widget.setValue(value)
    widget.setKeyboardTracking(False)
    widget.setMaximumWidth(_SPIN_MAX_WIDTH)
    return widget


def _int_spin(value: int = 0, *, minimum: int = -1_000_000, maximum: int = 1_000_000) -> QSpinBox:
    widget = WheelSafeSpinBox()
    widget.setRange(minimum, maximum)
    widget.setValue(value)
    widget.setKeyboardTracking(False)
    widget.setMaximumWidth(_SPIN_MAX_WIDTH)
    return widget


def _combo(values: list[str], value: str) -> QComboBox:
    widget = WheelSafeComboBox()
    widget.addItems(values)
    index = widget.findText(value)
    if index >= 0:
        widget.setCurrentIndex(index)
    return widget


def _widen_for_content(widget: QLineEdit, padding: int = 40) -> QLineEdit:
    """Size a QLineEdit to fit its current text instead of Qt's small
    default sizeHint -- path values (Qmix SDK / QMIXSDK / Cetoni config)
    can be long Windows paths that would otherwise be visually cramped.
    Shared by qt_ui.py's own Initialization tab and qt_ui_v2.py's
    InitializationDialog, which re-parent these same widget instances."""
    required_width = widget.fontMetrics().horizontalAdvance(widget.text()) + padding
    widget.setMinimumWidth(max(widget.minimumWidth(), required_width))
    return widget


def _hardware_reference_tabs(window: QWidget, mark_unwired_stub) -> QTabWidget:
    """Task-grouped presentation of the Initialization surface's resource/
    path fields, separating what hardware_factory.build_hardware_bundle()
    actually reads (Connections) from informational-only reference paths
    and fields retained for migration reference that it never reads (v3
    design-idea adoption, Proposal 5, 2026-08-06). Shared by qt_ui.py's own
    Initialization tab and qt_ui_v2.py's InitializationDialog, which
    re-parent these same widget instances -- same convention as
    _widen_for_content() above. `mark_unwired_stub` is each caller's own
    static helper (their tooltip wording differs slightly), not duplicated
    here."""
    tabs = QTabWidget()

    connections = QWidget()
    connections_form = QFormLayout(connections)
    connections_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    connections_form.addRow("Thorlabs/APT serial", window.thorlabs_apt_serial)
    connections_form.addRow("Valve VISA resource name", window.valve_resource)
    connections_form.addRow("Cetoni Device Configuration Path", _widen_for_content(window.cetoni_config_path))
    connections_form.addRow("TEC resource", window.tec_port)
    window._add_tooltip_icons(connections_form)

    reference_paths = QWidget()
    reference_form = QFormLayout(reference_paths)
    reference_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    reference_form.addRow("Qmix SDK Python Path", mark_unwired_stub(_widen_for_content(window.qmix_sdk_python_path)))
    reference_form.addRow("Qmix QMIXSDK Path", mark_unwired_stub(_widen_for_content(window.qmix_qmixsdk_path)))
    reference_note = QLabel("Reference paths only; the runtime does not read these fields.")
    reference_note.setWordWrap(True)
    reference_form.addRow(reference_note)
    window._add_tooltip_icons(reference_form)

    retained = QWidget()
    retained_form = QFormLayout(retained)
    retained_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    retained_form.addRow("Z stage backend", mark_unwired_stub(window.z_backend))
    retained_form.addRow("Prior VISA resource name (legacy, unwired)", mark_unwired_stub(window.prior_resource))
    retained_form.addRow("Thorlabs/APT backend", mark_unwired_stub(window.thorlabs_apt_backend))
    retained_form.addRow("Thorlabs/APT discovery only", mark_unwired_stub(window.thorlabs_apt_discovery_only))
    retained_note = QLabel("Retained for migration reference; the runtime does not use these fields.")
    retained_note.setWordWrap(True)
    retained_form.addRow(retained_note)
    window._add_tooltip_icons(retained_form)

    tabs.addTab(connections, "Connections")
    tabs.addTab(reference_paths, "Reference paths")
    tabs.addTab(retained, "Retained fields")
    return tabs


def _set_combo_text(widget: QComboBox, value: str) -> None:
    index = widget.findText(value)
    if index >= 0:
        widget.setCurrentIndex(index)


def bind_waveform_parameter_policy(function_widget: QComboBox, form: QFormLayout, fields: dict[str, object], *, prefix: str = "", suffix: str = "") -> None:
    """Apply the shared static waveform policy to one carrier form."""
    keys = tuple(fields)
    base_tooltips = {key: fields[key].toolTip() for key in keys}

    def label_for_field(field: object):
        label = form.labelForField(field)
        if label is not None:
            return label
        for row in range(form.rowCount()):
            item = form.itemAt(row, QFormLayout.ItemRole.FieldRole)
            wrapper = item.widget() if item is not None else None
            if wrapper is not None and (wrapper is field or field in wrapper.findChildren(QWidget)):
                label_item = form.itemAt(row, QFormLayout.ItemRole.LabelRole)
                return label_item.widget() if label_item is not None else None
        return None

    def refresh(function_text: str) -> None:
        policy = waveform_parameter_policy(function_text)
        applicable = {
            "frequency": policy.frequency_applicable,
            "amplitude": policy.amplitude_applicable,
            "offset": policy.offset_applicable,
            "symmetry": policy.symmetry_applicable,
            "phase": policy.phase_applicable,
        }
        labels = {
            "frequency": f"{policy.frequency_label} (kHz)",
            "amplitude": policy.amplitude_label,
            "offset": policy.offset_label,
            "symmetry": policy.symmetry_label,
            "phase": policy.phase_label,
        }
        help_text = dict(policy.help_text)
        if policy.function == WaveformFunction.DC:
            labels["frequency"] = "Frequency (not applicable)"
            labels["amplitude"] = "Amplitude (not applicable)"
            labels["symmetry"] = "Symmetry (not applicable)"
            labels["phase"] = "Phase (not applicable)"
        for key in keys:
            fields[key].setEnabled(policy.visible and policy.is_editable(key) and applicable[key])
            base_tooltip = base_tooltips[key]
            fields[key].setToolTip(
                f"{base_tooltip}\n{help_text[key]}" if base_tooltip else help_text[key]
            )
            label = label_for_field(fields[key])
            if label is not None:
                label.setText(f"{prefix}{labels[key]}{suffix}")

    function_widget.currentTextChanged.connect(refresh)
    refresh(function_widget.currentText())


class FocusWheelGuard(QObject):
    """Compatibility guard for legacy controls; shared factories are wheel-safe."""

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


class TooltipDeclutterGuard(QObject):
    """Prevents two native tooltips from visually overlapping (v2 audit,
    2026-08-02 finding 1a: a real user screenshot showed the Z-Scan
    tab's stacked "Z Start"/"Z End" tooltips both visible at once).
    Root cause, confirmed empirically: round 2 left widget.toolTip() set
    on every field (not just the click-triggered _TooltipIconButton), so
    hovering the field itself also native-hover-triggers a tooltip; on
    the real platform this delegates to the native OS tooltip control
    (see _wrap_with_tooltip_icon()'s own note on this), whose fade-out
    animation is not instant. A fast hover from one dense-form row to an
    adjacent one -- exactly the Z Start/Z End layout -- can trigger the
    second tooltip before the first has visually finished closing.
    QEvent.ToolTip is delivered (via this app-wide filter, which runs
    before the target widget's own event() handling) immediately before
    Qt's default handling would call QToolTip.showText() for the new
    tooltip; forcing an explicit QToolTip.hideText() here first turns
    that into a clean hide-then-show instead of a same-widget
    replace-in-place, closing the fade-overlap window. Click-triggered
    icon tooltips don't raise QEvent.ToolTip (they call
    QToolTip.showText() directly in Python), so they're unaffected by
    this filter -- confirmed separately (rapid clicks across two
    different icons never produced two visible bubbles, since
    QToolTip.showText() already replaces its own single shared
    instance); _TooltipIconButton._show_explanation() also calls
    hideText() first now, for the same reasoning, applied uniformly."""

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt API name
        if event.type() == QEvent.Type.ToolTip:
            QToolTip.hideText()
        return super().eventFilter(obj, event)


def install_tooltip_declutter_guard(app: QApplication | None) -> None:
    if app is None or getattr(app, "_thermo_acoustic_tooltip_declutter_guard", None) is not None:
        return
    guard = TooltipDeclutterGuard(app)
    app.installEventFilter(guard)
    app._thermo_acoustic_tooltip_declutter_guard = guard


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
        # Explicit hide-then-show, matching TooltipDeclutterGuard's fix for
        # the native-hover path (2026-08-02, v2 audit finding 1a) -- applied
        # here too for consistency, even though this click-triggered path
        # was confirmed not to race on its own (QToolTip.showText() already
        # replaces its own single shared instance).
        QToolTip.hideText()
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

    def show_frame(
        self,
        frame: np.ndarray,
        *,
        method: str = "Full Dynamic",
        shifts: int = 0,
        minimum: float | None = None,
        maximum: float | None = None,
    ) -> tuple[float, float] | None:
        self._last_qimage = self._convert_to_display_image(
            frame, method=method, shifts=shifts, minimum=minimum, maximum=maximum
        )
        self._update_pixmap()
        return self._last_display_range

    def show_message(self, message: str) -> None:
        self._last_qimage = None
        self._last_display_range = None
        self.image_label.setPixmap(QPixmap())
        self.image_label.setText(message)

    def _convert_to_display_image(
        self,
        frame: np.ndarray,
        *,
        method: str = "Full Dynamic",
        shifts: int = 0,
        minimum: float | None = None,
        maximum: float | None = None,
    ) -> QImage:
        array = np.asarray(frame)
        if array.size == 0:
            raise ValueError("empty camera frame")
        if array.ndim > 2:
            array = array[..., 0]
        if method == "Native (No Auto Scaling)":
            display_range = self._native_display_range(array)
            display = self._linear_stretch(array, *display_range)
        elif method == "Full Dynamic":
            display, display_range = self._display_full_dynamic(array)
        elif method == "90% Dynamic":
            display, display_range = self._display_90_percent_dynamic(array)
        elif method == "Downshift":
            display, display_range = self._display_downshift(array, shifts)
        elif method == "Fixed Range":
            if minimum is None or maximum is None or not np.isfinite(minimum) or not np.isfinite(maximum) or minimum >= maximum:
                raise ValueError("fixed display range requires finite minimum < maximum")
            display_range = (float(minimum), float(maximum))
            display = self._linear_stretch(array, *display_range)
        else:
            raise ValueError(f"unknown conversion method: {method}")
        self._last_display_range = display_range
        display = np.ascontiguousarray(display)
        height, width = display.shape
        image = QImage(display.data, width, height, display.strides[0], QImage.Format.Format_Grayscale8)
        return image.copy()

    def _native_display_range(self, array: np.ndarray) -> tuple[float, float]:
        """Return the deterministic range implied by the frame pixel dtype."""
        if not np.issubdtype(array.dtype, np.integer):
            raise ValueError("Native display requires an integer camera pixel dtype")
        limits = np.iinfo(array.dtype)
        return float(limits.min), float(limits.max)

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
        # Pending feedback item 3: a long entry (e.g. a real exception
        # message) had no way to be read in full inside this widget's fixed
        # width other than horizontal-scrolling one row at a time -- QListWidget
        # items don't wrap by default. Wrapping instead keeps every entry
        # fully visible without horizontal scrolling.
        self.setWordWrap(True)

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
        install_tooltip_declutter_guard(QApplication.instance())
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
        # clicked (its own "Stopping after {unit}..." status overwrites
        # app.status while the series' current repeat may still genuinely
        # be in flight).
        self._experiment_series_active = False
        # Distinct from _experiment_series_active above (set True whenever
        # EITHER kind of series runs): tracks specifically whether the
        # currently-running series is a TEC temperature scan
        # (_run_temperature_experiment_series()), set/cleared via the
        # "temperature_scan_active" progress kind. Needed because the
        # graceful-stop message differs by unit-of-completion: a plain
        # experiment series finishes "this repeat"; a TEC scan finishes
        # "this temperature point" (target + wait + hold + ALL of that
        # point's own repeats -- see Application.run_temperature_series()'s
        # 2026-08-04 abort fix).
        self._temperature_scan_active = False
        # Display-only series timing state. The start/estimate anchors are
        # created in the worker from the same monotonic clock used by the
        # experiment loops, then marshalled to the UI thread via progress.
        # A UI timer keeps the readout live even while a hardware call emits
        # no progress events for several seconds.
        self._series_started_at_monotonic: float | None = None
        self._series_estimate_anchor_at_monotonic: float | None = None
        self._series_estimated_remaining_at_anchor_s = 0.0
        self._series_timing_timer = QTimer(self)
        self._series_timing_timer.setInterval(250)
        self._series_timing_timer.timeout.connect(self._refresh_series_timing)
        # Graceful-stop indicator (2026-08-04, Part C follow-up): set True
        # by _abort() while a series is actively running, cleared the
        # instant that series' "experiment_series_active" progress goes
        # False (its try/finally fires on every exit path -- normal
        # completion, ExperimentSeriesAborted, or a raised error) --
        # deliberately reset at series-end, not left to a fresh series'
        # own first repeat to clear, so a later run never starts already
        # showing a stale "Stopping..." from a previous Abort (the
        # specific TestStand stale-highlight mistake this was designed to
        # avoid).
        self._stopping_after_current_repeat = False
        # Phase 3 step-progress breadcrumb (2026-08-04): tracked here in the
        # base class, not just qt_ui_v2.py, so the underlying state exists
        # regardless of whether a widget is listening to it -- matches
        # _experiment_series_active's own base-class-tracks-state,
        # subclass-renders-it split. "pending" for every step until its own
        # step_started/step_completed/step_failed event arrives, or until an
        # explicit "step_reset" (fired once per repeat and once per TEC
        # temperature point -- see application.py) puts every step back to
        # "pending" ahead of the next unit's first step_started.
        self._step_states: dict[str, str] = dict.fromkeys(STEP_ORDER, "pending")
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
        self._zscan_active = False
        self._manual_z_operation_active = False
        self._fixed_display_range = (0.0, 65535.0)

        self._build_state()
        self._build_layout()
        self._load_settings()
        self._refresh_status()

    def _build_state(self) -> None:
        """Build shared widget state inherited unchanged by the v2 and v3 surfaces."""
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
            "hardware_factory.build_hardware_bundle() connects to the real Thorlabs piezo "
            "(thorlabs_apt_serial, below) via the same thorlabs_piezo.PiezoStage connection the "
            "Z-Scan tab uses -- not the legacy Prior-serial/COM7 path this used to build (that path "
            "pointed at a port that never existed on this lab's hardware; see "
            "docs/pending_feedback.md item 4). Initialize only connects and reads device state; it does "
            "not authorize or perform piezo motion. Motion remains limited to the separately confirmed "
            "Z-Scan workflow. Z stage backend selection still has no real effect (there is only one real "
            "backend now)."
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
        self.tec_enabled = QCheckBox("Off/On")
        self.tec_enabled.setChecked(False)
        self.tec_enabled.setToolTip(
            "Includes the Meerstetter TEC when Initialize is clicked. With Simulate checked it uses "
            "the safe in-memory backend. With Simulate unchecked, the integrated real MeCom adapter "
            "may attempt real I/O. Its named parameter mapping is source-checked, but the historical "
            "bench evidence is not independently verified. Leave TEC simulated unless a human review "
            "explicitly authorizes real operation."
        )
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
        self.sim_tec = QCheckBox("Off/On")
        self.sim_tec.setChecked(True)
        self.sim_tec.setToolTip(
            "Only matters when Meerstetter TEC above is On. Checked = safe in-memory fake backend, "
            "no real hardware touched. Unchecked selects the integrated real MeCom adapter, which "
            "may attempt real I/O; leave this checked unless its code and retained bench record have been "
            "independently reviewed and approved."
        )

        self.z_backend = _combo([item.value for item in ZStageBackend], hardware_defaults.z_stage.backend.value)
        self.prior_resource = QLineEdit(hardware_defaults.z_stage.prior_resource)
        self.prior_resource.setToolTip(
            "Not wired to a real backend: the legacy Prior Z-motor/COM7 connection path this used "
            "to feed was retired (it pointed at a port that never existed on this lab's hardware "
            "and was never actually the real piezo -- confirmed via real-hardware investigation, "
            "docs/pending_feedback.md item 4). 'Z stage' now always connects to the real Thorlabs "
            "piezo via thorlabs_apt_serial below, not this field."
        )
        self.thorlabs_apt_serial = QLineEdit(hardware_defaults.z_stage.thorlabs_apt_serial)
        self.thorlabs_apt_serial.setToolTip(
            "The real Thorlabs piezo's own device serial number (thorlabs_piezo.PiezoStage "
            "connects by serial number via Kinesis, not a COM port) -- passed to "
            "HardwareRuntimeConfig and genuinely used when 'Z stage' is enabled at Initialize; "
            "Manual Focus and Z-Scan reuse that initialized Application-owned stage."
        )
        self.thorlabs_apt_backend = QLineEdit(hardware_defaults.z_stage.thorlabs_apt_backend)
        self.thorlabs_apt_discovery_only = QCheckBox("Discovery only")
        self.thorlabs_apt_discovery_only.setChecked(hardware_defaults.z_stage.thorlabs_apt_discovery_only)
        self.valve_resource = QLineEdit("COM5")  # Current application default; confirm physical wiring at the bench.
        # Relocated here from _instrument_group() (Session 40): that method
        # is v1-tab-only -- qt_ui_v2.py's InitializationDialog builds its own
        # separate form around this same widget without ever calling
        # _instrument_group(), so a tooltip set there never reached v2 users
        # at all. Every other tooltip in this codebase lives in _build_state()
        # for exactly this reason (guaranteed to apply regardless of which
        # UI's layout method runs).
        self.valve_resource.setToolTip(
            "Valve COM port setting. It is passed to HardwareRuntimeConfig and used by the "
            "serial backend; confirm physical wiring and valve routing at the bench."
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
        self.tec_port = QLineEdit("")
        self.tec_port.setToolTip(
            "USB/serial resource passed to the non-simulated TEC adapter. That adapter is currently "
            "uncommitted and not independently approved for operation, so this field must not be used "
            "to authorize real TEC control; leave TEC simulated."
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
        # Pending feedback item 3: _set_mso_stats() concatenates a
        # per-channel summary with " | ".join() -- unbounded length (grows
        # with capture channel count), same unwrapped-QLabel-in-a-form class
        # already fixed elsewhere in this tab (sweep_header/hint), just
        # missed here.
        self.mso_stats.setWordWrap(True)
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
        # Session (2026-08-03): Refill/Empty previously had no user-facing
        # flow rate at all -- QmixPumpBackend._fill_flow_rate() picked
        # 100% of the syringe's live max_flow_rate_ul_min unconditionally,
        # then (briefly) a fixed 12000 uL/min (200 uL/s) constant, verified
        # on real hardware but with a DIFFERENT syringe actually configured
        # than the one active by default -- caused real
        # "Value range of parameter exceeded" SDK rejections on Refill/
        # Empty (logs/hardware_transactions.log, 2026-08-03). This field
        # lets the operator set the target directly instead of a buried
        # constant; QmixPumpBackend still clamps the actual SDK request to
        # whichever syringe's real live max is smaller, so entering a value
        # above what the currently-configured syringe can do is safe (gets
        # capped, not rejected) rather than silently exceeding the ceiling.
        self.fill_flow_rate = _spin(12000.0, decimals=1, minimum=0.0)
        self.fill_flow_rate.setToolTip(
            "Refill/Empty flow rate in uL/min (default 12000 = 200 uL/s). The actual SDK request "
            "is clamped to the currently-configured syringe's "
            "own live-reported max flow rate -- entering a value this syringe can't reach is "
            "capped automatically, not rejected as an error."
        )
        self.level_ml = _spin(0.0, decimals=3, minimum=0.0)
        self.level_ml.setToolTip(
            "Absolute mL target for 'Go to Level' (not a fraction of syringe capacity -- Session "
            "13 removed an earlier 0.0-1.0 fraction-vs-absolute-mL ambiguity)."
        )
        self.flush_flowrate = _spin(0.0, decimals=3, minimum=0.0)
        self.flush_flowrate.setToolTip(
            "Positive dispense flow rate in uL/min. Zero means unset and is rejected if a flush "
            "is started. Together with Flush Volume, it determines the pump-move timeout."
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
            "Manual Pump&Valve-tab operations only: seconds to wait after the flush's second "
            "valve move (P02). This field does not override the separate automated Experiment "
            "request's WaitAfterFlush value."
        )
        self.flush_count = _int_spin(1, minimum=1)

        self.roi_h_offset = _int_spin(0, minimum=0)
        self.roi_v_offset = _int_spin(792, minimum=0)
        self.roi_v_offset.setToolTip(
            "Startup default follows the retained LabVIEW screenshot candidate "
            "(vertical_offset=792, vertical_size=740, exposure=40.0ms; see "
            "experiment_presets.py). Confirm it against the connected camera before real use. "
            "Combines with Vertical "
            "Size below (the two together set DCAM SUBARRAYVPOS/SUBARRAYVSIZE) and with Exposure "
            "Time to determine the real DCAM readout time _check_camera_timing_budget() checks "
            "against Camera FPS on the Experiment tab."
        )
        self.roi_h_size = _int_spin(2304, minimum=0)
        self.roi_v_size = _int_spin(740, minimum=0)
        self.roi_v_size.setToolTip(self.roi_v_offset.toolTip())
        self.exposure_ms = _spin(40.0, decimals=3, minimum=0.0)
        self.exposure_ms.setToolTip(
            "Applied to real DCAM hardware via Configure Camera (configure_exposure_time()). "
            "Automated Experiment runs use their own Exposure time (ms) field instead and enforce "
            "a timing budget: Application._check_camera_timing_budget() rejects a configured "
            "Camera FPS when the slower of current exposure and fresh DCAM readout time (itself "
            "set by the ROI size above) can't sustain it."
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
            "How a captured frame is converted to 8-bit for on-screen preview only -- "
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
        self.conversion_applied_range = QLabel("Applied: not available")
        self.conversion_applied_range.setWordWrap(True)
        self.conversion_min.valueChanged.connect(lambda _value: self._remember_fixed_display_range())
        self.conversion_max.valueChanged.connect(lambda _value: self._remember_fixed_display_range())
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
            "hardcode this to 'Internal', the selected steady/quasi-steady mode. The physically "
            "connected DIO0 camera trigger remains unprogrammed and currently unused. External "
            "triggering is deferred for a future transient/synchronized mode and would require "
            "explicit polarity plus physical timing verification. Polarity/Delay below are only "
            "physically meaningful when this manual control is 'External'."
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
            "Requested Internal-trigger camera frame rate. Must be > 0 and must be achievable "
            "given the slower limiting interval of applied exposure and fresh DCAM readout time; "
            "Application._check_camera_timing_budget() rejects an infeasible request before "
            "capture. Normal production does not program the connected DIO0 camera-trigger or "
            "DIO1 laser-trigger lines."
        )
        self.exp_camera_start = _spin(0.0, decimals=3, minimum=0.0)
        self.exp_camera_start.setToolTip(
            "Retained requested camera-start metadata for the current plan. Normal production does "
            "not convert this value into a camera delay or program DIO0/DIO1. Ignored whenever "
            "Dynamic Camera Start Time (below) is checked."
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
        self.exp_ch1_start.setToolTip(
            "Programmed as this AnalogOut channel's sec_wait value. Its physical reference depends on "
            "Trigger source; trigsrcNone timing versus the later shared PC trigger remains bench-unverified."
        )
        self.exp_ch1_run = _spin(0.0, decimals=3, minimum=0.0)
        self.exp_ch1_run.setToolTip(
            "Output duration in seconds. 0 = continuous/free-running (no defined stop time) -- "
            "Application._ad2_trigger_completion_seconds() raises before starting if this is 0, "
            "since flush/save can't safely proceed without a known completion time."
        )
        # New normal experiments default to one finite output run. Persisted
        # owner settings are still loaded unchanged; an older Repeat=0 value
        # therefore remains visible and is rejected by production preflight.
        self.exp_ch1_repeat = _int_spin(1, minimum=0)
        self.exp_ch1_trigger_source = _combo(WFG_TRIGGER_SOURCE_OPTIONS, "trigsrcNone")
        self.exp_ch1_trigger_source.setToolTip(
            "AD2 SDK trigger source enum. trigsrcNone (the steady/pre-actuated default) starts "
            "generation without waiting for a trigger when the WFG is configured/started, so "
            "output may already be active before camera acquisition. trigsrcPC arms the WFG to "
            "wait for Application.run_experiment2()'s later shared PC trigger and is the software "
            "shape for future onset capture. Call order is not physical timing verification; "
            "neither mode proves synchronization with camera exposure."
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
            "Start/Stop and Center/Total Span are both live inputs for the same underlying value -- "
            "editing either pair updates the other to match (center_hz=(start+stop)/2, "
            "total_span_hz=stop-start; half-deviation=total span/2). Unlike the manual WFG tab's own Sweep group, enabling this "
            "one DOES apply to real automated Experiment runs (Session 16)."
        )
        for widget in (self.exp_sweep_start_khz, self.exp_sweep_stop_khz, self.exp_sweep_center_khz, self.exp_sweep_width_khz):
            widget.setToolTip(exp_sweep_dual_mode_tip)
        self.exp_sweep_type.setToolTip(
            "Digilent FM-node mapping: Symmetric uses Triangle at 50% and sweeps bidirectionally "
            "between Start and Stop; RampUp uses RampUp at 100% for Start->Stop then reset; "
            "RampDown uses RampDown at 100% for Stop->Start then reset. Direction comes from "
            "the official WaveForms function enum; symmetry sets full-period directional ramps."
        )
        self.exp_ch2_freq = _spin(1.0, decimals=3, minimum=0.0)
        self.exp_ch2_freq.setToolTip(
            "Project Ch2 maps to WaveForms API channel index 1 / physical W2, which the owner "
            "identifies as connected to the laser Analog In. This value is retained for provenance "
            "but normal production rejects an enabled Ch2 until the laser input polarity, scaling, "
            "and enable semantics are confirmed. Frequency Scanning and FM Sweep remain acoustic "
            "Ch1/API-index-0/W1 only."
        )
        self.exp_ch2_amp = _spin(1.0, decimals=3)
        self.exp_ch2_offset = _spin(0.0, decimals=3)
        self.exp_ch2_function = _combo([item.value for item in WaveformFunction], WaveformFunction.SINE.value)
        self.exp_ch2_enable = QCheckBox("Enable")
        self.exp_ch2_enable.setToolTip(
            "Project Ch2 is physical W2 connected to the laser Analog In. Normal production fails "
            "closed if this is selected; do not enable it until exact current laser electrical "
            "semantics are confirmed. The separate DIO1 green lead is the laser digital-trigger "
            "connection and is also unprogrammed by normal production."
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
            "metadata slots, or planning rejects the request before a run starts."
        )
        self.exp_frames = _int_spin(1, minimum=0)
        self.exp_frames.setToolTip(
            "Frames captured per repeat. With Camera FPS this defines the requested acquisition "
            "duration for planning and metadata. Automated capture configures DCAM Internal trigger; "
            "normal production programs neither the DIO0 camera cable nor DIO1 laser cable."
        )
        self.exp_exposure_ms = _spin(0.0, decimals=3, minimum=0.0)
        self.exp_exposure_ms.setToolTip(
            "Applied to real DCAM hardware every run via configure_exposure_time() (Session 20 "
            "fix -- a prior bug called a Python-side bookkeeping setter instead, silently leaving "
            "the camera at whatever exposure a previous manual session had set). Combines with "
            "Camera FPS above: Application._check_camera_timing_budget() rejects the run before "
            "capture starts if the slower of this exposure and the fresh DCAM readout time (set "
            "by the ROI size, Camera tab) can't sustain the configured Camera FPS."
        )
        self.exp_flush_flowrate = _spin(0.0, decimals=3, minimum=0.0)
        self.exp_flush_flowrate.setToolTip(
            "Positive dispense flow rate in uL/min. Zero means unset and is rejected if the "
            "experiment attempts a flush. Together with Flush Volume, it determines the "
            "pump-move timeout."
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
            "Canonical operator-selected stabilization delay for this automated experiment "
            "request, applied once after P02 during repeat-to-repeat refresh. The separate manual "
            "Pump&Valve-tab value does not override it; no duration is scientifically universal."
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
        self.exp_tec_scan_enable = QCheckBox("Enable TEC temperature scan")
        self.exp_tec_scan_enable.setToolTip(
            "When checked, Start exp uses one temperature target per experiment group, applied to "
            "both TEC channels (locked) or independently per channel (unlocked, see the link toggle "
            "next to Temperature points). No in-group ramping or per-frame temperature changes occur."
        )
        self.exp_tec_points = QLineEdit("25.0")
        self.exp_tec_points.setToolTip(
            "Comma- or semicolon-separated TEC target temperatures in Celsius for channel 1 (both "
            "channels, while locked). One temperature point creates one experiment group; each group "
            "uses the existing repeat settings. Targets are rejected outside the local safety range "
            f"[{TEC_TARGET_MIN_C:.1f}, {TEC_TARGET_MAX_C:.1f}] C."
        )
        # Lock/link toggle -- the same well-established pattern as Photoshop's
        # aspect-ratio lock or a CSS box-model editor's margin/padding link
        # icon: locked (default) keeps both channels' scan series identical
        # (today's original, still-default behavior); unlocking allows
        # genuinely independent per-channel series. Historical project notes
        # report independent real control loops, but that evidence has not been
        # independently reconciled in the current audit. Plain checkable QPushButton with a
        # Unicode glyph, matching this app's existing convention of plain
        # text/tooltip widgets with no icon-asset pipeline (no QIcon/
        # QStyle.standardIcon usage anywhere else in this file).
        self.exp_tec_lock_channels = QPushButton()
        self.exp_tec_lock_channels.setCheckable(True)
        self.exp_tec_lock_channels.setChecked(True)
        self.exp_tec_lock_channels.setToolTip(
            "Locked: channel 2's temperature scan always mirrors channel 1's (today's original "
            "behavior). Unlocked: channel 2 gets its own independent temperature points, stepped "
            "together with channel 1 (both channels move to their own target at each step, the scan "
            "waits for both to stabilize before advancing)."
        )
        self.exp_tec_lock_channels.toggled.connect(self._on_tec_lock_toggled)
        self._update_tec_lock_button_text(locked=True)
        self.exp_tec_points_ch2 = QLineEdit("25.0")
        self.exp_tec_points_ch2.setEnabled(False)
        self.exp_tec_points_ch2.setToolTip(
            "Channel 2's own TEC target temperatures (only editable while unlocked). Must have the "
            "same number of points as channel 1's -- the scan is one sequence of steps, both channels "
            "move together at each step."
        )
        self.exp_tec_points.textChanged.connect(self._on_tec_points_ch1_changed)
        self.exp_tec_tolerance_c = _spin(0.1, decimals=3, minimum=0.0)
        self.exp_tec_tolerance_c.setToolTip("Allowed absolute error from target temperature before the TEC is considered stable.")
        self.exp_tec_min_settle_s = _spin(5.0, decimals=3, minimum=0.0)
        self.exp_tec_min_settle_s.setToolTip("Minimum time the TEC must remain inside tolerance before the experiment group starts.")
        self.exp_tec_max_wait_s = _spin(300.0, decimals=3, minimum=0.0)
        self.exp_tec_max_wait_s.setToolTip("Maximum time to wait for a TEC setpoint before failing clearly.")
        self.exp_tec_poll_interval_s = _spin(1.0, decimals=3, minimum=0.001)
        self.exp_tec_poll_interval_s.setToolTip("Seconds between TEC status polls while waiting for stability.")
        self.exp_tec_post_stable_hold_s = _spin(0.0, decimals=3, minimum=0.0)
        self.exp_tec_post_stable_hold_s.setToolTip(
            "Additional hold time in seconds AFTER the TEC is already confirmed stable (Min settle "
            "time above), before running that temperature point's experiment group -- for real "
            "sample thermal equilibration, which can lag behind the TEC's own sensor reading. "
            "Default 0.0 = no extra wait."
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
            "Inclusive: full Step Size intervals are captured and an exact final End position is appended "
            "when needed; no target is beyond Z End. The real per-frame position embedded in each filename is the "
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
            "whole number (Session 47); the saved filename reflects the controller closed-loop "
            "readback, not the nominal target or independently measured microscope displacement."
        )
        self.zscan_exposure_ms = _spin(40.0, decimals=3, minimum=0.001)
        self.zscan_exposure_ms.setToolTip(
            "Camera exposure time in milliseconds, applied once via configure_exposure_time() at the "
            "start of the scan (Session 47) -- independent of whatever the manual Camera tab's own "
            "ExposureTime(ms) is currently set to."
        )
        self.zscan_output_dir = QLineEdit(r"C:\test\zscan_calibration")
        self.zscan_output_dir.setToolTip(
            "Folder where each frame is saved as z_<controller_readback_um>um.tif (controller "
            "closed-loop coordinate, not the commanded target or physical microscope metrology). "
            "Created if it doesn't already exist."
        )

        self.manual_z_observed_um = QLabel("Unknown")
        self.manual_z_observed_um.setObjectName("manualZObserved")
        self.manual_z_target_um = _spin(0.0, decimals=2, minimum=0.0, maximum=0.0)
        self.manual_z_jog_step_um = _spin(1.0, decimals=2, minimum=0.01, maximum=1000.0)
        self.manual_z_refresh = QPushButton("Refresh")
        self.manual_z_move = QPushButton("Move")
        self.manual_z_minus = QPushButton("-Z")
        self.manual_z_plus = QPushButton("+Z")
        self.manual_z_range_status = QLabel("Initialize Z stage to read closed-loop capability")
        self.manual_z_range_status.setWordWrap(True)
        self.manual_z_refresh.clicked.connect(self._manual_z_refresh_position)
        self.manual_z_move.clicked.connect(self._manual_z_move_to_target)
        self.manual_z_minus.clicked.connect(lambda: self._manual_z_jog(-1.0))
        self.manual_z_plus.clicked.connect(lambda: self._manual_z_jog(1.0))

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
        state["sec_wait"].setToolTip(
            "Programmed as this AnalogOut channel's sec_wait value. Its physical reference depends on "
            "Trigger source; trigsrcNone timing versus a later PC trigger remains bench-unverified."
        )
        state["trigger_source"].setToolTip(
            "AD2 SDK trigger source enum controlling what starts this channel. trigsrcNone starts "
            "without waiting for a trigger; trigsrcPC waits for a later PC trigger. This manual "
            "control does not establish camera synchronization or physically verified onset timing."
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
            "Start/Stop and Center/Total Span are both live inputs for the same underlying value -- "
            "editing either pair updates the other to match (center_hz=(start+stop)/2, "
            "total_span_hz=stop-start; half-deviation=total span/2). Continuous ms-scale sweep within a single acoustic drive, "
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
            "Digilent FM-node mapping: Symmetric uses Triangle at 50% and sweeps bidirectionally "
            "between Start and Stop; RampUp uses RampUp at 100% for Start->Stop then reset; "
            "RampDown uses RampDown at 100% for Stop->Start then reset. Direction comes from "
            "the official WaveForms function enum; symmetry sets full-period directional ramps."
        )
        return state

    def _build_layout(self) -> None:
        """Build the v1-specific presentation; v2 and v3 replace this wholesale."""
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        top = QGridLayout()
        exit_button = QPushButton("Exit")
        exit_button.clicked.connect(self._exit_app)
        self.stop_series_button = QPushButton("Abort")
        self.stop_series_button.setToolTip(
            "Stops after the current repeat, or after the current temperature point during a TEC scan. "
            "It does not stop hardware in the middle of an operation."
        )
        self.stop_series_button.clicked.connect(self._abort)
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
        # UI layout audit (2026-08-02): these four are the same conceptual
        # group (global actions) and should read as a uniform row per the
        # LabVIEW Style Guide's "controls of the same type maintain
        # consistent size" principle -- previously `top.setColumnStretch(3, 1)`
        # gave all of this grid's extra width to column 3, which happens to
        # be Load Settings' own column (748px actual vs. its natural 170px
        # sizeHint, identical to Save Settings' own 170px). Matched to the
        # widest natural sizeHint among the four, same effect the Z-Scan
        # tab's Scan Control group already gets for free from a plain
        # QVBoxLayout equalizing its own three buttons.
        toolbar_button_width = max(
            b.sizeHint().width() for b in (exit_button, self.stop_series_button, save_settings, load_settings)
        )
        for b in (exit_button, self.stop_series_button, save_settings, load_settings):
            b.setFixedWidth(toolbar_button_width)
        # UI layout audit round 3 (2026-08-02): removed the redundant "Exit"/
        # "Abort" QLabel captions previously sitting in row 0 above these two
        # buttons -- not a menu bar, not connected to anything (verified: no
        # QMenuBar/QAction exists anywhere in this file), just static text
        # duplicating each button's own visible label, and applied
        # inconsistently in the first place (Save Settings/Load Settings,
        # cols 2-3, never got one). Leaving these two buttons in row 1 with
        # nothing above now matches Save Settings/Load Settings exactly.
        top.addWidget(exit_button, 1, 0)
        top.addWidget(self.stop_series_button, 1, 1)
        top.addWidget(save_settings, 1, 2)
        top.addWidget(load_settings, 1, 3)
        top.addWidget(QLabel("Status"), 0, 4)
        # Session (2026-08-03): was a bare top.addWidget(self.status, ...) --
        # unlike every other tooltip-bearing widget in this file, a widget
        # placed directly in a QGridLayout (not a QFormLayout row) never
        # passes through _add_tooltip_icons(), so this one's long tooltip
        # was left both un-HTML-wrapped (round 2's word-wrap fix never
        # applied to it) and without its own click-triggered "ⓘ" icon.
        # Wrapping it explicitly here matches how every other grid-placed
        # tooltip widget in this codebase already does it (e.g. the
        # Elapsed Time/Time Left labels in qt_ui_v2.py's equivalent group).
        top.addWidget(self._wrap_with_tooltip_icon(self.status), 1, 4)
        # Extra grid width now goes to Status (col 4, already has its own
        # setMinimumWidth(280) above and benefits from more room for a
        # scrollable history log) instead of a fixed-width button's column.
        top.setColumnStretch(4, 1)
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
        outer = QVBoxLayout(group)
        form = QFormLayout()
        form.addRow("Analog Discovery 3", self.ad2_enabled)
        form.addRow("Z stage", self.z_enabled)
        form.addRow("Hamamatsu", self.camera_enabled)
        form.addRow("Cetoni Pump", self.pump_enabled)
        form.addRow("MX Valve", self.valve_enabled)
        form.addRow("Meerstetter TEC", self.tec_enabled)
        outer.addLayout(form)
        # _add_tooltip_icons() must run after the layout is actually
        # installed on a parent widget (outer.addLayout() above), not
        # before -- confirmed by a real, reproducible test failure when
        # this was called on a still-unparented QFormLayout() first: every
        # other call site in this file uses the QFormLayout(group)
        # constructor form, which installs the layout immediately, so this
        # ordering requirement never surfaced there.
        self._add_tooltip_icons(form)
        # v3 design-idea adoption, Proposal 5 (2026-08-06): the resource/path
        # fields below used to sit interleaved with the enable checkboxes
        # above in one flat form, live-wired fields (Thorlabs/APT serial,
        # Valve VISA resource, Cetoni config path, TEC resource) mixed in
        # with informational-only reference paths (Qmix SDK/QMIXSDK paths)
        # and fields retained purely for migration reference (Z stage
        # backend, Prior VISA resource, Thorlabs/APT backend, Thorlabs/APT
        # discovery only) -- all disabled the same way regardless of which
        # of those two very different categories they were actually in.
        # Grouped into task-oriented tabs instead, same shared helper
        # qt_ui_v2.py's InitializationDialog now also uses.
        outer.addWidget(_hardware_reference_tabs(self, self._mark_unwired_stub))
        return group

    @staticmethod
    def _mark_unwired_stub(widget: QWidget) -> QWidget:
        widget.setEnabled(False)
        widget.setToolTip(
            "Not wired to a real backend: never read by hardware_factory.build_hardware_bundle() "
            "(Session 3)."
        )
        return widget

    def _elapsed_time_label(self) -> QLabel:
        self.elapsed_time_label = QLabel("00:00:00")
        self.elapsed_time_label.setToolTip(
            "Live wall-clock time since the current experiment series started."
        )
        return self.elapsed_time_label

    def _time_left_label(self) -> QLabel:
        self.time_left_label = QLabel("00:00:00")
        self.time_left_label.setToolTip(
            "Estimate only. Initially derived from programmed WFG/DIO and flush durations; "
            "after one repeat completes it uses the measured mean repeat duration. TEC "
            "stabilization and hardware/acquisition variability can change the actual time."
        )
        return self.time_left_label

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
        # Real-screenshot bug (2026-08-02): plain-text QToolTip does not
        # word-wrap on Windows' real native tooltip control -- confirmed via
        # a real user screenshot of the MSO tab's Range (V) field rendering
        # as one unwrapped line. The prior offscreen-only verification
        # missed this because the "offscreen" QPA platform has no native OS
        # tooltip to delegate to, so it always falls back to Qt's own
        # internal QLabel-based tooltip renderer, which DOES auto-wrap
        # regardless of platform -- structurally incapable of reproducing
        # this bug, not just an unlucky test case. Wrapping in a minimal
        # HTML tag is Qt's own documented way to force QToolTip word-wrap
        # on the real native control too. Escaped (not raw HTML) so a
        # literal &/</> in tooltip text (e.g. "Pump&Valve",
        # "z_<controller_readback_um>um.tif") renders as the real character instead of
        # being misinterpreted as markup or silently dropped.
        # Applied to the field widget's own tooltip too, not just the icon
        # button's: widget.toolTip() is still set here (never cleared), so
        # a plain hover over the field itself -- not just a click on the
        # icon -- also triggers Qt's native tooltip via this same string;
        # both paths need the same fix.
        wrapped_tip = f"<html>{html.escape(tip)}</html>"
        widget.setToolTip(wrapped_tip)
        container = _TooltipIconWrapper()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(widget)
        layout.addWidget(_TooltipIconButton(wrapped_tip))
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
        form.addRow("Simulate TEC", self.sim_tec)
        self._add_tooltip_icons(form)
        return group

    def _wfg_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        note = QLabel("Manual AD2 test tool -- independent from Experiment tab. Settings here do NOT affect experiment runs.")
        note.setWordWrap(True)
        # UI layout audit (2026-08-02): no explicit width cap previously --
        # wrap width was whatever the tab's own current width happened to
        # be, so this note only ever became a single very long unbroken
        # line rather than the clean 1-2 line wrap the Z-Scan tab's
        # description panel already demonstrates for the same wordWrap=True
        # pattern (same fix, sized for a banner-width note rather than that
        # panel's narrow side column).
        note.setMaximumWidth(700)
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
        apply.setToolTip(
            "Applies these settings immediately. If a real AD2 is initialized, this can start or change "
            "real analog output without an additional confirmation dialog."
        )
        apply.clicked.connect(self._start_apply_wfg)
        layout.addWidget(apply, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addStretch()
        return tab

    def _wfg_channel_group(self, title: str, state: dict[str, object]) -> QGroupBox:
        """Build the v1/v2 WFG group; v3 calls this base then adapts its result."""
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
            (f"AD2 source peak amplitude (V){overridden}", "amplitude"),
            (f"Offset(V){overridden}", "offset"),
            (f"Symmetry(%){overridden}", "symmetry"),
            (f"Phase(Deg){overridden}", "phase"),
            (f"Function{overridden}", "function"),
        ):
            if key in _DENSE_NUMERIC_FIELD_KEYS:
                state[key].setMaximumWidth(_DENSE_NUMERIC_FIELD_WIDTH)
            form.addRow(label, state[key])
            form.labelForField(state[key]).setObjectName(f"manualWfgCarrier_{key}Label")
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
        bind_waveform_parameter_policy(
            state["function"], form,
            {key: state[key] for key in ("frequency", "amplitude", "offset", "symmetry", "phase")},
            suffix=overridden,
        )

        self._add_tooltip_icons(form)
        trigger = QFormLayout()
        for label, key in (
            (f"Run duration (s)   [0 = continuous]{overridden}", "sec_run"),
            (f"secWait{overridden}", "sec_wait"),
            (f"Repeat count   [0 = infinite]{overridden}", "repeat"),
        ):
            trigger.addRow(label, state[key])
            trigger.labelForField(state[key]).setObjectName(f"manualWfgTrigger_{key}Label")
        state["repeat_trigger"].setText(f"Repeat Trigger{overridden}")
        trigger.addRow(state["repeat_trigger"])
        trigger.addRow(f"Trigger source{overridden}", state["trigger_source"])
        trigger.labelForField(state["trigger_source"]).setObjectName("manualWfgTrigger_sourceLabel")
        trigger_header = QLabel("Trigger")
        trigger_header.setObjectName("manualWfgTriggerSectionLabel")
        layout.addWidget(trigger_header)
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
            fm.labelForField(state[key]).setObjectName(f"manualWfgFm_{key}Label")
        fm.addRow(state["fm_enable"])
        fm_header = QLabel("FM Mod")
        fm_header.setObjectName("manualWfgFmSectionLabel")
        layout.addWidget(fm_header)
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
        sweep_header.setObjectName("manualWfgSweepSectionLabel")
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
        # Start/Stop and Center/Total Span are kept in sync (see
        # _connect_sweep_dual_mode_refresh()); reading Start/Stop here is
        # equivalent to reading Center/Total Span. Endpoints are authoritative
        # so the AD2 modulation index cannot silently reinterpret total span as
        # a one-sided deviation.
        start_hz = state["sweep_start_khz"].value() * 1000.0
        stop_hz = state["sweep_stop_khz"].value() * 1000.0
        return FmSweepSettings.from_endpoints(
            start_hz, stop_hz, state["sweep_time_ms"].value(), state["sweep_type"].currentText()
        )

    def _mso_tab(self) -> QWidget:
        """Build the v1/v2 MSO tab; v3 calls this base then repackages its groups."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        # v3 design-idea adoption, Proposal C (2026-08-05): one-line
        # orienting note, same wording pattern as the WFG tab's own note --
        # confirmed via grep that neither application.py nor workflows.py
        # ever reference "mso" in any form, so this is genuinely, not just
        # apparently, independent from automated runs.
        note = QLabel("Manual AD2 diagnostic tool -- independent from Experiment tab. Settings here do NOT affect experiment runs.")
        note.setWordWrap(True)
        note.setMaximumWidth(700)
        layout.addWidget(note)
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
        # Pending feedback item 3: _set_mso_stats() previews up to 6 samples
        # per channel per capture (2 channels = 12 lines) -- 90px only shows
        # ~4-5 without scrolling. Internally scrollable either way (no
        # content is ever inaccessible), but 140 shows close to a full
        # 2-channel preview at once, matching the height already established
        # for other small scrollable panels this session (Session 58's
        # HistoryLogWidget status/progress group).
        self.mso_text.setMaximumHeight(140)
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
        """Build the shared v1/v2 pump tab; v3 replaces it without calling this base."""
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
        # v3 design-idea adoption, Proposal C (2026-08-05): one-line
        # orienting note, same wording pattern as the WFG tab's own note.
        # This manual tab's own fields (flow_rate/level_ml/fill_flow_rate/
        # flush_flowrate etc.) are confirmed distinct Qt objects and
        # settings.json keys from the Experiment tab's own separate flush
        # fields (batch 1's own independence test) -- values entered here
        # do not feed automated runs, even though the pump/valve hardware
        # itself is the same shared self.app.pump/self.app.valve instances
        # an automated flush also uses.
        note = QLabel(
            "Manual pump/valve controls -- independent from the Experiment tab's own Flush "
            "settings. Values entered here do NOT feed automated experiment runs, even though "
            "the pump/valve hardware itself is shared."
        )
        note.setWordWrap(True)
        note.setMaximumWidth(700)
        outer.addWidget(note)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)

        # P01/P02 are protocol-confirmed position tokens. Their physical
        # fluidic routing remains a bench-confirmation item, so the controls
        # deliberately avoid unsupported Open/Closed labels.
        pos1 = QPushButton("Pos1 (P01)")
        pos1.setToolTip("Sends the protocol-confirmed valve position command P01. Physical fluidic routing remains unverified.")
        pos1.clicked.connect(lambda: self._run_action(lambda progress: self.app.valve.set_position(1), "Valve Pos1 (P01)"))
        pos2 = QPushButton("Pos2 (P02)")
        pos2.setToolTip("Sends the protocol-confirmed valve position command P02. Physical fluidic routing remains unverified.")
        pos2.clicked.connect(lambda: self._run_action(lambda progress: self.app.valve.set_position(2), "Valve Pos2 (P02)"))
        # v3 design-idea adoption, Proposal 7 (2026-08-06): selectively
        # clearer button text -- picked the four genuinely ambiguous ones
        # (bare "GO"/"STOP" and terse "Refill"/"Empty" with no adjacent
        # label spelling out the action), left Configure/Generate/Ref
        # Move/Flush alone (already reasonably self-explanatory or already
        # paired with a clarifying row label).
        refill = QPushButton("Refill syringe")
        refill.clicked.connect(lambda: self._run_action(lambda progress: self._refill(), "Refilling"))
        empty = QPushButton("Empty syringe")
        empty.clicked.connect(lambda: self._run_action(lambda progress: self._empty(), "Emptying"))
        configure = QPushButton("Configure")
        configure.clicked.connect(self._start_configure_syringe)
        generate = QPushButton("Generate")
        generate.clicked.connect(self._start_generate_flow)
        go = QPushButton("Move to target fill level")
        go.clicked.connect(self._start_go_level)
        ref = QPushButton("Ref Move")
        ref.clicked.connect(self._start_reference_move)
        flush = QPushButton("Flush")
        flush.clicked.connect(self._start_flush)
        stop = QPushButton("Stop pump")
        stop.setMinimumSize(200, 70)
        stop.clicked.connect(lambda: self._run_action(lambda progress: self.app.pump.stop(), "Pump stopped"))

        # WrapLongRows on every column's QFormLayout: an offscreen truncation
        # sweep (Session 38) found several row labels here clipped (e.g.
        # "Number of flushes" at 60px actual vs. 204px required) because each
        # column is narrower than a single-row form normally assumes. Wrapping
        # the label onto its own line above the field when needed avoids
        # clipping without widening the columns themselves.
        # v3 design-idea adoption, Proposal D (2026-08-05): split into
        # "Operational controls" (Valve/Pump refill-empty/Flow Control/
        # Flush/STOP -- genuinely touched every run) and "Static
        # configuration" (Setup/Syringe -- one-time-per-mount calibration
        # and geometry, not something an operator revisits mid-run).
        # Continues the same precedent Reference Move's own leading Setup
        # section already established (UI layout audit Part 3, 2026-08-03):
        # Reference move must happen BEFORE a syringe is loaded/refilled,
        # so it belongs with the other one-time setup, not mixed into
        # Flow Control's actual flow-rate controls. No widgets rebuilt --
        # this only changes which section each existing group is placed
        # under.
        setup_group = QGroupBox("Setup")
        setup_form = QFormLayout(setup_group)
        setup_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        setup_form.addRow("Reference move", ref)
        self._add_tooltip_icons(setup_form)

        # Keep this explicit action separate from normal Initialize: normal
        # Qmix initialization already clears the vendor fault latch, while
        # this action is for a fault observed later or an operator-requested
        # fresh reconnect. It remains gated behind a warning dialog.
        fault_group = QGroupBox("Pump Fault Recovery (advanced)")
        fault_form = QFormLayout(fault_group)
        fault_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        clear_fault = QPushButton("Clear Fault && Retry Connection")
        clear_fault.setStyleSheet("color: darkred; font-weight: bold;")
        clear_fault.setToolTip(
            "Use after a fault observed during a session, or to request a fresh operator-"
            "approved reconnect. Normal Initialize already clears the vendor fault latch."
        )
        clear_fault.clicked.connect(self._start_clear_pump_fault)
        fault_form.addRow("Manual fault clear", clear_fault)
        self._add_tooltip_icons(fault_form)

        valve_group = QGroupBox("Valve")
        valve_form = QFormLayout(valve_group)
        valve_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        valve_form.addRow("Valve Pos1 (P01)", pos1)
        valve_form.addRow("Valve Pos2 (P02)", pos2)
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
        pump_form.addRow("Refill/Empty Flow Rate (uL/min)", self.fill_flow_rate)
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
        column2.addStretch()

        flow_group = QGroupBox("Flow Control")
        flow_form = QFormLayout(flow_group)
        flow_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        flow_form.addRow("Flow Rate (-=aspirate, +=dispense)", self.flow_rate)
        flow_form.addRow("Generate Flow", generate)
        flow_form.addRow("Level(ml)", self.level_ml)
        flow_form.addRow("Go to Level", go)
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

        operational_columns = QHBoxLayout()
        operational_columns.setAlignment(Qt.AlignmentFlag.AlignTop)
        operational_columns.addLayout(column1)
        operational_columns.addLayout(column2)
        operational_columns.addLayout(column3)
        operational_columns.addLayout(column4)
        operational_columns.addStretch()

        setup_column = QVBoxLayout()
        setup_column.addWidget(setup_group)
        setup_column.addStretch()
        syringe_column = QVBoxLayout()
        syringe_column.addWidget(syringe_group)
        syringe_column.addStretch()
        # Session 104: its own column, not folded into setup_column above --
        # keeps this rare/advanced recovery action visually separate from
        # routine one-time setup, matching the task's requirement that it be
        # "visually/operationally distinct" from normal controls.
        fault_column = QVBoxLayout()
        fault_column.addWidget(fault_group)
        fault_column.addStretch()
        static_columns = QHBoxLayout()
        static_columns.setAlignment(Qt.AlignmentFlag.AlignTop)
        static_columns.addLayout(setup_column)
        static_columns.addLayout(syringe_column)
        static_columns.addLayout(fault_column)
        static_columns.addStretch()

        operational_label = QLabel("Operational controls")
        operational_label.setStyleSheet("font-weight: bold;")
        static_label = QLabel("Static configuration")
        static_label.setStyleSheet("font-weight: bold;")

        content_layout.addWidget(operational_label)
        content_layout.addLayout(operational_columns)
        content_layout.addWidget(static_label)
        content_layout.addLayout(static_columns)
        content_layout.addStretch()

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
        # UI layout audit (2026-08-02): this form was the one of six
        # sibling QFormLayouts in this tab missing the WrapLongRows policy
        # (see valve_form/pump_form/syringe_form/flow_form/flush_count_form
        # above -- all added by the same Session-38 fix this form's own
        # column-width constraint applies to identically, just missed here).
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.addRow("Flush Flow Rate (uL/min)", self.flush_flowrate)
        form.addRow("flush volume (ml)", self.flush_volume)
        form.addRow("WaitAfterFlush", self.wait_after_flush)
        self._add_tooltip_icons(form)
        return group

    def _camera_tab(self) -> QWidget:
        """Build the shared v1/v2 camera tab; v3 replaces it without calling this base."""
        tab = QWidget()
        grid = QGridLayout(tab)
        grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        # v3 design-idea adoption, Proposal C (2026-08-05): one-line
        # orienting note, same wording pattern as the WFG tab's own note --
        # but this tab is genuinely mixed (unlike WFG/MSO's clean "nothing
        # here affects automated runs"): Image/ROI/Conversion below are
        # independent (confirmed distinct from the Experiment tab's own
        # exposure_ms, batch 2's own independence test), while Sequence
        # Settings below already carries its own correct, more detailed
        # "DO affect experiment runs" note right where it's relevant --
        # not duplicated here, just pointed to.
        note = QLabel(
            "Manual camera controls -- Image/ROI/Conversion below are independent from the "
            "Experiment tab. Sequence Settings below is the one exception: those DO affect "
            "automated experiment runs (see that group's own note)."
        )
        note.setWordWrap(True)
        note.setMaximumWidth(700)
        grid.addWidget(note, 0, 0, 1, 3)
        grid.addWidget(self._image_group(), 1, 0, 1, 2)
        grid.addWidget(self._roi_group(), 2, 0, 1, 2)
        grid.addWidget(self._conversion_group(), 1, 2, 2, 1)
        grid.addWidget(self._sequence_group(), 3, 0, 1, 2)
        grid.addWidget(self._camera_retained_fields_group(), 3, 2)
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
        row.addWidget(QLabel("Image Continuous"))
        row.addWidget(image_continuous)
        # word-wrap: this HBoxLayout row has no wrap-long-rows equivalent
        # (that's a QFormLayout-only policy) -- an offscreen truncation
        # sweep (Session 38) found this label clipped at 324px actual vs.
        # 744px required. Give it a fixed width to wrap into instead of one
        # long unbroken line.
        # UI layout audit (2026-08-02): setMaximumWidth(260) alone wasn't
        # enough -- this row's earlier siblings (Image/Image Continuous/
        # checkbox) were squeezing the actual allocated width down to
        # ~120px, well short of that 260px ceiling (measured: the longest
        # word, "configure," is 108px wide at this label's font, leaving
        # only ~12px of margin at 120px -- enough to force the mid-word
        # break this label was originally fixed to avoid). setMinimumWidth
        # forces the row to actually give it the intended width instead of
        # treating 260 as an unreachable ceiling.
        hint_label = QLabel("If the button is grayed out, press the configure camera button")
        hint_label.setWordWrap(True)
        hint_label.setMinimumWidth(260)
        hint_label.setMaximumWidth(260)
        row.addWidget(hint_label)
        row.addStretch()
        return group

    def _live_image_continuous_checkbox(self) -> QCheckBox:
        try:
            self.image_continuous.isChecked()
        except (RuntimeError, SystemError):
            # v2 opens the validated v1 Camera tab as a late-created manual
            # dialog. Under offscreen Qt, the unparented checkbox created
            # during _build_state() can occasionally lose its C++ object
            # before that dialog is built; recreate only that dead widget.
            # Widened to also catch SystemError (2026-08-04, Save/Load
            # Settings gap-closure batch 2): bisected a real, deterministic
            # full-suite crash to this exact widget -- shiboken's offscreen
            # failure mode for an already-dead C++ object is not always a
            # catchable RuntimeError; conftest.py's own build_with_retry()
            # already treats SystemError as the expected exception class for
            # this general problem (dead/failed native Qt object access),
            # so this accessor now does the same for its own known-fragile
            # widget instead of assuming only RuntimeError can occur.
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
        freeze = QPushButton("Freeze Current Range")
        freeze.setToolTip("Use the last dynamic preview range as a fixed display range; this never captures or changes camera settings.")
        freeze.clicked.connect(self._freeze_current_display_range)
        self.conversion_method.currentTextChanged.connect(lambda _value: self._update_conversion_controls())
        layout.addLayout(form)
        self._add_tooltip_icons(form)
        layout.addWidget(QLabel("Adjust Intensity in image"))
        actions = QHBoxLayout()
        actions.addWidget(adjust)
        actions.addWidget(freeze)
        actions.addStretch()
        layout.addLayout(actions)
        layout.addWidget(self.conversion_applied_range)
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
        settings.addRow("Frames", self.sequence_frames)
        settings.addRow("Dcam Trigger Source", self.dcam_source)
        settings.addRow("Polarity", self.external_polarity)
        settings.addRow("Delay", self.external_delay)
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

    def _camera_retained_fields_group(self) -> QGroupBox:
        # v3 design-idea adoption, Proposal 6 (2026-08-06): capture_mode and
        # sequence_exposure_ms previously sat inline inside Sequence
        # Settings' own form, each individually suffixed "(unused)" --
        # correct, but visually indistinguishable at a glance from the
        # live, automated-run-affecting fields right above/below them in
        # that same group (which Sequence Settings' own note says DO
        # affect experiment runs). Isolated into their own group instead of
        # a full tab restructure, matching this fix's scope.
        group = QGroupBox("Retained (not used by runtime)")
        form = QFormLayout(group)
        form.addRow("Capture mode", self.capture_mode)
        form.addRow("ExposureTime(ms)", self.sequence_exposure_ms)
        note = QLabel("Retained for migration reference; the current runtime does not use these fields.")
        note.setWordWrap(True)
        form.addRow(note)
        self._add_tooltip_icons(form)
        return group

    # --- Z-scan calibration tab (Phase 4) ---

    def _zscan_tab(self) -> QWidget:
        """Build the shared v1/v2 Z-scan tab; v3 replaces it without calling this base."""
        tab = QWidget()
        grid = QGridLayout(tab)
        grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        # v3 design-idea adoption, Proposal C (2026-08-05): one-line
        # orienting note, same wording pattern as the WFG tab's own note.
        # This is a separate concern from the Scan Control group's own
        # existing hint below (which explains this tab's real dependency on
        # the Camera tab's Configure Camera step, not its relationship to
        # automated Experiment runs) -- Z-Scan calibration is a standalone
        # workflow never called from run_experiment2()/the automated path.
        note = QLabel("Manual Z-Scan calibration workflow -- independent from Experiment tab. Settings here do NOT affect experiment runs.")
        note.setWordWrap(True)
        note.setMaximumWidth(700)
        grid.addWidget(note, 0, 0, 1, 2)
        grid.addWidget(self._manual_focus_group(), 1, 0, 1, 2)
        grid.addWidget(self._zscan_parameters_group(), 2, 0)
        grid.addWidget(self._zscan_control_group(), 2, 1)
        grid.setColumnStretch(2, 1)
        return tab

    def _manual_focus_group(self) -> QGroupBox:
        group = QGroupBox("Manual Focus (Z Stage)")
        form = QFormLayout(group)
        form.addRow("Controller readback position (um)", self.manual_z_observed_um)
        form.addRow("Requested target (um)", self.manual_z_target_um)
        form.addRow("Jog step (um)", self.manual_z_jog_step_um)
        buttons = QHBoxLayout()
        buttons.addWidget(self.manual_z_refresh)
        buttons.addWidget(self.manual_z_move)
        buttons.addWidget(self.manual_z_minus)
        buttons.addWidget(self.manual_z_plus)
        form.addRow(buttons)
        form.addRow(self.manual_z_range_status)
        self._update_manual_focus_controls()
        return group

    def _manual_focus_stage(self):
        z_motor = getattr(self.app, "z_motor", None)
        stage = getattr(z_motor, "stage", None)
        if z_motor is None or not getattr(z_motor, "enabled", False) or stage is None:
            return None
        if not getattr(stage, "connected", False):
            return None
        # Kinesis reports the enum spelling ``CloseLoop``; the user-facing
        # terminology is Closed Loop. Accept the descriptive fake spelling in
        # offline tests without weakening the real-mode gate.
        if str(getattr(stage, "position_control_mode", "")) not in {"CloseLoop", "ClosedLoop"}:
            return None
        maximum = getattr(stage, "max_travel_um", None)
        if maximum is None or not math.isfinite(float(maximum)) or float(maximum) <= 0.0:
            return None
        return stage

    def _update_manual_focus_controls(self) -> None:
        if not hasattr(self, "manual_z_move"):
            return
        stage = self._manual_focus_stage()
        blocked = bool(
            self._busy_count
            or self._experiment_series_active
            or self._zscan_active
            or self._manual_z_operation_active
        )
        enabled = stage is not None and not blocked
        for widget in (self.manual_z_target_um, self.manual_z_jog_step_um, self.manual_z_refresh,
                       self.manual_z_move, self.manual_z_minus, self.manual_z_plus):
            widget.setEnabled(enabled)
        if stage is None:
            self.manual_z_range_status.setText("Manual focus unavailable: initialize a connected ClosedLoop PPC001/PFM450E stage.")
            self.manual_z_target_um.setRange(0.0, 0.0)
        else:
            maximum = float(getattr(stage, "max_travel_um", 0.0))
            self.manual_z_target_um.setRange(0.0, maximum)
            self.manual_z_range_status.setText(f"Valid range: 0.00 – {maximum:.2f} um; motion requires an explicit button.")
        if blocked:
            self.manual_z_range_status.setText("Manual focus unavailable while another operation owns the stage.")

    def _manual_z_refresh_position(self) -> None:
        stage = self._manual_focus_stage()
        if stage is None or self._busy_count or self._experiment_series_active or self._zscan_active:
            self._update_manual_focus_controls()
            return
        self._manual_z_operation_active = True
        try:
            position = float(stage.get_position())
            self.manual_z_observed_um.setText(f"{position:.3f}")
            self._set_status("Z position refreshed")
        except Exception as exc:
            self._set_status(f"Z refresh failed: {exc}")
        finally:
            self._manual_z_operation_active = False
            self._update_manual_focus_controls()

    def _manual_z_validate_target(self, target: float, stage) -> bool:
        maximum = float(getattr(stage, "max_travel_um", 0.0))
        if target < 0.0 or target > maximum:
            self._set_status(f"Z target rejected: {target:.3f} um is outside 0.000–{maximum:.3f} um")
            return False
        return True

    def _manual_z_move_to_target(self) -> None:
        stage = self._manual_focus_stage()
        if stage is None or self._busy_count or self._experiment_series_active or self._zscan_active:
            self._update_manual_focus_controls()
            return
        target = float(self.manual_z_target_um.value())
        if not self._manual_z_validate_target(target, stage):
            return
        self._manual_z_operation_active = True
        try:
            stage.set_position(target)
            readback = float(stage.get_position())
            self.manual_z_observed_um.setText(f"{readback:.3f}")
            self._set_status(f"Z moved; readback {readback:.3f} um")
        except Exception as exc:
            self._set_status(f"Z move failed: {exc}")
        finally:
            self._manual_z_operation_active = False
            self._update_manual_focus_controls()

    def _manual_z_jog(self, direction: float) -> None:
        stage = self._manual_focus_stage()
        if stage is None or self._busy_count or self._experiment_series_active or self._zscan_active:
            self._update_manual_focus_controls()
            return
        self._manual_z_operation_active = True
        try:
            current = float(stage.get_position())
            target = current + direction * float(self.manual_z_jog_step_um.value())
            if not self._manual_z_validate_target(target, stage):
                return
            stage.set_position(target)
            readback = float(stage.get_position())
            self.manual_z_observed_um.setText(f"{readback:.3f}")
            self._set_status(f"Z jog complete; readback {readback:.3f} um")
        except Exception as exc:
            self._set_status(f"Z jog failed: {exc}")
        finally:
            self._manual_z_operation_active = False
            self._update_manual_focus_controls()

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
            "Requires the Camera tab's own Configure Camera and Initialize hardware to have already "
            "been run this session. The scan reuses the Application-owned camera and configured Z-stage "
            "connections; it never opens a second default piezo. Query Piezo Range reads live MaxTravel "
            "from that initialized stage before you commit to a scan."
        )
        hint.setWordWrap(True)
        hint.setMaximumWidth(260)
        layout.addWidget(hint)
        layout.addStretch()
        return group

    def _configured_z_stage_for_zscan(self):
        """Return the initialized Application-owned stage, or fail closed."""
        z_motor = getattr(self.app, "z_motor", None)
        stage = getattr(z_motor, "stage", None)
        if z_motor is None or not getattr(z_motor, "enabled", False) or stage is None:
            self._set_status("Z-scan unavailable: configured Z stage is not initialized.")
            return None
        if not getattr(stage, "connected", False):
            self._set_status("Z-scan unavailable: configured Z stage is not connected.")
            return None
        maximum = getattr(stage, "max_travel_um", None)
        if maximum is None or not math.isfinite(float(maximum)) or float(maximum) <= 0.0:
            self._set_status("Z-scan unavailable: configured Z stage MaxTravel is unknown or invalid.")
            return None
        return stage

    def _query_zscan_range(self) -> None:
        stage = self._configured_z_stage_for_zscan()
        if stage is None:
            return
        self._apply_zscan_range(float(stage.max_travel_um))
        self._set_status("Piezo range read from the initialized configured stage.")

    def _apply_zscan_range(self, max_travel_um: float | None) -> None:
        if max_travel_um is None:
            return
        self.zscan_z_start_um.setRange(0.0, max_travel_um)
        self.zscan_z_end_um.setRange(0.0, max_travel_um)
        self.zscan_z_start_um.setEnabled(True)
        self.zscan_z_end_um.setEnabled(True)
        self.zscan_range_status.setText(f"Valid range: 0.00 - {max_travel_um:.2f} um (live-read from device MaxTravel)")

    def _start_zscan(self) -> None:
        if self._busy_count or self._zscan_active or self._manual_z_operation_active:
            self._set_status("Busy")
            return
        from .thorlabs_piezo import PiezoStageError

        if getattr(self.app.camera, "handle", None) is None:
            self._set_status("Z-scan error: camera is not initialized -- run Configure Camera on the Camera tab first.")
            return

        piezo = self._configured_z_stage_for_zscan()
        if piezo is None:
            return

        output_dir = Path(self.zscan_output_dir.text())
        step_size_um = float(self.zscan_step_size_um.value())
        exposure_ms = float(self.zscan_exposure_ms.value())

        # Apply/refresh the already initialized stage's live MaxTravel-based
        # range before reading Z Start/End. This never opens a second device.
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
                self._set_status("Z-scan cancelled: ClosedLoop switch declined.")
                return
            try:
                piezo.switch_to_closed_loop()
            except PiezoStageError as exc:
                self.app.check_loop_error(str(exc))
                self._set_status(f"Z-scan error: ClosedLoop switch failed: {exc}")
                return

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
            self._set_status("Z-scan cancelled: PPC001 motion not authorized.")
            return

        self._zscan_abort_requested = False
        self._zscan_active = True
        self._update_manual_focus_controls()
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
            # Application owns this connection. Only Application.cleanup()
            # may disconnect it; a completed scan must leave the shared stage
            # available to Manual Focus and later workflows.
            self._zscan_active = False
        return f"Z-scan complete: {len(results)} frames written to {output_dir}"

    def _abort_zscan(self) -> None:
        self._zscan_abort_requested = True
        self._set_status("Z-scan abort requested")

    def _experiment_primary_run_control_group(self) -> QGroupBox:
        # v3 design-idea adoption, Proposal A (2026-08-05): "Start exp" was
        # previously just one of several equally-weighted rows/cards (v1's
        # flat Experiment-tab grid; v2's "Sequence Control" card, itself
        # buried as step-card 1 of 7 inside the scrolling configuration
        # column) -- easy to miss among the surrounding configuration
        # fields despite being the single most consequential control on
        # this tab. Elevated into its own dedicated, visually distinct
        # group, placed at the TOP of the configuration content (not
        # stacked above the v2 config/live-monitoring column split --
        # that would compete with the live-monitoring column's own
        # always-visible screen space, the exact mistake flagged when v3
        # was evaluated for design ideas). Reuses self.series_path/
        # self._browse_folder/self._start_experiment verbatim -- no new
        # state, same widgets/handlers the old locations used.
        group = QGroupBox("Run Experiment")
        grid = QGridLayout(group)
        start = QPushButton("Start exp")
        start.setMinimumHeight(44)
        start.setToolTip(
            "Starts the experiment with the currently initialized backends. Real hardware actions are not "
            "protected by the staged smoke scripts' command-line confirmations. Abort stops only after the "
            "current repeat or temperature point finishes."
        )
        start.clicked.connect(self._start_experiment)
        browse = QPushButton("...")
        browse.clicked.connect(lambda: self._browse_folder(self.series_path))
        note = QLabel("Uses the configured setup below and the currently initialized hardware.")
        note.setWordWrap(True)
        note.setMaximumWidth(520)
        grid.addWidget(start, 0, 0, 2, 1)
        grid.addWidget(QLabel("Series path"), 0, 1)
        grid.addWidget(self._wrap_with_tooltip_icon(self.series_path), 1, 1)
        grid.addWidget(browse, 1, 2)
        grid.addWidget(note, 0, 3, 2, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        return group

    def _experiment_tab(self) -> QWidget:
        tab = QWidget()
        grid = QGridLayout(tab)
        grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        grid.addWidget(self._experiment_primary_run_control_group(), 0, 0, 1, 6)
        grid.addWidget(QLabel("Elapsed Time"), 1, 0)
        grid.addWidget(self._elapsed_time_label(), 2, 0)
        grid.addWidget(QLabel("Estimated time remaining"), 1, 1)
        grid.addWidget(self._time_left_label(), 2, 1)
        grid.addWidget(QLabel("# elements in queue"), 1, 2)
        self.queue_count = QLabel("0")
        grid.addWidget(self.queue_count, 2, 2)
        grid.addWidget(self._ad_settings_group(), 3, 0, 1, 2)
        grid.addWidget(self._experiment_settings_column(), 3, 2, 2, 1)
        grid.addWidget(self._camera_start_group(), 3, 4, 2, 1)
        grid.addWidget(QLabel("Average FPS"), 6, 5)
        grid.addWidget(self.average_fps, 7, 5)
        # Measured offscreen (Session 38): only a ~5px safety margin between
        # this label's required text width (168px) and its actual rendered
        # width (173px) at the app's own minimum window size (980x680) --
        # not conclusively clipped in this environment, but fragile enough to
        # explain a reported "first character cut off" screenshot at a
        # slightly narrower real window. setMinimumWidth gives real headroom.
        waveform_graph_label = QLabel("Waveform Graph")
        waveform_graph_label.setMinimumWidth(200)
        grid.addWidget(waveform_graph_label, 6, 0)
        self.waveform_graph = WaveformGraph()
        grid.addWidget(self.waveform_graph, 7, 0, 1, 5)
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
        # UI layout audit (2026-08-02): same fix as the WFG tab's parallel
        # intro note -- no explicit width cap previously meant this could
        # render as one long unbroken line (or worse, get clipped) rather
        # than wrapping cleanly regardless of window size.
        note.setMaximumWidth(700)
        layout.addWidget(note)

        top = QFormLayout()
        top.addRow("Camera FPS (Internal trigger)", self.exp_camera_fps)
        top.addRow("Camera Start request (s; metadata only)", self.exp_camera_start)
        layout.addLayout(top)
        self._add_tooltip_icons(top)

        self._add_experiment_channel_sections(layout, "CH0")
        self._add_experiment_channel_sections(layout, "CH1")

        scroll = QScrollArea()
        # UI layout audit round 3 (2026-08-02): was setWidgetResizable(True),
        # which actively shrinks the scroll area's content to match its
        # viewport -- silently overriding every child widget's own preferred/
        # max width, including the intro note's setMaximumWidth(700) above
        # and every per-channel field's own natural size, regardless of the
        # group's own comment describing the intended (False) behavior
        # ("lets it lay out at its real size internally and scroll, instead
        # of being compressed"). _wfg_channel_group()'s scroll area -- the
        # direct sibling this method's own comment says it mirrors -- already
        # uses False correctly; this was the one place that diverged.
        # Horizontal policy also changed from AlwaysOff to AsNeeded to match:
        # with setWidgetResizable(False), content lays out at its natural
        # (possibly wider-than-viewport) size -- AlwaysOff would have
        # silently clipped anything that didn't fit with no way to reach it,
        # trading "squeezed but visible" for "natural-width but invisible."
        scroll.setWidgetResizable(False)
        scroll.setMaximumHeight(360)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
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
        for field in (freq, amp, offset, symmetry, phase):
            field.setMaximumWidth(_DENSE_NUMERIC_FIELD_WIDTH)
        carrier = QFormLayout()
        carrier.addRow(f"{channel_label} Enable{overrides}", enable)
        carrier.addRow(f"{channel_label} Function{overrides}", function)
        carrier.addRow(f"{channel_label} Frequency (kHz){overrides}", freq)
        carrier.addRow(f"{channel_label} AD2 source peak amplitude (V){overrides}", amp)
        carrier.addRow(f"{channel_label} Offset (V){overrides}", offset)
        carrier.addRow(f"{channel_label} Symmetry (%){overrides}", symmetry)
        carrier.addRow(f"{channel_label} Phase (Deg){overrides}", phase)
        layout.addWidget(QLabel("Carrier"))
        layout.addLayout(carrier)
        bind_waveform_parameter_policy(
            function, carrier,
            {"frequency": freq, "amplitude": amp, "offset": offset, "symmetry": symmetry, "phase": phase},
            prefix=f"{channel_label} ", suffix=overrides,
        )
        self._add_tooltip_icons(carrier)
        if channel_label == "CH0":
            self._bind_dc_incompatible_experiment_features(function)

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
            sweep.addRow(f"{channel_label} Total Span, Start-to-Stop (kHz)", self.exp_sweep_width_khz)
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

    def _bind_dc_incompatible_experiment_features(self, function_widget: QComboBox) -> None:
        if getattr(self, "_dc_feature_policy_bound", False):
            return
        self._dc_feature_policy_bound = True
        controls = (
            self.exp_freq_scan_enable, self.exp_freq_scan_start_khz,
            self.exp_freq_scan_stop_khz, self.exp_freq_scan_count,
            self.exp_freq_scan_step_khz, self.exp_sweep_enable,
            self.exp_sweep_start_khz, self.exp_sweep_stop_khz,
            self.exp_sweep_center_khz, self.exp_sweep_width_khz,
            self.exp_sweep_time_ms, self.exp_sweep_type,
        )
        def refresh(function_text: str) -> None:
            policy = waveform_parameter_policy(function_text)
            enabled = policy.is_editable("frequency_scan") and policy.is_editable("fm")
            for control in controls:
                control.setEnabled(enabled)
        function_widget.currentTextChanged.connect(refresh)
        refresh(function_widget.currentText())

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
        layout.addWidget(self._experiment_temperature_group())
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
        form.addRow("Flush Flow Rate (uL/min)", self.exp_flush_flowrate)
        form.addRow("flush volume (ml)", self.exp_flush_volume)
        form.addRow("WaitAfterFlush", self.exp_wait_after_flush)
        self._add_tooltip_icons(form)
        return group

    def _experiment_temperature_group(self) -> QGroupBox:
        group = QGroupBox("TEC Temperature Scan")
        form = QFormLayout(group)
        form.addRow("Enable", self.exp_tec_scan_enable)
        form.addRow("Temperature points CH1 (C)", self.exp_tec_points)
        form.addRow("Channel lock", self.exp_tec_lock_channels)
        form.addRow("Temperature points CH2 (C)", self.exp_tec_points_ch2)
        form.addRow("Tolerance (C)", self.exp_tec_tolerance_c)
        form.addRow("Minimum settle time (s)", self.exp_tec_min_settle_s)
        form.addRow("Maximum wait time (s)", self.exp_tec_max_wait_s)
        form.addRow("Poll interval (s)", self.exp_tec_poll_interval_s)
        form.addRow("Post-stabilization hold (s)", self.exp_tec_post_stable_hold_s)
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
        # Current production retains these values as requested metadata only;
        # it does not program either connected digital line.
        group = QGroupBox("Camera Start Array(s) (per-repeat metadata)")
        outer = QVBoxLayout(group)
        content = QWidget()
        form = QFormLayout(content)
        # Moved here from an isolated spot elsewhere in the tab's grid --
        # Dynamic Camera Start Time controls whether this metadata array is
        # selected, so it belongs directly above the array it controls.
        form.addRow("Dynamic Camera Start Time (per-repeat metadata)", self.dynamic_camera_start)
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
        group = QGroupBox("Frequency Scanning (Dynamic Frequency, CH0 only)")
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
        form.addRow("Total Span, Start-to-Stop (kHz)", self.exp_sweep_width_khz)
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
        # v3 design-idea adoption, Proposal 2 (2026-08-06): "Error Out" was
        # literal LabVIEW-era jargon describing a display mode this widget
        # no longer has -- Session 58 already replaced the single-value
        # display with this scrollable HistoryLogWidget, but the caption
        # itself was never updated to match.
        group = QGroupBox("Status and error history")
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
        for index, (experiment_state, wfg_state) in enumerate(zip(self.exp_ad2_channels, self.wfg_channels)):
            experiment_state["frequency"].setValue(wfg_state["frequency"].value())
            experiment_state["amplitude"].setValue(wfg_state["amplitude"].value())
            experiment_state["offset"].setValue(wfg_state["offset"].value())
            _set_combo_text(experiment_state["function"], wfg_state["function"].currentText())
            experiment_state["enable"].setChecked(wfg_state["enable"].isChecked())
            experiment_state["sec_wait"].setValue(wfg_state["sec_wait"].value())
            experiment_state["sec_run"].setValue(wfg_state["sec_run"].value())
            # WaveForms manual state historically defaults Repeat to 0
            # (infinite). Do not let that legacy manual default overwrite the
            # fresh normal-experiment CH0 default of 1. Explicit persisted
            # experiment settings set _experiment_ad2_seeded during loading,
            # so an owner's existing Repeat=0 remains unchanged and is
            # rejected visibly by normal-run preflight.
            if index != 0 or wfg_state["repeat"].value() != 0:
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
        if index == 0 and carrier.function != WaveformFunction.DC and self.exp_sweep_enable.isChecked():
            sweep = self._experiment_fm_sweep_settings()
            carrier.frequency_hz = sweep.center_hz
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
        if index == 0 and carrier.function != WaveformFunction.DC and frequency_override_hz is not None:
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
        # Start/Stop and Center/Total Span are kept in sync by
        # _connect_sweep_dual_mode_refresh(); reading Start/Stop here is
        # equivalent to reading Center/Total Span. Endpoints remain
        # authoritative through planning and AD2 translation.
        start_hz = self.exp_sweep_start_khz.value() * 1000.0
        stop_hz = self.exp_sweep_stop_khz.value() * 1000.0
        return FmSweepSettings.from_endpoints(
            start_hz, stop_hz, self.exp_sweep_time_ms.value(), self.exp_sweep_type.currentText()
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
            thorlabs_apt_serial=self.thorlabs_apt_serial.text(),
            valve_resource=self.valve_resource.text(),
            cetoni_config_path=self.cetoni_config_path.text(),
            tec_enabled=self.tec_enabled.isChecked(),
            sim_tec=self.sim_tec.isChecked(),
            tec_port=self.tec_port.text(),
        )
        self._run_action(lambda progress: self._initialize_system(config, progress), "Initializing")

    def _initialize_system(self, config: HardwareRuntimeConfig, progress=None) -> str:
        if progress:
            progress("status", "Opening selected hardware")
        try:
            self.app.cleanup()
        except Exception as exc:
            self.app.check_loop_error(exc)
            raise RuntimeError(
                "Existing hardware cleanup failed; refusing to initialize a replacement hardware bundle."
            ) from exc
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
        self._run_action(lambda progress: self._go_to_level(level, flow_rate), "Setting pump level")

    # Finding 1 (qt_ui.py/qt_ui_v2.py targeted UI audit): this button used to
    # call self.app.pump.set_fill_level() directly, the same fire-and-forget
    # shape refill()/empty() were fixed for -- now routes through
    # Application.go_to_level() (same wait_for_pump()/resync pattern), same
    # bool-to-status-string conversion as _refill()/_empty() below.
    def _go_to_level(self, level: float, flow_rate: float) -> str:
        return "GoToLevelComplete" if self.app.go_to_level(level, flow_rate) else "GoToLevelTimedOut"

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

    def _start_clear_pump_fault(self) -> None:
        # This QMessageBox is the non-skippable warning for the remaining
        # manual-recovery scope: a fault observed after initialization or an
        # operator-requested fresh reconnect. Normal initialization now clears
        # the vendor fault latch before its final enable gate.
        answer = QMessageBox.question(
            self,
            "Confirm Pump Fault Clear",
            "Normal initialization clears the vendor fault latch. Use this separate "
            "manual recovery only for a fault observed later in the session, or when you "
            "want an explicit fresh reconnect. A fault that remains or relatches still "
            "blocks drive enable. This does NOT fix the underlying cause; see "
            "docs/hardware_repair_plan.md.\n\n"
            "This action is recorded in the status/error history below, and in data.tdms "
            "if an experiment run follows this session.\n\n"
            "Clear the fault and retry the pump connection now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            self._set_status("Pump fault clear cancelled.")
            return
        self._run_action(
            lambda progress: self.app.clear_pump_fault_and_retry(), "Clearing Pump Fault"
        )

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

    # H1 (qmix_backend.py line-by-line review): these buttons used to call
    # self.app.pump.refill()/empty() directly, which returned as soon as the
    # real move was issued, not when it actually completed. Now route through
    # Application.refill()/empty() (which wait for real completion the same
    # way flush() already does) -- converting the bool result to a status
    # string here matches _flush()'s own established pattern just above.
    def _refill(self) -> str:
        return "RefillComplete" if self.app.refill(self.fill_flow_rate.value()) else "RefillTimedOut"

    def _empty(self) -> str:
        return "EmptyComplete" if self.app.empty(self.fill_flow_rate.value()) else "EmptyTimedOut"

    def _start_configure_camera(self) -> None:
        defaults = self._experiment_camera_defaults()
        roi = defaults.roi
        exposure_ms = self.exposure_ms.value()
        center = self.center_roi.isChecked()
        sequence_settings = defaults.sequence_settings(
            frames=self.sequence_frames.value(),
            trigger_source_override=self.dcam_source.currentText(),
        )
        self._run_action(
            lambda progress: self._configure_camera(roi, exposure_ms, center, sequence_settings),
            "Configuring Camera",
        )

    def _camera_sequence_settings(self) -> dict[str, object]:
        return self._experiment_camera_defaults().sequence_settings(
            frames=self.sequence_frames.value(),
            trigger_source_override=self.dcam_source.currentText(),
        )

    def _experiment_camera_defaults(self) -> ExperimentCameraDefaults:
        """Adapt the existing Camera widgets into one shared defaults model."""

        return ExperimentCameraDefaults(
            masterpulse_mode=self.sequence_mode.currentText(),
            masterpulse_source=self.sequence_source.currentText(),
            masterpulse_interval_s=self.sequence_interval.value(),
            masterpulse_burst_times=self.sequence_burst.value(),
            trigger_source=self.dcam_source.currentText(),
            trigger_polarity=self.external_polarity.currentText(),
            trigger_delay_s=self.external_delay.value(),
            roi=SubRegion(
                horizontal_offset=self.roi_h_offset.value(),
                vertical_offset=self.roi_v_offset.value(),
                horizontal_size=self.roi_h_size.value(),
                vertical_size=self.roi_v_size.value(),
            ),
        )

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
        if method == "Fixed Range":
            self.conversion_min.setReadOnly(False)
            self.conversion_max.setReadOnly(False)
            self.conversion_min.setEnabled(True)
            self.conversion_max.setEnabled(True)
            self.conversion_min.setValue(self._fixed_display_range[0])
            self.conversion_max.setValue(self._fixed_display_range[1])
        else:
            self.conversion_min.setReadOnly(True)
            self.conversion_max.setReadOnly(True)
            self.conversion_min.setEnabled(False)
            self.conversion_max.setEnabled(False)
        self.conversion_shifts.setEnabled(method == "Downshift")

    def _remember_fixed_display_range(self) -> None:
        if self.conversion_method.currentText() != "Fixed Range":
            return
        minimum = float(self.conversion_min.value())
        maximum = float(self.conversion_max.value())
        if minimum < maximum:
            self._fixed_display_range = (minimum, maximum)

    def _set_conversion_range(self, display_range: tuple[float, float] | None) -> None:
        if display_range is None:
            return
        minimum, maximum = display_range
        self.conversion_applied_range.setText(f"Applied: {minimum:.3f} – {maximum:.3f}")
        if self.conversion_method.currentText() != "Fixed Range":
            self.conversion_min.setValue(float(minimum))
            self.conversion_max.setValue(float(maximum))

    def _freeze_current_display_range(self) -> None:
        display_range = getattr(self._camera_preview, "_last_display_range", None)
        if display_range is None:
            self._set_status("No dynamic display range is available to freeze")
            return
        self._fixed_display_range = tuple(float(value) for value in display_range)
        self.conversion_method.setCurrentText("Fixed Range")
        self._set_status("Current display range frozen")

    def _display_range_for_method(self) -> tuple[float, float] | None:
        if self.conversion_method.currentText() != "Fixed Range":
            return None
        minimum = float(self.conversion_min.value())
        maximum = float(self.conversion_max.value())
        if minimum >= maximum:
            raise ValueError("fixed display range requires minimum < maximum")
        self._fixed_display_range = (minimum, maximum)
        return self._fixed_display_range

    def _adjust_camera_preview(self) -> None:
        if not self._last_camera_image_data:
            self._set_status("No image captured yet")
            return
        self._ensure_camera_preview()
        method, shifts = self._conversion_policy()
        try:
            fixed_range = self._display_range_for_method()
            display_range = self._camera_preview.show_frame(
                np.asarray(self._last_camera_image_data[-1]),
                method=method,
                shifts=shifts,
                minimum=fixed_range[0] if fixed_range else None,
                maximum=fixed_range[1] if fixed_range else None,
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
            fixed_range = self._display_range_for_method()
            display_range = preview.show_frame(
                np.asarray(image), method=method, shifts=shifts,
                minimum=fixed_range[0] if fixed_range else None,
                maximum=fixed_range[1] if fixed_range else None,
            )
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

        if EXPERIMENT_PLANNING_AUTHORITY == LEGACY_AUTHORITY:
            self._start_experiment_legacy_authority(series_path)
            return

        request = self._experiment_request()
        plan = build_independent_run_plan(request)
        groups = legacy_series_from_run_plan(plan)
        if not groups or not groups[0].experiments:
            raise ValueError("Shared plan did not produce an experiment to execute.")
        config = coerce_wfg_config(groups[0].experiments[0].wfg_config)
        if request.tec_scan_enabled:
            temperature_series = temperature_series_from_request(request)
            self.queue_count.setText(str(sum(group.see_elements_left() for group in groups)))
            self.waveform_graph.set_points(self._preview_points(config))
            self._run_action(
                lambda progress: self._run_temperature_experiment_series(
                    temperature_series, groups, plan.total_frames, config, progress
                ),
                "Running TEC temperature scan",
            )
            return

        series = groups[0]
        self.queue_count.setText(str(series.see_elements_left()))
        self.waveform_graph.set_points(self._preview_points(config))
        self._run_action(
            lambda progress: self._run_experiment_series(series, plan.total_frames, config, progress),
            "Running experiment",
        )

    def _start_experiment_legacy_authority(self, series_path: Path) -> None:
        """Rollback branch retained while shared-plan authority is validated."""
        if self.exp_tec_scan_enable.isChecked():
            temperature_series, groups, total_frames, config = self._build_temperature_experiment_groups(series_path)
            self.queue_count.setText(str(sum(group.see_elements_left() for group in groups)))
            self.waveform_graph.set_points(self._preview_points(config))
            self._run_action(
                lambda progress: self._run_temperature_experiment_series(
                    temperature_series, groups, total_frames, config, progress
                ),
                "Running TEC temperature scan",
            )
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

    def _build_experiment_series(
        self,
        series_root: Path | None = None,
        tec_target_c: float | None = None,
        tec_targets_c: dict[int, float] | None = None,
        *,
        output_root: Path | None = None,
        temperature_point_index: int | None = None,
    ) -> tuple[ExperimentSeries2, int, WfgConfig]:
        series_path = Path(series_root) if series_root is not None else Path(self.series_path.text())
        repeats = self.exp_repeats.value()
        frequency_scan_hz: list[float] | None = None
        if self.exp_freq_scan_enable.isChecked() and self.exp_ch1_function.currentText() != WaveformFunction.DC.value:
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
        fm_sweep = (
            self._experiment_fm_sweep_settings()
            if self.exp_sweep_enable.isChecked() and self.exp_ch1_function.currentText() != WaveformFunction.DC.value
            else None
        )
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
            do_clock = self._experiment_do_clock_config(repeat)
            folder = series_path / f"repeat_{repeat + 1:03d}"
            experiments.append(
                Experiment2(
                    repeat_id=repeat,
                    experiment_folder=folder,
                    output_root=output_root if output_root is not None else series_path,
                    planned_repeat_count=repeats,
                    temperature_point_index=temperature_point_index,
                    frequency_scan_selected_hz=(
                        frequency_scan_hz[repeat] if frequency_scan_hz is not None else None
                    ),
                    flush_settings=self._flush_settings(experiment=True),
                    flush_enabled=self.exp_flush_enabled.isChecked(),
                    global_exposure_ms=self.exp_exposure_ms.value(),
                    requested_exposure_ms=self.exp_exposure_ms.value(),
                    trigger_global_exposure=self.global_exposure.isChecked(),
                    sequence_settings={
                        # The existing Camera widgets edit one shared defaults
                        # model. Automated runs keep their two explicit overrides:
                        # Experiment Frames and deterministic Internal trigger.
                        **self._experiment_camera_defaults().sequence_settings(
                            frames=self.exp_frames.value(),
                            trigger_source_override="Internal",
                        ),
                        "camera_fps": float(self.exp_camera_fps.value()),
                        "camera_start_s": [widget.value() for widget in self.camera_start_array],
                        "camera_start_mode": "dynamic" if self.dynamic_camera_start.isChecked() else "fixed",
                        "camera_start_selected_s": do_clock.channels[0].trigger.sec_wait,
                        # Explicit and deterministic so experiment runs never inherit
                        # whatever trigger source a prior manual Camera tab session left
                        # the DCAM device in. Whether this should be "External" and which
                        # verified AD2 line would pace the camera is still an open bench
                        # question. The current experiment DO config below programs only
                        # DIO1; this deterministic Internal setting removes undefined
                        # leftover state but does not establish physical synchronization.
                    },
                    wfg_config=config,
                    do_clock_settings=do_clock,
                    fm_sweep=fm_sweep,
                    tec_target_c=tec_target_c,
                    tec_targets_c=tec_targets_c,
                )
            )
        return ExperimentSeries2(series_path, experiments), self.exp_frames.value() * repeats, preview_config

    def _temperature_series(self) -> TemperatureSeries:
        return TemperatureSeries.from_text(
            self.exp_tec_points.text(),
            text_ch2=None if self.exp_tec_lock_channels.isChecked() else self.exp_tec_points_ch2.text(),
            tolerance_c=float(self.exp_tec_tolerance_c.value()),
            min_settle_s=float(self.exp_tec_min_settle_s.value()),
            max_wait_s=float(self.exp_tec_max_wait_s.value()),
            poll_interval_s=float(self.exp_tec_poll_interval_s.value()),
            post_stable_hold_s=float(self.exp_tec_post_stable_hold_s.value()),
        )

    def _experiment_request(self) -> ExperimentRequest:
        """Common v1/v2/v3 UI-value adapter for the shared static request.

        It deliberately reads widgets but creates neither legacy experiments nor
        runtime objects.  Planning rules remain in ``experiment_planning``.
        """
        try:
            frequencies = tuple(self._experiment_frequency_scan_list_hz())
        except (TypeError, ValueError):
            frequencies = ()
        targets: list[tuple[tuple[int, float], ...]] = []
        if self.exp_tec_scan_enable.isChecked():
            try:
                temperature_series = self._temperature_series()
                for index in range(len(temperature_series.temperature_points_c)):
                    target = temperature_series.target_at(index)
                    values = (
                        {channel: float(target) for channel in self.app.tec.channels}
                        if isinstance(target, float) else dict(target)
                    )
                    targets.append(tuple(sorted(values.items())))
            except ValueError:
                pass
        dynamic = self.dynamic_camera_start.isChecked()
        starts = tuple(float(widget.value()) for widget in self.camera_start_array)
        fm_sweep = None
        if self.exp_sweep_enable.isChecked() and self.exp_ch1_function.currentText() != WaveformFunction.DC.value:
            sweep = self._experiment_fm_sweep_settings()
            fm_sweep = (sweep.start_hz, sweep.stop_hz, sweep.sweep_time_ms, sweep.sweep_type)
        sequence = self._experiment_camera_defaults().sequence_settings(
            frames=self.exp_frames.value(), trigger_source_override="Internal"
        )
        return ExperimentRequest(
            output_path=Path(self.series_path.text()),
            repeats_per_group=self.exp_repeats.value(),
            frequency_scan_enabled=self.exp_freq_scan_enable.isChecked(),
            frequency_values_hz=frequencies,
            channel0_waveform_function=self.exp_ch1_function.currentText(),
            camera_fps=float(self.exp_camera_fps.value()), frames=self.exp_frames.value(),
            camera_start_s=starts, dynamic_camera_start=dynamic,
            fixed_camera_start_s=float(self.exp_camera_start.value()),
            fm_sweep_enabled=self.exp_sweep_enable.isChecked(),
            channel0_output_selected=self.exp_ad2_channels[0]["enable"].isChecked(),
            flush_enabled=self.exp_flush_enabled.isChecked(), tec_scan_enabled=self.exp_tec_scan_enable.isChecked(),
            temperature_targets_c=tuple(targets),
            tec_settle_settings=(
                float(self.exp_tec_tolerance_c.value()), float(self.exp_tec_min_settle_s.value()),
                float(self.exp_tec_max_wait_s.value()), float(self.exp_tec_poll_interval_s.value()),
                float(self.exp_tec_post_stable_hold_s.value()),
            ),
            device_modes=(
                ("ad2", self.app.ad2.enabled, isinstance(self.app.ad2, SimulatedAD2Sdk)),
                ("camera", self.app.camera.enabled, self.app.camera.simulate),
                ("pump", self.app.pump.enabled, self.app.pump.simulate),
                ("valve", self.app.valve.enabled, self.app.valve.simulate),
                ("tec", self.app.tec.enabled, self.app.tec.simulate),
            ),
            wfg_templates=(asdict(self._experiment_wfg_config()),),
            sequence_settings=tuple(sequence.items()),
            flush_settings=(
                self.exp_flush_flowrate.value(), self.exp_flush_volume.value(),
                self.exp_wait_after_flush.value(), self._syringe_volume_ml(),
            ),
            exposure_ms=float(self.exp_exposure_ms.value()),
            trigger_global_exposure=self.global_exposure.isChecked(), fm_sweep=fm_sweep,
        )

    def _update_tec_lock_button_text(self, *, locked: bool) -> None:
        if locked:
            self.exp_tec_lock_channels.setText("\U0001F517 Locked (CH1 = CH2)")
        else:
            self.exp_tec_lock_channels.setText("\U0001F513 Unlocked (independent)")

    def _on_tec_lock_toggled(self, checked: bool) -> None:
        locked = checked
        self._update_tec_lock_button_text(locked=locked)
        self.exp_tec_points_ch2.setEnabled(not locked)
        if locked:
            # Unlock -> lock: channel 1's current value becomes the new
            # shared value (the less surprising choice -- this is a text
            # field, not a hardware action, so silently discarding
            # channel 2's now-hidden independent value is low-stakes and
            # fully reversible by unlocking again; a confirmation dialog
            # would be friction for a routine toggle).
            self.exp_tec_points_ch2.setText(self.exp_tec_points.text())
        # Lock -> unlock: channel 2 already mirrors channel 1 (kept in
        # sync live by _on_tec_points_ch1_changed while locked), so it
        # already starts from the previously-shared value -- nothing else
        # to do here.

    def _on_tec_points_ch1_changed(self, text: str) -> None:
        if self.exp_tec_lock_channels.isChecked():
            self.exp_tec_points_ch2.setText(text)

    @staticmethod
    def _temperature_folder_name(index: int, temperature_c: float) -> str:
        label = f"{temperature_c:.3f}".replace("-", "m").replace(".", "p")
        return f"temperature_{index:03d}_{label}C"

    def _build_temperature_experiment_groups(
        self, series_path: Path
    ) -> tuple[TemperatureSeries, list[ExperimentSeries2], int, WfgConfig]:
        temperature_series = self._temperature_series()
        if not temperature_series.enabled:
            raise ValueError("Enable TEC temperature scan with at least one temperature point.")
        groups = []
        total_frames = 0
        preview_config: WfgConfig | None = None
        for index, temperature_c in enumerate(temperature_series.temperature_points_c, start=1):
            group_path = series_path / self._temperature_folder_name(index, temperature_c)
            target = temperature_series.target_at(index - 1)
            targets = (
                {channel: float(target) for channel in self.app.tec.channels}
                if isinstance(target, float)
                else dict(target)
            )
            group, frames, config = self._build_experiment_series(
                group_path,
                tec_target_c=temperature_c,
                tec_targets_c=targets,
                output_root=series_path,
                temperature_point_index=index,
            )
            groups.append(group)
            total_frames += frames
            if preview_config is None:
                preview_config = config
        if preview_config is None:
            raise ValueError("TEC temperature scan did not produce any experiment groups.")
        return temperature_series, groups, total_frames, preview_config

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
        experiments = list(series.experiments or [])
        total_repeats = len(experiments)
        lifecycle_manifest = SeriesLifecycleManifest.create(
            series.series_path, requested_repeats=total_repeats
        )
        # "experiment_series_active" progress kind brackets the entire method
        # body (try/finally, so it clears on every exit path: normal
        # completion, ExperimentSeriesAborted, or a raised RuntimeError) --
        # this is the ground truth qt_ui_v2.py's "Experiment running"
        # indicator now reads (see _handle_worker_progress()), instead of
        # its old "experiment" in self.app.status.lower() heuristic, which
        # went stale the instant Abort was clicked (Abort's own
        # "Stopping after {unit}..." status overwrites app.status while the
        # current repeat, if any, may still genuinely be in flight). Emitted via the existing
        # progress-signal mechanism (not set directly) since this method
        # runs on a background QThread (ActionWorker) and progress.emit()
        # is the established way this codebase marshals state back to the
        # main/UI thread.
        if progress:
            progress(
                "series_timing_started",
                {
                    "started_at": started_at,
                    "programmed_remaining_s": _programmed_series_duration_s(experiments),
                },
            )
            progress("experiment_series_active", True)
        try:
            result = self._run_experiment_series_body(
                series,
                total_frames,
                config,
                progress,
                started_at=started_at,
                total_repeats=total_repeats,
                lifecycle_manifest=lifecycle_manifest,
            )
            if lifecycle_manifest.outcome == "IN_PROGRESS":
                lifecycle_manifest.finalize("COMPLETED")
            return result
        except Exception:
            if lifecycle_manifest.outcome == "IN_PROGRESS":
                lifecycle_manifest.finalize("FAILED")
            raise
        finally:
            if progress:
                progress("experiment_series_active", False)

    def _run_temperature_experiment_series(
        self,
        temperature_series: TemperatureSeries,
        groups: list[ExperimentSeries2],
        total_frames: int,
        config: WfgConfig,
        progress=None,
    ) -> str:
        started_at = time.monotonic()
        experiments = [
            experiment
            for group in groups
            for experiment in (group.experiments or [])
        ]
        total_repeats = len(experiments)
        series_path = groups[0].series_path.parent if groups else Path()
        lifecycle_manifest = SeriesLifecycleManifest.create(
            series_path,
            requested_repeats=total_repeats,
            tec_points_requested=len(groups),
        )
        if progress:
            progress(
                "series_timing_started",
                {
                    "started_at": started_at,
                    "programmed_remaining_s": _programmed_series_duration_s(experiments),
                },
            )
            progress("experiment_series_active", True)
            progress("temperature_scan_active", True)
            progress("queue_count", sum(group.see_elements_left() for group in groups))
            progress("waveform", self._preview_points(config))
        self.app.create_stop_event()
        completed_repeats = 0

        def timed_progress(kind: str, value: object) -> None:
            nonlocal completed_repeats
            if progress:
                progress(kind, value)
            if progress and kind == "step_completed" and value == STEP_SAVE_RESULTS:
                completed_repeats += 1
                completed_at = time.monotonic()
                progress(
                    "series_repeat_completed",
                    {
                        "completed_at": completed_at,
                        "elapsed_s": max(completed_at - started_at, 0.0),
                        "completed_repeats": completed_repeats,
                        "total_repeats": total_repeats,
                    },
                )

        try:
            # Same fix as _run_experiment_series_body()'s run_experiment2() call
            # just below it in this file: `progress` was previously dropped
            # here too, so a TEC scan never fired step_started/step_completed/
            # step_failed either -- the v2 breadcrumb (2026-08-04) needs this.
            with action_scope(
                series_path / "action_log.jsonl",
                run_id=series_path.name or "temperature_series",
                condition="temperature_series",
                repeat=None,
                phase="PRE_RUN",
            ):
                completed = self.app.run_temperature_series(
                    temperature_series,
                    groups,
                    progress=timed_progress if progress else None,
                    lifecycle_manifest=lifecycle_manifest,
                )
            if not completed:
                if lifecycle_manifest.outcome == "IN_PROGRESS":
                    lifecycle_manifest.finalize(
                        "GRACEFULLY_ABORTED" if self.app.stop_fired else "FAILED",
                        graceful_abort_requested=self.app.stop_fired,
                    )
                message = f"TEC temperature scan stopped before completion (status={self.app.status!r})."
                logger.error(message)
                raise RuntimeError(message)
            elapsed = max(time.monotonic() - started_at, 0.001)
            if progress:
                progress("queue_count", 0)
                progress("status", self.app.status)
                progress("average_fps", f"{total_frames / elapsed:.2f}")
            return "TemperatureSeriesComplete"
        except Exception:
            if lifecycle_manifest.outcome == "IN_PROGRESS":
                lifecycle_manifest.finalize("FAILED")
            raise
        finally:
            if progress:
                progress("experiment_series_active", False)
                progress("temperature_scan_active", False)

    def _run_experiment_series_body(
        self,
        series: ExperimentSeries2,
        total_frames: int,
        config: WfgConfig,
        progress=None,
        *,
        started_at: float,
        total_repeats: int,
        lifecycle_manifest: SeriesLifecycleManifest,
    ) -> str:
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
                # Abort was triggered (qt_ui.py:_abort()). This is now the
                # ONLY place abort state is ever checked (2026-08-04 safety-
                # behavior change): Abort no longer forces hardware to stop
                # mid-repeat (the removed _abort_hardware()) and
                # run_experiment2()/wait_for_pump() no longer bail early
                # either -- the in-progress repeat, if any, has ALWAYS
                # already run to full completion (capture, AD2 wait, flush,
                # save) by the time this check is reached, since
                # run_experiment2() only returns after that. What this
                # check guarantees is that no *further* queued repeat
                # starts after Abort was pressed.
                remaining = self.app.experiment_series.see_elements_left()
                logger.info(
                    f"Experiment series stopped after {repeat_index} repeat(s): Abort was triggered; "
                    f"{remaining} repeat(s) remain queued and will not run."
                )
                self.app.fire_status_event("ExperimentSeriesAborted")
                lifecycle_manifest.finalize("GRACEFULLY_ABORTED", graceful_abort_requested=True)
                if progress:
                    progress("queue_count", remaining)
                return "ExperimentSeriesAborted"
            # step_started/step_completed/step_failed (fired by application.py's
            # _report_step() inside run_experiment2()) previously never reached
            # the UI at all -- this call omitted `progress`, so v2's Phase 3
            # step-progress breadcrumb (2026-08-04) had nothing to listen to.
            # Fixed here, the real wiring point, not just in a test double.
            lifecycle_manifest.repeat_started()
            try:
                completed = self.app.run_experiment2(progress=progress)
            except Exception:
                lifecycle_manifest.repeat_failed()
                raise
            repeat_index += 1
            if progress:
                progress("queue_count", self.app.experiment_series.see_elements_left())
                progress("status", self.app.status)
            if not completed:
                lifecycle_manifest.repeat_failed()
                message = (
                    f"Experiment series stopped at repeat {repeat_index}: "
                    f"run_experiment2 did not complete (status={self.app.status!r})."
                )
                logger.error(message)
                raise RuntimeError(message)
            if progress:
                lifecycle_manifest.repeat_completed()
                completed_at = time.monotonic()
                progress(
                    "series_repeat_completed",
                    {
                        "completed_at": completed_at,
                        "elapsed_s": max(completed_at - started_at, 0.0),
                        "completed_repeats": repeat_index,
                        "total_repeats": total_repeats,
                    },
                )
            else:
                lifecycle_manifest.repeat_completed()
        elapsed = max(time.monotonic() - started_at, 0.001)
        if self.app.stop_fired:
            # An abort requested during the final in-flight repeat still
            # describes this series as gracefully aborted, even though there
            # was no later queued repeat to suppress.
            self.app.fire_status_event("ExperimentSeriesAborted")
            lifecycle_manifest.finalize("GRACEFULLY_ABORTED", graceful_abort_requested=True)
            return "ExperimentSeriesAborted"
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
        # Safety-behavior change (2026-08-04): Abort no longer forces
        # hardware to stop mid-operation (the removed _abort_hardware(),
        # previously run concurrently on its own QThread regardless of
        # what the in-flight repeat was doing -- confirmed to have no
        # other legitimate caller before removal). Abort now ONLY sets
        # the stop flag qt_ui.py's own _run_experiment_series_body()
        # already checks between repeats -- the currently in-flight
        # repeat, if any, always runs to full completion (capture, AD2
        # wait, flush, save) before the series actually halts. This is
        # deliberate: no separate emergency hard-stop is offered anymore.
        # The manual Pump&Valve tab's own "Stop" button (self.app.pump.stop,
        # wired independently) is unaffected -- that's a distinct,
        # operator-initiated single-instrument action, not part of Abort.
        self.app.fire_stop_event()
        # Part C follow-up, extended 2026-08-04 (TEC-scan abort fix): the
        # unit that finishes before stopping differs by what's running --
        # a plain experiment series finishes "this repeat"; a TEC
        # temperature scan finishes "this temperature point" (target +
        # wait + hold + ALL of that point's own repeats -- see
        # Application.run_temperature_series()'s matching fix). Both
        # progress kinds ("experiment_series_active"/"temperature_scan_active")
        # are set together at series start/end, so this flag reliably picks
        # the right wording.
        unit = "this temperature point" if self._temperature_scan_active else "this repeat"
        self._set_status(f"Stopping after {unit}...")
        # Only show the graceful-stop indicator in the repeat-counter area
        # if a series is actually running -- Abort is reachable (menu
        # action) even when idle, and in that case there is no counter to
        # replace.
        if self._experiment_series_active:
            self._stopping_after_current_repeat = True
            self.queue_count.setText(f"Stopping after {unit}...")

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
        elif kind == "series_timing_started" and isinstance(value, dict):
            started_at = float(value["started_at"])
            self._series_started_at_monotonic = started_at
            self._series_estimate_anchor_at_monotonic = started_at
            self._series_estimated_remaining_at_anchor_s = max(
                float(value.get("programmed_remaining_s", 0.0)), 0.0
            )
            self._series_timing_timer.start()
            self._refresh_series_timing()
        elif kind == "series_repeat_completed" and isinstance(value, dict):
            completed_repeats = int(value.get("completed_repeats", 0))
            total_repeats = int(value.get("total_repeats", 0))
            elapsed_s = max(float(value.get("elapsed_s", 0.0)), 0.0)
            if completed_repeats > 0:
                measured_mean_s = elapsed_s / completed_repeats
                self._series_estimate_anchor_at_monotonic = float(value["completed_at"])
                self._series_estimated_remaining_at_anchor_s = (
                    measured_mean_s * max(total_repeats - completed_repeats, 0)
                )
                self._refresh_series_timing()
        elif kind == "temperature_scan_active":
            self._temperature_scan_active = bool(value)
        elif kind == "experiment_series_active":
            self._experiment_series_active = bool(value)
            if not self._experiment_series_active:
                self._refresh_series_timing()
                self._series_timing_timer.stop()
                self._series_estimated_remaining_at_anchor_s = 0.0
                self.time_left_label.setText("00:00:00")
                # The series just halted (any reason: completed, aborted,
                # or a raised error) -- clear the graceful-stop indicator
                # here, at series-end, rather than waiting for a future
                # series' first repeat to overwrite it. That deliberate
                # reset point is what avoids TestStand's classic stale-
                # highlight mistake (a leftover "Stopping..." from a
                # previous Abort still showing when the next series starts).
                # Also restore a real count immediately -- the last
                # "queue_count" progress event fired while still stopping
                # was suppressed below, so without this the label would be
                # left reading "Stopping..." forever, past the point the
                # series has genuinely already halted.
                if self._stopping_after_current_repeat:
                    self._stopping_after_current_repeat = False
                    self.queue_count.setText(str(self.app.experiment_series.see_elements_left()))
        elif kind == "queue_count":
            if not self._stopping_after_current_repeat:
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
        elif kind == "step_reset":
            self._step_states = dict.fromkeys(STEP_ORDER, "pending")
            self._refresh_step_breadcrumb()
        elif kind == "step_started":
            self._step_states[str(value)] = "active"
            self._refresh_step_breadcrumb()
        elif kind == "step_completed":
            self._step_states[str(value)] = "completed"
            self._refresh_step_breadcrumb()
        elif kind == "step_failed":
            step_name, _message = value
            self._step_states[str(step_name)] = "failed"
            self._refresh_step_breadcrumb()

    def _refresh_series_timing(self) -> None:
        if self._series_started_at_monotonic is None:
            return
        now = time.monotonic()
        elapsed_s = max(now - self._series_started_at_monotonic, 0.0)
        self.elapsed_time_label.setText(_format_duration_s(elapsed_s))

        anchor = self._series_estimate_anchor_at_monotonic
        if anchor is None:
            remaining_s = 0.0
        else:
            remaining_s = max(
                self._series_estimated_remaining_at_anchor_s - max(now - anchor, 0.0),
                0.0,
            )
        self.time_left_label.setText(_format_duration_s(remaining_s, round_up=True))

    def _refresh_step_breadcrumb(self) -> None:
        # No-op in the base (v1) window -- there is no breadcrumb widget to
        # update, only the underlying _step_states being tracked. qt_ui_v2.py's
        # MainWindowV2 overrides this to actually paint its _StepBreadcrumb,
        # the same base-tracks/subclass-renders split _refresh_status() and
        # _experiment_series_active already use elsewhere in this class.
        pass

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
        self._update_manual_focus_controls()

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
            "tec_enabled": self.tec_enabled.isChecked(),
            "sim_ad2": self.sim_ad2.isChecked(),
            "sim_camera": self.sim_camera.isChecked(),
            "sim_pump": self.sim_pump.isChecked(),
            "sim_valve": self.sim_valve.isChecked(),
            "sim_tec": self.sim_tec.isChecked(),
            "z_backend": self.z_backend.currentText(),
            "prior_resource": self.prior_resource.text(),
            "thorlabs_apt_serial": self.thorlabs_apt_serial.text(),
            "thorlabs_apt_backend": self.thorlabs_apt_backend.text(),
            "thorlabs_apt_discovery_only": self.thorlabs_apt_discovery_only.isChecked(),
            "valve_resource": self.valve_resource.text(),
            "tec_port": self.tec_port.text(),
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
            # Save/Load Settings gap-closure, batch 4 (2026-08-05): the WFG
            # manual tab's own master On/Off toggle (feeds WfgConfig.running
            # in _wfg_config()) -- previously unpersisted. A plain top-level
            # key, not nested under a new "wfg" sub-dict: that name is
            # already the per-channel list immediately above, and reusing it
            # for a second, differently-shaped value would collide.
            # Confirmed via grep: no connected .toggled/.stateChanged signal
            # on this checkbox, so it is not a live action trigger the way
            # image_continuous (batch 2) was.
            "wfg_running": self.wfg_running.isChecked(),
            "mso": {
                "ch1_enabled": self.mso_ch1_enabled.isChecked(),
                "ch2_enabled": self.mso_ch2_enabled.isChecked(),
                "trigger_source": self.mso_trigger_source.currentText(),
                "sample_frequency_hz": self.mso_sample_frequency.value(),
                "sample_count": self.mso_sample_count.value(),
                "range_v": self.mso_range.value(),
                "offset_v": self.mso_offset.value(),
            },
            # Save/Load Settings gap-closure, batch 1 (2026-08-04): Pump&Valve
            # manual tab's own fields -- previously entirely unpersisted,
            # including fill_flow_rate specifically (subject of an earlier,
            # never-actually-executed instruction to persist it -- confirmed
            # via audit, not a lost completion). Own sub-dict, mirroring
            # "mso" above, per that audit's own recommendation. Distinct keys
            # from "experiment"'s own flush_flowrate/flush_volume/
            # wait_after_flush (self.exp_flush_flowrate etc.) -- these are
            # the separate manual-tab widgets (self.flush_flowrate etc.),
            # never the same Qt objects, so no collision either at the
            # Python-attribute or the settings.json-key level.
            "pump_valve": {
                "syringe": self.syringe.currentText(),
                "custom_syringe_volume_ml": self.custom_syringe_volume_ml.value(),
                "custom_syringe_inner_diameter_mm": self.custom_syringe_inner_diameter_mm.value(),
                "custom_syringe_stroke_mm": self.custom_syringe_stroke_mm.value(),
                "flow_rate": self.flow_rate.value(),
                "fill_flow_rate": self.fill_flow_rate.value(),
                "level_ml": self.level_ml.value(),
                "flush_flowrate": self.flush_flowrate.value(),
                "flush_volume": self.flush_volume.value(),
                "wait_after_flush": self.wait_after_flush.value(),
                "flush_count": self.flush_count.value(),
            },
            # Save/Load Settings gap-closure, batch 2 (2026-08-04): Camera
            # manual tab's own fields -- previously entirely unpersisted,
            # same as batch 1's Pump&Valve tab. Own sub-dict, same shape.
            # conversion_min/conversion_max remain derived/applied readouts;
            # the explicit Fixed Range preference is persisted separately.
            # Distinct key from "experiment"'s own exposure_ms
            # (self.exp_exposure_ms) -- self.exposure_ms here is the
            # separate manual ROI-group widget, never the same Qt object.
            "camera": {
                "roi_h_offset": self.roi_h_offset.value(),
                "roi_v_offset": self.roi_v_offset.value(),
                "roi_h_size": self.roi_h_size.value(),
                "roi_v_size": self.roi_v_size.value(),
                "center_roi": self.center_roi.isChecked(),
                "exposure_ms": self.exposure_ms.value(),
                "conversion_method": self.conversion_method.currentText(),
                "conversion_shifts": self.conversion_shifts.value(),
                "conversion_fixed_min": self._fixed_display_range[0],
                "conversion_fixed_max": self._fixed_display_range[1],
                "sequence_mode": self.sequence_mode.currentText(),
                "sequence_source": self.sequence_source.currentText(),
                "sequence_interval": self.sequence_interval.value(),
                "sequence_burst": self.sequence_burst.value(),
                "sequence_frames": self.sequence_frames.value(),
                "capture_mode": self.capture_mode.currentText(),
                "dcam_source": self.dcam_source.currentText(),
                "external_polarity": self.external_polarity.currentText(),
                "external_delay": self.external_delay.value(),
                "sequence_exposure_ms": self.sequence_exposure_ms.value(),
                # image_continuous deliberately EXCLUDED, not missed: unlike
                # every other field here, it is a live action trigger, not
                # passive configuration -- toggling it True
                # (_set_image_continuous(), toggled.connect()'d) opens a real
                # ImagePreviewWindow, starts a repeating QTimer, and attempts
                # a live camera capture. Restoring it via _load_settings()
                # would auto-start continuous capture the instant settings
                # are loaded, before hardware is even connected -- the same
                # class of thing conversion_min/conversion_max were already
                # excluded for above (a live/derived value, not a saved
                # preference), just via a different mechanism (an action
                # side effect instead of a computed readout).
            },
            # Save/Load Settings gap-closure, batch 3 (2026-08-05): Z-Scan
            # tab's own fields -- previously entirely unpersisted, same
            # disposition as batches 1-2. Own sub-dict, same shape. Confirmed
            # none of the 5 fields fire a connected signal on
            # setValue/setChecked/setText (grepped for .valueChanged/
            # .textChanged/.editingFinished connections on all 5 -- none
            # exist), so none is a live action trigger the way
            # image_continuous was. zscan_z_start_um/zscan_z_end_um needed a
            # different, real correctness fix instead: both are disabled at
            # construction with range [0.0, 0.0] until _query_zscan_range()
            # reads the real piezo's MaxTravel and calls
            # _apply_zscan_range() to widen the range and enable them -- a
            # bare setValue() at load time (before any hardware has ever
            # been queried) would silently clamp a real saved value straight
            # to 0.0, a quiet data-loss trap distinct from but analogous to
            # image_continuous's crash risk. Handled below in
            # _load_settings() by widening the range just enough to hold the
            # loaded value; _apply_zscan_range() still fully overwrites that
            # range with the real device bound the next time it is queried,
            # so this does not weaken that safety gate.
            "zscan": {
                "zscan_output_dir": self.zscan_output_dir.text(),
                "zscan_z_start_um": self.zscan_z_start_um.value(),
                "zscan_z_end_um": self.zscan_z_end_um.value(),
                "zscan_step_size_um": self.zscan_step_size_um.value(),
                "zscan_exposure_ms": self.zscan_exposure_ms.value(),
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
                "tec_scan_enable": self.exp_tec_scan_enable.isChecked(),
                "tec_points": self.exp_tec_points.text(),
                "tec_lock_channels": self.exp_tec_lock_channels.isChecked(),
                "tec_points_ch2": self.exp_tec_points_ch2.text(),
                "tec_tolerance_c": self.exp_tec_tolerance_c.value(),
                "tec_min_settle_s": self.exp_tec_min_settle_s.value(),
                "tec_max_wait_s": self.exp_tec_max_wait_s.value(),
                "tec_poll_interval_s": self.exp_tec_poll_interval_s.value(),
                "tec_post_stable_hold_s": self.exp_tec_post_stable_hold_s.value(),
                # Save/Load Settings gap-closure, batch 4 (2026-08-05):
                # purely additive keys under this same "experiment" dict,
                # same convention as Frequency Scanning/TEC above -- no
                # schema_version bump. Confirmed via grep: none of these
                # fields (nor camera_start_array below) has a connected
                # .valueChanged/.toggled/.stateChanged signal with a real
                # side effect -- the FM Sweep start/stop<->center/width
                # cross-field sync (_connect_sweep_dual_mode_refresh()) is
                # pure UI-side arithmetic (no hardware/window/timer touch),
                # not a live action trigger the way image_continuous (batch
                # 2) was; loading all four keeps them mutually consistent
                # the same way editing any one live already does. None of
                # these fields is disabled/range-gated behind a hardware
                # query the way zscan_z_start_um/zscan_z_end_um (batch 3)
                # were, so no special load-time handling is needed here.
                "sweep_enable": self.exp_sweep_enable.isChecked(),
                "sweep_start_khz": self.exp_sweep_start_khz.value(),
                "sweep_stop_khz": self.exp_sweep_stop_khz.value(),
                "sweep_center_khz": self.exp_sweep_center_khz.value(),
                "sweep_width_khz": self.exp_sweep_width_khz.value(),
                "sweep_time_ms": self.exp_sweep_time_ms.value(),
                "sweep_type": self.exp_sweep_type.currentText(),
                "camera_fps": self.exp_camera_fps.value(),
                "camera_start": self.exp_camera_start.value(),
                "dynamic_camera_start": self.dynamic_camera_start.isChecked(),
                "camera_start_array": [widget.value() for widget in self.camera_start_array],
                "global_exposure": self.global_exposure.isChecked(),
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
            ("tec_enabled", self.tec_enabled),
            ("sim_ad2", self.sim_ad2),
            ("sim_camera", self.sim_camera),
            ("sim_pump", self.sim_pump),
            ("sim_valve", self.sim_valve),
            ("sim_tec", self.sim_tec),
            ("thorlabs_apt_discovery_only", self.thorlabs_apt_discovery_only),
            ("wfg_running", self.wfg_running),
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
            ("tec_port", self.tec_port),
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
        pump_valve = data.get("pump_valve", {})
        if isinstance(pump_valve, dict):
            if "syringe" in pump_valve:
                index = self.syringe.findText(str(pump_valve["syringe"]))
                if index >= 0:
                    self.syringe.setCurrentIndex(index)
            for key, widget in (
                ("custom_syringe_volume_ml", self.custom_syringe_volume_ml),
                ("custom_syringe_inner_diameter_mm", self.custom_syringe_inner_diameter_mm),
                ("custom_syringe_stroke_mm", self.custom_syringe_stroke_mm),
                ("flow_rate", self.flow_rate),
                ("fill_flow_rate", self.fill_flow_rate),
                ("level_ml", self.level_ml),
                ("flush_flowrate", self.flush_flowrate),
                ("flush_volume", self.flush_volume),
                ("wait_after_flush", self.wait_after_flush),
                ("flush_count", self.flush_count),
            ):
                if key in pump_valve:
                    widget.setValue(pump_valve[key])
        camera = data.get("camera", {})
        if isinstance(camera, dict):
            for key, widget in (
                ("roi_h_offset", self.roi_h_offset),
                ("roi_v_offset", self.roi_v_offset),
                ("roi_h_size", self.roi_h_size),
                ("roi_v_size", self.roi_v_size),
                ("exposure_ms", self.exposure_ms),
                ("conversion_shifts", self.conversion_shifts),
                ("sequence_interval", self.sequence_interval),
                ("sequence_burst", self.sequence_burst),
                ("sequence_frames", self.sequence_frames),
                ("external_delay", self.external_delay),
                ("sequence_exposure_ms", self.sequence_exposure_ms),
            ):
                if key in camera:
                    widget.setValue(camera[key])
            if "center_roi" in camera:
                self.center_roi.setChecked(bool(camera["center_roi"]))
            if "conversion_fixed_min" in camera and "conversion_fixed_max" in camera:
                minimum = float(camera["conversion_fixed_min"])
                maximum = float(camera["conversion_fixed_max"])
                if np.isfinite(minimum) and np.isfinite(maximum) and minimum < maximum:
                    self._fixed_display_range = (minimum, maximum)
            # image_continuous intentionally not loaded -- see the matching
            # exclusion comment in _settings_dict() above.
            for key, widget in (
                ("conversion_method", self.conversion_method),
                ("sequence_mode", self.sequence_mode),
                ("sequence_source", self.sequence_source),
                ("capture_mode", self.capture_mode),
                ("dcam_source", self.dcam_source),
                ("external_polarity", self.external_polarity),
            ):
                if key in camera:
                    _set_combo_text(widget, str(camera[key]))
        zscan = data.get("zscan", {})
        if isinstance(zscan, dict):
            if "zscan_output_dir" in zscan:
                self.zscan_output_dir.setText(str(zscan["zscan_output_dir"]))
            # zscan_z_start_um/zscan_z_end_um start disabled with range
            # [0.0, 0.0] until a real "Query Piezo Range" hardware call
            # widens it (see the matching comment in _settings_dict()) -- a
            # plain setValue() here would silently clamp a real saved value
            # to 0.0 before that ever happens. Widen the range just enough
            # to hold the loaded value first; _apply_zscan_range() still
            # fully replaces this range with the real device bound the next
            # time it runs, so this does not weaken that gate, and the
            # field stays disabled exactly as it already does by default.
            for key, widget in (
                ("zscan_z_start_um", self.zscan_z_start_um),
                ("zscan_z_end_um", self.zscan_z_end_um),
            ):
                if key in zscan:
                    value = float(zscan[key])
                    if value > widget.maximum():
                        widget.setMaximum(value)
                    widget.setValue(value)
            for key, widget in (
                ("zscan_step_size_um", self.zscan_step_size_um),
                ("zscan_exposure_ms", self.zscan_exposure_ms),
            ):
                if key in zscan:
                    widget.setValue(zscan[key])
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
                "tec_tolerance_c": self.exp_tec_tolerance_c,
                "tec_min_settle_s": self.exp_tec_min_settle_s,
                "tec_max_wait_s": self.exp_tec_max_wait_s,
                "tec_poll_interval_s": self.exp_tec_poll_interval_s,
                "tec_post_stable_hold_s": self.exp_tec_post_stable_hold_s,
                "sweep_start_khz": self.exp_sweep_start_khz,
                "sweep_stop_khz": self.exp_sweep_stop_khz,
                "sweep_center_khz": self.exp_sweep_center_khz,
                "sweep_width_khz": self.exp_sweep_width_khz,
                "sweep_time_ms": self.exp_sweep_time_ms,
                "camera_fps": self.exp_camera_fps,
                "camera_start": self.exp_camera_start,
            }
            for key, widget in mapping.items():
                if key in experiment:
                    widget.setValue(experiment[key])
            if "tec_points" in experiment:
                self.exp_tec_points.setText(str(experiment["tec_points"]))
            for key, widget in (
                ("ch1_function", self.exp_ch1_function),
                ("ch1_trigger_source", self.exp_ch1_trigger_source),
                ("ch2_function", self.exp_ch2_function),
                ("ch2_trigger_source", self.exp_ch2_trigger_source),
                ("sweep_type", self.exp_sweep_type),
            ):
                if key in experiment:
                    _set_combo_text(widget, str(experiment[key]))
            for key, widget in (
                ("ch1_enable", self.exp_ch1_enable),
                ("ch2_enable", self.exp_ch2_enable),
                ("ch1_repeat_trigger", self.exp_ch1_repeat_trigger),
                ("ch2_repeat_trigger", self.exp_ch2_repeat_trigger),
                ("freq_scan_enable", self.exp_freq_scan_enable),
                ("tec_scan_enable", self.exp_tec_scan_enable),
                # Absent (older saved settings, pre-dual-channel-lock) ->
                # setChecked() simply isn't called -> stays at its current
                # default (locked=True), matching "default to locked for
                # any config that doesn't specify it."
                ("tec_lock_channels", self.exp_tec_lock_channels),
                ("sweep_enable", self.exp_sweep_enable),
                ("dynamic_camera_start", self.dynamic_camera_start),
                ("global_exposure", self.global_exposure),
            ):
                if key in experiment:
                    widget.setChecked(bool(experiment[key]))
            if "camera_start_array" in experiment:
                for widget, value in zip(self.camera_start_array, experiment["camera_start_array"]):
                    widget.setValue(value)
            # Restored AFTER tec_lock_channels above, deliberately: toggling
            # the lock checkbox mirrors channel 1 into channel 2 as a live
            # UI side effect (_on_tec_lock_toggled()) -- setting channel 2's
            # own saved text here, last, guarantees an exact save/load round
            # trip regardless of that side effect, in both locked and
            # unlocked saved states.
            if "tec_points_ch2" in experiment:
                self.exp_tec_points_ch2.setText(str(experiment["tec_points_ch2"]))
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
# but is a transitional UI and not yet the default launch target.
def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
