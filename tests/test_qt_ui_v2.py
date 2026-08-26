from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QAbstractSpinBox, QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QGridLayout, QGroupBox, QLabel, QLineEdit, QPushButton, QSpinBox

from thermo_acoustic import qt_ui, qt_ui_v2
from thermo_acoustic.application import (
    STEP_CAPTURE_FRAMES,
    STEP_CONFIGURE_CAMERA,
    STEP_CONFIGURE_WFG,
    STEP_FLUSH,
    STEP_INITIALIZE_EXPERIMENT,
    STEP_ORDER,
    STEP_SAVE_RESULTS,
    STEP_WAIT_FOR_AD2_COMPLETION,
)
from thermo_acoustic.hardware_factory import HardwareRuntimeConfig

from conftest import build_with_retry


def make_window(monkeypatch, tmp_path) -> qt_ui_v2.MainWindowV2:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({}), encoding="utf-8")
    monkeypatch.setattr(qt_ui, "SETTINGS_PATH", settings_path)
    QApplication.instance() or QApplication([])
    return build_with_retry(qt_ui_v2.MainWindowV2)


@pytest.mark.parametrize(
    ("module", "window_class"),
    ((qt_ui, qt_ui.MainWindow), (qt_ui_v2, qt_ui_v2.MainWindowV2)),
)
def test_reinitialize_refuses_replacement_bundle_when_existing_cleanup_fails(
    monkeypatch, tmp_path, module, window_class
):
    class FailingCleanupApplication:
        def __init__(self):
            self.errors = []

        def cleanup(self):
            raise RuntimeError("simulated blocked hardware cleanup")

        def check_loop_error(self, error):
            self.errors.append(error)

    class WindowHolder:
        app = FailingCleanupApplication()

    replacement_calls = []
    monkeypatch.setattr(module, "build_hardware_bundle", lambda config: replacement_calls.append("build"))
    monkeypatch.setattr(module, "apply_hardware_bundle", lambda app, bundle: replacement_calls.append("apply"))
    config = HardwareRuntimeConfig(
        ad2_enabled=False,
        sim_ad2=True,
        camera_enabled=False,
        sim_camera=True,
        pump_enabled=False,
        sim_pump=True,
        valve_enabled=False,
        sim_valve=True,
        z_enabled=False,
        thorlabs_apt_serial="",
        valve_resource="COM5",
        cetoni_config_path=tmp_path,
    )

    with pytest.raises(RuntimeError, match="refusing to initialize a replacement hardware bundle"):
        window_class._initialize_system(WindowHolder(), config)

    assert replacement_calls == []
    assert len(WindowHolder.app.errors) == 1


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

    window_v1 = build_with_retry(qt_ui.MainWindow)
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
        assert window.windowTitle() == "Thermo Acoustic Streaming - Transitional UI (shared hardware runtime)"
        assert window.connection_button.text() == "* Not Connected"
    finally:
        window.close()


