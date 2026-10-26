from __future__ import annotations

import json
from time import monotonic, sleep

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPointF, Qt, QTimer
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QAbstractSpinBox, QApplication, QMessageBox, QSizePolicy

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
    Ad2ConfigureDigitalOutputArgs,
    Ad2ConfigureWaveformArgs,
    Ad2TriggerSettingsArgs,
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
    CommandResult,
    DeviceCommand,
    CommandEvent,
    ConfirmationRequest,
    DeviceOperation,
    OPERATION_SPECS,
    PumpSetFlowArgs,
    PumpReferenceMoveArgs,
    PumpConnectArgs,
)
from thermo_acoustic.application.configuration import DEFAULT_PUMP_CONFIGURATION_DIR
from thermo_acoustic.console.parser import parse_command
from thermo_acoustic.application.event_formatting import detailed_event_text
from thermo_acoustic.domain.models import (
    Ad2Readback,
    CameraReadback,
    CameraRoiLimitsReadback,
    CameraRoiReadback,
    ConnectionState,
    DeviceId,
    DeviceStatus,
    IntegerRange,
    OperatingMode,
    PumpReadback,
    PumpUnitReadback,
    TecChannelReadback,
    TecReadback,
)
from thermo_acoustic.hal.registry import DeviceRegistry
from thermo_acoustic.hal.ad2 import AD2Worker
from thermo_acoustic.drivers.ad2.simulated import SimulatedAD2
from thermo_acoustic.drivers.pump import SimulatedPumpBank
from thermo_acoustic.ui.device_panels import Ad2Panel, CameraPanel, PANEL_TYPES, PumpPanel, TecPanel
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
    if device is DeviceId.CAMERA:
        panel.sequence_save_folder.setText("camera-sequence-test-output")
    commands = []
    panel.command_requested.connect(lambda _action, command: commands.append(command))

    panel._buttons["connect"].click()
    readback = PumpReadback(units=(PumpUnitReadback(0, max_volume_ml=1.0, max_flow_rate_ul_min=1000.0),)) if device is DeviceId.PUMP else None
    panel.set_status(DeviceStatus(device, ConnectionState.CONNECTED, busy=True, readback=readback))
    for action, button in panel._buttons.items():
        if action != "connect" and not (device is DeviceId.PUMP and action.startswith(("level_", "flow_", "syringe_"))):
            button.click()

    operations = {command.operation for command in commands}
    expected = {
        operation
        for operation, spec in OPERATION_SPECS.items()
        if device in spec.devices
    }
    if device is DeviceId.CAMERA:
        expected -= {
            DeviceOperation.CAMERA_SNAPSHOT_CONFIGURE,
            DeviceOperation.CAMERA_SEQUENCE_CONFIGURE,
            DeviceOperation.CAMERA_SEQUENCE_ARM,
            DeviceOperation.CAMERA_SEQUENCE_COLLECT,
            DeviceOperation.CAMERA_SETTINGS_READ,  # import lives in the simple experiment tab
        }
    if device is DeviceId.AD2:
        expected -= {
            DeviceOperation.AD2_EXPERIMENT_DIGITAL_CONFIGURE,
            DeviceOperation.AD2_OUTPUT_STATUS_READ,
        }
    if device is DeviceId.PUMP:
        expected = {
            DeviceOperation.CONNECT, DeviceOperation.DISCONNECT,
            DeviceOperation.ABORT_ACTIVE, DeviceOperation.SAFE_STOP,
            DeviceOperation.PUMP_REFILL, DeviceOperation.PUMP_EMPTY,
            DeviceOperation.PUMP_FLOW_STOP, DeviceOperation.PUMP_REFERENCE_MOVE,
                DeviceOperation.PUMP_VALVE_POSITION_READ,
        }
    assert operations == expected


def test_duplicate_action_is_prevented_by_disabling_pending_button(qt_app):
    del qt_app
    panel = PumpPanel()
    commands = []
    panel.command_requested.connect(lambda action, command: commands.append((action, command)))
    panel.set_status(DeviceStatus(DeviceId.PUMP, ConnectionState.CONNECTED, readback=PumpReadback(units=(PumpUnitReadback(0),))))

    panel._buttons["refill_0"].click()
    action, command = commands[-1]
    panel.mark_pending(action, command.request_id)
    assert not panel._buttons["refill_0"].isEnabled()
    panel._buttons["refill_0"].click()

    assert len(commands) == 1
    assert panel.notice_label.text() == ""
    assert "pending" in panel._buttons["refill_0"].text().lower()
    panel.clear_pending(command.request_id)
    assert panel._buttons["refill_0"].text() == "Refill"
    assert panel._buttons["refill_0"].isEnabled()


def test_pump_tile_shows_observed_state_and_syringe(qt_app):
    del qt_app
    panel = PumpPanel()
    def show(unit):
        panel.set_status(DeviceStatus(DeviceId.PUMP, ConnectionState.CONNECTED,
            readback=PumpReadback(units=(unit,))))
        return panel.tiles_layout.itemAtPosition(0, 0).widget()

    tile = show(PumpUnitReadback(0, fill_level_ml=0.3, current_flow_ul_min=15.0,
        is_pumping=True, is_faulted=False, max_volume_ml=1.0,
        syringe_name="BD 1ml", syringe_inner_diameter_mm=4.78,
        syringe_max_piston_stroke_mm=55.7))
    assert "Pumping" in tile.state_label.text()
    assert "BD 1ml" in tile.syringe_label.text()
    assert "4.78 mm" in tile.syringe_label.text()
    assert tile.flow_label.text() == "15"
    panel._blink()
    assert "transparent" in tile.state_label.styleSheet()

    tile = show(PumpUnitReadback(0, is_pumping=False, is_faulted=False))
    assert "Idle" in tile.state_label.text()
    tile = show(PumpUnitReadback(0, is_pumping=True, is_faulted=True))
    assert "Error" in tile.state_label.text()
    assert "#c62828" in tile.state_label.styleSheet()


def test_tec_table_shows_dash_not_literal_none_for_an_unreported_target(qt_app):
    # The controller can report ready/output-on with no target readback at
    # all (a real protocol characteristic, not an error) -- the table must
    # not render that as the literal string "None".
    del qt_app
    panel = TecPanel()
    panel.set_status(DeviceStatus(DeviceId.TEC, ConnectionState.CONNECTED,
        readback=TecReadback(channels=(
            TecChannelReadback(1, current_temperature_c=24.5, target_temperature_c=None,
                              output_enabled=True, ready=True),
        ))))
    assert panel.table.item(0, 2).text() == "—"
    assert panel.table.item(0, 1).text() == "24.5"
    assert "protocol characteristic" in panel.table.horizontalHeaderItem(2).toolTip()


def test_duplicate_operation_is_blocked_across_ad2_subtabs(qt_app):
    del qt_app
    panel = Ad2Panel()
    commands = []
    panel.command_requested.connect(lambda action, command: commands.append((action, command)))
    panel.set_status(DeviceStatus(DeviceId.AD2, ConnectionState.CONNECTED))

    panel._buttons["wave_trigger_pc"].click()
    action, command = commands[-1]
    panel.mark_pending(action, command.request_id)
    assert not panel._buttons["wave_trigger_pc"].isEnabled()
    assert not panel._buttons["do_trigger_pc"].isEnabled()
    panel._buttons["do_trigger_pc"].click()

    assert len(commands) == 1
    assert panel.notice_label.text() == ""
    assert panel._buttons["abort"].isEnabled() is False
    panel.set_status(DeviceStatus(DeviceId.AD2, ConnectionState.CONNECTED, busy=True))
    assert panel._buttons["abort"].isEnabled()
    assert panel._buttons["safe_stop"].isEnabled()
    panel.clear_pending(command.request_id)
    assert panel._buttons["wave_trigger_pc"].isEnabled()
    assert panel._buttons["do_trigger_pc"].isEnabled()


