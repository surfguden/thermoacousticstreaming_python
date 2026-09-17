from __future__ import annotations

import math
from typing import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..application.commands import (
    Ad2ConfigureDigitalOutputArgs,
    Ad2ConfigureScopeArgs,
    Ad2ConfigureWaveformArgs,
    Ad2DigitalOutputType,
    Ad2ScopeReadResult,
    Ad2TriggerSource,
    CameraConfigureExposureArgs,
    CameraConfigureRoiArgs,
    CameraConfigureSequenceArgs,
    CameraConfigureSnapshotArgs,
    CameraSequenceResult,
    CameraSnapshotResult,
    DeviceCommand,
    DeviceOperation,
    PumpConfigureFlowUnitArgs,
    PumpConfigureSyringeArgs,
    PumpFlowUnit,
    PumpMoveArgs,
    PumpReferenceMoveArgs,
    PumpSetFillLevelArgs,
    PumpSetFlowArgs,
    PumpSyringePreset,
    TecApplySetpointsArgs,
    TecReadStatusArgs,
    TecStatusResult,
    TecWaitStableArgs,
    ValveSetPositionArgs,
    ValveWaitReadyArgs,
    ZStageSetPositionArgs,
)
from ..domain.models import ConnectionState, DEVICE_LABELS, DeviceId, DeviceStatus
from .widgets import CameraPreview, ScopePlot


def double_spin(
    value: float = 0.0,
    minimum: float = -1_000_000.0,
    maximum: float = 1_000_000.0,
    decimals: int = 4,
) -> QDoubleSpinBox:
    widget = QDoubleSpinBox()
    widget.setDecimals(decimals)
    widget.setRange(minimum, maximum)
    widget.setValue(value)
    return widget


def int_spin(value: int = 0, minimum: int = 0, maximum: int = 10_000_000) -> QSpinBox:
    widget = QSpinBox()
    widget.setRange(minimum, maximum)
    widget.setValue(value)
    return widget


def button_row(*buttons: QPushButton) -> QWidget:
    widget = QWidget()
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    for button in buttons:
        layout.addWidget(button)
    layout.addStretch(1)
    return widget


def form_group(title: str) -> tuple[QGroupBox, QFormLayout]:
    group = QGroupBox(title)
    return group, QFormLayout(group)


