from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QSpinBox,
    QWidget,
)

from ..application.commands import (
    Ad2ConfigureScopeArgs,
    Ad2ScopeAppliedResult,
    Ad2ScopeChannelArgs,
    Ad2ScopeReadResult,
    Ad2ScopeTriggerArgs,
    Ad2ScopeTriggerCondition,
    Ad2ScopeTriggerFilter,
    Ad2ScopeTriggerLengthCondition,
    Ad2ScopeTriggerType,
    Ad2TriggerSource,
    DeviceOperation,
)
from ..domain.models import Ad2ScopeCapabilities
from .widgets import ScopePlotWindow


def _double_spin(
    value: float, minimum: float, maximum: float, decimals: int
) -> QDoubleSpinBox:
    widget = QDoubleSpinBox()
    widget.setDecimals(decimals)
    widget.setRange(minimum, maximum)
    widget.setValue(value)
    return widget


def _int_spin(value: int, minimum: int, maximum: int = 10_000_000) -> QSpinBox:
    widget = QSpinBox()
    widget.setRange(minimum, maximum)
    widget.setValue(value)
    return widget


def _range_combo() -> QComboBox:
    widget = QComboBox()
    for value in (0.5, 1.0, 2.0, 5.0, 10.0, 25.0, 50.0):
        widget.addItem(f"{value:g}", value)
    widget.setCurrentIndex(widget.findData(5.0))
    return widget


