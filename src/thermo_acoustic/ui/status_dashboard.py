"""Passive summary of controller readbacks and experiment progress."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton, QScrollArea, QTabWidget, QVBoxLayout,
    QWidget,
)

from ..application.run_activity import describe_phase, devices_for_phase
from ..application.saved_frames import SavedFramesError
from ..domain.models import ConnectionState, DeviceId
from .status_text import (  # describe_condition is re-exported for existing importers
    ad2_outputs_summary, connection_phrase, describe_condition, format_frequency, is_connected, sweep_summary,
    valve_summary,
)
from .saved_frames_window import SavedFramesWindow
from .status_icons import STATE_MARKS, action_icon, state_pixmap
from .temperature_plot import TemperaturePlot


def _value(value: object, unit: str = "") -> str:
    return "unknown" if value is None else f"{value:g}{unit}" if isinstance(value, (int, float)) else str(value)


def _state_kind(status) -> str:
    """The mark for what a device reports: failed, not connected, active, busy or just connected.
    Connected says nothing about being ready for the experiment."""
    if not is_connected(status):
        return "disconnected"
    if status.fault or status.connection is ConnectionState.ERROR:
        return "failed"
    return "active" if status.active else "busy" if status.busy else "connected"


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
        self.stage = QLabel("—")
        self.stage.setWordWrap(True)
        self.series = QLabel("—")
        self.series.setWordWrap(True)
        self.output = QLabel("—")
        self.output.setWordWrap(True)
        self.output.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        run_grid.addWidget(self.experiment, 0, 0, 1, 2)
        # Shown only when a run ended abnormally or was stopped; says which, in words.
        self.alert = QLabel()
        self.alert.setWordWrap(True)
        self.alert.setVisible(False)
        run_grid.addWidget(self.alert, 6, 0, 1, 2)
        for row, (caption, label) in enumerate((("Condition", self.condition), ("Stage", self.stage),
                                                ("Series", self.series), ("Output folder", self.output)), 1):
            run_grid.addWidget(QLabel(caption), row, 0)
            run_grid.addWidget(label, row, 1)
        run_grid.setColumnStretch(1, 1)
        buttons = QHBoxLayout()
        self.open_output_button = QPushButton(action_icon("folder"), "Open output folder")
        self.review_button = QPushButton("Review saved frames")
        self.image_window_button = QPushButton("Pop out image")
        self.image_window_button.setToolTip("Show the image in its own window; the same viewer, moved")
        self.open_output_button.setEnabled(False)
        self.open_output_button.clicked.connect(self.open_output_folder)
        self.image_window_button.clicked.connect(self.image_window_requested)
        self.review_button.clicked.connect(lambda: self.review_requested.emit(self._folder or ""))
        for button in (self.open_output_button, self.review_button, self.image_window_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        run_grid.addLayout(buttons, 5, 0, 1, 2)
        root.addWidget(run)
        self._folder: str | None = None

        middle = QHBoxLayout()
        # The live image viewer is the camera page's own viewer, moved here while this workspace is shown.
        self.image_tabs = QTabWidget()
        live_page = QWidget()
        self.image_layout = QVBoxLayout(live_page)
        self.image_layout.setContentsMargins(0, 0, 0, 0)
        self.image_tabs.addTab(live_page, "Live image or last frame (not saved data)")
        saved_page = QWidget()
        saved_layout = QVBoxLayout(saved_page)
        saved_layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        self.saved_label = QLabel("No acquisition has been saved in this batch yet.")
        self.saved_label.setWordWrap(True)
        self.follow_check = QCheckBox("Follow newest")
        self.follow_check.setChecked(True)
        self.follow_check.setToolTip("Show each newly saved acquisition here, unless you have moved to another frame "
                                     "or folder (then your view is left alone). Display only.")
        self.show_newest_button = QPushButton("Show newest")
        self.show_newest_button.setEnabled(False)
        self.show_newest_button.clicked.connect(lambda: self._show_saved(force=True))
        header.addWidget(self.saved_label, 1)
        header.addWidget(self.follow_check)
        header.addWidget(self.show_newest_button)
        saved_layout.addLayout(header)
        # What the viewer shows, kept apart from the newest-saved line above: it may be an older result.
        self.viewing_label = QLabel()
        self.viewing_label.setWordWrap(True)
        saved_layout.addWidget(self.viewing_label)
        self.saved_viewer = SavedFramesWindow()
        self.saved_viewer.setWindowFlags(Qt.WindowType.Widget)
        self.saved_viewer.set_measurement_visible(False)
        saved_layout.addWidget(self.saved_viewer, 1)
        self.saved_viewer.show()
        self.image_tabs.addTab(saved_page, "Newest saved acquisition")
        self.saved_viewer.source_changed.connect(self._render_viewing)
        self.follow_check.toggled.connect(lambda *_: self._render_viewing())
        middle.addWidget(self.image_tabs, 3)
        self._last_saved: dict | None = None
        self._followed_folder: str | None = None
        self._status: dict = {}
        self._statuses: dict = {}
        side = QVBoxLayout()
        middle.addLayout(side, 2)
        root.addLayout(middle, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        grid = QGridLayout(body)
        self.rows = {}
        self.names = {}
        self.marks = {}  # what the device itself reports (connected / busy / active / failed)
        self.involved_tags = {}  # what the current stage works with: not a device report
        for index, device in enumerate(DeviceId):
            mark = QLabel()
            mark.setFixedWidth(20)
            self.marks[device] = mark
            grid.addWidget(mark, index, 0)
            name = QLabel(device.value)
            self.names[device] = name
            grid.addWidget(name, index, 1)
            tag = QLabel()
            tag.setVisible(False)
            self.involved_tags[device] = tag
            grid.addWidget(tag, index, 2)
            label = QLabel("not connected")
            label.setWordWrap(True)
            grid.addWidget(label, index, 3)
            self.rows[device] = label
        grid.setColumnStretch(3, 1)
        grid.setRowStretch(len(DeviceId), 1)
        scroll.setWidget(body)
        side.addWidget(scroll, 1)
        side.addWidget(QLabel("TEC temperatures · latest rolling samples"))
        self.temperature_plot = TemperaturePlot()
        side.addWidget(self.temperature_plot, 2)  # the trend gets more height than the short device list

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
        self._status = status
        state = status.get("state")
        phase = status.get("phase", "")
        self.stage.setText((describe_phase(phase) or "—") if state == "running" else "— (no stage is running)")
        self._render_saved(status.get("last_saved"), state)
        text, color = {"failed": (phase, "#b71c1c"), "aborted": (phase, "#a65a00"),
                       "stopped": ("Stopped after the current experiment; the remaining ones were not run.",
                                   "#a65a00")}.get(state, ("", ""))
        self.alert.setVisible(bool(text))
        self.alert.setText(text)
        self.alert.setStyleSheet(f"color: {color}; font-weight: 600")
        number = status.get("current_experiment_number")
        repeat = status.get("current_repeat")
        if status.get("current_parameters"):
            prefix = f"Experiment {number}/{count}" if number else "Experiment"
            suffix = f" · repeat {repeat}" if repeat else ""
            self.condition.setText(f"{prefix}{suffix} · "
                                   f"{describe_condition(status['current_parameters'], status.get('current_plan'))}")
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
        self._render_devices()

    def add_temperature_sample(self, sample: dict) -> None:
        self.temperature_plot.add_sample(sample)

    def update_statuses(self, statuses: dict) -> None:
        self._statuses = dict(statuses)
        self._render_devices()

    def _requested_text(self, device: DeviceId) -> str:
        """What the running experiment asks of the device (from the runner's own plan), kept apart from what the
        device reports."""
        parameters = self._status.get("current_parameters") or {}
        plan = self._status.get("current_plan") or {}
        def known(key):
            value = parameters.get(key)
            return None if value in (None, "NaN") else value
        pieces = []
        if device is DeviceId.AD2:
            if known("frequency_hz") is not None:
                pieces.append(f"center frequency {format_frequency(known('frequency_hz'))}")
            sweep = sweep_summary(parameters, plan, say_requested=False)
            if sweep:
                pieces.append(sweep)
            if known("amplitude_v") is not None:
                pieces.append(f"amplitude {known('amplitude_v'):g} V")
            if plan.get("sound_enabled") is False:
                pieces.append("ultrasound disabled")
            elif plan.get("sound_run_s") is not None:
                pieces.append(f"ultrasound {plan['sound_start_s']:g}+{plan['sound_run_s']:g} s")
        elif device is DeviceId.CAMERA:
            if known("exposure_ms") is not None:
                pieces.append(f"exposure {known('exposure_ms'):g} ms")
            if plan.get("frames") is not None:
                pieces.append(f"{plan['frames']} frames")
        elif device is DeviceId.TEC and known("temperature_c") is not None:
            pieces.append(f"target {known('temperature_c'):g} °C")
        return "requested: " + ", ".join(pieces) if pieces else ""

    def _render_devices(self) -> None:
        involved = devices_for_phase(self._status.get("phase")) if self._status.get("state") == "running" else frozenset()
        for device, status in self._statuses.items():
            data = status.readback
            pieces = [connection_phrase(status)]
            if status.fault:
                pieces.append(f"reason: {status.fault}")
            if device is DeviceId.PUMP and data is not None:
                for unit in getattr(data, "units", ()):
                    pieces.append(
                        f"Unit {unit.unit_index + 1}: {_value(unit.fill_level_ml, ' mL')} · "
                        f"flow {_value(unit.current_flow_ul_min, ' µL/min')} · "
                        f"{'pumping' if unit.is_pumping else 'idle' if unit.is_pumping is False else 'unknown'}")
            elif device is DeviceId.VALVE and data is not None:
                pieces.append(valve_summary(data))
            elif device is DeviceId.Z_STAGE and data is not None:
                pieces.append(z_stage_summary(data))
            elif device is DeviceId.CAMERA and data is not None:
                pieces.append(camera_summary(data))
            elif device is DeviceId.AD2 and data is not None:
                pieces.append(ad2_outputs_summary(data))
            elif device is DeviceId.TEC and data is not None:
                for channel in getattr(data, "channels", ()):
                    pieces.append(f"CH{channel.channel}: {_value(channel.current_temperature_c, ' °C')} "
                                  f"→ {_value(channel.target_temperature_c, ' °C')}")
            kind = _state_kind(status)
            if kind in {"active", "busy"}:
                pieces.insert(1, "active (reported by the device)" if kind == "active" else "busy (command running)")
            request = self._requested_text(device) if self._status.get("state") == "running" else ""
            if request:
                pieces.append(request)
            self.rows[device].setText(" · ".join(pieces))
            self.rows[device].setStyleSheet("color: #b71c1c; font-weight: 600" if status.fault else "")
            colour, word = STATE_MARKS[kind]
            self.marks[device].setPixmap(state_pixmap(kind))
            self.marks[device].setToolTip(word)
            self.names[device].setStyleSheet("font-weight: 700" if device in involved else "")
            # "used in this stage" is the run plan's statement, not something the device reported.
            tag = self.involved_tags[device]
            tag.setVisible(device in involved)
            tag.setText("[ this stage ]")
            tag.setStyleSheet("color: #1f4e8c")
            tag.setToolTip("The current run stage works with this device. This is the plan, not a device report; "
                           "the mark on the left is what the device reports.")

    # ------------------------------------------------------------- newest saved
    def _render_saved(self, saved: dict | None, batch_state: str | None = None) -> None:
        """Name what is on disk and how far that experiment got. Images saved is not experiment completed,
        and a stop by the operator is not a fault."""
        self._last_saved = saved
        self.show_newest_button.setEnabled(saved is not None)
        if saved is None:
            ended = batch_state in {"aborted", "failed", "stopped"}
            self.saved_label.setText(
                f"No acquisition was saved in this batch before it ended ({batch_state})." if ended
                else "No acquisition has been saved in this batch yet.")
            self._render_viewing()
            return
        outcome = {"saved": "images saved; the experiment has not finished (flush and closing may still run)",
                   "completed": "the experiment completed",
                   "failed_after_save": "images saved, but the experiment later failed: " + (saved.get("reason") or ""),
                   "aborted_after_save": "images saved, then the batch was stopped before the experiment finished"
                                         + (f" ({saved['reason']})" if saved.get("reason") else "")
                   }.get(saved["outcome"], saved["outcome"])
        self.saved_label.setText(
            f"Newest saved: {saved['experiment_id']} · repeat {saved['repeat_index']} · "
            f"{describe_condition(saved['parameters'])} · {saved['frame_count']} frames — {outcome}")
        self._show_saved(force=False)
        self._render_viewing()

    def _render_viewing(self) -> None:
        """Provenance of what the viewer shows now: the newest result, or something else, said plainly."""
        viewer, saved = self.saved_viewer, self._last_saved
        loaded = viewer.loaded_folder()
        if loaded is None:
            self.viewing_label.setText("Viewing: nothing loaded.")
            return
        what = f"{viewer.loaded_experiment_id()} ({loaded})"
        if saved is not None and loaded == saved["experiment_folder"]:
            note = "the newest saved acquisition of this batch"
        elif saved is not None and Path(loaded).is_relative_to(saved["series_folder"]):
            note = "an earlier acquisition of this series, not the newest saved"
        elif saved is not None:
            note = "a result outside this batch's newest series, not from this batch's newest save"
        else:
            note = "an earlier result, not from this batch (nothing has been saved in this batch yet)"
        mode = "following newest" if self.follow_check.isChecked() else "following is off"
        self.viewing_label.setText(f"Viewing: {what} — {note} · {mode}")

    def _show_saved(self, *, force: bool) -> None:
        """Load the newest saved experiment into the viewer. Automatic only when following and the viewer is
        still where the last automatic load left it (frame 1 of that folder); never over a user's own view."""
        saved = self._last_saved
        if saved is None:
            return
        folder = saved["experiment_folder"]
        viewer = self.saved_viewer
        if viewer.loaded_folder() == folder:
            return
        untouched = viewer.loaded_folder() in (None, self._followed_folder) and viewer.position() == 0
        if not force and not (self.follow_check.isChecked() and untouched):
            self.saved_label.setText(self.saved_label.text() + "  — your view was left as it is; press Show newest to switch.")
            return
        try:
            viewer.open_folder(folder)
        except SavedFramesError as exc:
            self.saved_label.setText(self.saved_label.text() + f"  — cannot be shown yet: {exc}")
            return
        self._followed_folder = folder
        self._render_viewing()
