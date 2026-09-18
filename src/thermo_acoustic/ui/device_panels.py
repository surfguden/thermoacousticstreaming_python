from __future__ import annotations

import math
from typing import Callable

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..application.commands import (
    Ad2ConfigureDigitalOutputArgs,
    Ad2ConfigureScopeArgs,
    Ad2ConfigureWaveformArgs,
    Ad2AnalogOutputIdle,
    Ad2DigitalOutputType,
    Ad2WaveformAppliedResult,
    Ad2WaveformChannelArgs,
    Ad2WaveformFunction,
    Ad2TriggerSettingsArgs,
    Ad2TriggerSource,
    CameraMasterPulseMode,
    CameraMasterPulseSource,
    CameraConfigureExposureArgs,
    CameraConfigureRoiArgs,
    CameraConfigureSequenceArgs,
    CameraConfigureSnapshotArgs,
    CameraSequenceTriggerArgs,
    CameraSequenceResult,
    CameraSnapshotResult,
    CameraTriggerActive,
    CameraTriggerPolarity,
    CameraTriggerSource,
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
from ..domain.models import (
    Ad2Capabilities,
    Ad2WaveformChannelCapabilities,
    ConnectionState,
    DEVICE_LABELS,
    DeviceId,
    DeviceStatus,
)
from .ad2_scope import OscilloscopePanel
from .widgets import CameraPreview


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
    layout = QGridLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setHorizontalSpacing(4)
    layout.setVerticalSpacing(4)
    for index, button in enumerate(buttons):
        layout.addWidget(button, index // 3, index % 3)
    return widget


def form_group(title: str) -> tuple[QGroupBox, QFormLayout]:
    group = QGroupBox(title)
    form = QFormLayout(group)
    form.setContentsMargins(6, 6, 6, 6)
    form.setVerticalSpacing(3)
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    return group, form


class CurrentPageStack(QStackedWidget):
    """Let responsive layouts size to the exposed mode, not hidden pages."""

    def sizeHint(self):
        current = self.currentWidget()
        return current.sizeHint() if current is not None else super().sizeHint()

    def minimumSizeHint(self):
        current = self.currentWidget()
        return current.minimumSizeHint() if current is not None else super().minimumSizeHint()


class DevicePanel(QScrollArea):
    command_requested = Signal(str, object)
    notice = Signal(str)

    def __init__(self, device_id: DeviceId, parent=None) -> None:
        super().__init__(parent)
        self.device_id = device_id
        self._pending: dict[str, str] = {}
        self._buttons: dict[str, QPushButton] = {}
        self._button_labels: dict[str, str] = {}
        self._action_operations: dict[str, DeviceOperation] = {}
        self._requires_connection: set[str] = set()
        self._profile_widgets: dict[str, QWidget] = {}
        self._connected = False
        self._busy = False
        self.setWidgetResizable(True)
        body = QWidget()
        self.layout = QVBoxLayout(body)
        self.layout.setContentsMargins(6, 6, 6, 6)
        self.layout.setSpacing(4)
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
        self._action_operations[action] = operation
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
        duplicate_action = next(
            (
                pending_action
                for pending_action in self._pending
                if self._action_operations[pending_action] is operation
            ),
            None,
        )
        if duplicate_action is not None:
            self.show_notice(
                f"{self._button_labels[action]} was not queued again; request "
                f"{self._pending[duplicate_action]} is still pending."
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
        self._update_controls()

    def clear_pending(self, request_id: str) -> None:
        for action, pending_id in tuple(self._pending.items()):
            if pending_id == request_id:
                del self._pending[action]
                self._buttons[action].setText(self._button_labels[action])
        self._update_controls()

    def show_notice(self, message: str) -> None:
        self.notice_label.setText(message)
        self.notice.emit(f"{self.device_id.value}: {message}")
        QTimer.singleShot(
            5000,
            lambda expected=message: self.notice_label.setText("")
            if self.notice_label.text() == expected
            else None,
        )

    def set_status(self, status: DeviceStatus) -> None:
        # ERROR represents a connected device with an operation fault; it is
        # not a physical disconnect. Keep recovery and disconnect controls usable.
        self._connected = status.connection in {
            ConnectionState.CONNECTED,
            ConnectionState.ERROR,
        }
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
        pending_operations = {
            self._action_operations[action] for action in self._pending
        }
        for action, button in self._buttons.items():
            if action == "connect":
                enabled = not self._connected
            elif action == "disconnect":
                enabled = self._connected
            elif action == "abort":
                enabled = self._connected and self._busy
            elif action in self._requires_connection:
                enabled = self._connected
            else:
                enabled = True
            if self._action_operations[action] in pending_operations:
                enabled = False
            button.setEnabled(enabled)

    def update_readback(self, readback: object) -> None:
        del readback

    def handle_result(self, result: object) -> None:
        del result

    def apply_successful_command(self, command: DeviceCommand | None) -> None:
        """Synchronize editable controls after any successful command source."""
        del command

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
                if widget.findData(value) < 0:
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


class WaveformChannelEditor(QGroupBox):
    _MODES = ("single", "sweep", "advanced")

    def __init__(self, panel: "Ad2Panel", channel_index: int) -> None:
        super().__init__(f"CH{channel_index + 1}")
        self.panel = panel
        self.channel_index = channel_index
        self.prefix = f"wave_ch{channel_index + 1}"
        self._loading = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        common, common_form = form_group("Channel")
        self.mode = panel.register_profile(f"{self.prefix}_mode", QComboBox())
        self.mode.addItem("Single Freq", "single")
        self.mode.addItem("Sweep", "sweep")
        self.mode.addItem("Advanced", "advanced")
        self.enabled = panel.register_profile(f"{self.prefix}_enabled", QCheckBox())
        self.enabled.setChecked(channel_index == 0)
        self.idle = panel.register_profile(f"{self.prefix}_idle", QComboBox())
        for idle in Ad2AnalogOutputIdle:
            self.idle.addItem(idle.value, idle.value)
        self.idle.setCurrentIndex(self.idle.findData(Ad2AnalogOutputIdle.INITIAL.value))
        common_form.addRow("Mode", self.mode)
        common_form.addRow("Output enabled", self.enabled)
        common_form.addRow("Idle output", self.idle)
        layout.addWidget(common)

        self.pages = CurrentPageStack()
        self.pages.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.pages, 1)
        self._build_single_page()
        self._build_sweep_page()
        self._build_advanced_page()

        trigger_group, trigger_form = form_group("Trigger")
        trigger_prefix = "wave" if channel_index == 0 else self.prefix
        self.trigger = panel._add_trigger_controls(trigger_prefix, trigger_form)
        layout.addWidget(trigger_group)
        self.applied_label = QLabel("Not configured")
        self.applied_label.setWordWrap(True)
        layout.addWidget(self.applied_label)

        self.mode.currentIndexChanged.connect(self._mode_changed)
        for widget in self.single_widgets + self.sweep_widgets:
            if isinstance(widget, QComboBox):
                widget.currentIndexChanged.connect(self._sync_current_to_advanced)
            elif isinstance(widget, QDoubleSpinBox):
                widget.valueChanged.connect(self._sync_current_to_advanced)

    def _profile(self, name: str, widget: QWidget) -> QWidget:
        return self.panel.register_profile(name, widget)

    @staticmethod
    def _function_combo() -> QComboBox:
        combo = QComboBox()
        for function in Ad2WaveformFunction:
            combo.addItem(function.value, function.value)
        return combo

    @staticmethod
    def _set_function_options(combo: QComboBox, values: tuple[str, ...]) -> None:
        """Replace options with the exact functions reported by the connected device."""
        selected = combo.currentData()
        combo.blockSignals(True)
        try:
            combo.clear()
            for value in values:
                combo.addItem(value, value)
            combo.setCurrentIndex(combo.findData(selected) if selected in values else 0)
        finally:
            combo.blockSignals(False)

    def _build_single_page(self) -> None:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(4, 4, 4, 4)
        form.setVerticalSpacing(3)
        self.single_function = self._profile(
            f"{self.prefix}_single_function", self._function_combo()
        )
        frequency_name = "wave_frequency_hz" if self.channel_index == 0 else f"{self.prefix}_single_frequency_hz"
        amplitude_name = "wave_amplitude_v" if self.channel_index == 0 else f"{self.prefix}_single_amplitude_v"
        self.single_frequency = self._profile(frequency_name, double_spin(1000, 0.001))
        self.single_amplitude = self._profile(amplitude_name, double_spin(1, 0, 5, 4))
        self.single_offset = self._profile(
            f"{self.prefix}_single_offset_v", double_spin(0, -5, 5, 4)
        )
        for label, widget in (
            ("Type", self.single_function),
            ("Frequency (Hz)", self.single_frequency),
            ("Amplitude (V peak)", self.single_amplitude),
            ("Offset (V)", self.single_offset),
        ):
            form.addRow(label, widget)
        self.single_widgets = (
            self.single_function,
            self.single_frequency,
            self.single_amplitude,
            self.single_offset,
        )
        self.pages.addWidget(page)

    def _build_sweep_page(self) -> None:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(4, 4, 4, 4)
        form.setVerticalSpacing(3)
        self.sweep_function = self._profile(
            f"{self.prefix}_sweep_function", self._function_combo()
        )
        self.sweep_start = self._profile(
            f"{self.prefix}_sweep_start_hz", double_spin(900, 0, 100_000_000, 3)
        )
        self.sweep_stop = self._profile(
            f"{self.prefix}_sweep_stop_hz", double_spin(1100, 0.001, 100_000_000, 3)
        )
        self.sweep_time = self._profile(
            f"{self.prefix}_sweep_time_ms", double_spin(1, 0.001, 1_000_000, 4)
        )
        self.sweep_direction = self._profile(f"{self.prefix}_sweep_direction", QComboBox())
        self.sweep_direction.addItem("Bidirectional (Triangle)", "Triangle")
        self.sweep_direction.addItem("Unidirectional up", "RampUp")
        self.sweep_direction.addItem("Unidirectional down", "RampDown")
        self.sweep_offset = self._profile(
            f"{self.prefix}_sweep_offset_v", double_spin(0, -5, 5, 4)
        )
        for label, widget in (
            ("Carrier type", self.sweep_function),
            ("Frequency start (Hz)", self.sweep_start),
            ("Frequency stop (Hz)", self.sweep_stop),
            ("Sweep time (ms)", self.sweep_time),
            ("Direction", self.sweep_direction),
            ("Offset (V)", self.sweep_offset),
        ):
            form.addRow(label, widget)
        self.sweep_widgets = (
            self.sweep_function,
            self.sweep_start,
            self.sweep_stop,
            self.sweep_time,
            self.sweep_direction,
            self.sweep_offset,
        )
        self.pages.addWidget(page)

    def _build_advanced_page(self) -> None:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(3)
        advanced_tabs = QTabWidget()
        page_layout.addWidget(advanced_tabs)
        carrier, carrier_form = form_group("Carrier")
        self.adv_function = self._profile(f"{self.prefix}_function", self._function_combo())
        self.adv_frequency = self._profile(
            f"{self.prefix}_frequency_hz", double_spin(1000, 0.001, 100_000_000, 3)
        )
        self.adv_amplitude = self._profile(
            f"{self.prefix}_amplitude_v", double_spin(1, 0, 5, 4)
        )
        self.adv_offset = self._profile(f"{self.prefix}_offset_v", double_spin(0, -5, 5, 4))
        self.adv_symmetry = self._profile(
            f"{self.prefix}_symmetry_percent", double_spin(50, 0, 100, 3)
        )
        self.adv_phase = self._profile(
            f"{self.prefix}_phase_deg", double_spin(0, -360, 360, 3)
        )
        for label, widget in (
            ("Type", self.adv_function),
            ("Frequency (Hz)", self.adv_frequency),
            ("Amplitude (V peak)", self.adv_amplitude),
            ("Offset (V)", self.adv_offset),
            ("Symmetry (%)", self.adv_symmetry),
            ("Phase (°)", self.adv_phase),
        ):
            carrier_form.addRow(label, widget)
        advanced_tabs.addTab(carrier, "Carrier")

        modulation, modulation_form = form_group("FM modulation node")
        self.fm_enabled = self._profile(f"{self.prefix}_fm_enabled", QCheckBox())
        self.fm_function = self._profile(f"{self.prefix}_fm_function", self._function_combo())
        self.fm_frequency = self._profile(
            f"{self.prefix}_fm_frequency_hz", double_spin(1000, 0.001, 100_000_000, 3)
        )
        self.fm_index = self._profile(
            f"{self.prefix}_fm_index_percent", double_spin(0, 0, 100, 6)
        )
        self.fm_offset = self._profile(
            f"{self.prefix}_fm_offset_percent", double_spin(0, -100, 100, 4)
        )
        self.fm_symmetry = self._profile(
            f"{self.prefix}_fm_symmetry_percent", double_spin(50, 0, 100, 3)
        )
        self.fm_phase = self._profile(
            f"{self.prefix}_fm_phase_deg", double_spin(0, -360, 360, 3)
        )
        for label, widget in (
            ("Enabled", self.fm_enabled),
            ("Type", self.fm_function),
            ("Frequency (Hz)", self.fm_frequency),
            ("Modulation index (%)", self.fm_index),
            ("Offset (%)", self.fm_offset),
            ("Symmetry (%)", self.fm_symmetry),
            ("Phase (°)", self.fm_phase),
        ):
            modulation_form.addRow(label, widget)
        advanced_tabs.addTab(modulation, "FM modulation")
        self.pages.addWidget(page)

    def _mode_changed(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        self.pages.updateGeometry()
        self._sync_current_to_advanced()

    def _sync_current_to_advanced(self, *_args: object) -> None:
        if self._loading:
            return
        mode = self.mode.currentData()
        if mode == "single":
            self.adv_function.setCurrentIndex(
                self.adv_function.findData(self.single_function.currentData())
            )
            self.adv_frequency.setValue(self.single_frequency.value())
            self.adv_amplitude.setValue(self.single_amplitude.value())
            self.adv_offset.setValue(self.single_offset.value())
            self.fm_enabled.setChecked(False)
        elif mode == "sweep":
            start = self.sweep_start.value()
            stop = self.sweep_stop.value()
            if stop <= start:
                return
            center = (start + stop) / 2.0
            self.adv_function.setCurrentIndex(
                self.adv_function.findData(self.sweep_function.currentData())
            )
            self.adv_frequency.setValue(center)
            self.adv_offset.setValue(self.sweep_offset.value())
            self.fm_enabled.setChecked(True)
            self.fm_function.setCurrentIndex(
                self.fm_function.findData(self.sweep_direction.currentData())
            )
            self.fm_frequency.setValue(1000.0 / self.sweep_time.value())
            self.fm_index.setValue(((stop - start) / 2.0) / center * 100.0)
            self.fm_offset.setValue(0.0)
            self.fm_symmetry.setValue(
                50.0
                if self.sweep_direction.currentData() == Ad2WaveformFunction.TRIANGLE.value
                else 100.0
            )
            self.fm_phase.setValue(0.0)

    def arguments(self) -> Ad2WaveformChannelArgs:
        if self.mode.currentData() == "sweep" and self.sweep_stop.value() <= self.sweep_start.value():
            raise ValueError(f"CH{self.channel_index + 1} sweep stop must exceed sweep start")
        self._sync_current_to_advanced()
        return Ad2WaveformChannelArgs(
            channel_index=self.channel_index,
            enabled=self.enabled.isChecked(),
            function=Ad2WaveformFunction(self.adv_function.currentData()),
            frequency_hz=self.adv_frequency.value(),
            amplitude_v=self.adv_amplitude.value(),
            offset_v=self.adv_offset.value(),
            symmetry_percent=self.adv_symmetry.value(),
            phase_deg=self.adv_phase.value(),
            fm_enabled=self.fm_enabled.isChecked(),
            fm_function=Ad2WaveformFunction(self.fm_function.currentData()),
            fm_frequency_hz=self.fm_frequency.value(),
            fm_modulation_index_percent=self.fm_index.value(),
            fm_offset_percent=self.fm_offset.value(),
            fm_symmetry_percent=self.fm_symmetry.value(),
            fm_phase_deg=self.fm_phase.value(),
            idle_state=Ad2AnalogOutputIdle(self.idle.currentData()),
            trigger=self.panel._trigger_args(self.trigger),
        )

    def apply_readback(self, channel: Ad2WaveformChannelArgs) -> None:
        self._loading = True
        try:
            self.enabled.setChecked(channel.enabled)
            self.idle.setCurrentIndex(self.idle.findData(channel.idle_state.value))
            for combo, value in (
                (self.adv_function, channel.function.value),
                (self.single_function, channel.function.value),
                (self.sweep_function, channel.function.value),
                (self.fm_function, channel.fm_function.value),
            ):
                combo.setCurrentIndex(combo.findData(value))
            for widget, value in (
                (self.adv_frequency, channel.frequency_hz),
                (self.single_frequency, channel.frequency_hz),
                (self.adv_amplitude, channel.amplitude_v),
                (self.single_amplitude, channel.amplitude_v),
                (self.adv_offset, channel.offset_v),
                (self.single_offset, channel.offset_v),
                (self.sweep_offset, channel.offset_v),
                (self.adv_symmetry, channel.symmetry_percent),
                (self.adv_phase, channel.phase_deg),
                (self.fm_frequency, channel.fm_frequency_hz),
                (self.fm_index, channel.fm_modulation_index_percent),
                (self.fm_offset, channel.fm_offset_percent),
                (self.fm_symmetry, channel.fm_symmetry_percent),
                (self.fm_phase, channel.fm_phase_deg),
            ):
                widget.setValue(value)
            self.fm_enabled.setChecked(channel.fm_enabled)
            if channel.fm_enabled and channel.fm_frequency_hz > 0:
                deviation = channel.frequency_hz * channel.fm_modulation_index_percent / 100.0
                self.sweep_start.setValue(max(0.0, channel.frequency_hz - deviation))
                self.sweep_stop.setValue(channel.frequency_hz + deviation)
                self.sweep_time.setValue(1000.0 / channel.fm_frequency_hz)
                self.sweep_direction.setCurrentIndex(
                    self.sweep_direction.findData(channel.fm_function.value)
                )
            self.applied_label.setText(
                f"SDK applied: {channel.function.value}, {channel.frequency_hz:g} Hz, "
                f"{channel.amplitude_v:g} V peak, offset {channel.offset_v:g} V"
            )
        finally:
            self._loading = False

    def apply_capabilities(self, capabilities: Ad2WaveformChannelCapabilities) -> None:
        carrier = capabilities.carrier
        fm = capabilities.fm
        for combo in (self.single_function, self.sweep_function, self.adv_function):
            self._set_function_options(combo, carrier.functions)
        self._set_function_options(self.fm_function, fm.functions)
        sweep_functions = tuple(
            value
            for value in fm.functions
            if value
            in {
                Ad2WaveformFunction.TRIANGLE.value,
                Ad2WaveformFunction.RAMP_UP.value,
                Ad2WaveformFunction.RAMP_DOWN.value,
            }
        )
        self._set_function_options(self.sweep_direction, sweep_functions)
        for widget in (self.single_frequency, self.adv_frequency, self.sweep_start, self.sweep_stop):
            widget.setRange(carrier.frequency_hz.minimum, carrier.frequency_hz.maximum)
        for widget in (self.single_amplitude, self.adv_amplitude):
            widget.setRange(carrier.amplitude.minimum, carrier.amplitude.maximum)
        for widget in (self.single_offset, self.sweep_offset, self.adv_offset):
            widget.setRange(carrier.offset.minimum, carrier.offset.maximum)
        self.adv_symmetry.setRange(
            carrier.symmetry_percent.minimum, carrier.symmetry_percent.maximum
        )
        self.adv_phase.setRange(carrier.phase_deg.minimum, carrier.phase_deg.maximum)
        self.fm_frequency.setRange(fm.frequency_hz.minimum, fm.frequency_hz.maximum)
        self.fm_index.setRange(fm.amplitude.minimum, fm.amplitude.maximum)
        self.fm_offset.setRange(fm.offset.minimum, fm.offset.maximum)
        self.fm_symmetry.setRange(
            fm.symmetry_percent.minimum, fm.symmetry_percent.maximum
        )
        self.fm_phase.setRange(fm.phase_deg.minimum, fm.phase_deg.maximum)
        if fm.frequency_hz.minimum > 0 and fm.frequency_hz.maximum > 0:
            self.sweep_time.setRange(
                1000.0 / fm.frequency_hz.maximum,
                1000.0 / fm.frequency_hz.minimum,
            )
        self.trigger["wait"].setRange(
            capabilities.wait_s.minimum, capabilities.wait_s.maximum
        )
        self.trigger["run"].setRange(
            capabilities.run_s.minimum, capabilities.run_s.maximum
        )
        self.trigger["repeat"].setRange(
            capabilities.repeat_count.minimum, capabilities.repeat_count.maximum
        )


class Ad2Panel(DevicePanel):
    def __init__(self, parent=None) -> None:
        super().__init__(DeviceId.AD2, parent)
        self._applied_capabilities: Ad2Capabilities | None = None
        self.instrument_status_label = QLabel(
            "WFG: idle · Oscilloscope: idle · Digital output: idle"
        )
        self.instrument_status_label.setWordWrap(True)
        self.instrument_status_label.setStyleSheet("font-weight: 600;")
        # Place per-instrument state directly beneath the common AD2 header,
        # before transient notices and the instrument controls.
        self.layout.insertWidget(1, self.instrument_status_label)
        self.instrument_tabs = QTabWidget()
        self.instrument_tabs.setMinimumWidth(0)
        self.instrument_tabs.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored
        )
        # Keep the shared header/readback visible in a 960 px half-screen
        # window. Each instrument page is deliberately laid out within this
        # height; scope traces use their own resizable viewer.
        self.instrument_tabs.setMaximumHeight(636)
        self.layout.addWidget(self.instrument_tabs, 1)

        waveform_tab = QWidget()
        waveform_layout = QGridLayout(waveform_tab)
        waveform_layout.setContentsMargins(4, 4, 4, 4)
        waveform_layout.setSpacing(4)
        self.wave_channels = (
            WaveformChannelEditor(self, 0),
            WaveformChannelEditor(self, 1),
        )
        waveform_layout.addWidget(self.wave_channels[0], 0, 0)
        waveform_layout.addWidget(self.wave_channels[1], 0, 1)
        waveform_layout.setColumnStretch(0, 1)
        waveform_layout.setColumnStretch(1, 1)
        waveform_layout.addWidget(button_row(
            self.action_button("wave_config", "Configure", DeviceOperation.AD2_WAVEFORM_CONFIGURE, self._wave_args),
            self.action_button("wave_start", "Start", DeviceOperation.AD2_WAVEFORM_START),
            self.action_button("wave_stop", "Stop", DeviceOperation.AD2_WAVEFORM_STOP),
            self.action_button("wave_trigger_pc", "PC trigger", DeviceOperation.AD2_SOFTWARE_TRIGGER),
        ), 1, 0, 1, 2)
        self.instrument_tabs.addTab(waveform_tab, "Waveform generator")

        self.scope_controls = OscilloscopePanel(self)
        self.scope_plot = self.scope_controls.plot
        self.instrument_tabs.addTab(self.scope_controls, "Oscilloscope")

        digital_tab = QWidget()
        digital_layout = QGridLayout(digital_tab)
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
            self.action_button("do_trigger_pc", "PC trigger", DeviceOperation.AD2_SOFTWARE_TRIGGER),
        ))
        digital_layout.addWidget(group, 0, 0)
        trigger_group, trigger_form = form_group("Trigger")
        self.do_trigger = self._add_trigger_controls("do", trigger_form)
        digital_layout.addWidget(trigger_group, 0, 1)
        digital_layout.setColumnStretch(0, 1)
        digital_layout.setColumnStretch(1, 1)
        digital_layout.setRowStretch(1, 1)
        self.instrument_tabs.addTab(digital_tab, "Digital output")

        self.readback_label = QLabel("No readback")
        self.readback_label.setWordWrap(True)
        self.readback_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.layout.addWidget(self.readback_label)
        self.finish_layout()

    def _add_trigger_controls(
        self, prefix: str, form: QFormLayout
    ) -> dict[str, QWidget]:
        source = self.register_profile(f"{prefix}_trigger_source", QComboBox())
        for trigger_source in Ad2TriggerSource:
            source.addItem(trigger_source.value, trigger_source.value)
        wait = self.register_profile(f"{prefix}_trigger_wait_s", double_spin(0, 0, 1_000_000))
        run = self.register_profile(f"{prefix}_trigger_run_s", double_spin(0, 0, 1_000_000))
        repeat = self.register_profile(f"{prefix}_trigger_repeat_count", int_spin(0, 0, 1_000_000))
        retrigger = self.register_profile(f"{prefix}_trigger_repeat", QCheckBox())
        for label, widget in (
            ("Source", source),
            ("Wait (s)", wait),
            ("Run (s)", run),
            ("Repeat count", repeat),
            ("Retrigger each repeat", retrigger),
        ):
            form.addRow(label, widget)
        return {
            "source": source,
            "wait": wait,
            "run": run,
            "repeat": repeat,
            "retrigger": retrigger,
        }

    @staticmethod
    def _trigger_args(controls: dict[str, QWidget]) -> Ad2TriggerSettingsArgs:
        return Ad2TriggerSettingsArgs(
            source=Ad2TriggerSource(controls["source"].currentData()),
            wait_s=controls["wait"].value(),
            run_s=controls["run"].value(),
            repeat_count=controls["repeat"].value(),
            repeat_trigger=controls["retrigger"].isChecked(),
        )

    def _wave_args(self) -> Ad2ConfigureWaveformArgs:
        return Ad2ConfigureWaveformArgs(
            channels=tuple(editor.arguments() for editor in self.wave_channels)
        )

    def _scope_args(self) -> Ad2ConfigureScopeArgs:
        return self.scope_controls.arguments()

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
            trigger=self._trigger_args(self.do_trigger),
        )

    def _validate_profile_values(self, values: dict[str, object]) -> None:
        self.scope_controls.validate_profile_values(values)
        bits = "".join(str(values["do_bits"]).split())
        if any(bit not in "01" for bit in bits):
            raise ValueError("do_bits may contain only 0 and 1")
        if values["do_type"] == Ad2DigitalOutputType.CUSTOM.value and not bits:
            raise ValueError("do_bits must not be empty for custom digital output")
        for prefix in ("wave", "do"):
            Ad2TriggerSettingsArgs(
                source=Ad2TriggerSource(values[f"{prefix}_trigger_source"]),
                wait_s=float(values[f"{prefix}_trigger_wait_s"]),
                run_s=float(values[f"{prefix}_trigger_run_s"]),
                repeat_count=int(values[f"{prefix}_trigger_repeat_count"]),
                repeat_trigger=bool(values[f"{prefix}_trigger_repeat"]),
            )
        for channel in (1, 2):
            prefix = f"wave_ch{channel}"
            if values[f"{prefix}_mode"] == "sweep":
                if float(values[f"{prefix}_sweep_stop_hz"]) <= float(
                    values[f"{prefix}_sweep_start_hz"]
                ):
                    raise ValueError(f"CH{channel} sweep stop must exceed sweep start")

    def update_readback(self, readback: object) -> None:
        if readback is not None:
            capabilities = getattr(readback, "capabilities", None)
            if (
                isinstance(capabilities, Ad2Capabilities)
                and capabilities is not self._applied_capabilities
            ):
                self._apply_capabilities(capabilities)
                self._applied_capabilities = capabilities
            channels = getattr(readback, "waveform_channels", ())
            channel_text = ", ".join(
                f"CH{channel.channel_index + 1} "
                f"{'on' if channel.enabled else 'off'} "
                f"{channel.frequency_hz:g} Hz/{channel.amplitude_v:g} V"
                for channel in channels
            ) or "not configured"
            wfg_state = (
                "running"
                if getattr(readback, "waveform_running", False)
                else "configured"
                if channels
                else "idle"
            )
            digital_state = (
                "running"
                if getattr(readback, "digital_output_running", False)
                else "configured"
                if getattr(readback, "digital_output_configured", False)
                else "idle"
            )
            self.instrument_status_label.setText(
                f"WFG: {wfg_state} · "
                f"Oscilloscope: {getattr(readback, 'scope_state', 'idle')} · "
                f"Digital output: {digital_state}"
            )
            self.readback_label.setText(f"WFG configuration: {channel_text}")

    def _apply_capabilities(self, capabilities: Ad2Capabilities) -> None:
        by_channel = {
            channel.channel_index: channel
            for channel in capabilities.waveform_channels
        }
        for editor in self.wave_channels:
            editor.apply_capabilities(by_channel[editor.channel_index])
        self.scope_controls.apply_capabilities(capabilities.scope)
        digital = capabilities.digital_output
        self.do_channel.setRange(0, max(0, digital.channel_count - 1))
        self.do_clock.setRange(
            digital.clock_frequency_hz.minimum,
            digital.clock_frequency_hz.maximum,
        )
        self.do_high.setRange(
            digital.counter_bits.minimum, digital.counter_bits.maximum
        )
        self.do_low.setRange(
            digital.counter_bits.minimum, digital.counter_bits.maximum
        )
        self.do_bits.setMaxLength(digital.custom_data_bits_max)
        self.do_trigger["wait"].setRange(
            digital.wait_s.minimum, digital.wait_s.maximum
        )
        self.do_trigger["run"].setRange(
            digital.run_s.minimum, digital.run_s.maximum
        )
        self.do_trigger["repeat"].setRange(
            digital.repeat_count.minimum, digital.repeat_count.maximum
        )

    def handle_result(self, result: object) -> None:
        if self.scope_controls.handle_result(result):
            return
        if isinstance(result, Ad2WaveformAppliedResult):
            for channel in result.channels:
                self.wave_channels[channel.channel_index].apply_readback(channel)
                self._apply_trigger(self.wave_channels[channel.channel_index].trigger, channel.trigger)

    def apply_successful_command(self, command: DeviceCommand | None) -> None:
        if command is None:
            return
        args = command.arguments
        if isinstance(args, Ad2ConfigureScopeArgs):
            self.scope_controls.timeout.setValue(args.timeout_s)
        elif isinstance(args, Ad2ConfigureDigitalOutputArgs):
            self.do_channel.setValue(args.channel_index)
            self.do_enabled.setChecked(args.enabled)
            self.do_type.setCurrentIndex(self.do_type.findData(args.output_type.value))
            self.do_clock_enabled.setChecked(args.clock_frequency_hz is not None)
            if args.clock_frequency_hz is not None:
                self.do_clock.setValue(args.clock_frequency_hz)
            self.do_high.setValue(args.counter_high_bits)
            self.do_low.setValue(args.counter_low_bits)
            self.do_start_high.setChecked(args.start_high)
            self.do_bits.setText("".join(str(bit) for bit in args.bits))
            self.do_frames_enabled.setChecked(args.frame_count is not None)
            if args.frame_count is not None:
                self.do_frames.setValue(args.frame_count)
            self._apply_trigger(self.do_trigger, args.trigger)

    @staticmethod
    def _apply_trigger(controls: dict[str, QWidget], trigger: Ad2TriggerSettingsArgs) -> None:
        controls["source"].setCurrentIndex(controls["source"].findData(trigger.source.value))
        controls["wait"].setValue(trigger.wait_s)
        controls["run"].setValue(trigger.run_s)
        controls["repeat"].setValue(trigger.repeat_count)
        controls["retrigger"].setChecked(trigger.repeat_trigger)