class DevicePanel(QScrollArea):
    command_requested = Signal(str, object)
    notice = Signal(str)

    def __init__(self, device_id: DeviceId, parent=None) -> None:
        super().__init__(parent)
        self.device_id = device_id
        self._pending: dict[str, str] = {}
        self._buttons: dict[str, QPushButton] = {}
        self._button_labels: dict[str, str] = {}
        self._requires_connection: set[str] = set()
        self._profile_widgets: dict[str, QWidget] = {}
        self._connected = False
        self._busy = False
        self.setWidgetResizable(True)
        body = QWidget()
        self.layout = QVBoxLayout(body)
        self.setWidget(body)

        header = QGroupBox(DEVICE_LABELS[device_id])
        header_layout = QGridLayout(header)
        self.connection_label = QLabel("Disconnected")
        self.state_label = QLabel("Idle")
        self.fault_label = QLabel("")
        self.fault_label.setWordWrap(True)
        header_layout.addWidget(QLabel("Connection"), 0, 0)
        header_layout.addWidget(self.connection_label, 0, 1)
        header_layout.addWidget(QLabel("State"), 0, 2)
        header_layout.addWidget(self.state_label, 0, 3)
        header_layout.addWidget(QLabel("Fault"), 1, 0)
        header_layout.addWidget(self.fault_label, 1, 1, 1, 3)
        connect = self.action_button("connect", "Connect", DeviceOperation.CONNECT, requires_connection=False)
        disconnect = self.action_button(
            "disconnect", "Disconnect", DeviceOperation.DISCONNECT, requires_connection=False
        )
        abort = self.action_button("abort", "Abort active", DeviceOperation.ABORT_ACTIVE)
        safe_stop = self.action_button("safe_stop", "Safe stop", DeviceOperation.SAFE_STOP)
        header_layout.addWidget(button_row(connect, disconnect, abort, safe_stop), 2, 0, 1, 4)
        self.layout.addWidget(header)

        self.notice_label = QLabel("")
        self.notice_label.setWordWrap(True)
        self.notice_label.setStyleSheet("color: #a65a00; font-weight: 600;")
        self.layout.addWidget(self.notice_label)

    def finish_layout(self) -> None:
        self.layout.addStretch(1)
        self._update_controls()

    def action_button(
        self,
        action: str,
        label: str,
        operation: DeviceOperation,
        arguments: Callable[[], object] | None = None,
        *,
        requires_connection: bool = True,
    ) -> QPushButton:
        button = QPushButton(label)
        self._buttons[action] = button
        self._button_labels[action] = label
        if requires_connection:
            self._requires_connection.add(action)
        button.clicked.connect(
            lambda checked=False: self._trigger(action, operation, arguments)
        )
        return button

    def _trigger(
        self,
        action: str,
        operation: DeviceOperation,
        arguments: Callable[[], object] | None,
    ) -> None:
        if action in self._pending:
            self.show_notice(
                f"{self._button_labels[action]} was not queued again; request "
                f"{self._pending[action]} is still pending."
            )
            return
        try:
            value = arguments() if arguments is not None else None
            command = (
                DeviceCommand(self.device_id, operation, source="ui")
                if value is None
                else DeviceCommand(self.device_id, operation, value, source="ui")
            )
        except (TypeError, ValueError) as exc:
            self.show_notice(str(exc))
            return
        self.command_requested.emit(action, command)

    def mark_pending(self, action: str, request_id: str) -> None:
        self._pending[action] = request_id
        self._buttons[action].setText(f"{self._button_labels[action]} · pending")
        self.show_notice(
            f"{self._button_labels[action]} queued as {request_id}; duplicate submissions are blocked."
        )

    def clear_pending(self, request_id: str) -> None:
        for action, pending_id in tuple(self._pending.items()):
            if pending_id == request_id:
                del self._pending[action]
                self._buttons[action].setText(self._button_labels[action])

    def show_notice(self, message: str) -> None:
        self.notice_label.setText(message)
        self.notice.emit(f"{self.device_id.value}: {message}")

    def set_status(self, status: DeviceStatus) -> None:
        self._connected = status.connection is ConnectionState.CONNECTED
        self._busy = status.busy
        self.connection_label.setText(status.connection.value.replace("_", " ").title())
        flags = ["busy" if status.busy else "idle"]
        if status.configured:
            flags.append("configured")
        if status.active:
            flags.append("active")
        self.state_label.setText(" · ".join(flags))
        self.fault_label.setText(status.fault or "—")
        self.update_readback(status.readback)
        self._update_controls()

    def _update_controls(self) -> None:
        for action, button in self._buttons.items():
            if action == "connect":
                button.setEnabled(not self._connected)
            elif action == "disconnect":
                button.setEnabled(self._connected)
            elif action == "abort":
                button.setEnabled(self._connected and self._busy)
            elif action in self._requires_connection:
                button.setEnabled(self._connected)

    def update_readback(self, readback: object) -> None:
        del readback

    def handle_result(self, result: object) -> None:
        del result

    def register_profile(self, name: str, widget: QWidget) -> QWidget:
        self._profile_widgets[name] = widget
        return widget

    def profile_values(self) -> dict[str, object]:
        values: dict[str, object] = {}
        for name, widget in self._profile_widgets.items():
            if isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                values[name] = widget.value()
            elif isinstance(widget, QCheckBox):
                values[name] = widget.isChecked()
            elif isinstance(widget, QComboBox):
                values[name] = widget.currentData()
            elif isinstance(widget, QLineEdit):
                values[name] = widget.text()
        return values

    def validate_profile(self, data: object) -> dict[str, object]:
        if not isinstance(data, dict):
            raise ValueError(f"{self.device_id.value} settings must be an object")
        unknown = set(data) - set(self._profile_widgets)
        if unknown:
            raise ValueError(
                f"Unknown {self.device_id.value} setting(s): {', '.join(sorted(unknown))}"
            )
        values = self.profile_values()
        for name, value in data.items():
            widget = self._profile_widgets[name]
            if isinstance(widget, QSpinBox):
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ValueError(f"{name} must be an integer")
                if not widget.minimum() <= value <= widget.maximum():
                    raise ValueError(f"{name} is outside the allowed range")
            elif isinstance(widget, QDoubleSpinBox):
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(f"{name} must be a number")
                value = float(value)
                if not math.isfinite(value) or not widget.minimum() <= value <= widget.maximum():
                    raise ValueError(f"{name} is outside the allowed finite range")
            elif isinstance(widget, QCheckBox):
                if not isinstance(value, bool):
                    raise ValueError(f"{name} must be true or false")
            elif isinstance(widget, QComboBox):
                if not isinstance(value, str) or widget.findData(value) < 0:
                    raise ValueError(f"{name} has an unsupported choice")
            elif isinstance(widget, QLineEdit) and not isinstance(value, str):
                raise ValueError(f"{name} must be text")
            values[name] = value
        self._validate_profile_values(values)
        return values

    def _validate_profile_values(self, values: dict[str, object]) -> None:
        del values

    def apply_profile(self, values: dict[str, object]) -> None:
        for name, value in values.items():
            widget = self._profile_widgets[name]
            if isinstance(widget, QSpinBox):
                widget.setValue(int(value))
            elif isinstance(widget, QDoubleSpinBox):
                widget.setValue(float(value))
            elif isinstance(widget, QCheckBox):
                widget.setChecked(bool(value))
            elif isinstance(widget, QComboBox):
                widget.setCurrentIndex(widget.findData(value))
            elif isinstance(widget, QLineEdit):
                widget.setText(str(value))


