from __future__ import annotations

import json

import numpy as np
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from thermo_acoustic.application import ApplicationController
from thermo_acoustic.application.commands import (
    Ad2ScopeReadResult,
    Ad2ScopeAppliedResult,
    Ad2ScopeChannelArgs,
    Ad2ScopeTriggerArgs,
    Ad2ScopeTriggerCondition,
    Ad2ScopeTriggerFilter,
    Ad2ScopeTriggerLengthCondition,
    Ad2ScopeTriggerType,
    Ad2AnalogOutputIdle,
    Ad2TriggerSource,
    Ad2WaveformAppliedResult,
    Ad2WaveformChannelArgs,
    Ad2WaveformFunction,
    CameraMasterPulseMode,
    CameraMasterPulseSource,
    CameraSnapshotResult,
    CameraTriggerActive,
    CameraTriggerPolarity,
    CameraTriggerSource,
    DeviceOperation,
    OPERATION_SPECS,
)
from thermo_acoustic.domain.models import ConnectionState, DeviceId, DeviceStatus, OperatingMode
from thermo_acoustic.hal.registry import DeviceRegistry
from thermo_acoustic.ui.device_panels import Ad2Panel, CameraPanel, PANEL_TYPES, PumpPanel
from thermo_acoustic.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication(["test-device-ui"])


def wait(app, ms=80):
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(app.quit)
    timer.start(ms)
    app.exec()


@pytest.mark.parametrize("device", tuple(DeviceId))
def test_each_panel_builds_every_typed_device_operation(qt_app, device):
    del qt_app
    panel = PANEL_TYPES[device]()
    commands = []
    panel.command_requested.connect(lambda _action, command: commands.append(command))

    panel._buttons["connect"].click()
    panel.set_status(DeviceStatus(device, ConnectionState.CONNECTED, busy=True))
    for action, button in panel._buttons.items():
        if action != "connect":
            button.click()

    operations = {command.operation for command in commands}
    expected = {
        operation
        for operation, spec in OPERATION_SPECS.items()
        if device in spec.devices
    }
    assert operations == expected


def test_duplicate_action_is_prevented_with_visible_notice(qt_app):
    del qt_app
    panel = PumpPanel()
    commands = []
    notices = []
    panel.command_requested.connect(lambda action, command: commands.append((action, command)))
    panel.notice.connect(notices.append)
    panel.set_status(DeviceStatus(DeviceId.PUMP, ConnectionState.CONNECTED))

    panel._buttons["status"].click()
    action, command = commands[-1]
    panel.mark_pending(action, command.request_id)
    panel._buttons["status"].click()

    assert len(commands) == 1
    assert "not queued again" in notices[-1]
    assert "pending" in panel._buttons["status"].text().lower()
    panel.clear_pending(command.request_id)
    assert panel._buttons["status"].text() == "Read status"


def test_duplicate_operation_is_blocked_across_ad2_subtabs(qt_app):
    del qt_app
    panel = Ad2Panel()
    commands = []
    panel.command_requested.connect(lambda action, command: commands.append((action, command)))
    panel.set_status(DeviceStatus(DeviceId.AD2, ConnectionState.CONNECTED))

    panel._buttons["wave_trigger_pc"].click()
    action, command = commands[-1]
    panel.mark_pending(action, command.request_id)
    panel._buttons["do_trigger_pc"].click()

    assert len(commands) == 1
    assert "not queued again" in panel.notice_label.text()
    assert panel._buttons["abort"].isEnabled() is False
    panel.set_status(DeviceStatus(DeviceId.AD2, ConnectionState.CONNECTED, busy=True))
    assert panel._buttons["abort"].isEnabled()
    assert panel._buttons["safe_stop"].isEnabled()


def test_main_window_routes_panel_commands_and_terminal_events(qt_app):
    controller = ApplicationController(DeviceRegistry(), mode=OperatingMode.SIMULATION)
    window = MainWindow(controller)
    controller.start()
    pump = window.panels[DeviceId.PUMP]

    pump._buttons["connect"].click()
    wait(qt_app)
    assert pump.connection_label.text() == "Connected"
    assert pump._pending == {}

    pump.flow.setValue(44.0)
    pump._buttons["set_flow"].click()
    wait(qt_app)
    assert controller.statuses()[DeviceId.PUMP].readback.requested_flow_ul_min == 44.0
    assert pump._pending == {}
    window.close()


