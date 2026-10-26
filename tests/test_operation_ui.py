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