class Ad2Panel(DevicePanel):
    def __init__(self, parent=None) -> None:
        super().__init__(DeviceId.AD2, parent)
        group, form = form_group("Waveform generator")
        self.wave_frequency = self.register_profile("wave_frequency_hz", double_spin(1000, 0.001))
        self.wave_amplitude = self.register_profile("wave_amplitude_v", double_spin(1, 0, 1000))
        form.addRow("Frequency (Hz)", self.wave_frequency)
        form.addRow("Amplitude (V)", self.wave_amplitude)
        form.addRow(button_row(
            self.action_button("wave_config", "Configure", DeviceOperation.AD2_WAVEFORM_CONFIGURE, self._wave_args),
            self.action_button("wave_start", "Start", DeviceOperation.AD2_WAVEFORM_START),
            self.action_button("wave_stop", "Stop", DeviceOperation.AD2_WAVEFORM_STOP),
        ))
        self.layout.addWidget(group)

        group, form = form_group("Oscilloscope")
        self.scope_count = self.register_profile("scope_sample_count", int_spin(1000, 1))
        self.scope_channels = self.register_profile("scope_channels", QLineEdit("0"))
        self.scope_trigger = self.register_profile("scope_trigger", QComboBox())
        for source in Ad2TriggerSource:
            self.scope_trigger.addItem(source.value, source.value)
        form.addRow("Sample count", self.scope_count)
        form.addRow("Channels (comma separated)", self.scope_channels)
        form.addRow("Trigger", self.scope_trigger)
        form.addRow(button_row(
            self.action_button("scope_config", "Configure", DeviceOperation.AD2_SCOPE_CONFIGURE, self._scope_args),
            self.action_button("scope_trigger_pc", "PC trigger", DeviceOperation.AD2_SOFTWARE_TRIGGER),
            self.action_button("scope_read", "Read", DeviceOperation.AD2_SCOPE_READ),
        ))
        self.scope_plot = ScopePlot()
        form.addRow(self.scope_plot)
        self.layout.addWidget(group)

        group, form = form_group("Digital output")
        self.do_channel = self.register_profile("do_channel", int_spin(0, 0, 31))
        self.do_enabled = self.register_profile("do_enabled", QCheckBox())
        self.do_enabled.setChecked(True)
        self.do_type = self.register_profile("do_type", QComboBox())
        for output_type in Ad2DigitalOutputType:
            self.do_type.addItem(output_type.value, output_type.value)
        self.do_clock_enabled = self.register_profile("do_clock_enabled", QCheckBox())
        self.do_clock_enabled.setChecked(True)
        self.do_clock = self.register_profile("do_clock_hz", double_spin(500, 0.001))
        self.do_high = self.register_profile("do_high_bits", int_spin(1, 1))
        self.do_low = self.register_profile("do_low_bits", int_spin(1, 1))
        self.do_start_high = self.register_profile("do_start_high", QCheckBox())
        self.do_start_high.setChecked(True)
        self.do_bits = self.register_profile("do_bits", QLineEdit(""))
        self.do_frames_enabled = self.register_profile("do_frames_enabled", QCheckBox())
        self.do_frames = self.register_profile("do_frame_count", int_spin(1, 1))
        for label, widget in (
            ("Channel", self.do_channel), ("Enabled", self.do_enabled), ("Type", self.do_type),
            ("Use clock", self.do_clock_enabled), ("Clock (Hz)", self.do_clock),
            ("High bits", self.do_high), ("Low bits", self.do_low),
            ("Start high", self.do_start_high), ("Custom bits", self.do_bits),
            ("Limit frames", self.do_frames_enabled), ("Frame count", self.do_frames),
        ):
            form.addRow(label, widget)
        form.addRow(button_row(
            self.action_button("do_config", "Configure", DeviceOperation.AD2_DIGITAL_OUTPUT_CONFIGURE, self._do_args),
            self.action_button("do_start", "Start", DeviceOperation.AD2_DIGITAL_OUTPUT_START),
            self.action_button("do_stop", "Stop", DeviceOperation.AD2_DIGITAL_OUTPUT_STOP),
            self.action_button("do_reset", "Reset", DeviceOperation.AD2_DIGITAL_OUTPUT_RESET),
        ))
        self.layout.addWidget(group)
        self.readback_label = QLabel("No readback")
        self.layout.addWidget(self.readback_label)
        self.finish_layout()

    def _channels(self, text: str | None = None) -> tuple[int, ...]:
        raw = self.scope_channels.text() if text is None else text
        values = tuple(
            int(value.strip()) for value in raw.split(",") if value.strip()
        )
        if not values:
            raise ValueError("Choose at least one scope channel")
        return values

    def _wave_args(self) -> Ad2ConfigureWaveformArgs:
        return Ad2ConfigureWaveformArgs(self.wave_frequency.value(), self.wave_amplitude.value())

    def _scope_args(self) -> Ad2ConfigureScopeArgs:
        return Ad2ConfigureScopeArgs(
            self.scope_count.value(), self._channels(), Ad2TriggerSource(self.scope_trigger.currentData())
        )

    def _do_args(self) -> Ad2ConfigureDigitalOutputArgs:
        text = "".join(self.do_bits.text().split())
        if any(bit not in "01" for bit in text):
            raise ValueError("Custom digital output bits may contain only 0 and 1")
        return Ad2ConfigureDigitalOutputArgs(
            channel_index=self.do_channel.value(), enabled=self.do_enabled.isChecked(),
            output_type=Ad2DigitalOutputType(self.do_type.currentData()),
            clock_frequency_hz=self.do_clock.value() if self.do_clock_enabled.isChecked() else None,
            counter_high_bits=self.do_high.value(), counter_low_bits=self.do_low.value(),
            start_high=self.do_start_high.isChecked(), bits=tuple(int(bit) for bit in text),
            frame_count=self.do_frames.value() if self.do_frames_enabled.isChecked() else None,
        )

    def _validate_profile_values(self, values: dict[str, object]) -> None:
        self._channels(str(values["scope_channels"]))
        bits = "".join(str(values["do_bits"]).split())
        if any(bit not in "01" for bit in bits):
            raise ValueError("do_bits may contain only 0 and 1")
        if values["do_type"] == Ad2DigitalOutputType.CUSTOM.value and not bits:
            raise ValueError("do_bits must not be empty for custom digital output")

    def update_readback(self, readback: object) -> None:
        if readback is not None:
            self.readback_label.setText(str(readback))

    def handle_result(self, result: object) -> None:
        if isinstance(result, Ad2ScopeReadResult):
            self.scope_plot.set_samples(result.samples_by_channel)