class PumpPanel(DevicePanel):
    def __init__(self, parent=None) -> None:
        super().__init__(DeviceId.PUMP, parent)
        controls = QWidget()
        controls_layout = QGridLayout(controls)
        self.layout.addWidget(controls)
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
        controls_layout.addWidget(group, 0, 0)

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
        controls_layout.addWidget(group, 0, 1)

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
        controls_layout.addWidget(group, 1, 0, 1, 2)
        for column in range(2):
            controls_layout.setColumnStretch(column, 1)
        self.readback_label = QLabel("No readback")
        self.readback_label.setWordWrap(True)
        self.readback_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
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

    def apply_successful_command(self, command: DeviceCommand | None) -> None:
        if command is None:
            return
        args = command.arguments
        if isinstance(args, PumpSetFlowArgs):
            self.flow.setValue(args.flow_ul_min)
        elif isinstance(args, PumpSetFillLevelArgs):
            self.fill_level.setValue(args.fill_level_ml)
            self.fill_flow_enabled.setChecked(args.flow_rate_ul_min is not None)
            if args.flow_rate_ul_min is not None:
                self.fill_flow.setValue(args.flow_rate_ul_min)
        elif isinstance(args, PumpMoveArgs):
            self.move_flow_enabled.setChecked(args.flow_rate_ul_min is not None)
            if args.flow_rate_ul_min is not None:
                self.move_flow.setValue(args.flow_rate_ul_min)
            self.move_timeout.setValue(args.timeout_s)
            self.move_poll.setValue(args.poll_interval_s)
        elif isinstance(args, PumpReferenceMoveArgs):
            self.reference_timeout.setValue(args.timeout_s)
            self.reference_poll.setValue(args.poll_interval_s)
        elif isinstance(args, PumpConfigureFlowUnitArgs):
            self.flow_unit.setCurrentIndex(self.flow_unit.findData(args.unit.value))
        elif isinstance(args, PumpConfigureSyringeArgs):
            if args.preset is not None:
                self.syringe_mode.setCurrentIndex(self.syringe_mode.findData(args.preset.value))
            else:
                self.syringe_mode.setCurrentIndex(self.syringe_mode.findData("custom"))
                if args.inner_diameter_mm is not None:
                    self.syringe_diameter.setValue(args.inner_diameter_mm)
                if args.max_piston_stroke_mm is not None:
                    self.syringe_stroke.setValue(args.max_piston_stroke_mm)


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
        self.readback_label.setWordWrap(True)
        self.readback_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
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

    def apply_successful_command(self, command: DeviceCommand | None) -> None:
        if command is None:
            return
        args = command.arguments
        if isinstance(args, ValveSetPositionArgs):
            self.position.setValue(args.position)
        elif isinstance(args, ValveWaitReadyArgs):
            self.wait_timeout.setValue(args.timeout_s)
            self.wait_poll.setValue(args.poll_interval_s)