def test_main_window_routes_panel_commands_and_terminal_events(qt_app):
    controller = ApplicationController(DeviceRegistry(), mode=OperatingMode.SIMULATION)
    window = MainWindow(controller)
    controller.start()
    try:
        pump = window.panels[DeviceId.PUMP]

        pump._buttons["connect"].click()
        wait(qt_app)
        assert pump.connection_label.text() == "Connected"
        assert pump._pending == {}

        pump._buttons["refill_0"].click()
        wait(qt_app, 650)
        assert controller.statuses()[DeviceId.PUMP].readback.units[0].fill_level_ml == 1.0
        assert pump._pending == {}
    finally:
        window.close()
        controller.shutdown()


def test_main_window_uses_fixed_minimum_and_separate_detailed_log(qt_app):
    controller = ApplicationController(DeviceRegistry(), mode=OperatingMode.SIMULATION)
    window = MainWindow(controller)

    # Content scrolls inside the tabs, so the window can follow a small screen (1366x768 at 125 %
    # scaling leaves roughly 1090x610 logical pixels) and no panel may demand more than the minimum.
    assert (window.minimumWidth(), window.minimumHeight()) == (900, 560)
    hint = window.minimumSizeHint()
    assert hint.width() <= window.minimumWidth() and hint.height() <= window.minimumHeight(), hint
    assert window.log.parent() is window.log_window
    assert [action.text() for action in window.menuBar().actions()] == [
        "&File", "&Log", "Experiment &builder"]
    assert window.tabs.tabText(window.tabs.count() - 2) == "Experiments"
    assert window.tabs.tabText(window.tabs.count() - 1) == "Run monitor"
    assert window.builder_window.panel.parent() is window.builder_window
    for spin in window.findChildren(QAbstractSpinBox):
        assert spin.buttonSymbols() is QAbstractSpinBox.ButtonSymbols.NoButtons
        assert not spin.keyboardTracking()
        value = spin.value()
        assert window.eventFilter(spin, QEvent(QEvent.Type.Wheel))
        assert spin.value() == value
    window.close()


def test_human_readable_event_log_includes_time_call_and_arguments():
    event = CommandEvent(
        request_id="abc123",
        state="queued",
        device=DeviceId.PUMP,
        operation=DeviceOperation.PUMP_FLOW_SET,
        source="console",
        arguments=PumpSetFlowArgs(12.5),
    )

    text = detailed_event_text(event)

    assert "abc123" in text
    assert "CETONI pump" in text
    assert "flow set" in text
    assert '"flow_ul_min": 12.5' in text


def test_numeric_editor_keeps_intermediate_text_until_commit(qt_app):
    del qt_app
    controller = ApplicationController(DeviceRegistry(), mode=OperatingMode.SIMULATION)
    window = MainWindow(controller)
    spin = window.panels[DeviceId.AD2].do_trigger["wait"]
    spin.setRange(100, 1000)
    spin.setValue(100)
    spin.lineEdit().setText("5")
    assert spin.lineEdit().text() == "5"
    assert spin.value() == 100
    spin.lineEdit().setText("500")
    spin.interpretText()
    assert spin.value() == 500
    window.close()


def test_success_replaces_persistent_error_feedback(qt_app):
    del qt_app
    controller = ApplicationController(DeviceRegistry(), mode=OperatingMode.SIMULATION)
    window = MainWindow(controller)
    panel = window.panels[DeviceId.AD2]
    panel.show_notice("Invalid digital configuration")
    assert "Invalid digital configuration" in window.statusBar().currentMessage()
    window._event(CommandEvent(
        request_id="ad2-config-failure",
        state="failed",
        device=DeviceId.AD2,
        operation=DeviceOperation.AD2_DIGITAL_OUTPUT_CONFIGURE,
        source="ui",
        message="digital trigger wait_s must be within 2e-07..86400; received 0",
    ))
    assert "failed" in panel.notice_label.text()
    event = CommandEvent(
        request_id="ad2-start-success",
        state="completed",
        device=DeviceId.AD2,
        operation=DeviceOperation.AD2_DIGITAL_OUTPUT_START,
        source="ui",
    )
    window._event(event)
    assert "done!" in window.statusBar().currentMessage()
    assert "done!" in panel.notice_label.text()
    assert "#2e7d32" in panel.notice_label.styleSheet()
    window._status(controller.statuses())
    assert "done!" in window.statusBar().currentMessage()
    window.close()


def test_ad2_zero_trigger_times_bypass_positive_sdk_minimum(qt_app):
    del qt_app
    capabilities = SimulatedAD2().capabilities()
    for channel in capabilities["waveform_channels"]:
        channel["wait_s"] = (2e-7, 86400.0)
        channel["run_s"] = (2e-7, 86400.0)
    capabilities["digital_output"]["wait_s"] = (2e-7, 86400.0)
    capabilities["digital_output"]["run_s"] = (2e-7, 86400.0)
    worker = AD2Worker(SimulatedAD2)
    worker._capabilities = worker._convert_capabilities(capabilities)
    worker._validate_digital_output(Ad2ConfigureDigitalOutputArgs())
    worker._validate_waveform(Ad2ConfigureWaveformArgs().resolved_channels())
    with pytest.raises(ValueError, match="digital trigger wait_s"):
        worker._validate_digital_output(
            Ad2ConfigureDigitalOutputArgs(trigger=Ad2TriggerSettingsArgs(wait_s=1e-7))
        )
    panel = Ad2Panel()
    panel._apply_capabilities(worker._capabilities)
    assert panel.do_trigger["wait"].minimum() == 0
    assert panel.do_trigger["run"].minimum() == 0
    assert panel.wave_channels[0].trigger["wait"].minimum() == 0
    assert panel.wave_channels[0].trigger["run"].minimum() == 0
    panel.do_trigger["wait"].setValue(2e-7)
    assert panel.do_trigger["wait"].value() == 2e-7


def test_main_window_routes_waveform_sdk_readback_to_both_channels(qt_app):
    controller = ApplicationController(DeviceRegistry(), mode=OperatingMode.SIMULATION)
    window = MainWindow(controller)
    controller.start()
    try:
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
    finally:
        window.close()
        controller.shutdown()


def test_console_waveform_configuration_updates_visible_ad2_controls(qt_app):
    controller = ApplicationController(DeviceRegistry(), mode=OperatingMode.SIMULATION)
    window = MainWindow(controller)
    command = parse_command(
        "ad2 waveform configure --ch1-frequency-hz 2000 --ch1-amplitude-v 2 "
        "--ch2-enabled false"
    )
    window._result(
        CommandResult(
            command.request_id,
            DeviceId.AD2,
            command.operation,
            True,
            Ad2WaveformAppliedResult(command.arguments.resolved_channels()),
            command=command,
        )
    )
    channel = window.panels[DeviceId.AD2].wave_channels[0]
    assert channel.single_frequency.value() == 2000.0
    assert channel.single_amplitude.value() == 2.0
    assert not window.panels[DeviceId.AD2].wave_channels[1].enabled.isChecked()
    window.close()


def test_successful_console_commands_synchronize_other_panel_editors(qt_app):
    del qt_app
    camera = CameraPanel()
    camera.apply_successful_command(parse_command("camera sequence configure --frames 7 --exposure-ms 3 --timeout-s 5 --poll-interval-s 0.1"))
    assert camera.sequence_frames.value() == 7
    assert camera.sequence_exposure.value() == 3.0
    assert camera.frame_timeout.value() == 5.0