class PumpPanel(DevicePanel):
    def __init__(self, parent=None) -> None:
        super().__init__(DeviceId.PUMP, parent)
        group, form = form_group("Flow and fill level")
        self.flow = self.register_profile("flow_ul_min", double_spin(100))
        self.fill_level = self.register_profile("fill_level_ml", double_spin(0, 0))
        self.fill_flow_enabled = self.register_profile("fill_flow_enabled", QCheckBox())
        self.fill_flow = self.register_profile("fill_flow_ul_min", double_spin(100))
        form.addRow("Flow (µL/min)", self.flow)
        form.addRow(button_row(
            self.action_button("set_flow", "Set flow", DeviceOperation.PUMP_FLOW_SET, lambda: PumpSetFlowArgs(self.flow.value())),
            self.action_button("stop", "Stop pump", DeviceOperation.PUMP_FLOW_STOP),
            self.action_button("status", "Read status", DeviceOperation.PUMP_STATUS_READ),
        ))
        form.addRow("Fill level (mL)", self.fill_level)
        form.addRow("Use fill flow", self.fill_flow_enabled)
        form.addRow("Fill flow (µL/min)", self.fill_flow)
        form.addRow(button_row(
            self.action_button("set_fill", "Set fill level", DeviceOperation.PUMP_FILL_LEVEL_SET, self._fill_args),
            self.action_button("read_fill", "Read fill level", DeviceOperation.PUMP_FILL_LEVEL_READ),
        ))
        self.layout.addWidget(group)

        group, form = form_group("Refill, empty, and reference")
        self.move_flow_enabled = self.register_profile("move_flow_enabled", QCheckBox())
        self.move_flow = self.register_profile("move_flow_ul_min", double_spin(1000))
        self.move_timeout = self.register_profile("move_timeout_s", double_spin(120, 0.001))
        self.move_poll = self.register_profile("move_poll_s", double_spin(0.1, 0.001, 60, 3))
        self.reference_timeout = self.register_profile("reference_timeout_s", double_spin(60, 0.001))
        self.reference_poll = self.register_profile("reference_poll_s", double_spin(0.1, 0.001, 60, 3))
        for label, widget in (
            ("Use flow override", self.move_flow_enabled), ("Flow override (µL/min)", self.move_flow),
            ("Movement timeout (s)", self.move_timeout), ("Movement poll (s)", self.move_poll),
            ("Reference timeout (s)", self.reference_timeout), ("Reference poll (s)", self.reference_poll),
        ):
            form.addRow(label, widget)
        form.addRow(button_row(
            self.action_button("refill", "Refill", DeviceOperation.PUMP_REFILL, self._move_args),
            self.action_button("empty", "Empty", DeviceOperation.PUMP_EMPTY, self._move_args),
            self.action_button("reference", "Reference move", DeviceOperation.PUMP_REFERENCE_MOVE, self._reference_args),
        ))
        self.layout.addWidget(group)

        group, form = form_group("Configuration and recovery")
        self.syringe_mode = self.register_profile("syringe_mode", QComboBox())
        self.syringe_mode.addItem("BD 1 mL", PumpSyringePreset.BD_1_ML.value)
        self.syringe_mode.addItem("BD 5 mL", PumpSyringePreset.BD_5_ML.value)
        self.syringe_mode.addItem("BD 10 mL", PumpSyringePreset.BD_10_ML.value)
        self.syringe_mode.addItem("Custom", "custom")
        self.syringe_diameter = self.register_profile("syringe_diameter_mm", double_spin(4.7, 0.001, 100))
        self.syringe_stroke = self.register_profile("syringe_stroke_mm", double_spin(57, 0.001, 100))
        self.flow_unit = self.register_profile("flow_unit", QComboBox())
        for unit in PumpFlowUnit:
            self.flow_unit.addItem(unit.value, unit.value)
        form.addRow("Syringe", self.syringe_mode)
        form.addRow("Custom diameter (mm)", self.syringe_diameter)
        form.addRow("Custom stroke (mm)", self.syringe_stroke)
        form.addRow(button_row(self.action_button("syringe", "Configure syringe", DeviceOperation.PUMP_SYRINGE_CONFIGURE, self._syringe_args)))
        form.addRow("Flow unit", self.flow_unit)
        form.addRow(button_row(
            self.action_button("unit", "Configure unit", DeviceOperation.PUMP_FLOW_UNIT_CONFIGURE, lambda: PumpConfigureFlowUnitArgs(PumpFlowUnit(self.flow_unit.currentData()))),
            self.action_button("recover", "Recover fault", DeviceOperation.PUMP_FAULT_RECOVER),
        ))
        self.layout.addWidget(group)
        self.readback_label = QLabel("No readback")
        self.readback_label.setWordWrap(True)
        self.layout.addWidget(self.readback_label)
        self.finish_layout()

    def _fill_args(self) -> PumpSetFillLevelArgs:
        return PumpSetFillLevelArgs(
            self.fill_level.value(), self.fill_flow.value() if self.fill_flow_enabled.isChecked() else None
        )

    def _move_args(self) -> PumpMoveArgs:
        return PumpMoveArgs(
            self.move_flow.value() if self.move_flow_enabled.isChecked() else None,
            self.move_timeout.value(), self.move_poll.value(),
        )

    def _reference_args(self) -> PumpReferenceMoveArgs:
        return PumpReferenceMoveArgs(self.reference_timeout.value(), self.reference_poll.value())

    def _syringe_args(self) -> PumpConfigureSyringeArgs:
        value = self.syringe_mode.currentData()
        if value == "custom":
            return PumpConfigureSyringeArgs(
                inner_diameter_mm=self.syringe_diameter.value(),
                max_piston_stroke_mm=self.syringe_stroke.value(),
            )
        return PumpConfigureSyringeArgs(preset=PumpSyringePreset(value))

    def _validate_profile_values(self, values: dict[str, object]) -> None:
        PumpMoveArgs(
            float(values["move_flow_ul_min"]) if values["move_flow_enabled"] else None,
            float(values["move_timeout_s"]), float(values["move_poll_s"]),
        )
        PumpReferenceMoveArgs(float(values["reference_timeout_s"]), float(values["reference_poll_s"]))

    def update_readback(self, readback: object) -> None:
        if readback is not None:
            self.readback_label.setText(str(readback))


