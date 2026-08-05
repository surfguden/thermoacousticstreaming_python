from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .application import Application
from .instruments import SimulatedAD2Sdk
from .qt_ui import install_focus_wheel_guard
from .qt_ui_v2 import MainWindowV2


class MainWindowV3(MainWindowV2):
    """Layout-focused evolution of v2 using the same application runtime."""

    _MANUAL_PANEL_INITIAL_SIZES = {
        "WFG": (900, 760),
        "MSO": (820, 680),
        "PumpValve": (900, 760),
        "Camera": (900, 760),
        "ZScan": (900, 540),
    }

    def __init__(self, app: Application | None = None) -> None:
        super().__init__(app=app)
        self.setWindowTitle("Thermo Acoustic Streaming - Transitional UI v3")
        self.resize(1440, 900)

    def _build_layout(self) -> None:
        self._build_menu_bar()

        # Build the detailed monitoring column first because it owns the live
        # connection labels mirrored by the compact summary strip below.
        runtime = self._v3_runtime_column()

        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QHBoxLayout(root)
        root_layout.addWidget(self._left_navigation(), 0)

        workspace = QWidget()
        workspace_layout = QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)

        workspace_layout.addWidget(self._v3_connection_strip(), 0)

        status = self._v2_status_progress_group()
        status.setObjectName("v3StatusFirst")
        workspace_layout.addWidget(status, 0)

        workspace_layout.addWidget(self._v3_run_control_group(), 0)

        operational = QWidget()
        operational_layout = QHBoxLayout(operational)
        operational_layout.setContentsMargins(0, 0, 0, 0)
        operational_layout.addWidget(self._v3_setup_tabs(), 1)
        operational_layout.addWidget(runtime, 0)
        workspace_layout.addWidget(operational, 1)

        root_layout.addWidget(workspace, 1)

    def _ensure_initialization_dialog(self):
        created = self._initialization_dialog is None
        dialog = super()._ensure_initialization_dialog()
        if created:
            # v2 sizes these path fields to their complete text, which makes
            # this dialog wider than many screens. QLineEdit still scrolls to
            # show the full path, so a practical minimum does not hide data.
            for field in (
                self.qmix_sdk_python_path,
                self.qmix_qmixsdk_path,
                self.cetoni_config_path,
            ):
                field.setMinimumWidth(260)
            dialog.setMinimumSize(760, 560)
            dialog.resize(900, 680)
        return dialog

    def _ensure_manual_panel(self, panel_name: str):
        created = panel_name not in self._manual_panels
        dialog = super()._ensure_manual_panel(panel_name)
        if created:
            dialog.resize(*self._MANUAL_PANEL_INITIAL_SIZES[panel_name])
        return dialog

    def _v3_connection_strip(self) -> QGroupBox:
        group = QGroupBox("Connections")
        group.setObjectName("v3ConnectionStrip")
        layout = QHBoxLayout(group)
        self._v3_connection_values: dict[str, QLabel] = {}
        for name in ("AD2", "Camera", "Pump", "Valve"):
            layout.addWidget(QLabel(name))
            value = QLabel("Not connected")
            value.setMinimumWidth(82)
            self._v3_connection_values[name] = value
            layout.addWidget(value)
        layout.addStretch(1)
        return group

    def _v3_run_control_group(self) -> QGroupBox:
        group = QGroupBox("Run experiment")
        group.setObjectName("v3PrimaryRunControl")
        grid = QGridLayout(group)
        start = QPushButton("Start experiment")
        start.setMinimumHeight(44)
        start.setToolTip(
            "Runs with the currently initialized backends. Abort remains a repeat-boundary request, "
            "not an emergency hardware stop."
        )
        start.clicked.connect(self._start_experiment)
        browse = QPushButton("...")
        browse.clicked.connect(lambda: self._browse_folder(self.series_path))
        note = QLabel("Uses the configured setup below and the currently initialized hardware.")
        note.setWordWrap(True)
        note.setMaximumWidth(520)
        grid.addWidget(start, 0, 0, 2, 1)
        grid.addWidget(QLabel("Series path"), 0, 1)
        grid.addWidget(self._wrap_with_tooltip_icon(self.series_path), 1, 1)
        grid.addWidget(browse, 1, 2)
        grid.addWidget(note, 0, 3, 2, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        return group

    def _v3_setup_tabs(self) -> QTabWidget:
        tabs = QTabWidget()
        tabs.setObjectName("v3SetupTabs")

        ad2_content = QWidget()
        ad2_layout = QVBoxLayout(ad2_content)
        ad2_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        ad2_layout.addWidget(self._v2_ad2_output_group())
        modulation = QTabWidget()
        modulation.setObjectName("v3ModulationTabs")
        modulation.addTab(self._experiment_fm_sweep_group(), "FM Sweep")
        modulation.addTab(self._experiment_frequency_scan_group(), "Frequency Scan")
        ad2_layout.addWidget(modulation)
        tabs.addTab(self._v3_scroll_page(ad2_content, "v3Ad2SetupScroll"), "AD2 Output")

        camera_content = QWidget()
        camera_layout = QVBoxLayout(camera_content)
        camera_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        camera_layout.addWidget(self._v2_acquisition_group())
        tabs.addTab(self._v3_scroll_page(camera_content, "v3CameraSetupScroll"), "Camera")

        fluidics_content = QWidget()
        fluidics_layout = QVBoxLayout(fluidics_content)
        fluidics_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        fluidics_note = QLabel("Optional post-capture pump/valve workflow. Disabled by default.")
        fluidics_note.setWordWrap(True)
        fluidics_note.setMaximumWidth(520)
        fluidics_layout.addWidget(fluidics_note)
        fluidics_layout.addWidget(self._experiment_flush_group())
        fluidics_layout.addStretch(1)
        tabs.addTab(self._v3_scroll_page(fluidics_content, "v3FluidicsSetupScroll"), "Fluidics")

        advanced_content = QWidget()
        advanced_layout = QVBoxLayout(advanced_content)
        advanced_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        advanced_layout.addWidget(self._experiment_temperature_group())
        advanced_layout.addStretch(1)
        tabs.addTab(self._v3_scroll_page(advanced_content, "v3AdvancedSetupScroll"), "Advanced")
        return tabs

    @staticmethod
    def _v3_scroll_page(content: QWidget, object_name: str) -> QScrollArea:
        area = QScrollArea()
        area.setObjectName(object_name)
        area.setWidgetResizable(True)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.setWidget(content)
        return area

    def _v3_runtime_column(self) -> QScrollArea:
        area = QScrollArea()
        area.setObjectName("v3RuntimeMonitoring")
        area.setWidgetResizable(True)
        area.setMaximumWidth(320)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self._v2_waveform_group())
        layout.addWidget(self._global_status_panel())
        area.setWidget(content)
        return area

    def _experiment_temperature_group(self) -> QGroupBox:
        group = super()._experiment_temperature_group()
        group.setTitle("TEC Temperature Scan")
        note = QLabel("Simulated by default. Real TEC operation remains unapproved.")
        note.setWordWrap(True)
        note.setMaximumWidth(520)
        layout = group.layout()
        if isinstance(layout, QFormLayout):
            layout.insertRow(0, note)
        return group

    def _refresh_status(self) -> None:
        super()._refresh_status()
        values = getattr(self, "_v3_connection_values", None)
        if not values or not hasattr(self, "ad2_connection_status"):
            return
        sources = {
            "AD2": self.ad2_connection_status.text(),
            "Camera": self.camera_connection_status.text(),
            "Pump": self.pump_connection_status.text(),
            "Valve": self.valve_connection_status.text(),
        }
        for name, text in sources.items():
            label = values[name]
            label.setText(text)
            if text == "Connected":
                color = "green"
            elif text == "Disabled":
                color = "gray"
            elif text.startswith("Connected"):
                color = "darkorange"
            else:
                color = "red"
            label.setStyleSheet(f"color: {color};")

    # Manual WFG panel: retain v2's computed preview and v1's validated
    # controls, but stack the two long channel forms instead of putting them
    # side by side with the preview.
    def _wfg_manual_panel_content(self) -> QWidget:
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setObjectName("v3WfgScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        note = QLabel("Manual AD2 test. These settings do not affect experiment runs.")
        note.setWordWrap(True)
        note.setMaximumWidth(700)
        layout.addWidget(note)

        header = QHBoxLayout()
        header.addWidget(QLabel("Output configuration"))
        header.addWidget(self._wrap_with_tooltip_icon(self.wfg_running))
        header.addStretch(1)
        self.wfg_sync.setEnabled(False)
        self.wfg_sync.setToolTip("Not implemented: SynchronizeState is currently a non-functional stub.")
        header.addWidget(QLabel("SynchronizeState"))
        header.addWidget(self._wrap_with_tooltip_icon(self.wfg_sync))
        layout.addLayout(header)

        layout.addWidget(self._wfg_channel_group("Ch1", self.wfg_channels[0]))
        layout.addWidget(self._wfg_channel_group("Ch2", self.wfg_channels[1]))

        apply = QPushButton("Apply WFG")
        apply.setToolTip(
            "Applies these manual settings immediately. A connected real AD2 can change output "
            "without an additional confirmation dialog."
        )
        apply.clicked.connect(self._start_apply_wfg)
        layout.addWidget(apply, alignment=Qt.AlignmentFlag.AlignLeft)

        preview = self._wfg_preview_group()
        preview.setMaximumHeight(280)
        layout.addWidget(preview)

        scroll.setWidget(content)
        outer.addWidget(scroll)
        self._update_wfg_preview()
        return tab

    def _wfg_preview_group(self) -> QGroupBox:
        group = super()._wfg_preview_group()
        labels = group.findChildren(QLabel)
        if labels:
            labels[0].setText("Computed from the current manual settings; no hardware readback.")
            labels[0].setMaximumWidth(700)
        return group

    def _mso_tab(self) -> QWidget:
        base = super()._mso_tab()
        groups = base.findChildren(QGroupBox, options=Qt.FindChildOption.FindDirectChildrenOnly)

        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setObjectName("v3MsoScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        note = QLabel("Manual AD2 diagnostic; independent of experiment runs.")
        note.setWordWrap(True)
        note.setMaximumWidth(700)
        layout.addWidget(note)
        for group in groups:
            layout.addWidget(group)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        base.deleteLater()
        return tab

    def _pump_tab(self) -> QWidget:
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setObjectName("v3PumpValveScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        note = QLabel("Manual controls. P01/P02 routing needs bench confirmation.")
        note.setWordWrap(True)
        note.setMaximumWidth(700)
        layout.addWidget(note)

        operational_label = QLabel("Operational controls")
        operational_label.setObjectName("v3PumpOperationalHeading")
        layout.addWidget(operational_label)
        operational = QGridLayout()

        pump_group = QGroupBox("Pump operations")
        pump_form = QFormLayout(pump_group)
        pump_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        refill = QPushButton("Refill")
        refill.clicked.connect(lambda: self._run_action(lambda progress: self._refill(), "Refilling"))
        empty = QPushButton("Empty")
        empty.clicked.connect(lambda: self._run_action(lambda progress: self._empty(), "Emptying"))
        generate = QPushButton("Generate")
        generate.clicked.connect(self._start_generate_flow)
        go = QPushButton("GO")
        go.clicked.connect(self._start_go_level)
        stop = QPushButton("STOP")
        stop.setMinimumHeight(50)
        stop.clicked.connect(lambda: self._run_action(lambda progress: self.app.pump.stop(), "Pump stopped"))
        pump_form.addRow("Refill/Empty flow (uL/min)", self.fill_flow_rate)
        pump_form.addRow(refill, empty)
        pump_form.addRow("Flow rate (-=aspirate, +=dispense)", self.flow_rate)
        pump_form.addRow(generate)
        pump_form.addRow("Target level (ml)", self.level_ml)
        pump_form.addRow(go)
        pump_form.addRow(stop)
        self._add_tooltip_icons(pump_form)

        valve_group = QGroupBox("Valve position / routing")
        valve_form = QFormLayout(valve_group)
        valve_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        pos1 = QPushButton("Pos1 (P01)")
        pos1.setToolTip("Sends P01. Physical fluidic routing remains unverified.")
        pos1.clicked.connect(
            lambda: self._run_action(lambda progress: self.app.valve.set_position(1), "Valve Pos1 (P01)")
        )
        pos2 = QPushButton("Pos2 (P02)")
        pos2.setToolTip("Sends P02. Physical fluidic routing remains unverified.")
        pos2.clicked.connect(
            lambda: self._run_action(lambda progress: self.app.valve.set_position(2), "Valve Pos2 (P02)")
        )
        valve_form.addRow(pos1)
        valve_form.addRow(pos2)

        flush_group = QGroupBox("Flush workflow")
        flush_form = QFormLayout(flush_group)
        flush_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        flush = QPushButton("Flush")
        flush.clicked.connect(self._start_flush)
        flush_form.addRow("Number of flushes", self.flush_count)
        flush_form.addRow("Flow rate (uL/min)", self.flush_flowrate)
        flush_form.addRow("Volume (ml)", self.flush_volume)
        flush_form.addRow("Wait after flush (s)", self.wait_after_flush)
        flush_form.addRow(flush)
        self._add_tooltip_icons(flush_form)

        operational.addWidget(pump_group, 0, 0, 2, 1)
        operational.addWidget(valve_group, 0, 1)
        operational.addWidget(flush_group, 1, 1)
        operational.setColumnStretch(0, 1)
        operational.setColumnStretch(1, 1)
        layout.addLayout(operational)

        configuration_label = QLabel("Static configuration")
        configuration_label.setObjectName("v3PumpConfigurationHeading")
        layout.addWidget(configuration_label)
        configuration = QGridLayout()

        syringe_group = QGroupBox("Syringe and calibration")
        syringe_form = QFormLayout(syringe_group)
        syringe_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        configure = QPushButton("Configure")
        configure.clicked.connect(self._start_configure_syringe)
        reference = QPushButton("Reference move")
        reference.clicked.connect(self._start_reference_move)
        syringe_form.addRow("Reference", reference)
        syringe_form.addRow("Syringe", self.syringe)
        syringe_form.addRow("Custom volume (ml)", self.custom_syringe_volume_ml)
        syringe_form.addRow("Custom inner diameter (mm)", self.custom_syringe_inner_diameter_mm)
        syringe_form.addRow("Custom max piston stroke (mm)", self.custom_syringe_stroke_mm)
        syringe_form.addRow(configure)
        self._add_tooltip_icons(syringe_form)

        configuration.addWidget(syringe_group, 0, 0)
        configuration.setColumnStretch(0, 1)
        layout.addLayout(configuration)

        scroll.setWidget(content)
        outer.addWidget(scroll)
        return tab

    def _camera_tab(self) -> QWidget:
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setObjectName("v3CameraScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        note = QLabel("Manual camera controls. Sequence settings also feed experiment runs.")
        note.setWordWrap(True)
        note.setMaximumWidth(700)
        layout.addWidget(note)
        layout.addWidget(self._v3_camera_acquisition_group())
        layout.addWidget(self._roi_group())
        layout.addWidget(self._v3_camera_sequence_actions_group())
        layout.addWidget(self._v3_camera_sequence_settings_group())
        layout.addWidget(self._v3_conversion_group())

        scroll.setWidget(content)
        outer.addWidget(scroll)
        return tab

    def _v3_camera_acquisition_group(self) -> QGroupBox:
        group = QGroupBox("Acquisition")
        row = QHBoxLayout(group)
        image = QPushButton("Image")
        image.clicked.connect(self._start_capture_camera_image)
        continuous = self._live_image_continuous_checkbox()
        continuous.toggled.connect(self._set_image_continuous)
        row.addWidget(image)
        row.addWidget(QLabel("Continuous"))
        row.addWidget(continuous)
        hint = QLabel("Configure camera before capture.")
        hint.setWordWrap(True)
        hint.setMaximumWidth(300)
        row.addWidget(hint)
        row.addStretch(1)
        return group

    def _v3_camera_sequence_actions_group(self) -> QGroupBox:
        group = QGroupBox("Sequence actions")
        form = QFormLayout(group)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        start = QPushButton("Start capture")
        start.clicked.connect(
            lambda: self._run_action(lambda progress: self.app.camera.start_capture(), "Camera capture started")
        )
        trigger = QPushButton("Software trigger")
        trigger.clicked.connect(lambda: self._run_action(lambda progress: self.app.camera.sw_trigg(), "Camera triggered"))
        save = QPushButton("Save frames")
        save.clicked.connect(self._start_save_sequence)
        browse = QPushButton("...")
        browse.clicked.connect(lambda: self._browse_folder(self.sequence_path))
        path_row = QHBoxLayout()
        path_row.addWidget(self.sequence_path, 1)
        path_row.addWidget(browse)
        form.addRow(start)
        form.addRow(trigger)
        form.addRow("Output folder", path_row)
        form.addRow(save)
        return group

    def _v3_camera_sequence_settings_group(self) -> QGroupBox:
        group = QGroupBox("Sequence settings")
        form = QFormLayout(group)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        for label, widget in (
            ("Mode", self.sequence_mode),
            ("Source", self.sequence_source),
            ("Interval", self.sequence_interval),
            ("Burst", self.sequence_burst),
            ("Frames", self.sequence_frames),
            ("DCAM trigger source", self.dcam_source),
            ("Polarity", self.external_polarity),
            ("Delay", self.external_delay),
            ("Capture mode (unused)", self.capture_mode),
            ("Sequence exposure (unused)", self.sequence_exposure_ms),
        ):
            form.addRow(label, widget)
        note = QLabel("Also used by experiment runs.")
        note.setWordWrap(True)
        form.addRow(note)
        self._add_tooltip_icons(form)
        return group

    def _v3_conversion_group(self) -> QGroupBox:
        group = QGroupBox("Advanced: display conversion")
        form = QFormLayout(group)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.addRow("Method", self.conversion_method)
        form.addRow("Minimum", self.conversion_min)
        form.addRow("Maximum", self.conversion_max)
        form.addRow("Bit shifts", self.conversion_shifts)
        adjust = QPushButton("Apply to preview")
        adjust.clicked.connect(self._adjust_camera_preview)
        self.conversion_method.currentTextChanged.connect(lambda _value: self._update_conversion_controls())
        form.addRow(adjust)
        self._add_tooltip_icons(form)
        self._update_conversion_controls()
        return group

    def _zscan_control_group(self) -> QGroupBox:
        group = QGroupBox("Scan Control")
        layout = QVBoxLayout(group)
        query_range = QPushButton("Query Piezo Range")
        query_range.clicked.connect(self._query_zscan_range)
        start = QPushButton("Start Z-Scan")
        start.clicked.connect(self._start_zscan)
        abort = QPushButton("Abort Z-Scan")
        abort.clicked.connect(self._abort_zscan)
        layout.addWidget(query_range)
        layout.addWidget(start)
        layout.addWidget(abort)
        hint = QLabel("Configure the camera first. Motion requires explicit confirmation.")
        hint.setWordWrap(True)
        hint.setMaximumWidth(280)
        layout.addWidget(hint)
        layout.addStretch(1)
        return group


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    install_focus_wheel_guard(app)
    window = MainWindowV3(app=Application(ad2=SimulatedAD2Sdk()))
    window.show()
    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
