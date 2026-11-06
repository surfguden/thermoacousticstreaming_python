"""Everyday controls on the Prepare tab: same controls, same commands, same rules as the device pages.

The Prepare tab does not copy controls; it takes them over from the device panels. These tests check
that moving them kept what matters: commands and parameters, no action from just looking, saved
settings, experiment locking, and that the detail pages still hold the rest.
"""

from __future__ import annotations

from time import monotonic, sleep

import pytest
from PySide6.QtWidgets import QApplication, QWidget

from thermo_acoustic.application import ApplicationController
from thermo_acoustic.application.commands import DeviceOperation
from thermo_acoustic.domain.models import ConnectionState, DeviceId, OperatingMode
from thermo_acoustic.hal.registry import DeviceRegistry
from thermo_acoustic.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication(["test-prepare-workbench"])


@pytest.fixture
def env(qt_app):
    controller = ApplicationController(DeviceRegistry(), mode=OperatingMode.SIMULATION)
    events = []
    controller.command_event.connect(events.append)
    controller.start()
    window = MainWindow(controller)
    window.show()

    def wait(condition, timeout=8):
        deadline = monotonic() + timeout
        while monotonic() < deadline and not condition():
            qt_app.processEvents()
            sleep(0.01)
        assert condition()

    yield window, controller, events, wait
    window.close()
    controller.shutdown()


def _inside(widget: QWidget, ancestor: QWidget) -> bool:
    while widget is not None:
        if widget is ancestor:
            return True
        widget = widget.parentWidget()
    return False


def _connect(window, wait, *devices):
    for device in devices:
        window.panels[device]._buttons["connect"].click()
    wait(lambda: all(window.controller.statuses()[d].connection is ConnectionState.CONNECTED for d in devices))


def test_everyday_controls_live_on_prepare_and_detail_controls_stay_on_the_device_page(env):
    window, controller, events, wait = env
    prepare = window.prepare_panel
    pump, camera, stage, tec = (window.panels[d] for d in (DeviceId.PUMP, DeviceId.CAMERA,
                                                           DeviceId.Z_STAGE, DeviceId.TEC))
    _connect(window, wait, DeviceId.PUMP)
    for key in ("refill_0", "empty_0", "stop_0", "level_0", "flow_0"):
        assert _inside(pump._buttons[key], prepare), key
    for key in ("valve_1_0", "reference_0", "syringe_0"):  # low-frequency pump operations
        assert _inside(pump._buttons[key], pump) and not _inside(pump._buttons[key], prepare), key
    for key in ("snapshot", "continuous", "capture_stop", "exposure", "roi", "center_roi"):
        assert _inside(camera._buttons[key], prepare), key
    for key in ("sequence", "sequence_save"):
        assert not _inside(camera._buttons[key], prepare), key
    assert _inside(camera.show_image_button, prepare)
    for key in ("requirement", "enable", "move", "read", "up", "down"):
        assert _inside(stage._buttons[key], prepare), key
    for key in ("apply", "wait", "read", "off"):
        assert _inside(tec._buttons[key], prepare), key
    assert not _inside(tec.port, prepare)  # connection inputs stay with the device page


def test_looking_at_prepare_and_folding_sections_sends_nothing(env):
    window, controller, events, wait = env
    prepare = window.prepare_panel
    window.show_workspace("prepare")
    for section in (prepare.pump_section, prepare.imaging_section, prepare.temperature_section):
        section.set_expanded(True)
        section.set_expanded(False)
    for _ in range(20):
        QApplication.processEvents()
    assert events == []