class ValvePanel(DevicePanel):
    def __init__(self, parent=None) -> None:
        super().__init__(DeviceId.VALVE, parent)
        group, form = form_group("Valve position")
        self.position = self.register_profile("position", int_spin(1, 1, 2))
        self.wait_timeout = self.register_profile("wait_timeout_s", double_spin(1, 0.001, 3600, 3))
        self.wait_poll = self.register_profile("wait_poll_s", double_spin(0.05, 0.001, 60, 3))
        form.addRow("Position", self.position)
        form.addRow(button_row(
            self.action_button("set", "Set position", DeviceOperation.VALVE_POSITION_SET, lambda: ValveSetPositionArgs(self.position.value())),
            self.action_button("read", "Read position", DeviceOperation.VALVE_POSITION_READ),
        ))
        form.addRow("Ready timeout (s)", self.wait_timeout)
        form.addRow("Poll interval (s)", self.wait_poll)
        form.addRow(button_row(self.action_button("wait", "Wait until ready", DeviceOperation.VALVE_WAIT_READY, self._wait_args)))
        self.layout.addWidget(group)
        self.readback_label = QLabel("No readback")
        self.layout.addWidget(self.readback_label)
        self.finish_layout()

    def _wait_args(self) -> ValveWaitReadyArgs:
        if self.wait_poll.value() > self.wait_timeout.value():
            raise ValueError("Valve poll interval must not exceed its timeout")
        return ValveWaitReadyArgs(self.wait_timeout.value(), self.wait_poll.value())

    def _validate_profile_values(self, values: dict[str, object]) -> None:
        if float(values["wait_poll_s"]) > float(values["wait_timeout_s"]):
            raise ValueError("Valve poll interval must not exceed its timeout")

    def update_readback(self, readback: object) -> None:
        if readback is not None:
            self.readback_label.setText(str(readback))


