from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox, QGroupBox, QLabel, QPushButton, QScrollArea, QTabWidget

from thermo_acoustic import qt_ui, qt_ui_v2, qt_ui_v3
from thermo_acoustic.application import Application
from thermo_acoustic.experiment_planning import normalize_experiment
from thermo_acoustic.instruments import SimulatedAD2Sdk
from thermo_acoustic.tec import TecStatus

from conftest import build_with_retry


def make_window(monkeypatch, tmp_path, app: Application | None = None) -> qt_ui_v3.MainWindowV3:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({}), encoding="utf-8")
    monkeypatch.setattr(qt_ui, "SETTINGS_PATH", settings_path)
    QApplication.instance() or QApplication([])
    return build_with_retry(lambda: qt_ui_v3.MainWindowV3(app=app))


def test_v3_main_constructs_its_offline_application_without_entering_qt_loop(monkeypatch):
    captured = []

    class FakeQApplication:
        @staticmethod
        def instance():
            return None

        def __init__(self, argv):
            self.argv = argv

        def exec(self):
            return 17

    class FakeWindow:
        def __init__(self, *, app):
            captured.append(app)

        def show(self):
            pass

    monkeypatch.setattr(qt_ui_v3, "QApplication", FakeQApplication)
    monkeypatch.setattr(qt_ui_v3, "MainWindowV3", FakeWindow)
    monkeypatch.setattr(qt_ui_v3, "install_focus_wheel_guard", lambda app: None)

    assert qt_ui_v3.main() == 17
    assert len(captured) == 1
    assert isinstance(captured[0].ad2, SimulatedAD2Sdk)


@pytest.mark.parametrize("module, window_name", [(qt_ui, "MainWindow"), (qt_ui_v2, "MainWindowV2")])
def test_v1_v2_main_construct_offline_application_without_qt_loop(monkeypatch, module, window_name):
    captured = []

    class FakeQApplication:
        @staticmethod
        def instance(): return None
        def __init__(self, argv): pass
        def exec(self): return 0

    class FakeWindow:
        def __init__(self, *args, **kwargs): captured.append(kwargs.get("app"))
        def show(self): pass

    monkeypatch.setattr(module, "QApplication", FakeQApplication)
    monkeypatch.setattr(module, window_name, FakeWindow)
    if hasattr(module, "install_focus_wheel_guard"):
        monkeypatch.setattr(module, "install_focus_wheel_guard", lambda app: None)
    assert module.main() == 0
    assert len(captured) == 1
    if module is qt_ui:
        assert captured[0] is None  # MainWindow itself supplies the canonical simulated default.
    else:
        assert isinstance(captured[0].ad2, SimulatedAD2Sdk)


def test_v3_is_a_layout_evolution_of_v2_and_v2_remains_available(monkeypatch, tmp_path):
    v3 = make_window(monkeypatch, tmp_path)
    v2 = build_with_retry(qt_ui_v2.MainWindowV2)
    try:
        assert isinstance(v3, qt_ui_v2.MainWindowV2)
        assert type(v3) is qt_ui_v3.MainWindowV3
        assert type(v2) is qt_ui_v2.MainWindowV2
        assert v3.windowTitle() == "Thermo Acoustic Streaming - UI v3 (shared hardware runtime)"
        assert v2.windowTitle() == "Thermo Acoustic Streaming - Transitional UI (shared hardware runtime)"
        assert any(action.text() == "Abort" for action in v3.menuBar().actions())
    finally:
        v3.close()
        v2.close()


