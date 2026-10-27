"""Controls for the application-owned Z-stack runner."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDoubleSpinBox, QFileDialog, QFormLayout,
                               QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QSpinBox, QVBoxLayout, QWidget)

from ..application.commands import DeviceCommand, DeviceOperation, NoArguments
from ..application.z_stack import ZStackSettings
from ..domain.models import DeviceId, ZStageReadback


def numeric(value, minimum, maximum):
    widget = QDoubleSpinBox()
    widget.setDecimals(4)
    widget.setRange(minimum, maximum)
    widget.setValue(value)
    return widget


class ZStackPanel(QWidget):
    def __init__(self, runner, camera_panel, parent=None) -> None:
        super().__init__(parent)
        self.runner = runner
        self.camera_panel = camera_panel
        self._import_request = None
        layout = QVBoxLayout(self)
        needs = QLabel("Needs the camera and Z-stage connected, the Z-stage closed loop enabled (Device details, "
                       "Z-stage) and an empty output folder. Images appear in the live image viewer.")
        needs.setWordWrap(True)
        layout.addWidget(needs)
        columns = QHBoxLayout()
        layout.addLayout(columns, 1)
        left, right = QVBoxLayout(), QVBoxLayout()
        columns.addLayout(left, 1)
        columns.addLayout(right, 1)

        scan = QGroupBox("Scan range")
        scan_form = QFormLayout(scan)
        self.start_z = numeric(0, 0, 1_000_000)
        self.stop_z = numeric(100, 0, 1_000_000)
        self.points = QSpinBox()
        self.points.setRange(2, 100_000)
        self.points.setValue(11)
        self.tolerance = numeric(1, 0.001, 1_000)
        self.timeout = numeric(10, 0.1, 1_000)
        for label, widget in (("Z start (µm)", self.start_z), ("Z stop (µm)", self.stop_z),
                              ("Points", self.points), ("Position tolerance (µm)", self.tolerance),
                              ("Position timeout (s)", self.timeout)):
            scan_form.addRow(label, widget)
        left.addWidget(scan)

        camera = QGroupBox("Camera for the scan")
        camera_form = QFormLayout(camera)
        self.exposure = numeric(2.5, 0.001, 1_000_000)
        self.roi = [QSpinBox() for _ in range(4)]
        for index, widget in enumerate(self.roi):
            widget.setRange(0 if index < 2 else 1, 100_000)
            widget.setValue(0 if index < 2 else 512)
        camera_form.addRow("Exposure (ms)", self.exposure)
        roi_grid = QWidget()
        roi_layout = QGridLayout(roi_grid)
        roi_layout.setContentsMargins(0, 0, 0, 0)
        for index, (name, widget) in enumerate(zip(("X", "Y", "Width", "Height"), self.roi)):
            roi_layout.addWidget(QLabel(f"{name} (px)"), index // 2, (index % 2) * 2)
            roi_layout.addWidget(widget, index // 2, (index % 2) * 2 + 1)
        camera_form.addRow("ROI", roi_grid)
        self.import_button = QPushButton("Import exposure and ROI from camera")
        self.import_button.setToolTip("Copies the camera's current exposure and ROI into this scan (camera to form)")
        self.import_button.clicked.connect(self._import_camera)
        camera_form.addRow(self.import_button)
        left.addWidget(camera)
        left.addStretch(1)

        positioning = QGroupBox("Positioning and live view")
        positioning_layout = QVBoxLayout(positioning)
        self.step = numeric(1, 0.001, 1_000_000)
        step_row = QFormLayout()
        step_row.addRow("Jog step for Up / Down (µm)", self.step)
        positioning_layout.addLayout(step_row)
        motion = QHBoxLayout()
        for label, action in (("Up", lambda: self.runner.move_relative(self.step.value())),
                              ("Down", lambda: self.runner.move_relative(-self.step.value())),
                              ("To top", lambda: self.runner.move_to(max(self.start_z.value(), self.stop_z.value()))),
                              ("To bottom", lambda: self.runner.move_to(min(self.start_z.value(), self.stop_z.value()))),
                              ("To center", lambda: self.runner.move_to((self.start_z.value() + self.stop_z.value()) / 2))):
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, fn=action: self._try(fn))
            motion.addWidget(button)
        positioning_layout.addLayout(motion)
        preview = QHBoxLayout()
        for label, action in (("Start live view", lambda: self.runner.start_preview(self.exposure.value())),
                              ("Stop live view", self.runner.stop_preview)):
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, fn=action: self._try(fn))
            preview.addWidget(button)
        positioning_layout.addLayout(preview)
        self.position_label = QLabel("Measured Z: not read yet")
        positioning_layout.addWidget(self.position_label)
        right.addWidget(positioning)

        run = QGroupBox("Z stack run")
        run_layout = QVBoxLayout(run)
        self.folder = QLineEdit()
        self.folder.setPlaceholderText("Empty output folder")
        browse = QPushButton("Choose empty folder…")
        browse.clicked.connect(self._browse)
        folder_row = QHBoxLayout()
        folder_row.addWidget(self.folder, 1)
        folder_row.addWidget(browse)
        run_layout.addLayout(folder_row)
        actions = QHBoxLayout()
        start = QPushButton("Start Z stack")
        start.setStyleSheet("font-weight: 600")
        stop = QPushButton("Stop Z stack")
        start.clicked.connect(self._start)
        stop.clicked.connect(self.runner.stop)
        actions.addWidget(start)
        actions.addWidget(stop)
        run_layout.addLayout(actions)
        self.progress = QLabel("Idle")
        self.progress.setWordWrap(True)
        run_layout.addWidget(self.progress)
        results = QHBoxLayout()
        self.open_folder_button = QPushButton("Open output folder")
        self.open_folder_button.clicked.connect(self._open_folder)
        self.show_image_button = QPushButton("Show image")
        self.show_image_button.setToolTip("Shows the live image viewer; it does not start a capture")
        self.show_image_button.clicked.connect(self.camera_panel.show_image_window)
        results.addWidget(self.open_folder_button)
        results.addWidget(self.show_image_button)
        run_layout.addLayout(results)
        right.addWidget(run)
        right.addStretch(1)
        self.runner.changed.connect(self._status)
        self.runner.controller.status_changed.connect(self._device_status)
        self.runner.controller.command_result.connect(self._import_result)

    def _try(self, action) -> None:
        try:
            action()
            self.camera_panel._show_image_window("Z stack live view")
        except Exception as exc:
            QMessageBox.warning(self, "Z stack", str(exc))

    def _open_folder(self) -> None:
        folder = self.folder.text().strip()
        if folder and Path(folder).is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        else:
            QMessageBox.information(self, "Z stack", "The output folder does not exist yet.")

    def _browse(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Choose empty Z stack folder")
        if selected:
            self.folder.setText(selected)

    def _settings(self) -> ZStackSettings:
        if not self.folder.text().strip():
            raise ValueError("Choose an empty output folder")
        return ZStackSettings(self.start_z.value(), self.stop_z.value(), self.points.value(),
                              self.exposure.value(), tuple(widget.value() for widget in self.roi),
                              Path(self.folder.text().strip()), self.tolerance.value(),
                              self.timeout.value())

    def _start(self) -> None:
        self._try(lambda: self.runner.start(self._settings()))

    def _import_camera(self) -> None:
        command = DeviceCommand(DeviceId.CAMERA, DeviceOperation.CAMERA_SETTINGS_READ,
                                NoArguments(), source="ui")
        self._import_request = command.request_id
        try:
            self.runner.controller.submit(command)
        except Exception as exc:
            self._import_request = None
            QMessageBox.warning(self, "Camera settings import", str(exc))

    def _import_result(self, result) -> None:
        if result.request_id != self._import_request:
            return
        self._import_request = None
        if not result.ok:
            QMessageBox.warning(self, "Camera settings import", result.error or "Read failed")
            return
        readback = result.value
        if readback.roi is None or readback.exposure_ms is None:
            QMessageBox.warning(self, "Camera settings import", "Camera ROI or exposure is unavailable")
            return
        self.exposure.setValue(readback.exposure_ms)
        for widget, value in zip(self.roi, (readback.roi.horizontal_offset,
                                             readback.roi.vertical_offset,
                                             readback.roi.horizontal_size,
                                             readback.roi.vertical_size)):
            widget.setValue(value)

    def _device_status(self, statuses) -> None:
        stage = statuses[DeviceId.Z_STAGE].readback
        if isinstance(stage, ZStageReadback) and stage.position_um is not None:
            self.position_label.setText(f"Measured Z: {stage.position_um:.3f} µm (last read)")

    def _status(self, status) -> None:
        self.progress.setText(status["detail"])