class CameraPanel(DevicePanel):
    def __init__(self, parent=None) -> None:
        super().__init__(DeviceId.CAMERA, parent)
        group, form = form_group("Snapshot and exposure")
        self.snapshot_exposure_enabled = self.register_profile("snapshot_exposure_enabled", QCheckBox())
        self.snapshot_exposure = self.register_profile("snapshot_exposure_ms", double_spin(2.5, 0, 1_000_000))
        self.exposure = self.register_profile("exposure_ms", double_spin(2.5, 0, 1_000_000))
        form.addRow("Configure exposure", self.snapshot_exposure_enabled)
        form.addRow("Snapshot exposure (ms)", self.snapshot_exposure)
        form.addRow(button_row(
            self.action_button("snapshot_config", "Configure snapshot", DeviceOperation.CAMERA_SNAPSHOT_CONFIGURE, self._snapshot_args),
            self.action_button("snapshot", "Capture snapshot", DeviceOperation.CAMERA_SNAPSHOT_CAPTURE),
        ))
        form.addRow("Exposure (ms)", self.exposure)
        form.addRow(button_row(self.action_button("exposure", "Set exposure", DeviceOperation.CAMERA_EXPOSURE_CONFIGURE, lambda: CameraConfigureExposureArgs(self.exposure.value()))))
        self.layout.addWidget(group)

        group, form = form_group("Buffered sequence")
        self.sequence_frames = self.register_profile("sequence_frames", int_spin(10, 1, 1_000_000))
        self.sequence_exposure_enabled = self.register_profile("sequence_exposure_enabled", QCheckBox())
        self.sequence_exposure = self.register_profile("sequence_exposure_ms", double_spin(2.5, 0, 1_000_000))
        self.frame_timeout = self.register_profile("frame_timeout_s", double_spin(30, 0.001, 86_400, 3))
        self.frame_poll = self.register_profile("frame_poll_s", double_spin(0.05, 0.001, 60, 3))
        for label, widget in (
            ("Frames", self.sequence_frames), ("Configure exposure", self.sequence_exposure_enabled),
            ("Exposure (ms)", self.sequence_exposure), ("Per-frame timeout (s)", self.frame_timeout),
            ("Poll interval (s)", self.frame_poll),
        ):
            form.addRow(label, widget)
        form.addRow(button_row(
            self.action_button("sequence_config", "Configure sequence", DeviceOperation.CAMERA_SEQUENCE_CONFIGURE, self._sequence_args),
            self.action_button("sequence", "Capture sequence", DeviceOperation.CAMERA_SEQUENCE_CAPTURE),
            self.action_button("capture_stop", "Stop capture", DeviceOperation.CAMERA_CAPTURE_STOP),
        ))
        self.sequence_status = QLabel("No sequence")
        form.addRow("Progress", self.sequence_status)
        self.layout.addWidget(group)

        group, form = form_group("ROI and timing")
        self.roi_x = self.register_profile("roi_x", int_spin(0, 0, 100_000))
        self.roi_y = self.register_profile("roi_y", int_spin(0, 0, 100_000))
        self.roi_width = self.register_profile("roi_width", int_spin(512, 1, 100_000))
        self.roi_height = self.register_profile("roi_height", int_spin(512, 1, 100_000))
        for label, widget in (("X", self.roi_x), ("Y", self.roi_y), ("Width", self.roi_width), ("Height", self.roi_height)):
            form.addRow(label, widget)
        form.addRow(button_row(
            self.action_button("roi", "Set ROI", DeviceOperation.CAMERA_ROI_CONFIGURE, self._roi_args),
            self.action_button("timing", "Read timing", DeviceOperation.CAMERA_TIMING_READ),
        ))
        self.layout.addWidget(group)
        self.preview = CameraPreview()
        self.layout.addWidget(self.preview)
        self.readback_label = QLabel("No readback")
        self.readback_label.setWordWrap(True)
        self.layout.addWidget(self.readback_label)
        self.finish_layout()

    def _snapshot_args(self) -> CameraConfigureSnapshotArgs:
        return CameraConfigureSnapshotArgs(
            self.snapshot_exposure.value() if self.snapshot_exposure_enabled.isChecked() else None
        )

    def _sequence_args(self) -> CameraConfigureSequenceArgs:
        return CameraConfigureSequenceArgs(
            self.sequence_frames.value(),
            self.sequence_exposure.value() if self.sequence_exposure_enabled.isChecked() else None,
            self.frame_timeout.value(), self.frame_poll.value(),
        )

    def _roi_args(self) -> CameraConfigureRoiArgs:
        return CameraConfigureRoiArgs(
            self.roi_x.value(), self.roi_y.value(), self.roi_width.value(), self.roi_height.value()
        )

    def _validate_profile_values(self, values: dict[str, object]) -> None:
        CameraConfigureSequenceArgs(
            int(values["sequence_frames"]),
            float(values["sequence_exposure_ms"]) if values["sequence_exposure_enabled"] else None,
            float(values["frame_timeout_s"]), float(values["frame_poll_s"]),
        )
        CameraConfigureRoiArgs(
            int(values["roi_x"]), int(values["roi_y"]), int(values["roi_width"]), int(values["roi_height"])
        )

    def update_readback(self, readback: object) -> None:
        if readback is not None:
            self.readback_label.setText(str(readback))
            captured = getattr(readback, "captured_frame_count", 0)
            expected = getattr(readback, "sequence_frame_count", None)
            if expected is not None:
                self.sequence_status.setText(f"{captured}/{expected} frames")

    def handle_result(self, result: object) -> None:
        if isinstance(result, CameraSnapshotResult):
            self.preview.set_frame(result.frame)
            self.sequence_status.setText("Snapshot captured")
        elif isinstance(result, CameraSequenceResult):
            if result.frames:
                self.preview.set_frame(result.frames[-1])
            timestamp = result.timestamps[-1] if result.timestamps else "no timestamp"
            self.sequence_status.setText(f"{len(result.frames)} frames · last: {timestamp}")