def test_v3_waveform_policy_locks_dc_and_labels_square(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        state = window.exp_ad2_channels[0]
        state["function"].setCurrentText("Square")
        assert state["symmetry"].isEnabled()
        assert any("Duty Cycle (%)" in label.text() for label in window.findChildren(QLabel))
        state["function"].setCurrentText("DC")
        assert not state["frequency"].isEnabled()
        assert not state["amplitude"].isEnabled()
        assert not state["symmetry"].isEnabled()
        assert not state["phase"].isEnabled()
        assert state["offset"].isEnabled()
        assert any("DC Level (V)" in label.text() for label in window.findChildren(QLabel))
        assert "Not applicable" in state["frequency"].toolTip()
    finally:
        window.close()


def test_v3_reuses_the_supplied_application_and_places_status_first(monkeypatch, tmp_path):
    app = Application()
    window = make_window(monkeypatch, tmp_path, app=app)
    window.show()
    QApplication.processEvents()
    try:
        assert window.app is app
        assert window.app.camera is app.camera
        status = window.findChild(QGroupBox, "v3StatusFirst")
        connections = window.findChild(QGroupBox, "v3ConnectionStrip")
        identity = window.findChild(QGroupBox, "v3ExperimentIdentity")
        plan = window.findChild(QGroupBox, "v3ExperimentPlan")
        run_control = window.findChild(QGroupBox, "v3PrimaryRunControl")
        setup_tabs = window.findChild(QTabWidget, "v3SetupTabs")
        runtime = window.findChild(QScrollArea, "v3RuntimeMonitoring")
        assert status is not None
        assert connections is not None
        assert identity is not None
        assert plan is not None
        assert run_control is not None
        assert setup_tabs is not None
        assert runtime is not None
        assert connections.title() == "Hardware connection status"
        assert status.title() == "Experiment status and progress"
        connection_y = connections.mapTo(window.centralWidget(), connections.rect().topLeft()).y()
        status_y = status.mapTo(window.centralWidget(), status.rect().topLeft()).y()
        identity_y = identity.mapTo(window.centralWidget(), identity.rect().topLeft()).y()
        plan_y = plan.mapTo(window.centralWidget(), plan.rect().topLeft()).y()
        run_y = run_control.mapTo(window.centralWidget(), run_control.rect().topLeft()).y()
        setup_y = setup_tabs.mapTo(window.centralWidget(), setup_tabs.rect().topLeft()).y()
        assert connection_y < status_y < identity_y == plan_y < setup_y < run_y
        assert runtime.width() >= 330
        assert [setup_tabs.tabText(index) for index in range(setup_tabs.count())] == [
            "AD2 Output",
            "Camera",
            "Fluidics",
            "Temperature scan",
        ]
        assert set(window._v3_connection_values) == {"AD2", "Camera", "Pump", "Valve", "TEC"}
        assert all(dot.text() == "\u25cf" for dot in window._sidebar_status_dots.values())
        assert window._v3_connection_values["AD2"].text() == window.ad2_connection_status.text()
        assert window._v3_connection_values["Camera"].text() == window.camera_connection_status.text()
        assert window._v3_connection_values["Pump"].text() == window.pump_connection_status.text()
        assert window._v3_connection_values["Valve"].text() == window.valve_connection_status.text()
        assert window._v3_connection_values["TEC"].text() == "Disabled"
        labels = {label.text() for label in window.findChildren(QLabel)}
        assert {
            "Elapsed time",
            "Estimated time remaining",
            "Runs remaining",
            "Status and error history",
            "DIO1 pulse rate (camera FPS)",
            "Fixed DIO1 pulse start delay (s)",
            "Series repeats",
            "Frames per repeat",
            "Request global exposure reset",
            "Use per-repeat DIO1 pulse delays",
            "Measured camera rate (fps)",
        } <= labels
        assert window.findChild(QLabel, "v3ElapsedTimeCaption").text() == "Elapsed time"
        assert window.findChild(QLabel, "v3CameraFrameRateCaption").text() == "DIO1 pulse rate (camera FPS)"
        assert window.findChild(QLabel, "v3StatusHistoryCaption").text() == "Status and error history"
        assert {
            "Elapsed Time",
            "Time Left",
            "Elapsed time (unavailable)",
            "Remaining time (unavailable)",
            "# elements in queue",
            "Error Out",
            "Camera FPS",
            "Camera Start (s)",
            "GlobalExposure",
            "Dynamic Camera Start Time",
            "Average FPS",
        }.isdisjoint(labels)
        groups = {group.title() for group in window.findChildren(QGroupBox)}
        assert {"Experiment acquisition", "Per-repeat DIO1 pulse delays (s)"} <= groups
        assert "DIO1" in window.dynamic_camera_start.toolTip()
        assert "bench-unverified" in window.dynamic_camera_start.toolTip()
        assert "unchanged" in window.global_exposure.toolTip()
        assert "unresolved" in window.global_exposure.toolTip()
        acquisition = next(
            group for group in window.findChildren(QGroupBox) if group.title() == "Experiment acquisition"
        )
        assert identity.isAncestorOf(window.exp_repeats)
        assert not run_control.isAncestorOf(window.exp_repeats)
        assert not acquisition.isAncestorOf(window.exp_repeats)
        button_texts = {button.text() for button in window.findChildren(QPushButton)}
        assert "Browse..." in button_texts
        assert "..." not in button_texts
        graceful_stop = window.findChild(QPushButton, "v3RequestGracefulStopButton")
        assert graceful_stop is not None
        assert graceful_stop.text() == "Request graceful stop"
        assert "current repeat" in graceful_stop.toolTip()
        assert "current temperature point" in graceful_stop.toolTip()
        assert "does not stop hardware" in graceful_stop.toolTip()
        window.app.status = "WFG configured"
        window._refresh_status()
        assert window.connection_button.text() == "Initialize hardware"
        assert "device selection" in window.connection_button.toolTip()
    finally:
        window.close()


def test_v3_field_bound_adapters_survive_inherited_caption_changes(monkeypatch, tmp_path):
    original_status_builder = qt_ui_v2.MainWindowV2._v2_status_progress_group
    original_acquisition_builder = qt_ui_v2.MainWindowV2._v2_acquisition_group

    def status_with_changed_captions(self):
        group = original_status_builder(self)
        inherited = {
            "Elapsed Time",
            "Estimated time remaining",
            "# elements in queue",
        }
        for label in group.findChildren(QLabel):
            if label.text() in inherited:
                label.setText(f"Changed upstream: {label.text()}")
        return group

    def acquisition_with_changed_captions(self):
        group = original_acquisition_builder(self)
        inherited = {
            "Camera FPS (drives DIO1 LED clock)",
            "Camera Start (s) (DIO1 pulse delay)",
            "Repeats",
            "Frames",
            "GlobalExposure",
            "Dynamic Camera Start Time (per-repeat DIO1 delays)",
        }
        for label in group.findChildren(QLabel):
            if label.text() in inherited:
                label.setText(f"Changed upstream: {label.text()}")
        for nested_group in group.findChildren(QGroupBox):
            if nested_group.title() == "Camera Start Array(s) (per-repeat DIO1 delays)":
                nested_group.setTitle("Changed upstream camera-start group")
        return group

    monkeypatch.setattr(qt_ui_v2.MainWindowV2, "_v2_status_progress_group", status_with_changed_captions)
    monkeypatch.setattr(qt_ui_v2.MainWindowV2, "_v2_acquisition_group", acquisition_with_changed_captions)

    window = make_window(monkeypatch, tmp_path)
    try:
        assert window.findChild(QLabel, "v3ElapsedTimeCaption").text() == "Elapsed time"
        assert window.findChild(QLabel, "v3CameraFrameRateCaption").text() == "DIO1 pulse rate (camera FPS)"
        assert window.findChild(QLabel, "v3DynamicCameraStartCaption").text() == (
            "Use per-repeat DIO1 pulse delays"
        )
        assert window.findChild(QGroupBox, "v3PerRepeatCameraStartGroup").title() == (
            "Per-repeat DIO1 pulse delays (s)"
        )
    finally:
        window.close()


def test_v3_main_ad2_settings_use_channel_tabs_without_horizontal_overflow(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    window.show()
    QApplication.processEvents()
    try:
        group = window.findChild(QGroupBox, "v3ExperimentAd2Output")
        channels = window.findChild(QTabWidget, "v3ExperimentAd2Channels")
        scroll = window.findChild(QScrollArea, "v3Ad2SetupScroll")
        assert group is not None
        assert channels is not None
        assert scroll is not None
        assert [channels.tabText(index) for index in range(channels.count())] == [
            "Channel 0",
            "Channel 1 — role unverified",
        ]
        assert window.exp_ch1_freq in channels.findChildren(type(window.exp_ch1_freq))
        assert window.exp_ch2_freq in channels.findChildren(type(window.exp_ch2_freq))
        labels = {label.text() for label in group.findChildren(QLabel)}
        assert {
            "Channel output",
            "Waveform",
            "Start delay (s)",
            "Repeat count [0 = infinite]",
            "Re-arm trigger after each repeat",
        } <= labels
        assert {"Enable", "Function", "Start (s)", "Repeat count", "Repeat trigger"}.isdisjoint(labels)
        modulation = window.findChild(QTabWidget, "v3ModulationTabs")
        assert modulation is not None
        frequency_program = window.findChild(QGroupBox, "v3FrequencyProgram")
        assert frequency_program is not None
        assert channels.widget(0).isAncestorOf(frequency_program)
        modulation_titles = {group.title() for group in modulation.findChildren(QGroupBox)}
        assert {"FM sweep within a repeat", "Frequency scan across repeats"} <= modulation_titles
        assert all("Ch1 only" not in title for title in modulation_titles)
        modulation_labels = {label.text() for label in modulation.findChildren(QLabel)}
        assert {
            "Sweep Start Frequency (kHz)",
            "Sweep Stop Frequency (kHz)",
            "Sweep Center Frequency (kHz)",
            "Sweep Width (kHz)",
            "Number of Frequencies",
            "Step size (kHz) [0 = Count]",
        } <= modulation_labels
        assert "Equivalent inputs: Start / Stop ↔ Center / Width" in window.findChild(
            QLabel, "v3FmEquivalentInputsNote"
        ).text()
        assert "Step Size > 0 derives Number of Frequencies" in window.findChild(
            QLabel, "v3ScanAlternativeInputsNote"
        ).text()
        channel1_note = window.findChild(QLabel, "v3Channel1RoleNote")
        assert "Independent analog output" in channel1_note.text()
        assert "role unverified" in channel1_note.text()
        assert "camera" not in channel1_note.text().lower()
        window.exp_sweep_enable.setChecked(True)
        window.exp_freq_scan_enable.setChecked(True)
        assert "Scan selects each repeat's base carrier" in window.findChild(
            QLabel, "v3FrequencyProgramSummary"
        ).text()
        assert scroll.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        assert scroll.horizontalScrollBar().maximum() == 0
    finally:
        window.close()


def test_v3_preserves_v2_flush_sequence_safety_context(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        tabs = window.findChild(QTabWidget, "v3SetupTabs")
        assert tabs is not None
        flush_groups = [group for group in tabs.widget(2).findChildren(QGroupBox) if group.title() == "Flush settings"]
        assert len(flush_groups) == 1
        tooltip = flush_groups[0].toolTip().lower()
        assert "position 1" in tooltip
        assert "position 2" in tooltip
        assert "idle" in tooltip
        assert "sequential" in tooltip
        workflow_note = window.findChild(QLabel, "v3FluidicsWorkflowNote")
        assert "P01 → pump dispense → valve P02" in workflow_note.text()
        assert "bench-unverified" in workflow_note.text()
        summary = window.findChild(QGroupBox, "v3FlushDerivedSummary")
        assert summary is not None
        window.syringe.setCurrentText("BD 1ml")
        window.app.pump.fill_level = 0.75
        window.exp_flush_flowrate.setValue(200.0)
        window.exp_flush_volume.setValue(0.05)
        assert window._v3_flush_movement.text() == "15.000 s"
        assert window._v3_flush_timeout.text().startswith("20.000 s")
        assert window._v3_flush_capacity.text() == "1.000 ml; within capacity"
        assert window._v3_flush_fill_margin.text().startswith("0.700 ml")
    finally:
        window.close()


def test_v3_inactive_parameter_families_preserve_values_but_disable_inputs(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        assert not window.exp_sweep_enable.isChecked()
        assert not window.exp_sweep_start_khz.isEnabled()
        sweep_start = window.exp_sweep_start_khz.value()
        window.exp_sweep_enable.setChecked(True)
        assert window.exp_sweep_start_khz.isEnabled()
        assert window.exp_sweep_start_khz.value() == sweep_start

        assert not window.exp_freq_scan_enable.isChecked()
        assert not window.exp_freq_scan_start_khz.isEnabled()
        assert not window._v3_frequency_scan_input_mode.isEnabled()
        assert not window.exp_freq_scan_count.isEnabled()
        assert not window.exp_freq_scan_step_khz.isEnabled()
        window.exp_freq_scan_enable.setChecked(True)
        assert window.exp_freq_scan_start_khz.isEnabled()
        assert window._v3_frequency_scan_input_mode.isEnabled()
        assert window.exp_freq_scan_count.isEnabled()
        assert not window.exp_freq_scan_step_khz.isEnabled()
        window._v3_frequency_scan_input_mode.setCurrentIndex(1)
        assert not window.exp_freq_scan_count.isEnabled()
        assert window.exp_freq_scan_step_khz.isEnabled()

        assert not window.exp_flush_enabled.isChecked()
        assert not window.exp_flush_flowrate.isEnabled()
        flush_flow = window.exp_flush_flowrate.value()
        window.exp_flush_enabled.setChecked(True)
        assert window.exp_flush_flowrate.isEnabled()
        assert window.exp_flush_flowrate.value() == flush_flow

        assert not window.exp_tec_scan_enable.isChecked()
        assert not window.exp_tec_points.isEnabled()
        assert not window.exp_tec_tolerance_c.isEnabled()
        window.exp_tec_scan_enable.setChecked(True)
        assert window.exp_tec_points.isEnabled()
        assert window.exp_tec_tolerance_c.isEnabled()
        assert not window.exp_tec_points_ch2.isEnabled()
        window.exp_tec_lock_channels.setChecked(False)
        assert window.exp_tec_points_ch2.isEnabled()

        window.dcam_source.setCurrentText("Internal")
        assert not window.external_polarity.isEnabled()
        assert not window.external_delay.isEnabled()
        window.dcam_source.setCurrentText("External")
        assert window.external_polarity.isEnabled()
        assert window.external_delay.isEnabled()
    finally:
        window.close()


def test_v3_temperature_group_separates_policy_and_shows_cached_readback(monkeypatch, tmp_path):
    app = Application()
    window = make_window(monkeypatch, tmp_path, app=app)
    try:
        temperature = window.findChild(QGroupBox, "v3TecTemperatureScan")
        assert temperature is not None
        assert {
            "Temperature targets",
            "Stabilization criteria",
            "Advanced wait and polling policy",
            "Cached TEC readback",
        } <= {group.title() for group in temperature.findChildren(QGroupBox)}

        app.tec.enabled = True
        app.tec.simulate = True
        app.tec.initialized = True
        app.tec.last_status = {
            1: TecStatus(
                channel=1,
                current_temperature_c=24.75,
                target_temperature_c=25.0,
                output_stage_static_on=True,
                ready=True,
            ),
            2: TecStatus(channel=2, error_state="sensor warning"),
        }
        window._refresh_status()
        assert window._v3_connection_values["TEC"].text() == "Connected (simulated)"
        assert "Measured 24.750 °C; target 25.000 °C; ready; output on" in window.findChild(
            QLabel, "v3TecChannel1Readback"
        ).text()
        assert "error: sensor warning" in window.findChild(QLabel, "v3TecChannel2Readback").text()
    finally:
        window.close()


def test_v3_shadow_preflight_presentation_is_explicit_and_wrapped(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        start = window.findChild(QPushButton, "v3StartExperimentButton")
        assert start is not None
        assert "shadow-only" in start.toolTip()
        assert "authoritative" in start.toolTip()

        assert window.exp_tec_scan_enable.toolTip().startswith("<html>")
        assert type(window.exp_tec_scan_enable.parentWidget()).__name__ == "_TooltipIconWrapper"

        review = window.findChild(QLabel, "v3PreRunWarnings")
        assert review is not None
        assert "Camera FPS" in review.text()
        assert "darkred" in review.styleSheet()
        assert ".." not in review.text()
    finally:
        window.close()


def test_v3_inherits_live_timing_for_ordinary_and_tec_series(monkeypatch, tmp_path):
    clock = {"now": 100.0}
    monkeypatch.setattr(qt_ui.time, "monotonic", lambda: clock["now"])
    window = make_window(monkeypatch, tmp_path)
    try:
        assert window._refresh_series_timing.__func__ is qt_ui.MainWindow._refresh_series_timing
        assert window._handle_worker_progress.__func__ is qt_ui_v2.MainWindowV2._handle_worker_progress
        assert window._run_experiment_series.__func__ is qt_ui.MainWindow._run_experiment_series
        assert window._run_temperature_experiment_series.__func__ is qt_ui.MainWindow._run_temperature_experiment_series
        window._handle_worker_progress(
            "series_timing_started",
            {"started_at": 100.0, "programmed_remaining_s": 30.0},
        )
        window._handle_worker_progress("experiment_series_active", True)
        clock["now"] = 107.2
        window._refresh_series_timing()
        assert window.elapsed_time_label.text() == "00:00:07"
        assert window.time_left_label.text() == "00:00:23"
        assert window.findChild(QLabel, "v3ElapsedTimeCaption").text() == "Elapsed time"
        assert window.findChild(QLabel, "v3RemainingTimeCaption").text() == "Estimated time remaining"
    finally:
        window._handle_worker_progress("experiment_series_active", False)
        window.close()


def test_v3_relationship_panels_use_shared_requested_timing_builders(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        ch0, ch1 = window.exp_ad2_channels
        ch0["enable"].setChecked(True)
        ch0["sec_wait"].setValue(1.0)
        ch0["sec_run"].setValue(4.0)
        ch1["enable"].setChecked(True)
        ch1["sec_wait"].setValue(2.0)
        ch1["sec_run"].setValue(5.0)
        ch1_before = (ch1["sec_wait"].value(), ch1["sec_run"].value())
        ch0["sec_wait"].setValue(1.5)
        ch0["sec_wait"].setValue(1.0)
        assert (ch1["sec_wait"].value(), ch1["sec_run"].value()) == ch1_before
        window.exp_camera_fps.setValue(10.0)
        window.exp_frames.setValue(30)
        window.exp_camera_start.setValue(0.5)

        assert window.findChild(QGroupBox, "v3OneRepeatTimingPlan") is not None
        assert window.findChild(QLabel, "v3TimingCh0End").text() == "5.000"
        assert window.findChild(QLabel, "v3TimingCh1End").text() == "7.000"
        assert window.findChild(QLabel, "v3TimingCh1Delta").text() == "2.000"
        assert window.findChild(QLabel, "v3TimingDio1Run").text() == "3.000"
        assert window.findChild(QLabel, "v3TimingDio1Delta").text() == "-1.500"
        assert window.findChild(QLabel, "v3TimingDeltaHeader").text() == "End delta vs CH0 (s)"
        assert window.findChild(QLabel, "v3Ad2CompletionBudget").text().startswith(
            "Shared AD2 completion budget: 7.000 s"
        )

        ch0["enable"].setChecked(False)
        assert window.findChild(QLabel, "v3TimingDeltaHeader").text() == (
            "End delta vs completion driver (s)"
        )
        assert window.findChild(QLabel, "v3TimingCh1Delta").text() == "0.000"
        assert window.findChild(QLabel, "v3TimingDio1Delta").text() == "-3.500"
        assert "CH0 is disabled" in window.findChild(QLabel, "v3TimingAnchorNote").text()

        window.exp_repeats.setValue(11)
        window.dynamic_camera_start.setChecked(True)
        assert not window.exp_camera_start.isEnabled()
        assert all(widget.isEnabled() for widget in window.camera_start_array)
        assert "per-repeat slot 1" in window._v3_dio_start_source.text()
        assert "10/11 repeats" in window._v3_dio_slot_budget.text()
        assert "run will reject" in window._v3_dio_slot_budget.text()
        assert "live DCAM readout" in window._v3_camera_feasibility.text()
        uncertainty = window.findChild(QLabel, "v3SyncUncertaintyBanner")
        assert "camera trigger is Internal" in uncertainty.text()
        assert "not been bench verified" in uncertainty.text()
    finally:
        window.close()


def test_v3_plan_exposes_axes_sequence_camera_request_and_evidence_boundaries(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        window.exp_repeats.setValue(3)
        window.exp_camera_fps.setValue(20.0)
        window.exp_frames.setValue(50)
        window.exp_exposure_ms.setValue(10.0)
        mode = window.findChild(QComboBox, "v3FrequencyScanInputMode")
        mode.setCurrentText("Number of Frequencies")
        window.exp_freq_scan_start_khz.setValue(100.0)
        window.exp_freq_scan_stop_khz.setValue(140.0)
        window.exp_freq_scan_count.setValue(3)
        window.exp_freq_scan_enable.setChecked(True)
        window.exp_tec_points.setText("20, 25")
        window.exp_tec_scan_enable.setChecked(True)

        axis = window.findChild(QLabel, "v3ExperimentAxisSummary")
        workflow = window.findChild(QLabel, "v3RepeatWorkflowSummary")
        camera = window.findChild(QLabel, "v3RequestedCameraSummary")
        requirements = window.findChild(QLabel, "v3HardwareRequirementsSummary")
        preview = window.findChild(QLabel, "v3FrequencyScanListPreview")
        warnings = window.findChild(QLabel, "v3PreRunWarnings")
        assert "TEC temperature: 2 point(s)" in axis.text()
        assert "3 repeat(s) per temperature; 6 acquisition run(s) total" in axis.text()
        assert "one-to-one to repeat indices" in axis.text()
        assert "configure AD2/DIO" in workflow.text()
        assert "optional flush" in workflow.text()
        assert "2.500 s DIO1 window" in camera.text()
        assert "10.000 ms exposure vs 50.000 ms frame interval" in camera.text()
        assert "Live DCAM readout margin is checked only at run start" in camera.text()
        assert "Software-known shared snapshot only; no hardware query" in requirements.text()
        assert "shared AD2 snapshot intentionally deferred" in requirements.text()
        assert "Output path: CONFIGURED" in requirements.text()
        assert "Frequency-list preview (3 point(s), kHz): 100, 120, 140" == preview.text()
        assert "DIO1-to-camera exposure synchronization remains bench-unverified" in warnings.text()
        assert "2 temperature point(s) × 3 repeats = 6 acquisition runs" in window.findChild(
            QLabel, "v3TecAxisSummary"
        ).text()

        window.exp_ad2_channels[0]["enable"].setChecked(False)
        window.exp_sweep_enable.setChecked(True)
        assert "FM sweep enables channel 0" in warnings.text()
    finally:
        window.close()


def test_v3_readiness_distinguishes_disabled_not_required_and_unverified_state(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        readiness = window.findChild(QLabel, "v3HardwareRequirementsSummary")
        warnings = window.findChild(QLabel, "v3PreRunWarnings")
        window.app.ad2.enabled = False
        window.app.camera.enabled = False
        window.app.pump.enabled = False
        window.app.valve.enabled = True
        window.app.tec.enabled = False
        window.exp_camera_fps.setValue(25.0)
        window.series_path.setText("")
        assert "Output path: UNSET" in readiness.text()
        window.exp_flush_enabled.setChecked(True)
        window.exp_tec_points.setText("20")
        window.exp_tec_scan_enable.setChecked(True)
        window._refresh_v3_relationships()

        assert "AD2: DISABLED — current runtime skips this subsystem" in readiness.text()
        assert "Camera: DISABLED — current runtime skips this subsystem" in readiness.text()
        assert "Fluidics: DISABLED — selected flush will be skipped by runtime" in readiness.text()
        assert "TEC: DISABLED — current runtime skips this subsystem" in readiness.text()
        assert "Output path: UNSET" in readiness.text()
        assert "no physical-ready claim" in readiness.text()
        assert "Blank output path resolves to the current working directory" in warnings.text()
        assert "TEC evidence is simulated, not physical" in warnings.text()
        assert "current runtime will skip its hardware actions" in warnings.text()

        window.exp_flush_enabled.setChecked(False)
        window.exp_tec_scan_enable.setChecked(False)
        assert "Pump/Valve: NOT REQUIRED (flush off)" in readiness.text()
        assert "TEC: NOT REQUIRED (temperature scan off)" in readiness.text()
    finally:
        window.close()


def test_v3_frequency_scan_warns_on_repeat_mismatch_like_dio_slot_budget(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        mode = window.findChild(QComboBox, "v3FrequencyScanInputMode")
        mode.setCurrentIndex(0)
        window.exp_freq_scan_count.setValue(5)
        window.exp_repeats.setValue(11)
        window.exp_freq_scan_enable.setChecked(True)
        scan_summary = window._v3_series_relationship_summary
        assert "frequency scan 5/11 repeats" in scan_summary.text()
        assert "run will reject" in scan_summary.text()
        assert "darkorange" in scan_summary.styleSheet()

        window.dynamic_camera_start.setChecked(True)
        assert "run will reject" in window._v3_dio_slot_budget.text()
        assert window._v3_dio_slot_budget.styleSheet() == scan_summary.styleSheet()

        window.dynamic_camera_start.setChecked(False)
        window.exp_repeats.setValue(5)
        assert "counts match" in scan_summary.text()
        assert scan_summary.styleSheet() == ""
    finally:
        window.close()


def test_v3_shadow_plan_matches_authoritative_builder_for_frequency_camera_flush_and_path(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        output_path = tmp_path / "shadow-series"
        window.series_path.setText(str(output_path))
        window.exp_repeats.setValue(3)
        window.exp_camera_fps.setValue(25.0)
        window.exp_frames.setValue(40)
        window.exp_camera_start.setValue(0.4)
        window.exp_flush_enabled.setChecked(True)
        window.exp_flush_flowrate.setValue(15.0)
        window.exp_flush_volume.setValue(0.2)
        window.exp_wait_after_flush.setValue(1.5)
        mode = window.findChild(QComboBox, "v3FrequencyScanInputMode")
        mode.setCurrentText("Number of Frequencies")
        window.exp_freq_scan_start_khz.setValue(100.0)
        window.exp_freq_scan_stop_khz.setValue(120.0)
        window.exp_freq_scan_count.setValue(3)
        window.exp_freq_scan_enable.setChecked(True)

        authoritative, total_frames, _config = window._build_experiment_series(output_path)
        shadow = window._v3_shadow_build_result()

        assert shadow.plan is not None
        assert shadow.plan.total_frames == total_frames == 120
        assert shadow.plan.output_path == output_path
        assert shadow.request.frequency_values_hz == (100000.0, 110000.0, 120000.0)
        assert shadow.request.camera_fps == 25.0
        assert shadow.request.frames == 40
        assert shadow.request.flush_enabled is True
        assert shadow.plan.normalized_experiments() == tuple(
            normalize_experiment(experiment) for experiment in authoritative.experiments
        )
        assert [item["wfg_frequencies_hz"][0] for item in shadow.plan.normalized_experiments()] == [
            100000.0,
            110000.0,
            120000.0,
        ]
        assert [item["frequency_scan_selected_hz"] for item in shadow.plan.normalized_experiments()] == [
            100000.0,
            110000.0,
            120000.0,
        ]
        assert all(item["output_root"] == str(output_path) for item in shadow.plan.normalized_experiments())
        assert all(item["planned_repeat_count"] == 3 for item in shadow.plan.normalized_experiments())
        assert all(item["do_channels"][0][2:] == (25.0, 0.4, 1.6) for item in shadow.plan.normalized_experiments())
        assert all(item["flush_enabled"] is True for item in shadow.plan.normalized_experiments())
    finally:
        window.close()


def test_v3_shadow_plan_matches_authoritative_unlocked_tec_groups(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        output_path = tmp_path / "shadow-tec-series"
        window.series_path.setText(str(output_path))
        window.exp_repeats.setValue(2)
        window.exp_camera_fps.setValue(20.0)
        window.exp_tec_scan_enable.setChecked(True)
        window.exp_tec_lock_channels.setChecked(False)
        window.exp_tec_points.setText("21, 26")
        window.exp_tec_points_ch2.setText("18, 23")

        _series, groups, total_frames, _config = window._build_temperature_experiment_groups(output_path)
        shadow = window._v3_shadow_build_result()

        assert shadow.plan is not None
        assert shadow.plan.total_frames == total_frames
        assert shadow.request.temperature_targets_c == (((1, 21.0), (2, 18.0)), ((1, 26.0), (2, 23.0)))
        authoritative_normalized = tuple(
            normalize_experiment(experiment)
            for group in groups
            for experiment in group.experiments
        )
        assert shadow.plan.normalized_experiments() == authoritative_normalized
        assert [item["tec_targets_c"] for item in authoritative_normalized] == [
            {1: 21.0, 2: 18.0},
            {1: 21.0, 2: 18.0},
            {1: 26.0, 2: 23.0},
            {1: 26.0, 2: 23.0},
        ]
        assert [item["temperature_point_index"] for item in authoritative_normalized] == [1, 1, 2, 2]
        assert all(item["output_root"] == str(output_path) for item in authoritative_normalized)
    finally:
        window.close()


def test_v3_shadow_plan_matches_plain_fixed_start_grouping_and_camera_overrides(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        output_path = tmp_path / "plain-shadow"
        window.series_path.setText(str(output_path))
        window.exp_repeats.setValue(4)
        window.exp_frames.setValue(6)
        window.exp_camera_fps.setValue(12.0)
        window.exp_camera_start.setValue(0.25)
        window.dynamic_camera_start.setChecked(False)
        window.exp_freq_scan_enable.setChecked(False)
        window.exp_sweep_enable.setChecked(False)
        window.exp_flush_enabled.setChecked(False)
        window.exp_tec_scan_enable.setChecked(False)

        authoritative, total_frames, _config = window._build_experiment_series(output_path)
        shadow = window._v3_shadow_build_result()

        assert shadow.plan is not None
        assert shadow.plan.normalized_groups() == (
            tuple(normalize_experiment(experiment) for experiment in authoritative.experiments),
        )
        assert tuple(len(group) for group in shadow.plan.experiment_groups) == (4,)
        assert shadow.plan.total_frames == total_frames == 24
        assert all(item["sequence_settings"]["frames"] == 6 for item in shadow.plan.normalized_experiments())
        assert all(
            item["sequence_settings"]["trigger_source"] == "Internal"
            for item in shadow.plan.normalized_experiments()
        )
        assert all(item["do_channels"][0][3] == 0.25 for item in shadow.plan.normalized_experiments())
    finally:
        window.close()


def test_v3_shadow_plan_matches_fm_dynamic_start_locked_tec_and_blank_path(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        window.series_path.setText("")
        window.exp_repeats.setValue(3)
        window.exp_frames.setValue(4)
        window.exp_camera_fps.setValue(10.0)
        window.dynamic_camera_start.setChecked(True)
        for value, widget in zip((0.1, 0.2, 0.3), window.camera_start_array, strict=False):
            widget.setValue(value)
        window.exp_sweep_enable.setChecked(True)
        window.exp_ad2_channels[0]["enable"].setChecked(False)
        window.exp_flush_enabled.setChecked(False)
        window.exp_tec_scan_enable.setChecked(True)
        window.exp_tec_lock_channels.setChecked(True)
        window.exp_tec_points.setText("20, 25")
        window.sequence_mode.setCurrentText("Continuous")
        window.sequence_source.setCurrentText("External")
        window.sequence_interval.setValue(0.125)
        window.sequence_burst.setValue(2)
        window.external_polarity.setCurrentText("Negative")
        window.external_delay.setValue(0.003)
        window.exp_exposure_ms.setValue(7.5)
        window.app.camera.enabled = False
        window.app.pump.enabled = False
        window.app.valve.enabled = False
        window.app.tec.enabled = False

        _temperature_series, groups, total_frames, _config = window._build_temperature_experiment_groups(Path(""))
        shadow = window._v3_shadow_build_result()

        assert shadow.plan is not None
        authoritative_groups = tuple(
            tuple(normalize_experiment(experiment) for experiment in group.experiments)
            for group in groups
        )
        assert shadow.plan.normalized_groups() == authoritative_groups
        assert tuple(len(group) for group in shadow.plan.experiment_groups) == (3, 3)
        assert shadow.plan.total_frames == total_frames == 24
        assert shadow.preflight.output_path_state == "implicit_working_directory"
        assert shadow.preflight.fluidics_required is False
        assert "pump" not in shadow.preflight.required_devices
        assert "valve" not in shadow.preflight.required_devices
        assert {"camera", "tec"}.issubset(shadow.preflight.disabled_devices)
        assert "ad2" in shadow.preflight.simulated_devices
        normalized = shadow.plan.normalized_experiments()
        assert [item["do_channels"][0][3] for item in normalized[:3]] == [0.1, 0.2, 0.3]
        assert all(item["fm_sweep"] is not None for item in normalized)
        assert all(item["wfg"]["channels"][0]["carrier"]["enable"] is True for item in normalized)
        assert all(item["global_exposure_ms"] == 7.5 for item in normalized)
        assert all(item["sequence_settings"]["trigger_source"] == "Internal" for item in normalized)
        assert all(item["sequence_settings"]["masterpulse_interval_s"] == 0.125 for item in normalized)
    finally:
        window.close()


def test_v3_shadow_preflight_matches_legacy_dc_scan_and_fm_semantics(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        window.series_path.setText(str(tmp_path / "dc"))
        window.exp_repeats.setValue(3)
        window.exp_camera_fps.setValue(10.0)
        window.exp_ch1_function.setCurrentText("DC")
        window.exp_freq_scan_enable.setChecked(True)
        window.exp_freq_scan_count.setValue(1)  # intentionally mismatched if scan were effective
        window.exp_sweep_enable.setChecked(True)

        authoritative, _frames, _config = window._build_experiment_series(Path(window.series_path.text()))
        shadow = window._v3_shadow_build_result()

        assert shadow.plan is not None
        assert shadow.plan.normalized_experiments() == tuple(
            normalize_experiment(experiment) for experiment in authoritative.experiments
        )
        assert shadow.preflight.frequency_repeat_compatible is True
        assert not shadow.preflight.blocking_issues
        codes = {issue.code for issue in shadow.preflight.warnings}
        assert {"frequency_scan_ignored_for_dc", "fm_sweep_ignored_for_dc"} <= codes
        assert "inactive for DC" in window._v3_axis_summary.text()
    finally:
        window.close()


def test_v3_frequency_scan_count_and_step_modes_are_exclusive_and_preserve_values(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        mode = window.findChild(QComboBox, "v3FrequencyScanInputMode")
        assert mode.currentText() == "Number of Frequencies"
        assert not window.exp_freq_scan_count.isEnabled()
        assert not window.exp_freq_scan_step_khz.isEnabled()
        window.exp_freq_scan_enable.setChecked(True)
        assert window.exp_freq_scan_count.isEnabled()
        assert not window.exp_freq_scan_step_khz.isEnabled()

        window.exp_freq_scan_count.setValue(5)
        mode.setCurrentText("Step Size")
        assert not window.exp_freq_scan_count.isEnabled()
        assert window.exp_freq_scan_step_khz.isEnabled()
        assert window.exp_freq_scan_step_khz.value() > 0
        window.exp_freq_scan_step_khz.setValue(12.5)

        mode.setCurrentText("Number of Frequencies")
        assert window.exp_freq_scan_count.isEnabled()
        assert not window.exp_freq_scan_step_khz.isEnabled()
        assert window.exp_freq_scan_count.value() == 5
        assert window.exp_freq_scan_step_khz.value() == 0.0

        mode.setCurrentText("Step Size")
        assert not window.exp_freq_scan_count.isEnabled()
        assert window.exp_freq_scan_step_khz.isEnabled()
        assert window.exp_freq_scan_step_khz.value() == 12.5
    finally:
        window.close()


def test_v3_launcher_states_opt_in_hardware_and_rollback_boundaries():
    launcher = (Path(__file__).resolve().parents[1] / "launch_gui_v3.bat").read_text(encoding="utf-8")

    assert "opt-in" in launcher
    assert "tracked" in launcher
    assert "formally accepted repository content" in launcher
    assert "not independently hardware-verified" in launcher
    assert "launch_gui_v2.bat" in launcher
    assert "rollback/reference" in launcher
    assert "launch_gui.bat" in launcher


def test_v3_pump_panel_separates_actions_from_static_configuration(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        dialog = build_with_retry(lambda: window._ensure_manual_panel("PumpValve"))
        dialog.show()
        QApplication.processEvents()
        scroll = dialog.findChild(QScrollArea, "v3PumpValveScroll")
        tasks = dialog.findChild(QTabWidget, "v3PumpValveTasks")
        assert scroll is not None
        assert tasks is not None
        assert scroll.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        assert scroll.horizontalScrollBar().maximum() == 0
        assert [tasks.tabText(index) for index in range(tasks.count())] == [
            "Pump",
            "Valve",
            "Flush",
            "Syringe setup",
            "Recovery",
        ]
        assert {group.title() for group in tasks.widget(0).findChildren(QGroupBox)} == {
            "Immediate pump operations"
        }
        assert {group.title() for group in tasks.widget(1).findChildren(QGroupBox)} == {"Valve position"}
        assert {group.title() for group in tasks.widget(2).findChildren(QGroupBox)} == {"Manual flush"}
        assert {group.title() for group in tasks.widget(3).findChildren(QGroupBox)} == {
            "Shared syringe setup and calibration"
        }
        assert {group.title() for group in tasks.widget(4).findChildren(QGroupBox)} == {
            "Connection recovery"
        }
        groups = {group.title() for group in dialog.findChildren(QGroupBox)}
        assert {
            "Immediate pump operations",
            "Valve position",
            "Manual flush",
            "Shared syringe setup and calibration",
        } <= groups
        button_texts = {button.text() for button in dialog.findChildren(QPushButton)}
        assert {
            "Refill syringe",
            "Empty syringe",
            "Start flow at selected rate",
            "Move to target fill level",
            "Stop pump",
            "Set valve to position 1 (P01)",
            "Set valve to position 2 (P02)",
            "Start flush sequence",
            "Configure syringe",
            "Run reference move",
            "Clear fault and retry connection",
        } <= button_texts
        assert {
            "Refill",
            "Empty",
            "Generate",
            "GO",
            "STOP",
            "Pos1 (P01)",
            "Pos2 (P02)",
            "Flush",
            "Configure",
            "Reference move",
        }.isdisjoint(button_texts)
        assert window.flow_rate in dialog.findChildren(type(window.flow_rate))
        recovery = dialog.findChild(QGroupBox, "v3PumpConnectionRecovery")
        clear_fault = dialog.findChild(QPushButton, "v3ClearPumpFaultButton")
        assert recovery is not None
        assert clear_fault is not None
        assert "confirmation-gated" in clear_fault.toolTip()
        assert "underlying CAN cause" in " ".join(
            label.text() for label in recovery.findChildren(QLabel)
        )
        stop_pump = dialog.findChild(QPushButton, "v3StopPumpButton")
        assert stop_pump is not None
        assert "darkred" in stop_pump.styleSheet()
        flush_note = dialog.findChild(QLabel, "v3ManualFlushWorkflowNote")
        assert "P01 → pump dispense → valve P02" in flush_note.text()
        syringe_boundary = dialog.findChild(QLabel, "v3SharedSyringeBoundary")
        assert "capacity" in syringe_boundary.text()
        assert "does not apply it" in syringe_boundary.text()
        assert dialog.findChild(QGroupBox, "v3PumpValveLocalStatus") is not None
        pump_state = dialog.findChild(QLabel, "v3PumpLocalState")
        valve_state = dialog.findChild(QLabel, "v3ValveLocalState")
        syringe_state = dialog.findChild(QLabel, "v3SyringeLocalState")
        assert "tracked fill 0.000 ml" in pump_state.text()
        assert "cached protocol position 1 (P01)" in valve_state.text()
        assert "No syringe configuration has been applied" in syringe_state.text()
        assert "does not query hardware" in dialog.findChild(
            QLabel, "v3PumpLocalStatusEvidenceNote"
        ).text()

        window.app.pump.initialized = True
        window.app.pump.fill_level = 0.625
        window.app.pump.referenced = True
        window.app.pump.syringe_config = {"name": "Custom", "inner_diameter_mm": 4.5}
        window.app.valve.initialized = True
        window.app.valve.position = 2
        window.app.valve.status_note = "confirmed"
        window._refresh_status()
        assert "Connected; idle; tracked fill 0.625 ml; reference move confirmed" in pump_state.text()
        assert "Connected; cached protocol position 2 (P02); status confirmed" in valve_state.text()
        assert "name Custom; inner diameter 4.5 mm" in syringe_state.text()
    finally:
        window.close()


def test_v3_camera_panel_has_ordered_acquisition_sequence_and_advanced_display(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        dialog = build_with_retry(lambda: window._ensure_manual_panel("Camera"))
        dialog.show()
        QApplication.processEvents()
        scroll = dialog.findChild(QScrollArea, "v3CameraScroll")
        tasks = dialog.findChild(QTabWidget, "v3CameraTasks")
        assert scroll is not None
        assert tasks is not None
        assert scroll.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        assert scroll.horizontalScrollBar().maximum() == 0
        assert [tasks.tabText(index) for index in range(tasks.count())] == ["Capture", "Sequence", "Display"]
        assert {group.title() for group in tasks.widget(0).findChildren(QGroupBox)} == {
            "Capture and preview",
            "Shared applied ROI and manual exposure",
            "Saved-frame output",
        }
        sequence_sections = tasks.widget(1).findChild(QTabWidget, "v3CameraSequenceSections")
        assert sequence_sections is not None
        assert [sequence_sections.tabText(index) for index in range(sequence_sections.count())] == [
            "Actions",
            "Timing",
            "Trigger",
            "Retained (not used by runtime)",
        ]
        assert {group.title() for group in sequence_sections.widget(0).findChildren(QGroupBox)} == {
            "Sequence actions"
        }
        assert "Save last captured image" not in {
            button.text() for button in sequence_sections.widget(0).findChildren(QPushButton)
        }
        assert {group.title() for group in sequence_sections.widget(1).findChildren(QGroupBox)} == {
            "Shared sequence defaults"
        }
        assert {group.title() for group in sequence_sections.widget(2).findChildren(QGroupBox)} == {
            "Trigger defaults and manual mode"
        }
        assert {group.title() for group in sequence_sections.widget(3).findChildren(QGroupBox)} == {
            "Retained sequence fields (not used)"
        }
        trigger_labels = {label.text() for label in sequence_sections.widget(2).findChildren(QLabel)}
        assert {"Camera trigger source", "Trigger polarity", "Trigger delay (s)"} <= trigger_labels
        assert {"DCAM source", "Polarity", "Delay (s)"}.isdisjoint(trigger_labels)
        timing_labels = {label.text() for label in sequence_sections.widget(1).findChildren(QLabel)}
        assert {"Master pulse mode", "Capture buffer size (frames)"} <= timing_labels
        assert {"Mode", "Frames"}.isdisjoint(timing_labels)
        legacy_labels = {label.text() for label in sequence_sections.widget(3).findChildren(QLabel)}
        assert "Sequence exposure (ms)" in legacy_labels
        assert "Sequence exposure" not in legacy_labels
        assert {group.title() for group in tasks.widget(2).findChildren(QGroupBox)} == {
            "Display conversion (advanced)"
        }
        display_labels = {label.text() for label in tasks.widget(2).findChildren(QLabel)}
        assert {
            "Conversion method",
            "Display minimum",
            "Display maximum",
            "Right shift (bits)",
        } <= display_labels
        assert {"Method", "Minimum", "Maximum", "Bit shifts"}.isdisjoint(display_labels)
        button_texts = {button.text() for button in dialog.findChildren(QPushButton)}
        assert {"Capture single image", "Save last captured image", "Browse..."} <= button_texts
        assert {"Image", "Save last Image capture", "..."}.isdisjoint(button_texts)
        labels = {label.text() for label in tasks.widget(0).findChildren(QLabel)}
        assert "Live preview" in labels
        assert window.sequence_frames in sequence_sections.widget(1).findChildren(type(window.sequence_frames))
        assert window.dcam_source in sequence_sections.widget(2).findChildren(type(window.dcam_source))
        assert window.capture_mode in sequence_sections.widget(3).findChildren(type(window.capture_mode))
        shared_summary = dialog.findChild(QLabel, "v3CameraSharedStateSummary")
        assert "inherit the applied ROI" in shared_summary.text()
        assert "force Internal trigger source" in shared_summary.text()
        assert "preview only" in shared_summary.text()
        assert "replace the capture-buffer" in dialog.findChild(
            QLabel, "v3CameraSequenceBoundary"
        ).text()
        assert "force trigger source to Internal" in dialog.findChild(
            QLabel, "v3CameraTriggerBoundary"
        ).text()
        capture_labels = {label.text() for label in tasks.widget(0).findChildren(QLabel)}
        assert {
            "Horizontal offset (px)",
            "Vertical offset (px)",
            "Horizontal size (px)",
            "Vertical size (px)",
            "Output folder",
        } <= capture_labels
    finally:
        window.close()


def test_v3_wfg_keeps_manual_controls_but_removes_outer_horizontal_overflow(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    dispatched: list[str] = []
    monkeypatch.setattr(window, "_start_apply_wfg", lambda checked=False: dispatched.append("apply-wfg"))
    try:
        dialog = build_with_retry(lambda: window._ensure_manual_panel("WFG"))
        scroll = dialog.findChild(QScrollArea, "v3WfgScroll")
        assert scroll is not None
        assert scroll.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        assert dialog.sizeHint().width() < 800
        dialog.resize(900, 760)
        dialog.show()
        QApplication.processEvents()
        for index in (0, 1):
            channel_scroll = dialog.findChild(QScrollArea, f"v3WfgChannel{index}Scroll")
            assert channel_scroll is not None
            assert channel_scroll.widgetResizable()
            assert channel_scroll.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            assert channel_scroll.horizontalScrollBar().maximum() == 0
        groups = {group.title(): group for group in dialog.findChildren(QGroupBox)}
        assert "AD2 channel 0 (LabVIEW Ch1)" in groups
        assert "AD2 channel 1 (LabVIEW Ch2)" in groups
        assert "Computed waveform preview" in groups
        labels = {label.text() for label in dialog.findChildren(QLabel)}
        assert "Synchronize channels" in labels
        assert "SynchronizeState" not in labels
        assert window.wfg_running.text() == "Enable WFG output"
        assert any(text.startswith("Carrier frequency (kHz)") for text in labels)
        assert any(text.startswith("Start delay (s)") for text in labels)
        assert "FM modulation (manual WFG only)" in labels
        assert all("(unused)" not in text for text in labels)
        assert all("secWait" not in text for text in labels)
        assert all("Function 2" not in text for text in labels)
        assert all(text != "FM Mod" for text in labels)
        assert "channel synchronization is currently unavailable" in window.wfg_sync.toolTip()
        assert window.wfg_channels[0]["frequency"] in dialog.findChildren(type(window.wfg_channels[0]["frequency"]))
        channel_zero = groups["AD2 channel 0 (LabVIEW Ch1)"]
        assert channel_zero.findChild(QLabel, "manualWfgCarrier_frequencyLabel").text().startswith(
            "Carrier frequency (kHz)"
        )
        assert channel_zero.findChild(QLabel, "manualWfgTrigger_sec_waitLabel").text().startswith(
            "Start delay (s)"
        )
        assert channel_zero.findChild(QLabel, "manualWfgFmSectionLabel").text() == "FM modulation (manual WFG only)"
        preview_note = groups["Computed waveform preview"].findChild(
            QLabel, "manualWfgPreviewDescription"
        )
        assert preview_note.text() == "Computed from the current manual settings; no hardware readback."
        boundary = dialog.findChild(QLabel, "v3ManualWfgExperimentBoundary")
        assert "first hardware initialization only" in boundary.text()
        assert "one-time seed" in boundary.text()
        window.wfg_channels[0]["enable"].setChecked(True)
        window.wfg_channels[1]["enable"].setChecked(True)
        window._update_wfg_preview()
        assert set(window.wfg_preview_graph._series) == {"AD2 channel 0", "AD2 channel 1"}
        [
            button
            for button in dialog.findChildren(QPushButton)
            if button.text() == "Apply manual WFG settings"
        ][0].click()
        assert dispatched == ["apply-wfg"]
    finally:
        window.close()


def test_v3_mso_stacks_controls_and_preview_without_outer_horizontal_scroll(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    dispatched: list[str] = []
    monkeypatch.setattr(window, "_start_mso_init", lambda checked=False: dispatched.append("mso-init"))
    monkeypatch.setattr(window, "_start_mso_capture", lambda checked=False: dispatched.append("mso-capture"))
    try:
        dialog = build_with_retry(lambda: window._ensure_manual_panel("MSO"))
        scroll = dialog.findChild(QScrollArea, "v3MsoScroll")
        assert scroll is not None
        assert scroll.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        assert dialog.sizeHint().width() < 800
        groups = {group.title() for group in dialog.findChildren(QGroupBox)}
        assert {"MSO acquisition settings", "Captured waveform"} <= groups
        assert {"MSO Configuration", "Waveform"}.isdisjoint(groups)
        labels = {label.text() for label in dialog.findChildren(QLabel)}
        assert "Capture summary" in labels
        assert "Stats" not in labels
        assert window.mso_sample_frequency in dialog.findChildren(type(window.mso_sample_frequency))
        buttons = {button.text(): button for button in dialog.findChildren(QPushButton)}
        assert dialog.findChild(QPushButton, "v3MsoCaptureButton") is buttons["Capture waveform"]
        buttons["Initialize MSO"].click()
        buttons["Capture waveform"].click()
        assert dispatched == ["mso-init", "mso-capture"]
    finally:
        window.close()


@pytest.mark.known_flaky
def test_v3_dialogs_open_at_usable_sizes_without_full_path_width(monkeypatch, tmp_path):
    # Informational marker only: this test has shown the same deleted-C++-
    # object signature in a full-suite run, while passing isolated repeats.
    # Do not retry, skip, or xfail it; a future failure must remain visible.
    window = make_window(monkeypatch, tmp_path)
    try:
        expected_sizes = {
            "WFG": (900, 760),
            "MSO": (820, 680),
            "PumpValve": (820, 680),
            "Camera": (860, 700),
            "ZScan": (820, 440),
        }
        for panel_name, expected in expected_sizes.items():
            dialog = build_with_retry(lambda panel_name=panel_name: window._ensure_manual_panel(panel_name))
            assert (dialog.width(), dialog.height()) == expected

        initialize = window._ensure_initialization_dialog()
        initialize.show()
        QApplication.processEvents()
        assert initialize.width() == 900
        assert initialize.height() == 620
        assert initialize.minimumWidth() == 760
        assert window.cetoni_config_path.minimumWidth() == 260
        assert initialize.sizeHint().width() < 1200
        details = initialize.findChild(QTabWidget, "v3InitializationDetails")
        assert details is not None
        assert [details.tabText(index) for index in range(details.count())] == [
            "Connections",
            "Reference paths",
            "Retained fields",
        ]
        assert window.valve_resource in details.widget(0).findChildren(type(window.valve_resource))
        assert window.qmix_sdk_python_path in details.widget(1).findChildren(type(window.qmix_sdk_python_path))
        assert window.prior_resource in details.widget(2).findChildren(type(window.prior_resource))
        resource_labels = {label.text() for label in details.widget(0).findChildren(QLabel)}
        assert {
            "Piezo device serial number",
            "Valve serial port",
            "Cetoni configuration path",
            "TEC serial resource",
        } <= resource_labels
        assert {"Piezo serial", "Cetoni configuration", "TEC resource"}.isdisjoint(resource_labels)
        legacy_labels = {label.text() for label in details.widget(2).findChildren(QLabel)}
        assert "Discovery-only mode" in legacy_labels
        assert "Discovery only" not in legacy_labels
        assert "Real TEC operation remains unapproved" in window.tec_port.toolTip()
        groups = {group.title(): group for group in initialize.findChildren(QGroupBox)}
        device_y = groups["Devices"].mapTo(initialize, groups["Devices"].rect().topLeft()).y()
        details_y = groups["Hardware resources and references"].mapTo(
            initialize, groups["Hardware resources and references"].rect().topLeft()
        ).y()
        assert device_y < details_y
        assert set(initialize._status_labels) == {"AD2", "Camera", "Pump", "Valve", "Z-stage", "TEC"}
        button_texts = {button.text() for button in initialize.findChildren(QPushButton)}
        assert "Initialize selected devices" in button_texts
        assert "Initialize" not in button_texts
        assert initialize.findChild(QPushButton, "v3InitializeSelectedDevicesButton").text() == (
            "Initialize selected devices"
        )
        assert window.qmix_sdk_python_path.isEnabled() is False
        assert window.prior_resource.isEnabled() is False
    finally:
        window.close()


def test_v3_zscan_keeps_motion_warning_compact_and_groups_top_aligned(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        dialog = build_with_retry(lambda: window._ensure_manual_panel("ZScan"))
        dialog.show()
        QApplication.processEvents()
        labels = [label.text() for label in dialog.findChildren(QLabel)]
        workflow_note = next(label for label in labels if label.startswith("Manual calibration workflow only."))
        assert "existing camera connection" in workflow_note
        assert "independent of the experiment-camera exposure" in workflow_note
        assert "Motion requires explicit confirmation" in workflow_note
        groups = {group.title(): group for group in dialog.findChildren(QGroupBox)}
        assert {"Z-Scan Calibration Parameters", "Z-Scan actions"} <= set(groups)
        assert groups["Z-Scan Calibration Parameters"].height() < dialog.height() - 80
        assert groups["Z-Scan actions"].height() < dialog.height() - 80
        window._apply_zscan_range(10.0)
        window.zscan_z_start_um.setValue(0.0)
        window.zscan_z_end_um.setValue(10.0)
        window.zscan_step_size_um.setValue(3.0)
        summary = dialog.findChild(QLabel, "v3ZScanDerivedSummary")
        assert "5 position(s) / image(s)" in summary.text()
        assert "0.000–10.000 µm" in summary.text()
        assert "live-read from device MaxTravel" in summary.text()
    finally:
        window.close()


def test_v3_shell_controls_dispatch_to_shared_v1_v2_callbacks(monkeypatch, tmp_path):
    events: list[str] = []

    monkeypatch.setattr(qt_ui.MainWindow, "_start_experiment", lambda self: events.append("experiment"))
    monkeypatch.setattr(qt_ui.MainWindow, "_abort", lambda self: events.append("abort"))
    monkeypatch.setattr(qt_ui.MainWindow, "_exit_app", lambda self: events.append("exit"))
    monkeypatch.setattr(qt_ui.MainWindow, "_save_settings", lambda self: events.append("save-settings"))
    monkeypatch.setattr(qt_ui.MainWindow, "_load_settings", lambda self: events.append("load-settings"))
    monkeypatch.setattr(
        qt_ui_v2.MainWindowV2,
        "_open_initialization_dialog",
        lambda self: events.append("initialize-dialog"),
    )
    monkeypatch.setattr(
        qt_ui_v2.MainWindowV2,
        "_open_manual_panel",
        lambda self, panel_name: events.append(f"panel:{panel_name}"),
    )

    window = make_window(monkeypatch, tmp_path)
    events.clear()  # MainWindow loads persisted settings during construction.
    try:
        buttons = {button.text(): button for button in window.findChildren(QPushButton)}
        buttons["Initialize hardware"].click()
        buttons["Start experiment"].click()
        buttons["Request graceful stop"].click()
        for label in ("WFG", "MSO", "Pump & Valve", "Camera", "Z-Scan"):
            buttons[label].click()

        actions = {action.text(): action for action in window.menuBar().actions()}
        assert "local settings file" in actions["Save UI settings"].toolTip()
        assert "local settings file" in actions["Load UI settings"].toolTip()
        for label in ("Abort", "Exit", "Save UI settings", "Load UI settings"):
            actions[label].trigger()

        assert events == [
            "initialize-dialog",
            "experiment",
            "abort",
            "panel:WFG",
            "panel:MSO",
            "panel:PumpValve",
            "panel:Camera",
            "panel:ZScan",
            "abort",
            "exit",
            "save-settings",
            "load-settings",
        ]
    finally:
        window.close()


def test_v3_opening_manual_panels_is_inert(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    dispatched: list[str] = []
    monkeypatch.setattr(window, "_run_action", lambda *args, **kwargs: dispatched.append("action"))
    try:
        for panel_name in ("PumpValve", "Camera", "ZScan"):
            window._ensure_manual_panel(panel_name)

        assert dispatched == []
        assert window.app.camera.handle is None
        assert window.app.ad2.device_handle is None
        assert window.app.pump.initialized is False
        assert window.app.valve.initialized is False
    finally:
        window.close()


def test_v3_rebuilt_manual_panel_buttons_dispatch_without_hardware(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    events: list[str] = []
    direct_callbacks = {
        "_start_generate_flow": "generate-flow",
        "_start_go_level": "go-level",
        "_start_flush": "flush",
        "_start_configure_syringe": "configure-syringe",
        "_start_reference_move": "reference-move",
        "_start_clear_pump_fault": "clear-pump-fault",
        "_start_capture_camera_image": "camera-image",
        "_start_save_sequence": "save-last-image",
        "_start_configure_camera": "configure-camera",
        "_adjust_camera_preview": "adjust-preview",
        "_query_zscan_range": "query-z-range",
        "_start_zscan": "start-zscan",
        "_abort_zscan": "abort-zscan",
    }
    for method_name, event_name in direct_callbacks.items():
        monkeypatch.setattr(
            window,
            method_name,
            lambda checked=False, event_name=event_name: events.append(event_name),
        )
    monkeypatch.setattr(
        window,
        "_set_image_continuous",
        lambda checked: events.append(f"continuous:{checked}"),
    )
    monkeypatch.setattr(
        window,
        "_run_action",
        lambda action, starting_status, **kwargs: events.append(f"worker:{starting_status}"),
    )

    try:
        dialogs = {
            panel_name: window._ensure_manual_panel(panel_name)
            for panel_name in ("PumpValve", "Camera", "ZScan")
        }
        button_events = {
            "Refill syringe": "worker:Refilling",
            "Empty syringe": "worker:Emptying",
            "Start flow at selected rate": "generate-flow",
            "Move to target fill level": "go-level",
            "Stop pump": "worker:Pump stopped",
            "Set valve to position 1 (P01)": "worker:Setting valve to position 1 (P01)",
            "Set valve to position 2 (P02)": "worker:Setting valve to position 2 (P02)",
            "Start flush sequence": "flush",
            "Configure syringe": "configure-syringe",
            "Run reference move": "reference-move",
            "Clear fault and retry connection": "clear-pump-fault",
            "Capture single image": "camera-image",
            "Start camera capture session": "worker:Camera capture started",
            "Stop camera capture session": "worker:Camera capture stopped",
            "Send software trigger": "worker:Camera triggered",
            "Save last captured image": "save-last-image",
            "Apply camera settings": "configure-camera",
            "Reprocess preview": "adjust-preview",
            "Read piezo travel range": "query-z-range",
            "Start Z-Scan": "start-zscan",
            "Abort Z-Scan": "abort-zscan",
        }
        all_buttons = [
            button
            for dialog in dialogs.values()
            for button in dialog.findChildren(QPushButton)
        ]
        for button_text, expected_event in button_events.items():
            matches = [button for button in all_buttons if button.text() == button_text]
            assert len(matches) == 1, button_text
            matches[0].click()
            assert events[-1] == expected_event

        window.image_continuous.setChecked(True)
        assert events[-1] == "continuous:True"

        camera_buttons = {
            button.text(): button
            for button in dialogs["Camera"].findChildren(QPushButton)
        }
        assert "does not retrieve an image" in camera_buttons["Start camera capture session"].toolTip()
        assert "does not retrieve an image" in camera_buttons["Send software trigger"].toolTip()
        assert "Capture single image" in camera_buttons["Save last captured image"].toolTip()
        assert "does not retrieve a new frame" in camera_buttons["Save last captured image"].toolTip()
        assert "does not capture a new image" in camera_buttons["Reprocess preview"].toolTip()
    finally:
        window.close()


def test_v3_camera_start_and_stop_reach_fake_camera_methods(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    calls: list[str] = []
    camera_type = type(window.app.camera)
    monkeypatch.setattr(camera_type, "start_capture", lambda self: calls.append("start"))
    monkeypatch.setattr(camera_type, "stop_capture", lambda self: calls.append("stop"))
    monkeypatch.setattr(
        window,
        "_run_action",
        lambda action, starting_status, **kwargs: action(None),
    )
    try:
        dialog = window._ensure_manual_panel("Camera")
        buttons = {button.text(): button for button in dialog.findChildren(QPushButton)}
        buttons["Start camera capture session"].click()
        buttons["Stop camera capture session"].click()
        assert calls == ["start", "stop"]
    finally:
        window.close()