class CameraPanel(DevicePanel):
    def __init__(self, parent=None) -> None:
        super().__init__(DeviceId.CAMERA, parent)
        controls = QWidget()
        controls_layout = QGridLayout(controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setVerticalSpacing(2)
        self.layout.addWidget(controls, 1)
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
        controls_layout.addWidget(group, 0, 0)

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
        controls_layout.addWidget(group, 1, 0)

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
        controls_layout.addWidget(group, 2, 0)

        group, form = form_group("Sequence trigger")
        self.trigger_enabled = self.register_profile("trigger_enabled", QCheckBox())
        self.trigger_source = self.register_profile("trigger_source", QComboBox())
        for value in CameraTriggerSource:
            self.trigger_source.addItem(value.value, value.value)
        self.trigger_polarity = self.register_profile("trigger_polarity", QComboBox())
        for value in CameraTriggerPolarity:
            self.trigger_polarity.addItem(value.value, value.value)
        self.trigger_active = self.register_profile("trigger_active", QComboBox())
        for value in CameraTriggerActive:
            self.trigger_active.addItem(value.value, value.value)
        self.trigger_times = self.register_profile("trigger_times", int_spin(1, 1, 10_000))
        self.trigger_delay = self.register_profile(
            "trigger_delay_s", double_spin(0, 0, 10.000002, 6)
        )
        for label, widget in (
            ("Apply trigger settings", self.trigger_enabled),
            ("Source", self.trigger_source),
            ("Polarity", self.trigger_polarity),
            ("Active", self.trigger_active),
            ("Times", self.trigger_times),
            ("Delay (s)", self.trigger_delay),
        ):
            form.addRow(label, widget)
        controls_layout.addWidget(group, 0, 1)

        group, form = form_group("Master pulse")
        self.masterpulse_mode = self.register_profile("masterpulse_mode", QComboBox())
        for value in CameraMasterPulseMode:
            self.masterpulse_mode.addItem(value.value, value.value)
        self.masterpulse_source = self.register_profile("masterpulse_source", QComboBox())
        for value in CameraMasterPulseSource:
            self.masterpulse_source.addItem(value.value, value.value)
        self.masterpulse_interval = self.register_profile(
            "masterpulse_interval_s", double_spin(0.01, 0.000005, 10, 6)
        )
        self.masterpulse_burst = self.register_profile(
            "masterpulse_burst_times", int_spin(1, 1, 65_535)
        )
        self.global_exposure_enabled = self.register_profile(
            "global_exposure_enabled", QCheckBox()
        )
        self.global_exposure = self.register_profile("global_exposure", QCheckBox())
        for label, widget in (
            ("Mode", self.masterpulse_mode),
            ("Source", self.masterpulse_source),
            ("Interval (s)", self.masterpulse_interval),
            ("Burst times", self.masterpulse_burst),
            ("Set global exposure", self.global_exposure_enabled),
            ("Global exposure", self.global_exposure),
        ):
            form.addRow(label, widget)
        controls_layout.addWidget(group, 1, 1)

        self.preview = CameraPreview()
        controls_layout.addWidget(self.preview, 2, 1)
        controls_layout.setColumnStretch(0, 1)
        controls_layout.setColumnStretch(1, 1)
        self.readback_label = QLabel("No readback")
        self.readback_label.setWordWrap(True)
        self.readback_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.layout.addWidget(self.readback_label)
        self.finish_layout()

    def _snapshot_args(self) -> CameraConfigureSnapshotArgs:
        return CameraConfigureSnapshotArgs(
            self.snapshot_exposure.value() if self.snapshot_exposure_enabled.isChecked() else None
        )

    def _sequence_args(self) -> CameraConfigureSequenceArgs:
        trigger = None
        if self.trigger_enabled.isChecked():
            trigger = CameraSequenceTriggerArgs(
                source=CameraTriggerSource(self.trigger_source.currentData()),
                polarity=CameraTriggerPolarity(self.trigger_polarity.currentData()),
                active=CameraTriggerActive(self.trigger_active.currentData()),
                trigger_times=self.trigger_times.value(),
                delay_s=self.trigger_delay.value(),
                masterpulse_mode=CameraMasterPulseMode(self.masterpulse_mode.currentData()),
                masterpulse_source=CameraMasterPulseSource(
                    self.masterpulse_source.currentData()
                ),
                masterpulse_interval_s=self.masterpulse_interval.value(),
                masterpulse_burst_times=self.masterpulse_burst.value(),
                global_exposure=(
                    self.global_exposure.isChecked()
                    if self.global_exposure_enabled.isChecked()
                    else None
                ),
            )
        return CameraConfigureSequenceArgs(
            self.sequence_frames.value(),
            self.sequence_exposure.value() if self.sequence_exposure_enabled.isChecked() else None,
            self.frame_timeout.value(), self.frame_poll.value(),
            trigger,
        )

    def _roi_args(self) -> CameraConfigureRoiArgs:
        return CameraConfigureRoiArgs(
            self.roi_x.value(), self.roi_y.value(), self.roi_width.value(), self.roi_height.value()
        )

    def _validate_profile_values(self, values: dict[str, object]) -> None:
        trigger = None
        if values["trigger_enabled"]:
            trigger = CameraSequenceTriggerArgs(
                source=CameraTriggerSource(values["trigger_source"]),
                polarity=CameraTriggerPolarity(values["trigger_polarity"]),
                active=CameraTriggerActive(values["trigger_active"]),
                trigger_times=int(values["trigger_times"]),
                delay_s=float(values["trigger_delay_s"]),
                masterpulse_mode=CameraMasterPulseMode(values["masterpulse_mode"]),
                masterpulse_source=CameraMasterPulseSource(values["masterpulse_source"]),
                masterpulse_interval_s=float(values["masterpulse_interval_s"]),
                masterpulse_burst_times=int(values["masterpulse_burst_times"]),
                global_exposure=(
                    bool(values["global_exposure"])
                    if values["global_exposure_enabled"]
                    else None
                ),
            )
        CameraConfigureSequenceArgs(
            int(values["sequence_frames"]),
            float(values["sequence_exposure_ms"]) if values["sequence_exposure_enabled"] else None,
            float(values["frame_timeout_s"]), float(values["frame_poll_s"]),
            trigger,
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

    def apply_successful_command(self, command: DeviceCommand | None) -> None:
        if command is None:
            return
        args = command.arguments
        if isinstance(args, CameraConfigureSnapshotArgs):
            self.snapshot_exposure_enabled.setChecked(args.exposure_ms is not None)
            if args.exposure_ms is not None:
                self.snapshot_exposure.setValue(args.exposure_ms)
        elif isinstance(args, CameraConfigureExposureArgs):
            self.exposure.setValue(args.exposure_ms)
        elif isinstance(args, CameraConfigureRoiArgs):
            self.roi_x.setValue(args.horizontal_offset)
            self.roi_y.setValue(args.vertical_offset)
            self.roi_width.setValue(args.horizontal_size)
            self.roi_height.setValue(args.vertical_size)
        elif isinstance(args, CameraConfigureSequenceArgs):
            self.sequence_frames.setValue(args.frame_count)
            self.sequence_exposure_enabled.setChecked(args.exposure_ms is not None)
            if args.exposure_ms is not None:
                self.sequence_exposure.setValue(args.exposure_ms)
            self.frame_timeout.setValue(args.frame_timeout_s)
            self.frame_poll.setValue(args.poll_interval_s)
            trigger = args.trigger
            self.trigger_enabled.setChecked(trigger is not None)
            if trigger is not None:
                self.trigger_source.setCurrentIndex(self.trigger_source.findData(trigger.source.value))
                self.trigger_polarity.setCurrentIndex(self.trigger_polarity.findData(trigger.polarity.value))
                self.trigger_active.setCurrentIndex(self.trigger_active.findData(trigger.active.value))
                self.trigger_times.setValue(trigger.trigger_times)
                self.trigger_delay.setValue(trigger.delay_s)
                self.masterpulse_mode.setCurrentIndex(self.masterpulse_mode.findData(trigger.masterpulse_mode.value))
                self.masterpulse_source.setCurrentIndex(self.masterpulse_source.findData(trigger.masterpulse_source.value))
                self.masterpulse_interval.setValue(trigger.masterpulse_interval_s)
                self.masterpulse_burst.setValue(trigger.masterpulse_burst_times)
                self.global_exposure_enabled.setChecked(trigger.global_exposure is not None)
                if trigger.global_exposure is not None:
                    self.global_exposure.setChecked(trigger.global_exposure)


class TecPanel(DevicePanel):
    def __init__(self, parent=None) -> None:
        super().__init__(DeviceId.TEC, parent)
        controls = QWidget()
        controls_layout = QGridLayout(controls)
        self.layout.addWidget(controls)
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
        controls_layout.addWidget(group, 0, 0)
        self.table = QTableWidget(2, 6)
        self.table.setHorizontalHeaderLabels(("Channel", "Current °C", "Target °C", "Output", "Ready", "Fault"))
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        controls_layout.addWidget(self.table, 0, 1)
        controls_layout.setColumnStretch(0, 1)
        controls_layout.setColumnStretch(1, 2)
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

    def apply_successful_command(self, command: DeviceCommand | None) -> None:
        if command is None:
            return
        args = command.arguments
        if isinstance(args, (TecApplySetpointsArgs, TecWaitStableArgs)):
            targets = args.target_temperature_c
            if isinstance(targets, dict):
                self.target_mode.setCurrentIndex(self.target_mode.findData("per_channel"))
                if 1 in targets:
                    self.target_1.setValue(targets[1])
                if 2 in targets:
                    self.target_2.setValue(targets[2])
            else:
                self.target_mode.setCurrentIndex(self.target_mode.findData("broadcast"))
                self.target.setValue(targets)
            if isinstance(args, TecWaitStableArgs):
                self.tolerance.setValue(args.tolerance_c)
                self.settle.setValue(args.min_settle_s)
                self.max_wait.setValue(args.max_wait_s)
                self.poll.setValue(args.poll_interval_s)

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
        self.readback_label.setWordWrap(True)
        self.readback_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.layout.addWidget(self.readback_label)
        self.finish_layout()

    def update_readback(self, readback: object) -> None:
        if readback is not None:
            self.readback_label.setText(str(readback))

    def apply_successful_command(self, command: DeviceCommand | None) -> None:
        if command is not None and isinstance(command.arguments, ZStageSetPositionArgs):
            self.position.setValue(command.arguments.position_um)


PANEL_TYPES = {
    DeviceId.AD2: Ad2Panel,
    DeviceId.PUMP: PumpPanel,
    DeviceId.VALVE: ValvePanel,
    DeviceId.CAMERA: CameraPanel,
    DeviceId.TEC: TecPanel,
    DeviceId.Z_STAGE: ZStagePanel,
}
