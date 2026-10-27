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


def test_task_buttons_only_switch_tabs_and_follow_the_visible_page(window):
    names = {"prepare": "1 Prepare devices", "configure": "2 Configure", "review": "3 Review and start",
             "monitor": "4 Monitor run"}
    assert {key: button.text() for key, button in window._nav_buttons.items()} == names
    window._nav_buttons["review"].click()
    assert window.tabs.currentWidget() is window.experiment_panel
    assert window.experiment_panel.pages.currentIndex() == 1
    assert [key for key, button in window._nav_buttons.items() if button.isChecked()] == ["review"]
    window._nav_buttons["configure"].click()
    assert window.experiment_panel.pages.currentIndex() == 0
    assert [key for key, button in window._nav_buttons.items() if button.isChecked()] == ["configure"]
    window._nav_buttons["monitor"].click()
    assert window.tabs.tabText(window.tabs.currentIndex()) == "Run monitor"
    # Any tab stays reachable directly; the highlight follows, nothing is blocked.
    window.tabs.setCurrentIndex(3)
    assert window.tabs.tabText(3) == "Camera"
    assert [key for key, button in window._nav_buttons.items() if button.isChecked()] == ["prepare"]
    window._nav_buttons["monitor"].click()
    window._nav_buttons["prepare"].click()  # back to the device tab last used
    assert window.tabs.tabText(window.tabs.currentIndex()) == "Camera"
    assert window.submitted == []


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


def test_advanced_values_are_folded_but_still_part_of_the_series(window):
    panel = window.experiment_panel
    assert not panel.advanced.is_expanded()
    assert not panel.sound_run.isVisibleTo(panel)  # folded away
    assert "sound 0+1 s" in panel.advanced.summary.text()
    panel.sound_run.setValue(2.5)
    panel.camera_start.setValue(0.4)
    assert "sound 0+2.5 s" in panel.advanced.summary.text() and "camera from 0.4 s" in panel.advanced.summary.text()
    settings = panel._settings(require_pump_unit=False)
    assert settings.sound_run_s == 2.5 and settings.camera_start_s == 0.4  # folded does not mean ignored
    panel.advanced.set_expanded(True)
    assert panel.sound_run.isVisibleTo(panel)
    # Saved with the settings profile either way.
    assert window.profile_document()["experiment"]["sound_run_s"] == 2.5


def test_form_uses_one_column_on_a_narrow_window_and_two_on_a_wide_one(window, qt_app):
    panel = window.experiment_panel
    window._navigate("configure")  # a hidden tab is not laid out until it is shown
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
    assert "Simulation" in summary and "TEC" in summary and "error" in summary and "connected" in summary


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
    assert window.tabs.tabText(window.tabs.indexOf(window._scroll_pages[window.workflow_panel])) == "Flush"
    camera.image_window.close()