def test_v2_abort_menu_explains_graceful_not_mid_operation_semantics(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        actions = {action.text(): action for action in window.menuBar().actions()}
        assert "Abort" in actions
        tooltip = actions["Abort"].toolTip()
        assert "current repeat" in tooltip
        assert "does not stop hardware" in tooltip
    finally:
        window.close()


def test_v2_menu_actions_have_stable_identifiers_for_layout_adapters(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        actions = {action.objectName(): action for action in window.menuBar().actions()}
        assert set(actions) == {
            "menuExitAction",
            "menuAbortAction",
            "menuSaveSettingsAction",
            "menuLoadSettingsAction",
        }
        assert actions["menuSaveSettingsAction"].text() == "Save Settings"
        assert actions["menuLoadSettingsAction"].text() == "Load Settings"
    finally:
        window.close()


def test_v2_start_experiment_discloses_shared_real_hardware_boundary(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        start_exp = next(button for button in window.findChildren(QPushButton) if button.text() == "Start exp")
        assert "currently initialized backends" in start_exp.toolTip()
        assert "not protected" in start_exp.toolTip()
        assert "Abort stops only after" in start_exp.toolTip()
    finally:
        window.close()


@pytest.mark.known_flaky
def test_v2_sidebar_opening_manual_panel_does_not_initialize_hardware(monkeypatch, tmp_path):
    # Informational marker only: this test produced the same PySide
    # _TooltipIconWrapper NULL-without-exception failure both before and after
    # the v3-acceptance changes. It is intentionally not retried or hidden.
    window = make_window(monkeypatch, tmp_path)
    try:
        window._open_manual_panel("WFG")

        assert "WFG" in window._manual_panels
        assert window._manual_panels["WFG"].isVisible()
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
    # qt_ui.py's own tab bar uses for this feature ("Pump&Valve").
    window = make_window(monkeypatch, tmp_path)
    try:
        button_texts = [
            button.text()
            for button in window.findChildren(QPushButton)
            if button.text() in ("WFG", "MSO", "PumpValve", "Pump&Valve", "Camera")
        ]
        assert "Pump&Valve" in button_texts
        assert "PumpValve" not in button_texts
    finally:
        window.close()


def test_v2_sidebar_buttons_open_existing_manual_test_panels(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        for panel_name in ("WFG", "MSO", "PumpValve", "Camera"):
            dialog = build_with_retry(lambda panel_name=panel_name: window._ensure_manual_panel(panel_name))

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
        wfg_frequency_label = window._manual_panels["WFG"].findChild(
            QLabel, "manualWfgCarrier_frequencyLabel"
        )
        assert wfg_frequency_label is not None
        assert wfg_frequency_label.text().startswith("Frequency (kHz) Carrier")
        window.wfg_channels[0]["enable"].setChecked(True)
        window.wfg_channels[1]["enable"].setChecked(True)
        window._update_wfg_preview()
        assert set(window.wfg_preview_graph._series) == {"Ch1", "Ch2"}

        mso_dialog_widgets = window._manual_panels["MSO"].findChildren(type(window.mso_sample_frequency))
        assert window.mso_sample_frequency in mso_dialog_widgets
    finally:
        window.close()


def test_v2_valve_status_flags_unverified_and_busy_responses(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        window.app.valve.initialized = True

        window.app.valve.status_note = "confirmed"
        window.app.valve.position = 1
        window._refresh_status()
        assert window.valve_connection_status.text() == "Connected"
        assert window.valve_position_status.text() == "1 (P01)"

        window.app.valve.position = 2
        window.app.valve.status_note = "requested P02; confirmation pending"
        window._refresh_status()
        assert window.valve_position_status.text() == "2 (P02)"
        assert window.valve_connection_status.text() == "Connected (requested P02; confirmation pending)"

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
        first = build_with_retry(lambda: window._ensure_manual_panel("Camera"))
        second = build_with_retry(lambda: window._ensure_manual_panel("Camera"))

        assert first is second
    finally:
        window.close()


def test_v2_initialization_dialog_reuses_existing_config_widgets(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        dialog = build_with_retry(window._ensure_initialization_dialog)
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
        assert window.tec_enabled in checkboxes
        assert window.sim_tec in checkboxes
        assert window.thorlabs_apt_discovery_only in checkboxes
        assert "Only one UI window should control real hardware at a time. Close the other UI window before initializing here." in labels
        assert "Z-stage" in dialog._status_labels
        assert dialog._status_labels["Z-stage"].text() == "Waiting"
        assert "TEC" in dialog._status_labels
        assert dialog._status_labels["TEC"].text() == "Waiting"
    finally:
        window.close()


def _unwrap_grid_cell(grid: QGridLayout, row: int, col: int):
    """The cell's real widget, unwrapping the tooltip-icon container
    _wrap_with_tooltip_icon() creates for any tooltipped field (same
    pattern as _form_field_widget() above, for QGridLayout cells instead
    of QFormLayout rows)."""
    widget = grid.itemAtPosition(row, col).widget()
    layout = widget.layout()
    if layout is not None and layout.count():
        return layout.itemAt(0).widget()
    return widget


def test_v2_initialization_dialog_device_column_order_is_device_simulate_enable(monkeypatch, tmp_path):
    # Pending feedback item 2: was Enable | Simulate | Device; reordered to
    # Device | Simulate | Enable (device identity first, then whether it's
    # simulated, then whether it's enabled at all).
    window = make_window(monkeypatch, tmp_path)
    try:
        dialog = build_with_retry(window._ensure_initialization_dialog)
        devices_group = next(
            group for group in dialog.findChildren(QGroupBox) if group.title() == "Devices"
        )
        grid = devices_group.layout()
        assert isinstance(grid, QGridLayout)

        header_texts = [grid.itemAtPosition(0, col).widget().text() for col in range(4)]
        assert header_texts == ["Device", "Simulate", "Enable", "Progress"]

        rows = (
            (1, "AD2", window.sim_ad2, window.ad2_enabled),
            (2, "Camera", window.sim_camera, window.camera_enabled),
            (3, "Pump", window.sim_pump, window.pump_enabled),
            (4, "Valve", window.sim_valve, window.valve_enabled),
            (6, "TEC", window.sim_tec, window.tec_enabled),
        )
        for row, name, simulate_widget, enable_widget in rows:
            assert grid.itemAtPosition(row, 0).widget().text() == name
            assert _unwrap_grid_cell(grid, row, 1) is simulate_widget
            assert _unwrap_grid_cell(grid, row, 2) is enable_widget
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
        thorlabs_apt_serial="44533854",
            valve_resource="COM6",
            cetoni_config_path=tmp_path,
            tec_enabled=False,
            sim_tec=True,
            tec_port="",
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
            ("TEC", "In Progress"),
        ]
        assert window.app.status == "System Initialized"
        window._refresh_status()
        assert window.connection_button.text() == "* Connected"
        assert window.ad2_connection_status.text() == "Connected"
        assert window.camera_connection_status.text() == "Connected"
        assert window.pump_connection_status.text() == "Connected"
        assert window.valve_connection_status.text() == "Connected"

        # Bug fix regression test (found during v3 design evaluation,
        # 2026-08-06): connection_button used to derive "connected" from
        # `self.app.status == "System Initialized"`, a general status
        # string every later action overwrites -- a flush, a refill, an
        # experiment run, etc. -- so the button flipped to red
        # "* Not Connected" after the very first successful post-init
        # action, even though hardware was still fully connected. Same
        # "directly overwrite window.app.status to simulate a later
        # action" pattern already used above for the analogous
        # experiment_running_status fix (Category 2, Session 39).
        window.app.status = "FlushComplete"
        window._refresh_status()
        assert window.connection_button.text() == "* Connected"
        assert window.connection_button.styleSheet() == "color: green;"
    finally:
        window.close()


def test_v2_tec_init_failure_leaves_other_devices_genuinely_connected(monkeypatch, tmp_path):
    # Architecture fix (2026-08-13), superseding the 2026-08-03 regression
    # test this replaces: devices are confirmed functionally independent
    # (no device's initialize() reads another's state), so
    # Application.initialize() no longer rolls back AD2/Camera/Pump/Valve
    # just because a later, unrelated device (TEC here) fails -- see
    # docs/hardware_repair_plan.md's "Initialization And Failure Recovery".
    # The old version of this test asserted the opposite (rollback was
    # real and the dialog had to report it); this confirms the new,
    # correct behavior: the Initialize dialog's per-device rows AND
    # Global Status both genuinely agree the earlier devices stayed
    # connected, and only TEC (the device that actually failed) shows
    # "Failed".
    from thermo_acoustic.tec import TecController

    def _raise_tec_failure(self) -> None:
        raise RuntimeError("TEC not found")

    monkeypatch.setattr(TecController, "initialize", _raise_tec_failure)

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
        thorlabs_apt_serial="44533854",
        valve_resource="COM6",
        cetoni_config_path=tmp_path,
        tec_enabled=True,
        sim_tec=True,
        tec_port="",
    )
    try:
        with pytest.raises(RuntimeError, match="TEC initialize failed"):
            window._initialize_system(config, lambda kind, value: events.append((kind, value)))

        # Each device's own genuine outcome is reported -- AD2/Camera/Pump/
        # Valve stay "Complete", only TEC shows "Failed". No "Rolled back"
        # text anywhere; nothing gets rolled back anymore.
        final_status: dict[str, str] = {}
        for kind, value in events:
            if kind == "init_device":
                name, status = value
                final_status[name] = status
        for name in ("AD2", "Camera", "Pump", "Valve"):
            assert "Complete" in final_status[name], f"{name}: {final_status[name]}"
            assert "Rolled back" not in final_status[name], f"{name}: {final_status[name]}"
        assert final_status["TEC"] == "Failed"

        # Global Status must AGREE with the dialog: genuinely still
        # connected, not artificially disconnected by a rollback that no
        # longer happens.
        window._refresh_status()
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


def _form_field_widget(form, row):
    """The row's real field widget, unwrapping the [field, ⓘ icon]
    container _wrap_with_tooltip_icon() (Session 41, Part 2) creates for any
    tooltipped field -- a plain (untooltipped) field has no layout of its
    own, so this is a no-op for those; a wrapped field's real widget is
    always its container's first child."""
    widget = form.itemAt(row, form.ItemRole.FieldRole).widget()
    layout = widget.layout()
    if layout is not None and layout.count():
        return layout.itemAt(0).widget()
    return widget


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
        # Both groups' fields carry tooltips (Session 41 kept them, as
        # cross-parameter dependencies), so their FieldRole slot now holds
        # the [field, ⓘ icon] wrapper container _wrap_with_tooltip_icon()
        # creates -- _form_field_widget() unwraps it to get back to the
        # real, identical widget instance.
        fm_sweep_group = build_with_retry(window._experiment_fm_sweep_group)
        fm_sweep_form = fm_sweep_group.layout()
        assert _form_field_widget(fm_sweep_form, 1) is window.exp_sweep_start_khz
        assert _form_field_widget(fm_sweep_form, 2) is window.exp_sweep_stop_khz

        freq_scan_group = build_with_retry(window._experiment_frequency_scan_group)
        freq_scan_form = freq_scan_group.layout()
        assert _form_field_widget(freq_scan_form, 1) is window.exp_freq_scan_start_khz
        assert _form_field_widget(freq_scan_form, 3) is window.exp_freq_scan_count

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
                dialog = build_with_retry(lambda name=name: window._ensure_manual_panel(name))
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


_TOOLTIP_COVERAGE_WIDGET_TYPES = (QDoubleSpinBox, QSpinBox, QComboBox, QCheckBox, QLineEdit)


def _has_tooltip_icon(widget) -> bool:
    """True if widget's immediate parent is one of
    MainWindow._wrap_with_tooltip_icon()'s _TooltipIconWrapper containers
    (Session 41, Part 2) -- same isinstance() check as qt_ui.py's own
    completeness test, kept as an independent copy per this project's own
    "verify as two genuinely separate live instances" convention (Session
    28/29/33) -- never assume v2 inherits v1's coverage just because widgets
    are shared."""
    return isinstance(widget.parentWidget(), qt_ui._TooltipIconWrapper)


def _tooltip_coverage_sweep(window) -> list[tuple[str, str, bool, bool]]:
    """Same generic findChildren() sweep as qt_ui.py's own completeness
    test, kept as an independent copy per this project's own "verify as two
    genuinely separate live instances" convention (Session 28/29/33) --
    never assume v2 inherits v1's coverage just because widgets are shared.

    Excludes the AD2 Output Parameters table's per-channel field widgets
    (_v2_ad2_output_group()): those are the SAME shared instances the
    Experiment tab's own labeled rows use, and that method's own comment
    documents deliberately not wrapping them with an icon there, to avoid
    changing what grid.itemAtPosition(row, col).widget() returns and
    breaking that table's pre-existing Session 24/25 identity tests -- a
    tradeoff made before this session's Part 1 narrowing existed, but which
    still applies now that these particular fields carry real tooltip text
    (kept, not self-evident). The explanation is still reachable via this
    same widget's icon wherever v1's Experiment tab shows it."""
    excluded_ids = {id(widget) for channel in window.exp_ad2_channels for widget in channel.values()}
    results = []
    for widget_cls in _TOOLTIP_COVERAGE_WIDGET_TYPES:
        for widget in window.findChildren(widget_cls):
            if isinstance(widget.parent(), (QAbstractSpinBox, QComboBox)):
                continue
            if id(widget) in excluded_ids:
                continue
            tip = widget.toolTip()
            results.append((type(widget).__name__, tip, bool(tip), _has_tooltip_icon(widget)))
    return results


def test_v2_every_value_widget_has_a_tooltip_and_visible_marker(monkeypatch, tmp_path):
    # Requirement A/B/C completeness test, revised (Session 41): Session 40
    # required a tooltip on all 172(+) fields; this session narrowed coverage
    # back to genuinely non-obvious fields only and replaced the label-style
    # marker with a separate ⓘ icon widget (see the Session 41 changelog
    # entry for the full classification and rationale -- v1's own test
    # asserts the exact 127-of-172 split; this v2 sweep additionally covers
    # MainWindowV2's own sidebar/status/init-dialog widgets on top of that
    # same 172, so it checks COHERENCE generically instead of a second
    # hardcoded count). Covers MainWindowV2's own window AND its
    # Initialization dialog AND all four manual-panel dialogs (the latter
    # reuse qt_ui.py's builder methods directly, but this confirms that
    # reuse genuinely carries the tooltips/markers through, not just
    # structurally).
    window = make_window(monkeypatch, tmp_path)
    try:
        build_with_retry(window._ensure_initialization_dialog)
        for name in ("WFG", "MSO", "PumpValve", "Camera"):
            build_with_retry(lambda name=name: window._ensure_manual_panel(name))

        results = _tooltip_coverage_sweep(window)
        # 173 real widgets minus the AD2 Output Parameters table's 24
        # deliberately-excluded shared field widgets (2 channels x 12 fields
        # each -- see _tooltip_coverage_sweep()'s docstring).
        assert len(results) >= 149, f"expected at least 149 real widgets, found {len(results)}"

        missing_marker = [(cls, tip) for cls, tip, has_tip, marked in results if has_tip and not marked]
        assert not missing_marker, f"tooltipped widgets missing the visible icon marker: {missing_marker}"

        unwanted_marker = [cls for cls, _tip, has_tip, marked in results if not has_tip and marked]
        assert not unwanted_marker, f"widgets with no tooltip but an icon marker anyway: {unwanted_marker}"

        # Spot-check a representative sample from both sides of the Session
        # 41 classification, reached via v2's manual-panel reuse of v1's
        # builder methods (full list and rationale in the changelog).
        assert window.custom_syringe_volume_ml.toolTip()  # named dependency example, kept
        assert window.dcam_source.toolTip()  # unverified status, kept
        assert not window.wfg_channels[0]["frequency"].toolTip()  # self-evident, removed
        assert not window.flush_count.toolTip()  # self-evident, removed
    finally:
        window.close()


def test_v2_experiment_setup_tabs_has_four_task_oriented_tabs(monkeypatch, tmp_path):
    # v3 design-idea adoption, Proposal B (2026-08-05): replaces the former
    # per-step card sequence (Phase 2) with task-oriented setup tabs,
    # grouping by what an operator is configuring rather than
    # run_experiment2()'s internal step order.
    window = make_window(monkeypatch, tmp_path)
    try:
        tabs = build_with_retry(window._v2_experiment_setup_tabs)
        assert [tabs.tabText(i) for i in range(tabs.count())] == [
            "AD2 Output",
            "Camera",
            "Fluidics",
            "Advanced",
        ]
    finally:
        window.close()


@pytest.mark.known_flaky
def test_v2_experiment_setup_tabs_embeds_the_real_shared_group_widgets(monkeypatch, tmp_path):
    # Informational marker only: this test produced a Shiboken "Internal C++
    # object ... already deleted" failure in 2/6 isolated runs across c5665b3
    # and bcd1634. It is intentionally not retried, skipped, or xfailed.
    # Each tab re-parents v2's existing shared group-box builders whole (not
    # rebuilt) -- confirm identity, matching this file's established
    # reuse-verification convention (e.g.
    # test_v2_experiment_area_exposes_fm_sweep_and_frequency_scanning above).
    window = make_window(monkeypatch, tmp_path)
    try:
        tabs = build_with_retry(window._v2_experiment_setup_tabs)

        ad2_tab = tabs.widget(0)
        assert ad2_tab.isAncestorOf(window.exp_ad2_channels[0]["enable"])
        assert ad2_tab.isAncestorOf(window.exp_ad2_channels[1]["enable"])
        assert ad2_tab.isAncestorOf(window.exp_sweep_start_khz)
        assert ad2_tab.isAncestorOf(window.exp_freq_scan_start_khz)

        camera_tab = tabs.widget(1)
        assert camera_tab.isAncestorOf(window.exp_camera_fps)
        assert camera_tab.isAncestorOf(window.exp_frames)

        fluidics_tab = tabs.widget(2)
        assert fluidics_tab.isAncestorOf(window.exp_flush_flowrate)
        assert fluidics_tab.isAncestorOf(window.exp_wait_after_flush)

        advanced_tab = tabs.widget(3)
        assert advanced_tab.isAncestorOf(window.exp_tec_scan_enable)
        assert advanced_tab.isAncestorOf(window.exp_tec_points)
    finally:
        window.close()


def test_v2_flush_group_tooltip_explains_the_real_sequential_valve_pump_relationship(monkeypatch, tmp_path):
    # Part A/C follow-up (2026-08-04), moved onto the Flush group itself
    # when Proposal B retired the step-card view that used to carry this
    # tooltip: the real sequence (confirmed against the LabVIEW source and
    # the current Python flush()) is valve position 1 -> pump move -> valve
    # position 2, strictly sequential -- the pump never flows through a
    # valve switch. Hovering the Flush group should still say so.
    window = make_window(monkeypatch, tmp_path)
    try:
        tabs = build_with_retry(window._v2_experiment_setup_tabs)
        fluidics_tab = tabs.widget(2)
        flush_groups = [g for g in fluidics_tab.findChildren(QGroupBox) if g.title() == "Flush settings"]
        assert len(flush_groups) == 1

        tooltip = flush_groups[0].toolTip()
        assert "position 1" in tooltip
        assert "position 2" in tooltip
        assert "idle" in tooltip.lower()
    finally:
        window.close()


def test_v2_experiment_setup_tabs_have_inline_safety_caveats(monkeypatch, tmp_path):
    # Proposal B's second half: the safety-relevant tabs carry inline
    # caveat text where the control lives, matching this project's actual
    # current TEC/fluidics safety framing (not invented wording).
    window = make_window(monkeypatch, tmp_path)
    try:
        tabs = build_with_retry(window._v2_experiment_setup_tabs)
        fluidics_text = " ".join(label.text() for label in tabs.widget(2).findChildren(QLabel))
        advanced_text = " ".join(label.text() for label in tabs.widget(3).findChildren(QLabel))
        assert "disabled by default" in fluidics_text.lower()
        assert "simulated by default" in advanced_text.lower()
    finally:
        window.close()


def test_v2_primary_run_control_group_reuses_series_path_and_start_button(monkeypatch, tmp_path):
    # v3 design-idea adoption, Proposal A (2026-08-05): confirms the
    # elevated run-control group reuses the real self.series_path widget
    # (no new state) and its Start button is wired to the same
    # self._start_experiment handler the old "Sequence Control" card used.
    window = make_window(monkeypatch, tmp_path)
    try:
        group = build_with_retry(window._experiment_primary_run_control_group)
        assert group.isAncestorOf(window.series_path)
        buttons = group.findChildren(QPushButton)
        start_buttons = [b for b in buttons if b.text() == "Start exp"]
        assert len(start_buttons) == 1
        assert start_buttons[0].minimumHeight() >= 44
    finally:
        window.close()


def test_v2_configuration_column_places_run_control_above_setup_tabs(monkeypatch, tmp_path):
    # Confirms the run-control group sits inside the scrolling configuration
    # column (not stacked above the config/live-monitoring split, which
    # would compete with the live-monitoring column's own always-visible
    # screen space -- the specific mistake flagged when v3 was evaluated).
    window = make_window(monkeypatch, tmp_path)
    try:
        area = build_with_retry(window._configuration_column)
        content = area.widget()
        assert content.isAncestorOf(window.series_path)
        assert content.isAncestorOf(window.exp_tec_scan_enable)
    finally:
        window.close()


def test_v2_step_breadcrumb_has_seven_markers_in_step_order(monkeypatch, tmp_path):
    # Phase 3 step-progress breadcrumb (2026-08-04): derives its 7-step
    # order from application.py's STEP_ORDER, the single source of truth,
    # all pending before any real progress event has ever arrived.
    window = make_window(monkeypatch, tmp_path)
    try:
        assert tuple(window.step_breadcrumb._markers.keys()) == STEP_ORDER
        for step_name in STEP_ORDER:
            assert window.step_breadcrumb.state_of(step_name) == "pending"
    finally:
        window.close()


def test_v2_step_breadcrumb_marks_active_step_on_step_started_event(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        window._handle_worker_progress("step_started", STEP_CONFIGURE_WFG)

        assert window.step_breadcrumb.state_of(STEP_CONFIGURE_WFG) == "active"
        # Untouched steps stay pending -- a step_started event for one step
        # must not imply anything about any other step's own state.
        assert window.step_breadcrumb.state_of(STEP_INITIALIZE_EXPERIMENT) == "pending"
        assert window.step_breadcrumb.state_of(STEP_CAPTURE_FRAMES) == "pending"
    finally:
        window.close()


def test_v2_step_breadcrumb_completed_and_failed_styling_are_distinct_from_active(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        window._handle_worker_progress("step_started", STEP_INITIALIZE_EXPERIMENT)
        window._handle_worker_progress("step_completed", STEP_INITIALIZE_EXPERIMENT)
        window._handle_worker_progress("step_started", STEP_CONFIGURE_WFG)
        window._handle_worker_progress("step_failed", (STEP_CONFIGURE_WFG, "simulated failure"))
        window._handle_worker_progress("step_started", STEP_CONFIGURE_CAMERA)

        assert window.step_breadcrumb.state_of(STEP_INITIALIZE_EXPERIMENT) == "completed"
        assert window.step_breadcrumb.state_of(STEP_CONFIGURE_WFG) == "failed"
        assert window.step_breadcrumb.state_of(STEP_CONFIGURE_CAMERA) == "active"

        # Three genuinely different states must render three genuinely
        # different colors -- not just three different internal state
        # strings that happen to look identical on screen.
        completed_style = window.step_breadcrumb._markers[STEP_INITIALIZE_EXPERIMENT].styleSheet()
        failed_style = window.step_breadcrumb._markers[STEP_CONFIGURE_WFG].styleSheet()
        active_style = window.step_breadcrumb._markers[STEP_CONFIGURE_CAMERA].styleSheet()
        assert len({completed_style, failed_style, active_style}) == 3
    finally:
        window.close()


def test_v2_step_breadcrumb_step_reset_clears_every_marker_including_mid_highlight_ones(monkeypatch, tmp_path):
    # TestStand-lesson-aware reset (same discipline as
    # _stopping_after_current_repeat elsewhere in this codebase): a
    # step_reset must return EVERY marker to "pending", including one that
    # was still "active" (interrupted mid-step, not cleanly completed) and
    # ones already "completed" -- not rely on the next repeat's own step
    # events to eventually overwrite each marker one at a time, which would
    # leave a misleading "already partway done" impression for however long
    # that takes.
    window = make_window(monkeypatch, tmp_path)
    try:
        window._handle_worker_progress("step_started", STEP_INITIALIZE_EXPERIMENT)
        window._handle_worker_progress("step_completed", STEP_INITIALIZE_EXPERIMENT)
        window._handle_worker_progress("step_started", STEP_CONFIGURE_WFG)
        window._handle_worker_progress("step_completed", STEP_CONFIGURE_WFG)
        # STEP_CONFIGURE_CAMERA left "active" -- simulates a repeat
        # interrupted mid-step (e.g. an Abort-triggered stop between
        # repeats, or a prior repeat's step_failed never explicitly fired).
        window._handle_worker_progress("step_started", STEP_CONFIGURE_CAMERA)

        window._handle_worker_progress("step_reset", None)

        for step_name in STEP_ORDER:
            assert window.step_breadcrumb.state_of(step_name) == "pending", step_name
    finally:
        window.close()


def test_v1_window_tracks_step_states_without_a_breadcrumb_widget(monkeypatch, tmp_path):
    # Base MainWindow (v1, qt_ui.py) has no breadcrumb widget, but still
    # tracks _step_states -- _refresh_step_breadcrumb() is a no-op there,
    # confirming the base-tracks/subclass-renders split doesn't crash
    # without a v2-only widget present.
    from test_qt_ui_hardware_settings import make_window as make_v1_window

    window = make_v1_window(monkeypatch, tmp_path)
    try:
        assert not hasattr(window, "step_breadcrumb")
        window._handle_worker_progress("step_started", STEP_FLUSH)
        assert window._step_states[STEP_FLUSH] == "active"
        window._handle_worker_progress("step_reset", None)
        assert all(state == "pending" for state in window._step_states.values())
    finally:
        window.close()