def test_prepare_buttons_send_the_same_commands_as_before_the_move(env):
    window, controller, events, wait = env
    _connect(window, wait, DeviceId.PUMP, DeviceId.CAMERA, DeviceId.TEC)
    sent = []
    for device in (DeviceId.PUMP, DeviceId.CAMERA, DeviceId.TEC):
        window.panels[device].command_requested.connect(lambda action, command: sent.append(command))
    window.panels[DeviceId.PUMP]._buttons["refill_0"].click()
    wait(lambda: any(e.operation is DeviceOperation.PUMP_REFILL and e.state == "completed" for e in events))
    camera = window.panels[DeviceId.CAMERA]
    camera.exposure.setValue(3.5)
    camera._buttons["exposure"].click()
    tec = window.panels[DeviceId.TEC]
    tec.target.setValue(30.0)
    tec._buttons["apply"].click()
    wait(lambda: any(e.operation is DeviceOperation.TEC_SETPOINTS_APPLY and e.state == "completed"
                     for e in events))
    by_operation = {c.operation: c for c in sent}
    assert by_operation[DeviceOperation.PUMP_REFILL].arguments.unit_index == 0
    assert by_operation[DeviceOperation.CAMERA_EXPOSURE_CONFIGURE].arguments.exposure_ms == 3.5
    assert 30.0 in tuple(getattr(by_operation[DeviceOperation.TEC_SETPOINTS_APPLY].arguments, "targets_c", ())) \
        or "30.0" in repr(by_operation[DeviceOperation.TEC_SETPOINTS_APPLY].arguments)


def test_saved_settings_round_trip_with_controls_moved(env, tmp_path):
    window, controller, events, wait = env
    camera, tec, stage = (window.panels[d] for d in (DeviceId.CAMERA, DeviceId.TEC, DeviceId.Z_STAGE))
    camera.exposure.setValue(4.25)
    camera.roi_width.setValue(640)
    tec.target.setValue(31.5)
    stage.position.setValue(12.0)
    path = tmp_path / "settings.json"
    window.save_profile(path)
    camera.exposure.setValue(1.0)
    camera.roi_width.setValue(512)
    tec.target.setValue(25.0)
    stage.position.setValue(50.0)
    window.load_profile(path)
    assert camera.exposure.value() == 4.25 and camera.roi_width.value() == 640
    assert tec.target.value() == 31.5 and stage.position.value() == 12.0
    assert [e for e in events if e.state == "queued"] == []  # loading sends nothing


def test_experiment_lock_still_disables_the_moved_controls_but_stop_paths_stay_available(env):
    window, controller, events, wait = env
    _connect(window, wait, DeviceId.PUMP, DeviceId.CAMERA)
    pump, camera = window.panels[DeviceId.PUMP], window.panels[DeviceId.CAMERA]
    assert pump._buttons["refill_0"].isEnabled() and camera._buttons["exposure"].isEnabled()
    window._experiment_changed({**window._experiment_status, "state": "running"})
    assert not pump._buttons["refill_0"].isEnabled() and not camera._buttons["exposure"].isEnabled()
    assert not pump._buttons["level_0"].isEnabled()
    assert window.abort_button.isEnabled() and window.stop_after_button.isEnabled()
    assert window.panic_button.isEnabled()
    window._experiment_changed({**window._experiment_status, "state": "idle"})
    assert pump._buttons["refill_0"].isEnabled()


def test_device_pages_point_to_prepare_and_the_pointer_opens_it(env):
    window, controller, events, wait = env
    pointer_buttons = [b for b in window.panels[DeviceId.CAMERA].findChildren(type(window.configure_button_proxy))] \
        if hasattr(window, "configure_button_proxy") else []
    window.show_workspace("devices")
    window.panels[DeviceId.CAMERA].open_prepare_requested.emit()
    assert window.tabs.currentWidget() is window._scroll_pages[window.prepare_panel]
    window.prepare_panel.configure_button.click()
    assert window.tabs.currentWidget() is window.experiment_panel
    assert window.experiment_panel.pages.currentIndex() == 0


def test_pump_fill_bar_is_drawn_only_from_known_level_and_capacity(env):
    from thermo_acoustic.domain.models import PumpReadback, PumpUnitReadback
    window, controller, events, wait = env
    pump = window.panels[DeviceId.PUMP]
    show = lambda unit: (pump.update_readback(PumpReadback(units=(unit,))), pump.tiles_layout.itemAtPosition(0, 0).widget())[1]
    group = show(PumpUnitReadback(0, fill_level_ml=0.5, max_volume_ml=1.0))
    assert not group.fill_bar.isHidden() and group.fill_bar.value() == 500
    group = show(PumpUnitReadback(0, fill_level_ml=0.5, max_volume_ml=None))  # capacity unknown: no invented scale
    assert group.fill_bar.isHidden() and "capacity unknown" in group.volume_label.text()
    group = show(PumpUnitReadback(0, fill_level_ml=None, max_volume_ml=1.0))
    assert group.fill_bar.isHidden() and group.volume_label.text() == "—"