def test_ad2_connect_populates_sdk_capabilities_and_scope_limits(qt_app):
    controller = ApplicationController(DeviceRegistry(), mode=OperatingMode.SIMULATION)
    window = MainWindow(controller)
    controller.start()
    try:
        ad2 = window.panels[DeviceId.AD2]

        ad2._buttons["connect"].click()
        wait(qt_app)

        capabilities = controller.statuses()[DeviceId.AD2].readback.capabilities
        assert capabilities is not None
        assert ad2.scope_controls.sample_rate.value() == capabilities.scope.sample_frequency_hz.maximum
        assert tuple(
            ad2.scope_controls.channel_range[0].itemData(index)
            for index in range(ad2.scope_controls.channel_range[0].count())
        ) == capabilities.scope.input_ranges_v
        assert tuple(
            ad2.wave_channels[0].single_function.itemData(index)
            for index in range(ad2.wave_channels[0].single_function.count())
        ) == capabilities.waveform_channels[0].carrier.functions
        assert ad2.wave_channels[0].sweep_direction.itemData(0) == "Triangle"
    finally:
        window.close()
        controller.shutdown()


def test_ad2_header_shows_each_instrument_state(qt_app):
    del qt_app
    panel = Ad2Panel()
    panel.update_readback(
        Ad2Readback(
            waveform_running=True,
            scope_state="armed",
            digital_output_configured=True,
        )
    )
    assert panel.instrument_status_label.text() == (
        "WFG: running · Oscilloscope: armed · Digital output: configured"
    )


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
    scope.channel_enabled[0].setChecked(True)
    scope.channel_enabled[1].setChecked(True)
    scope.channel_range[0].setCurrentIndex(scope.channel_range[0].findData(2.0))
    scope.channel_offset[1].setValue(-0.25)
    scope.trigger_source.setCurrentIndex(
        scope.trigger_source.findData(Ad2TriggerSource.DETECTOR_ANALOG_IN.value)
    )
    scope.trigger_channel.setCurrentIndex(scope.trigger_channel.findData("1"))
    scope.trigger_condition.setCurrentIndex(
        scope.trigger_condition.findData(Ad2ScopeTriggerCondition.FALLING_NEGATIVE.value)
    )
    scope.trigger_filter.setCurrentIndex(
        scope.trigger_filter.findData(Ad2ScopeTriggerFilter.AVERAGE.value)
    )
    scope.trigger_level.setValue(0.4)
    scope.trigger_hysteresis.setValue(0.05)
    scope.trigger_holdoff.setValue(0.002)
    scope.trigger_auto_timeout.setValue(1.5)

    args = panel._scope_args()
    assert args.sample_count == 4096
    assert args.sample_frequency_hz == 2_000_000
    assert args.pretrigger_samples == 1024
    assert args.poll_interval_s == 0.01
    assert args.channels == (
        Ad2ScopeChannelArgs(0, 2.0, 0.0),
        Ad2ScopeChannelArgs(1, 5.0, -0.25),
    )
    assert args.trigger == Ad2ScopeTriggerArgs(
        source=Ad2TriggerSource.DETECTOR_ANALOG_IN,
        channel_index=1,
        trigger_type=Ad2ScopeTriggerType.EDGE,
        condition=Ad2ScopeTriggerCondition.FALLING_NEGATIVE,
        filter=Ad2ScopeTriggerFilter.AVERAGE,
        level_v=0.4,
        hysteresis_v=0.05,
        length_condition=Ad2ScopeTriggerLengthCondition.MORE,
        length_s=0.0,
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


def test_camera_acquisition_controls_always_send_visible_settings(qt_app):
    del qt_app
    panel = CameraPanel()
    panel.snapshot_exposure.setValue(4.5)
    panel.sequence_exposure.setValue(7.5)

    assert not hasattr(panel, "snapshot_exposure_enabled")
    assert not hasattr(panel, "sequence_exposure_enabled")
    assert not hasattr(panel, "trigger_enabled")
    assert not hasattr(panel, "global_exposure_enabled")
    assert panel._snapshot_args().exposure_ms == 4.5
    sequence = panel._sequence_args()
    assert sequence.exposure_ms == 7.5
    assert sequence.trigger is not None
    panel.image_window.close()


def test_camera_frames_keep_independent_viewer_geometry(qt_app):
    panel = CameraPanel()
    viewer = panel.image_window
    assert viewer.parentWidget() is None
    assert not viewer.isModal()
    assert viewer.preview.sizePolicy().horizontalPolicy() is QSizePolicy.Policy.Ignored

    panel.handle_result(CameraSnapshotResult(np.zeros((64, 64), dtype=np.uint16)))
    qt_app.processEvents()
    viewer.resize(750, 590)
    viewer.move(35, 45)
    qt_app.processEvents()
    geometry = viewer.geometry()

    panel.handle_result(CameraSnapshotResult(np.zeros((1200, 1600), dtype=np.uint16)))
    qt_app.processEvents()
    assert viewer.geometry() == geometry
    viewer.close()


def test_camera_viewer_intensity_controls_use_raw_16_bit_frames(qt_app):
    panel = CameraPanel()
    viewer = panel.image_window
    frame = np.array([[100, 200], [300, 400]], dtype=np.uint16)
    viewer.show_frame(frame, "Snapshot captured")
    qt_app.processEvents()
    assert viewer.preview.display_limits is None
    assert viewer.preview._image.format().name == "Format_Grayscale16"
    assert viewer.histogram.pixel_count == 4
    assert viewer.histogram.counts[0] == 2
    assert viewer.histogram.counts[1] == 2

    viewer.adjust_intensity_button.click()
    assert viewer.preview.display_limits == (100, 400)
    assert viewer.histogram.limits == (100, 400)
    assert viewer.preview._image.pixelColor(0, 0).red() == 0
    assert viewer.preview._image.pixelColor(1, 1).red() == 255
    frame[0, 0] = 500
    assert viewer.preview.raw_frame[0, 0] == 100

    newer = np.array([[1000, 1100], [1200, 65535]], dtype=np.uint16)
    viewer.show_frame(newer, "Continuous snapshot")
    assert viewer.preview.display_limits == (100, 400)
    assert viewer.histogram.saturated_count == 1
    assert viewer.histogram.observed_range == (1000, 65535)
    assert "pixels at 65535: 1/4" in viewer.intensity_status.text()
    viewer.autoscale_checkbox.setChecked(True)
    assert viewer.preview.display_limits == (1000, 65535)
    viewer.show_frame(np.array([[10, 20], [30, 40]], dtype=np.uint16), "Continuous snapshot")
    assert viewer.preview.display_limits == (10, 40)

    viewer.full_range_button.click()
    assert not viewer.autoscale_checkbox.isChecked()
    assert viewer.preview.display_limits is None
    assert viewer.histogram.limits is None
    assert viewer.preview._image.format().name == "Format_Grayscale16"
    viewer.close()


@pytest.mark.parametrize("value, limits", [(0, (0, 1)), (65535, (65534, 65535))])
def test_camera_viewer_can_adjust_constant_frame(qt_app, value, limits):
    del qt_app
    panel = CameraPanel()
    viewer = panel.image_window
    viewer.show_frame(np.full((4, 4), value, dtype=np.uint16), "Snapshot captured")
    viewer.adjust_intensity_button.click()
    assert viewer.preview.display_limits == limits
    assert viewer.histogram.observed_range == (value, value)
    viewer.close()


def test_camera_viewer_hover_maps_letterboxed_pixels_to_raw_values(qt_app):
    panel = CameraPanel()
    viewer = panel.image_window
    frame = np.array([[1, 2, 3, 4], [5, 6, 7, 8]], dtype=np.uint16)
    viewer.show_frame(frame, "Snapshot captured")
    qt_app.processEvents()
    preview = viewer.preview
    target = preview.image_target_rect()
    left, top = target.x(), target.y()
    position = QPointF(left + 2.5 * target.width() / 4, top + 1.5 * target.height() / 2)
    assert preview.pixel_at(position) == (2, 1, 7)
    preview.mouseMoveEvent(QMouseEvent(
        QEvent.Type.MouseMove, position, position, position,
        Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
    ))
    qt_app.processEvents()
    assert viewer.cursor_status.text().endswith("2, 1, 7")
    viewer.show_frame(frame + 10, "Continuous snapshot")
    assert viewer.cursor_status.text().endswith("2, 1, 17")
    preview.leaveEvent(QEvent(QEvent.Type.Leave))
    viewer.show_frame(frame + 20, "Continuous snapshot")
    assert viewer.cursor_status.text().endswith("—")
    assert preview.pixel_at(QPointF(left + 10, top - 2)) is None
    assert preview.pixel_at(QPointF(left + target.width() + 2, top + 1)) is None
    viewer.close()


def test_pump_connect_uses_selected_configuration_folder(qt_app, tmp_path):
    del qt_app
    panel = PumpPanel()
    assert panel.configuration_dir.text() == str(DEFAULT_PUMP_CONFIGURATION_DIR)
    assert "configuration_dir" not in panel.profile_values()
    (tmp_path / "qmixdevices.xml").touch()
    panel.configuration_dir.setText(str(tmp_path))
    commands = []
    panel.command_requested.connect(lambda _action, command: commands.append(command))

    panel._buttons["connect"].click()
    assert len(commands) == 1
    assert isinstance(commands[0].arguments, PumpConnectArgs)
    assert commands[0].arguments.configuration_dir == tmp_path.resolve()
    event = CommandEvent(
        request_id=commands[0].request_id,
        state="queued",
        device=DeviceId.PUMP,
        operation=DeviceOperation.CONNECT,
        source="ui",
        arguments=commands[0].arguments,
    )
    logged_args = json.loads(detailed_event_text(event).split("arguments=", 1)[1])
    assert logged_args["configuration_dir"] == str(tmp_path.resolve())

    panel.configuration_dir.setText("")
    panel._buttons["connect"].click()
    assert len(commands) == 1
    assert "Choose a Qmix configuration folder" in panel.notice_label.text()

    panel.configuration_dir.setText(str(tmp_path / "missing"))
    panel._buttons["connect"].click()
    assert len(commands) == 1
    assert "does not exist" in panel.notice_label.text()


def test_center_roi_sends_single_command_for_worker_managed_pause_restart(qt_app):
    del qt_app
    panel = CameraPanel()
    limits = CameraRoiLimitsReadback(
        IntegerRange(0, 2044, 4),
        IntegerRange(0, 1020, 4),
        IntegerRange(4, 2048, 4),
        IntegerRange(4, 1024, 4),
    )
    panel.set_status(
        DeviceStatus(
            DeviceId.CAMERA,
            ConnectionState.CONNECTED,
            active=True,
            readback=CameraReadback(
                mode="continuous",
                capture_active=True,
                roi=CameraRoiReadback(0, 0, 512, 256),
                roi_limits=limits,
            ),
        )
    )
    panel.roi_width.setValue(512)
    panel.roi_height.setValue(256)
    commands = []
    panel.command_requested.connect(lambda _action, command: commands.append(command))

    panel._buttons["center_roi"].click()

    assert [command.operation for command in commands] == [DeviceOperation.CAMERA_ROI_CONFIGURE]
    roi = commands[0].arguments
    assert (roi.horizontal_offset, roi.vertical_offset) == (768, 384)


def test_center_roi_restarts_live_simulated_continuous_capture(qt_app):
    controller = ApplicationController(DeviceRegistry(), mode=OperatingMode.SIMULATION)
    window = MainWindow(controller)
    controller.start()
    try:
        camera = window.panels[DeviceId.CAMERA]
        camera._buttons["connect"].click()
        wait(qt_app)
        camera.roi_width.setValue(512)
        camera.roi_height.setValue(256)
        camera._buttons["continuous"].click()
        wait(qt_app, 180)
        assert camera.preview.has_image

        camera._buttons["center_roi"].click()
        wait(qt_app, 350)

        readback = controller.statuses()[DeviceId.CAMERA].readback
        assert readback.capture_active
        assert readback.mode == "continuous"
        assert readback.roi == CameraRoiReadback(768, 384, 512, 256)
        camera._buttons["capture_stop"].click()
        wait(qt_app)
        camera.image_window.close()
    finally:
        window.close()
        controller.shutdown()


@pytest.mark.parametrize("button, expected", [
    (QMessageBox.StandardButton.Yes, True),
    (QMessageBox.StandardButton.Cancel, False),
])
def test_reference_confirmation_uses_clicked_button(qt_app, button, expected):
    controller = ApplicationController(DeviceRegistry(), mode=OperatingMode.SIMULATION)
    window = MainWindow(controller)

    def click_button():
        dialog = qt_app.activeModalWidget()
        assert isinstance(dialog, QMessageBox)
        dialog.button(button).click()

    QTimer.singleShot(20, click_button)
    request = ConfirmationRequest(
        DeviceCommand(DeviceId.PUMP, DeviceOperation.PUMP_REFERENCE_MOVE, PumpReferenceMoveArgs()),
        "Remove the syringe before reference move",
    )
    accepted = window.confirm_operation(request)
    assert accepted is expected
    window.close()


def test_simulated_sequence_updates_popup_and_saves_tiff_with_settings(qt_app, tmp_path):
    controller = ApplicationController(DeviceRegistry(), mode=OperatingMode.SIMULATION)
    window = MainWindow(controller)
    controller.start()
    try:
        camera = window.panels[DeviceId.CAMERA]
        camera._buttons["connect"].click()
        wait(qt_app)
        camera.sequence_frames.setValue(3)
        camera._buttons["sequence"].click()
        wait(qt_app, 350)

        assert camera.preview.has_image
        assert "3 frames" in camera.sequence_status.text()
        camera.sequence_save_folder.setText(str(tmp_path))
        camera._buttons["sequence_save"].click()
        wait(qt_app, 150)

        assert len(list(tmp_path.glob("frame_*.tiff"))) == 3
        metadata = json.loads((tmp_path / "camera_settings.json").read_text(encoding="utf-8"))
        assert metadata["sequence"]["frame_count"] == 3
        assert metadata["properties"]
        camera.image_window.close()
    finally:
        window.close()
        controller.shutdown()


def test_camera_profile_migrates_removed_enable_checkboxes(qt_app, tmp_path):
    del qt_app
    controller = ApplicationController(DeviceRegistry(), mode=OperatingMode.SIMULATION)
    window = MainWindow(controller)
    document = window.profile_document()
    document["schema_version"] = 1
    document["devices"]["camera"].update(
        snapshot_exposure_enabled=True,
        sequence_exposure_enabled=True,
        trigger_enabled=True,
        global_exposure_enabled=True,
    )
    path = tmp_path / "legacy-camera-profile.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    window.load_profile(path)

    assert window.panels[DeviceId.CAMERA].snapshot_exposure.value() == 2.5
    window.close()


def test_waveform_modes_share_the_advanced_configuration(qt_app):
    del qt_app
    panel = Ad2Panel()
    channel = panel.wave_channels[0]
    channel.mode.setCurrentIndex(1)
    channel.sweep_center.setValue(1000.0)
    channel.sweep_width.setValue(200.0)
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
    camera.sequence_frames.setValue(27)
    path = tmp_path / "settings.json"
    window.save_profile(path)

    document = json.loads(path.read_text(encoding="utf-8"))
    assert set(document) == {"schema_version", "devices", "experiment"}
    assert "connection" not in path.read_text(encoding="utf-8")

    assert document["devices"]["pump"] == {}
    camera.sequence_frames.setValue(1)
    window.load_profile(path)
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
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError, match="Unknown pump setting"):
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


