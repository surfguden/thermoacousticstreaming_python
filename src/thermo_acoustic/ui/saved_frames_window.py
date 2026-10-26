"""Review of frames already saved by an experiment series. Not the live camera."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QSlider, QSpinBox,
)
from PySide6.QtCore import Qt

from ..application.saved_frames import (
    SavedExperiment, SavedExperimentInfo, SavedFramesError, find_experiments,
)
from .status_dashboard import describe_condition
from .widgets import CameraImageWindow


class SavedFramesWindow(CameraImageWindow):
    """Same display and measurement controls as the live viewer, fed from disk.

    Frames are read one at a time on demand (a few are cached); the saved files and run
    records are never modified. The banner and state line say this is saved data so an old
    frame cannot be taken for the current camera image.
    """

    _BLUE = "#1f4e8c"

    def __init__(self, parent=None) -> None:
        self._experiments: list[SavedExperimentInfo] = []
        self._experiment: SavedExperiment | None = None
        self._position = 0
        self._load_error: str | None = None
        super().__init__(parent)
        self.setWindowTitle("Saved frames review — saved data, not live")
        banner = QLabel("SAVED DATA FROM DISK — not the live camera image")
        banner.setStyleSheet(f"background: {self._BLUE}; color: white; font-weight: 700; padding: 3px 6px;")
        self.banner = banner
        self.extra_top.addWidget(banner)
        source_row = QHBoxLayout()
        self.open_button = QPushButton("Open series or experiment folder…")
        self.experiment_combo = QComboBox()
        self.experiment_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.experiment_combo.setMinimumContentsLength(24)
        source_row.addWidget(self.open_button)
        source_row.addWidget(self.experiment_combo, 1)
        self.extra_top.addLayout(source_row)
        frame_row = QHBoxLayout()
        self.previous_button = QPushButton("◀")
        self.next_button = QPushButton("▶")
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.frame_spin = QSpinBox()
        self.frame_spin.setKeyboardTracking(False)
        self.count_label = QLabel("of —")
        for widget in (self.previous_button, self.slider, self.next_button, QLabel("Frame"),
                       self.frame_spin, self.count_label):
            frame_row.addWidget(widget, 1 if widget is self.slider else 0)
        self.extra_top.addLayout(frame_row)
        self.open_button.clicked.connect(self.choose_folder)
        self.experiment_combo.currentIndexChanged.connect(self._experiment_selected)
        self.previous_button.clicked.connect(lambda: self.show_position(self._position - 1))
        self.next_button.clicked.connect(lambda: self.show_position(self._position + 1))
        self.slider.valueChanged.connect(lambda value: self.show_position(value - 1))
        self.frame_spin.valueChanged.connect(lambda value: self.show_position(value - 1))
        self._set_controls_enabled(False)
        self.status.setText("Open a series or experiment folder written by an experiment batch.")
        self._render_state()

    # ---------------------------------------------------------------- source
    def choose_folder(self, start: str = "") -> None:
        path = QFileDialog.getExistingDirectory(self, "Series or experiment folder", start or "")
        if path:
            self.open_or_report(path)

    def open_or_report(self, path: str | Path) -> None:
        try:
            self.open_folder(path)
        except SavedFramesError as exc:
            QMessageBox.warning(self, "Cannot review this folder", str(exc))

    def open_folder(self, path: str | Path) -> None:
        experiments = find_experiments(path)
        if not experiments:
            raise SavedFramesError("This series has no saved experiments yet")
        self._experiments = experiments
        self.experiment_combo.blockSignals(True)
        self.experiment_combo.clear()
        for info in experiments:
            self.experiment_combo.addItem(f"{info.relative_path} · {describe_condition(info.parameters)}")
        self.experiment_combo.blockSignals(False)
        self._select(0)

    def _experiment_selected(self, index: int) -> None:
        if index >= 0:
            self._select(index)

    def _select(self, index: int) -> None:
        info = self._experiments[index]
        try:
            experiment = SavedExperiment(info.folder)
            first = experiment.load_frame(0)
        except SavedFramesError as exc:
            # Nothing of the previously shown experiment may stay on screen as if it were this one.
            self._experiment = None
            self._load_error = None
            self._clear_view()
            self.status.setText(f"Cannot show {info.relative_path}: {exc}")
            self._render_state()
            return
        self._experiment = experiment
        self.experiment_combo.blockSignals(True)
        self.experiment_combo.setCurrentIndex(index)
        self.experiment_combo.blockSignals(False)
        for widget, upper in ((self.slider, experiment.frame_count), (self.frame_spin, experiment.frame_count)):
            widget.blockSignals(True)
            widget.setRange(1, upper)
            widget.blockSignals(False)
        self.count_label.setText(f"of {experiment.frame_count}")
        self._set_controls_enabled(True)
        self._display(0, first)

    # ---------------------------------------------------------------- frames
    def show_position(self, position: int) -> None:
        experiment = self._experiment
        if experiment is None or not 0 <= position < experiment.frame_count:
            return
        try:
            frame = experiment.load_frame(position)
        except SavedFramesError as exc:
            # The last valid image stays, labelled as such; the controls go back to its frame.
            self._load_error = f"frame {position + 1} could not be read"
            self._sync_controls(self._position)
            self.status.setText(f"{exc} — still showing frame {self._position + 1}")
            self._render_state()
            return
        self._display(position, frame)

    def _clear_view(self) -> None:
        self._set_controls_enabled(False)
        self.count_label.setText("of —")
        self._frame_description = "—"
        self.histogram.set_frame(None)
        self.preview.set_frame(None)  # also drops the analysis ROI
        self.preview.setText("No saved frame")
        self.adjust_intensity_button.setEnabled(False)
        self.robust_button.setEnabled(False)
        self._apply_limits(None, update_preview=False)
        self.measurement.refresh()

    def _sync_controls(self, position: int) -> None:
        for widget in (self.slider, self.frame_spin):
            widget.blockSignals(True)
            widget.setValue(position + 1)
            widget.blockSignals(False)

    def _display(self, position: int, frame) -> None:
        experiment = self._experiment
        record = experiment.frames[position]
        self._position = position
        self._load_error = None
        self._sync_controls(position)
        self.previous_button.setEnabled(position > 0)
        self.next_button.setEnabled(position < experiment.frame_count - 1)
        self.show_frame(frame, (
            f"{record.path} · page {record.page_index} · SDK timestamp {record.camera_sdk_timestamp} · "
            f"host received {record.host_received_utc}"))

    def _set_controls_enabled(self, enabled: bool) -> None:
        for widget in (self.slider, self.frame_spin, self.previous_button, self.next_button):
            widget.setEnabled(enabled)

    # ---------------------------------------------------------------- state
    def _render_state(self) -> None:
        experiment = self._experiment
        if experiment is None:
            self.preview_state.setText("No saved frames loaded")
            self.frame_info.setText("Image: —")
        else:
            self.preview_state.setText(
                f"Saved frame {self._position + 1} of {experiment.frame_count} — historical, not live"
                + (f" · {self._load_error}" if self._load_error else ""))
            self.frame_info.setText(
                f"Image: {self._frame_description} · experiment {experiment.experiment_id} · "
                f"{describe_condition(experiment.parameters)}")
        self.preview_state.setStyleSheet(f"color: {self._BLUE}; font-weight: 600;")