def test_image_viewer_docks_and_pops_out_without_any_device_command(env):
    window, controller, events, wait = env
    camera, prepare = window.panels[DeviceId.CAMERA], window.prepare_panel
    assert camera.image_docked and _inside(camera.image_window, prepare)
    prepare.pop_button.click()
    assert not camera.image_docked and not _inside(camera.image_window, prepare)
    prepare.pop_button.click()
    assert camera.image_docked and _inside(camera.image_window, prepare)
    camera.image_window.close() if not camera.image_docked else None
    assert [e for e in events if e.state == "queued"] == []


def test_requested_temperature_is_kept_apart_from_the_reported_target(env):
    window, controller, events, wait = env
    _connect(window, wait, DeviceId.TEC)
    tec = window.panels[DeviceId.TEC]
    assert tec.table.item(0, 2) is None or tec.table.item(0, 2).text() == "—"  # nothing requested yet
    tec.target.setValue(27.5)
    tec._buttons["apply"].click()
    wait(lambda: any(e.operation is DeviceOperation.TEC_SETPOINTS_APPLY and e.state == "completed" for e in events))
    wait(lambda: tec.table.item(0, 2) is not None and tec.table.item(0, 2).text() == "27.5")
    assert tec.table.horizontalHeaderItem(3).text() == "Reported target °C"


def test_valve_ad2_and_manual_flush_controls_are_in_prepare_and_send_their_usual_commands(env):
    from thermo_acoustic.application.commands import WorkflowOperation
    window, controller, events, wait = env
    _connect(window, wait, DeviceId.PUMP, DeviceId.VALVE, DeviceId.AD2)
    prepare = window.prepare_panel
    valve, ad2 = window.panels[DeviceId.VALVE], window.panels[DeviceId.AD2]
    assert _inside(valve._buttons["set"], prepare) and not _inside(valve.port, prepare)
    assert _inside(ad2._buttons["wave_stop_quick"], prepare) and not _inside(ad2._buttons["wave_start"], prepare)
    assert _inside(window.workflow_panel.flush_button, prepare)
    valve.position.setCurrentIndex(1)
    valve._buttons["set"].click()
    wait(lambda: any(e.operation is DeviceOperation.VALVE_POSITION_SET and e.state == "completed" for e in events))
    assert [e for e in events if e.operation is DeviceOperation.VALVE_POSITION_SET][0].arguments.position == 2
    ad2._buttons["wave_stop_quick"].click()
    wait(lambda: any(e.operation is DeviceOperation.AD2_WAVEFORM_STOP and e.state == "completed" for e in events))
    wait(lambda: window.panels[DeviceId.PUMP].tiles_layout.count() > 0)
    flush = window.workflow_panel
    flush.unit.setCurrentIndex(1)
    flush.flush_button.click()
    wait(lambda: any(e.operation is WorkflowOperation.FLUSH and e.state in {"completed", "failed"} for e in events))
    assert [e for e in events if e.operation is WorkflowOperation.FLUSH][0].arguments.unit_index == 0


def test_stopping_a_manual_output_is_blocked_while_a_batch_owns_the_instruments(env):
    window, controller, events, wait = env
    _connect(window, wait, DeviceId.AD2)
    ad2 = window.panels[DeviceId.AD2]
    assert ad2._buttons["wave_stop_quick"].isEnabled()
    window._experiment_changed({**window._experiment_status, "state": "running"})
    assert not ad2._buttons["wave_stop_quick"].isEnabled() and not ad2._buttons["do_stop_quick"].isEnabled()
    assert window.abort_button.isEnabled() and window.panic_button.isEnabled()  # the experiment is stopped there


