"""Fixed-form series controls; all expansion and execution live in application code."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGridLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QScrollArea, QSpinBox, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..application.experiments import validate_definition
from ..application.experiment_runner import BATCH_ACTIVE_STATES
from ..application.commands import DeviceCommand, DeviceOperation, NoArguments
from ..application.simple_preflight import SimpleSeriesPreflight
from ..application.simple_series import NumericRange, SimpleSeriesSettings, compile_simple_series
from ..domain.models import ConnectionState, DeviceId, PumpReadback, TecReadback
from .widgets import CollapsibleSection


def number(value: float, minimum: float = 0, maximum: float = 100_000_000,
           decimals: int = 6) -> QDoubleSpinBox:
    control = QDoubleSpinBox()
    control.setRange(minimum, maximum)
    control.setDecimals(decimals)
    control.setValue(value)
    control.setKeyboardTracking(False)
    return control


def integer(value: int, minimum: int = 1, maximum: int = 100_000) -> QSpinBox:
    control = QSpinBox()
    control.setRange(minimum, maximum)
    control.setValue(value)
    control.setKeyboardTracking(False)
    return control


class SimpleSeriesPanel(QWidget):
    def __init__(self, controller, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.manager = controller.experiments
        self.preflight = SimpleSeriesPreflight(controller, self)
        self._queued_settings: dict[str, SimpleSeriesSettings] = {}
        # The one queued series the form is editing (set only by "Load selected for editing").
        # Update acts on this folder, never on whatever row is selected in the list.
        self._editing_folder: str | None = None
        self._edit_target_lost = False
        self._edit_buttons_allowed = True
        self._start_locked = False
        self._camera_import_request: str | None = None
        # Set by _apply_settings() when a loaded flush_unit_index isn't
        # among the pump_unit combo's current choices (most commonly:
        # nothing is connected yet). Consumed by _devices() once the pump
        # actually connects and the combo is repopulated -- restores the
        # saved selection instead of silently leaving Qt's own "first item
        # becomes current" default in place. Cleared once matched.
        self._pending_flush_unit_index: int | None = None
        root = QVBoxLayout(self)
        # Two free-to-visit pages of one form; neither is a required step. The Configure
        # page edits the form, the Review page works on what is queued.
        self.pages = QTabWidget()
        root.addWidget(self.pages, 1)
        configure_page = QWidget()
        configure_layout = QVBoxLayout(configure_page)
        self.edit_target_label = QLabel()
        self.edit_target_label.setWordWrap(True)
        configure_layout.addWidget(self.edit_target_label)
        scan_order = QLabel("Scan order: temperature → frequency → sweep width → amplitude → exposure → repeats")
        scan_order.setWordWrap(True)
        configure_layout.addWidget(scan_order)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        self._body = body
        grid = QGridLayout(body)
        scroll.setWidget(body)
        configure_layout.addWidget(scroll, 1)
        self.pages.addTab(configure_page, "Configure")

        output = QGroupBox("Output and acquisition")
        form = QFormLayout(output)
        self.description = QLineEdit()
        self.description.setPlaceholderText("Required: describe this experiment series")
        form.addRow("Series descriptor", self.description)
        self.output_root = QLineEdit()
        self.choose_root = QPushButton("Browse…")
        folder = QWidget()
        folder_row = QHBoxLayout(folder)
        folder_row.setContentsMargins(0, 0, 0, 0)
        folder_row.addWidget(self.output_root, 1)
        folder_row.addWidget(self.choose_root)
        form.addRow("Experiment base folder", folder)
        self.repeats = integer(1)
        self.frames = integer(10)
        self.fps = number(10, 0.001)
        self.tiff_format = QComboBox()
        self.tiff_format.addItem("Individual TIFF", "frames")
        self.tiff_format.addItem("Stacked TIFF", "stacked")
        for label, control in (("Number of repeats", self.repeats),
                               ("Number of frames", self.frames),
                               ("Camera FPS", self.fps),
                               ("Image format", self.tiff_format)):
            form.addRow(label, control)
        left_groups = [output]

        timing = QGroupBox("Hardware timing from PC trigger")
        form = QFormLayout(timing)
        self.sound_start = number(0)
        self.sound_run = number(1, 0.001)
        self.laser_start = number(0)
        self.laser_run = number(0.1, 0.001)
        self.camera_start = number(0.1)
        for label, control in (("Sound start (s)", self.sound_start),
                               ("Sound run time (s)", self.sound_run),
                               ("Laser start (s)", self.laser_start),
                               ("Laser run time (s), fixed 5 V", self.laser_run),
                               ("Camera start (s)", self.camera_start)):
            form.addRow(label, control)

        frequency = QGroupBox("Ultrasound")
        form = QFormLayout(frequency)
        self.frequency = self._range(form, "Center frequency (Hz)", 1_000_000, 1_000_000)
        self.amplitude = self._range(form, "AD2 source peak amplitude (V)", 1, 1, maximum=5)
        self.sweep_enabled = QCheckBox("Frequency sweep · frequency values become center frequencies")
        form.addRow(self.sweep_enabled)
        self.sweep_width = self._range(form, "Full sweep width (Hz)", 100_000, 100_000)
        self.sweep_period = number(1, 0.001, 1_000_000)
        form.addRow("Sweep period (ms), triangle", self.sweep_period)
        left_groups.append(frequency)

        temperature = QGroupBox("Temperature")
        form = QFormLayout(temperature)
        self.temperature_control = QCheckBox("Control temperature")
        self.temperature_logging = QCheckBox("Log both TEC channels throughout series (1 s)")
        self.tec_channel = QComboBox()
        self.tec_channel.addItem("Channel 1", 1)
        self.tec_channel.addItem("Channel 2", 2)
        self.temperature = self._range(form, "Temperature (°C)", 25, 25, minimum=0, maximum=80)
        self.temperature_wait_for_stability = QCheckBox(
            "Wait for the controller to confirm stability (instead of a fixed duration alone)")
        self.temperature_tolerance = number(0.2, 0, 100)
        self.temperature_min_settle = number(5, 0, 86_400)
        self.temperature_max_wait = number(300, 0.001, 86_400)
        self.temp_wait = number(30, 0, 86_400)
        form.insertRow(0, self.temperature_control)
        form.addRow("Controlled channel", self.tec_channel)
        form.addRow(self.temperature_wait_for_stability)
        form.addRow("Additional hold once stable, or fixed wait (s)", self.temp_wait)
        form.addRow(self.temperature_logging)
        right_groups = [temperature]
        stability = QGroupBox("Temperature stability policy")
        form = QFormLayout(stability)
        form.addRow("Tolerance (°C)", self.temperature_tolerance)
        form.addRow("Minimum time within tolerance (s)", self.temperature_min_settle)
        form.addRow("Maximum wait for stability (s)", self.temperature_max_wait)

        camera = QGroupBox("Camera")
        form = QFormLayout(camera)
        self.exposure = self._range(form, "Exposure (ms)", 1, 1)
        self.roi_x = integer(0, 0)
        self.roi_y = integer(0, 0)
        self.roi_width = integer(512)
        self.roi_height = integer(512)
        for label, control in (("ROI X", self.roi_x), ("ROI Y", self.roi_y),
                               ("ROI width", self.roi_width), ("ROI height", self.roi_height)):
            form.addRow(label, control)
        self.import_camera = QPushButton("Import ROI and exposure from camera")
        form.addRow(self.import_camera)
        left_groups.append(camera)
        self.camera_preflight_label = QLabel("Camera preflight: No")

        fluidics = QGroupBox("Flush")
        form = QFormLayout(fluidics)
        self.pump_unit = QComboBox()
        self.pump_unit_notice = QLabel("")
        self.volume = number(0.1, 0.000001, 1000)
        self.flow = number(500, 0.000001, 1_000_000)
        self.wait_after_flush = number(0, 0, 100, 3)
        form.addRow("Pump unit", self.pump_unit)
        form.addRow(self.pump_unit_notice)
        form.addRow("Volume (mL)", self.volume)
        form.addRow("Flow (µL/min)", self.flow)
        form.addRow("Wait after flush (s)", self.wait_after_flush)
        form.addRow(QLabel("One initial flush and one after every acquisition."))
        right_groups.append(fluidics)

        self.preflight_button = QPushButton("Preflight camera settings")
        self.syringe_preflight_button = QPushButton("Preflight batch syringe level")
        self.queue_button = QPushButton("Queue series")
        self.load_button = QPushButton("Load selected for editing")
        self.update_button = QPushButton("Update loaded series")
        self.remove_button = QPushButton("Remove selected series")
        self.start_button = QPushButton("Start queued batch")
        self.start_button.setStyleSheet("font-weight: 600; padding: 6px 18px")
        self.start_button.setToolTip(
            "Starts the queued series. Stop after current, Abort and Panic are always visible "
            "at the top of the window while it runs.")

        # Advanced values stay editable and are still saved/queued while folded away; the
        # folded header summarizes them so a non-default value is not hidden from view.
        self.advanced = CollapsibleSection("Advanced: hardware timing and temperature stability")
        advanced_body = QWidget()
        advanced_grid = QGridLayout(advanced_body)
        advanced_grid.setContentsMargins(0, 0, 0, 0)
        advanced_grid.addWidget(timing, 0, 0)
        advanced_grid.addWidget(stability, 0, 1)
        advanced_grid.setColumnStretch(0, 1)
        advanced_grid.setColumnStretch(1, 1)
        self.advanced.set_content(advanced_body)
        self._left_groups, self._right_groups = left_groups, right_groups
        self._grid_columns = 0
        self._body_grid = grid
        self._arrange_groups(2)

        self.config_hint = QLabel()
        self.config_hint.setWordWrap(True)
        configure_actions = QHBoxLayout()
        configure_actions.addWidget(self.queue_button)
        configure_actions.addWidget(self.update_button)
        configure_actions.addWidget(self.config_hint, 1)
        configure_layout.addLayout(configure_actions)

        review_page = QScrollArea()
        review_page.setWidgetResizable(True)
        review_body = QWidget()
        review_layout = QVBoxLayout(review_body)
        review_page.setWidget(review_body)
        self.pages.addTab(review_page, "Review and start")
        queue_group = QGroupBox("Series in this batch")
        queue_layout = QVBoxLayout(queue_group)
        self.batch_list = QTreeWidget()
        self.batch_list.setHeaderLabels(["Series descriptor", "State", "Experiments",
                                         "Camera preflight", "Syringe preflight", "Output folder"])
        self.batch_list.setMinimumHeight(110)
        self._batch_snapshot = None
        queue_layout.addWidget(self.batch_list)
        queue_actions = QHBoxLayout()
        queue_actions.addWidget(self.load_button)
        queue_actions.addWidget(self.remove_button)
        queue_actions.addStretch(1)
        queue_layout.addLayout(queue_actions)
        review_layout.addWidget(queue_group)
        checks = QGroupBox("Preflight checks")
        checks_layout = QGridLayout(checks)
        checks_layout.addWidget(self.preflight_button, 0, 0)
        checks_layout.addWidget(self.camera_preflight_label, 0, 1)
        checks_layout.addWidget(self.syringe_preflight_button, 1, 0)
        checks_layout.setColumnStretch(2, 1)
        note = QLabel("Start asks for confirmation if the camera preflight is not current for a queued "
                      "series; in real mode Start requires the batch syringe preflight.")
        note.setWordWrap(True)
        checks_layout.addWidget(note, 2, 0, 1, 3)
        review_layout.addWidget(checks)
        summary_group = QGroupBox("Plan for the current form values")
        summary_layout = QVBoxLayout(summary_group)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        summary_layout.addWidget(self.summary)
        review_layout.addWidget(summary_group)
        self.start_readiness_label = QLabel()
        self.start_readiness_label.setWordWrap(True)
        self.start_readiness_label.setTextFormat(Qt.TextFormat.RichText)
        start_row = QHBoxLayout()
        start_row.addWidget(self.start_button, 0, Qt.AlignmentFlag.AlignTop)
        start_row.addWidget(self.start_readiness_label, 1)
        review_layout.addLayout(start_row)
        review_layout.addStretch(1)
        self.state_label = QLabel()
        self.state_label.setWordWrap(True)
        root.addWidget(self.state_label)

        self.choose_root.clicked.connect(self._choose_root)
        self.import_camera.clicked.connect(self._import_camera)
        self.preflight_button.clicked.connect(self._preflight)
        self.syringe_preflight_button.clicked.connect(self._preflight_syringe)
        self.queue_button.clicked.connect(self._queue)
        self.load_button.clicked.connect(self._load_selected)
        self.update_button.clicked.connect(self._update_selected)
        self.remove_button.clicked.connect(self._remove_selected)
        self.start_button.clicked.connect(self._start)
        self.preflight.finished.connect(self._preflight_finished)
        self.manager.changed.connect(self._status)
        self.controller.status_changed.connect(self._devices)
        self.controller.command_result.connect(self._camera_import_result)
        self.controller.panic_changed.connect(self._panic_changed)
        self.sweep_enabled.toggled.connect(self._enabled)
        self.temperature_control.toggled.connect(self._enabled)
        self.temperature_wait_for_stability.toggled.connect(self._enabled)
        for widget in self.findChildren(QSpinBox) + self.findChildren(QDoubleSpinBox):
            widget.valueChanged.connect(self._preview)
        for widget in (self.sweep_enabled, self.temperature_control, self.temperature_logging,
                       self.temperature_wait_for_stability):
            widget.toggled.connect(self._preview)
        self.description.textChanged.connect(self._preview)
        self.pump_unit.currentIndexChanged.connect(self._pump_unit_selected)
        self._enabled()
        self._devices(controller.statuses())
        self._preview()
        self._status(self.manager.status())

    def _arrange_groups(self, columns: int) -> None:
        """One column on a narrow window, two otherwise; only moves existing widgets."""
        if columns == self._grid_columns:
            return
        self._grid_columns = columns
        grid = self._body_grid
        for group in (*self._left_groups, *self._right_groups, self.advanced):
            grid.removeWidget(group)
        if columns == 1:
            groups = [*self._left_groups, *self._right_groups]
            for row, group in enumerate(groups):
                grid.addWidget(group, row, 0, 1, 2)
            rows = len(groups)
        else:
            for row, group in enumerate(self._left_groups):
                grid.addWidget(group, row, 0)
            for row, group in enumerate(self._right_groups):
                grid.addWidget(group, row, 1)
            rows = max(len(self._left_groups), len(self._right_groups))
        grid.addWidget(self.advanced, rows, 0, 1, 2)
        for row in range(rows + 2):
            grid.setRowStretch(row, 1 if row == rows + 1 else 0)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._arrange_groups(1 if self.width() < 1000 else 2)

    @staticmethod
    def _range(form: QFormLayout, label: str, start: float, stop: float,
               *, minimum: float = 0, maximum: float = 100_000_000) -> tuple:
        box = QWidget()
        row = QGridLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        start_widget = number(start, minimum, maximum)
        stop_widget = number(stop, minimum, maximum)
        steps = integer(1)
        steps_tip = ("Steps is the number of evenly spaced values. With 1 step, only Start is used "
                     "and Stop is ignored. With 2 or more steps, both endpoints are included.")
        steps.setToolTip(steps_tip)
        stop_widget.setToolTip(steps_tip)
        steps_label = QLabel("Steps")
        steps_label.setToolTip(steps_tip)
        for column, (caption, control) in enumerate(((QLabel("Start"), start_widget),
                                                     (QLabel("Stop"), stop_widget),
                                                     (steps_label, steps))):
            row.addWidget(caption, 0, column)
            row.addWidget(control, 1, column)
            row.setColumnStretch(column, 1)
        form.addRow(label, box)
        return start_widget, stop_widget, steps

    @staticmethod
    def _values(controls: tuple) -> NumericRange:
        return NumericRange(controls[0].value(), controls[1].value(), controls[2].value())

    def _settings(self, *, require_pump_unit: bool = True) -> SimpleSeriesSettings:
        # require_pump_unit=False is for the settings-profile save path only
        # (MainWindow.profile_document()): capturing every form input must
        # not require a pump to be connected, unlike actually compiling or
        # queuing an experiment, which still needs a real flush unit and
        # keeps the default True behavior unchanged.
        if require_pump_unit and self.pump_unit.currentData() is None:
            raise ValueError("Select a configured pump unit")
        return SimpleSeriesSettings(
            repeats=self.repeats.value(), frame_count=self.frames.value(), camera_fps=self.fps.value(),
            sound_start_s=self.sound_start.value(), sound_run_s=self.sound_run.value(),
            laser_start_s=self.laser_start.value(), laser_run_s=self.laser_run.value(),
            camera_start_s=self.camera_start.value(), frequency_hz=self._values(self.frequency),
            amplitude_v=self._values(self.amplitude), exposure_ms=self._values(self.exposure),
            roi=(self.roi_x.value(), self.roi_y.value(), self.roi_width.value(), self.roi_height.value()),
            flush_unit_index=(self.pump_unit.currentData()
                              if self.pump_unit.currentData() is not None
                              else self._pending_flush_unit_index), flush_volume_ml=self.volume.value(),
            flush_flow_ul_min=self.flow.value(), flush_wait_after_s=self.wait_after_flush.value(),
            description=self.description.text().strip(), sweep_enabled=self.sweep_enabled.isChecked(),
            sweep_width_hz=self._values(self.sweep_width), sweep_period_ms=self.sweep_period.value(),
            temperature_control=self.temperature_control.isChecked(), tec_channel=self.tec_channel.currentData(),
            temperature_c=self._values(self.temperature), temperature_wait_s=self.temp_wait.value(),
            temperature_logging=self.temperature_logging.isChecked(), tiff_format=self.tiff_format.currentData(),
            temperature_wait_for_stability=self.temperature_wait_for_stability.isChecked(),
            temperature_tolerance_c=self.temperature_tolerance.value(),
            temperature_min_settle_s=self.temperature_min_settle.value(),
            temperature_max_wait_s=self.temperature_max_wait.value(),
        )

    def _apply_settings(self, settings: SimpleSeriesSettings) -> None:
        for widget, value in (
            (self.repeats, settings.repeats), (self.frames, settings.frame_count),
            (self.fps, settings.camera_fps), (self.sound_start, settings.sound_start_s),
            (self.sound_run, settings.sound_run_s), (self.laser_start, settings.laser_start_s),
            (self.laser_run, settings.laser_run_s), (self.camera_start, settings.camera_start_s),
            (self.roi_x, settings.roi[0]), (self.roi_y, settings.roi[1]),
            (self.roi_width, settings.roi[2]), (self.roi_height, settings.roi[3]),
            (self.volume, settings.flush_volume_ml), (self.flow, settings.flush_flow_ul_min),
            (self.wait_after_flush, settings.flush_wait_after_s),
            (self.sweep_period, settings.sweep_period_ms), (self.temp_wait, settings.temperature_wait_s),
            (self.temperature_tolerance, settings.temperature_tolerance_c),
            (self.temperature_min_settle, settings.temperature_min_settle_s),
            (self.temperature_max_wait, settings.temperature_max_wait_s),
        ):
            widget.setValue(value)
        for controls, values in ((self.frequency, settings.frequency_hz),
                                 (self.amplitude, settings.amplitude_v),
                                 (self.exposure, settings.exposure_ms),
                                 (self.sweep_width, settings.sweep_width_hz),
                                 (self.temperature, settings.temperature_c)):
            for widget, value in zip(controls, (values.start, values.stop, values.steps)):
                widget.setValue(value)
        self.description.setText(settings.description)
        self.sweep_enabled.setChecked(settings.sweep_enabled)
        self.temperature_control.setChecked(settings.temperature_control)
        self.temperature_logging.setChecked(settings.temperature_logging)
        self.temperature_wait_for_stability.setChecked(settings.temperature_wait_for_stability)
        self._apply_flush_unit_index(settings.flush_unit_index)
        self.tec_channel.setCurrentIndex(self.tec_channel.findData(settings.tec_channel))
        self.tiff_format.setCurrentIndex(self.tiff_format.findData(settings.tiff_format))
        self._enabled()
        self._preview()

    def _validate_settings_ranges(self, settings: SimpleSeriesSettings) -> None:
        """Called by MainWindow.load_profile() before _apply_settings():
        simple_series_settings_from_profile() only checks each field's
        *type*; a type-valid value can still be outside what the real
        widget can represent (an integer far beyond a QSpinBox's own
        range, for instance) -- setValue() does not reliably reject or
        clamp that, so without this check it would only surface partway
        through _apply_settings()'s widget-setting loop, after earlier
        fields in that same loop had already been applied. Mirrors
        DevicePanel.validate_profile()'s own min()/max() check, against
        this panel's own live widgets instead of a generic registry."""
        for widget, value, name in (
            (self.repeats, settings.repeats, "repeats"),
            (self.frames, settings.frame_count, "frame_count"),
            (self.fps, settings.camera_fps, "camera_fps"),
            (self.sound_start, settings.sound_start_s, "sound_start_s"),
            (self.sound_run, settings.sound_run_s, "sound_run_s"),
            (self.laser_start, settings.laser_start_s, "laser_start_s"),
            (self.laser_run, settings.laser_run_s, "laser_run_s"),
            (self.camera_start, settings.camera_start_s, "camera_start_s"),
            (self.roi_x, settings.roi[0], "roi[0]"), (self.roi_y, settings.roi[1], "roi[1]"),
            (self.roi_width, settings.roi[2], "roi[2]"), (self.roi_height, settings.roi[3], "roi[3]"),
            (self.volume, settings.flush_volume_ml, "flush_volume_ml"),
            (self.flow, settings.flush_flow_ul_min, "flush_flow_ul_min"),
            (self.wait_after_flush, settings.flush_wait_after_s, "flush_wait_after_s"),
            (self.sweep_period, settings.sweep_period_ms, "sweep_period_ms"),
            (self.temp_wait, settings.temperature_wait_s, "temperature_wait_s"),
            (self.temperature_tolerance, settings.temperature_tolerance_c, "temperature_tolerance_c"),
            (self.temperature_min_settle, settings.temperature_min_settle_s, "temperature_min_settle_s"),
            (self.temperature_max_wait, settings.temperature_max_wait_s, "temperature_max_wait_s"),
        ):
            if not widget.minimum() <= value <= widget.maximum():
                raise ValueError(
                    f"{name} ({value:g}) is outside the allowed range "
                    f"[{widget.minimum():g}, {widget.maximum():g}]")
        for controls, values, name in (
            (self.frequency, settings.frequency_hz, "frequency_hz"),
            (self.amplitude, settings.amplitude_v, "amplitude_v"),
            (self.exposure, settings.exposure_ms, "exposure_ms"),
            (self.sweep_width, settings.sweep_width_hz, "sweep_width_hz"),
            (self.temperature, settings.temperature_c, "temperature_c"),
        ):
            start_widget, stop_widget, steps_widget = controls
            for widget, value, suffix in ((start_widget, values.start, "start"),
                                          (stop_widget, values.stop, "stop"),
                                          (steps_widget, values.steps, "steps")):
                if not widget.minimum() <= value <= widget.maximum():
                    raise ValueError(
                        f"{name}.{suffix} ({value:g}) is outside the allowed range "
                        f"[{widget.minimum():g}, {widget.maximum():g}]")

    def _apply_flush_unit_index(self, flush_unit_index: int | None) -> None:
        # The pump_unit combo only has items while the pump is connected
        # (see _devices() below) -- if the saved unit isn't among them
        # right now (most commonly: nothing connected yet, or connected
        # with a different set of units than when this was saved),
        # selecting it directly would silently do nothing. Remember the
        # saved value instead and restore it once _devices() repopulates
        # the combo with a matching entry; show an explicit notice
        # meanwhile. Critically, force the combo to "nothing selected"
        # (-1) in the no-match case rather than leaving whatever it
        # already showed -- a stale selection from before this load must
        # not be mistaken for the loaded one, and must not silently
        # become the unit an experiment compiles/queues against.
        if flush_unit_index is not None and self.pump_unit.findData(flush_unit_index) >= 0:
            self.pump_unit.setCurrentIndex(self.pump_unit.findData(flush_unit_index))
            self._pending_flush_unit_index = None
        else:
            self._pending_flush_unit_index = flush_unit_index
            self.pump_unit.setCurrentIndex(-1)
        self._update_pump_unit_notice()

    def _pump_unit_selected(self) -> None:
        # Fires on every currentIndexChanged, including _devices()'s own
        # restore -- but that already clears _pending_flush_unit_index
        # itself, and _devices() blocks this signal while repopulating
        # the combo (see below), so the only case this still needs to
        # handle is a genuine user pick of an available (but different
        # from any pending) unit: clear the stale pending value so it
        # doesn't resurface and silently override a deliberate choice
        # later, and update the notice/preview to match.
        if self.pump_unit.currentData() is not None:
            self._pending_flush_unit_index = None
        self._update_pump_unit_notice()
        self._preview()

    def _update_pump_unit_notice(self) -> None:
        if self._pending_flush_unit_index is None:
            self.pump_unit_notice.setText("")
            return
        if self.pump_unit.findData(self._pending_flush_unit_index) >= 0:
            self.pump_unit_notice.setText("")
            return
        self.pump_unit_notice.setText(
            f"Loaded setting: unit {self._pending_flush_unit_index + 1} -- not available "
            "yet (not a current choice). Connect the pump to restore it."
        )
        self.pump_unit_notice.setStyleSheet("color: #b71c1c; font-weight: 600")

    def _definition(self) -> dict:
        return compile_simple_series(self._settings())

    def _update_advanced_summary(self) -> None:
        text = (f"sound {self.sound_start.value():g}+{self.sound_run.value():g} s · "
                f"laser {self.laser_start.value():g}+{self.laser_run.value():g} s · "
                f"camera from {self.camera_start.value():g} s")
        if self.temperature_control.isChecked() and self.temperature_wait_for_stability.isChecked():
            text += (f" · stability ±{self.temperature_tolerance.value():g} °C, "
                     f"settle {self.temperature_min_settle.value():g} s, "
                     f"max {self.temperature_max_wait.value():g} s")
        self.advanced.set_summary(text)

    def _preview(self, *_args) -> None:
        self._update_advanced_summary()
        try:
            definition = self._definition()
            expansion = validate_definition(definition)
            count = len(expansion.experiments)
            self.summary.setText(self._run_preview_text(expansion, count))
            self.config_hint.setText(f"Current form: {count} experiments planned. Details under Review and start.")
            self.config_hint.setStyleSheet("")
            passed = self.manager.camera_preflighted(definition)
            self.camera_preflight_label.setText("Camera preflight: Yes" if passed else "Camera preflight: No")
            self.camera_preflight_label.setStyleSheet(
                f"color: {'#2e7d32' if passed else '#b71c1c'}; font-weight: 600")
        except (ValueError, ZeroDivisionError) as exc:
            self.summary.setText(f"Settings need attention: {exc}")
            self.config_hint.setText(f"Settings need attention: {exc}")
            self.config_hint.setStyleSheet("color: #b71c1c")
            self.camera_preflight_label.setText("Camera preflight: No")

    def _run_preview_text(self, expansion, count: int) -> str:
        """Summarize the compiled experiments and current fixed-form inputs.

        Scanned values/repeat indices come from expansion, not a second range
        expansion. Counts, flush totals, temperature text and output location
        also use this panel's scalar inputs; this is not a generic plan viewer.
        """
        lines = [f"{count} experiments · {count + 1} flushes · "
                 f"{(count + 1) * self.volume.value():g} mL total flush volume · "
                 f"{count * self.frames.value()} saved frames"]
        # repeat_index is 1-based (experiments.py's "repeat" node loop runs
        # range(1, count + 1)), reset for each outer parameter combination
        # -- not a running count across the whole plan.
        repeats = max((experiment.repeat_index for experiment in expansion.experiments), default=0)
        lines.append(f"Repeats per point: {repeats}")
        for key, label in (("frequency_hz", "Frequency (Hz)"), ("amplitude_v", "Amplitude (V)"),
                           ("exposure_ms", "Exposure (ms)"), ("sweep_width_hz", "Sweep width (Hz)"),
                           ("temperature_c", "Temperature (°C)")):
            # compile_simple_series() fills a disabled sweep/temperature
            # axis with the literal string "NaN" (not a float, not an
            # absent key) -- that's the compiled plan's own way of saying
            # "not applicable this run," so it's excluded here rather than
            # shown as a one-value range.
            values = sorted({experiment.parameters[key] for experiment in expansion.experiments
                             if key in experiment.parameters and experiment.parameters[key] != "NaN"})
            if not values:
                continue
            lines.append(f"{label}: {values[0]:g}" if len(values) == 1
                         else f"{label}: {values[0]:g} .. {values[-1]:g} ({len(values)} values)")
        if self.temperature_control.isChecked():
            if self.temperature_wait_for_stability.isChecked():
                lines.append(
                    f"Temperature strategy: wait for stability (±{self.temperature_tolerance.value():g}°C, "
                    f"settled {self.temperature_min_settle.value():g}s, max wait "
                    f"{self.temperature_max_wait.value():g}s), then hold {self.temp_wait.value():g}s")
            else:
                lines.append(f"Temperature strategy: fixed wait of {self.temp_wait.value():g}s, no stability check")
        output_root = self.output_root.text().strip()
        lines.append(f"Output location: {output_root}" if output_root else "Output location: not chosen yet")
        return "\n".join(lines)

    def _enabled(self, *_args) -> None:
        for widget in (*self.sweep_width, self.sweep_period):
            widget.setEnabled(self.sweep_enabled.isChecked())
        control = self.temperature_control.isChecked()
        for widget in (*self.temperature, self.tec_channel, self.temp_wait,
                      self.temperature_wait_for_stability):
            widget.setEnabled(control)
        for widget in (self.temperature_tolerance, self.temperature_min_settle, self.temperature_max_wait):
            widget.setEnabled(control and self.temperature_wait_for_stability.isChecked())

    def _choose_root(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Experiment base folder", self.output_root.text())
        if path:
            self.output_root.setText(path)

    def _import_camera(self) -> None:
        status = self.controller.statuses()[DeviceId.CAMERA]
        if status.connection is not ConnectionState.CONNECTED:
            QMessageBox.warning(self, "Camera import", "Connect the camera first.")
            return
        command = DeviceCommand(DeviceId.CAMERA, DeviceOperation.CAMERA_SETTINGS_READ,
                                NoArguments(), source="ui")
        self._camera_import_request = command.request_id
        self.import_camera.setEnabled(False)
        try:
            self.controller.submit(command)
        except Exception as exc:
            self._camera_import_request = None
            self.import_camera.setEnabled(True)
            QMessageBox.warning(self, "Camera import", str(exc))

    def _camera_import_result(self, result) -> None:
        if result.request_id != self._camera_import_request:
            return
        self._camera_import_request = None
        self.import_camera.setEnabled(True)
        if not result.ok:
            QMessageBox.warning(self, "Camera import", result.error or "Camera settings read failed")
            return
        camera = result.value
        if camera.roi is None or camera.exposure_ms is None:
            QMessageBox.warning(self, "Camera import", "Camera did not report ROI and exposure.")
            return
        self._apply_camera_import(camera)

    def _apply_camera_import(self, camera) -> None:
        for widget, value in ((self.roi_x, camera.roi.horizontal_offset),
                              (self.roi_y, camera.roi.vertical_offset),
                              (self.roi_width, camera.roi.horizontal_size),
                              (self.roi_height, camera.roi.vertical_size)):
            widget.setValue(value)
        self.exposure[0].setValue(camera.exposure_ms)
        self.exposure[1].setValue(camera.exposure_ms)
        self.exposure[2].setValue(1)

    def _fill_level(self) -> float | None:
        readback = self.controller.statuses()[DeviceId.PUMP].readback
        if not isinstance(readback, PumpReadback):
            return None
        unit = next((item for item in readback.units if item.unit_index == self.pump_unit.currentData()), None)
        return unit.fill_level_ml if unit else None

    def _preflight(self) -> None:
        try:
            if not self.description.text().strip():
                raise ValueError("Enter a series descriptor before preflight")
            definition = self._definition()
            self.preflight_button.setEnabled(False)
            self.state_label.setText("Camera preflight running; ultrasound, laser, LED and pump inactive")
            self.preflight.run(definition)
        except Exception as exc:
            self.preflight_button.setEnabled(True)
            QMessageBox.warning(self, "Preflight could not start", str(exc))

    def _preflight_finished(self, ok: bool, message: str, fingerprint: str) -> None:
        self.preflight_button.setEnabled(True)
        if ok:
            self.manager.record_camera_preflight(fingerprint)
        self._preview()
        self.state_label.setText(("Preflight passed: " if ok else "Preflight failed: ") + message)
        if not ok and not message.startswith("Cancelled by Panic"):
            QMessageBox.warning(self, "Preflight failed", message)

    def _panic_changed(self, status: dict) -> None:
        if status["state"] == "stopping":
            self.preflight.abort_for_panic()

    def _queue(self) -> None:
        try:
            definition = self._definition()
            root = Path(self.output_root.text().strip())
            if not self.output_root.text().strip():
                raise ValueError("Choose an experiment base folder")
            folder = self.manager.queue(definition, root)
            self._queued_settings[str(folder)] = self._settings()
            self._editing_folder = None
            self._render_edit_target()
            self.state_label.setText(f"Queued: {folder}")
        except Exception as exc:
            QMessageBox.warning(self, "Could not queue series", str(exc))

    def _start(self) -> None:
        try:
            self.manager.start()
        except Exception as exc:
            QMessageBox.warning(self, "Could not start batch", str(exc))

    def _preflight_syringe(self) -> None:
        try:
            self.syringe_preflight_button.setEnabled(False)
            self.manager.preflight_syringe(self._syringe_finished)
        except Exception as exc:
            self.syringe_preflight_button.setEnabled(True)
            QMessageBox.warning(self, "Syringe preflight could not start", str(exc))

    def _syringe_finished(self, ok: bool, message: str) -> None:
        self.syringe_preflight_button.setEnabled(True)
        self.state_label.setText(message)
        if not ok:
            QMessageBox.warning(self, "Syringe preflight failed", message)

    def _selected_folder(self) -> str:
        item = self.batch_list.currentItem()
        if item is None:
            raise ValueError("Select a queued series first")
        return item.text(5)

    def _load_selected(self) -> None:
        try:
            folder = self._selected_folder()
            settings = self._queued_settings[folder]
            if self.manager.queued_definition(folder) != compile_simple_series(settings):
                raise ValueError("This series was changed outside the simple form; edit it in the JSON builder")
            self._apply_settings(settings)
            self.output_root.setText(str(Path(folder).parent))
            self._editing_folder = folder
            self._render_edit_target()
            self.pages.setCurrentIndex(0)
            self.state_label.setText("Series loaded for editing; edit and press Update loaded series")
        except Exception as exc:
            QMessageBox.warning(self, "Could not load series", str(exc))

    def _update_selected(self) -> None:
        try:
            folder = self._editing_folder
            if folder is None:
                raise ValueError("No queued series is loaded for editing. Select one under Review and "
                                 "start and press Load selected for editing")
            settings = self._settings()
            self.manager.update_queued(folder, compile_simple_series(settings))
            self._queued_settings[folder] = settings
            self._render_edit_target()
            self.state_label.setText("Queued series updated; batch syringe preflight reset")
        except Exception as exc:
            QMessageBox.warning(self, "Could not update series", str(exc))

    def _render_start_readiness(self) -> None:
        """Show the manager's own Start rule: what blocks Start, and what is only a reminder."""
        readiness = self.manager.start_readiness()
        lines = [f'<span style="color:#b71c1c;font-weight:600">Cannot start: {text}</span>'
                 for text in readiness.blocking]
        if readiness.reminders:
            lines.append('<span style="color:#555">Not blocking: ' + "; ".join(readiness.reminders) + "</span>")
        self.start_readiness_label.setText("<br>".join(lines))
        self.start_button.setEnabled(not readiness.blocking and not self._start_locked)

    def _queued_descriptor(self, folder: str, status: dict | None = None) -> str | None:
        for series in (status or self.manager.status()).get("series", []):
            if series["folder"] == folder and series["state"] == "queued":
                return series["description"]
        return None

    def _render_edit_target(self, status: dict | None = None) -> None:
        """Show which queued series Update will change, or that none is loaded."""
        folder = self._editing_folder
        if folder is not None and self._queued_descriptor(folder, status) is None:
            # Removed, started or finished since it was loaded: drop the target, change nothing.
            self._editing_folder = folder = None
            self._edit_target_lost = True
        if folder is None:
            lost = getattr(self, "_edit_target_lost", False)
            text = ("The loaded series is no longer queued; nothing was changed. " if lost else "") +                 "Not editing a queued series: Queue adds a new series."
            self.edit_target_label.setStyleSheet("color: #a65a00; font-weight: 600" if lost else "")
        else:
            text = (f"Editing queued series: {self._queued_descriptor(folder, status)} — Update changes it, "
                    "Queue adds a new series.")
            self.edit_target_label.setStyleSheet("font-weight: 600")
            self._edit_target_lost = False
        self.edit_target_label.setText(text)
        self.update_button.setEnabled(folder is not None and self._edit_buttons_allowed)

    def _remove_selected(self) -> None:
        try:
            folder = self._selected_folder()
            self.manager.remove_queued(folder)
            self._queued_settings.pop(folder, None)
            self._render_edit_target()
            self.state_label.setText("Series removed from batch; its output folder was kept")
        except Exception as exc:
            QMessageBox.warning(self, "Could not remove series", str(exc))

    def _devices(self, statuses: dict) -> None:
        if statuses[DeviceId.CAMERA].connection is not ConnectionState.CONNECTED:
            self.camera_preflight_label.setText("Camera preflight: No")
            self.camera_preflight_label.setStyleSheet("color: #b71c1c; font-weight: 600")
        pump = statuses[DeviceId.PUMP]
        desired_pumps = []
        if pump.connection is ConnectionState.CONNECTED and isinstance(pump.readback, PumpReadback):
            for unit in pump.readback.units:
                desired_pumps.append((f"Unit {unit.unit_index + 1} · {unit.syringe_name or 'syringe'}",
                                      unit.unit_index))
        current_pumps = [(self.pump_unit.itemText(index), self.pump_unit.itemData(index))
                         for index in range(self.pump_unit.count())]
        if desired_pumps != current_pumps:
            current = self.pump_unit.currentData()
            # Signals blocked for the whole clear()/addItem()/select dance:
            # Qt makes the first added item "current" by default as items
            # go in, which would otherwise fire currentIndexChanged (and
            # this panel's own _pump_unit_selected()) with a unit nobody
            # actually chose -- that self-inflicted event was the residual
            # bug Codex's independent simulation caught: it looked like a
            # real selection and silently became the one _settings()
            # reported, even though the "not matched" notice still (and
            # now, correctly) said otherwise.
            self.pump_unit.blockSignals(True)
            try:
                self.pump_unit.clear()
                for label, index in desired_pumps:
                    self.pump_unit.addItem(label, index)
                if current is not None and self.pump_unit.findData(current) >= 0:
                    self.pump_unit.setCurrentIndex(self.pump_unit.findData(current))
                elif self._pending_flush_unit_index is not None and self.pump_unit.findData(
                    self._pending_flush_unit_index) >= 0:
                    # A loaded setting's unit just became available (the
                    # pump connected). Restore it.
                    self.pump_unit.setCurrentIndex(self.pump_unit.findData(self._pending_flush_unit_index))
                    self._pending_flush_unit_index = None
                else:
                    # Neither the previous selection nor any pending saved
                    # value is available right now -- explicitly select
                    # nothing. Never let whichever unit Qt would otherwise
                    # default to stand in as "the experiment's flush unit."
                    self.pump_unit.setCurrentIndex(-1)
            finally:
                self.pump_unit.blockSignals(False)
            self._update_pump_unit_notice()
        tec = statuses[DeviceId.TEC].readback
        if isinstance(tec, TecReadback) and tec.channels:
            desired_tec = [(f"Channel {channel.channel}", channel.channel) for channel in tec.channels]
            current_tec = [(self.tec_channel.itemText(index), self.tec_channel.itemData(index))
                           for index in range(self.tec_channel.count())]
            if desired_tec != current_tec:
                current_channel = self.tec_channel.currentData()
                self.tec_channel.clear()
                for label, channel in desired_tec:
                    self.tec_channel.addItem(label, channel)
                if self.tec_channel.findData(current_channel) >= 0:
                    self.tec_channel.setCurrentIndex(self.tec_channel.findData(current_channel))
        self._render_batch_list(self.manager.status())
        self._render_start_readiness()

    def _render_batch_list(self, status: dict) -> None:
        selected = self.batch_list.currentItem().text(5) if self.batch_list.currentItem() else None
        snapshot = tuple((item["description"], item["state"], item["experiment_count"],
                          item["camera_preflight_passed"], item["syringe_preflight_passed"], item["folder"])
                         for item in status.get("series", []))
        if snapshot == self._batch_snapshot:
            return
        self._batch_snapshot = snapshot
        self.batch_list.clear()
        for series in status.get("series", []):
            camera_badge = ("● Yes" if series["camera_preflight_passed"] else "● No") \
                if series["camera_preflight_applicable"] else "N/A"
            syringe_badge = ("● Yes" if series["syringe_preflight_passed"] else "● No") \
                if series["syringe_preflight_applicable"] else "N/A"
            item = QTreeWidgetItem([series["description"], series["state"],
                                    str(series["experiment_count"]), camera_badge, syringe_badge,
                                    series["folder"]])
            item.setForeground(3, QColor("#2e7d32" if series["camera_preflight_passed"] else "#b71c1c"))
            item.setForeground(4, QColor("#2e7d32" if series["syringe_preflight_passed"] else "#b71c1c"))
            self.batch_list.addTopLevelItem(item)
            if series["folder"] == selected:
                self.batch_list.setCurrentItem(item)

    def _status(self, status: dict) -> None:
        locked = status["state"] in BATCH_ACTIVE_STATES
        editing_locked = locked or status["syringe_preflight_active"] or self.preflight._active
        self._body.setEnabled(not locked)
        self.preflight_button.setEnabled(not locked and not self.preflight._active)
        self.syringe_preflight_button.setEnabled(not locked and not status["syringe_preflight_active"])
        self.queue_button.setEnabled(not editing_locked)
        self._edit_buttons_allowed = not editing_locked
        for button in (self.load_button, self.remove_button):
            button.setEnabled(not editing_locked and status["queued_series"] > 0)
        self._render_edit_target(status)
        self._start_locked = locked
        self._render_start_readiness()
        self._render_batch_list(status)
        self.state_label.setText(f"Batch: {status['state']} · queued: {status['queued_series']} · "
                                 f"completed experiments: {status['completed_experiments']}")