def _connect_pump_via_real_button(app, window, results):
    window.panels[DeviceId.PUMP]._buttons["connect"].click()
    deadline = monotonic() + 5
    while monotonic() < deadline and not any(
        result.operation is DeviceOperation.CONNECT and result.device is DeviceId.PUMP and result.ok
        for result in results
    ):
        app.processEvents(); sleep(0.01)
    assert any(result.operation is DeviceOperation.CONNECT and result.device is DeviceId.PUMP and result.ok
               for result in results)


def test_experiment_tab_inputs_round_trip_through_the_settings_profile(qt_app, tmp_path):
    # Extends the existing device-settings profile (same file, same
    # save_profile()/load_profile() entry point -- see
    # test_profile_round_trip_is_input_only_and_submits_nothing above) to
    # also cover the Experiment tab's fixed-form inputs: scan (frequency/
    # amplitude/exposure/sweep), repeats, acquisition timing, temperature,
    # flush, and output (tiff_format) settings. Configures a non-default
    # series on one window, saves, builds a *second*, independent MainWindow
    # (fresh controller/registry, nothing connected yet), loads, and checks
    # both the raw field values and the compiled experiment definition
    # agree -- not just that loading didn't crash.
    app = QApplication.instance() or QApplication(["test-experiment-profile"])
    controller1 = ApplicationController(DeviceRegistry(mode=OperatingMode.SIMULATION), mode=OperatingMode.SIMULATION)
    results1 = []
    controller1.command_result.connect(results1.append)
    controller1.start()
    window1 = MainWindow(controller1)
    try:
        _connect_pump_via_real_button(app, window1, results1)
        panel1 = window1.experiment_panel
        panel1.description.setText("Non-default saved series")
        panel1.repeats.setValue(3)
        panel1.frames.setValue(5)
        panel1.fps.setValue(12)
        panel1.sweep_enabled.setChecked(True)
        for widget, value in zip(panel1.frequency, (900_000, 1_100_000, 3)):
            widget.setValue(value)
        for widget, value in zip(panel1.amplitude, (0.5, 1.5, 2)):
            widget.setValue(value)
        for widget, value in zip(panel1.exposure, (2, 4, 2)):
            widget.setValue(value)
        for widget, value in zip(panel1.sweep_width, (50_000, 150_000, 2)):
            widget.setValue(value)
        panel1.sweep_period.setValue(5)
        panel1.roi_x.setValue(10); panel1.roi_y.setValue(20)
        panel1.roi_width.setValue(64); panel1.roi_height.setValue(48)
        # Unit 1 (index 1), deliberately not unit 0 -- unit 0 happens to be
        # Qt's own "first item becomes current" default for an empty-then-
        # populated combo, so it would not actually exercise the pending-
        # selection restore path below (see
        # test_experiment_tab_flush_unit_selection_survives_a_load_before_connect).
        assert panel1.pump_unit.findData(1) >= 0  # the simulated pump bank has >= 2 units
        panel1.pump_unit.setCurrentIndex(panel1.pump_unit.findData(1))
        panel1.volume.setValue(0.07)
        panel1.flow.setValue(350)
        panel1.wait_after_flush.setValue(1.5)
        panel1.temperature_control.setChecked(True)
        panel1.tec_channel.setCurrentIndex(0)
        for widget, value in zip(panel1.temperature, (18, 28, 3)):
            widget.setValue(value)
        panel1.temp_wait.setValue(2.5)
        panel1.temperature_logging.setChecked(True)
        panel1.temperature_wait_for_stability.setChecked(True)
        panel1.temperature_tolerance.setValue(0.3)
        panel1.temperature_min_settle.setValue(1.0)
        panel1.temperature_max_wait.setValue(30)

        saved_definition = panel1._definition()
        path = tmp_path / "settings.json"
        window1.save_profile(path)

        document = json.loads(path.read_text(encoding="utf-8"))
        assert document["experiment"]["description"] == "Non-default saved series"
        assert document["experiment"]["repeats"] == 3
        assert document["experiment"]["frequency_hz"] == {"start": 900_000, "stop": 1_100_000, "steps": 3}

        # A brand-new window, independent controller/registry -- nothing
        # connected at load time, matching "load only restores inputs, it
        # does not connect devices."
        controller2 = ApplicationController(DeviceRegistry(mode=OperatingMode.SIMULATION), mode=OperatingMode.SIMULATION)
        results2 = []
        controller2.command_result.connect(results2.append)
        controller2.start()
        window2 = MainWindow(controller2)
        try:
            commands_before_load = len(results2)
            window2.load_profile(path)
            assert len(results2) == commands_before_load  # no device command submitted by the load itself

            panel2 = window2.experiment_panel
            restored = panel2._settings(require_pump_unit=False)
            original = panel1._settings(require_pump_unit=False)
            for field in ("description", "repeats", "frame_count", "camera_fps", "sweep_enabled",
                          "frequency_hz", "amplitude_v", "exposure_ms", "sweep_width_hz", "sweep_period_ms",
                          "roi", "flush_volume_ml", "flush_flow_ul_min", "flush_wait_after_s",
                          "temperature_control", "temperature_c", "temperature_wait_s",
                          "temperature_logging", "temperature_wait_for_stability",
                          "temperature_tolerance_c", "temperature_min_settle_s", "temperature_max_wait_s"):
                assert getattr(restored, field) == getattr(original, field), field
            # flush_unit_index/tec_channel are combo selections that only
            # exist once the matching device is connected -- connecting the
            # same pump unit here recovers them and lets the full compiled
            # definition be compared, not just the individually-restored
            # fields above.
            _connect_pump_via_real_button(app, window2, results2)
            assert panel2._definition() == saved_definition
        finally:
            window2.close()
            controller2.shutdown()
    finally:
        window1.close()
        controller1.shutdown()