def test_main_window_routes_waveform_sdk_readback_to_both_channels(qt_app):
    controller = ApplicationController(DeviceRegistry(), mode=OperatingMode.SIMULATION)
    window = MainWindow(controller)
    controller.start()
    ad2 = window.panels[DeviceId.AD2]

    ad2._buttons["connect"].click()
    wait(qt_app)
    ad2.wave_channels[1].enabled.setChecked(True)
    ad2.wave_channels[1].single_frequency.setValue(2500.0)
    ad2._buttons["wave_config"].click()
    wait(qt_app)

    readback = controller.statuses()[DeviceId.AD2].readback
    assert len(readback.waveform_channels) == 2
    assert readback.waveform_channels[1].frequency_hz == 2500.0
    assert "SDK applied" in ad2.wave_channels[0].applied_label.text()
    assert "SDK applied" in ad2.wave_channels[1].applied_label.text()
    window.close()


def test_status_readback_and_result_widgets_update(qt_app):
    del qt_app
    camera = CameraPanel()
    camera.set_status(
        DeviceStatus(DeviceId.CAMERA, ConnectionState.CONNECTED, busy=True, active=True)
    )
    assert camera.connection_label.text() == "Connected"
    assert "busy" in camera.state_label.text()
    assert "active" in camera.state_label.text()

    camera.handle_result(CameraSnapshotResult(np.arange(16, dtype=np.uint16).reshape(4, 4)))
    assert camera.preview.has_image

    ad2 = Ad2Panel()
    ad2.handle_result(Ad2ScopeReadResult({0: [0.0, 1.0], 1: [1.0, -1.0]}))
    assert ad2.scope_plot.samples_by_channel == {0: [0.0, 1.0], 1: [1.0, -1.0]}


def test_ad2_uses_separate_instrument_tabs_and_builds_trigger_arguments(qt_app):
    del qt_app
    panel = Ad2Panel()
    assert [panel.instrument_tabs.tabText(index) for index in range(3)] == [
        "Waveform generator",
        "Oscilloscope",
        "Digital output",
    ]
    channel = panel.wave_channels[0]
    channel.trigger["source"].setCurrentIndex(
        channel.trigger["source"].findData(Ad2TriggerSource.PC.value)
    )
    channel.trigger["wait"].setValue(0.25)
    channel.trigger["run"].setValue(0.5)
    channel.trigger["repeat"].setValue(4)
    channel.trigger["retrigger"].setChecked(True)
    args = panel._wave_args()
    assert len(args.channels) == 2
    assert args.channels[0].trigger.source is Ad2TriggerSource.PC
    assert args.channels[0].trigger.wait_s == 0.25
    assert args.channels[0].trigger.run_s == 0.5
    assert args.channels[0].trigger.repeat_count == 4
    assert args.channels[0].trigger.repeat_trigger


def test_scope_builds_shared_acquisition_and_detector_trigger_arguments(qt_app):
    del qt_app
    panel = Ad2Panel()
    scope = panel.scope_controls
    scope.sample_count.setValue(4096)
    scope.sample_rate.setValue(2_000_000)
    scope.pretrigger_samples.setValue(1024)
    scope.timeout.setValue(3.0)
    scope.poll_interval.setValue(0.02)
    scope.channel_enabled[0].setChecked(True)
    scope.channel_enabled[1].setChecked(True)
    scope.channel_range[0].setValue(2.0)
    scope.channel_offset[1].setValue(-0.25)
    scope.trigger_source.setCurrentIndex(
        scope.trigger_source.findData(Ad2TriggerSource.DETECTOR_ANALOG_IN.value)
    )
    scope.trigger_channel.setCurrentIndex(scope.trigger_channel.findData("1"))
    scope.trigger_type.setCurrentIndex(
        scope.trigger_type.findData(Ad2ScopeTriggerType.PULSE.value)
    )
    scope.trigger_condition.setCurrentIndex(
        scope.trigger_condition.findData(Ad2ScopeTriggerCondition.FALLING_NEGATIVE.value)
    )
    scope.trigger_filter.setCurrentIndex(
        scope.trigger_filter.findData(Ad2ScopeTriggerFilter.AVERAGE.value)
    )
    scope.trigger_level.setValue(0.4)
    scope.trigger_hysteresis.setValue(0.05)
    scope.trigger_length_condition.setCurrentIndex(
        scope.trigger_length_condition.findData(Ad2ScopeTriggerLengthCondition.LESS.value)
    )
    scope.trigger_length.setValue(0.001)
    scope.trigger_holdoff.setValue(0.002)
    scope.trigger_auto_timeout.setValue(1.5)

    args = panel._scope_args()
    assert args.sample_count == 4096
    assert args.sample_frequency_hz == 2_000_000
    assert args.pretrigger_samples == 1024
    assert args.poll_interval_s == 0.02
    assert args.channels == (
        Ad2ScopeChannelArgs(0, 2.0, 0.0),
        Ad2ScopeChannelArgs(1, 5.0, -0.25),
    )
    assert args.trigger == Ad2ScopeTriggerArgs(
        source=Ad2TriggerSource.DETECTOR_ANALOG_IN,
        channel_index=1,
        trigger_type=Ad2ScopeTriggerType.PULSE,
        condition=Ad2ScopeTriggerCondition.FALLING_NEGATIVE,
        filter=Ad2ScopeTriggerFilter.AVERAGE,
        level_v=0.4,
        hysteresis_v=0.05,
        length_condition=Ad2ScopeTriggerLengthCondition.LESS,
        length_s=0.001,
        holdoff_s=0.002,
        auto_timeout_s=1.5,
    )


