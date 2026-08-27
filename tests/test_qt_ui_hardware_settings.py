from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QAbstractSpinBox, QCheckBox, QComboBox, QDoubleSpinBox, QGroupBox, QLabel, QLineEdit, QMainWindow, QPushButton, QScrollArea, QSpinBox, QWidget
from PySide6.QtWidgets import QApplication

from thermo_acoustic import qt_ui, qt_ui_v2, qt_ui_v3
from thermo_acoustic.ad2 import WfgChannelConfig, WfgConfig
from thermo_acoustic.camera import SubRegion
from thermo_acoustic.hardware_config import ZStageBackend, default_hardware_config
from thermo_acoustic.instruments import AD2Sdk
from thermo_acoustic.waveforms import WaveFormsBackend

from conftest import build_with_retry


def make_window(monkeypatch, tmp_path, settings: dict | None = None) -> qt_ui.MainWindow:
    settings_path = tmp_path / "settings.json"
    if settings is not None:
        settings_path.write_text(json.dumps(settings), encoding="utf-8")
    monkeypatch.setattr(qt_ui, "SETTINGS_PATH", settings_path)
    QApplication.instance() or QApplication([])
    return build_with_retry(qt_ui.MainWindow)


def test_build_state_is_one_shared_widget_contract_across_all_ui_surfaces():
    assert "_build_state" not in qt_ui_v2.MainWindowV2.__dict__
    assert "_build_state" not in qt_ui_v3.MainWindowV3.__dict__
    assert qt_ui_v2.MainWindowV2._build_state is qt_ui.MainWindow._build_state
    assert qt_ui_v3.MainWindowV3._build_state is qt_ui.MainWindow._build_state

    QApplication.instance() or QApplication([])

    snapshots: dict[type, tuple[frozenset[str], frozenset[str]]] = {}

    def contains_widget(value) -> bool:
        if isinstance(value, QWidget):
            return True
        if isinstance(value, dict):
            return any(contains_widget(item) for item in value.values())
        if isinstance(value, (list, tuple)):
            return any(contains_widget(item) for item in value)
        return False

    state_holders = []
    for window_class in (qt_ui.MainWindow, qt_ui_v2.MainWindowV2, qt_ui_v3.MainWindowV3):
        # Exercise the inherited method on each real subclass type without
        # constructing any layout. Full v2/v3 layouts re-parent these shared
        # widgets and are intentionally outside this state-contract test.
        holder = window_class.__new__(window_class)
        QMainWindow.__init__(holder)
        before = set(holder.__dict__)
        holder._build_state()
        added = frozenset(set(holder.__dict__) - before)
        widget_attributes = frozenset(
            name for name in added if contains_widget(holder.__dict__[name])
        )
        snapshots[window_class] = (added, widget_attributes)
        state_holders.append(holder)

    expected_attributes, expected_widget_attributes = snapshots[qt_ui.MainWindow]
    assert len(expected_widget_attributes) > 100, "sanity check: capture the real shared widget state"
    for window_class in (qt_ui_v2.MainWindowV2, qt_ui_v3.MainWindowV3):
        assert snapshots[window_class][0] == expected_attributes
        assert snapshots[window_class][1] == expected_widget_attributes


def combo_items(widget) -> list[str]:
    return [widget.itemText(index) for index in range(widget.count())]


def process_events_until(condition, timeout_s: float = 2.0) -> bool:
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        QApplication.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    QApplication.processEvents()
    return condition()


def test_focus_wheel_guard_ignores_unfocused_spinbox_wheel():
    QApplication.instance() or QApplication([])
    guard = qt_ui.FocusWheelGuard()
    spin = QDoubleSpinBox()

    try:
        event = QEvent(QEvent.Type.Wheel)

        handled = guard.eventFilter(spin, event)

        assert handled is True
        assert not event.isAccepted()
    finally:
        spin.close()


def _experiment_ad_settings_group(window: qt_ui.MainWindow) -> QGroupBox:
    for index in range(window.tabs.count()):
        if window.tabs.tabText(index) == "Experiment":
            window.tabs.setCurrentIndex(index)
            break
    QApplication.processEvents()
    QApplication.processEvents()
    return next(
        group for group in window.tabs.currentWidget().findChildren(QGroupBox)
        if group.title() == "Analog Discovery Settings"
    )