def test_experiment_tab_flush_unit_selection_survives_a_load_before_connect(qt_app, tmp_path):
    # Regression test for a real defect: loading a settings profile while
    # the pump is disconnected calls _apply_settings() against an *empty*
    # pump_unit combo. findData(flush_unit_index) on an empty combo always
    # returns -1, so the saved unit was silently lost -- and because Qt
    # makes the first item "current" by default once a combo is populated,
    # connecting the pump afterward could default to unit 1 regardless of
    # what was actually saved, with no indication anything was wrong.
    app = QApplication.instance() or QApplication(["test-flush-unit-pending"])
    controller1 = ApplicationController(DeviceRegistry(mode=OperatingMode.SIMULATION), mode=OperatingMode.SIMULATION)
    results1 = []
    controller1.command_result.connect(results1.append)
    controller1.start()
    window1 = MainWindow(controller1)
    try:
        _connect_pump_via_real_button(app, window1, results1)
        panel1 = window1.experiment_panel
        panel1.description.setText("Unit 1 selected")
        assert panel1.pump_unit.findData(1) >= 0
        panel1.pump_unit.setCurrentIndex(panel1.pump_unit.findData(1))
        path = tmp_path / "settings.json"
        window1.save_profile(path)
        document = json.loads(path.read_text(encoding="utf-8"))
        assert document["experiment"]["flush_unit_index"] == 1

        controller2 = ApplicationController(DeviceRegistry(mode=OperatingMode.SIMULATION), mode=OperatingMode.SIMULATION)
        results2 = []
        controller2.command_result.connect(results2.append)
        controller2.start()
        window2 = MainWindow(controller2)
        try:
            panel2 = window2.experiment_panel
            assert panel2.pump_unit.count() == 0  # nothing connected yet

            window2.load_profile(path)
            # Not silently replaced with "the first pump" (unit 0) or left
            # looking like nothing was ever saved: an explicit notice names
            # the saved-but-unavailable unit.
            assert panel2.pump_unit.currentData() is None
            assert "unit 2" in panel2.pump_unit_notice.text().lower()  # unit_index=1 is displayed as "Unit 2"
            assert "not available" in panel2.pump_unit_notice.text().lower()

            # Re-saving now (still disconnected) must not lose the pending
            # selection -- it was never applied to the combo, but it must
            # still be known.
            resaved_path = tmp_path / "resaved.json"
            window2.save_profile(resaved_path)
            resaved_document = json.loads(resaved_path.read_text(encoding="utf-8"))
            assert resaved_document["experiment"]["flush_unit_index"] == 1

            # Connecting the pump now restores the saved selection and
            # clears the notice -- the device list "appearing" is what
            # resolves the pending value, not an automatic connect.
            assert results2 == []
            _connect_pump_via_real_button(app, window2, results2)
            assert panel2.pump_unit.currentData() == 1
            assert panel2.pump_unit_notice.text() == ""
        finally:
            window2.close()
            controller2.shutdown()
    finally:
        window1.close()
        controller1.shutdown()