def test_scope_applied_readback_updates_controls_and_capture_opens_plot(qt_app):
    panel = Ad2Panel()
    applied = Ad2ScopeAppliedResult(
        sample_count=2048,
        sample_frequency_hz=500_000,
        pretrigger_samples=512,
        channels=(Ad2ScopeChannelArgs(1, 1.0, 0.1),),
        trigger=Ad2ScopeTriggerArgs(
            source=Ad2TriggerSource.DETECTOR_ANALOG_IN,
            channel_index=1,
            level_v=0.2,
        ),
    )
    panel.handle_result(applied)
    scope = panel.scope_controls
    assert scope.sample_count.value() == 2048
    assert scope.sample_rate.value() == 500_000
    assert scope.pretrigger_samples.value() == 512
    assert not scope.channel_enabled[0].isChecked()
    assert scope.channel_enabled[1].isChecked()
    assert "SDK applied" in scope.applied_label.text()

    panel.handle_result(Ad2ScopeReadResult({1: [0.0, 0.5, -0.5]}))
    qt_app.processEvents()
    assert scope.plot_window.isVisible()
    assert scope.plot.sample_frequency_hz == 500_000
    assert scope.plot.samples_by_channel == {1: [0.0, 0.5, -0.5]}
    scope.plot_window.close()


def test_camera_builds_complete_sequence_trigger_arguments(qt_app):
    del qt_app
    panel = CameraPanel()
    panel.trigger_enabled.setChecked(True)
    panel.trigger_source.setCurrentIndex(
        panel.trigger_source.findData(CameraTriggerSource.EXTERNAL.value)
    )
    panel.trigger_polarity.setCurrentIndex(
        panel.trigger_polarity.findData(CameraTriggerPolarity.NEGATIVE.value)
    )
    panel.trigger_active.setCurrentIndex(
        panel.trigger_active.findData(CameraTriggerActive.LEVEL.value)
    )
    panel.trigger_times.setValue(3)
    panel.trigger_delay.setValue(0.1)
    panel.masterpulse_mode.setCurrentIndex(
        panel.masterpulse_mode.findData(CameraMasterPulseMode.BURST.value)
    )
    panel.masterpulse_source.setCurrentIndex(
        panel.masterpulse_source.findData(CameraMasterPulseSource.EXTERNAL.value)
    )
    panel.masterpulse_interval.setValue(0.02)
    panel.masterpulse_burst.setValue(8)
    panel.global_exposure_enabled.setChecked(True)
    panel.global_exposure.setChecked(True)

    trigger = panel._sequence_args().trigger
    assert trigger is not None
    assert trigger.source is CameraTriggerSource.EXTERNAL
    assert trigger.polarity is CameraTriggerPolarity.NEGATIVE
    assert trigger.active is CameraTriggerActive.LEVEL
    assert trigger.trigger_times == 3
    assert trigger.delay_s == 0.1
    assert trigger.masterpulse_mode is CameraMasterPulseMode.BURST
    assert trigger.masterpulse_source is CameraMasterPulseSource.EXTERNAL
    assert trigger.masterpulse_interval_s == 0.02
    assert trigger.masterpulse_burst_times == 8
    assert trigger.global_exposure is True


def test_waveform_modes_share_the_advanced_configuration(qt_app):
    del qt_app
    panel = Ad2Panel()
    channel = panel.wave_channels[0]
    channel.mode.setCurrentIndex(1)
    channel.sweep_start.setValue(900.0)
    channel.sweep_stop.setValue(1100.0)
    channel.sweep_time.setValue(2.0)
    channel.sweep_direction.setCurrentIndex(
        channel.sweep_direction.findData("RampUp")
    )
    channel.sweep_offset.setValue(0.25)

    args = channel.arguments()
    assert args.frequency_hz == 1000.0
    assert args.offset_v == 0.25
    assert args.fm_enabled
    assert args.fm_function is Ad2WaveformFunction.RAMP_UP
    assert args.fm_frequency_hz == 500.0
    assert args.fm_modulation_index_percent == 10.0

    channel.mode.setCurrentIndex(2)
    assert channel.adv_frequency.value() == 1000.0
    assert channel.fm_index.value() == 10.0