def test_tec_wait_reports_its_end(env):
    window, controller, events, wait = env
    _connect(window, wait, DeviceId.TEC)
    tec = window.panels[DeviceId.TEC]
    tec.target.setValue(25.0)
    tec._buttons["apply"].click()
    wait(lambda: any(e.operation is DeviceOperation.TEC_SETPOINTS_APPLY and e.state == "completed" for e in events))
    tec.settle.setValue(0.2)
    tec._buttons["wait"].click()
    wait(lambda: "pending" not in tec._buttons["wait"].text(), timeout=20)
    assert "wait stable" in tec.notice_label.text() and "done" in tec.notice_label.text()
    assert tec._buttons["wait"].isEnabled()  # connected or applied never meant "stable"; this reports the wait


def test_tec_wait_that_never_reaches_the_target_fails_with_the_reason_on_the_page(qt_app):
    from thermo_acoustic.drivers.tec.simulated import SimulatedTec

    class FarTec(SimulatedTec):  # reports a temperature 10 degrees away from any target
        def read_status(self, channels=None):
            status = super().read_status(channels)
            return {c: type(s)(channel=c, current_temperature_c=(s.target_temperature_c or 25.0) + 10.0,
                               target_temperature_c=s.target_temperature_c, output_stage_static_on=True, ready=True)
                    for c, s in status.items()}

    controller = ApplicationController(DeviceRegistry(factories={DeviceId.TEC: FarTec}), mode=OperatingMode.SIMULATION)
    controller.start()
    window = MainWindow(controller)
    window.show()
    try:
        tec = window.panels[DeviceId.TEC]
        tec._buttons["connect"].click()
        deadline = monotonic() + 8
        while monotonic() < deadline and controller.statuses()[DeviceId.TEC].connection is not ConnectionState.CONNECTED:
            qt_app.processEvents(); sleep(0.01)
        tec.target.setValue(25.0)
        tec.max_wait.setValue(0.6)
        tec.poll.setValue(0.05)
        tec.settle.setValue(0.1)
        tec._buttons["wait"].click()
        deadline = monotonic() + 15
        while monotonic() < deadline and "pending" in tec._buttons["wait"].text():
            qt_app.processEvents(); sleep(0.01)
        assert tec._buttons["wait"].isEnabled()  # the page is usable again after the failure
        text = tec.notice_label.text().lower()
        assert "failed" in text and ("stab" in text or "wait" in text or "reach" in text)
        assert "connected" in tec.connection_label.text().lower()  # a failed wait is not a lost connection
    finally:
        window.close()
        controller.shutdown()


def test_tec_wait_can_be_cancelled_and_regulation_stays_on(qt_app):
    from thermo_acoustic.drivers.tec.simulated import SimulatedTec

    class NeverStable(SimulatedTec):  # keeps the wait running: always 10 degrees from the target
        def read_status(self, channels=None):
            status = super().read_status(channels)
            return {c: type(s)(channel=c, current_temperature_c=(s.target_temperature_c or 25.0) + 10.0,
                               target_temperature_c=s.target_temperature_c, output_stage_static_on=self.outputs_enabled,
                               ready=True) for c, s in status.items()}

    controller = ApplicationController(DeviceRegistry(factories={DeviceId.TEC: NeverStable}),
                                       mode=OperatingMode.SIMULATION)
    controller.start()
    window = MainWindow(controller)
    window.show()

    def until(condition, timeout=15):
        deadline = monotonic() + timeout
        while monotonic() < deadline and not condition():
            qt_app.processEvents(); sleep(0.01)
        assert condition()
    try:
        tec = window.panels[DeviceId.TEC]
        tec._buttons["connect"].click()
        until(lambda: controller.statuses()[DeviceId.TEC].connection is ConnectionState.CONNECTED)
        tec.target.setValue(25.0)
        tec._buttons["apply"].click()
        until(lambda: tec._buttons["apply"].isEnabled() and controller.statuses()[DeviceId.TEC].configured)
        tec.max_wait.setValue(60.0)
        tec.poll.setValue(0.05)
        tec._buttons["wait"].click()
        until(lambda: "pending" in tec._buttons["wait"].text() and tec._buttons["abort"].isEnabled())
        sleep(0.3)
        assert "pending" in tec._buttons["wait"].text()  # still waiting; the fake never settles
        tec._buttons["abort"].click()  # the existing cancel entry
        until(lambda: "pending" not in tec._buttons["wait"].text())
        assert tec._buttons["wait"].isEnabled() and tec.notice_label.text()
        assert controller.statuses()[DeviceId.TEC].connection is ConnectionState.CONNECTED
        device = controller.registry.by_id(DeviceId.TEC).device
        assert any(getattr(d, "outputs_enabled", False) for d in (device, getattr(device, "driver", device)))
    finally:
        window.close()
        controller.shutdown()