class TecPanel(DevicePanel):
    def __init__(self, parent=None) -> None:
        super().__init__(DeviceId.TEC, parent)
        group, form = form_group("Setpoints and stabilization")
        self.target_mode = self.register_profile("target_mode", QComboBox())
        self.target_mode.addItem("Broadcast to both channels", "broadcast")
        self.target_mode.addItem("Per channel", "per_channel")
        self.target = self.register_profile("target_c", double_spin(25, -100, 200))
        self.target_1 = self.register_profile("target_1_c", double_spin(25, -100, 200))
        self.target_2 = self.register_profile("target_2_c", double_spin(25, -100, 200))
        self.tolerance = self.register_profile("tolerance_c", double_spin(0.2, 0, 100))
        self.settle = self.register_profile("min_settle_s", double_spin(5, 0, 86_400))
        self.max_wait = self.register_profile("max_wait_s", double_spin(300, 0.001, 86_400))
        self.poll = self.register_profile("poll_interval_s", double_spin(1, 0.001, 3600, 3))
        for label, widget in (
            ("Target mode", self.target_mode), ("Broadcast target (°C)", self.target),
            ("Channel 1 target (°C)", self.target_1), ("Channel 2 target (°C)", self.target_2),
            ("Tolerance (°C)", self.tolerance), ("Minimum settle (s)", self.settle),
            ("Maximum wait (s)", self.max_wait), ("Poll interval (s)", self.poll),
        ):
            form.addRow(label, widget)
        form.addRow(button_row(
            self.action_button("apply", "Apply setpoints", DeviceOperation.TEC_SETPOINTS_APPLY, self._apply_args),
            self.action_button("wait", "Wait until stable", DeviceOperation.TEC_WAIT_STABLE, self._wait_args),
            self.action_button("read", "Read status", DeviceOperation.TEC_STATUS_READ, TecReadStatusArgs),
            self.action_button("off", "Outputs off", DeviceOperation.TEC_OUTPUTS_OFF),
        ))
        self.layout.addWidget(group)
        self.table = QTableWidget(2, 6)
        self.table.setHorizontalHeaderLabels(("Channel", "Current °C", "Target °C", "Output", "Ready", "Fault"))
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.layout.addWidget(self.table)
        self.finish_layout()

    def _targets(self) -> float | dict[int, float]:
        if self.target_mode.currentData() == "broadcast":
            return self.target.value()
        return {1: self.target_1.value(), 2: self.target_2.value()}

    def _apply_args(self) -> TecApplySetpointsArgs:
        return TecApplySetpointsArgs(self._targets())

    def _wait_args(self) -> TecWaitStableArgs:
        return TecWaitStableArgs(
            self._targets(), self.tolerance.value(), self.settle.value(),
            self.max_wait.value(), self.poll.value(),
        )

    def _validate_profile_values(self, values: dict[str, object]) -> None:
        targets: float | dict[int, float]
        if values["target_mode"] == "broadcast":
            targets = float(values["target_c"])
        else:
            targets = {1: float(values["target_1_c"]), 2: float(values["target_2_c"])}
        TecWaitStableArgs(
            targets, float(values["tolerance_c"]), float(values["min_settle_s"]),
            float(values["max_wait_s"]), float(values["poll_interval_s"]),
        )

    def update_readback(self, readback: object) -> None:
        channels = getattr(readback, "channels", ()) if readback is not None else ()
        self._set_channels(channels)

    def handle_result(self, result: object) -> None:
        if isinstance(result, TecStatusResult):
            self._set_channels(result.channels)

    def _set_channels(self, channels: object) -> None:
        for row, channel in enumerate(channels):
            if row >= self.table.rowCount():
                self.table.insertRow(row)
            values = (
                channel.channel,
                channel.current_temperature_c,
                channel.target_temperature_c,
                channel.output_enabled,
                channel.ready,
                channel.fault or "",
            )
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(str(value)))