def test_experiment_tab_flush_unit_stays_unselected_when_the_saved_unit_never_appears(qt_app, tmp_path):
    # Regression test for a residual defect found by an independent
    # simulation after the first fix above landed: connecting a pump that
    # genuinely never offers the saved unit (not just "not yet, until
    # connected") must not silently fall back to whichever unit Qt would
    # otherwise default the freshly-populated combo to. The saved unit
    # must stay unresolved -- pending, visibly flagged, and excluded from
    # anything that would actually run an experiment -- not quietly
    # swapped for a different real pump.
    del qt_app
    controller1 = ApplicationController(DeviceRegistry(mode=OperatingMode.SIMULATION), mode=OperatingMode.SIMULATION)
    window1 = MainWindow(controller1)
    document = window1.profile_document()
    document["experiment"]["flush_unit_index"] = 1
    path = tmp_path / "unit-1.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    window1.close()
    controller1.shutdown()

    app = QApplication.instance() or QApplication(["test-flush-unit-never-appears"])
    # Only one unit (index 0) ever exists for this controller -- unit 1,
    # the saved value, can never become available no matter what connects.
    controller2 = ApplicationController(
        DeviceRegistry(mode=OperatingMode.SIMULATION,
                       factories={DeviceId.PUMP: lambda: SimulatedPumpBank(unit_count=1)}),
        mode=OperatingMode.SIMULATION)
    results2 = []
    controller2.command_result.connect(results2.append)
    controller2.start()
    window2 = MainWindow(controller2)
    try:
        panel2 = window2.experiment_panel
        window2.load_profile(path)
        assert panel2.pump_unit.currentData() is None
        assert "unit 2" in panel2.pump_unit_notice.text().lower()

        _connect_pump_via_real_button(app, window2, results2)
        # The only real unit (0) must NOT have been silently adopted --
        # neither as the combo's visible selection nor as what an
        # experiment would actually compile/queue against.
        assert panel2.pump_unit.count() == 1
        assert panel2.pump_unit.currentData() is None
        assert "unit 2" in panel2.pump_unit_notice.text().lower()
        assert "not available" in panel2.pump_unit_notice.text().lower()
        assert panel2._settings(require_pump_unit=False).flush_unit_index == 1  # still pending, not silently 0
        with pytest.raises(ValueError, match="Select a configured pump unit"):
            panel2._definition()  # must refuse to compile against the wrong unit, not succeed on unit 0

        # Still recoverable by saving again -- the pending value isn't
        # lost just because it turned out to be permanently unavailable
        # on this particular setup.
        resaved_path = tmp_path / "resaved.json"
        window2.save_profile(resaved_path)
        resaved_document = json.loads(resaved_path.read_text(encoding="utf-8"))
        assert resaved_document["experiment"]["flush_unit_index"] == 1
    finally:
        window2.close()
        controller2.shutdown()


def test_experiment_tab_flush_unit_notice_clears_once_the_user_picks_a_different_unit(qt_app, tmp_path):
    # Complementary scenario to the one above: the saved unit is
    # unavailable, but the operator deliberately picks one of the units
    # that *is* available instead of waiting for the saved one. That
    # explicit choice must take over cleanly -- the stale pending value
    # must not resurface later and override it (e.g. if a different pump
    # bank happens to be connected afterward).
    app = QApplication.instance() or QApplication(["test-flush-unit-explicit-reselect"])
    controller = ApplicationController(
        DeviceRegistry(mode=OperatingMode.SIMULATION,
                       factories={DeviceId.PUMP: lambda: SimulatedPumpBank(unit_count=1)}),
        mode=OperatingMode.SIMULATION)
    results = []
    controller.command_result.connect(results.append)
    controller.start()
    window = MainWindow(controller)
    try:
        panel = window.experiment_panel
        document = window.profile_document()
        document["experiment"]["flush_unit_index"] = 1  # never available on this controller's 1-unit bank
        path = tmp_path / "unit-1.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        window.load_profile(path)

        _connect_pump_via_real_button(app, window, results)
        assert panel.pump_unit.currentData() is None
        assert panel.pump_unit_notice.text() != ""

        # The operator explicitly selects the one available unit (0) --
        # a real combo interaction, not an internal call.
        panel.pump_unit.setCurrentIndex(panel.pump_unit.findData(0))
        assert panel.pump_unit.currentData() == 0
        assert panel.pump_unit_notice.text() == ""  # the stale notice must not linger
        assert panel._settings(require_pump_unit=False).flush_unit_index == 0
        assert panel._definition()  # now compiles cleanly against the chosen unit

        # The abandoned pending value must not come back on its own --
        # not even if _devices() runs again for an unrelated reason (the
        # same pump reporting updated status, say).
        panel._devices(controller.statuses())
        assert panel.pump_unit.currentData() == 0
    finally:
        window.close()
        controller.shutdown()


def test_experiment_tab_settings_profile_is_optional_for_backward_compatibility(qt_app, tmp_path):
    # An existing device-settings file saved before this feature existed
    # has no "experiment" key at all -- loading it must still work and
    # must leave the Experiment tab's own inputs untouched, not reset them
    # to defaults or raise.
    del qt_app
    controller = ApplicationController(DeviceRegistry(mode=OperatingMode.SIMULATION), mode=OperatingMode.SIMULATION)
    window = MainWindow(controller)
    panel = window.experiment_panel
    panel.description.setText("Untouched by an old-format load")
    panel.repeats.setValue(7)
    before = panel._settings(require_pump_unit=False)

    old_style_document = {"schema_version": 2, "devices": {}}
    path = tmp_path / "old-style.json"
    path.write_text(json.dumps(old_style_document), encoding="utf-8")

    window.load_profile(path)  # must not raise
    after = panel._settings(require_pump_unit=False)
    assert after == before


def test_experiment_tab_settings_profile_save_handles_a_disconnected_pump(qt_app, tmp_path):
    # Saving the form must not require a pump to be connected, unlike
    # actually compiling/queuing/running a series -- confirmed directly
    # against the saved document, not just that save_profile() didn't raise.
    del qt_app
    controller = ApplicationController(DeviceRegistry(mode=OperatingMode.SIMULATION), mode=OperatingMode.SIMULATION)
    window = MainWindow(controller)
    assert window.experiment_panel.pump_unit.currentData() is None
    with pytest.raises(ValueError, match="Select a configured pump unit"):
        window.experiment_panel._definition()  # the behavior this test must NOT change

    path = tmp_path / "settings.json"
    window.save_profile(path)
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["experiment"]["flush_unit_index"] is None