def test_every_surface_says_connected_when_the_last_operation_failed(env):
    from thermo_acoustic.domain.models import DeviceStatus, TecChannelReadback, TecReadback
    window, controller, events, wait = env
    readback = TecReadback(channels=(TecChannelReadback(1, current_temperature_c=24.0, target_temperature_c=None,
                                                         output_enabled=True, ready=True),))
    failed = DeviceStatus(DeviceId.TEC, ConnectionState.ERROR, fault="wait timed out", readback=readback)
    controller._statuses[DeviceId.TEC] = failed
    window._status(controller.statuses())
    window.prepare_panel._refresh()
    texts = {
        "chips": window.connection_summary.text(),
        "table": window.prepare_panel.state_labels[DeviceId.TEC].text(),
        "summary": window.prepare_panel.temperature_section.summary.text(),
        "monitor": window.dashboard.rows[DeviceId.TEC].text(),
        "page": window.panels[DeviceId.TEC].connection_label.text(),
    }
    for where, text in texts.items():
        if where != "chips":  # the chips line also names the six devices that really are not connected
            assert "not connected" not in text.lower() and "disconnected" not in text.lower(), (where, text)
    assert "connected · last operation failed" in texts["chips"]
    assert "last operation failed" in texts["table"] and "operation failed" in texts["page"].lower()
    assert "24.00 °C" in texts["summary"] and "wait timed out" in texts["monitor"]
    assert "reported target none" in texts["summary"]  # unknown is written as unknown


def _surfaces(window):
    window.prepare_panel._refresh()
    return {"strip": window.panels[DeviceId.AD2].acoustic_status_label.text(),
            "summary": window.prepare_panel.acoustic_section.summary.text(),
            "monitor": window.dashboard.rows[DeviceId.AD2].text(),
            "page": window.panels[DeviceId.AD2].readback_label.text()}


def test_ad2_configuration_is_not_shown_as_a_running_output(env):
    window, controller, events, wait = env
    _connect(window, wait, DeviceId.AD2)
    ad2 = window.panels[DeviceId.AD2]

    def done(operation):
        return lambda: any(e.operation is operation and e.state == "completed" for e in events)

    def state_is(text):
        window._status(controller.statuses())
        return text in window.prepare_panel.acoustic_section.summary.text()
    wait(lambda: state_is("idle (nothing configured)"))  # nothing configured yet
    ad2._buttons["wave_config"].click()
    wait(done(DeviceOperation.AD2_WAVEFORM_CONFIGURE))
    wait(lambda: state_is("not running (configured"))
    for where, text in _surfaces(window).items():  # configured only: enabled in configuration, not running
        assert "running" not in text.replace("not running", "") or where == "page", (where, text)
    surfaces = _surfaces(window)
    assert "CH1 enabled" in surfaces["summary"] and "CH2 disabled" in surfaces["summary"]  # a disabled channel is said so
    assert "CH1 enabled" in surfaces["monitor"] and "not running" in surfaces["monitor"]
    ad2._buttons["wave_start"].click()
    wait(done(DeviceOperation.AD2_WAVEFORM_START))
    wait(lambda: state_is("waveform generator running"))
    for where, text in _surfaces(window).items():
        if where != "page":
            assert "waveform generator running" in text, (where, text)
    ad2._buttons["wave_stop"].click()
    wait(done(DeviceOperation.AD2_WAVEFORM_STOP))
    wait(lambda: state_is("not running (configured"))
    for where, text in _surfaces(window).items():  # stopped: no "on", still shown as configured, not as output
        assert "waveform generator running" not in text and " on " not in f" {text} ", (where, text)
        if where != "page":
            assert "CH1 enabled" in text and "not running" in text, (where, text)
    assert "not a running state" in ad2.readback_label.text()


