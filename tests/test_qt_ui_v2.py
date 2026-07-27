from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QGroupBox, QLabel, QPushButton, QSpinBox

from thermo_acoustic import qt_ui, qt_ui_v2
from thermo_acoustic.hardware_factory import HardwareRuntimeConfig


def make_window(monkeypatch, tmp_path) -> qt_ui_v2.MainWindowV2:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({}), encoding="utf-8")
    monkeypatch.setattr(qt_ui, "SETTINGS_PATH", settings_path)
    QApplication.instance() or QApplication([])
    return qt_ui_v2.MainWindowV2()


def _synthetic_wheel_event(target, dy: int = 120) -> QWheelEvent:
    pos = QPointF(max(target.width(), 1) / 2, max(target.height(), 1) / 2)
    return QWheelEvent(
        pos, QPointF(target.mapToGlobal(pos.toPoint())),
        QPoint(0, 0), QPoint(0, dy),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase, False,
    )


def _sweep_for_unguarded_widgets(window) -> tuple[int, list]:
    targets: list = []
    for widget_cls in (QSpinBox, QDoubleSpinBox, QComboBox):
        targets.extend(window.findChildren(widget_cls))
    failures = []
    for widget in targets:
        widget.clearFocus()
        QApplication.processEvents()
        before = widget.currentIndex() if isinstance(widget, QComboBox) else widget.value()
        QApplication.sendEvent(widget, _synthetic_wheel_event(widget))
        QApplication.processEvents()
        after = widget.currentIndex() if isinstance(widget, QComboBox) else widget.value()
        if before != after:
            failures.append(widget)
    return len(targets), failures


def test_wheel_guard_completeness_on_both_window_types_independently(monkeypatch, tmp_path):
    # Task D: re-verify as two genuinely separate live instances -- do not
    # assume v2 inherits v1's coverage just because it shares some widgets
    # with itself. Each window is swept independently and reported separately.
    v1_settings = tmp_path / "v1_settings.json"
    v1_settings.write_text(json.dumps({}), encoding="utf-8")
    monkeypatch.setattr(qt_ui, "SETTINGS_PATH", v1_settings)
    QApplication.instance() or QApplication([])

    window_v1 = qt_ui.MainWindow()
    window_v1.show()
    QApplication.processEvents()
    try:
        count_v1, failures_v1 = _sweep_for_unguarded_widgets(window_v1)
        assert count_v1 > 50, "sanity check: expected the real qt_ui.MainWindow widget tree"
        assert not failures_v1, f"qt_ui.MainWindow: {len(failures_v1)}/{count_v1} unguarded widgets: {failures_v1}"
    finally:
        window_v1.close()

    window_v2 = make_window(monkeypatch, tmp_path)
    window_v2.show()
    QApplication.processEvents()
    try:
        count_v2, failures_v2 = _sweep_for_unguarded_widgets(window_v2)
        assert count_v2 > 20, "sanity check: expected the real qt_ui_v2.MainWindowV2 widget tree"
        assert not failures_v2, f"qt_ui_v2.MainWindowV2: {len(failures_v2)}/{count_v2} unguarded widgets: {failures_v2}"

        # The two fields named in the original report, checked specifically
        # through the v2 window object.
        window_v2.exp_ch1_freq.clearFocus()
        window_v2.exp_wait_after_flush.clearFocus()
        QApplication.processEvents()
        before = (window_v2.exp_ch1_freq.value(), window_v2.exp_wait_after_flush.value())
        QApplication.sendEvent(window_v2.exp_ch1_freq, _synthetic_wheel_event(window_v2.exp_ch1_freq))
        QApplication.sendEvent(window_v2.exp_wait_after_flush, _synthetic_wheel_event(window_v2.exp_wait_after_flush))
        QApplication.processEvents()
        after = (window_v2.exp_ch1_freq.value(), window_v2.exp_wait_after_flush.value())
        assert after == before
    finally:
        window_v2.close()