def test_waveform_sdk_readback_populates_channel_controls(qt_app):
    del qt_app
    panel = Ad2Panel()
    applied = Ad2WaveformChannelArgs(
        0,
        function=Ad2WaveformFunction.SQUARE,
        frequency_hz=1234.0,
        amplitude_v=0.75,
        offset_v=0.1,
        idle_state=Ad2AnalogOutputIdle.OFFSET,
    )
    panel.handle_result(Ad2WaveformAppliedResult((applied, Ad2WaveformChannelArgs(1))))

    channel = panel.wave_channels[0]
    assert channel.adv_frequency.value() == 1234.0
    assert channel.single_frequency.value() == 1234.0
    assert channel.idle.currentData() == Ad2AnalogOutputIdle.OFFSET.value
    assert "SDK applied" in channel.applied_label.text()


def test_panels_fit_half_of_a_1920_by_1200_screen(qt_app):
    controller = ApplicationController(DeviceRegistry(), mode=OperatingMode.SIMULATION)
    window = MainWindow(controller)
    window.resize(960, 1080)
    window.show()
    qt_app.processEvents()
    for index, panel in enumerate(window.panels.values()):
        window.tabs.setCurrentIndex(index)
        qt_app.processEvents()
        assert panel.horizontalScrollBar().maximum() == 0
        assert panel.verticalScrollBar().maximum() == 0
    ad2 = window.panels[DeviceId.AD2]
    window.tabs.setCurrentIndex(0)
    for mode in range(3):
        for channel in ad2.wave_channels:
            channel.mode.setCurrentIndex(mode)
        qt_app.processEvents()
        assert ad2.horizontalScrollBar().maximum() == 0
        assert ad2.verticalScrollBar().maximum() == 0
    ad2.instrument_tabs.setCurrentIndex(1)
    qt_app.processEvents()
    assert ad2.horizontalScrollBar().maximum() == 0
    assert ad2.verticalScrollBar().maximum() == 0
    assert ad2.scope_controls.geometry().right() <= ad2.instrument_tabs.contentsRect().right()
    window.close()


def test_profile_round_trip_is_input_only_and_submits_nothing(qt_app, tmp_path):
    del qt_app
    controller = ApplicationController(DeviceRegistry(), mode=OperatingMode.SIMULATION)
    events = []
    controller.command_event.connect(events.append)
    window = MainWindow(controller)
    pump = window.panels[DeviceId.PUMP]
    camera = window.panels[DeviceId.CAMERA]
    pump.flow.setValue(321.5)
    camera.sequence_frames.setValue(27)
    path = tmp_path / "settings.json"
    window.save_profile(path)

    document = json.loads(path.read_text(encoding="utf-8"))
    assert set(document) == {"schema_version", "devices"}
    assert "connection" not in path.read_text(encoding="utf-8")

    pump.flow.setValue(1.0)
    camera.sequence_frames.setValue(1)
    window.load_profile(path)
    assert pump.flow.value() == 321.5
    assert camera.sequence_frames.value() == 27
    assert events == []


def test_profile_load_is_atomic_and_rejects_invalid_data(qt_app, tmp_path):
    del qt_app
    controller = ApplicationController(DeviceRegistry(), mode=OperatingMode.SIMULATION)
    window = MainWindow(controller)
    camera = window.panels[DeviceId.CAMERA]
    original_exposure = camera.exposure.value()
    document = window.profile_document()
    document["devices"]["camera"]["exposure_ms"] = original_exposure + 10
    document["devices"]["pump"]["move_timeout_s"] = 1.0
    document["devices"]["pump"]["move_poll_s"] = 2.0
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError, match="must not exceed"):
        window.load_profile(path)
    assert camera.exposure.value() == original_exposure

    path.write_text('{"schema_version": 99, "devices": {}}', encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported"):
        window.load_profile(path)

    path.write_text(
        '{"schema_version": 1, "devices": {"camera": {"exposure_ms": Infinity}}}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Non-finite"):
        window.load_profile(path)


def test_previous_waveform_profile_keys_still_load(qt_app, tmp_path):
    del qt_app
    controller = ApplicationController(DeviceRegistry(), mode=OperatingMode.SIMULATION)
    window = MainWindow(controller)
    path = tmp_path / "legacy-waveform.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "devices": {
                    "ad2": {
                        "wave_frequency_hz": 4321.0,
                        "wave_amplitude_v": 0.4,
                        "wave_trigger_source": Ad2TriggerSource.PC.value,
                        "wave_trigger_wait_s": 0.2,
                        "wave_trigger_run_s": 0.3,
                        "wave_trigger_repeat_count": 2,
                        "wave_trigger_repeat": True,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    window.load_profile(path)
    channel = window.panels[DeviceId.AD2].wave_channels[0]
    assert channel.single_frequency.value() == 4321.0
    assert channel.single_amplitude.value() == 0.4
    assert channel.trigger["source"].currentData() == Ad2TriggerSource.PC.value
    window.close()