def test_folded_summaries_always_name_their_device(env):
    """Connected, not connected and failed devices are all named; a valve reading never reads as the pump's."""
    window, controller, events, wait = env
    prepare = window.prepare_panel
    prepare._refresh()
    assert prepare.pump_section.summary.text().startswith("Pump: not connected")
    assert "Selector valve: not connected" in prepare.pump_section.summary.text()
    _connect(window, wait, DeviceId.PUMP, DeviceId.VALVE, DeviceId.CAMERA)
    prepare._refresh()
    text = prepare.pump_section.summary.text()
    pump_part, valve_part = text.split(" | ")
    assert pump_part.startswith("Pump: unit 1:") and "requested position" not in pump_part
    assert valve_part.startswith("Selector valve: requested position")
    assert prepare.imaging_section.summary.text().startswith("Camera: ")
    assert "Z-stage: not connected" in prepare.imaging_section.summary.text()


def test_frequency_summary_is_readable_and_the_exact_value_stays_available():
    from thermo_acoustic.ui.status_text import describe_condition, format_frequency
    assert format_frequency(1_000_000) == "1 MHz" and format_frequency(1_200_000.0) == "1.2 MHz"
    assert format_frequency(1_234_567.891) == "1.234567891 MHz" and format_frequency(999.5) == "999.5 Hz"
    assert format_frequency(50_000) == "50 kHz" and format_frequency(0) == "0 Hz"
    # the summary keeps 12 significant digits, so a very long value is rounded in it ...
    assert format_frequency(99_999_999.999999) == "100 MHz"
    # ... and the exact stored value is in the tooltip text, and in the input fields (see test_frequency_section)
    from thermo_acoustic.ui.status_text import exact_condition_text
    assert "frequency_hz = 99999999.999999" in exact_condition_text({"frequency_hz": 99_999_999.999999})
    assert describe_condition({"frequency_hz": 1e6, "sweep_width_hz": "NaN"}) == "frequency 1 MHz · sweep off"
    assert describe_condition({"frequency_hz": 1.2e6, "sweep_width_hz": 1e5}) == "frequency 1.2 MHz · sweep full width 100 kHz (1.15 MHz … 1.25 MHz), period not recorded"


def test_button_icons_and_stop_hierarchy_send_nothing(env):
    window, controller, events, wait = env
    before = len(events)
    assert not window.panic_button.icon().isNull()
    assert window.stop_after_button.icon().isNull() and window.abort_button.icon().isNull()  # text and colour rank them
    assert "background: #b71c1c" in window.panic_button.styleSheet() and "#ffe0b2" in window.abort_button.styleSheet()
    assert "background" not in window.stop_after_button.styleSheet()
    assert not window.panels[DeviceId.PUMP]._buttons["connect"].icon().isNull()
    assert len(events) == before  # looking at icons does not command a device


def test_tec_shows_only_the_current_mode_inputs_and_keeps_the_others(env):
    window, controller, events, wait = env
    tec = window.panels[DeviceId.TEC]
    assert not tec.target.isHidden() and tec.target_1.isHidden() and tec.target_2.isHidden()
    tec.target.setValue(31.5)
    tec.target_1.setValue(20.0)
    tec.target_2.setValue(22.0)
    tec.target_mode.setCurrentIndex(tec.target_mode.findData("per_channel"))
    assert tec.target.isHidden() and not tec.target_1.isHidden() and not tec.target_2.isHidden()
    assert tec._targets() == {1: 20.0, 2: 22.0}
    values = tec.profile_values()
    assert values["target_c"] == 31.5 and values["target_1_c"] == 20.0  # hidden values are still saved
    tec.target_mode.setCurrentIndex(tec.target_mode.findData("broadcast"))
    assert tec._targets() == 31.5 and tec.target.value() == 31.5


