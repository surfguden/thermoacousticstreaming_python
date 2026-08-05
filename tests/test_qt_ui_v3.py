from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QGroupBox, QLabel, QScrollArea, QTabWidget

from thermo_acoustic import qt_ui, qt_ui_v2, qt_ui_v3
from thermo_acoustic.application import Application

from conftest import build_with_retry


def make_window(monkeypatch, tmp_path, app: Application | None = None) -> qt_ui_v3.MainWindowV3:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({}), encoding="utf-8")
    monkeypatch.setattr(qt_ui, "SETTINGS_PATH", settings_path)
    QApplication.instance() or QApplication([])
    return build_with_retry(lambda: qt_ui_v3.MainWindowV3(app=app))


def test_v3_is_a_layout_evolution_of_v2_and_v2_remains_available(monkeypatch, tmp_path):
    v3 = make_window(monkeypatch, tmp_path)
    v2 = build_with_retry(qt_ui_v2.MainWindowV2)
    try:
        assert isinstance(v3, qt_ui_v2.MainWindowV2)
        assert type(v3) is qt_ui_v3.MainWindowV3
        assert type(v2) is qt_ui_v2.MainWindowV2
        assert v3.windowTitle() == "Thermo Acoustic Streaming - Transitional UI v3"
        assert v2.windowTitle() == "Thermo Acoustic Streaming - Transitional UI (shared hardware runtime)"
        assert any(action.text() == "Abort" for action in v3.menuBar().actions())
    finally:
        v3.close()
        v2.close()


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
        run_control = window.findChild(QGroupBox, "v3PrimaryRunControl")
        setup_tabs = window.findChild(QTabWidget, "v3SetupTabs")
        assert status is not None
        assert connections is not None
        assert run_control is not None
        assert setup_tabs is not None
        connection_y = connections.mapTo(window.centralWidget(), connections.rect().topLeft()).y()
        status_y = status.mapTo(window.centralWidget(), status.rect().topLeft()).y()
        run_y = run_control.mapTo(window.centralWidget(), run_control.rect().topLeft()).y()
        setup_y = setup_tabs.mapTo(window.centralWidget(), setup_tabs.rect().topLeft()).y()
        assert connection_y < status_y < run_y < setup_y
        assert [setup_tabs.tabText(index) for index in range(setup_tabs.count())] == [
            "AD2 Output",
            "Camera",
            "Fluidics",
            "Advanced",
        ]
        assert set(window._v3_connection_values) == {"AD2", "Camera", "Pump", "Valve"}
        assert window._v3_connection_values["AD2"].text() == window.ad2_connection_status.text()
        assert window._v3_connection_values["Camera"].text() == window.camera_connection_status.text()
        assert window._v3_connection_values["Pump"].text() == window.pump_connection_status.text()
        assert window._v3_connection_values["Valve"].text() == window.valve_connection_status.text()
    finally:
        window.close()


def test_v3_pump_panel_separates_actions_from_static_configuration(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        dialog = window._ensure_manual_panel("PumpValve")
        scroll = dialog.findChild(QScrollArea, "v3PumpValveScroll")
        assert scroll is not None
        assert scroll.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        headings = {label.objectName(): label.text() for label in dialog.findChildren(QLabel) if label.objectName()}
        assert headings["v3PumpOperationalHeading"] == "Operational controls"
        assert headings["v3PumpConfigurationHeading"] == "Static configuration"
        groups = {group.title() for group in dialog.findChildren(QGroupBox)}
        assert {
            "Pump operations",
            "Valve position / routing",
            "Flush workflow",
            "Syringe and calibration",
        } <= groups
        assert window.flow_rate in dialog.findChildren(type(window.flow_rate))
    finally:
        window.close()


def test_v3_camera_panel_has_ordered_acquisition_sequence_and_advanced_display(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        dialog = window._ensure_manual_panel("Camera")
        scroll = dialog.findChild(QScrollArea, "v3CameraScroll")
        assert scroll is not None
        assert scroll.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        direct_titles = [
            item.widget().title()
            for index in range(scroll.widget().layout().count())
            if (item := scroll.widget().layout().itemAt(index)).widget() is not None
            and isinstance(item.widget(), QGroupBox)
        ]
        assert direct_titles == [
            "Acquisition",
            "ROI",
            "Sequence actions",
            "Sequence settings",
            "Advanced: display conversion",
        ]
        assert window.sequence_frames in dialog.findChildren(type(window.sequence_frames))
    finally:
        window.close()


def test_v3_wfg_keeps_manual_controls_but_removes_outer_horizontal_overflow(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        dialog = window._ensure_manual_panel("WFG")
        scroll = dialog.findChild(QScrollArea, "v3WfgScroll")
        assert scroll is not None
        assert scroll.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        assert dialog.sizeHint().width() < 800
        groups = {group.title(): group for group in dialog.findChildren(QGroupBox)}
        assert "Ch1" in groups and "Ch2" in groups
        assert "Waveform Preview (computed)" in groups
        assert window.wfg_channels[0]["frequency"] in dialog.findChildren(type(window.wfg_channels[0]["frequency"]))
    finally:
        window.close()


def test_v3_mso_stacks_controls_and_preview_without_outer_horizontal_scroll(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        dialog = window._ensure_manual_panel("MSO")
        scroll = dialog.findChild(QScrollArea, "v3MsoScroll")
        assert scroll is not None
        assert scroll.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        assert dialog.sizeHint().width() < 800
        groups = {group.title() for group in dialog.findChildren(QGroupBox)}
        assert {"MSO Configuration", "Waveform"} <= groups
        assert window.mso_sample_frequency in dialog.findChildren(type(window.mso_sample_frequency))
    finally:
        window.close()


def test_v3_dialogs_open_at_usable_sizes_without_full_path_width(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)
    try:
        expected_sizes = {
            "WFG": (900, 760),
            "MSO": (820, 680),
            "PumpValve": (900, 760),
            "Camera": (900, 760),
            "ZScan": (900, 540),
        }
        for panel_name, expected in expected_sizes.items():
            dialog = window._ensure_manual_panel(panel_name)
            assert (dialog.width(), dialog.height()) == expected

        initialize = window._ensure_initialization_dialog()
        assert initialize.width() == 900
        assert initialize.height() == 680
        assert initialize.minimumWidth() == 760
        assert window.cetoni_config_path.minimumWidth() == 260
        assert initialize.sizeHint().width() < 1200
    finally:
        window.close()