def test_v2_is_separate_main_window_without_old_tab_widget(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        assert isinstance(window, qt_ui.MainWindow)
        assert not hasattr(window, "tabs")
        assert window.windowTitle() == "Thermo Acoustic Streaming - New UI Preview"
        assert window.connection_button.text() == "* Not Connected"
    finally:
        window.close()


def test_v2_placeholder_buttons_do_not_drive_hardware(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        window._show_placeholder("WFG")

        assert "WFG panel is not yet implemented" in window.status.text()
        assert window.app.ad2.device_handle is None
        assert window.app.camera.handle is None
    finally:
        window.close()


def test_v2_sidebar_shows_friendly_name_not_internal_panel_key(monkeypatch, tmp_path):
    # Category 8 (Session 39): "PumpValve" is the internal dict key used to
    # look up _MANUAL_PANEL_BUILDERS/_manual_panels -- it was also rendered
    # verbatim as the sidebar button's own text, the only one of the four
    # panel names that reads like a smashed-together internal identifier
    # rather than a real label. Confirms the button now shows the same name
    # qt_ui.py's own tab bar uses for this feature ("Pump&Valve"), and that
    # _show_placeholder() (the dead-in-production but still-tested pre-
    # Session-2 handler) uses the same friendly name too.
    window = make_window(monkeypatch, tmp_path)
    try:
        button_texts = [
            button.text()
            for button in window.findChildren(QPushButton)
            if button.text() in ("WFG", "MSO", "PumpValve", "Pump&Valve", "Camera")
        ]
        assert "Pump&Valve" in button_texts
        assert "PumpValve" not in button_texts

        window._show_placeholder("PumpValve")
        assert "Pump&Valve panel is not yet implemented" in window.status.text()
    finally:
        window.close()


def test_v2_sidebar_buttons_open_existing_manual_test_panels(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        for panel_name in ("WFG", "MSO", "PumpValve", "Camera"):
            dialog = window._ensure_manual_panel(panel_name)

            # PumpValve (Session 39, Category 8): the internal dict key is
            # smashed together with no separator for use as a Python
            # identifier -- the displayed title uses the same human-friendly
            # name qt_ui.py's own tab bar shows for this feature
            # ("Pump&Valve"), not the raw key, unlike the other three panels
            # (already their own correct display text).
            assert dialog.windowTitle() == f"{qt_ui_v2.MainWindowV2._panel_display_name(panel_name)} (Manual Test)"
            assert not dialog.isModal()

        checkboxes = window._manual_panels["WFG"].findChildren(QCheckBox)
        assert window.wfg_running in checkboxes

        mso_dialog_widgets = window._manual_panels["MSO"].findChildren(type(window.mso_sample_frequency))
        assert window.mso_sample_frequency in mso_dialog_widgets
    finally:
        window.close()


def test_v2_valve_status_flags_unverified_and_busy_responses(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        window.app.valve.initialized = True

        window.app.valve.status_note = "confirmed"
        window._refresh_status()
        assert window.valve_connection_status.text() == "Connected"

        window.app.valve.status_note = "unverified position response: 'ERR'"
        window._refresh_status()
        assert window.valve_connection_status.text() == "Connected (unverified position response: 'ERR')"

        window.app.valve.status_note = "busy"
        window._refresh_status()
        assert window.valve_connection_status.text() == "Connected (busy)"
    finally:
        window.close()


def test_v2_experiment_running_indicator_reads_explicit_flag_not_status_text(monkeypatch, tmp_path):
    # Category 2 (Session 39): the old "experiment" in self.app.status.lower()
    # heuristic would have reported "No" here even though an experiment
    # series is genuinely still active -- e.g. right after Abort is clicked,
    # when self.app.status has just been overwritten to "Aborting..." but the
    # current repeat may still be executing. _experiment_series_active is the
    # explicit flag qt_ui.py's _run_experiment_series() now brackets its own
    # execution with, independent of whatever status text happens to be set.
    window = make_window(monkeypatch, tmp_path)
    try:
        window._busy_count = 1
        window.app.status = "Aborting..."
        window._experiment_series_active = True
        window._refresh_status()
        assert window.experiment_running_status.text() == "Yes"

        window._experiment_series_active = False
        window._refresh_status()
        assert window.experiment_running_status.text() == "No"
    finally:
        window.close()


def test_v2_elapsed_time_and_time_left_are_marked_as_stale_stubs(monkeypatch, tmp_path):
    # Category 4 (Session 39): v2's own "Status / Progress" group had the
    # identical bare QLabel("00:00:00") construction as qt_ui.py's Experiment
    # tab -- fixed via the same shared _elapsed_time_label()/_time_left_label()
    # helpers, confirmed here independently for the v2 window.
    window = make_window(monkeypatch, tmp_path)
    try:
        for label in (window.elapsed_time_label, window.time_left_label):
            assert label.text() == "00:00:00"
            assert not label.isEnabled()
            assert "Not wired to a real backend" in label.toolTip()
    finally:
        window.close()


def test_v2_manual_panel_dialogs_are_reused_not_rebuilt(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        first = window._ensure_manual_panel("Camera")
        second = window._ensure_manual_panel("Camera")

        assert first is second
    finally:
        window.close()


def test_v2_initialization_dialog_reuses_existing_config_widgets(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        dialog = window._ensure_initialization_dialog()
        checkboxes = dialog.findChildren(QCheckBox)
        labels = [label.text() for label in dialog.findChildren(QLabel)]

        assert window.ad2_enabled in checkboxes
        assert window.sim_ad2 in checkboxes
        assert window.camera_enabled in checkboxes
        assert window.sim_camera in checkboxes
        assert window.pump_enabled in checkboxes
        assert window.sim_pump in checkboxes
        assert window.valve_enabled in checkboxes
        assert window.sim_valve in checkboxes
        assert window.z_enabled in checkboxes
        assert window.thorlabs_apt_discovery_only in checkboxes
        assert "Only one UI window should control real hardware at a time. Close the other UI window before initializing here." in labels
        assert "Z-stage" in dialog._status_labels
        assert dialog._status_labels["Z-stage"].text() == "Waiting"
    finally:
        window.close()


def test_v2_initialization_progress_uses_existing_instrument_order(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    events = []
    config = HardwareRuntimeConfig(
        ad2_enabled=True,
        sim_ad2=True,
        camera_enabled=True,
        sim_camera=True,
        pump_enabled=True,
        sim_pump=True,
        valve_enabled=True,
        sim_valve=True,
        z_enabled=False,
        prior_resource="COM7",
        valve_resource="COM6",
        cetoni_config_path=tmp_path,
    )
    try:
        result = window._initialize_system(config, lambda kind, value: events.append((kind, value)))

        assert result == "System Initialized"
        assert [value for kind, value in events if kind == "init_device" and value[1] == "In Progress"] == [
            ("AD2", "In Progress"),
            ("Camera", "In Progress"),
            ("Pump", "In Progress"),
            ("Valve", "In Progress"),
            ("Z-stage", "In Progress"),
        ]
        assert window.app.status == "System Initialized"
        window._refresh_status()
        assert window.connection_button.text() == "* Connected"
        assert window.ad2_connection_status.text() == "Connected"
        assert window.camera_connection_status.text() == "Connected"
        assert window.pump_connection_status.text() == "Connected"
        assert window.valve_connection_status.text() == "Connected"
    finally:
        window.close()


def test_v2_reuses_existing_experiment_builder(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        window.series_path.setText(str(tmp_path / "series"))
        window.exp_camera_fps.setValue(100.0)
        window.exp_frames.setValue(3)
        window.exp_repeats.setValue(2)
        window.exp_ch1_enable.setChecked(True)
        window.exp_ch1_run.setValue(0.5)

        series, total_frames, config = window._build_experiment_series()

        assert total_frames == 6
        assert series.see_elements_left() == 2
        assert config.channels[0].carrier.enable is True
    finally:
        window.close()


def test_v2_experiment_area_exposes_fm_sweep_and_frequency_scanning(monkeypatch, tmp_path):
    # Category 7 (Session 39): v2's Experiment area never had any reachable
    # control for FM Sweep (flagged as a known gap since Session 25, never
    # fixed) or Frequency Scanning (added Session 34, gap never even
    # flagged) -- both are real, fully-wired qt_ui.py Experiment-tab
    # features, not new development, so this confirms the new
    # _experiment_fm_sweep_group()/reused _experiment_frequency_scan_group()
    # bind the *same* widget instances qt_ui.py's own Experiment tab uses
    # (identity, not copies), and that a value set through v2's own groups
    # reaches the real _build_experiment_series() output exactly like it
    # would from qt_ui.py.
    window = make_window(monkeypatch, tmp_path)
    try:
        fm_sweep_group = window._experiment_fm_sweep_group()
        fm_sweep_form = fm_sweep_group.layout()
        assert fm_sweep_form.itemAt(1, fm_sweep_form.ItemRole.FieldRole).widget() is window.exp_sweep_start_khz
        assert fm_sweep_form.itemAt(2, fm_sweep_form.ItemRole.FieldRole).widget() is window.exp_sweep_stop_khz

        freq_scan_group = window._experiment_frequency_scan_group()
        freq_scan_form = freq_scan_group.layout()
        assert freq_scan_form.itemAt(1, freq_scan_form.ItemRole.FieldRole).widget() is window.exp_freq_scan_start_khz
        assert freq_scan_form.itemAt(3, freq_scan_form.ItemRole.FieldRole).widget() is window.exp_freq_scan_count

        window.series_path.setText(str(tmp_path / "series"))
        window.exp_camera_fps.setValue(100.0)
        window.exp_frames.setValue(3)
        window.exp_repeats.setValue(2)
        window.exp_ch1_enable.setChecked(True)
        window.exp_ch1_run.setValue(0.5)
        window.exp_sweep_enable.setChecked(True)
        window.exp_sweep_start_khz.setValue(1000.0)
        window.exp_sweep_stop_khz.setValue(1100.0)

        _series, _total_frames, config = window._build_experiment_series()

        assert config.channels[0].carrier.frequency_hz == pytest.approx(1_050_000.0)
    finally:
        window.close()


def test_v2_ad2_output_table_exposes_symmetry_phase_and_repeat_trigger(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        group = window._v2_ad2_output_group()
        scroll = group.layout().itemAt(0).widget()
        grid = scroll.widget().layout()

        # Row 0 is the "Detail" sub-header spanning the Symmetry/Phase/Repeat
        # Trigger columns; row 1 is the per-column header row (shifted down
        # from row 0 by the addition of the sub-header row).
        detail_item = grid.itemAtPosition(0, 10)
        assert detail_item is not None
        assert detail_item.widget().text() == "Detail"

        headers = [grid.itemAtPosition(1, column).widget().text() for column in range(1, grid.columnCount())]
        assert "Symmetry (%)" in headers
        assert "Phase (Deg)" in headers
        assert "Repeat Trigger" in headers

        symmetry_col = headers.index("Symmetry (%)") + 1
        phase_col = headers.index("Phase (Deg)") + 1
        repeat_trigger_col = headers.index("Repeat Trigger") + 1

        # Bound to the exact same widgets qt_ui.py's Experiment tab uses --
        # not copies -- so a value set through either surface reaches the
        # same _build_experiment_series() output.
        assert grid.itemAtPosition(2, symmetry_col).widget() is window.exp_ch1_symmetry
        assert grid.itemAtPosition(2, phase_col).widget() is window.exp_ch1_phase
        assert grid.itemAtPosition(2, repeat_trigger_col).widget() is window.exp_ch1_repeat_trigger
        assert grid.itemAtPosition(3, symmetry_col).widget() is window.exp_ch2_symmetry

        window.series_path.setText(str(tmp_path / "series"))
        window.exp_camera_fps.setValue(100.0)
        window.exp_frames.setValue(3)
        window.exp_ch1_enable.setChecked(True)
        window.exp_ch1_run.setValue(0.5)
        window.exp_ch1_symmetry.setValue(65.0)
        window.exp_ch1_phase.setValue(12.5)
        window.exp_ch1_repeat_trigger.setChecked(True)

        _series, _total_frames, config = window._build_experiment_series()
        ch0 = config.channels[0]

        assert ch0.carrier.symmetry_percent == 65.0
        assert ch0.carrier.phase_deg == 12.5
        assert ch0.trigger.repeat_trigger is True
    finally:
        window.close()


def test_v2_no_group_box_is_squeezed_below_its_minimum_size_hint(monkeypatch, tmp_path):
    # Category 3 (Session 39): qt_ui.py's own
    # test_no_group_box_is_squeezed_below_its_minimum_size_hint (Session 29)
    # only walks window.tabs.currentWidget() -- qt_ui_v2.MainWindowV2 has no
    # such tabs, so none of its own groups (Status/Progress, Sequence
    # Control, AD2 Output Parameters, Acquisition Parameters, Waveform
    # Preview, Global Status) or its manual-panel QDialogs were ever covered
    # by that guard. An offscreen sweep this session found the "Global
    # Status" panel's value QLabels squeezed to a fixed 34px regardless of
    # content (fixed via WrapLongRows + word-wrap, see qt_ui_v2.py's
    # _global_status_panel()) -- this test locks that fix in and extends
    # the same generic, no-hardcoded-list method to v2's own window AND its
    # four manual-panel dialogs, so future v2-only groups stay covered too.
    window = make_window(monkeypatch, tmp_path)
    try:
        window.show()
        for width, height in ((1440, 860), (980, 680)):
            window.resize(width, height)
            QApplication.processEvents()
            QApplication.processEvents()

            failures = []
            for group in window.findChildren(QGroupBox):
                geometry = group.geometry()
                min_hint = group.minimumSizeHint()
                if min_hint.height() > 0 and geometry.height() < min_hint.height():
                    failures.append(("MainWindowV2", group.title(), geometry.height(), min_hint.height()))

            for name in ("WFG", "MSO", "PumpValve", "Camera"):
                dialog = window._ensure_manual_panel(name)
                dialog.show()
                QApplication.processEvents()
                QApplication.processEvents()
                for group in dialog.findChildren(QGroupBox):
                    geometry = group.geometry()
                    min_hint = group.minimumSizeHint()
                    if min_hint.height() > 0 and geometry.height() < min_hint.height():
                        failures.append((f"{name} dialog", group.title(), geometry.height(), min_hint.height()))

            assert not failures, (
                f"at window size {width}x{height}: group box(es) squeezed below their own "
                f"minimumSizeHint (rows collapsing to 0-1px): {failures}"
            )
    finally:
        window.close()


def test_v2_global_status_panel_does_not_truncate_value_labels(monkeypatch, tmp_path):
    # Reproduces the specific truncation this session found: every value
    # QLabel in "Global Status" rendered at a fixed 34px regardless of its
    # own required width (e.g. "Not connected" needing 156px). Confirms both
    # the short-text case and a real long-text case (the valve's
    # status_note passthrough, Session 2) now render without clipping.
    window = make_window(monkeypatch, tmp_path)
    try:
        window.resize(1440, 860)
        window.show()
        QApplication.processEvents()
        QApplication.processEvents()

        for label in (
            window.ad2_connection_status,
            window.camera_connection_status,
            window.pump_connection_status,
            window.valve_connection_status,
        ):
            assert label.wordWrap() is True

        window.app.valve.initialized = True
        window.app.valve.status_note = "unverified position response: 'ERR'"
        window._refresh_status()
        QApplication.processEvents()

        assert window.valve_connection_status.text() == "Connected (unverified position response: 'ERR')"
        # word-wrapped into more than a single 12px text line rather than
        # clipped to one line's worth of pixels.
        assert window.valve_connection_status.height() > 20
    finally:
        window.close()