def test_valve_wait_settings_are_folded_but_still_used_and_z_leads_with_the_measured_position(env):
    window, controller, events, wait = env
    valve = window.panels[DeviceId.VALVE]
    assert not valve.wait_settings.is_expanded() and "timeout 1 s" in valve.wait_settings.summary.text()
    valve.wait_timeout.setValue(2.5)
    assert "timeout 2.5 s" in valve.wait_settings.summary.text()
    assert valve._wait_args().timeout_s == 2.5  # folded does not mean ignored
    z = window.panels[DeviceId.Z_STAGE]
    assert z.measured_label.text().startswith("Measured position:")
    assert {"move", "read", "up", "down", "requirement", "enable"} <= set(z._buttons)


def test_z_position_text_keeps_long_values_and_says_why_it_is_unread(env):
    from thermo_acoustic.domain.models import ZStageReadback
    window, controller, events, wait = env
    z = window.panels[DeviceId.Z_STAGE]
    z.update_readback(ZStageReadback(closed_loop=True, position_um=123456.789012, commanded_position_um=12.5))
    assert "123456.789 µm" in z.measured_label.text() and "closed loop on" in z.measured_label.text()
    z.update_readback(ZStageReadback(closed_loop=False))
    assert "not read; closed loop is off" in z.measured_label.text()  # nothing is invented
    z.update_readback(None)
    assert "not read yet" in z.measured_label.text()


def _hover_tooltip(window, button, wait_s=1.5):
    """Move the pointer over the button in the shown window and return the tooltip Qt really displays."""
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QToolTip
    QToolTip.hideText()
    settle = monotonic() + 0.4
    while monotonic() < settle:  # let the resized, shown window finish its layout
        QApplication.processEvents()
        sleep(0.01)
    QTest.mouseMove(window, button.mapTo(window, button.rect().bottomRight()))
    QTest.mouseMove(window, button.mapTo(window, button.rect().center()))
    deadline = monotonic() + wait_s
    while monotonic() < deadline and not QToolTip.isVisible():
        QApplication.processEvents()
        sleep(0.01)
    return QToolTip.text() if QToolTip.isVisible() else ""


def test_disabled_stop_buttons_give_the_real_reason_and_get_their_own_tooltip_back(env):
    window, controller, events, wait = env
    window.resize(1200, 800)
    base_abort = window._stop_tips[1]
    assert "Unavailable: no batch is running." in _hover_tooltip(window, window.abort_button)  # seen in the UI
    # Stop was requested: the button says so and the tooltip says what is being waited for.
    running = {**controller.experiments.status(), "state": "running", "stop_after_current": True}
    window._experiment_changed(running)
    assert window.stop_after_button.text() == "Stop requested" and not window.stop_after_button.isEnabled()
    assert "ends after the current experiment finishes" in window.stop_after_button.toolTip()
    assert window.abort_button.isEnabled() and window.abort_button.toolTip() == base_abort  # enabled: own text back
    # Panic stopping is not "no batch is running".
    window._panic_changed({**window._panic_status, "state": "stopping", "pending": 2})
    assert "Panic safe stop is in progress" in window.abort_button.toolTip()
    assert "no batch is running" not in window.abort_button.toolTip()
    assert "already in progress" in window.panic_button.toolTip() and not window.panic_button.isEnabled()
    window._panic_changed({**window._panic_status, "state": "idle", "pending": 0})
    window._experiment_changed({**controller.experiments.status(), "state": "running"})
    assert window.stop_after_button.isEnabled() and window.stop_after_button.toolTip() == window._stop_tips[0]
    assert window.panic_button.toolTip() == window._panic_tip


def test_the_second_pc_trigger_entry_says_it_waits_for_the_other_one(env):
    window, controller, events, wait = env
    _connect(window, wait, DeviceId.AD2)
    ad2 = window.panels[DeviceId.AD2]
    ad2._pending["wave_trigger_pc"] = "request-1"
    ad2._update_controls()
    other = ad2._buttons["do_trigger_pc"]
    assert not other.isEnabled() and "other tab" in other.toolTip() and "pending" in other.toolTip()
    assert "other tab" not in ad2._buttons["wave_trigger_pc"].toolTip()  # that one says its own request is pending
    assert "still pending" in ad2._buttons["wave_trigger_pc"].toolTip()
    ad2._pending.clear()
    ad2._update_controls()
    assert other.isEnabled() and "Unavailable" not in other.toolTip()  # enabled again: no leftover reason