def test_experiment_tab_settings_profile_rejects_malformed_experiment_data(qt_app, tmp_path):
    del qt_app
    controller = ApplicationController(DeviceRegistry(mode=OperatingMode.SIMULATION), mode=OperatingMode.SIMULATION)
    window = MainWindow(controller)
    original_repeats = window.experiment_panel.repeats.value()
    path = tmp_path / "invalid-experiment.json"

    document = window.profile_document()
    document["experiment"]["not_a_real_field"] = 1
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="Unknown experiment setting"):
        window.load_profile(path)
    assert window.experiment_panel.repeats.value() == original_repeats

    document = window.profile_document()
    document["experiment"]["frequency_hz"] = {"start": 1, "stop": 2}  # missing "steps"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="start/stop/steps object"):
        window.load_profile(path)

    document = window.profile_document()
    document["experiment"]["roi"] = [1, 2, 3]  # needs exactly 4 elements
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="roi must be a 4-element array"):
        window.load_profile(path)

    document = window.profile_document()
    document["experiment"] = "not an object"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="must be an object"):
        window.load_profile(path)

    # Regression case for a real defect found by an independent simulation
    # (Codex): a profile with a new, otherwise-legal repeats value but a
    # wrong-typed frame_count used to raise a TypeError from deep inside
    # _apply_settings()'s widget-setting loop -- AFTER repeats had already
    # been applied to the real widget, since SimpleSeriesSettings and
    # NumericRange are plain dataclasses that never checked field types at
    # construction time. The fix validates every field's type up front, in
    # simple_series_settings_from_profile(), before _apply_settings() is
    # ever called -- so a rejected load leaves every field, including the
    # ones listed earlier in the widget-setting loop, exactly as they were.
    document = window.profile_document()
    document["experiment"]["repeats"] = original_repeats + 5
    document["experiment"]["frame_count"] = "two"  # wrong type, not just an unknown field
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="frame_count must be an integer"):
        window.load_profile(path)
    assert window.experiment_panel.repeats.value() == original_repeats  # not the new value

    # Residual gap found by an independent simulation (Codex), right after
    # the type-check fix above landed: a correctly-TYPED but out-of-range
    # integer (frame_count's QSpinBox only goes up to 100_000) is not
    # caught by simple_series_settings_from_profile() at all -- that
    # function has no widget to check a range against. QSpinBox.setValue()
    # does not reject such a value gracefully either: a merely-too-large
    # one (confirmed directly: 50_000 against a 1..1_000 range) is
    # silently CLAMPED, not rejected, which would have quietly accepted a
    # value the profile never actually asked for; one beyond the C `int`
    # range raises a raw OverflowError, reproducing the exact same
    # "repeats already applied, frame_count blew up" half-application the
    # earlier fix was supposed to close. Fixed with
    # SimpleSeriesPanel._validate_settings_ranges(), called from
    # load_profile() against this panel's own live widget ranges, before
    # _apply_settings() runs.
    document = window.profile_document()
    document["experiment"]["repeats"] = original_repeats + 5
    document["experiment"]["frame_count"] = 999_999_999  # correctly typed, far outside the QSpinBox's 1..100_000
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="frame_count"):
        window.load_profile(path)
    assert window.experiment_panel.repeats.value() == original_repeats  # not the new value
    assert window.experiment_panel.frames.value() != 999_999_999  # not silently clamped into looking accepted


def test_experiment_tab_valid_non_default_profile_still_round_trips_after_the_type_check(qt_app, tmp_path):
    # Confirms the new up-front type validation (added alongside the fix
    # above) does not reject a genuinely valid, non-default configuration
    # -- every field type used across the test suite's other non-default
    # profiles (ints, floats, bools, strings, NumericRange objects, a
    # 4-element roi, and a null flush_unit_index/tec_channel) must still
    # pass.
    del qt_app
    controller = ApplicationController(DeviceRegistry(mode=OperatingMode.SIMULATION), mode=OperatingMode.SIMULATION)
    window = MainWindow(controller)
    panel = window.experiment_panel
    panel.description.setText("Valid non-default configuration")
    panel.repeats.setValue(4)
    panel.frames.setValue(6)
    panel.fps.setValue(15)
    panel.sweep_enabled.setChecked(True)
    for widget, value in zip(panel.sweep_width, (50_000, 150_000, 3)):
        widget.setValue(value)
    panel.temperature_control.setChecked(True)
    for widget, value in zip(panel.temperature, (15, 35, 3)):
        widget.setValue(value)
    panel.temperature_logging.setChecked(True)
    panel.temperature_wait_for_stability.setChecked(True)

    path = tmp_path / "valid-non-default.json"
    window.save_profile(path)
    window.load_profile(path)  # must not raise
    assert panel.repeats.value() == 4
    assert panel.frames.value() == 6
    assert panel.sweep_enabled.isChecked() is True
    assert panel.temperature_wait_for_stability.isChecked() is True


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
    CameraReadback,
    CameraRoiLimitsReadback,
    CameraRoiReadback,
    IntegerRange,


def _viewer(qt_app):
    panel = CameraPanel()
    viewer = panel.image_window
    viewer.resize(900, 700)
    viewer.show()
    qt_app.processEvents()
    return panel, viewer


def test_camera_display_adjustments_never_change_raw_frame(qt_app):
    _panel, viewer = _viewer(qt_app)
    frame = np.arange(64 * 48, dtype=np.uint16).reshape(48, 64) * 7
    original = frame.copy()
    viewer.show_frame(frame, "x")
    viewer.adjust_intensity_button.click()
    viewer.robust_button.click()
    viewer.limit_low.setValue(100)
    viewer.limit_high.setValue(2000)
    viewer.limit_apply_button.click()
    viewer.zoom_in_button.click()
    viewer.full_range_button.click()
    assert np.array_equal(frame, original)
    assert np.array_equal(viewer.preview.raw_frame, original)
    viewer.close()


def test_camera_fixed_range_persists_across_frames_and_autoscale_is_per_frame(qt_app):
    _panel, viewer = _viewer(qt_app)
    viewer.show_frame(np.full((8, 8), 500, dtype=np.uint16), "x")
    viewer.limit_low.setValue(100)
    viewer.limit_high.setValue(900)
    viewer.limit_apply_button.click()
    assert viewer.preview.display_limits == (100, 900)
    viewer.show_frame(np.full((8, 8), 20000, dtype=np.uint16), "x")
    viewer.show_frame(np.full((8, 8), 30000, dtype=np.uint16), "x")
    assert viewer.preview.display_limits == (100, 900)
    viewer.limit_low.setValue(900)
    viewer.limit_high.setValue(900)
    viewer.limit_apply_button.click()
    assert viewer.preview.display_limits == (100, 900)  # invalid range rejected
    viewer.autoscale_checkbox.setChecked(True)
    viewer.show_frame(np.array([[10, 20], [30, 40]], dtype=np.uint16), "x")
    assert viewer.preview.display_limits == (10, 40)
    viewer.show_frame(np.array([[50, 60], [70, 80]], dtype=np.uint16), "x")
    assert viewer.preview.display_limits == (50, 80)
    viewer.close()


def test_robust_stretch_ignores_isolated_hot_pixel_and_handles_constant_image():
    from thermo_acoustic.ui.widgets import robust_display_limits
    rng = np.random.default_rng(1)
    frame = rng.integers(1000, 2000, size=(200, 200), dtype=np.uint16)
    frame[3, 3] = 65535
    frame[5, 5] = 0
    low, high = robust_display_limits(frame)
    assert frame.min() == 0 and frame.max() == 65535
    assert 1000 <= low < high <= 2000
    assert robust_display_limits(np.full((10, 10), 4321, dtype=np.uint16)) == (4321, 4322)
    assert robust_display_limits(np.full((10, 10), 65535, dtype=np.uint16)) == (65534, 65535)
    assert robust_display_limits(np.zeros((4, 4), dtype=np.float32)) is None


def test_camera_robust_button_sets_fixed_limits_then_keeps_them(qt_app):
    _panel, viewer = _viewer(qt_app)
    frame = np.full((50, 50), 1500, dtype=np.uint16)
    frame[0:25] = 1200
    frame[10, 10] = 65535
    viewer.show_frame(frame, "x")
    viewer.robust_button.click()
    limits = viewer.preview.display_limits
    assert limits is not None and limits[1] < 65535
    viewer.show_frame(frame + 1, "x")
    assert viewer.preview.display_limits == limits
    viewer.close()


