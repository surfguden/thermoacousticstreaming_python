"""Fixed-form series controls; all expansion and execution live in application code."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGridLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from ..application.experiments import validate_definition
from ..application.commands import DeviceCommand, DeviceOperation, NoArguments
from ..application.simple_preflight import SimpleSeriesPreflight
from ..application.simple_series import NumericRange, SimpleSeriesSettings, compile_simple_series
from ..domain.models import ConnectionState, DeviceId, PumpReadback, TecReadback


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
        self._passed: tuple[str, float | None] | None = None
        self._camera_import_request: str | None = None
        root = QVBoxLayout(self)
        root.addWidget(QLabel("Simple series · temperature → frequency → sweep width → amplitude → exposure → repeats"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        grid = QGridLayout(body)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        output = QGroupBox("Output and acquisition")
        form = QFormLayout(output)
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
        grid.addWidget(output, 0, 0)

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
        grid.addWidget(timing, 0, 1)

        frequency = QGroupBox("Ultrasound")
        form = QFormLayout(frequency)
        self.frequency = self._range(form, "Center frequency (Hz)", 1_000_000, 1_000_000)
        self.amplitude = self._range(form, "AD2 source peak amplitude (V)", 1, 1, maximum=5)
        self.sweep_enabled = QCheckBox("Frequency sweep · frequency values become center frequencies")
        form.addRow(self.sweep_enabled)
        self.sweep_width = self._range(form, "Full sweep width (Hz)", 100_000, 100_000)
        self.sweep_period = number(1, 0.001, 1_000_000)
        form.addRow("Sweep period (ms), triangle", self.sweep_period)
        grid.addWidget(frequency, 1, 0)

        temperature = QGroupBox("Temperature")
        form = QFormLayout(temperature)
        self.temperature_control = QCheckBox("Control temperature")
        self.temperature_logging = QCheckBox("Log both TEC channels throughout series (1 s)")
        self.tec_channel = QComboBox()
        self.tec_channel.addItem("Channel 1", 1)
        self.tec_channel.addItem("Channel 2", 2)
        self.temperature = self._range(form, "Temperature (°C)", 25, 25, minimum=0, maximum=80)
        self.temp_wait = number(30, 0, 86_400)
        form.insertRow(0, self.temperature_control)
        form.addRow("Controlled channel", self.tec_channel)
        form.addRow("Wait after setpoint change (s)", self.temp_wait)
        form.addRow(self.temperature_logging)
        grid.addWidget(temperature, 1, 1)

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
        grid.addWidget(camera, 2, 0)

        fluidics = QGroupBox("Flush")
        form = QFormLayout(fluidics)
        self.pump_unit = QComboBox()
        self.volume = number(0.1, 0.000001, 1000)
        self.flow = number(500, 0.000001, 1_000_000)
        form.addRow("Pump unit", self.pump_unit)
        form.addRow("Volume (mL)", self.volume)
        form.addRow("Flow (µL/min)", self.flow)
        form.addRow(QLabel("One initial flush and one after every acquisition."))
        grid.addWidget(fluidics, 2, 1)

        controls = QHBoxLayout()
        self.preflight_button = QPushButton("Preflight camera and syringe")
        self.queue_button = QPushButton("Queue series")
        self.start_button = QPushButton("Start queued batch")
        self.stop_button = QPushButton("Stop after current")
        self.abort_button = QPushButton("Abort batch")
        for button in (self.preflight_button, self.queue_button, self.start_button,
                       self.stop_button, self.abort_button):
            controls.addWidget(button)
        root.addLayout(controls)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)
        self.state_label = QLabel()
        root.addWidget(self.state_label)

        self.choose_root.clicked.connect(self._choose_root)
        self.import_camera.clicked.connect(self._import_camera)
        self.preflight_button.clicked.connect(self._preflight)
        self.queue_button.clicked.connect(self._queue)
        self.start_button.clicked.connect(self._start)
        self.stop_button.clicked.connect(self.manager.stop_after_current)
        self.abort_button.clicked.connect(self.manager.abort)
        self.preflight.finished.connect(self._preflight_finished)
        self.manager.changed.connect(self._status)
        self.controller.status_changed.connect(self._devices)
        self.controller.command_result.connect(self._camera_import_result)
        self.sweep_enabled.toggled.connect(self._enabled)
        self.temperature_control.toggled.connect(self._enabled)
        for widget in self.findChildren(QSpinBox) + self.findChildren(QDoubleSpinBox):
            widget.valueChanged.connect(self._preview)
        for widget in (self.sweep_enabled, self.temperature_control, self.temperature_logging):
            widget.toggled.connect(self._preview)
        self._enabled()
        self._devices(controller.statuses())
        self._preview()
        self._status(self.manager.status())

    @staticmethod
    def _range(form: QFormLayout, label: str, start: float, stop: float,
               *, minimum: float = 0, maximum: float = 100_000_000) -> tuple:
        box = QWidget()
        row = QHBoxLayout(box)
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
        row.addWidget(QLabel("Start"))
        row.addWidget(start_widget)
        row.addWidget(QLabel("Stop"))
        row.addWidget(stop_widget)
        row.addWidget(steps_label)
        row.addWidget(steps)
        form.addRow(label, box)
        return start_widget, stop_widget, steps

    @staticmethod
    def _values(controls: tuple) -> NumericRange:
        return NumericRange(controls[0].value(), controls[1].value(), controls[2].value())

    def _settings(self) -> SimpleSeriesSettings:
        if self.pump_unit.currentData() is None:
            raise ValueError("Select a configured pump unit")
        return SimpleSeriesSettings(
            repeats=self.repeats.value(), frame_count=self.frames.value(), camera_fps=self.fps.value(),
            sound_start_s=self.sound_start.value(), sound_run_s=self.sound_run.value(),
            laser_start_s=self.laser_start.value(), laser_run_s=self.laser_run.value(),
            camera_start_s=self.camera_start.value(), frequency_hz=self._values(self.frequency),
            amplitude_v=self._values(self.amplitude), exposure_ms=self._values(self.exposure),
            roi=(self.roi_x.value(), self.roi_y.value(), self.roi_width.value(), self.roi_height.value()),
            flush_unit_index=self.pump_unit.currentData(), flush_volume_ml=self.volume.value(),
            flush_flow_ul_min=self.flow.value(), sweep_enabled=self.sweep_enabled.isChecked(),
            sweep_width_hz=self._values(self.sweep_width), sweep_period_ms=self.sweep_period.value(),
            temperature_control=self.temperature_control.isChecked(), tec_channel=self.tec_channel.currentData(),
            temperature_c=self._values(self.temperature), temperature_wait_s=self.temp_wait.value(),
            temperature_logging=self.temperature_logging.isChecked(), tiff_format=self.tiff_format.currentData(),
        )

    def _definition(self) -> dict:
        return compile_simple_series(self._settings())

    def _preview(self, *_args) -> None:
        try:
            definition = self._definition()
            count = len(validate_definition(definition).experiments)
            self.summary.setText(f"{count} experiments · {count + 1} flushes · "
                f"{(count + 1) * self.volume.value():g} mL total flush volume · "
                f"{count * self.frames.value()} saved frames")
        except (ValueError, ZeroDivisionError) as exc:
            self.summary.setText(f"Settings need attention: {exc}")

    def _enabled(self, *_args) -> None:
        for widget in (*self.sweep_width, self.sweep_period):
            widget.setEnabled(self.sweep_enabled.isChecked())
        for widget in (*self.temperature, self.tec_channel, self.temp_wait):
            widget.setEnabled(self.temperature_control.isChecked())

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
            definition = self._definition()
            self.preflight_button.setEnabled(False)
            self.state_label.setText("Count preflight running; ultrasound, laser, LED and pump inactive")
            self.preflight.run(definition)
        except Exception as exc:
            self.preflight_button.setEnabled(True)
            QMessageBox.warning(self, "Preflight could not start", str(exc))

    def _preflight_finished(self, ok: bool, message: str, fingerprint: str) -> None:
        self.preflight_button.setEnabled(True)
        self._passed = (fingerprint, self._fill_level()) if ok else None
        if ok:
            self.manager.record_simple_preflight(fingerprint, self.pump_unit.currentData(),
                                                 self._fill_level())
        self.state_label.setText(("Preflight passed: " if ok else "Preflight failed: ") + message)

    def _queue(self) -> None:
        try:
            definition = self._definition()
            root = Path(self.output_root.text().strip())
            if not self.output_root.text().strip():
                raise ValueError("Choose an experiment base folder")
            folder = self.manager.queue(definition, root)
            self.state_label.setText(f"Queued: {folder}")
        except Exception as exc:
            QMessageBox.warning(self, "Could not queue series", str(exc))

    def _start(self) -> None:
        try:
            self.manager.start()
        except Exception as exc:
            QMessageBox.warning(self, "Could not start batch", str(exc))

    def _devices(self, statuses: dict) -> None:
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
            self.pump_unit.clear()
            for label, index in desired_pumps:
                self.pump_unit.addItem(label, index)
            if current is not None and self.pump_unit.findData(current) >= 0:
                self.pump_unit.setCurrentIndex(self.pump_unit.findData(current))
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

    def _status(self, status: dict) -> None:
        self.state_label.setText(f"Batch: {status['state']} · queued: {status['queued_series']} · "
                                 f"completed experiments: {status['completed_experiments']}")