def test_frequency_scan_group_names_the_python_channel_it_actually_changes(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        titles = {group.title() for group in window.findChildren(QGroupBox)}
        assert "Frequency Scanning (Dynamic Frequency, CH0 only)" in titles
        assert all("Ch1 only" not in title for title in titles)
    finally:
        window.close()


def _synthetic_wheel_event(target, dy: int = 120) -> QWheelEvent:
    pos = QPointF(max(target.width(), 1) / 2, max(target.height(), 1) / 2)
    return QWheelEvent(
        pos, QPointF(target.mapToGlobal(pos.toPoint())),
        QPoint(0, 0), QPoint(0, dy),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase, False,
    )


def test_ad_settings_group_fields_render_at_visible_heights(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    window.show()
    QApplication.processEvents()

    group = _experiment_ad_settings_group(window)
    scroll = group.findChild(QScrollArea)
    assert scroll is not None, "Analog Discovery Settings group must wrap its content in a QScrollArea"
    assert scroll.maximumHeight() <= 400, "scroll area should have a fixed, reasonable maximum height"

    # Previously these collapsed to 0-1px tall when the group was squeezed below
    # its minimumSizeHint by the surrounding grid; confirm they now render at
    # their real, natural height inside the scroll area.
    for widget in (
        window.exp_ch1_enable, window.exp_ch1_freq, window.exp_ch1_amp,
        window.exp_ch1_symmetry, window.exp_ch1_phase, window.exp_ch1_repeat_trigger,
        window.exp_ch2_phase, window.exp_ch2_repeat_trigger,
    ):
        assert widget.geometry().height() > 5, f"{widget} rendered collapsed (height={widget.geometry().height()})"


def test_ad_settings_scroll_area_wheel_guard_interaction(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    window.show()
    QApplication.processEvents()

    group = _experiment_ad_settings_group(window)
    scroll = group.findChild(QScrollArea)
    vbar = scroll.verticalScrollBar()

    # Unfocused spin box: wheel must scroll the area, not change the value.
    window.exp_ch1_freq.clearFocus()
    vbar.setValue(0)
    QApplication.processEvents()
    before_value = window.exp_ch1_freq.value()
    QApplication.sendEvent(window.exp_ch1_freq, _synthetic_wheel_event(window.exp_ch1_freq, dy=-120))
    QApplication.processEvents()
    assert window.exp_ch1_freq.value() == before_value
    assert vbar.value() > 0, "wheel over an unfocused spin box should scroll the containing QScrollArea"

    # Focused spin box: wheel should still edit its own value (existing, unchanged behavior).
    vbar.setValue(0)
    window.exp_ch1_freq.setFocus(Qt.FocusReason.OtherFocusReason)
    QApplication.processEvents()
    assert window.exp_ch1_freq.hasFocus()
    before_focused_value = window.exp_ch1_freq.value()
    QApplication.sendEvent(window.exp_ch1_freq, _synthetic_wheel_event(window.exp_ch1_freq, dy=120))
    QApplication.processEvents()
    assert window.exp_ch1_freq.value() != before_focused_value


def test_no_group_box_is_squeezed_below_its_minimum_size_hint(monkeypatch, tmp_path):
    # Systematic re-audit (Task C): the same collapse symptom that hit
    # "Analog Discovery Settings" (Session 28) and "Ch1"/"Ch2" (this session --
    # this session's own longer live-use labels pushed the WFG tab's groups
    # over the same edge) is checked here across every QGroupBox in every tab,
    # generically via findChildren() -- not a hardcoded list -- so it stays
    # valid as new groups/fields are added later.
    #
    # Checked at both the app's real *default* size (1280x820) and its
    # documented *minimum* (980x680, self.setMinimumSize()) -- Session 39's
    # audit found "Camera Start Array(s)" only collapsed at the minimum size
    # (252px actual vs. 346px required), invisible at the default size this
    # test previously checked exclusively.
    window = make_window(monkeypatch, tmp_path)
    window.show()

    for width, height in ((1280, 820), (980, 680)):
        window.resize(width, height)
        QApplication.processEvents()
        QApplication.processEvents()

        failures = []
        for index in range(window.tabs.count()):
            window.tabs.setCurrentIndex(index)
            QApplication.processEvents()
            QApplication.processEvents()
            for group in window.tabs.currentWidget().findChildren(QGroupBox):
                geometry = group.geometry()
                min_hint = group.minimumSizeHint()
                if min_hint.height() > 0 and geometry.height() < min_hint.height():
                    failures.append(
                        (window.tabs.tabText(index), group.title(), geometry.height(), min_hint.height())
                    )

        assert not failures, (
            f"at window size {width}x{height}: group box(es) squeezed below their own "
            f"minimumSizeHint (rows collapsing to 0-1px): {failures}"
        )


def test_frequency_scanning_start_field_fits_full_precision(monkeypatch, tmp_path):
    # Task 2(a): "1900.000" was rendering as "1900." because the shared
    # _spin() factory capped every QDoubleSpinBox at setMaximumWidth(125)
    # while its real sizeHint() (accounting for the actual displayed
    # decimals) needed up to 252px -- confirmed via an offscreen sweep
    # across every tab, not just this one field. _SPIN_MAX_WIDTH raised to
    # 260 to comfortably cover every sizeHint measured at the time.
    window = make_window(monkeypatch, tmp_path)
    window.resize(1280, 820)
    window.show()
    window.tabs.setCurrentIndex(5)  # Experiment
    QApplication.processEvents()
    QApplication.processEvents()

    field = window.exp_freq_scan_start_khz
    assert field.sizeHint().width() <= field.maximumWidth()
    assert field.geometry().width() >= field.sizeHint().width() - 2


def test_waveform_graph_label_has_safety_margin(monkeypatch, tmp_path):
    # Task 2(b): only a ~5px margin existed between this label's required
    # text width and its actual rendered width at the app's minimum window
    # size (980x680) -- fragile enough to explain a reported "first
    # character cut off" screenshot. setMinimumWidth(200) gives real headroom.
    window = make_window(monkeypatch, tmp_path)
    window.resize(980, 680)  # the app's own minimum size, the tightest case
    window.show()
    window.tabs.setCurrentIndex(5)  # Experiment
    QApplication.processEvents()
    QApplication.processEvents()

    tab = window.tabs.widget(5)
    labels = [lbl for lbl in tab.findChildren(QLabel) if lbl.text() == "Waveform Graph"]
    assert len(labels) == 1
    label = labels[0]
    required = label.fontMetrics().horizontalAdvance(label.text())
    assert label.geometry().width() >= required + 20, "must keep real margin, not just barely fit"


def test_sweep_headers_wrap_instead_of_needing_full_single_line_width(monkeypatch, tmp_path):
    # Task 2(c): both Sweep group headers rendered as one unwrapped ~1300px
    # line inside a horizontally-scrollable area whose visible viewport is
    # much narrower -- since scrolling starts at the left edge, the closing
    # words ("...distinct from Frequency Scanning)") were never visible
    # without scrolling right. Word-wrapping at a bounded width fixes this
    # and, as a side effect, substantially shrinks the group's own natural
    # content width (this was the single widest element in the group).
    window = make_window(monkeypatch, tmp_path)

    window.tabs.setCurrentIndex(1)  # WFG
    QApplication.processEvents()
    wfg_tab = window.tabs.widget(1)
    wfg_headers = [lbl for lbl in wfg_tab.findChildren(QLabel) if "Sweep (FM modulation" in lbl.text()]
    assert wfg_headers, "expected at least one manual-tab Sweep header"
    for label in wfg_headers:
        assert label.wordWrap() is True
        assert label.maximumWidth() < 1000

    window.tabs.setCurrentIndex(5)  # Experiment
    QApplication.processEvents()
    experiment_tab = window.tabs.widget(5)
    experiment_headers = [lbl for lbl in experiment_tab.findChildren(QLabel) if "Sweep (FM modulation" in lbl.text()]
    assert len(experiment_headers) == 1
    assert experiment_headers[0].wordWrap() is True
    assert experiment_headers[0].maximumWidth() < 1000


def test_focus_wheel_guard_covers_every_spin_and_combo_widget(monkeypatch, tmp_path):
    # Completeness test, not a spot check: enumerate every QSpinBox/QDoubleSpinBox/
    # QComboBox in the real widget tree via findChildren() -- not a hardcoded list --
    # so this stays valid and catches any future field that's ever added without
    # going through the guarded _spin()/_int_spin()/_combo() factories.
    window = make_window(monkeypatch, tmp_path)
    window.show()
    QApplication.processEvents()

    targets: list = []
    for widget_cls in (QSpinBox, QDoubleSpinBox, QComboBox):
        targets.extend(window.findChildren(widget_cls))
    assert len(targets) > 50, "sanity check: expected to find the app's real widget tree, not an empty one"

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

    assert not failures, (
        f"{len(failures)} of {len(targets)} spin/combo widgets changed value from an "
        f"unfocused wheel event (FocusWheelGuard gap): {failures}"
    )


def test_representative_fields_have_grounded_tooltips(monkeypatch, tmp_path):
    # Task 3: a sample across every tab, not exhaustive -- confirms tooltips
    # exist and reference the specific documented fact they're grounded in
    # (changelog session numbers, real code paths, or established caveats),
    # not just a restatement of the label.
    window = make_window(monkeypatch, tmp_path)

    # Initialization: stub fields disabled + tooltipped, matching v2's
    # existing InitializationDialog._mark_unwired_stub() convention.
    # thorlabs_apt_serial is no longer one of them -- it's the real piezo's
    # own device serial, genuinely used since the Z-stage repoint (pending
    # feedback item 5, Part B1); prior_resource is the now-unwired one
    # (the legacy PriorZMotor/COM7 path was retired).
    assert not window.z_backend.isEnabled()
    assert "Not wired to a real backend" in window.z_backend.toolTip()
    assert "does not authorize or perform piezo motion" in window.z_enabled.toolTip()
    assert window.thorlabs_apt_serial.isEnabled()
    assert "PiezoStage" in window.thorlabs_apt_serial.toolTip()
    assert not window.prior_resource.isEnabled()
    assert "Not wired to a real backend" in window.prior_resource.toolTip()

    # WFG tab: Symmetry/secWait/Trigger source. sec_run/repeat tooltips were
    # removed in the Session 41 re-narrowing -- their row labels already
    # spell out "[0 = continuous]"/"[0 = infinite]" inline, so a separate
    # tooltip was judged redundant (self-evident), unlike secWait's terse
    # label, which still needs explaining.
    ch1_state = window.wfg_channels[0]
    assert "Duty-cycle" in ch1_state["symmetry"].toolTip()
    assert not ch1_state["sec_run"].toolTip()
    assert not ch1_state["repeat"].toolTip()
    assert "sec_wait" in ch1_state["sec_wait"].toolTip()
    assert "bench-unverified" in ch1_state["sec_wait"].toolTip()

    # MSO tab: Sample Frequency's 100 MS/s AD2 limit, Range's clipping risk.
    assert "100 MS/s" in window.mso_sample_frequency.toolTip() or "UNCONFIRMED" in window.mso_sample_frequency.toolTip()
    assert "clipping" in window.mso_range.toolTip()

    # PumpValve tab: valve position controls, Custom Volume, flow-rate sign convention.
    assert "Custom" in window.custom_syringe_volume_ml.toolTip()
    assert "negative values aspirate/withdraw" in window.flow_rate.toolTip()
    assert "positive values dispense/infuse" in window.flow_rate.toolTip()
    assert "unverifiable" not in window.flow_rate.toolTip()

    # TEC: the current uncommitted adapter can attempt real I/O, so the UI
    # must not incorrectly promise that unchecked Simulate always refuses.
    assert "may attempt real I/O" in window.tec_enabled.toolTip()
    assert "may attempt real I/O" in window.sim_tec.toolTip()
    assert "not independently approved" in window.tec_port.toolTip()

    # Camera tab: DCAM Trigger Source unresolved status.
    assert "oscilloscope" in window.dcam_source.toolTip()

    # Experiment tab: Step Size convention, Frequency Scanning spacing caveat.
    assert "0 = not used" in window.exp_freq_scan_step_khz.toolTip()
    assert "not confirmed" in window.exp_freq_scan_enable.toolTip()
    assert "trigsrcNone" in window.exp_camera_start.toolTip()
    assert "bench-unverified" in window.exp_camera_start.toolTip()
    assert "DCAM Internal trigger" in window.exp_frames.toolTip()
    assert "does not prove" in window.exp_frames.toolTip()


def test_custom_syringe_volume_disabled_unless_syringe_is_custom(monkeypatch, tmp_path):
    # Task 4 investigation (Session 38): Custom Volume is only ever read as a
    # fallback in _syringe_volume_ml() when Syringe="Custom" (ignored for the
    # three named BD presets), and has no effect on ConfigureSyringe's real
    # geometry call -- that is a deliberate, permanent decision (Session 44:
    # geometry is supplied via the separate Custom Inner Diameter/Max Piston
    # Stroke fields instead, see test_configure_syringe_sends_real_geometry_
    # for_custom_not_presets), not an unfixed gap. Disabled whenever a named
    # preset is selected -- same toggle now covers all three Custom-only
    # fields (Volume, Inner Diameter, Stroke).
    window = make_window(monkeypatch, tmp_path)

    # Default is "BD 1ml" -- all three Custom-only fields should start disabled.
    assert window.syringe.currentText() == "BD 1ml"
    assert not window.custom_syringe_volume_ml.isEnabled()
    assert not window.custom_syringe_inner_diameter_mm.isEnabled()
    assert not window.custom_syringe_stroke_mm.isEnabled()

    window.syringe.setCurrentText("Custom")
    assert window.custom_syringe_volume_ml.isEnabled()
    assert window.custom_syringe_inner_diameter_mm.isEnabled()
    assert window.custom_syringe_stroke_mm.isEnabled()

    window.syringe.setCurrentText("BD 5ml")
    assert not window.custom_syringe_volume_ml.isEnabled()
    assert not window.custom_syringe_inner_diameter_mm.isEnabled()
    assert not window.custom_syringe_stroke_mm.isEnabled()

    # Confirm the value is still read (just not editable) when disabled --
    # disabling a QDoubleSpinBox doesn't change its stored .value().
    window.syringe.setCurrentText("Custom")
    window.custom_syringe_volume_ml.setValue(3.5)
    assert window._syringe_volume_ml() == 3.5
    window.syringe.setCurrentText("BD 5ml")
    assert window._syringe_volume_ml() == 5.0  # preset value, custom ignored


def test_configure_syringe_sends_real_geometry_for_custom_not_presets(monkeypatch, tmp_path):
    # Session 44: Custom syringe geometry is wired to configure_syringe()'s
    # real Qmix SDK call via two new dedicated fields (Custom Inner Diameter/
    # Max Piston Stroke), sent only when Syringe="Custom" -- confirms Custom
    # Volume itself is NOT used to derive geometry (a volume alone can't
    # determine both diameter and stroke), and confirms the three named BD
    # presets are completely unaffected (still send only {"name": ...},
    # letting configure_syringe()'s own SYRINGE_PRESETS lookup apply exactly
    # as before this session).
    window = make_window(monkeypatch, tmp_path)
    try:
        configure_syringe_calls = []

        class FakePump:
            def configure_syringe(self, config):
                configure_syringe_calls.append(config)

        window.app.pump = FakePump()

        run_action_calls = []
        monkeypatch.setattr(window, "_run_action", lambda action, status: run_action_calls.append(action))

        window.syringe.setCurrentText("BD 5ml")
        window._start_configure_syringe()
        run_action_calls[-1](lambda *a, **k: None)
        assert configure_syringe_calls[-1] == {"name": "BD 5ml"}

        window.syringe.setCurrentText("Custom")
        window.custom_syringe_volume_ml.setValue(2.5)  # must NOT reach configure_syringe()
        window.custom_syringe_inner_diameter_mm.setValue(7.25)
        window.custom_syringe_stroke_mm.setValue(42.5)
        window._start_configure_syringe()
        run_action_calls[-1](lambda *a, **k: None)
        assert configure_syringe_calls[-1] == {
            "name": "Custom",
            "inner_diameter_mm": 7.25,
            "max_piston_stroke_mm": 42.5,
        }
    finally:
        window.close()


def test_pump_tab_valve_position_controls_show_protocol_tokens_not_unverified_routing(monkeypatch, tmp_path):
    # P01/P02 are protocol-confirmed. Physical fluidic routing remains a
    # hardware-confirmation item and must not be presented as Open/Closed.
    window = make_window(monkeypatch, tmp_path)
    pump_tab = None
    for index in range(window.tabs.count()):
        if window.tabs.tabText(index) == "Pump&Valve":
            pump_tab = window.tabs.widget(index)
            break
    assert pump_tab is not None

    label_texts = {lbl.text() for lbl in pump_tab.findChildren(QLabel)}
    button_texts = {btn.text() for btn in pump_tab.findChildren(QPushButton)}
    assert "Valve Pos1 (P01)" in label_texts
    assert "Valve Pos2 (P02)" in label_texts
    assert "Pos1 (P01)" in button_texts
    assert "Pos2 (P02)" in button_texts
    assert not any("Open" in text or "Closed" in text for text in label_texts | button_texts)


def test_pump_tab_reference_move_is_promoted_to_a_leading_setup_group(monkeypatch, tmp_path):
    # UI layout audit Part 3 design (agreed, then confirmed never actually
    # implemented, 2026-08-03): Reference move used to sit as the LAST row
    # of "Flow Control", mixed in with that group's own experiment-adjacent
    # flow-rate controls, even though it's a one-time-per-mount calibration
    # step that must happen BEFORE Refill/Empty in the real physical
    # sequence. Confirms it now has its own leading "Setup" group and is no
    # longer inside Flow Control.
    #
    # v3 design-idea adoption, Proposal D (2026-08-05): Setup is no longer
    # the first group in the WHOLE tab -- "Operational controls" (touched
    # every run) now reads first, "Static configuration" (Setup/Syringe,
    # one-time-per-mount) second, so "Setup" is column-first only within
    # its own "Static configuration" section. The original ordering intent
    # this test protects -- Reference move happens before Syringe
    # selection/loading, not mixed into Flow Control -- still holds and is
    # checked below.
    window = make_window(monkeypatch, tmp_path)
    pump_tab = None
    for index in range(window.tabs.count()):
        if window.tabs.tabText(index) == "Pump&Valve":
            pump_tab = window.tabs.widget(index)
            break
    assert pump_tab is not None

    groups = {g.title(): g for g in pump_tab.findChildren(QGroupBox)}
    assert "Setup" in groups
    setup_labels = {lbl.text() for lbl in groups["Setup"].findChildren(QLabel)}
    assert "Reference move" in setup_labels

    assert "Flow Control" in groups
    flow_control_labels = {lbl.text() for lbl in groups["Flow Control"].findChildren(QLabel)}
    assert "Reference move" not in flow_control_labels

    assert "Syringe" in groups
    all_groups_in_order = [g for g in pump_tab.findChildren(QGroupBox)]
    assert all_groups_in_order.index(groups["Setup"]) < all_groups_in_order.index(groups["Syringe"])


def test_refill_and_empty_pass_the_fill_flow_rate_field_value_through(monkeypatch, tmp_path):
    # Regression test (2026-08-03): the "Refill/Empty Flow Rate" field lets
    # an operator set the actual target instead of a buried constant --
    # confirms _refill()/_empty() read this field's current value and pass
    # it through to Application.refill()/empty(), rather than calling them
    # with no argument (which would silently fall back to
    # QmixPumpBackend's own default instead of what's shown on screen).
    window = make_window(monkeypatch, tmp_path)
    captured = []
    monkeypatch.setattr(qt_ui.Application, "refill", lambda self, flow_rate=None, timeout_s=60.0: captured.append(("refill", flow_rate)) or True)
    monkeypatch.setattr(qt_ui.Application, "empty", lambda self, flow_rate=None, timeout_s=60.0: captured.append(("empty", flow_rate)) or True)

    window.fill_flow_rate.setValue(9500.0)
    assert window._refill() == "RefillComplete"
    assert window._empty() == "EmptyComplete"

    assert ("refill", 9500.0) in captured
    assert ("empty", 9500.0) in captured


def test_init_tab_hardware_group_uses_clean_mx_valve_label(monkeypatch, tmp_path):
    # "MX Valve 2" was a stray LabVIEW front-panel disambiguation-suffix
    # artifact, the same bug class as the already-cleaned "SeriesPath 2" /
    # "ExposureTime(ms) 2" / "Flush Settings 2" -- there is only one Valve in
    # this codebase (self.valve_enabled/self.valve_resource are both
    # singular, never indexed), so the "2" did not distinguish anything.
    window = make_window(monkeypatch, tmp_path)
    init_tab = None
    for index in range(window.tabs.count()):
        if window.tabs.tabText(index) == "Initialization":
            init_tab = window.tabs.widget(index)
            break
    assert init_tab is not None
    label_texts = {lbl.text() for lbl in init_tab.findChildren(QLabel)}
    assert "MX Valve" in label_texts
    assert "MX Valve 2" not in label_texts


def test_experiment_tab_regroups_global_exposure_and_dynamic_camera_start(monkeypatch, tmp_path):
    # GlobalExposure and Dynamic Camera Start Time no longer float in
    # isolated grid cells -- confirm they're now inside the group boxes they
    # logically belong to (the "Experiment" numbers group they modify, and
    # the "Camera Start Array(s)" group they control), not merely present
    # somewhere on the tab.
    window = make_window(monkeypatch, tmp_path)
    experiment_tab = None
    for index in range(window.tabs.count()):
        if window.tabs.tabText(index) == "Experiment":
            experiment_tab = window.tabs.widget(index)
            break
    assert experiment_tab is not None

    groups = {gb.title(): gb for gb in experiment_tab.findChildren(QGroupBox)}
    assert window.global_exposure in groups["Experiment"].findChildren(QCheckBox)
    # v3 design-idea adoption, Proposal 4 (2026-08-06): title gained a
    # DIO1-clarifying suffix.
    assert window.dynamic_camera_start in groups["Camera Start Array(s) (per-repeat DIO1 delays)"].findChildren(
        QCheckBox
    )


def test_wfg_tab_and_experiment_tab_carry_live_use_labels(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)

    wfg_tab = None
    for index in range(window.tabs.count()):
        if window.tabs.tabText(index) == "WFG":
            wfg_tab = window.tabs.widget(index)
            break
    assert wfg_tab is not None
    wfg_label_texts = {lbl.text() for lbl in wfg_tab.findChildren(QLabel)}
    wfg_checkbox_texts = {box.text() for box in wfg_tab.findChildren(QCheckBox)}

    # Ch1 (task's "CH0") Frequency/Amplitude/secRun/secWait: overridden during a run.
    # Shortened from "(overridden during experiment run)"/"(not used by automated
    # experiment runs)" to "(overridden)"/"(unused)" -- same distinction (an active
    # Experiment-tab analog exists vs. none exists at all), far less per-row width.
    assert "Frequency (kHz) Carrier (overridden)" in wfg_label_texts
    assert "Amplitude (V) (overridden)" in wfg_label_texts
    assert "Run duration (s)   [0 = continuous] (overridden)" in wfg_label_texts
    assert "secWait (overridden)" in wfg_label_texts
    # Extended, verified-accurate labeling: Enable/Trigger source are also
    # overridden (not "active", per the trace in _wfg_channel_group()).
    assert "Enable (overridden)" in wfg_checkbox_texts
    assert "Trigger source (overridden)" in wfg_label_texts
    # FM Mod is genuinely never read by an automated run at all.
    assert "Frequency (kHz) (unused)" in wfg_label_texts

    for index in range(window.tabs.count()):
        if window.tabs.tabText(index) == "Experiment":
            window.tabs.setCurrentIndex(index)
            break
    QApplication.processEvents()
    exp_tab = window.tabs.currentWidget()
    exp_label_texts = {lbl.text() for lbl in exp_tab.findChildren(QLabel)}

    assert "CH0 Frequency (kHz) (overrides WFG tab)" in exp_label_texts
    assert "CH0 Amplitude (V) (overrides WFG tab)" in exp_label_texts
    assert "CH0 Start (s) (overrides WFG tab)" in exp_label_texts
    assert "CH1 Run (s)(0=Cont) (overrides WFG tab)" in exp_label_texts


def test_wfg_synchronize_state_is_visibly_disabled_stub(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)

    assert not window.wfg_sync.isEnabled()
    assert "Not implemented" in window.wfg_sync.toolTip()


def test_camera_sequence_group_flags_live_automated_use_and_dead_capture_mode(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)

    group = build_with_retry(window._sequence_group)
    # The grid now lives on its own content widget inside a QScrollArea
    # (Session 38 fix for the wrapped sequence_note label needing more row
    # height than the group's own minimumSizeHint could accommodate
    # unwrapped) -- navigate through that to reach the real QGridLayout.
    scroll = group.findChildren(QScrollArea)[0]
    grid = scroll.widget().layout()
    note_item = grid.itemAtPosition(1, 2)
    assert note_item is not None
    note_text = note_item.widget().text()
    assert "applied to every automated Experiment run" in note_text
    assert "DO affect experiment runs" in note_text

    # capture_mode/sequence_exposure_ms no longer live inside this group's
    # own settings form -- v3 design-idea adoption, Proposal 6 (2026-08-06)
    # isolated them into their own "Retained (not used by runtime)" group,
    # checked separately below, so they're no longer individually
    # "(unused)"-suffixed inline among this group's genuinely live,
    # automated-run-affecting fields.
    settings_layout = grid.itemAtPosition(4, 2).layout()
    remaining_labels = [
        settings_layout.itemAt(row, settings_layout.ItemRole.LabelRole).widget().text()
        for row in range(settings_layout.rowCount())
        if settings_layout.itemAt(row, settings_layout.ItemRole.LabelRole) is not None
    ]
    assert "Capture mode" not in "".join(remaining_labels)
    assert "ExposureTime(ms)" not in "".join(remaining_labels)

    assert not window.capture_mode.isEnabled()
    assert "Not wired to a real backend" in window.capture_mode.toolTip()

    # sequence_exposure_ms: confirmed dead since Session 11 (never included in
    # _camera_sequence_settings(), so never read by configure_sequence()), and
    # its "ExposureTime(ms)" label collided with the real, live self.exposure_ms
    # field in the ROI group on the same tab -- same bug class as capture_mode,
    # fixed the same way in this pass.
    assert not window.sequence_exposure_ms.isEnabled()
    assert "Not wired to a real backend" in window.sequence_exposure_ms.toolTip()
    assert "exposure_ms" not in window._camera_sequence_settings()

    retained_group = build_with_retry(window._camera_retained_fields_group)
    assert retained_group.title() == "Retained (not used by runtime)"
    assert window.capture_mode.parent() is not None
    assert window.sequence_exposure_ms.parent() is not None
    retained_labels = {label.text() for label in retained_group.findChildren(QLabel)}
    assert "Capture mode" in retained_labels
    assert "ExposureTime(ms)" in retained_labels


def test_experiment_tab_elapsed_time_and_time_left_are_live_displays(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)

    assert window.elapsed_time_label.text() == "00:00:00"
    assert window.time_left_label.text() == "00:00:00"
    assert window.elapsed_time_label.isEnabled()
    assert window.time_left_label.isEnabled()
    assert "wall-clock" in window.elapsed_time_label.toolTip()
    assert "Estimate only" in window.time_left_label.toolTip()


def test_programmed_repeat_duration_uses_concurrent_ad2_window_then_flush():
    from thermo_acoustic.ad2 import (
        CarrierSettings,
        DoConfig,
        DoSingleChannelConfig,
        TriggerSettings,
    )
    from thermo_acoustic.workflows import Experiment2, FlushSettings

    experiment = Experiment2(
        wfg_config=WfgConfig(
            running=True,
            channels=[
                WfgChannelConfig(
                    channel_index=0,
                    carrier=CarrierSettings(enable=True),
                    trigger=TriggerSettings(sec_run=10.0, sec_wait=2.0),
                ),
                WfgChannelConfig(
                    channel_index=1,
                    carrier=CarrierSettings(enable=True),
                    trigger=TriggerSettings(sec_run=20.0, sec_wait=1.0),
                ),
            ],
        ),
        do_clock_settings=DoConfig(
            running=True,
            channels=[
                DoSingleChannelConfig(
                    channel_index=1,
                    enable=True,
                    trigger=TriggerSettings(sec_run=3.0, sec_wait=5.0),
                )
            ],
        ),
        flush_enabled=True,
        flush_settings=FlushSettings(
            flush_flowrate=200.0,
            flush_volume_ml=0.05,
            wait_after_flush_s=3.0,
        ),
    )

    # AD2 contributes max(12, 21, 8) = 21s because outputs overlap.
    # Flush contributes 15s pump travel + 3s programmed post-flush wait.
    assert qt_ui._programmed_repeat_duration_s(experiment) == pytest.approx(39.0)


def test_series_timing_uses_controlled_clock_and_refines_remaining_estimate(monkeypatch, tmp_path):
    clock = {"now": 100.0}
    monkeypatch.setattr(qt_ui.time, "monotonic", lambda: clock["now"])
    window = make_window(monkeypatch, tmp_path)
    try:
        window._handle_worker_progress(
            "series_timing_started",
            {"started_at": 100.0, "programmed_remaining_s": 30.0},
        )
        window._handle_worker_progress("experiment_series_active", True)

        clock["now"] = 112.4
        window._refresh_series_timing()
        assert window.elapsed_time_label.text() == "00:00:12"
        assert window.time_left_label.text() == "00:00:18"

        # One 12-second repeat completed, so the measured estimate becomes
        # 12 seconds/repeat * 2 remaining repeats, anchored at completion.
        window._handle_worker_progress(
            "series_repeat_completed",
            {
                "completed_at": 112.0,
                "elapsed_s": 12.0,
                "completed_repeats": 1,
                "total_repeats": 3,
            },
        )
        clock["now"] = 115.2
        window._refresh_series_timing()
        assert window.elapsed_time_label.text() == "00:00:15"
        assert window.time_left_label.text() == "00:00:21"
    finally:
        window._handle_worker_progress("experiment_series_active", False)
        window.close()


def test_qt_ui_uses_passive_hardware_config_defaults(monkeypatch, tmp_path):
    defaults = default_hardware_config()

    window = make_window(monkeypatch, tmp_path)

    assert window.z_backend.currentText() == ZStageBackend.DISABLED.value
    assert window.prior_resource.text() == defaults.z_stage.prior_resource
    assert window.thorlabs_apt_serial.text() == defaults.z_stage.thorlabs_apt_serial
    assert window.thorlabs_apt_backend.text() == defaults.z_stage.thorlabs_apt_backend
    assert window.thorlabs_apt_discovery_only.isChecked() is True
    assert window.cetoni_config_path.text() == str(defaults.qmix.config_path)
    assert window.qmix_sdk_python_path.text() == str(defaults.qmix.sdk_python_path)
    assert window.qmix_qmixsdk_path.text() == str(defaults.qmix.qmixsdk_path)


def test_initialization_tab_path_fields_are_widened_to_fit_their_real_content(monkeypatch, tmp_path):
    # Pending feedback item 3: qt_ui_v2.py's InitializationDialog already
    # widens these same shared widget instances for itself
    # (_widen_for_content()) -- confirm v1's own Initialization tab (which
    # renders the same three fields in _instrument_group(), never opening
    # v2's dialog) gets that same treatment, not left at Qt's small default
    # sizeHint for a real, often-long Windows path.
    window = make_window(monkeypatch, tmp_path)
    try:
        for widget in (window.qmix_sdk_python_path, window.qmix_qmixsdk_path, window.cetoni_config_path):
            required_width = widget.fontMetrics().horizontalAdvance(widget.text()) + 40
            assert widget.minimumWidth() >= required_width
    finally:
        window.close()


def test_category_6_grounded_tooltips_added_this_session(monkeypatch, tmp_path):
    # Category 6 (Session 39): fields found genuinely non-self-evident and
    # previously untooltipped, each grounded in a fact traced from real code
    # this session (not invented) -- see the Session 39 changelog entry for
    # the full trace of each.
    window = make_window(monkeypatch, tmp_path)

    # prior_resource: was "genuinely used" (Session 39) -- since retired
    # (pending feedback item 5, Part B1): the legacy PriorZMotor/COM7 path
    # it fed was replaced with a real connection to the Thorlabs piezo via
    # thorlabs_apt_serial, so prior_resource is now itself an unwired stub.
    assert "Not wired to a real backend" in window.prior_resource.toolTip()

    # flush_flowrate (manual tab): both the label and tooltip state the actual
    # Qmix flow unit rather than presenting a volume-only "uL" label.
    assert "uL/min" in window.flush_flowrate.toolTip()
    assert "Positive dispense flow rate" in window.flush_flowrate.toolTip()
    assert window.flush_flowrate.minimum() == 0.0
    assert "Positive dispense flow rate" in window.exp_flush_flowrate.toolTip()
    assert window.exp_flush_flowrate.minimum() == 0.0

    # conversion_method: grounded in ImagePreviewWindow's own three display
    # methods, traced directly this session.
    assert "linearly stretches" in window.conversion_method.toolTip()
    assert "90th-percentile" in window.conversion_method.toolTip()
    assert "right-bit-shifts" in window.conversion_method.toolTip()

    # sequence_frames: grounded in the confirmed manual-vs-automated
    # divergence (unlike its six siblings, this one is NOT carried into
    # automated runs).
    assert "NOT carried into automated Experiment runs" in window.sequence_frames.toolTip()

    # exp_sweep_time_ms / manual WFG tab's sweep_time_ms: grounded in
    # FmSweepSettings.fm_frequency_hz's real formula (ad2.py).
    assert "1000/this value" in window.exp_sweep_time_ms.toolTip()
    assert "1000/this value" in window.wfg_channels[0]["sweep_time_ms"].toolTip()

    flush_group = build_with_retry(window._flush_group)
    flush_form = flush_group.layout()
    flush_label_item = flush_form.itemAt(0, flush_form.ItemRole.LabelRole)
    assert flush_label_item.widget().text() == "Flush Flow Rate (uL/min)"

    experiment_flush_group = build_with_retry(window._experiment_flush_group)
    experiment_flush_form = experiment_flush_group.layout()
    experiment_labels = {
        item.widget().text()
        for row in range(experiment_flush_form.rowCount())
        if (item := experiment_flush_form.itemAt(row, experiment_flush_form.ItemRole.LabelRole)) is not None
    }
    assert "Flush Flow Rate (uL/min)" in experiment_labels


def test_qt_ui_settings_dict_includes_passive_hardware_fields(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)

    settings = window._settings_dict()

    assert settings["z_backend"] == ZStageBackend.DISABLED.value
    assert settings["prior_resource"] == "COM7"
    assert settings["thorlabs_apt_serial"] == "44533854"
    assert settings["thorlabs_apt_backend"] == "pylablib"
    assert settings["thorlabs_apt_discovery_only"] is True
    assert settings["qmix_sdk_python_path"].endswith(r"qmix_sdk_for_codex\python")
    assert settings["qmix_qmixsdk_path"] == r"C:\Users\Lab user\AppData\Local\CETONI_SDK"
    assert "Cetoni_1pump_config_FM" in settings["cetoni_config_path"]


def test_qt_ui_load_settings_is_backward_compatible(monkeypatch, tmp_path):
    old_settings = {
        "z_enabled": False,
        "prior_resource": "COM7",
        "valve_resource": "COM6",
        "cetoni_config_path": r"C:\Users\Public\Documents\QmixElements\Projects",
    }

    window = make_window(monkeypatch, tmp_path, old_settings)

    assert window.z_backend.currentText() == ZStageBackend.DISABLED.value
    assert window.thorlabs_apt_serial.text() == "44533854"
    assert window.thorlabs_apt_backend.text() == "pylablib"
    assert window.thorlabs_apt_discovery_only.isChecked() is True
    assert window.qmix_sdk_python_path.text().endswith(r"qmix_sdk_for_codex\python")
    assert window.qmix_qmixsdk_path.text() == r"C:\Users\Lab user\AppData\Local\CETONI_SDK"
    assert window.cetoni_config_path.text() == old_settings["cetoni_config_path"]


def test_qt_ui_load_settings_auto_converts_legacy_hz_scale_frequencies(monkeypatch, tmp_path):
    # Files saved before the WFG/Experiment carrier frequency fields switched
    # to kHz have no "schema_version" key and store raw Hz values (e.g. a
    # 1.975 MHz carrier saved as 1975000.0). Loading such a file into the
    # now-kHz-labeled widgets must scale the value down, not misinterpret it.
    legacy_settings = {
        "wfg": [
            {"idx": 0, "frequency": 1975000.0, "amplitude": 1.0, "offset": 0.0, "symmetry": 50.0, "phase": 0.0, "function": "Sine", "enable": True},
        ],
        "experiment": {
            "ch1_frequency": 1975000.0,
            "ch2_frequency": 500000.0,
        },
    }

    window = make_window(monkeypatch, tmp_path, legacy_settings)

    assert window.wfg_channels[0]["frequency"].value() == pytest.approx(1975.0)
    assert window.exp_ch1_freq.value() == pytest.approx(1975.0)
    assert window.exp_ch2_freq.value() == pytest.approx(500.0)
    assert "auto-converted" in window.status.latest_text()

    # Once resaved, the file carries schema_version 2 and must not be
    # converted again on a subsequent load (that would silently divide a
    # correct kHz value by 1000 a second time).
    window._save_settings()
    resaved = json.loads(qt_ui.SETTINGS_PATH.read_text(encoding="utf-8"))
    assert resaved["schema_version"] == 2
    assert resaved["wfg"][0]["frequency"] == pytest.approx(1975.0)

    reloaded_window = build_with_retry(qt_ui.MainWindow)
    assert reloaded_window.wfg_channels[0]["frequency"].value() == pytest.approx(1975.0)
    assert reloaded_window.exp_ch1_freq.value() == pytest.approx(1975.0)
    assert "auto-converted" not in reloaded_window.status.latest_text()


def test_qt_ui_save_and_restore_passive_hardware_fields(monkeypatch, tmp_path):
    first_window = make_window(monkeypatch, tmp_path)
    first_window.z_backend.setCurrentText(ZStageBackend.THORLABS_APT.value)
    first_window.thorlabs_apt_serial.setText("44533854")
    first_window.thorlabs_apt_backend.setText("pylablib")
    first_window.thorlabs_apt_discovery_only.setChecked(False)
    first_window.qmix_sdk_python_path.setText(r"C:\sdk\python")
    first_window.qmix_qmixsdk_path.setText(r"C:\sdk\dll")
    first_window.cetoni_config_path.setText(r"C:\configs\one-pump")
    first_window.tec_enabled.setChecked(True)
    first_window.sim_tec.setChecked(False)
    first_window.tec_port.setText("COM9")

    first_window._save_settings()
    saved = json.loads(qt_ui.SETTINGS_PATH.read_text(encoding="utf-8"))

    assert saved["z_backend"] == ZStageBackend.THORLABS_APT.value
    assert saved["thorlabs_apt_discovery_only"] is False
    assert saved["qmix_sdk_python_path"] == r"C:\sdk\python"
    assert saved["tec_enabled"] is True
    assert saved["sim_tec"] is False
    assert saved["tec_port"] == "COM9"

    second_window = build_with_retry(qt_ui.MainWindow)

    assert second_window.z_backend.currentText() == ZStageBackend.THORLABS_APT.value
    assert second_window.thorlabs_apt_serial.text() == "44533854"
    assert second_window.thorlabs_apt_backend.text() == "pylablib"
    assert second_window.thorlabs_apt_discovery_only.isChecked() is False
    assert second_window.qmix_sdk_python_path.text() == r"C:\sdk\python"
    assert second_window.qmix_qmixsdk_path.text() == r"C:\sdk\dll"
    assert second_window.cetoni_config_path.text() == r"C:\configs\one-pump"
    assert second_window.tec_enabled.isChecked() is True
    assert second_window.sim_tec.isChecked() is False
    assert second_window.tec_port.text() == "COM9"


def test_qt_ui_save_and_restore_tec_temperature_scan_settings(monkeypatch, tmp_path):
    first_window = make_window(monkeypatch, tmp_path)
    first_window.exp_tec_scan_enable.setChecked(True)
    first_window.exp_tec_points.setText("20.0, 25.5")
    first_window.exp_tec_tolerance_c.setValue(0.25)
    first_window.exp_tec_min_settle_s.setValue(3.0)
    first_window.exp_tec_max_wait_s.setValue(120.0)
    first_window.exp_tec_poll_interval_s.setValue(0.5)
    first_window.exp_tec_post_stable_hold_s.setValue(12.5)

    first_window._save_settings()
    saved = json.loads(qt_ui.SETTINGS_PATH.read_text(encoding="utf-8"))

    assert saved["experiment"]["tec_scan_enable"] is True
    assert saved["experiment"]["tec_points"] == "20.0, 25.5"
    assert saved["experiment"]["tec_tolerance_c"] == pytest.approx(0.25)
    assert saved["experiment"]["tec_post_stable_hold_s"] == pytest.approx(12.5)

    second_window = build_with_retry(qt_ui.MainWindow)

    assert second_window.exp_tec_scan_enable.isChecked() is True
    assert second_window.exp_tec_points.text() == "20.0, 25.5"
    assert second_window.exp_tec_tolerance_c.value() == pytest.approx(0.25)
    assert second_window.exp_tec_min_settle_s.value() == pytest.approx(3.0)
    assert second_window.exp_tec_max_wait_s.value() == pytest.approx(120.0)
    assert second_window.exp_tec_poll_interval_s.value() == pytest.approx(0.5)
    assert second_window.exp_tec_post_stable_hold_s.value() == pytest.approx(12.5)
    # Default: locked, matching "default to locked for any config that
    # doesn't specify it" -- this save didn't touch the lock toggle at all.
    assert second_window.exp_tec_lock_channels.isChecked() is True


def test_qt_ui_save_and_restore_pump_valve_manual_tab_fields(monkeypatch, tmp_path):
    # Save/Load Settings gap-closure, batch 1 (2026-08-04): the Pump&Valve
    # manual tab was previously entirely unpersisted, including
    # fill_flow_rate specifically -- confirmed via a dedicated audit to be
    # the subject of an earlier instruction that was never actually
    # implemented, not a lost completion. Own "pump_valve" sub-dict,
    # mirroring "mso"'s own existing sub-dict.
    first_window = make_window(monkeypatch, tmp_path)
    first_window.syringe.setCurrentText("BD 5ml")
    first_window.custom_syringe_volume_ml.setValue(2.5)
    first_window.custom_syringe_inner_diameter_mm.setValue(9.0)
    first_window.custom_syringe_stroke_mm.setValue(40.0)
    first_window.flow_rate.setValue(-1234.5)
    first_window.fill_flow_rate.setValue(8000.0)
    first_window.level_ml.setValue(0.75)
    first_window.flush_flowrate.setValue(300.0)
    first_window.flush_volume.setValue(0.05)
    first_window.wait_after_flush.setValue(2.5)
    first_window.flush_count.setValue(3)

    first_window._save_settings()
    saved = json.loads(qt_ui.SETTINGS_PATH.read_text(encoding="utf-8"))

    assert saved["pump_valve"]["syringe"] == "BD 5ml"
    assert saved["pump_valve"]["custom_syringe_volume_ml"] == pytest.approx(2.5)
    assert saved["pump_valve"]["custom_syringe_inner_diameter_mm"] == pytest.approx(9.0)
    assert saved["pump_valve"]["custom_syringe_stroke_mm"] == pytest.approx(40.0)
    assert saved["pump_valve"]["flow_rate"] == pytest.approx(-1234.5)
    assert saved["pump_valve"]["fill_flow_rate"] == pytest.approx(8000.0)
    assert saved["pump_valve"]["level_ml"] == pytest.approx(0.75)
    assert saved["pump_valve"]["flush_flowrate"] == pytest.approx(300.0)
    assert saved["pump_valve"]["flush_volume"] == pytest.approx(0.05)
    assert saved["pump_valve"]["wait_after_flush"] == pytest.approx(2.5)
    assert saved["pump_valve"]["flush_count"] == 3

    second_window = build_with_retry(qt_ui.MainWindow)

    assert second_window.syringe.currentText() == "BD 5ml"
    assert second_window.custom_syringe_volume_ml.value() == pytest.approx(2.5)
    assert second_window.custom_syringe_inner_diameter_mm.value() == pytest.approx(9.0)
    assert second_window.custom_syringe_stroke_mm.value() == pytest.approx(40.0)
    assert second_window.flow_rate.value() == pytest.approx(-1234.5)
    assert second_window.fill_flow_rate.value() == pytest.approx(8000.0)
    assert second_window.level_ml.value() == pytest.approx(0.75)
    assert second_window.flush_flowrate.value() == pytest.approx(300.0)
    assert second_window.flush_volume.value() == pytest.approx(0.05)
    assert second_window.wait_after_flush.value() == pytest.approx(2.5)
    assert second_window.flush_count.value() == 3


def test_qt_ui_load_settings_without_pump_valve_key_loads_without_error(monkeypatch, tmp_path):
    # A settings.json saved before this batch has no "pump_valve" key at
    # all -- the tolerant `if key in data` pattern (same one every other
    # field in this dict already uses) means these fields simply stay at
    # their _build_state() construction defaults rather than raising.
    legacy_settings = {
        "schema_version": 2,
        "experiment": {"repeats": 3, "frames": 5},
    }
    window = make_window(monkeypatch, tmp_path, legacy_settings)

    assert window.exp_repeats.value() == 3
    assert window.syringe.currentText() == "BD 1ml"
    assert window.custom_syringe_volume_ml.value() == pytest.approx(1.0)
    assert window.custom_syringe_inner_diameter_mm.value() == pytest.approx(4.78)
    assert window.custom_syringe_stroke_mm.value() == pytest.approx(55.75)
    assert window.flow_rate.value() == pytest.approx(-5000.0)
    assert window.fill_flow_rate.value() == pytest.approx(12000.0)
    assert window.level_ml.value() == pytest.approx(0.0)
    assert window.flush_flowrate.value() == pytest.approx(0.0)
    assert window.flush_volume.value() == pytest.approx(0.0)
    assert window.wait_after_flush.value() == pytest.approx(0.0)
    assert window.flush_count.value() == 1


def test_qt_ui_pump_valve_manual_flush_fields_round_trip_independently_of_experiment_flush_fields(monkeypatch, tmp_path):
    # Confirms the manual Pump&Valve tab's own flush_flowrate/flush_volume/
    # wait_after_flush/flush_count (self.flush_flowrate etc., under the new
    # "pump_valve" key) are genuinely distinct from the Experiment tab's own
    # flush_flowrate/flush_volume/wait_after_flush (self.exp_flush_flowrate
    # etc., under the existing "experiment" key) -- different values on
    # each, saved and reloaded, must not collide or overwrite one another.
    first_window = make_window(monkeypatch, tmp_path)
    first_window.flush_flowrate.setValue(111.0)
    first_window.flush_volume.setValue(0.11)
    first_window.wait_after_flush.setValue(1.1)
    first_window.flush_count.setValue(11)
    first_window.exp_flush_flowrate.setValue(222.0)
    first_window.exp_flush_volume.setValue(0.22)
    first_window.exp_wait_after_flush.setValue(2.2)

    first_window._save_settings()
    saved = json.loads(qt_ui.SETTINGS_PATH.read_text(encoding="utf-8"))

    assert saved["pump_valve"]["flush_flowrate"] == pytest.approx(111.0)
    assert saved["pump_valve"]["flush_volume"] == pytest.approx(0.11)
    assert saved["pump_valve"]["wait_after_flush"] == pytest.approx(1.1)
    assert saved["pump_valve"]["flush_count"] == 11
    assert saved["experiment"]["flush_flowrate"] == pytest.approx(222.0)
    assert saved["experiment"]["flush_volume"] == pytest.approx(0.22)
    assert saved["experiment"]["wait_after_flush"] == pytest.approx(2.2)

    second_window = build_with_retry(qt_ui.MainWindow)

    assert second_window.flush_flowrate.value() == pytest.approx(111.0)
    assert second_window.flush_volume.value() == pytest.approx(0.11)
    assert second_window.wait_after_flush.value() == pytest.approx(1.1)
    assert second_window.flush_count.value() == 11
    assert second_window.exp_flush_flowrate.value() == pytest.approx(222.0)
    assert second_window.exp_flush_volume.value() == pytest.approx(0.22)
    assert second_window.exp_wait_after_flush.value() == pytest.approx(2.2)


def test_qt_ui_save_and_restore_camera_manual_tab_fields(monkeypatch, tmp_path):
    # Save/Load Settings gap-closure, batch 2 (2026-08-04): the Camera
    # manual tab was previously entirely unpersisted, same disposition as
    # batch 1's Pump&Valve tab. Own "camera" sub-dict, same shape.
    # conversion_min/conversion_max deliberately excluded -- confirmed
    # always setReadOnly(True), only ever written from a live capture's
    # computed display range, not a user-set config value.
    first_window = make_window(monkeypatch, tmp_path)
    first_window.roi_h_offset.setValue(100)
    first_window.roi_v_offset.setValue(200)
    first_window.roi_h_size.setValue(1024)
    first_window.roi_v_size.setValue(512)
    first_window.center_roi.setChecked(False)
    first_window.exposure_ms.setValue(55.5)
    first_window.conversion_method.setCurrentText("Downshift")
    first_window.conversion_shifts.setValue(3)
    first_window.sequence_mode.setCurrentText("Burst")
    first_window.sequence_source.setCurrentText("Software")
    first_window.sequence_interval.setValue(0.25)
    first_window.sequence_burst.setValue(5)
    first_window.sequence_frames.setValue(10)
    first_window.capture_mode.setCurrentText("Sequence")
    first_window.dcam_source.setCurrentText("External")
    first_window.external_polarity.setCurrentText("Positive")
    first_window.external_delay.setValue(0.002)
    first_window.sequence_exposure_ms.setValue(33.3)

    first_window._save_settings()
    saved = json.loads(qt_ui.SETTINGS_PATH.read_text(encoding="utf-8"))

    assert saved["camera"]["roi_h_offset"] == 100
    assert saved["camera"]["roi_v_offset"] == 200
    assert saved["camera"]["roi_h_size"] == 1024
    assert saved["camera"]["roi_v_size"] == 512
    assert saved["camera"]["center_roi"] is False
    assert saved["camera"]["exposure_ms"] == pytest.approx(55.5)
    assert saved["camera"]["conversion_method"] == "Downshift"
    assert saved["camera"]["conversion_shifts"] == 3
    assert saved["camera"]["sequence_mode"] == "Burst"
    assert saved["camera"]["sequence_source"] == "Software"
    assert saved["camera"]["sequence_interval"] == pytest.approx(0.25)
    assert saved["camera"]["sequence_burst"] == 5
    assert saved["camera"]["sequence_frames"] == 10
    assert saved["camera"]["capture_mode"] == "Sequence"
    assert saved["camera"]["dcam_source"] == "External"
    assert saved["camera"]["external_polarity"] == "Positive"
    assert saved["camera"]["external_delay"] == pytest.approx(0.002)
    assert saved["camera"]["sequence_exposure_ms"] == pytest.approx(33.3)
    # conversion_min/conversion_max/image_continuous deliberately excluded,
    # not missed -- see the matching comments in _settings_dict() and
    # _load_settings() (qt_ui.py). conversion_min/max are always-read-only,
    # live-capture-derived display values, never a user-set config value.
    # image_continuous is a live action trigger (opens a real camera
    # preview window, starts a repeating capture timer) rather than
    # passive configuration -- restoring it via _load_settings() would
    # auto-start continuous capture the instant settings load, before
    # hardware is even connected.
    assert "conversion_min" not in saved["camera"]
    assert "conversion_max" not in saved["camera"]
    assert "image_continuous" not in saved["camera"]

    second_window = build_with_retry(qt_ui.MainWindow)

    assert second_window.roi_h_offset.value() == 100
    assert second_window.roi_v_offset.value() == 200
    assert second_window.roi_h_size.value() == 1024
    assert second_window.roi_v_size.value() == 512
    assert second_window.center_roi.isChecked() is False
    assert second_window.exposure_ms.value() == pytest.approx(55.5)
    assert second_window.conversion_method.currentText() == "Downshift"
    assert second_window.conversion_shifts.value() == 3
    assert second_window.sequence_mode.currentText() == "Burst"
    assert second_window.sequence_source.currentText() == "Software"
    assert second_window.sequence_interval.value() == pytest.approx(0.25)
    assert second_window.sequence_burst.value() == 5
    assert second_window.sequence_frames.value() == 10
    assert second_window.capture_mode.currentText() == "Sequence"
    assert second_window.dcam_source.currentText() == "External"
    assert second_window.external_polarity.currentText() == "Positive"
    assert second_window.external_delay.value() == pytest.approx(0.002)
    assert second_window.sequence_exposure_ms.value() == pytest.approx(33.3)

    # Explicit cleanup: this test constructs two full MainWindow instances
    # (one more than most round-trip tests in this file already do) and
    # touches an unusually large number of widgets, including several tied
    # together by connected signals (conversion_method -> conversion_shifts
    # via _update_conversion_controls()) -- closing both here avoids adding
    # to the cumulative live-widget count that the documented PySide6/
    # shiboken offscreen flakiness (known_open_items.md) is triggered by.
    first_window.close()
    second_window.close()


def test_qt_ui_load_settings_without_camera_key_loads_without_error(monkeypatch, tmp_path):
    # A settings.json saved before this batch has no "camera" key at all --
    # the tolerant `if key in data` pattern means these fields simply stay
    # at their _build_state() construction defaults rather than raising.
    legacy_settings = {
        "schema_version": 2,
        "experiment": {"repeats": 3, "frames": 5},
    }
    window = make_window(monkeypatch, tmp_path, legacy_settings)

    assert window.exp_repeats.value() == 3
    assert window.roi_h_offset.value() == 0
    assert window.roi_v_offset.value() == 792
    assert window.roi_h_size.value() == 2304
    assert window.roi_v_size.value() == 740
    assert window.center_roi.isChecked() is True
    assert window.exposure_ms.value() == pytest.approx(40.0)
    assert window.conversion_method.currentText() == "Full Dynamic"
    assert window.conversion_shifts.value() == 0
    assert window.sequence_mode.currentText() == "Continuous"
    assert window.sequence_source.currentText() == "External"
    assert window.sequence_interval.value() == pytest.approx(1.0)
    assert window.sequence_burst.value() == 1
    assert window.sequence_frames.value() == 0
    assert window.capture_mode.currentText() == "Snap"
    assert window.dcam_source.currentText() == "Internal"
    assert window.external_polarity.currentText() == "Negative"
    assert window.external_delay.value() == pytest.approx(0.0)
    assert window.sequence_exposure_ms.value() == pytest.approx(0.0)
    window.close()


def test_qt_ui_camera_manual_exposure_field_round_trips_independently_of_experiment_exposure_field(monkeypatch, tmp_path):
    # Confirms the manual Camera tab's own exposure_ms (self.exposure_ms,
    # ROI group, under the new "camera" key) is genuinely distinct from the
    # Experiment tab's own exposure_ms (self.exp_exposure_ms, under the
    # existing "experiment" key) -- different values on each, saved and
    # reloaded, must not collide or overwrite one another. Same independence
    # check as batch 1's manual-vs-Experiment flush-field test.
    first_window = make_window(monkeypatch, tmp_path)
    first_window.exposure_ms.setValue(77.0)
    first_window.exp_exposure_ms.setValue(88.0)

    first_window._save_settings()
    saved = json.loads(qt_ui.SETTINGS_PATH.read_text(encoding="utf-8"))

    assert saved["camera"]["exposure_ms"] == pytest.approx(77.0)
    assert saved["experiment"]["exposure_ms"] == pytest.approx(88.0)

    second_window = build_with_retry(qt_ui.MainWindow)

    assert second_window.exposure_ms.value() == pytest.approx(77.0)
    assert second_window.exp_exposure_ms.value() == pytest.approx(88.0)
    first_window.close()
    second_window.close()


def test_qt_ui_save_and_restore_zscan_tab_fields(monkeypatch, tmp_path):
    # Save/Load Settings gap-closure, batch 3 (2026-08-05): the Z-Scan tab
    # was previously entirely unpersisted, same disposition as batches 1-2.
    # Own "zscan" sub-dict, same shape. Confirmed (grep) none of the 5
    # fields fire a connected signal on setValue/setChecked/setText, so
    # none is a live action trigger the way image_continuous (batch 2) was.
    # zscan_z_start_um/zscan_z_end_um start disabled with range [0.0, 0.0]
    # until a real "Query Piezo Range" call widens it -- this test uses
    # values that exceed that default range specifically to prove the
    # load-time range-widening fix actually works, not just a value that
    # happens to already fit in [0.0, 0.0].
    first_window = make_window(monkeypatch, tmp_path)
    first_window.zscan_output_dir.setText(str(tmp_path / "zscan_out"))
    first_window.zscan_z_start_um.setMaximum(500.0)  # simulates a real query having happened
    first_window.zscan_z_end_um.setMaximum(500.0)
    first_window.zscan_z_start_um.setValue(12.5)
    first_window.zscan_z_end_um.setValue(487.5)
    first_window.zscan_step_size_um.setValue(2.5)
    first_window.zscan_exposure_ms.setValue(66.0)

    first_window._save_settings()
    saved = json.loads(qt_ui.SETTINGS_PATH.read_text(encoding="utf-8"))

    assert saved["zscan"]["zscan_output_dir"] == str(tmp_path / "zscan_out")
    assert saved["zscan"]["zscan_z_start_um"] == pytest.approx(12.5)
    assert saved["zscan"]["zscan_z_end_um"] == pytest.approx(487.5)
    assert saved["zscan"]["zscan_step_size_um"] == pytest.approx(2.5)
    assert saved["zscan"]["zscan_exposure_ms"] == pytest.approx(66.0)

    second_window = build_with_retry(qt_ui.MainWindow)

    # second_window is freshly constructed -- its zscan_z_start_um/
    # zscan_z_end_um start disabled at the real default range [0.0, 0.0],
    # never queried. Confirms the load-time range-widening fix: these
    # loaded values (12.5/487.5) must survive, not get silently clamped to
    # 0.0, while the field stays disabled exactly as it does by default
    # (the widening only touches the numeric range, not the safety gate
    # that only a real "Query Piezo Range" call is meant to lift).
    assert second_window.zscan_z_start_um.isEnabled() is False
    assert second_window.zscan_z_end_um.isEnabled() is False
    assert second_window.zscan_output_dir.text() == str(tmp_path / "zscan_out")
    assert second_window.zscan_z_start_um.value() == pytest.approx(12.5)
    assert second_window.zscan_z_end_um.value() == pytest.approx(487.5)
    assert second_window.zscan_step_size_um.value() == pytest.approx(2.5)
    assert second_window.zscan_exposure_ms.value() == pytest.approx(66.0)
    first_window.close()
    second_window.close()


def test_qt_ui_load_settings_without_zscan_key_loads_without_error(monkeypatch, tmp_path):
    # A settings.json saved before this batch has no "zscan" key at all --
    # the tolerant `if key in data` pattern means these fields simply stay
    # at their _build_state() construction defaults rather than raising.
    legacy_settings = {
        "schema_version": 2,
        "experiment": {"repeats": 3, "frames": 5},
    }
    window = make_window(monkeypatch, tmp_path, legacy_settings)

    assert window.exp_repeats.value() == 3
    assert window.zscan_output_dir.text() == r"C:\test\zscan_calibration"
    assert window.zscan_z_start_um.value() == pytest.approx(0.0)
    assert window.zscan_z_start_um.isEnabled() is False
    assert window.zscan_z_end_um.value() == pytest.approx(0.0)
    assert window.zscan_z_end_um.isEnabled() is False
    assert window.zscan_step_size_um.value() == pytest.approx(1.0)
    assert window.zscan_exposure_ms.value() == pytest.approx(40.0)
    window.close()


def test_qt_ui_save_and_restore_wfg_running_and_fm_sweep_and_camera_acquisition_fields(monkeypatch, tmp_path):
    # Save/Load Settings gap-closure, batch 4 (2026-08-05, final batch): WFG
    # tab's master running toggle, Experiment tab's FM Sweep group, and
    # Experiment tab's camera-acquisition fields -- all previously
    # unpersisted. wfg_running is a new plain top-level key (not nested
    # under "wfg" -- that name is already the per-channel list); FM
    # Sweep/camera-acquisition are purely additive keys under the existing
    # "experiment" dict, same convention as Frequency Scanning/TEC. Grepped
    # all fields for connected signals first (batch 2's lesson) and for
    # disabled/range-gated state (batch 3's lesson) -- neither hazard found
    # for any field in this batch.
    first_window = make_window(monkeypatch, tmp_path)
    first_window.wfg_running.setChecked(False)
    first_window.exp_sweep_enable.setChecked(True)
    first_window.exp_sweep_start_khz.setValue(1000.0)
    first_window.exp_sweep_stop_khz.setValue(1100.0)
    # Reading center/width back after setting start/stop deliberately --
    # _connect_sweep_dual_mode_refresh() recomputes them live, so their
    # saved values should already be internally consistent with start/stop.
    expected_center = first_window.exp_sweep_center_khz.value()
    expected_width = first_window.exp_sweep_width_khz.value()
    first_window.exp_sweep_time_ms.setValue(2.5)
    first_window.exp_sweep_type.setCurrentText("RampUp")
    first_window.exp_camera_fps.setValue(25.0)
    first_window.exp_camera_start.setValue(0.5)
    first_window.dynamic_camera_start.setChecked(True)
    first_window.camera_start_array[0].setValue(1.1)
    first_window.camera_start_array[9].setValue(9.9)
    first_window.global_exposure.setChecked(True)

    first_window._save_settings()
    saved = json.loads(qt_ui.SETTINGS_PATH.read_text(encoding="utf-8"))

    assert saved["wfg_running"] is False
    assert saved["experiment"]["sweep_enable"] is True
    assert saved["experiment"]["sweep_start_khz"] == pytest.approx(1000.0)
    assert saved["experiment"]["sweep_stop_khz"] == pytest.approx(1100.0)
    assert saved["experiment"]["sweep_center_khz"] == pytest.approx(expected_center)
    assert saved["experiment"]["sweep_width_khz"] == pytest.approx(expected_width)
    assert saved["experiment"]["sweep_time_ms"] == pytest.approx(2.5)
    assert saved["experiment"]["sweep_type"] == "RampUp"
    assert saved["experiment"]["camera_fps"] == pytest.approx(25.0)
    assert saved["experiment"]["camera_start"] == pytest.approx(0.5)
    assert saved["experiment"]["dynamic_camera_start"] is True
    assert saved["experiment"]["camera_start_array"][0] == pytest.approx(1.1)
    assert saved["experiment"]["camera_start_array"][9] == pytest.approx(9.9)
    assert len(saved["experiment"]["camera_start_array"]) == 10
    assert saved["experiment"]["global_exposure"] is True

    second_window = build_with_retry(qt_ui.MainWindow)

    assert second_window.wfg_running.isChecked() is False
    assert second_window.exp_sweep_enable.isChecked() is True
    assert second_window.exp_sweep_start_khz.value() == pytest.approx(1000.0)
    assert second_window.exp_sweep_stop_khz.value() == pytest.approx(1100.0)
    assert second_window.exp_sweep_center_khz.value() == pytest.approx(expected_center)
    assert second_window.exp_sweep_width_khz.value() == pytest.approx(expected_width)
    assert second_window.exp_sweep_time_ms.value() == pytest.approx(2.5)
    assert second_window.exp_sweep_type.currentText() == "RampUp"
    assert second_window.exp_camera_fps.value() == pytest.approx(25.0)
    assert second_window.exp_camera_start.value() == pytest.approx(0.5)
    assert second_window.dynamic_camera_start.isChecked() is True
    assert second_window.camera_start_array[0].value() == pytest.approx(1.1)
    assert second_window.camera_start_array[9].value() == pytest.approx(9.9)
    assert second_window.global_exposure.isChecked() is True
    first_window.close()
    second_window.close()


def test_qt_ui_load_settings_without_wfg_running_or_fm_sweep_or_camera_acquisition_keys_loads_without_error(monkeypatch, tmp_path):
    # A settings.json saved before this batch has none of these keys at
    # all -- the tolerant `if key in data` pattern means these fields
    # simply stay at their _build_state() construction defaults.
    legacy_settings = {
        "schema_version": 2,
        "experiment": {"repeats": 3, "frames": 5},
    }
    window = make_window(monkeypatch, tmp_path, legacy_settings)

    assert window.exp_repeats.value() == 3
    assert window.wfg_running.isChecked() is True
    assert window.exp_sweep_enable.isChecked() is False
    assert window.exp_sweep_start_khz.value() == pytest.approx(1909.0)
    assert window.exp_sweep_stop_khz.value() == pytest.approx(1959.0)
    assert window.exp_sweep_center_khz.value() == pytest.approx(1934.0)
    assert window.exp_sweep_width_khz.value() == pytest.approx(50.0)
    assert window.exp_sweep_time_ms.value() == pytest.approx(1.0)
    assert window.exp_sweep_type.currentText() == "Symmetric"
    assert window.exp_camera_fps.value() == pytest.approx(0.0)
    assert window.exp_camera_start.value() == pytest.approx(0.0)
    assert window.dynamic_camera_start.isChecked() is False
    assert all(widget.value() == pytest.approx(0.0) for widget in window.camera_start_array)
    assert window.global_exposure.isChecked() is False
    window.close()


def test_qt_ui_tec_post_stable_hold_defaults_to_zero_and_feeds_temperature_series(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        assert window.exp_tec_post_stable_hold_s.value() == pytest.approx(0.0)
        assert window._temperature_series().post_stable_hold_s == pytest.approx(0.0)

        window.exp_tec_post_stable_hold_s.setValue(7.25)

        assert window._temperature_series().post_stable_hold_s == pytest.approx(7.25)
    finally:
        window.close()


def test_qt_ui_tec_lock_mirrors_ch1_into_ch2_while_locked(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        assert window.exp_tec_lock_channels.isChecked() is True
        assert window.exp_tec_points_ch2.isEnabled() is False

        window.exp_tec_points.setText("20.0, 25.5")

        assert window.exp_tec_points_ch2.text() == "20.0, 25.5"
        series = window._temperature_series()
        assert series.unlocked is False
        assert series.temperature_points_ch2_c is None
    finally:
        window.close()


def test_qt_ui_tec_unlock_starts_ch2_from_the_previously_shared_value(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        window.exp_tec_points.setText("20.0, 25.5")
        assert window.exp_tec_points_ch2.text() == "20.0, 25.5"

        window.exp_tec_lock_channels.setChecked(False)

        # Unlocking does NOT reset CH2 to a default -- it keeps the value it
        # was already mirroring, now independently editable.
        assert window.exp_tec_points_ch2.text() == "20.0, 25.5"
        assert window.exp_tec_points_ch2.isEnabled() is True

        window.exp_tec_points_ch2.setText("18.0, 22.0")
        window.exp_tec_points.setText("21.0, 26.5")  # CH1 edits no longer mirror while unlocked
        assert window.exp_tec_points_ch2.text() == "18.0, 22.0"

        series = window._temperature_series()
        assert series.unlocked is True
        assert series.temperature_points_c == [21.0, 26.5]
        assert series.temperature_points_ch2_c == [18.0, 22.0]
    finally:
        window.close()


def test_qt_ui_tec_relock_copies_ch1_into_ch2(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        window.exp_tec_points.setText("20.0, 25.5")
        window.exp_tec_lock_channels.setChecked(False)
        window.exp_tec_points_ch2.setText("18.0, 22.0")  # diverge

        window.exp_tec_lock_channels.setChecked(True)

        # Relocking: channel 1's current value becomes the new shared
        # value -- the less surprising choice for a reversible text-field
        # toggle (no confirmation dialog, no silent data loss since CH1's
        # value is what's kept and stays visible).
        assert window.exp_tec_points_ch2.text() == "20.0, 25.5"
        assert window.exp_tec_points_ch2.isEnabled() is False
        series = window._temperature_series()
        assert series.unlocked is False
    finally:
        window.close()


def test_qt_ui_save_and_restore_tec_unlocked_dual_channel_settings(monkeypatch, tmp_path):
    first_window = make_window(monkeypatch, tmp_path)
    first_window.exp_tec_points.setText("20.0, 25.5")
    first_window.exp_tec_lock_channels.setChecked(False)
    first_window.exp_tec_points_ch2.setText("18.0, 22.0")

    first_window._save_settings()
    saved = json.loads(qt_ui.SETTINGS_PATH.read_text(encoding="utf-8"))

    assert saved["experiment"]["tec_lock_channels"] is False
    assert saved["experiment"]["tec_points_ch2"] == "18.0, 22.0"

    second_window = build_with_retry(qt_ui.MainWindow)

    assert second_window.exp_tec_lock_channels.isChecked() is False
    assert second_window.exp_tec_points_ch2.isEnabled() is True
    assert second_window.exp_tec_points_ch2.text() == "18.0, 22.0"
    series = second_window._temperature_series()
    assert series.unlocked is True
    assert series.temperature_points_ch2_c == [18.0, 22.0]


def test_qt_ui_builds_one_experiment_group_per_tec_temperature(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        window.series_path.setText(str(tmp_path / "series"))
        window.exp_camera_fps.setValue(100.0)
        window.exp_repeats.setValue(2)
        window.exp_frames.setValue(3)
        window.exp_tec_points.setText("20.0;25.5")
        window.exp_tec_min_settle_s.setValue(0.0)

        temperature_series, groups, total_frames, config = window._build_temperature_experiment_groups(
            Path(window.series_path.text())
        )

        assert temperature_series.temperature_points_c == [20.0, 25.5]
        assert len(groups) == 2
        assert [group.see_elements_left() for group in groups] == [2, 2]
        assert total_frames == 12
        assert groups[0].series_path == tmp_path / "series" / "temperature_001_20p000C"
        assert groups[1].series_path == tmp_path / "series" / "temperature_002_25p500C"
        assert [experiment.tec_target_c for experiment in groups[0].experiments] == [20.0, 20.0]
        assert [experiment.tec_target_c for experiment in groups[1].experiments] == [25.5, 25.5]
        assert config is not None
    finally:
        window.close()


def test_qt_ui_save_and_restore_frequency_scanning_settings(monkeypatch, tmp_path):
    # Session 44: Frequency Scanning's fields (previously a deliberate,
    # flagged scope decision to leave unpersisted -- Session 34) are now
    # saved/loaded like every other Experiment-tab field. "freq_scan_enable"
    # is included alongside the task's named four fields (Start/Stop/Number
    # of Frequencies/Step Size) so the feature doesn't silently reset to off
    # while its values survive a restart.
    # Step Size left at 0 ("not used") deliberately: exp_freq_scan_step_khz
    # > 0 makes _connect_frequency_scan_count_display_refresh() (Session 35/
    # 39) auto-recompute "Number of Frequencies" from Start/Stop/Step live,
    # which would silently overwrite the explicit count set below and turn
    # this into a test of that already-covered precedence logic instead of
    # persistence. Save/restore of a nonzero Step Size itself is still
    # covered by the second window's assertions below.
    first_window = make_window(monkeypatch, tmp_path)
    first_window.exp_freq_scan_enable.setChecked(True)
    first_window.exp_freq_scan_start_khz.setValue(1234.5)
    first_window.exp_freq_scan_stop_khz.setValue(2345.6)
    first_window.exp_freq_scan_count.setValue(7)

    first_window._save_settings()
    saved = json.loads(qt_ui.SETTINGS_PATH.read_text(encoding="utf-8"))

    assert saved["experiment"]["freq_scan_enable"] is True
    assert saved["experiment"]["freq_scan_start_khz"] == pytest.approx(1234.5)
    assert saved["experiment"]["freq_scan_stop_khz"] == pytest.approx(2345.6)
    assert saved["experiment"]["freq_scan_count"] == 7
    assert saved["experiment"]["freq_scan_step_khz"] == pytest.approx(0.0)

    second_window = build_with_retry(qt_ui.MainWindow)

    assert second_window.exp_freq_scan_enable.isChecked() is True
    assert second_window.exp_freq_scan_start_khz.value() == pytest.approx(1234.5)
    assert second_window.exp_freq_scan_stop_khz.value() == pytest.approx(2345.6)
    assert second_window.exp_freq_scan_count.value() == 7
    assert second_window.exp_freq_scan_step_khz.value() == pytest.approx(0.0)


def test_qt_ui_load_settings_without_frequency_scanning_keys_loads_without_error(monkeypatch, tmp_path):
    # Confirms a settings.json saved before Session 44 (no freq_scan_* keys
    # at all) still loads cleanly -- the tolerant `if key in data` pattern
    # (same one every other field in this dict already uses) means the
    # fields simply stay at their _build_state() construction defaults
    # rather than raising or silently corrupting.
    legacy_settings = {
        "schema_version": 2,
        "experiment": {"repeats": 3, "frames": 5},
    }
    window = make_window(monkeypatch, tmp_path, legacy_settings)

    assert window.exp_repeats.value() == 3
    assert window.exp_frames.value() == 5
    assert window.exp_freq_scan_enable.isChecked() is False
    assert window.exp_freq_scan_start_khz.value() == pytest.approx(1900.0)
    assert window.exp_freq_scan_stop_khz.value() == pytest.approx(1975.0)
    assert window.exp_freq_scan_count.value() == 2
    assert window.exp_freq_scan_step_khz.value() == pytest.approx(0.0)


def test_qt_ui_experiment_flush_is_disabled_by_default_and_explicitly_enabled(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    window.series_path.setText(str(tmp_path / "series"))
    window.exp_camera_fps.setValue(100.0)
    window.exp_frames.setValue(20)

    series, _total_frames, _config = window._build_experiment_series()

    assert series.experiments is not None
    assert [experiment.flush_enabled for experiment in series.experiments] == [False]
    assert [experiment.trigger_global_exposure for experiment in series.experiments] == [False]
    assert series.experiments[0].do_clock_settings.running is True
    assert series.experiments[0].do_clock_settings.channels[0].channel_index == 1
    assert series.experiments[0].do_clock_settings.channels[0].clock_frequency_hz == 100.0
    assert series.experiments[0].do_clock_settings.channels[0].trigger.sec_run == 0.2

    window.exp_flush_enabled.setChecked(True)
    window.global_exposure.setChecked(True)
    series, _total_frames, _config = window._build_experiment_series()

    assert series.experiments is not None
    assert [experiment.flush_enabled for experiment in series.experiments] == [True]
    assert [experiment.trigger_global_exposure for experiment in series.experiments] == [True]


def test_experiment_sequence_settings_set_explicit_deterministic_trigger_source(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    window.series_path.setText(str(tmp_path / "series"))
    window.exp_camera_fps.setValue(100.0)
    window.exp_frames.setValue(5)

    series, _total_frames, _config = window._build_experiment_series()

    assert series.experiments[0].sequence_settings["trigger_source"] == "Internal"


def test_experiment_sequence_settings_carry_manual_tab_sequence_cluster_fields(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    window.series_path.setText(str(tmp_path / "series"))
    window.exp_camera_fps.setValue(100.0)
    window.exp_frames.setValue(5)

    window.sequence_mode.setCurrentText("Burst")
    window.sequence_source.setCurrentText("Software")
    window.sequence_interval.setValue(0.25)
    window.sequence_burst.setValue(7)
    window.external_polarity.setCurrentText("Positive")
    window.external_delay.setValue(0.5)

    series, _total_frames, _config = window._build_experiment_series()
    settings = series.experiments[0].sequence_settings

    assert settings["masterpulse_mode"] == "Burst"
    assert settings["masterpulse_source"] == "Software"
    assert settings["masterpulse_interval_s"] == 0.25
    assert settings["masterpulse_burst_times"] == 7
    assert settings["trigger_polarity"] == "Positive"
    assert settings["trigger_delay_s"] == 0.5
    # frames/camera_start_s/trigger_source remain experiment-sourced, not the manual tab's.
    assert settings["frames"] == 5
    assert settings["trigger_source"] == "Internal"


def test_experiment_wfg_config_carries_symmetry_phase_and_repeat_trigger(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    window.series_path.setText(str(tmp_path / "series"))
    window.exp_camera_fps.setValue(100.0)
    window.exp_frames.setValue(5)

    window.exp_ch1_symmetry.setValue(65.0)
    window.exp_ch1_phase.setValue(12.5)
    window.exp_ch1_repeat_trigger.setChecked(True)

    series, _total_frames, _config = window._build_experiment_series()
    ch0 = series.experiments[0].wfg_config.channels[0]

    assert ch0.carrier.symmetry_percent == 65.0
    assert ch0.carrier.phase_deg == 12.5
    assert ch0.trigger.repeat_trigger is True


def test_frequency_fields_display_khz_but_round_trip_to_correct_hz_hardware_value(monkeypatch, tmp_path):
    # Unification to kHz (matching the SeriesPath naming convention, e.g.
    # "1975kHz\..."): confirms entering "1900.000" kHz produces the exact
    # same 1_900_000.0 Hz hardware-facing value the old "1900000.000" Hz
    # field used to, on both the manual WFG tab and the Experiment tab.
    window = make_window(monkeypatch, tmp_path)

    # Manual WFG tab: Carrier "Frequency (kHz) Carrier" and FM Mod "Frequency (kHz)".
    manual_state = window.wfg_channels[0]
    manual_state["frequency"].setValue(1900.0)
    manual_state["fm_frequency"].setValue(2.5)
    manual_config = window._channel_config(manual_state)
    assert manual_config.carrier.frequency_hz == 1_900_000.0
    assert manual_config.fm_mod.frequency_hz == 2500.0

    # Manual WFG tab: Sweep "Start/Stop Frequency (kHz)" (Session 16 chose Center+Width
    # in MHz; corrected to kHz then, and to Start+Stop here -- matching Digilent's own
    # WaveForms sweep tool convention). Start=1909.0/Stop=1959.0 reproduces the exact
    # same Martens et al. reference case as before: (1909+1959)/2=1934, |1959-1909|=50.
    manual_state["sweep_start_khz"].setValue(1909.0)
    manual_state["sweep_stop_khz"].setValue(1959.0)
    sweep = window._fm_sweep_settings_from_state(manual_state)
    assert sweep.center_hz == 1_934_000.0
    assert sweep.width_hz == 50_000.0

    # Experiment tab: Carrier "Frequency (kHz)" and Sweep "Start/Stop Frequency (kHz)".
    window.exp_ch1_freq.setValue(1900.0)
    experiment_config = window._experiment_channel_config(0, window.exp_ad2_channels[0])
    assert experiment_config.carrier.frequency_hz == 1_900_000.0

    window.exp_sweep_start_khz.setValue(1909.0)
    window.exp_sweep_stop_khz.setValue(1959.0)
    experiment_sweep = window._experiment_fm_sweep_settings()
    assert experiment_sweep.center_hz == 1_934_000.0
    assert experiment_sweep.width_hz == 50_000.0


def test_fm_sweep_toggle_off_preserves_existing_experiment_behavior(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    window.series_path.setText(str(tmp_path / "series"))
    window.exp_camera_fps.setValue(100.0)
    window.exp_frames.setValue(5)
    # exp_sweep_enable is off by default -- do not touch it.

    series, _total_frames, _config = window._build_experiment_series()
    experiment = series.experiments[0]
    ch0 = experiment.wfg_config.channels[0]

    assert ch0.fm_mod.enable is False
    assert ch0.fm_mod.frequency_hz == 1000.0
    assert ch0.fm_mod.amplitude_v == 1.0
    assert ch0.fm_mod.function == qt_ui.WaveformFunction.SINE
    assert experiment.fm_sweep is None


def test_fm_sweep_toggle_on_carries_settings_into_experiment_wfg_config(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    window.series_path.setText(str(tmp_path / "series"))
    window.exp_camera_fps.setValue(100.0)
    window.exp_frames.setValue(5)

    window.exp_sweep_enable.setChecked(True)
    # Start=1909.0/Stop=1959.0 kHz reproduces the same Martens et al. reference
    # case as the original Center=1934/Width=50 kHz: (1909+1959)/2=1934, |1959-1909|=50.
    window.exp_sweep_start_khz.setValue(1909.0)
    window.exp_sweep_stop_khz.setValue(1959.0)
    window.exp_sweep_time_ms.setValue(1.0)
    window.exp_sweep_type.setCurrentText("Symmetric")

    series, _total_frames, _config = window._build_experiment_series()
    experiment = series.experiments[0]
    ch0 = experiment.wfg_config.channels[0]

    assert ch0.carrier.frequency_hz == 1_934_000.0
    assert ch0.carrier.enable is True
    assert ch0.fm_mod.enable is True
    assert ch0.fm_mod.frequency_hz == 1000.0
    assert ch0.fm_mod.amplitude_v == pytest.approx(2.585, abs=1e-3)
    assert ch0.fm_mod.function == qt_ui.WaveformFunction.TRIANGLE

    assert experiment.fm_sweep is not None
    assert experiment.fm_sweep.center_hz == 1_934_000.0
    assert experiment.fm_sweep.width_hz == 50_000.0
    assert experiment.fm_sweep.sweep_time_ms == 1.0

    properties = experiment._settings_properties()
    assert properties["FMSweepEnabled"] is True
    assert properties["FMSweepCenterHz"] == 1_934_000.0
    assert properties["FMSweepWidthKHz"] == 50.0
    assert properties["FMSweepTimeMs"] == 1.0
    assert properties["FMSweepType"] == "Symmetric"


def test_fm_sweep_dual_mode_start_stop_and_center_width_stay_in_sync(monkeypatch, tmp_path):
    # Task 1 correction: Start/Stop and Center/Width are both live inputs for
    # the same value -- editing either pair updates the other, neither is
    # ever hidden or removed. Martens et al. reference case both directions:
    # Start=1909/Stop=1959 <-> Center=1934/Width=50.
    window = make_window(monkeypatch, tmp_path)

    # Manual WFG tab (Ch1 state).
    manual_state = window.wfg_channels[0]
    manual_state["sweep_start_khz"].setValue(1909.0)
    manual_state["sweep_stop_khz"].setValue(1959.0)
    assert manual_state["sweep_center_khz"].value() == pytest.approx(1934.0)
    assert manual_state["sweep_width_khz"].value() == pytest.approx(50.0)

    manual_state["sweep_center_khz"].setValue(2000.0)
    manual_state["sweep_width_khz"].setValue(100.0)
    assert manual_state["sweep_start_khz"].value() == pytest.approx(1950.0)
    assert manual_state["sweep_stop_khz"].value() == pytest.approx(2050.0)

    # Round-trip back to the reference case via Center/Width this time.
    manual_state["sweep_center_khz"].setValue(1934.0)
    manual_state["sweep_width_khz"].setValue(50.0)
    sweep = window._fm_sweep_settings_from_state(manual_state)
    assert sweep.center_hz == 1_934_000.0
    assert sweep.width_hz == 50_000.0

    # Experiment tab.
    window.exp_sweep_start_khz.setValue(1909.0)
    window.exp_sweep_stop_khz.setValue(1959.0)
    assert window.exp_sweep_center_khz.value() == pytest.approx(1934.0)
    assert window.exp_sweep_width_khz.value() == pytest.approx(50.0)

    window.exp_sweep_center_khz.setValue(1934.0)
    window.exp_sweep_width_khz.setValue(50.0)
    assert window.exp_sweep_start_khz.value() == pytest.approx(1909.0)
    assert window.exp_sweep_stop_khz.value() == pytest.approx(1959.0)
    experiment_sweep = window._experiment_fm_sweep_settings()
    assert experiment_sweep.center_hz == 1_934_000.0
    assert experiment_sweep.width_hz == 50_000.0


def test_frequency_scanning_off_keeps_wfg_config_identical_across_repeats(monkeypatch, tmp_path):
    # Regression guard for the restructure that made _build_experiment_series()
    # build a fresh WfgConfig per repeat (like _experiment_do_clock_config(repeat))
    # instead of once outside the loop: with Dynamic Frequency off, every
    # repeat's Ch1/Ch2 carrier values must still come out identical.
    window = make_window(monkeypatch, tmp_path)
    window.series_path.setText(str(tmp_path / "series"))
    window.exp_camera_fps.setValue(100.0)
    window.exp_frames.setValue(5)
    window.exp_repeats.setValue(3)
    window.exp_ch1_freq.setValue(1900.0)
    # exp_freq_scan_enable is off by default -- do not touch it.

    series, _total_frames, _config = window._build_experiment_series()

    frequencies = [experiment.wfg_config.channels[0].carrier.frequency_hz for experiment in series.experiments]
    assert frequencies == [1_900_000.0, 1_900_000.0, 1_900_000.0]
    ch2_frequencies = [experiment.wfg_config.channels[1].carrier.frequency_hz for experiment in series.experiments]
    assert len(set(ch2_frequencies)) == 1


def test_frequency_scanning_substitutes_ch1_only_per_repeat(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    window.series_path.setText(str(tmp_path / "series"))
    window.exp_camera_fps.setValue(100.0)
    window.exp_frames.setValue(5)
    window.exp_repeats.setValue(4)
    window.exp_ch2_freq.setValue(1.0)  # kHz -- Ch2 must stay at this value every repeat

    window.exp_freq_scan_enable.setChecked(True)
    window.exp_freq_scan_start_khz.setValue(1900.0)
    window.exp_freq_scan_stop_khz.setValue(1975.0)
    window.exp_freq_scan_count.setValue(4)

    series, _total_frames, _config = window._build_experiment_series()

    ch1_frequencies = [experiment.wfg_config.channels[0].carrier.frequency_hz for experiment in series.experiments]
    assert ch1_frequencies == pytest.approx([1_900_000.0, 1_925_000.0, 1_950_000.0, 1_975_000.0])

    ch2_frequencies = [experiment.wfg_config.channels[1].carrier.frequency_hz for experiment in series.experiments]
    assert ch2_frequencies == [1000.0, 1000.0, 1000.0, 1000.0]


def test_frequency_scanning_step_size_overrides_count_when_nonzero(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    window.series_path.setText(str(tmp_path / "series"))
    window.exp_camera_fps.setValue(100.0)
    window.exp_frames.setValue(5)
    window.exp_repeats.setValue(4)

    window.exp_freq_scan_enable.setChecked(True)
    window.exp_freq_scan_start_khz.setValue(1900.0)
    window.exp_freq_scan_stop_khz.setValue(1975.0)
    window.exp_freq_scan_count.setValue(10)  # deliberately wrong -- Step Size must win
    window.exp_freq_scan_step_khz.setValue(25.0)  # (1975-1900)/25 + 1 = 4 points

    series, _total_frames, _config = window._build_experiment_series()

    ch1_frequencies = [experiment.wfg_config.channels[0].carrier.frequency_hz for experiment in series.experiments]
    assert ch1_frequencies == pytest.approx([1_900_000.0, 1_925_000.0, 1_950_000.0, 1_975_000.0])


def test_frequency_scanning_repeats_mismatch_raises_before_starting(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    window.series_path.setText(str(tmp_path / "series"))
    window.exp_camera_fps.setValue(100.0)
    window.exp_frames.setValue(5)
    window.exp_repeats.setValue(3)

    window.exp_freq_scan_enable.setChecked(True)
    window.exp_freq_scan_start_khz.setValue(1900.0)
    window.exp_freq_scan_stop_khz.setValue(1975.0)
    window.exp_freq_scan_count.setValue(5)  # deliberately != Repeats (3)

    with pytest.raises(ValueError, match="Frequency Scanning"):
        window._build_experiment_series()
    assert not (tmp_path / "series").exists(), "nothing should be created before the mismatch is caught"


def test_frequency_scanning_repeats_mismatch_error_names_the_true_count_source(monkeypatch, tmp_path):
    # Category 5 (Session 39): the mismatch error used to always say "(Number
    # of Frequencies)" even when Step Size (not Number of Frequencies) was
    # the field actually driving the count -- misattributing the source an
    # operator would need to fix. Confirms both branches now name correctly.
    window = make_window(monkeypatch, tmp_path)
    window.series_path.setText(str(tmp_path / "series"))
    window.exp_camera_fps.setValue(100.0)
    window.exp_frames.setValue(5)
    window.exp_repeats.setValue(3)
    window.exp_freq_scan_enable.setChecked(True)
    window.exp_freq_scan_start_khz.setValue(1900.0)
    window.exp_freq_scan_stop_khz.setValue(1975.0)

    window.exp_freq_scan_count.setValue(5)  # step is 0 -- Number of Frequencies drives it
    with pytest.raises(ValueError, match=r"\(Number of Frequencies\)"):
        window._build_experiment_series()

    window.exp_freq_scan_step_khz.setValue(25.0)  # (1975-1900)/25 + 1 = 4 points, step now drives it
    with pytest.raises(ValueError, match=r"\(Step Size\)"):
        window._build_experiment_series()


def test_frequency_scanning_number_of_frequencies_display_tracks_step_size(monkeypatch, tmp_path):
    # Category 5 (Session 39): unlike FM Sweep's Start/Stop<->Center/Width
    # (Session 38), Step Size silently overrode the real point count without
    # ever updating what "Number of Frequencies" displayed -- an operator
    # reading only that field would see a stale, wrong number once Step Size
    # took over. Confirms the display now tracks the real computed count
    # whenever Step Size is active, and that editing Number of Frequencies
    # directly still works, unchanged, whenever Step Size is 0.
    window = make_window(monkeypatch, tmp_path)

    window.exp_freq_scan_start_khz.setValue(1900.0)
    window.exp_freq_scan_stop_khz.setValue(1975.0)
    window.exp_freq_scan_count.setValue(10)  # stale/wrong once Step Size is set below

    window.exp_freq_scan_step_khz.setValue(25.0)  # (1975-1900)/25 + 1 = 4 points
    assert window.exp_freq_scan_count.value() == 4

    window.exp_freq_scan_stop_khz.setValue(2000.0)  # (2000-1900)/25 + 1 = 5 points
    assert window.exp_freq_scan_count.value() == 5

    window.exp_freq_scan_step_khz.setValue(0.0)  # back to "not used" -- Number of Frequencies is authoritative again
    window.exp_freq_scan_count.setValue(7)
    assert window.exp_freq_scan_count.value() == 7


def test_frequency_scanning_swept_value_reaches_real_tdms_metadata(monkeypatch, tmp_path):
    # End-to-end per Task 1(f): confirms _build_experiment_series()'s per-repeat
    # WFG config actually reaches Experiment2/_write_tdms() with no changes
    # needed there -- each repeat's existing WFGFreqCh1 property should record
    # the swept frequency automatically once the config itself varies by repeat.
    from test_application import install_fake_nptdms

    writes = install_fake_nptdms(monkeypatch)

    window = make_window(monkeypatch, tmp_path)
    window.series_path.setText(str(tmp_path / "series"))
    window.exp_camera_fps.setValue(100.0)
    window.exp_frames.setValue(5)
    window.exp_repeats.setValue(3)

    window.exp_freq_scan_enable.setChecked(True)
    window.exp_freq_scan_start_khz.setValue(1900.0)
    window.exp_freq_scan_stop_khz.setValue(1975.0)
    window.exp_freq_scan_count.setValue(3)

    series, _total_frames, _config = window._build_experiment_series()
    expected_hz = [1_900_000.0, 1_937_500.0, 1_975_000.0]

    for experiment, expected in zip(series.experiments, expected_hz):
        experiment.create_folder_and_tdms()
        experiment.save_settings()
        tdms_path = experiment.experiment_folder / "data.tdms"
        objects = writes[str(tdms_path)]
        experiment_group = next(item for item in objects if getattr(item, "kind", "") == "group" and item.name == "Experiment")
        assert experiment_group.properties["WFGFreqCh1"] == pytest.approx(expected)


def test_qt_ui_experiment_do_clock_config_uses_camera_timing_fields(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    window.exp_camera_fps.setValue(200.0)
    window.exp_camera_start.setValue(0.125)
    window.exp_frames.setValue(50)

    do_config = window._experiment_do_clock_config(0)

    assert do_config.running is True
    assert len(do_config.channels) == 1
    channel = do_config.channels[0]
    assert channel.channel_index == 1
    assert channel.enable is True
    assert channel.clock_frequency_hz == 200.0
    assert channel.output_type == qt_ui.DigitalOutType.PULSE
    assert channel.idle_state == qt_ui.DigitalOutIdleState.INITIAL
    assert channel.counter_high_bits == 1
    assert channel.counter_low_bits == 1
    assert channel.counter_initial_bits == 0
    assert channel.start_high is True
    assert channel.trigger.sec_run == 0.25
    assert channel.trigger.sec_wait == 0.125
    assert channel.trigger.repeat_count == 0
    assert channel.trigger.repeat_trigger is False
    assert channel.trigger.source == qt_ui.TriggerSource.NONE

    window.dynamic_camera_start.setChecked(True)
    window.camera_start_array[2].setValue(0.333)

    dynamic_config = window._experiment_do_clock_config(2)

    assert dynamic_config.channels[0].trigger.sec_wait == 0.333


def test_qt_ui_experiment_do_clock_rejects_zero_camera_fps(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    window.exp_camera_fps.setValue(0.0)

    try:
        window._experiment_do_clock_config(0)
    except ValueError as exc:
        assert "Camera FPS must be greater than 0" in str(exc)
    else:
        raise AssertionError("Camera FPS=0 should be rejected before deriving DO clock")


def test_qt_ui_experiment_ad2_fields_seed_once_from_wfg(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    wfg_ch0 = window.wfg_channels[0]
    wfg_ch1 = window.wfg_channels[1]
    wfg_ch0["frequency"].setValue(1234.0)
    wfg_ch0["amplitude"].setValue(0.25)
    wfg_ch0["offset"].setValue(0.5)
    wfg_ch0["function"].setCurrentText(qt_ui.WaveformFunction.SQUARE.value)
    wfg_ch0["enable"].setChecked(True)
    wfg_ch0["sec_wait"].setValue(0.2)
    wfg_ch0["sec_run"].setValue(0.3)
    wfg_ch0["repeat"].setValue(4)
    wfg_ch0["trigger_source"].setCurrentText("trigsrcPC")
    wfg_ch1["frequency"].setValue(5678.0)
    wfg_ch1["amplitude"].setValue(0.75)
    wfg_ch1["enable"].setChecked(False)

    window._seed_experiment_ad2_from_wfg_once()

    assert window.exp_ch1_freq.value() == 1234.0
    assert window.exp_ch1_amp.value() == 0.25
    assert window.exp_ch1_offset.value() == 0.5
    assert window.exp_ch1_function.currentText() == qt_ui.WaveformFunction.SQUARE.value
    assert window.exp_ch1_enable.isChecked() is True
    assert window.exp_ch1_start.value() == 0.2
    assert window.exp_ch1_run.value() == 0.3
    assert window.exp_ch1_repeat.value() == 4
    assert window.exp_ch1_trigger_source.currentText() == "trigsrcPC"
    assert window.exp_ch2_freq.value() == 5678.0
    assert window.exp_ch2_amp.value() == 0.75
    assert window.exp_ch2_enable.isChecked() is False

    wfg_ch0["frequency"].setValue(9999.0)
    window._seed_experiment_ad2_from_wfg_once()

    assert window.exp_ch1_freq.value() == 1234.0


def test_qt_ui_experiment_wfg_config_uses_only_experiment_ad2_fields(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    window._experiment_ad2_seeded = True
    window.wfg_running.setChecked(False)
    window.wfg_sync.setCurrentText("Synchronized")
    for channel in window.wfg_channels:
        channel["frequency"].setValue(99_999.0)
        channel["amplitude"].setValue(9.9)
        channel["offset"].setValue(9.9)
        channel["function"].setCurrentText(qt_ui.WaveformFunction.DC.value)
        channel["enable"].setChecked(False)
        channel["sec_wait"].setValue(9.9)
        channel["sec_run"].setValue(9.9)
        channel["repeat"].setValue(99)
        channel["repeat_trigger"].setChecked(True)
        channel["trigger_source"].setCurrentText("trigsrcAnalogIn")
        channel["symmetry"].setValue(10.0)
        channel["phase"].setValue(90.0)
        channel["fm_enable"].setChecked(True)

    window.exp_ch1_enable.setChecked(True)
    window.exp_ch1_function.setCurrentText(qt_ui.WaveformFunction.SINE.value)
    window.exp_ch1_freq.setValue(1975.0)  # kHz -> 1_975_000.0 Hz
    window.exp_ch1_amp.setValue(2.0)
    window.exp_ch1_offset.setValue(0.0)
    window.exp_ch1_start.setValue(0.1)
    window.exp_ch1_run.setValue(0.5)
    window.exp_ch1_repeat.setValue(1)
    window.exp_ch1_trigger_source.setCurrentText("trigsrcPC")
    window.exp_ch2_enable.setChecked(False)
    window.exp_ch2_function.setCurrentText(qt_ui.WaveformFunction.SQUARE.value)
    window.exp_ch2_freq.setValue(1.0)  # kHz -> 1000.0 Hz
    window.exp_ch2_amp.setValue(0.1)
    window.exp_ch2_offset.setValue(0.2)
    window.exp_ch2_start.setValue(0.3)
    window.exp_ch2_run.setValue(0.4)
    window.exp_ch2_repeat.setValue(2)
    window.exp_ch2_trigger_source.setCurrentText("trigsrcNone")

    config = window._experiment_wfg_config()

    assert config.running is True
    assert config.synchronize_state == "Independent"
    assert config.channels[0].carrier.frequency_hz == 1_975_000.0
    assert config.channels[0].carrier.amplitude_v == 2.0
    assert config.channels[0].carrier.offset_v == 0.0
    assert config.channels[0].carrier.function == qt_ui.WaveformFunction.SINE
    assert config.channels[0].carrier.enable is True
    assert config.channels[0].carrier.symmetry_percent == 50.0
    assert config.channels[0].carrier.phase_deg == 0.0
    assert config.channels[0].trigger.sec_wait == 0.1
    assert config.channels[0].trigger.sec_run == 0.5
    assert config.channels[0].trigger.repeat_count == 1
    assert config.channels[0].trigger.repeat_trigger is False
    assert config.channels[0].trigger.source == "trigsrcPC"
    assert config.channels[0].fm_mod.enable is False
    assert config.channels[1].carrier.frequency_hz == 1000.0
    assert config.channels[1].carrier.amplitude_v == 0.1
    assert config.channels[1].carrier.offset_v == 0.2
    assert config.channels[1].carrier.function == qt_ui.WaveformFunction.SQUARE
    assert config.channels[1].carrier.enable is False
    assert config.channels[1].trigger.sec_wait == 0.3
    assert config.channels[1].trigger.sec_run == 0.4
    assert config.channels[1].trigger.repeat_count == 2
    assert config.channels[1].trigger.source == "trigsrcNone"
    assert config.channels[1].fm_mod.enable is False


def test_camera_sequence_settings_use_confirmed_dcam_options(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)

    assert combo_items(window.sequence_mode) == ["Continuous", "Start (single)", "Burst"]
    assert combo_items(window.sequence_source) == ["External", "Software"]
    assert combo_items(window.dcam_source) == ["Internal", "External", "Software", "MasterPulse"]
    assert combo_items(window.external_polarity) == ["Negative", "Positive"]
    assert window.sequence_burst.minimum() == 1
    assert window.sequence_burst.maximum() == 65535
    assert window.sequence_burst.value() == 1
    assert window.sequence_interval.minimum() == 0.000005
    assert window.sequence_interval.maximum() == 10.0
    assert window.external_delay.maximum() == 10.000002


def test_camera_sequence_settings_are_passed_to_manual_configure(monkeypatch, tmp_path):
    class FakeCamera:
        def __init__(self) -> None:
            self.calls = []

        def configure_exposure_time(self, exposure_ms: float) -> None:
            self.calls.append(("configure_exposure_time", exposure_ms))

        def configure_roi(self, roi: SubRegion) -> None:
            self.calls.append(("configure_roi", roi))

        def configure_sequence(self, settings: dict[str, object] | None) -> None:
            self.calls.append(("configure_sequence", settings))

        def center_roi(self) -> None:
            self.calls.append(("center_roi",))

    window = make_window(monkeypatch, tmp_path)
    fake_camera = FakeCamera()
    window.app.camera = fake_camera
    window.sequence_mode.setCurrentText("Burst")
    window.sequence_source.setCurrentText("Software")
    window.sequence_interval.setValue(0.125)
    window.sequence_burst.setValue(3)
    window.sequence_frames.setValue(7)
    window.dcam_source.setCurrentText("MasterPulse")
    window.external_polarity.setCurrentText("Positive")
    window.external_delay.setValue(0.25)

    settings = window._camera_sequence_settings()

    assert settings == {
        "masterpulse_mode": "Burst",
        "masterpulse_source": "Software",
        "masterpulse_interval_s": 0.125,
        "masterpulse_burst_times": 3,
        "frames": 7,
        "trigger_source": "MasterPulse",
        "trigger_polarity": "Positive",
        "trigger_delay_s": 0.25,
    }
    assert "exposure_ms" not in settings
    assert "capture_mode" not in settings

    roi = SubRegion(horizontal_offset=1, vertical_offset=2, horizontal_size=3, vertical_size=4)
    result = window._configure_camera(roi, 12.5, False, settings)

    assert result == "Camera configured"
    assert fake_camera.calls == [
        ("configure_exposure_time", 12.5),
        ("configure_roi", roi),
        ("configure_sequence", settings),
    ]


def test_camera_preview_converts_16_bit_frame_to_display_image():
    QApplication.instance() or QApplication([])
    preview = qt_ui.ImagePreviewWindow()
    try:
        frame = np.array([[0, 32768], [65535, 65535]], dtype=np.uint16)

        image = preview._convert_to_display_image(frame, method="Full Dynamic", shifts=0)

        assert image.width() == 2
        assert image.height() == 2
        assert image.format() == image.Format.Format_Grayscale8
        assert preview._last_display_range == (0.0, 65535.0)
    finally:
        preview.close()


def test_camera_preview_conversion_modes():
    QApplication.instance() or QApplication([])
    preview = qt_ui.ImagePreviewWindow()
    try:
        frame = np.arange(100, dtype=np.uint16).reshape(10, 10)

        preview._convert_to_display_image(frame, method="90% Dynamic", shifts=0)

        assert preview._last_display_range == (5.0, 94.0)

        downshift = preview._convert_to_display_image(
            np.array([[0, 256, 512]], dtype=np.uint16),
            method="Downshift",
            shifts=8,
        )

        assert preview._last_display_range is None
        assert downshift.pixelColor(0, 0).value() == 0
        assert downshift.pixelColor(1, 0).value() == 1
        assert downshift.pixelColor(2, 0).value() == 2
    finally:
        preview.close()


def test_camera_conversion_policy_controls(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)

    assert combo_items(window.conversion_method) == ["Full Dynamic", "90% Dynamic", "Downshift"]
    assert window.conversion_method.currentText() == "Full Dynamic"
    assert window.conversion_min.isReadOnly()
    assert window.conversion_max.isReadOnly()
    assert window.conversion_min.isEnabled()
    assert window.conversion_max.isEnabled()
    assert not window.conversion_shifts.isEnabled()

    window.conversion_method.setCurrentText("Downshift")

    assert not window.conversion_min.isEnabled()
    assert not window.conversion_max.isEnabled()
    assert window.conversion_shifts.isEnabled()


def test_camera_capture_updates_preview_and_last_frame(monkeypatch, tmp_path):
    class FakeCamera:
        def __init__(self, frame) -> None:
            self.frame = frame

        def capture_snapshot(self):
            return self.frame

    window = make_window(monkeypatch, tmp_path)
    window.image_continuous.setChecked(False)
    frame = np.array([[10, 20], [30, 40]], dtype=np.uint16)
    window.app.camera = FakeCamera(frame)
    progress_events = []

    result = window._capture_camera_image(lambda kind, value: progress_events.append((kind, value)))
    window._ensure_camera_preview()
    window._handle_worker_progress("camera_image", frame)

    assert result is frame
    assert window._last_camera_image_data is not None
    assert window._last_camera_image_data[0] is frame
    assert len(progress_events) == 1
    assert progress_events[0][0] == "camera_image"
    assert progress_events[0][1] is frame
    assert window._camera_preview is not None
    pixmap = window._camera_preview.image_label.pixmap()
    assert pixmap is not None
    assert not pixmap.isNull()
    assert window.conversion_min.value() == 10.0
    assert window.conversion_max.value() == 40.0
    window._camera_preview.close()


def test_camera_adjust_reprocesses_last_raw_frame_without_recapture(monkeypatch, tmp_path):
    class FakeCamera:
        def __init__(self, frame) -> None:
            self.frame = frame
            self.capture_count = 0

        def capture_snapshot(self):
            self.capture_count += 1
            return self.frame

    window = make_window(monkeypatch, tmp_path)
    frame = np.array([[0, 256, 512]], dtype=np.uint16)
    fake_camera = FakeCamera(frame)
    window.app.camera = fake_camera

    captured = window._capture_camera_image()
    window._ensure_camera_preview()
    window._handle_worker_progress("camera_image", captured)
    window.conversion_method.setCurrentText("Downshift")
    window.conversion_shifts.setValue(8)
    window._adjust_camera_preview()

    assert fake_camera.capture_count == 1
    assert window._last_camera_image_data is not None
    assert window._last_camera_image_data[0] is frame
    assert window._camera_preview is not None
    assert window._camera_preview._last_display_range is None
    window._camera_preview.close()


def test_camera_adjust_without_prior_capture_reports_status(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)

    window._adjust_camera_preview()

    assert window.status.latest_text() == "No image captured yet"
    assert window._camera_preview is None


def test_history_log_widget_accumulates_distinct_entries():
    # Direct widget-level check that history genuinely accumulates -- not
    # just that the widget exists, and not just that the latest entry is
    # correct (a single-value display would also pass that check).
    QApplication.instance() or QApplication([])
    log = qt_ui.HistoryLogWidget()
    assert log.count() == 0

    log.add_entry("first")
    log.add_entry("second")
    log.add_entry("third")

    assert log.count() == 3
    assert [log.item(i).data(Qt.ItemDataRole.UserRole) for i in range(3)] == ["first", "second", "third"]
    assert log.latest_text() == "third"
    # Earlier entries are still genuinely present, not overwritten.
    assert log.item(0).data(Qt.ItemDataRole.UserRole) == "first"
    # Each row is timestamped.
    assert log.item(0).text().startswith("[")
    assert "first" in log.item(0).text()


def test_history_log_widget_dedupes_consecutive_identical_entries():
    # Several real call sites (_handle_worker_finished()'s "OK" branch,
    # _safe_call()'s success path) re-report the same state on every
    # successful action, not just on a genuine change -- without this,
    # the log would fill with redundant identical rows on every click.
    QApplication.instance() or QApplication([])
    log = qt_ui.HistoryLogWidget()

    log.add_entry("Ready")
    log.add_entry("Ready")
    log.add_entry("Ready")
    assert log.count() == 1

    log.add_entry("Busy")
    assert log.count() == 2

    # Not deduped against an entry further back than the immediately
    # preceding one -- only true consecutive repeats collapse.
    log.add_entry("Ready")
    assert log.count() == 3


def test_history_log_widget_auto_scrolls_unless_user_scrolled_up():
    QApplication.instance() or QApplication([])
    log = qt_ui.HistoryLogWidget()
    log.resize(200, 60)  # small viewport so enough entries actually overflow it
    for i in range(30):
        log.add_entry(f"entry {i}")
    QApplication.processEvents()

    bar = log.verticalScrollBar()
    assert bar.maximum() > 0, "test requires the list to actually overflow its viewport"
    assert bar.value() == bar.maximum(), "should auto-scroll to the newest entry by default"

    # User scrolls up to review history.
    bar.setValue(0)
    QApplication.processEvents()
    log.add_entry("new entry while scrolled up")
    QApplication.processEvents()

    assert bar.value() == 0, "an incoming entry must not yank the view back down while scrolled up"

    # Scrolling back to the bottom resumes auto-scroll for the next entry.
    bar.setValue(bar.maximum())
    QApplication.processEvents()
    log.add_entry("final entry after returning to bottom")
    QApplication.processEvents()


def test_mso_stats_label_wraps_instead_of_growing_unbounded(monkeypatch, tmp_path):
    # Pending feedback item 3: _set_mso_stats() concatenates a per-channel
    # summary with " | ".join() -- length grows with the number of captured
    # channels, unbounded. Without wordWrap, an unwrapped QLabel inside a
    # QFormLayout grows to fit its full text instead of wrapping, the same
    # bug class already fixed elsewhere in this tab (sweep_header/hint).
    window = make_window(monkeypatch, tmp_path)
    try:
        assert window.mso_stats.wordWrap() is True

        window._set_mso_stats(
            {0: [0.1, 0.2, 0.3, 0.4], 1: [-0.1, -0.2, -0.3, -0.4]},
            sample_frequency_hz=1000.0,
            trigger_source="External",
        )
        assert "CH1" in window.mso_stats.text()
        assert "CH2" in window.mso_stats.text()
    finally:
        window.close()


def test_mso_text_preview_box_shows_close_to_a_full_two_channel_preview(monkeypatch, tmp_path):
    # Pending feedback item 3: up to 6 lines/channel x 2 channels = 12
    # preview lines from _set_mso_stats(); 90px only showed ~4-5 without
    # scrolling (still reachable via QPlainTextEdit's own scrollbar, but
    # cramped) -- bumped to 140, matching the height already established for
    # other small scrollable panels (Session 58's HistoryLogWidget group).
    window = make_window(monkeypatch, tmp_path)
    try:
        assert window.mso_text.maximumHeight() == 140

        window._set_mso_stats(
            {0: [0.1] * 6, 1: [0.2] * 6},
            sample_frequency_hz=1000.0,
            trigger_source="Internal",
        )
        preview_lines = window.mso_text.toPlainText().splitlines()
        assert len(preview_lines) == 12
    finally:
        window.close()


def test_history_log_widget_wraps_long_entries_instead_of_requiring_horizontal_scroll():
    # Pending feedback item 3: QListWidget items don't wrap by default, so a
    # long entry (e.g. a real exception message) was only reachable by
    # horizontally scrolling one row at a time inside this widget's fixed
    # panel width. wordWrap(True) keeps every entry fully visible instead.
    QApplication.instance() or QApplication([])
    log = qt_ui.HistoryLogWidget()
    assert log.wordWrap() is True


def test_status_history_accumulates_across_multiple_status_changes(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        starting_count = window.status.count()

        window._set_status("Initializing")
        window._set_status("Running Experiment Frame")
        window._set_status("ExperimentComplete")

        # All three genuinely distinct messages are present, in order --
        # not just the latest one, which a single-value QLineEdit would
        # have shown before this change (it would only ever show
        # "ExperimentComplete", with "Initializing" and "Running Experiment
        # Frame" silently gone).
        assert window.status.count() == starting_count + 3
        new_entries = [
            window.status.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(starting_count, window.status.count())
        ]
        assert new_entries == ["Initializing", "Running Experiment Frame", "ExperimentComplete"]
        assert window.status.latest_text() == "ExperimentComplete"
    finally:
        window.close()


def test_error_log_accumulates_across_multiple_events(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        starting_count = window.error_log.count()

        window._append_error_entry("OK", "0", "")
        window._append_error_entry("ERROR", "1", "first failure")
        window._append_error_entry("ERROR", "1", "second failure")

        # Three distinct bundled entries accumulate -- not the latest
        # overwriting the previous two, which the old three separate
        # single-value fields would have done.
        assert window.error_log.count() == starting_count + 3
        new_entries = [
            window.error_log.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(starting_count, window.error_log.count())
        ]
        assert new_entries == [
            "OK | code=0",
            "ERROR | code=1 | first failure",
            "ERROR | code=1 | second failure",
        ]
    finally:
        window.close()


def test_camera_preview_timer_starts_and_stops(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    window._busy_count = 1

    window.image_continuous.setChecked(True)

    assert window._camera_preview is not None
    assert window._camera_preview_timer.isActive()

    window.image_continuous.setChecked(False)

    assert not window._camera_preview_timer.isActive()
    window._camera_preview.close()


def test_single_image_capture_does_not_start_continuous_timer(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    run_actions = []

    def fake_run_action(action, status):
        run_actions.append((action, status))

    window._run_action = fake_run_action

    window._start_capture_camera_image()

    assert window._camera_preview is not None
    assert run_actions and run_actions[0][1] == "Capturing image"
    assert not window._camera_preview_timer.isActive()
    window._camera_preview.close()


def test_closing_camera_preview_stops_continuous_and_late_callback_does_not_reopen(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    window._busy_count = 1
    frame = np.array([[1, 2], [3, 4]], dtype=np.uint16)

    window.image_continuous.setChecked(True)

    assert window._camera_preview is not None
    assert window._camera_preview_active is True
    assert window._camera_preview_timer.isActive()

    window._camera_preview.close()

    assert window._camera_preview is None
    assert window._camera_preview_active is False
    assert not window._camera_preview_timer.isActive()
    assert window.image_continuous.isChecked() is False

    window._handle_worker_progress("camera_image", frame)
    window._handle_worker_progress("camera_capture_failed", "Capture failed")

    assert window._camera_preview is None
    assert not window._camera_preview_timer.isActive()


def test_abort_does_not_touch_hardware_even_while_another_action_is_blocked(monkeypatch, tmp_path):
    # Safety-behavior change (2026-08-04): Abort used to concurrently force
    # pump.stop()/camera.stop_capture()/ad2.wfg_start_stop_all_ch(False) on
    # its own QThread regardless of what the running experiment was doing
    # (the removed _abort_hardware(), previously exercised by this test's
    # own predecessor). Abort now only ever sets the stop flag -- it must
    # never call any hardware primitive directly, even while another
    # action is genuinely blocked/in-flight.
    window = make_window(monkeypatch, tmp_path)
    blocked_started = threading.Event()
    release_blocked = threading.Event()
    hardware_calls: list[str] = []

    class RecordingPump:
        def stop(self):
            hardware_calls.append("pump_stop")

        def cleanup(self):
            pass

    class RecordingCamera:
        def stop_capture(self):
            hardware_calls.append("camera_stop_capture")

        def cleanup(self):
            pass

    class RecordingAd2:
        def wfg_start_stop_all_ch(self, running):
            hardware_calls.append("ad2_stop")

        def cleanup(self):
            pass

    def blocked_action(progress):
        _ = progress
        blocked_started.set()
        release_blocked.wait(2.0)
        return "Blocked action released"

    try:
        window.app.pump = RecordingPump()
        window.app.camera = RecordingCamera()
        window.app.ad2 = RecordingAd2()

        window._run_action(blocked_action, "Blocking action")
        assert blocked_started.wait(1.0)
        assert window._busy_count == 1

        window._abort()

        assert window.app.stop_fired is True
        assert hardware_calls == [], f"Abort must never call hardware primitives directly, called: {hardware_calls}"

        release_blocked.set()
        assert process_events_until(lambda: window._busy_count == 0 and not window._threads, 2.0)
        # Still nothing called after the blocked action finished naturally --
        # Abort itself never touches hardware, only the stop flag does.
        assert hardware_calls == []
    finally:
        release_blocked.set()
        process_events_until(lambda: not window._threads, 2.0)
        window._cleanup_complete_for_close = True
        window.close()


def test_abort_sets_stop_flag_synchronously_without_a_background_thread(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        assert window.app.stop_fired is False
        assert not window._threads

        window._abort()

        # Synchronous: no QThread spun up for Abort itself (there is
        # nothing left for it to do in the background -- it only flips a
        # flag), unlike the removed _abort_hardware() path.
        assert window.app.stop_fired is True
        assert not window._threads
        # Not a temperature scan (_temperature_scan_active is False, since
        # no series is running at all here) -- wording defaults to "this
        # repeat".
        assert "Stopping after this repeat" in window.app.status
    finally:
        window.close()


def test_abort_control_explains_its_graceful_not_mid_operation_behavior(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        assert window.stop_series_button.text() == "Abort"
        tooltip = window.stop_series_button.toolTip()
        assert "current repeat" in tooltip
        assert "does not stop hardware" in tooltip
    finally:
        window.close()


def test_hardware_action_buttons_disclose_missing_global_confirmation_gate(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        buttons = window.findChildren(QPushButton)
        apply_wfg = next(button for button in buttons if button.text() == "Apply WFG")
        start_exp = next(button for button in buttons if button.text() == "Start exp")
        assert "without an additional confirmation" in apply_wfg.toolTip()
        assert "not protected" in start_exp.toolTip()
        assert "Abort stops only after" in start_exp.toolTip()
    finally:
        window.close()


def test_abort_while_idle_does_not_touch_queue_count(monkeypatch, tmp_path):
    # Abort is reachable (menu action) even when no series is running --
    # in that case there is no repeat counter to replace, so queue_count
    # must be left alone.
    window = make_window(monkeypatch, tmp_path)
    try:
        window.queue_count.setText("0")
        assert window._experiment_series_active is False

        window._abort()

        assert window._stopping_after_current_repeat is False
        assert window.queue_count.text() == "0"
    finally:
        window.close()


def test_abort_during_active_series_shows_stopping_indicator_in_repeat_counter(monkeypatch, tmp_path):
    # Part C follow-up (2026-08-04): once Abort is triggered while a series
    # is genuinely running, the repeat-counter area (queue_count) switches
    # to a distinct "Stopping after this repeat..." state instead of the
    # raw remaining count, until the series actually halts.
    window = make_window(monkeypatch, tmp_path)
    try:
        window._handle_worker_progress("experiment_series_active", True)
        window._handle_worker_progress("queue_count", 5)
        assert window.queue_count.text() == "5"

        window._abort()

        assert window._stopping_after_current_repeat is True
        assert window.queue_count.text() == "Stopping after this repeat..."

        # A queue_count update that arrives while still stopping (e.g. the
        # between-repeats check firing progress("queue_count", remaining)
        # right before returning "ExperimentSeriesAborted") must not
        # clobber the indicator.
        window._handle_worker_progress("queue_count", 3)
        assert window.queue_count.text() == "Stopping after this repeat..."

        # The series actually halting clears the indicator and restores a
        # real count immediately -- not left stuck reading "Stopping..."
        # forever past the point the series has genuinely already stopped.
        window._handle_worker_progress("experiment_series_active", False)

        assert window._stopping_after_current_repeat is False
        assert window.queue_count.text() == str(window.app.experiment_series.see_elements_left())
    finally:
        window.close()


def test_abort_stopping_indicator_does_not_leak_into_the_next_series(monkeypatch, tmp_path):
    # The specific TestStand stale-highlight mistake this was designed to
    # avoid: a leftover "Stopping..." from a previous Abort must not still
    # be showing once a fresh series starts.
    window = make_window(monkeypatch, tmp_path)
    try:
        window._handle_worker_progress("experiment_series_active", True)
        window._abort()
        assert window._stopping_after_current_repeat is True
        window._handle_worker_progress("experiment_series_active", False)
        assert window._stopping_after_current_repeat is False

        # A fresh series starting afterward must display real counts again,
        # not be silently gated by a stale flag.
        window._handle_worker_progress("experiment_series_active", True)
        window._handle_worker_progress("queue_count", 7)

        assert window.queue_count.text() == "7"
    finally:
        window.close()


def test_abort_during_tec_scan_shows_temperature_point_wording(monkeypatch, tmp_path):
    # TEC-scan abort fix follow-up (2026-08-04): the unit that finishes
    # before stopping differs for a TEC temperature scan (a full
    # temperature point -- target + wait + hold + all its own repeats,
    # not just "this repeat") -- the graceful-stop wording must say so.
    window = make_window(monkeypatch, tmp_path)
    try:
        window._handle_worker_progress("experiment_series_active", True)
        window._handle_worker_progress("temperature_scan_active", True)
        window._handle_worker_progress("queue_count", 5)

        window._abort()

        assert window._stopping_after_current_repeat is True
        assert window.queue_count.text() == "Stopping after this temperature point..."
        assert "Stopping after this temperature point" in window.app.status

        window._handle_worker_progress("experiment_series_active", False)
        window._handle_worker_progress("temperature_scan_active", False)

        assert window._stopping_after_current_repeat is False
        assert window.queue_count.text() == str(window.app.experiment_series.see_elements_left())
    finally:
        window.close()


def test_abort_during_plain_series_still_shows_repeat_wording_not_temperature_point(monkeypatch, tmp_path):
    # Sanity check for the other side of the same branch: a plain
    # (non-TEC) experiment series must not pick up TEC-scan wording just
    # because _temperature_scan_active happens to be stale-False from a
    # prior run -- confirmed explicitly false here, not just omitted.
    window = make_window(monkeypatch, tmp_path)
    try:
        window._handle_worker_progress("experiment_series_active", True)
        window._handle_worker_progress("temperature_scan_active", False)

        window._abort()

        assert window.queue_count.text() == "Stopping after this repeat..."
        assert "Stopping after this repeat" in window.app.status
    finally:
        window.close()


def test_shown_then_hidden_window_still_uses_async_cleanup_path(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    shutdown_calls = []

    def record_shutdown(*, close_after):
        shutdown_calls.append(close_after)

    try:
        window.show()
        QApplication.processEvents()
        window.hide()
        QApplication.processEvents()
        window._start_shutdown = record_shutdown

        window.close()

        assert window._window_was_shown is True
        assert shutdown_calls == [True]
    finally:
        window._cleanup_complete_for_close = True
        window.close()


def test_window_close_times_out_blocked_cleanup_without_freezing(monkeypatch, tmp_path):
    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr(qt_ui, "SETTINGS_PATH", settings_path)
    QApplication.instance() or QApplication([])
    cleanup_started = threading.Event()

    class BlockingCleanupApp(qt_ui.Application):
        def cleanup(self):
            cleanup_started.set()
            threading.Event().wait()

    window = build_with_retry(lambda: qt_ui.MainWindow(app=BlockingCleanupApp()))
    window._shutdown_timeout_s = 0.1
    window.show()
    QApplication.processEvents()

    window.close()

    assert cleanup_started.wait(1.0)
    assert process_events_until(lambda: not window.isVisible(), timeout_s=1.0)
    assert any("Shutdown timed out" in str(error) for error in window.app.errors)
    assert settings_path.exists()


def test_run_experiment_series_stops_after_failed_repeat(monkeypatch, tmp_path, caplog):
    from thermo_acoustic.workflows import Experiment2, ExperimentSeries2

    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr(qt_ui, "SETTINGS_PATH", settings_path)
    QApplication.instance() or QApplication([])

    call_count = {"n": 0}

    class FailingRunApplication(qt_ui.Application):
        def run_experiment2(self, progress=None) -> bool:
            call_count["n"] += 1
            self.status = "ExperimentFlushFailed"
            return False

    window = build_with_retry(lambda: qt_ui.MainWindow(app=FailingRunApplication()))
    try:
        series = ExperimentSeries2(series_path=tmp_path)
        series.enqueue_experiments([Experiment2(), Experiment2()])
        config = window._experiment_wfg_config()

        with caplog.at_level("ERROR", logger="thermo_acoustic.qt_ui"):
            try:
                window._run_experiment_series(series, total_frames=1, config=config)
            except RuntimeError as exc:
                assert "repeat 1" in str(exc)
            else:
                raise AssertionError("expected RuntimeError when a repeat fails")

        assert call_count["n"] == 1
        assert any("repeat 1" in record.message for record in caplog.records)
    finally:
        window.close()


def test_run_experiment_series_stops_queuing_further_repeats_after_abort(monkeypatch, tmp_path):
    from thermo_acoustic.workflows import Experiment2, ExperimentSeries2

    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr(qt_ui, "SETTINGS_PATH", settings_path)
    QApplication.instance() or QApplication([])

    call_count = {"n": 0}

    class AbortingRunApplication(qt_ui.Application):
        def run_experiment2(self, progress=None) -> bool:
            self.experiment_series.dequeue_experiment()
            call_count["n"] += 1
            self.status = "ExperimentComplete"
            if call_count["n"] == 1:
                # Simulate the operator pressing Abort while this repeat was
                # running -- qt_ui.py's _abort() calls fire_stop_event().
                self.fire_stop_event()
            return True

    window = build_with_retry(lambda: qt_ui.MainWindow(app=AbortingRunApplication()))
    try:
        series = ExperimentSeries2(series_path=tmp_path)
        series.enqueue_experiments([Experiment2(), Experiment2(), Experiment2()])
        config = window._experiment_wfg_config()

        status = window._run_experiment_series(series, total_frames=1, config=config)

        assert status == "ExperimentSeriesAborted"
        assert call_count["n"] == 1, "no further repeat should have started after Abort was fired"
        assert series.see_elements_left() == 2, "queue must not drain to completion after Abort"
    finally:
        window.close()


def test_run_experiment_series_brackets_experiment_series_active_progress(monkeypatch, tmp_path):
    # Category 2 (Session 39): qt_ui_v2.py's "Experiment running" indicator
    # used to derive its Yes/No from "experiment" in self.app.status.lower(),
    # which goes stale the instant Abort is clicked (Abort's own
    # "Aborting..." status overwrites app.status while the current repeat may
    # still be executing). Fixed to read an explicit
    # "experiment_series_active" progress kind that _run_experiment_series()
    # now emits True before its loop and False (via try/finally) on every
    # exit path. This test confirms the bracketing on both the successful
    # path and the raised-RuntimeError path.
    from test_application import install_fake_nptdms
    from thermo_acoustic.workflows import Experiment2, ExperimentSeries2

    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr(qt_ui, "SETTINGS_PATH", settings_path)
    QApplication.instance() or QApplication([])
    install_fake_nptdms(monkeypatch)

    window = make_window(monkeypatch, tmp_path)
    try:
        series = ExperimentSeries2(series_path=tmp_path)
        series.enqueue_experiments([Experiment2()])
        config = window._experiment_wfg_config()

        events: list[tuple[str, object]] = []
        window._run_experiment_series(series, total_frames=1, config=config, progress=lambda kind, value: events.append((kind, value)))

        active_events = [value for kind, value in events if kind == "experiment_series_active"]
        assert active_events == [True, False]
        assert events.index(("experiment_series_active", True)) < events.index(("experiment_series_active", False))
        assert len([value for kind, value in events if kind == "series_timing_started"]) == 1
        repeat_timing = [value for kind, value in events if kind == "series_repeat_completed"]
        assert len(repeat_timing) == 1
        assert repeat_timing[0]["completed_repeats"] == 1
        assert repeat_timing[0]["total_repeats"] == 1
    finally:
        window.close()

    class FailingRunApplication(qt_ui.Application):
        def run_experiment2(self, progress=None) -> bool:
            self.status = "ExperimentFlushFailed"
            return False

    window = build_with_retry(lambda: qt_ui.MainWindow(app=FailingRunApplication()))
    try:
        series = ExperimentSeries2(series_path=tmp_path)
        series.enqueue_experiments([Experiment2()])
        config = window._experiment_wfg_config()

        events = []
        try:
            window._run_experiment_series(series, total_frames=1, config=config, progress=lambda kind, value: events.append((kind, value)))
        except RuntimeError:
            pass
        else:
            raise AssertionError("expected RuntimeError when the repeat fails")

        active_events = [value for kind, value in events if kind == "experiment_series_active"]
        assert active_events == [True, False], "flag must be cleared even when a repeat raises"
    finally:
        window.close()


def test_run_experiment_series_fires_real_step_events_for_all_seven_steps(monkeypatch, tmp_path):
    # Phase 3 step-progress breadcrumb (2026-08-04) prerequisite fix: this
    # call site (_run_experiment_series_body()) previously did not pass
    # `progress` into Application.run_experiment2() at all, so
    # step_started/step_completed (fired by application.py's _report_step())
    # never reached the UI -- confirmed here through the REAL call chain
    # (qt_ui.py's _run_experiment_series() -> run_experiment2()), not a
    # mocked or hand-simulated progress feed.
    from test_application import install_fake_nptdms
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
    from thermo_acoustic.workflows import Experiment2, ExperimentSeries2

    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr(qt_ui, "SETTINGS_PATH", settings_path)
    QApplication.instance() or QApplication([])
    install_fake_nptdms(monkeypatch)

    window = make_window(monkeypatch, tmp_path)
    try:
        series = ExperimentSeries2(series_path=tmp_path)
        series.enqueue_experiments([Experiment2()])
        config = window._experiment_wfg_config()

        events: list[tuple[str, object]] = []
        window._run_experiment_series(series, total_frames=1, config=config, progress=lambda kind, value: events.append((kind, value)))

        started = [value for kind, value in events if kind == "step_started"]
        completed = [value for kind, value in events if kind == "step_completed"]
        # WaitForAd2Completion/Flush are genuinely conditional in real
        # run_experiment2() (only entered if AD2 has remaining wait time /
        # flush is enabled for this experiment) -- not asserted unconditional
        # here, since a default Experiment2()/Application() doesn't exercise
        # either. The steps that DO always run must still fire, in the real
        # traced order, each started immediately followed eventually by its
        # own completed -- proving the real wiring, not just that SOME events
        # arrived.
        always_run = [
            STEP_INITIALIZE_EXPERIMENT, STEP_CONFIGURE_WFG, STEP_CONFIGURE_CAMERA,
            STEP_CAPTURE_FRAMES, STEP_SAVE_RESULTS,
        ]
        assert started == always_run, started
        assert completed == always_run, completed
        assert set(STEP_ORDER) - set(started) <= {STEP_WAIT_FOR_AD2_COMPLETION, STEP_FLUSH}
        assert events.index(("step_reset", None)) < events.index(("step_started", STEP_ORDER[0]))
    finally:
        window.close()


def test_run_temperature_experiment_series_fires_real_step_reset_per_temperature_point(monkeypatch, tmp_path):
    # Same prerequisite fix as the non-TEC test above, for the TEC path:
    # _run_temperature_experiment_series() previously called
    # Application.run_temperature_series() without `progress` at all, so
    # SetTecTarget/WaitTecStable/step_reset never reached the UI during a
    # real TEC scan. run_experiment2() is overridden to a trivial dequeue
    # here (matching test_tec.py's own TemperatureRunApplication pattern) so
    # this test isolates the TEC-path wiring specifically, through the REAL
    # qt_ui.py -> application.py call chain.
    from test_tec import RecordingTecBackend
    from thermo_acoustic.application import STEP_SAVE_RESULTS, STEP_SET_TEC_TARGET, STEP_WAIT_TEC_STABLE
    from thermo_acoustic.tec import TecController
    from thermo_acoustic.workflows import Experiment2, ExperimentSeries2, TemperatureSeries

    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr(qt_ui, "SETTINGS_PATH", settings_path)
    QApplication.instance() or QApplication([])

    class TemperatureRunApplication(qt_ui.Application):
        def __init__(self) -> None:
            super().__init__(tec=TecController(enabled=True, simulate=True, backend=RecordingTecBackend()))

        def run_experiment2(self, progress=None) -> bool:
            self.experiment_series.dequeue_experiment()
            if progress:
                progress("step_completed", STEP_SAVE_RESULTS)
            return True

    window = build_with_retry(lambda: qt_ui.MainWindow(app=TemperatureRunApplication()))
    try:
        temperature_series = TemperatureSeries(
            temperature_points_c=[20.0, 25.0],
            tolerance_c=0.1,
            min_settle_s=0.0,
            max_wait_s=0.1,
            poll_interval_s=0.001,
        )
        groups = [
            ExperimentSeries2(tmp_path / "t1", [Experiment2(repeat_id=0)]),
            ExperimentSeries2(tmp_path / "t2", [Experiment2(repeat_id=0)]),
        ]
        config = window._experiment_wfg_config()

        events: list[tuple[str, object]] = []
        window._run_temperature_experiment_series(
            temperature_series, groups, total_frames=2, config=config,
            progress=lambda kind, value: events.append((kind, value)),
        )

        reset_indices = [index for index, (kind, _value) in enumerate(events) if kind == "step_reset"]
        target_started_indices = [
            index for index, (kind, value) in enumerate(events)
            if kind == "step_started" and value == STEP_SET_TEC_TARGET
        ]
        stable_started_indices = [
            index for index, (kind, value) in enumerate(events)
            if kind == "step_started" and value == STEP_WAIT_TEC_STABLE
        ]
        # One reset + one SetTecTarget + one WaitTecStable per temperature
        # point (2 points), and each point's reset strictly precedes that
        # point's own target/stability steps.
        assert len(reset_indices) == 2
        assert len(target_started_indices) == 2
        assert len(stable_started_indices) == 2
        assert reset_indices[0] < target_started_indices[0] < stable_started_indices[0] < reset_indices[1]
        assert reset_indices[1] < target_started_indices[1] < stable_started_indices[1]
        repeat_timing = [value for kind, value in events if kind == "series_repeat_completed"]
        assert [value["completed_repeats"] for value in repeat_timing] == [1, 2]
        assert all(value["total_repeats"] == 2 for value in repeat_timing)
    finally:
        window.close()


def test_start_experiment_blocks_on_existing_data_until_confirmed(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        series_dir = tmp_path / "series"
        (series_dir / "repeat_001").mkdir(parents=True)
        (series_dir / "repeat_001" / "data.tdms").write_text("existing data", encoding="utf-8")
        window.series_path.setText(str(series_dir))

        run_action_calls = []
        monkeypatch.setattr(window, "_run_action", lambda *args, **kwargs: run_action_calls.append((args, kwargs)))

        monkeypatch.setattr(qt_ui.QMessageBox, "question", staticmethod(lambda *a, **k: qt_ui.QMessageBox.StandardButton.No))
        window._start_experiment()
        assert run_action_calls == [], "declining the overwrite confirmation must not start the experiment"
        assert not (series_dir / "repeat_002").exists(), "no new side effects should occur when the user declines"

        window.exp_camera_fps.setValue(100.0)
        monkeypatch.setattr(qt_ui.QMessageBox, "question", staticmethod(lambda *a, **k: qt_ui.QMessageBox.StandardButton.Yes))
        window._start_experiment()
        assert len(run_action_calls) == 1, "confirming the overwrite should proceed as normal"
    finally:
        window.close()


# Session 104: manual, operator-initiated pump fault-clear escape hatch UI.
def test_clear_pump_fault_button_shows_warning_and_is_not_skippable(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        run_action_calls = []
        monkeypatch.setattr(window, "_run_action", lambda *args, **kwargs: run_action_calls.append((args, kwargs)))

        question_calls = []

        def fake_question(*args, **kwargs):
            question_calls.append((args, kwargs))
            return qt_ui.QMessageBox.StandardButton.No

        monkeypatch.setattr(qt_ui.QMessageBox, "question", staticmethod(fake_question))

        window._start_clear_pump_fault()

        assert len(question_calls) == 1, "declining must not be reachable without the warning dialog having been shown"
        warning_text = question_calls[0][0][2]
        assert "hardware_repair_plan.md" in warning_text
        assert "does NOT fix the underlying cause" in warning_text
        assert run_action_calls == [], "declining the warning must not clear the fault or reconnect"
    finally:
        window.close()


def test_clear_pump_fault_button_proceeds_only_after_explicit_confirmation(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        run_action_calls = []
        monkeypatch.setattr(window, "_run_action", lambda *args, **kwargs: run_action_calls.append((args, kwargs)))
        monkeypatch.setattr(
            qt_ui.QMessageBox, "question", staticmethod(lambda *a, **k: qt_ui.QMessageBox.StandardButton.Yes)
        )

        window._start_clear_pump_fault()

        assert len(run_action_calls) == 1, "confirming the warning should proceed to clear_pump_fault_and_retry()"
        action, starting_status = run_action_calls[0][0][:2]
        assert starting_status == "Clearing Pump Fault"
        # Confirm the queued action really is Application.clear_pump_fault_and_retry() --
        # not, e.g., a bare pump.initialize() that would silently skip the fault-clear step.
        calls = []
        window.app.pump = type("FakePump", (), {"clear_fault_and_reinitialize": lambda self: calls.append("cleared")})()
        action(None)
        assert calls == ["cleared"]
    finally:
        window.close()


def test_clear_pump_fault_button_never_invoked_by_normal_initialize_flow(monkeypatch, tmp_path):
    # Requirement 1: clear_fault_and_reinitialize() must never be reachable
    # except through the explicit button -- confirm the normal Initialize
    # dialog path never calls Application.clear_pump_fault_and_retry() or
    # touches pump_fault_manually_cleared_this_session, even when Initialize
    # itself is exercised.
    window = make_window(monkeypatch, tmp_path)
    try:
        calls = []
        # Application is a slots dataclass (application.py:97) -- patch the
        # class, not the instance, same as any other slotted-instance method
        # override.
        monkeypatch.setattr(type(window.app), "clear_pump_fault_and_retry", lambda self: calls.append("cleared"))
        assert window.app.pump_fault_manually_cleared_this_session is False

        run_action_calls = []
        monkeypatch.setattr(window, "_run_action", lambda *args, **kwargs: run_action_calls.append((args, kwargs)))
        window._start_initialize()

        assert calls == [], "Initialize must never reach clear_pump_fault_and_retry()"
        assert window.app.pump_fault_manually_cleared_this_session is False
    finally:
        window.close()


def test_syringe_selection_and_custom_volume_flow_into_flush_settings(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        window.syringe.setCurrentText("BD 1ml")
        window.flush_volume.setValue(5.0)
        settings = window._flush_settings()
        assert settings.syringe_volume_ml == 1.0

        try:
            window.app.flush(settings)
        except ValueError as exc:
            assert "exceeds syringe capacity" in str(exc)
        else:
            raise AssertionError("expected flush() to refuse when volume exceeds syringe capacity")

        window.syringe.setCurrentText("Custom")
        window.custom_syringe_volume_ml.setValue(2.5)
        custom_settings = window._flush_settings()
        assert custom_settings.syringe_volume_ml == 2.5
    finally:
        window.close()


class _FakeAD2ConfigureDwf:
    """Purpose-built fake for _apply_wfg() -- lets frequency/amplitude
    device ranges be set independently (Session 51), unlike a generic
    blanket "*Info always returns some fixed value" fake."""

    def __init__(self, frequency_range=(10.0, 1_000_000.0), amplitude_range=(-5.0, 5.0)):
        self.frequency_range = frequency_range
        self.amplitude_range = amplitude_range

    def __getattr__(self, name):
        def func(*args):
            if name == "FDwfAnalogOutNodeFrequencyInfo":
                self._assign(args[3], self.frequency_range[0])
                self._assign(args[4], self.frequency_range[1])
            elif name == "FDwfAnalogOutNodeAmplitudeInfo":
                self._assign(args[3], self.amplitude_range[0])
                self._assign(args[4], self.amplitude_range[1])
            return 1
        return func

    @staticmethod
    def _assign(byref_arg, value):
        target = getattr(byref_arg, "_obj", byref_arg)
        target.value = value


def test_apply_wfg_surfaces_out_of_range_warning_in_status(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        window.app.ad2 = AD2Sdk(backend=WaveFormsBackend(dwf=_FakeAD2ConfigureDwf()))
        window.app.ad2.device_handle = 123
        config = WfgConfig(channels=[WfgChannelConfig(0), WfgChannelConfig(1)])
        config.channels[0].carrier.amplitude_v = 999.0  # above the fake device's max

        status = window._apply_wfg(config)

        assert "WARNING" in status
        assert "Ch1" in status
        assert "Ch2" not in status
    finally:
        window.close()


def test_apply_wfg_reports_no_warning_when_in_range(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        window.app.ad2 = AD2Sdk(backend=WaveFormsBackend(dwf=_FakeAD2ConfigureDwf()))
        window.app.ad2.device_handle = 123
        config = WfgConfig(channels=[WfgChannelConfig(0), WfgChannelConfig(1)])

        status = window._apply_wfg(config)

        assert status == "WFG configured"
    finally:
        window.close()


_TOOLTIP_COVERAGE_WIDGET_TYPES = (QDoubleSpinBox, QSpinBox, QComboBox, QCheckBox, QLineEdit)


def _has_tooltip_icon(widget) -> bool:
    """True if widget's immediate parent is one of
    MainWindow._wrap_with_tooltip_icon()'s _TooltipIconWrapper containers
    (Session 41, Part 2) -- isinstance() against a dedicated wrapper class,
    not a style/text guess, so it can't be confused with an unrelated
    sibling elsewhere in the same form."""
    return isinstance(widget.parentWidget(), qt_ui._TooltipIconWrapper)


def _tooltip_coverage_sweep(window) -> list[tuple[str, str, bool, bool]]:
    """findChildren()-based sweep (same pattern as the wheel-guard audit,
    Session 28/29/33) over every real value-bearing widget -- excludes the
    internal QLineEdit every QAbstractSpinBox/QComboBox uses as its own text
    editor, which is not a separate control. Returns
    (class_name, tooltip_text, has_tooltip, has_visible_marker) per widget."""
    results = []
    for widget_cls in _TOOLTIP_COVERAGE_WIDGET_TYPES:
        for widget in window.findChildren(widget_cls):
            if isinstance(widget.parent(), (QAbstractSpinBox, QComboBox)):
                continue
            tip = widget.toolTip()
            results.append((type(widget).__name__, tip, bool(tip), _has_tooltip_icon(widget)))
    return results


def test_every_value_widget_has_a_tooltip_and_visible_marker(monkeypatch, tmp_path):
    # Requirement A/B/C completeness test, revised (Session 41): Session 40
    # required a tooltip on all 172 fields; this session narrowed coverage
    # back to genuinely non-obvious fields only (127 of 172 in qt_ui.py --
    # see the Session 41 changelog entry for the full classification), and
    # replaced the label-style marker with a separate ⓘ icon widget. This
    # test checks COHERENCE generically (no hardcoded per-field list, so it
    # stays valid as fields are added/removed later): every widget with a
    # tooltip must have the icon marker, and -- just as importantly, since
    # Session 40's overshoot is the thing being corrected -- every widget
    # WITHOUT a tooltip must NOT have one either (confirming the narrowing
    # actually removed the marker, not just the tooltip text). The overall
    # kept/removed split itself is asserted as an explicit count, since that
    # split was a reviewed judgment call worth protecting from silent drift.
    window = make_window(monkeypatch, tmp_path)
    try:
        results = _tooltip_coverage_sweep(window)
        assert len(results) >= 172, f"expected at least 172 real widgets, found {len(results)}"

        missing_marker = [(cls, tip) for cls, tip, has_tip, marked in results if has_tip and not marked]
        assert not missing_marker, f"tooltipped widgets missing the visible icon marker: {missing_marker}"

        unwanted_marker = [cls for cls, _tip, has_tip, marked in results if not has_tip and marked]
        assert not unwanted_marker, f"widgets with no tooltip but an icon marker anyway: {unwanted_marker}"

        kept = sum(1 for _cls, _tip, has_tip, _marked in results if has_tip)
        # 129 (127, Session 41 re-narrowing, + 2, Session 44's
        # custom_syringe_inner_diameter_mm/custom_syringe_stroke_mm) + 5
        # piezo Z-scan calibration tab fields (Phase 4:
        # z_start/z_end/step_size/exposure_ms/output_dir, landed in commit
        # 23e17d5) + 9 TEC integration fields (enabled/sim/resource + 6 scan
        # controls) = 143, then -1 for the Status/Error Out history-log work:
        # error_status/error_code/error_source were three separate QLabel/
        # QLineEdit rows, one of which (error_code) carried a tooltip counted
        # here; replaced with a single HistoryLogWidget (a QListWidget
        # subclass, not in _TOOLTIP_COVERAGE_WIDGET_TYPES above, so its own
        # tooltip is real but genuinely out of this sweep's scope) = 142,
        # then +1 for the new "Refill/Empty Flow Rate" field
        # (self.fill_flow_rate, 2026-08-03) = 143, then +1 for the new
        # "Temperature points CH2 (C)" QLineEdit (self.exp_tec_points_ch2,
        # 2026-08-04, dual-channel lock/unlock feature) = 144. The lock
        # toggle itself (self.exp_tec_lock_channels) is a QPushButton, not
        # in _TOOLTIP_COVERAGE_WIDGET_TYPES above, so it's out of this
        # sweep's scope even though it does carry a real tooltip. Then +1
        # for the new "Post-stabilization hold (s)" field
        # (self.exp_tec_post_stable_hold_s, 2026-08-04) = 145.
        assert kept == 145, f"expected 145 fields with a tooltip after adding the TEC post-stable-hold field, found {kept}"

        # Spot-check a representative sample from both sides of the Session
        # 41 classification (full list and rationale in the changelog).
        assert window.custom_syringe_volume_ml.toolTip()  # named dependency example, kept
        assert window.wait_after_flush.toolTip()  # named example, kept
        assert window.dcam_source.toolTip()  # unverified status, kept
        assert not window.flush_count.toolTip()  # plain repeat count, removed
        assert not window.image_continuous.toolTip()  # self-explanatory checkbox, removed
        assert not window.wfg_channels[0]["frequency"].toolTip()  # self-evident + redundant w/ "(overridden)" label, removed
    finally:
        window.close()