def test_camera_zoom_and_pan_map_to_correct_raw_pixels(qt_app):
    _panel, viewer = _viewer(qt_app)
    preview = viewer.preview
    frame = np.arange(1200 * 1600, dtype=np.uint16).reshape(1200, 1600)
    viewer.show_frame(frame, "x")
    assert preview.is_fit
    target = preview.image_target_rect()
    x, y, value = preview.pixel_at(QPointF(target.center()))
    assert value == int(frame[y, x])
    viewer.zoom_100_button.click()
    assert not preview.is_fit
    # Zoom at the cursor keeps the pixel under the cursor.
    anchor = QPointF(target.center().x() + 30, target.center().y() + 10)
    before = preview.pixel_at(anchor)
    preview.zoom_by(2.0, anchor)
    assert preview.pixel_at(anchor)[:2] == before[:2]
    # Every sampled widget position reads the raw value of the pixel it names.
    rect = preview.image_target_rect()
    for fx, fy in ((0.1, 0.1), (0.5, 0.5), (0.9, 0.8)):
        pos = QPointF(rect.x() + fx * rect.width(), rect.y() + fy * rect.height())
        px, py, val = preview.pixel_at(pos)
        assert val == int(frame[py, px])
    # Panning moves the visible source rectangle without changing raw data.
    source_before = preview.visible_source_rect()
    preview._center = QPointF(preview._center.x() + 5, preview._center.y())
    assert preview.visible_source_rect() != source_before
    assert np.array_equal(preview.raw_frame, frame)
    viewer.fit_button.click()
    assert preview.is_fit
    viewer.close()


def test_camera_zoom_resets_to_fit_when_image_size_changes(qt_app):
    _panel, viewer = _viewer(qt_app)
    viewer.show_frame(np.zeros((1200, 1600), dtype=np.uint16), "x")
    viewer.zoom_100_button.click()
    viewer.show_frame(np.zeros((1200, 1600), dtype=np.uint16), "x")
    assert not viewer.preview.is_fit  # same shape keeps the operator's view
    viewer.show_frame(np.zeros((900, 1000), dtype=np.uint16), "x")
    assert viewer.preview.is_fit
    viewer.close()


def test_camera_preview_state_distinguishes_running_stopped_waiting_and_failed(qt_app):
    from datetime import datetime, timedelta
    from thermo_acoustic.application.commands import DeviceOperation
    now = [datetime(2026, 1, 1, 12, 0, 0)]
    panel, viewer = _viewer(qt_app)
    viewer._clock = lambda: now[0]
    assert "No acquisition yet" in viewer.preview_state.text()
    panel._show_image_window("Waiting for camera frame")
    assert "Waiting" in viewer.preview_state.text()
    viewer.set_camera_state(connected=True, fault=None, capture_active=True, mode="continuous", exposure_ms=12.5)
    assert "waiting for first frame" in viewer.preview_state.text()
    viewer.show_frame(np.zeros((6, 8), dtype=np.uint16), "x")
    assert viewer.preview_state.text() == "Preview running"
    assert "8 × 6" in viewer.frame_info.text() and "12.5 ms" in viewer.frame_info.text()
    assert "12:00:00" in viewer.frame_info.text()
    now[0] += timedelta(seconds=10)
    viewer._render_state()
    assert "no new frame" in viewer.preview_state.text()
    viewer.set_camera_state(connected=True, fault=None, capture_active=False, mode="continuous", exposure_ms=None)
    assert viewer.preview_state.text() == "Preview stopped"
    assert "not reported" in viewer.frame_info.text()
    event = type("E", (), {
        "operation": DeviceOperation.CAMERA_CONTINUOUS_CAPTURE, "state": "failed", "message": "no camera"})()
    panel.handle_terminal_event(event)
    assert viewer.preview_state.text() == "Preview failed: no camera"
    viewer.set_camera_state(connected=False, fault=None, capture_active=False, mode=None, exposure_ms=None)
    viewer.end_waiting()
    viewer._failure = None
    viewer._render_state()
    assert "disconnected" in viewer.preview_state.text()
    viewer.close()


def test_camera_viewer_stays_closed_until_operator_starts_new_acquisition(qt_app):
    panel, viewer = _viewer(qt_app)
    viewer.show_frame(np.zeros((4, 4), dtype=np.uint16), "x")
    viewer.close()
    viewer.show_frame(np.ones((4, 4), dtype=np.uint16), "x")
    assert not viewer.isVisible()
    panel._show_image_window("Waiting for camera frame")
    assert viewer.isVisible()
    viewer.close()


def test_camera_large_image_display_operations_stay_responsive(qt_app):
    import time
    _panel, viewer = _viewer(qt_app)
    rng = np.random.default_rng(0)
    frame = rng.integers(0, 65536, size=(2048, 2048), dtype=np.uint16)
    timings = {}
    start = time.perf_counter()
    viewer.show_frame(frame, "x")
    qt_app.processEvents()
    timings["show_frame"] = time.perf_counter() - start
    for name, action in (("robust", viewer.robust_button.click), ("zoom_in", viewer.zoom_in_button.click),
                         ("fit", viewer.fit_button.click), ("next_frame", lambda: viewer.show_frame(frame, "x"))):
        start = time.perf_counter()
        action()
        qt_app.processEvents()
        timings[name] = time.perf_counter() - start
    print("TIMINGS_MS", {key: round(value * 1000, 1) for key, value in timings.items()})
    # Generous bound: catches a real regression, not a slow machine.
    assert max(timings.values()) < 1.5, timings
    viewer.close()


@pytest.mark.parametrize("shape", [(30, 40), (1200, 1600)], ids=["smaller_than_viewport", "larger_than_viewport"])
@pytest.mark.parametrize("ratio", [1.0, 2.0], ids=["dpr1", "dpr2"])
def test_camera_100_percent_is_exact_and_independent_of_fit(qt_app, shape, ratio):
    _panel, viewer = _viewer(qt_app)
    preview = viewer.preview
    preview.devicePixelRatioF = lambda: ratio
    frame = np.arange(shape[0] * shape[1], dtype=np.uint16).reshape(shape)
    viewer.show_frame(frame, "x")
    assert preview.is_fit
    fit_percent = preview.zoom_percent()
    viewer.zoom_100_button.click()
    assert not preview.is_fit
    assert preview.zoom_percent() == pytest.approx(100.0)
    # 1 image pixel == 1 physical pixel == 1/ratio logical pixels.
    assert preview.effective_scale() == pytest.approx(1.0 / ratio)
    area = preview.contentsRect()
    target = preview.image_target_rect()
    expected_w = min(shape[1], area.width() * ratio) / ratio
    expected_h = min(shape[0], area.height() * ratio) / ratio
    assert target.width() == pytest.approx(expected_w)
    assert target.height() == pytest.approx(expected_h)
    if shape == (30, 40):
        assert fit_percent > 100.0  # Fit enlarges it; 100% must not
        assert viewer.zoom_label.text() == "Zoom: Manual (100%)"
    # Raw readout matches the displayed geometry at both ends of the target.
    source = preview.visible_source_rect()
    x0, y0 = int(source.x()), int(source.y())
    assert preview.pixel_at(QPointF(target.x() + 0.2, target.y() + 0.2)) == (x0, y0, int(frame[y0, x0]))
    last = preview.pixel_at(QPointF(target.right() - 0.2, target.bottom() - 0.2))
    assert last[2] == int(frame[last[1], last[0]])
    # Zooming out below Fit and back; Fit is a separate, reachable mode.
    preview.zoom_by(0.25, QPointF(area.center()))
    assert not preview.is_fit and preview.zoom_percent() == pytest.approx(25.0)
    px = preview.pixel_at(QPointF(preview.image_target_rect().center()))
    assert px[2] == int(frame[px[1], px[0]])
    viewer.fit_button.click()
    assert preview.is_fit and preview.zoom_percent() == pytest.approx(fit_percent)
    assert np.array_equal(preview.raw_frame, frame)
    viewer.close()