class ZStagePanel(DevicePanel):
    def __init__(self, parent=None) -> None:
        super().__init__(DeviceId.Z_STAGE, parent)
        group, form = form_group("Closed-loop position")
        self.position = self.register_profile("position_um", double_spin(50, -1_000_000, 1_000_000))
        form.addRow(button_row(
            self.action_button("requirement", "Check closed-loop requirement", DeviceOperation.Z_STAGE_CLOSED_LOOP_REQUIREMENT_READ),
            self.action_button("enable", "Enable closed loop", DeviceOperation.Z_STAGE_CLOSED_LOOP_ENABLE),
        ))
        form.addRow("Position (µm)", self.position)
        form.addRow(button_row(
            self.action_button("move", "Move", DeviceOperation.Z_STAGE_POSITION_SET, lambda: ZStageSetPositionArgs(self.position.value())),
            self.action_button("read", "Read position", DeviceOperation.Z_STAGE_POSITION_READ),
        ))
        self.layout.addWidget(group)
        self.readback_label = QLabel("No readback")
        self.layout.addWidget(self.readback_label)
        self.finish_layout()

    def update_readback(self, readback: object) -> None:
        if readback is not None:
            self.readback_label.setText(str(readback))


PANEL_TYPES = {
    DeviceId.AD2: Ad2Panel,
    DeviceId.PUMP: PumpPanel,
    DeviceId.VALVE: ValvePanel,
    DeviceId.CAMERA: CameraPanel,
    DeviceId.TEC: TecPanel,
    DeviceId.Z_STAGE: ZStagePanel,
}
