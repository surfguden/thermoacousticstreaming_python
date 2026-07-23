from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QCheckBox, QLabel

from thermo_acoustic import qt_ui, qt_ui_v2
from thermo_acoustic.hardware_factory import HardwareRuntimeConfig


def make_window(monkeypatch, tmp_path) -> qt_ui_v2.MainWindowV2:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({}), encoding="utf-8")
    monkeypatch.setattr(qt_ui, "SETTINGS_PATH", settings_path)
    QApplication.instance() or QApplication([])
    return qt_ui_v2.MainWindowV2()


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


def test_v2_sidebar_buttons_open_existing_manual_test_panels(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        for panel_name in ("WFG", "MSO", "PumpValve", "Camera"):
            dialog = window._ensure_manual_panel(panel_name)

            assert dialog.windowTitle() == f"{panel_name} (Manual Test)"
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