def _button_row(*buttons: QPushButton) -> QWidget:
    widget = QWidget()
    layout = QGridLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    for index, button in enumerate(buttons):
        layout.addWidget(button, index // 4, index % 4)
    return widget


def _form_group(title: str) -> tuple[QGroupBox, QFormLayout]:
    group = QGroupBox(title)
    form = QFormLayout(group)
    form.setContentsMargins(6, 6, 6, 6)
    form.setVerticalSpacing(3)
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    return group, form


class OscilloscopePanel(QWidget):
    """Reusable AD2 oscilloscope editor; application commands remain typed."""

    POLL_INTERVAL_S = 0.01

    def __init__(self, device_panel, parent=None) -> None:
        super().__init__(parent)
        self.device_panel = device_panel
        layout = QGridLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        acquisition, form = _form_group("Acquisition (shared by CH1 and CH2)")
        self.sample_count = self._profile("scope_sample_count", _int_spin(1000, 1))
        self.sample_rate = self._profile(
            "scope_sample_frequency_hz", _double_spin(100_000_000, 0.001, 100_000_000, 3)
        )
        self.pretrigger_samples = self._profile(
            "scope_pretrigger_samples", _int_spin(0, 0)
        )
        self.timeout = self._profile(
            "scope_timeout_s", _double_spin(5, 0.001, 3600, 3)
        )
        self.trigger_source = self._profile("scope_trigger", QComboBox())
        for source in Ad2TriggerSource:
            self.trigger_source.addItem(source.value, source.value)
        self.trigger_source.setCurrentIndex(
            self.trigger_source.findData(Ad2TriggerSource.DETECTOR_ANALOG_IN.value)
        )
        for label, widget in (
            ("Sample count", self.sample_count),
            ("Sample rate (Hz)", self.sample_rate),
            ("Pre-trigger samples", self.pretrigger_samples),
            ("Capture timeout (s)", self.timeout),
            ("Trigger source", self.trigger_source),
        ):
            form.addRow(label, widget)
        layout.addWidget(acquisition, 0, 0)

        channels = QGroupBox("Input channels")
        channel_layout = QGridLayout(channels)
        channel_layout.addWidget(QLabel("Enabled"), 0, 1)
        channel_layout.addWidget(QLabel("Range (V)"), 0, 2)
        channel_layout.addWidget(QLabel("Offset (V)"), 0, 3)
        self.channel_enabled: list[QCheckBox] = []
        self.channel_range: list[QComboBox] = []
        self.channel_offset: list[QDoubleSpinBox] = []
        for index in range(2):
            prefix = f"scope_ch{index + 1}"
            enabled = self._profile(f"{prefix}_enabled", QCheckBox())
            enabled.setChecked(index == 0)
            range_v = self._profile(f"{prefix}_range_v", _range_combo())
            offset_v = self._profile(
                f"{prefix}_offset_v", _double_spin(0, -50, 50, 3)
            )
            self.channel_enabled.append(enabled)
            self.channel_range.append(range_v)
            self.channel_offset.append(offset_v)
            channel_layout.addWidget(QLabel(f"CH{index + 1}"), index + 1, 0)
            channel_layout.addWidget(enabled, index + 1, 1)
            channel_layout.addWidget(range_v, index + 1, 2)
            channel_layout.addWidget(offset_v, index + 1, 3)
        channel_layout.setRowStretch(3, 1)
        layout.addWidget(channels, 0, 1)

        detector = QGroupBox("Analog detector trigger")
        detector_layout = QGridLayout(detector)
        detector_layout.setContentsMargins(6, 6, 6, 6)
        detector_layout.setVerticalSpacing(3)
        self.trigger_channel = self._profile("scope_trigger_channel", QComboBox())
        self.trigger_channel.addItem("CH1", "0")
        self.trigger_channel.addItem("CH2", "1")
        self.trigger_condition = self._enum_combo(
            "scope_trigger_condition", Ad2ScopeTriggerCondition
        )
        self.trigger_filter = self._enum_combo("scope_trigger_filter", Ad2ScopeTriggerFilter)
        self.trigger_level = self._profile(
            "scope_trigger_level_v", _double_spin(0, -50, 50, 4)
        )
        self.trigger_hysteresis = self._profile(
            "scope_trigger_hysteresis_v", _double_spin(0.1, 0, 50, 4)
        )
        self.trigger_holdoff = self._profile(
            "scope_trigger_holdoff_s", _double_spin(0, 0, 3600, 6)
        )
        self.trigger_auto_timeout = self._profile(
            "scope_trigger_auto_timeout_s", _double_spin(0, 0, 3600, 3)
        )
        self.detector_widgets = (
            self.trigger_channel,
            self.trigger_condition,
            self.trigger_filter,
            self.trigger_level,
            self.trigger_hysteresis,
            self.trigger_holdoff,
            self.trigger_auto_timeout,
        )
        detector_fields = (
            ("Detector channel", self.trigger_channel),
            ("Condition", self.trigger_condition),
            ("Filter", self.trigger_filter),
            ("Level (V)", self.trigger_level),
            ("Hysteresis (V)", self.trigger_hysteresis),
            ("Holdoff (s)", self.trigger_holdoff),
            ("Auto timeout (s)", self.trigger_auto_timeout),
        )
        for index, (label, widget) in enumerate(detector_fields):
            section = index // 4
            row = index % 4
            detector_layout.addWidget(QLabel(label), row, section * 2)
            detector_layout.addWidget(widget, row, section * 2 + 1)
        detector_layout.setColumnStretch(1, 1)
        detector_layout.setColumnStretch(3, 1)
        layout.addWidget(detector, 1, 0, 1, 2)

        self.plot_window = ScopePlotWindow(self)
        self.plot = self.plot_window.plot
        self.applied_label = QLabel("No scope configuration applied")
        self.applied_label.setWordWrap(True)
        open_plot = QPushButton("Open plot")
        open_plot.clicked.connect(self.plot_window.show)
        layout.addWidget(
            _button_row(
                device_panel.action_button(
                    "scope_config",
                    "Configure",
                    DeviceOperation.AD2_SCOPE_CONFIGURE,
                    self.arguments,
                ),
                device_panel.action_button(
                    "scope_trigger_pc", "PC trigger", DeviceOperation.AD2_SOFTWARE_TRIGGER
                ),
                device_panel.action_button(
                    "scope_read", "Read / capture", DeviceOperation.AD2_SCOPE_READ
                ),
                open_plot,
            ),
            2,
            0,
            1,
            2,
        )
        layout.addWidget(self.applied_label, 3, 0, 1, 2)
        for column in range(2):
            layout.setColumnStretch(column, 1)
        layout.setRowStretch(4, 1)

        self.trigger_source.currentIndexChanged.connect(self._source_changed)
        self.sample_count.valueChanged.connect(self._count_changed)
        self._count_changed(self.sample_count.value())
        self._source_changed()

    def _profile(self, name: str, widget):
        return self.device_panel.register_profile(name, widget)

    def _enum_combo(self, name: str, enum_type) -> QComboBox:
        combo = self._profile(name, QComboBox())
        for value in enum_type:
            combo.addItem(value.value, value.value)
        return combo

    def _count_changed(self, count: int) -> None:
        self.pretrigger_samples.setMaximum(max(0, count - 1))

    def _source_changed(self, *_args: object) -> None:
        enabled = self.trigger_source.currentData() == Ad2TriggerSource.DETECTOR_ANALOG_IN.value
        for widget in self.detector_widgets:
            widget.setEnabled(enabled)

    def arguments(self) -> Ad2ConfigureScopeArgs:
        channels = tuple(
            Ad2ScopeChannelArgs(
                index,
                float(self.channel_range[index].currentData()),
                self.channel_offset[index].value(),
            )
            for index in range(2)
            if self.channel_enabled[index].isChecked()
        )
        if not channels:
            raise ValueError("Choose at least one scope channel")
        trigger = Ad2ScopeTriggerArgs(
            source=Ad2TriggerSource(self.trigger_source.currentData()),
            channel_index=int(self.trigger_channel.currentData()),
            trigger_type=Ad2ScopeTriggerType.EDGE,
            condition=Ad2ScopeTriggerCondition(self.trigger_condition.currentData()),
            filter=Ad2ScopeTriggerFilter(self.trigger_filter.currentData()),
            level_v=self.trigger_level.value(),
            hysteresis_v=self.trigger_hysteresis.value(),
            length_condition=Ad2ScopeTriggerLengthCondition.MORE,
            length_s=0.0,
            holdoff_s=self.trigger_holdoff.value(),
            auto_timeout_s=self.trigger_auto_timeout.value(),
        )
        return Ad2ConfigureScopeArgs(
            sample_count=self.sample_count.value(),
            channels=channels,
            sample_frequency_hz=self.sample_rate.value(),
            pretrigger_samples=self.pretrigger_samples.value(),
            timeout_s=self.timeout.value(),
            poll_interval_s=self.POLL_INTERVAL_S,
            trigger=trigger,
        )

    @staticmethod
    def validate_profile_values(values: dict[str, object]) -> None:
        if not values["scope_ch1_enabled"] and not values["scope_ch2_enabled"]:
            raise ValueError("Choose at least one scope channel")
        if int(values["scope_pretrigger_samples"]) >= int(values["scope_sample_count"]):
            raise ValueError("scope_pretrigger_samples must be less than scope_sample_count")
        if OscilloscopePanel.POLL_INTERVAL_S > float(values["scope_timeout_s"]):
            raise ValueError("scope_timeout_s must be at least 0.01 seconds")

    def apply_capabilities(self, capabilities: Ad2ScopeCapabilities) -> None:
        self.sample_count.setRange(
            capabilities.sample_count.minimum, capabilities.sample_count.maximum
        )
        self.sample_rate.setRange(
            capabilities.sample_frequency_hz.minimum,
            capabilities.sample_frequency_hz.maximum,
        )
        self.sample_rate.setValue(capabilities.sample_frequency_hz.maximum)
        self.trigger_channel.clear()
        for index in range(
            capabilities.trigger_channel.minimum,
            capabilities.trigger_channel.maximum + 1,
        ):
            self.trigger_channel.addItem(f"CH{index + 1}", str(index))
        for combo in self.channel_range:
            previous = combo.currentData()
            combo.clear()
            for value in capabilities.input_ranges_v:
                combo.addItem(f"{value:g}", value)
            selected = combo.findData(previous)
            if selected < 0:
                selected = combo.findData(5.0)
            combo.setCurrentIndex(max(0, selected))
        for widget in self.channel_offset:
            widget.setRange(
                capabilities.input_offset_v.minimum,
                capabilities.input_offset_v.maximum,
            )
        for widget, limits in (
            (self.trigger_level, capabilities.trigger_level_v),
            (self.trigger_hysteresis, capabilities.trigger_hysteresis_v),
            (self.trigger_holdoff, capabilities.trigger_holdoff_s),
            (self.trigger_auto_timeout, capabilities.trigger_auto_timeout_s),
        ):
            widget.setRange(limits.minimum, limits.maximum)
            if limits.step is not None and limits.step > 0:
                widget.setSingleStep(limits.step)

    def handle_result(self, result: object) -> bool:
        if isinstance(result, Ad2ScopeReadResult):
            self.plot_window.set_samples(result.samples_by_channel, self.sample_rate.value())
            self.plot_window.show()
            return True
        if not isinstance(result, Ad2ScopeAppliedResult):
            return False
        self.sample_count.setValue(result.sample_count)
        self.sample_rate.setValue(result.sample_frequency_hz)
        self.pretrigger_samples.setValue(result.pretrigger_samples)
        for index in range(2):
            channel = next((item for item in result.channels if item.channel_index == index), None)
            self.channel_enabled[index].setChecked(channel is not None)
            if channel is not None:
                selected = self.channel_range[index].findData(channel.range_v)
                if selected >= 0:
                    self.channel_range[index].setCurrentIndex(selected)
                self.channel_offset[index].setValue(channel.offset_v)
        trigger = result.trigger
        for combo, value in (
            (self.trigger_source, trigger.source.value),
            (self.trigger_channel, str(trigger.channel_index)),
            (self.trigger_condition, trigger.condition.value),
            (self.trigger_filter, trigger.filter.value),
        ):
            combo.setCurrentIndex(combo.findData(value))
        for widget, value in (
            (self.trigger_level, trigger.level_v),
            (self.trigger_hysteresis, trigger.hysteresis_v),
            (self.trigger_holdoff, trigger.holdoff_s),
            (self.trigger_auto_timeout, trigger.auto_timeout_s),
        ):
            widget.setValue(value)
        self.applied_label.setText(
            f"SDK applied: {result.sample_count} samples at {result.sample_frequency_hz:g} Hz · "
            f"{result.pretrigger_samples} pre-trigger · {trigger.source.value}"
        )
        return True
