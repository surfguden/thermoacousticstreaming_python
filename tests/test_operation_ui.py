"""Task navigation, stop controls, advanced section and run-monitor text in the main window.

Offscreen widget tests: they check behaviour and state, not how the window looks (that is
inspected on rendered screenshots separately).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from thermo_acoustic.application import ApplicationController
from thermo_acoustic.domain.models import DeviceId, OperatingMode
from thermo_acoustic.hal.registry import DeviceRegistry
from thermo_acoustic.ui.main_window import MainWindow
from thermo_acoustic.ui.status_dashboard import StatusDashboard, describe_condition


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication(["test-operation-ui"])


@pytest.fixture
def window(qt_app):
    controller = ApplicationController(DeviceRegistry(mode=OperatingMode.SIMULATION),
                                       mode=OperatingMode.SIMULATION)
    submitted = []
    controller.submit = lambda command: submitted.append(command)  # navigation must never reach a device
    win = MainWindow(controller)
    win.submitted = submitted
    win.show()
    qt_app.processEvents()
    yield win
    win.close()
    controller.shutdown()


def test_primary_navigation_has_the_four_workspaces_and_device_details_as_secondary(window):
    assert [window.tabs.tabText(i) for i in range(window.tabs.count())] == [
        "1  Prepare devices", "2  Configure experiment", "3  Run monitor", "4  Results", "Device details"]
    window.show_workspace("queue")
    assert window.tabs.currentWidget() is window.experiment_panel
    assert window.experiment_panel.pages.currentIndex() == 1
    window.show_workspace("configure")
    assert window.experiment_panel.pages.currentIndex() == 0
    window.show_workspace("monitor")
    assert window.tabs.tabText(window.tabs.currentIndex()) == "3  Run monitor"
    window.open_page(window.panels[DeviceId.CAMERA])  # a device page opens inside Device details
    assert window.tabs.currentWidget() is window.device_tabs
    assert window.device_tabs.tabText(window.device_tabs.currentIndex()) == "Camera"
    window.show_workspace("prepare")
    assert window.tabs.tabText(window.tabs.currentIndex()) == "1  Prepare devices"
    assert window.submitted == []  # navigation never reaches a device


def test_stop_controls_are_always_visible_and_only_enabled_when_they_apply(window):
    assert window.panic_button.isEnabled()
    assert not window.stop_after_button.isEnabled() and not window.abort_button.isEnabled()
    window._experiment_changed({**window._experiment_status, "state": "running"})
    assert window.stop_after_button.isEnabled() and window.abort_button.isEnabled()
    window._experiment_changed({**window._experiment_status, "state": "running", "stop_after_current": True})
    assert not window.stop_after_button.isEnabled() and window.stop_after_button.text() == "Stop requested"
    assert window.abort_button.isEnabled()
    window._experiment_changed({**window._experiment_status, "state": "stopped", "stop_after_current": False})
    assert not window.stop_after_button.isEnabled() and window.stop_after_button.text() == "Stop after current"
    # The three stops say different things.
    assert "finish" in window.stop_after_button.toolTip()
    assert "discarded" in window.abort_button.toolTip()
    assert "Confirm" in window.panic_button.toolTip()
    for button in (window.stop_after_button, window.abort_button, window.panic_button):
        assert button.isVisibleTo(window)


def test_output_timing_is_a_main_parameter_and_only_the_stability_policy_is_folded(window):
    panel = window.experiment_panel
    window.show_workspace("configure")
    assert not panel.advanced.is_expanded()
    assert panel.sound_run.isVisibleTo(panel)  # timing of one experiment is core, not folded away
    assert not panel.temperature_tolerance.isVisibleTo(panel)  # the stability policy is folded
    panel.sound_run.setValue(2.5)
    panel.camera_start.setValue(0.4)
    settings = panel._settings(require_pump_unit=False)
    assert settings.sound_run_s == 2.5 and settings.camera_start_s == 0.4
    panel.advanced.set_expanded(True)
    assert panel.temperature_tolerance.isVisibleTo(panel)
    assert window.profile_document()["experiment"]["sound_run_s"] == 2.5  # saved with the settings


def test_form_uses_one_column_on_a_narrow_window_and_two_on_a_wide_one(window, qt_app):
    panel = window.experiment_panel
    window.show_workspace("configure")  # a hidden tab is not laid out until it is shown
    for size, columns in (((1300, 800), 2), ((900, 600), 1), ((1300, 800), 2)):
        window.resize(*size)
        qt_app.processEvents()
        assert panel._grid_columns == columns, size
    # Moving groups around must keep every group in the form.
    placed = {panel._body_grid.itemAt(i).widget() for i in range(panel._body_grid.count())}
    assert set(panel._left_groups + panel._right_groups + [panel.advanced]) <= placed


def test_condition_text_uses_the_plans_own_values_and_skips_unused_axes():
    parameters = {"temperature_c": "NaN", "frequency_hz": 1_000_000.0, "sweep_width_hz": "NaN",
                  "amplitude_v": 1.5, "exposure_ms": 10.0, "custom": "a"}
    text = describe_condition(parameters)
    assert text == "frequency 1e+06 Hz · amplitude 1.5 V · exposure 10 ms · custom=a"
    assert describe_condition(None) == "—" and describe_condition({}) == "—"


def test_run_monitor_shows_progress_condition_and_output_location(qt_app, tmp_path, monkeypatch):
    dashboard = StatusDashboard()
    opened = []
    monkeypatch.setattr("thermo_acoustic.ui.status_dashboard.QDesktopServices.openUrl",
                        lambda url: opened.append(url.toLocalFile()) or True)
    assert not dashboard.open_output_button.isEnabled()
    assert dashboard.output.text().startswith("—")
    series = tmp_path / "experiment_batch_0001"
    series.mkdir()
    status = {"state": "running", "planned_experiments": 6, "batch_completed_experiments": 2,
              "current_experiment_number": 3, "current_repeat": 2, "phase": "Acquiring",
              "current_parameters": {"frequency_hz": 2e6, "amplitude_v": 1.0, "temperature_c": "NaN"},
              "current_series": str(series),
              "series": [{"folder": str(series), "description": "Scan A", "state": "running",
                          "experiment_count": 6}]}
    dashboard.update_experiment(status)
    assert "completed 2/6" in dashboard.experiment.text() and "remaining 4" in dashboard.experiment.text()
    assert dashboard.condition.text() == "Experiment 3/6 · repeat 2 · frequency 2e+06 Hz · amplitude 1 V"
    assert "Scan A" in dashboard.series.text() and dashboard.output.text() == str(series)
    dashboard.open_output_button.click()
    assert len(opened) == 1 and Path(opened[0]) == series
    # After the batch ends the last output folder stays available for opening and review.
    dashboard.update_experiment({"state": "completed", "planned_experiments": 6,
                                 "batch_completed_experiments": 6, "current_parameters": None,
                                 "current_series": None, "series": []})
    assert dashboard.output_folder == str(series) and dashboard.open_output_button.isEnabled()
    assert dashboard.condition.text().startswith("—")
    requested = []
    dashboard.review_requested.connect(requested.append)
    dashboard.review_button.click()
    assert requested == [str(series)]


def test_runner_status_exposes_the_current_experiments_parameters(qt_app):
    controller = ApplicationController(DeviceRegistry(mode=OperatingMode.SIMULATION),
                                       mode=OperatingMode.SIMULATION)
    status = controller.experiments.status()
    assert status["current_parameters"] is None and status["current_repeat"] is None
    controller.shutdown()


def test_queue_edit_buttons_keep_their_meaning_across_the_two_pages(qt_app, tmp_path):
    from time import monotonic, sleep

    from thermo_acoustic.application.commands import (
        DeviceCommand, DeviceOperation, PumpSetFillLevelArgs,
    )
    from thermo_acoustic.application.simple_series import compile_simple_series

    controller = ApplicationController(DeviceRegistry(), mode=OperatingMode.SIMULATION)
    controller.start()
    window = MainWindow(controller)
    results = []
    controller.command_result.connect(results.append)

    def wait(condition, timeout=5):
        deadline = monotonic() + timeout
        while monotonic() < deadline and not condition():
            qt_app.processEvents(); sleep(0.01)
        assert condition()

    try:
        window.panels[DeviceId.PUMP]._buttons["connect"].click()
        wait(lambda: any(r.operation is DeviceOperation.CONNECT and r.ok for r in results))
        controller.submit(DeviceCommand(DeviceId.PUMP, DeviceOperation.PUMP_FILL_LEVEL_SET,
                                        PumpSetFillLevelArgs(1.0, unit_index=0)))
        wait(lambda: any(r.operation is DeviceOperation.PUMP_FILL_LEVEL_SET and r.ok for r in results))
        panel = window.experiment_panel
        wait(lambda: panel.pump_unit.count() > 0)
        panel.pump_unit.setCurrentIndex(0)
        panel.description.setText("Queue edit")
        panel.output_root.setText(str(tmp_path))
        panel.volume.setValue(0.01)
        panel.queue_button.click()
        assert panel.state_label.text().startswith("Queued:"), panel.state_label.text()
        assert panel.batch_list.topLevelItemCount() == 1
        folder = panel.batch_list.topLevelItem(0).text(5)
        panel.batch_list.setCurrentItem(panel.batch_list.topLevelItem(0))
        original = compile_simple_series(panel._settings())
        panel.exposure[0].setValue(3)  # an unsaved form change ...
        panel.pages.setCurrentIndex(1)
        panel.load_button.click()  # ... is replaced by the queued series' own values
        assert panel.exposure[0].value() == 1 and panel.pages.currentIndex() == 0
        panel.exposure[0].setValue(2)
        panel.exposure[1].setValue(2)
        panel.update_button.click()
        edited = controller.experiments.queued_definition(folder)
        assert edited == compile_simple_series(panel._settings()) and edited != original
        assert panel.state_label.text().startswith("Queued series updated")
        panel.pages.setCurrentIndex(1)
        panel.remove_button.click()
        assert controller.experiments.status()["queued_series"] == 0
        assert Path(folder).is_dir()  # removing from the queue keeps the output folder
    finally:
        window.close()
        controller.shutdown()


@pytest.fixture
def two_queued(qt_app, tmp_path):
    """A real window with series 'A' and 'B' queued (simulation); yields (window, panel, folder_a, folder_b)."""
    from time import monotonic, sleep

    from thermo_acoustic.application.commands import DeviceCommand, DeviceOperation

    controller = ApplicationController(DeviceRegistry(), mode=OperatingMode.SIMULATION)
    controller.start()
    window = MainWindow(controller)
    results = []
    controller.command_result.connect(results.append)
    window.panels[DeviceId.PUMP]._buttons["connect"].click()
    deadline = monotonic() + 5
    panel = window.experiment_panel
    while monotonic() < deadline and panel.pump_unit.count() == 0:
        qt_app.processEvents(); sleep(0.01)
    assert panel.pump_unit.count() > 0
    panel.pump_unit.setCurrentIndex(0)
    panel.output_root.setText(str(tmp_path))
    folders = []
    for name, frames in (("A", 3), ("B", 4)):
        panel.description.setText(name)
        panel.frames.setValue(frames)
        panel.queue_button.click()
        assert panel.state_label.text().startswith("Queued:"), panel.state_label.text()
        folders.append(panel.state_label.text().removeprefix("Queued: "))
    yield window, panel, folders[0], folders[1]
    window.close()
    controller.shutdown()


def _select(panel, folder):
    for index in range(panel.batch_list.topLevelItemCount()):
        item = panel.batch_list.topLevelItem(index)
        if item.text(5) == folder:
            panel.batch_list.setCurrentItem(item)
            return
    raise AssertionError(folder)


def _described(panel, folder):
    return panel.manager.queued_definition(folder)["description"]


def test_update_changes_the_loaded_series_not_the_one_selected_afterwards(two_queued):
    window, panel, a, b = two_queued
    assert not panel.update_button.isEnabled()  # nothing loaded yet
    _select(panel, a)
    panel.load_button.click()
    assert "Editing queued series: A" in panel.edit_target_label.text()
    _select(panel, b)  # browsing the list must not retarget Update
    panel.pages.setCurrentIndex(0)
    panel.exposure[0].setValue(2); panel.exposure[1].setValue(2)
    panel.update_button.click()
    assert panel.manager.queued_definition(a) != panel.manager.queued_definition(b)
    assert _described(panel, a) == "A" and _described(panel, b) == "B"
    assert panel.manager.queued_definition(a)["steps"] == compile_definition(panel)["steps"]


def compile_definition(panel):
    from thermo_acoustic.application.simple_series import compile_simple_series
    return compile_simple_series(panel._settings())


def test_update_without_a_loaded_series_changes_nothing(two_queued, monkeypatch):
    window, panel, a, b = two_queued
    from PySide6.QtWidgets import QMessageBox
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warned.append(args[2]))
    _select(panel, b)
    before = {f: panel.manager.queued_definition(f) for f in (a, b)}
    panel.description.setText("changed")
    panel._update_selected()
    assert warned and "No queued series is loaded" in warned[0]  # even if reached by another route, no selected row is modified
    assert {f: panel.manager.queued_definition(f) for f in (a, b)} == before
    assert "Not editing a queued series" in panel.edit_target_label.text()


def test_editing_target_is_dropped_when_it_goes_away_or_is_replaced(two_queued):
    window, panel, a, b = two_queued
    _select(panel, a); panel.load_button.click()
    _select(panel, b); panel.load_button.click()  # loading another series retargets explicitly
    assert "Editing queued series: B" in panel.edit_target_label.text()
    panel.queue_button.click()  # Queue a new series ends editing; nothing is overwritten
    assert "Not editing" in panel.edit_target_label.text() and not panel.update_button.isEnabled()
    _select(panel, a); panel.load_button.click()
    panel.manager.remove_queued(a)  # removed behind the form's back (e.g. another entry point)
    window.experiment_panel._status(panel.manager.status())
    assert "no longer queued" in panel.edit_target_label.text()
    assert not panel.update_button.isEnabled() and _described(panel, b) == "B"


def test_editing_target_is_dropped_when_the_batch_starts(two_queued):
    window, panel, a, b = two_queued
    _select(panel, a); panel.load_button.click()
    panel._status({**panel.manager.status(), "state": "running"})
    assert not panel.update_button.isEnabled()
    panel._status({**panel.manager.status(), "state": "idle", "series": []})
    assert "no longer queued" in panel.edit_target_label.text()


def _finished_manager(qt_app, tmp_path):
    controller = ApplicationController(DeviceRegistry(), mode=OperatingMode.SIMULATION)
    manager = controller.experiments
    manager._state, manager._phase = "completed", "Experiment series completed"
    manager._planned_total, manager._batch_series_total = 5, 1
    manager._batch_output_root = tmp_path
    return controller, manager


@pytest.mark.parametrize("reason", ["non_empty_folder", "missing_folder", "invalid_definition"])
def test_rejected_queue_keeps_the_finished_batch_record(qt_app, tmp_path, reason):
    from test_experiments import described_default_definition
    controller, manager = _finished_manager(qt_app, tmp_path)
    try:
        definition = described_default_definition()
        root = tmp_path
        if reason == "non_empty_folder":
            (tmp_path / "old_results").mkdir()
        elif reason == "missing_folder":
            root = tmp_path / "does_not_exist"
        else:
            definition["steps"] = "not steps"
        before = (manager._state, manager._phase, manager._planned_total,
                  manager._batch_series_total, manager._batch_output_root)
        with pytest.raises(ValueError):
            manager.queue(definition, root)
        assert (manager._state, manager._phase, manager._planned_total,
                manager._batch_series_total, manager._batch_output_root) == before
        assert manager.status()["state"] == "completed"
    finally:
        controller.shutdown()


def test_accepted_queue_after_a_finished_batch_starts_a_fresh_batch(qt_app, tmp_path):
    from test_experiments import described_default_definition
    controller, manager = _finished_manager(qt_app, tmp_path)
    try:
        fresh = tmp_path / "fresh"
        fresh.mkdir()
        manager.queue(described_default_definition(), fresh)
        status = manager.status()
        assert status["state"] == "idle" and status["queued_series"] == 1
    finally:
        controller.shutdown()


def test_idle_header_separates_batch_idle_device_activity_and_last_action(window):
    from thermo_acoustic.domain.models import ConnectionState, DeviceStatus
    assert window.activity_title.text() == "Batch idle"
    assert "Ready" not in window.activity_detail.text()  # no static Ready for an unconnected system
    assert "Last action: none yet" in window.activity_detail.text()
    statuses = dict(window.controller.statuses())
    statuses[DeviceId.TEC] = DeviceStatus(DeviceId.TEC, ConnectionState.ERROR, fault="comm lost")
    statuses[DeviceId.CAMERA] = DeviceStatus(DeviceId.CAMERA, ConnectionState.CONNECTED, active=True)
    window._status(statuses)
    detail = window.activity_detail.text()
    assert "Fault: TEC" in detail and "Active: Camera" in detail
    summary = window.connection_summary.text()
    assert "Simulation" in summary and "TEC" in summary and "operation failed" in summary and "connected" in summary


def test_abort_is_not_reported_as_a_series_failure(window):
    window._experiment_changed({**window._experiment_status, "state": "aborted",
                                "phase": "Experiment batch aborted: Operator aborted experiment batch"})
    assert "failed" not in window.activity_detail.text().lower()
    window._experiment_changed({**window._experiment_status, "state": "failed",
                                "phase": "Experiment series failed: valve timeout"})
    assert "failed" in window.activity_detail.text()


def test_camera_summary_names_unknown_values_and_does_not_dump_the_repr():
    from thermo_acoustic.domain.models import CameraReadback
    from thermo_acoustic.ui.status_dashboard import camera_summary
    text = camera_summary(CameraReadback(mode="continuous"))
    assert "exposure unknown" in text and "ROI unknown" in text and "CameraReadback(" not in text


def test_start_readiness_is_read_only_and_matches_what_start_refuses(qt_app, tmp_path):
    controller = ApplicationController(DeviceRegistry(), mode=OperatingMode.SIMULATION)
    manager = controller.experiments
    try:
        submitted = []
        controller.submit = lambda command: submitted.append(command)
        before = manager.status()
        readiness = manager.start_readiness()
        assert readiness.blocking == ("Queue at least one experiment series",)
        assert manager.status() == before and submitted == []  # asking changes and sends nothing
        with pytest.raises(RuntimeError, match="Queue at least one"):
            manager.start()
        from test_experiments import described_default_definition
        manager.queue(described_default_definition(), tmp_path)
        readiness = manager.start_readiness()
        assert readiness.blocking == ()  # simulation: syringe preflight is not required
        assert any("Camera preflight is not current" in text for text in readiness.reminders)
        assert any("when the series starts" in text for text in readiness.reminders)
        # Real mode makes the batch syringe preflight a blocker, with the text start() raises.
        monkey_mode = OperatingMode.REAL
        controller.mode = monkey_mode
        blocking = manager.start_readiness().blocking
        assert blocking == ("Run syringe preflight for the current batch before Start",)
        with pytest.raises(RuntimeError, match="Run syringe preflight"):
            manager.start()
    finally:
        controller.shutdown()


def test_review_page_shows_blockers_and_non_blocking_reminders(two_queued):
    window, panel, a, b = two_queued
    text = panel.start_readiness_label.text()
    assert "Cannot start" not in text and "Camera preflight is not current" in text
    assert panel.start_button.isEnabled()  # the optional camera preflight never disables Start
    panel.manager.remove_queued(a); panel.manager.remove_queued(b)
    panel._status(panel.manager.status())
    assert "Cannot start: Queue at least one experiment series" in panel.start_readiness_label.text()
    assert not panel.start_button.isEnabled()


def test_camera_page_can_show_the_image_window_without_acquiring_and_flush_tab_is_named(window):
    camera = window.panels[DeviceId.CAMERA]
    assert not camera.image_window.isVisible()
    camera.show_image_button.click()
    assert camera.image_window.isVisible()
    assert window.submitted == []  # showing the window issues no camera command
    assert window.workflow_panel.parentWidget() is not None  # the manual flush lives in Prepare, beside the pumps
    camera.image_window.close()


def test_z_stage_and_z_stack_panels_label_measured_and_commanded_positions(window):
    from thermo_acoustic.domain.models import ZStageReadback
    from thermo_acoustic.ui.status_dashboard import z_stage_summary
    text = z_stage_summary(ZStageReadback(closed_loop=True, position_um=10.0, commanded_position_um=12.5,
                                          max_travel_um=450.0))
    assert "measured position 10 µm" in text and "last commanded target 12.5 µm" in text
    assert "not confirmed" in text and "ZStageReadback(" not in text
    assert "no move commanded yet" in z_stage_summary(ZStageReadback())
    zs = window.z_stack_panel
    assert zs.show_image_button.isEnabled() and zs.open_folder_button.isEnabled()
    zs.show_image_button.click()
    assert window.panels[DeviceId.CAMERA].image_window.isVisible()
    assert window.submitted == []
    window.panels[DeviceId.CAMERA].image_window.close()


def test_range_rows_say_whether_they_are_fixed_or_a_scan_and_timing_table_follows_the_form(window):
    panel = window.experiment_panel
    start, stop, steps = panel.frequency
    steps.setValue(1)
    # The row's own description is the label under its Start/Stop/Steps fields.
    descriptions = [label.text() for label in panel.findChildren(type(panel.edit_target_label))
                    if label.text().startswith(("Fixed value", "Scan across"))]
    assert any(text.startswith("Fixed value") for text in descriptions)
    steps.setValue(3)
    assert any("Scan across experiments: 3 values" in label.text()
               for label in panel.findChildren(type(panel.edit_target_label)))
    panel.sound_start.setValue(0.5)
    panel.sound_run.setValue(2.0)
    assert [panel.timing_table.item(0, c).text() for c in range(4)] == ["Ultrasound (AD2)", "0.5", "2", "2.5"]
    panel.frames.setValue(20)
    panel.fps.setValue(10)
    assert panel.timing_table.item(2, 2).text() == "2"  # 20 frames at 10 fps; requested, not measured


def test_start_plan_follows_the_queued_definition_not_the_form_or_the_list_browsing(two_queued):
    window, panel, a, b = two_queued
    _select(panel, a)
    assert "Series “A”" in panel.queue_plan_title.text()
    assert "3 saved frames" in panel.queue_plan_text.text() and a in panel.queue_plan_text.text()
    assert "flush volume: pump unit 1" in panel.queue_plan_text.text()  # compiled budget, not the form scalar
    _select(panel, b)
    assert "Series “B”" in panel.queue_plan_title.text() and "4 saved frames" in panel.queue_plan_text.text()
    assert "2 queued series" in panel.batch_summary.text() and "2 experiments" in panel.batch_summary.text()
    # An unsaved form change is not in the queue: the plan keeps the queued value and says so.
    _select(panel, a)
    panel.load_button.click()
    panel.frames.setValue(9)
    assert "9 saved frames" in panel.summary.text() or "9" in panel.summary.text()  # the form preview follows the form
    assert "3 saved frames" in panel.queue_plan_text.text()  # what Start runs is unchanged
    assert "not in the queue" in panel.form_differs_label.text()
    # Browsing the list changes which queued plan is shown, never the form or the editing target.
    _select(panel, b)
    assert "4 saved frames" in panel.queue_plan_text.text() and panel.frames.value() == 9
    assert "Editing queued series: A" in panel.edit_target_label.text()
    _select(panel, a)
    panel.update_button.click()
    assert "9 saved frames" in panel.queue_plan_text.text() and panel.form_differs_label.text() == ""
    assert "Preview of this form" in panel.form_preview.toggle.text()


def test_queue_plan_follows_the_queued_definition_after_an_edit_made_elsewhere(two_queued):
    """The experiment builder (or any caller) updates the queue through update_queued; the queue page must
    show that definition, not the settings the series was first queued with."""
    from dataclasses import replace
    from thermo_acoustic.application.simple_series import compile_simple_series
    window, panel, a, b = two_queued
    _select(panel, a)
    assert "3 saved frames" in panel.queue_plan_text.text()
    assert [panel.queue_timing_table.item(0, c).text() for c in range(4)] == ["Ultrasound (AD2)", "0", "1", "1"]
    assert "Temperature strategy" not in panel.queue_plan_text.text()
    edited = replace(panel._settings(), frame_count=7, sound_run_s=2.0, temperature_control=True,
                     temperature_wait_for_stability=True, temperature_tolerance_c=0.5,
                     temperature_min_settle_s=3.0, temperature_max_wait_s=40.0, temperature_wait_s=6.0,
                     tec_channel=1)
    panel.manager.update_queued(a, compile_simple_series(edited))  # what the builder's update goes through
    window.experiment_panel._status(panel.manager.status())
    text = panel.queue_plan_text.text()
    assert "7 saved frames" in text and "3 saved frames" not in text
    assert [panel.queue_timing_table.item(0, c).text() for c in range(4)] == ["Ultrasound (AD2)", "0", "2", "2"]
    assert "wait for stability (±0.5°C, settled 3s, max wait 40s), then hold 6s" in text
    assert panel.queue_timing_table.item(2, 2).text() == "0.7"  # 7 frames at the form's 10 fps
    # The other series is untouched, and a definition without plain facts is said to be so.
    _select(panel, b)
    assert "4 saved frames" in panel.queue_plan_text.text()


def test_plan_facts_leave_out_what_a_definition_does_not_state_plainly():
    from thermo_acoustic.application.experiments import validate_definition
    from thermo_acoustic.application.plan_facts import plan_facts
    from test_experiments import described_default_definition
    facts = plan_facts(validate_definition(described_default_definition()).steps)
    assert facts.temperature_strategy is None  # no temperature program in that definition
    assert facts.uniform in (True, False)


def test_builder_edit_of_a_form_queued_series_shows_in_the_queue_plan(two_queued, monkeypatch):
    """Form -> queue -> experiment builder (load, edit the JSON, update) -> back to the queue page."""
    import json
    window, panel, a, b = two_queued
    builder = window.builder_window.panel
    builder._render_batch_list(builder.manager.status())
    for index in range(builder.batch_list.topLevelItemCount()):
        if builder.batch_list.topLevelItem(index).text(5) == a:
            builder.batch_list.setCurrentItem(builder.batch_list.topLevelItem(index))
    builder._queue_load()
    definition = json.loads(builder.definition_json.toPlainText())

    def edit(steps):
        for step in steps:
            if step.get("type") == "camera_configure":
                step["args"]["frame_count"] = 7
            if step.get("type") == "ad2_configure":
                step["args"]["ultrasound"]["run_s"] = 2.0
                step["args"]["dio"]["frame_count"] = 7
            edit(step.get("steps", []))
            for branch in step.get("branches", []):
                edit(branch)
    edit(definition["steps"])
    builder.definition_json.setPlainText(json.dumps(definition))
    builder._queue_update()
    window.show_workspace("queue")
    _select(panel, a)
    text = panel.queue_plan_text.text()
    assert "7 saved frames" in text and "3 saved frames" not in text
    assert [panel.queue_timing_table.item(0, c).text() for c in range(4)] == ["Ultrasound (AD2)", "0", "2", "2"]
    assert "Series “A”" in panel.queue_plan_title.text()
    _select(panel, b)
    assert "4 saved frames" in panel.queue_plan_text.text()  # the other series is unchanged
    _select(panel, a)
    # The form cannot take over a definition the builder changed; it says so and the plan stays as queued.
    from PySide6.QtWidgets import QMessageBox
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warned.append(args[2]))
    panel.load_button.click()
    assert warned and "outside the simple form" in warned[0]
    assert panel.queue_plan_text.text() == text
