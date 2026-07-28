from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .application import Application
from .hardware_factory import HardwareRuntimeConfig, apply_hardware_bundle, build_hardware_bundle
from .instruments import SimulatedAD2Sdk
from .qt_ui import MainWindow, install_focus_wheel_guard


class InitializationDialog(QDialog):
    """Preview initialization dialog with per-device progress rows."""

    DEVICE_NAMES = ("AD2", "Camera", "Pump", "Valve", "Z-stage")

    def __init__(self, parent: QWidget, start_callback) -> None:
        super().__init__(parent)
        self.setWindowTitle("Initialize Hardware")
        self.setModal(False)
        self._status_labels: dict[str, QLabel] = {}

        root = QVBoxLayout(self)
        note = QLabel("Only one UI window should control real hardware at a time. Close the other UI window before initializing here.")
        note.setWordWrap(True)
        root.addWidget(note)

        root.addWidget(self._device_selection_group(parent))
        root.addWidget(self._hardware_details_group(parent))

        buttons = QHBoxLayout()
        initialize = QPushButton("Initialize")
        initialize.clicked.connect(start_callback)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        buttons.addWidget(initialize)
        buttons.addWidget(close)
        root.addLayout(buttons)

    def _device_selection_group(self, window: QWidget) -> QGroupBox:
        group = QGroupBox("Devices")
        grid = QGridLayout(group)
        grid.addWidget(QLabel("Enable"), 0, 0)
        grid.addWidget(QLabel("Simulate"), 0, 1)
        grid.addWidget(QLabel("Device"), 0, 2)
        grid.addWidget(QLabel("Progress"), 0, 3)

        rows = (
            ("AD2", window.ad2_enabled, window.sim_ad2),
            ("Camera", window.camera_enabled, window.sim_camera),
            ("Pump", window.pump_enabled, window.sim_pump),
            ("Valve", window.valve_enabled, window.sim_valve),
            ("Z-stage", window.z_enabled, self._z_stage_simulate_placeholder()),
        )
        for row, (name, enable, simulate) in enumerate(rows, start=1):
            label = QLabel("Waiting")
            self._status_labels[name] = label
            # Enable/Simulate checkboxes already carry their own tooltip
            # (window._build_state()) -- wrapped directly (their own "Off/On"
            # text is the row's only label) since there's no separate
            # row-label widget in this grid layout to place an icon beside.
            grid.addWidget(window._wrap_with_tooltip_icon(enable), row, 0)
            grid.addWidget(window._wrap_with_tooltip_icon(simulate), row, 1)
            grid.addWidget(QLabel(name), row, 2)
            grid.addWidget(label, row, 3)
        grid.setColumnStretch(2, 1)
        return group

    def _z_stage_simulate_placeholder(self) -> QCheckBox:
        checkbox = QCheckBox("N/A")
        checkbox.setEnabled(False)
        checkbox.setToolTip(
            "Z stage has no Simulate checkbox on the Initialization tab either -- when enabled, "
            "hardware_factory.build_hardware_bundle() always builds a real Prior-serial backend, "
            "with no simulated variant."
        )
        return checkbox

    def _hardware_details_group(self, window: QWidget) -> QGroupBox:
        group = QGroupBox("Hardware Details")
        form = QFormLayout(group)
        form.addRow("Z stage backend", self._mark_unwired_stub(window.z_backend))
        form.addRow("Prior VISA resource name", window.prior_resource)
        form.addRow("Thorlabs/APT serial", self._mark_unwired_stub(window.thorlabs_apt_serial))
        form.addRow("Thorlabs/APT backend", self._mark_unwired_stub(window.thorlabs_apt_backend))
        form.addRow("Thorlabs/APT discovery only", self._mark_unwired_stub(window.thorlabs_apt_discovery_only))
        form.addRow("Valve resource", window.valve_resource)
        form.addRow("Qmix SDK Python Path", self._mark_unwired_stub(self._widen_for_content(window.qmix_sdk_python_path)))
        form.addRow("Qmix QMIXSDK Path", self._mark_unwired_stub(self._widen_for_content(window.qmix_qmixsdk_path)))
        form.addRow("Cetoni config path", self._widen_for_content(window.cetoni_config_path))
        window._add_tooltip_icons(form)
        return group

    @staticmethod
    def _mark_unwired_stub(widget: QWidget) -> QWidget:
        widget.setEnabled(False)
        widget.setToolTip("Not wired to a real backend")
        return widget

    @staticmethod
    def _widen_for_content(widget: QLineEdit, padding: int = 40) -> QLineEdit:
        # Path values (Qmix SDK / QMIXSDK / Cetoni config) can be long
        # Windows paths; size the field to the current value instead of
        # a guessed constant so it isn't visually truncated.
        required_width = widget.fontMetrics().horizontalAdvance(widget.text()) + padding
        widget.setMinimumWidth(max(widget.minimumWidth(), required_width))
        return widget

    def reset(self) -> None:
        for name in self.DEVICE_NAMES:
            self.set_device_status(name, "Waiting")

    def set_device_status(self, device_name: str, status: str) -> None:
        label = self._status_labels.get(device_name)
        if label is None:
            return
        label.setText(status)


class MainWindowV2(MainWindow):
    """Opt-in preview UI skeleton that reuses the existing experiment logic."""

    _MANUAL_PANEL_BUILDERS: dict[str, str] = {
        "WFG": "_wfg_tab",
        "MSO": "_mso_tab",
        "PumpValve": "_pump_tab",
        "Camera": "_camera_tab",
        "ZScan": "_zscan_tab",
    }
    # Category 8 (Session 39): "PumpValve" (an internal dict key, smashed
    # together with no separator for use as a Python identifier/lookup key)
    # was rendered verbatim on the sidebar button and in the manual-panel
    # dialog's own window title -- the only one of the four panel names that
    # reads like an internal identifier rather than a real label ("WFG"/"MSO"
    # are legitimate domain acronyms already used identically throughout
    # both UIs, not internal-naming leakage). Display text now matches
    # qt_ui.py's own tab name for the same feature exactly
    # (self.tabs.addTab(self._pump_tab(), "Pump&Valve")) rather than
    # inventing new wording; the other three keys are already their own
    # correct display text, so this dict only needs the one entry.
    _PANEL_DISPLAY_NAMES: dict[str, str] = {"PumpValve": "Pump&Valve", "ZScan": "Z-Scan"}

    @classmethod
    def _panel_display_name(cls, panel_name: str) -> str:
        return cls._PANEL_DISPLAY_NAMES.get(panel_name, panel_name)

    def __init__(self, app: Application | None = None) -> None:
        self._initialization_dialog: InitializationDialog | None = None
        self._manual_panels: dict[str, QDialog] = {}
        super().__init__(app=app)
        self.setWindowTitle("Thermo Acoustic Streaming - New UI Preview")
        self.resize(1440, 860)
        self._seed_experiment_ad2_from_wfg_once()
        self._refresh_status()

    def _build_layout(self) -> None:
        self._build_menu_bar()

        root = QWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)

        layout.addWidget(self._left_navigation(), 0)
        layout.addWidget(self._center_experiment_area(), 1)
        layout.addWidget(self._global_status_panel(), 0)

    def _build_menu_bar(self) -> None:
        menu = self.menuBar()
        menu.addAction("Exit", self._exit_app)
        menu.addAction("Abort", self._abort)
        menu.addAction("Save Settings", self._save_settings)
        menu.addAction("Load Settings", self._load_settings)

    def _left_navigation(self) -> QWidget:
        panel = QWidget()
        panel.setMaximumWidth(170)
        layout = QVBoxLayout(panel)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.connection_button = QPushButton("* Not Connected")
        self.connection_button.clicked.connect(self._open_initialization_dialog)
        layout.addWidget(self.connection_button)

        for name in ("WFG", "MSO", "PumpValve", "Camera", "ZScan"):
            button = QPushButton(self._panel_display_name(name))
            button.clicked.connect(lambda checked=False, panel_name=name: self._open_manual_panel(panel_name))
            layout.addWidget(button)

        layout.addStretch(1)
        return panel

    def _center_experiment_area(self) -> QScrollArea:
        area = QScrollArea()
        area.setWidgetResizable(True)

        content = QWidget()
        grid = QGridLayout(content)
        grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        grid.addWidget(self._v2_status_progress_group(), 0, 0, 1, 2)
        grid.addWidget(self._v2_sequence_control_group(), 1, 0, 1, 2)
        grid.addWidget(self._v2_ad2_output_group(), 2, 0, 1, 2)
        grid.addWidget(self._v2_acquisition_group(), 3, 0)
        grid.addWidget(self._experiment_flush_group(), 3, 1)
        # Category 7 (Session 39): FM Sweep and Frequency Scanning are both
        # real, fully-wired Experiment-tab features in qt_ui.py -- neither
        # had any reachable control anywhere in this window before (FM Sweep
        # flagged as a known gap since Session 25, never fixed; Frequency
        # Scanning's v2 gap was never even flagged, added in Session 34 after
        # this table was last touched). Both bind the exact same
        # self.exp_sweep_*/self.exp_freq_scan_* widgets qt_ui.py's Experiment
        # tab uses -- _experiment_frequency_scan_group() is reused directly
        # (same pattern as _experiment_flush_group() above); FM Sweep needed
        # a new standalone builder since its qt_ui.py equivalent is embedded
        # inline in a method v2 never calls (see _experiment_fm_sweep_group()).
        grid.addWidget(self._experiment_fm_sweep_group(), 4, 0)
        grid.addWidget(self._experiment_frequency_scan_group(), 4, 1)
        grid.addWidget(self._v2_waveform_group(), 5, 0, 1, 2)

        area.setWidget(content)
        return area

    def _v2_status_progress_group(self) -> QGroupBox:
        group = QGroupBox("Status / Progress")
        group.setMinimumHeight(120)
        grid = QGridLayout(group)

        self.status = QLineEdit("System Not Initialized")
        self.status.setReadOnly(True)
        self.status.setMinimumWidth(320)
        self.queue_count = QLabel("0")

        # Elapsed Time / Time Left: confirmed dead (Session 39, Category 4) --
        # a static "00:00:00" placeholder never updated by any code path in
        # either UI, same underlying stub helper qt_ui.py's own Experiment
        # tab now uses.
        grid.addWidget(QLabel("Elapsed Time"), 0, 0)
        grid.addWidget(self._wrap_with_tooltip_icon(self._elapsed_time_label()), 1, 0)
        grid.addWidget(QLabel("Time Left"), 0, 1)
        grid.addWidget(self._wrap_with_tooltip_icon(self._time_left_label()), 1, 1)
        grid.addWidget(QLabel("# elements in queue"), 0, 2)
        grid.addWidget(self.queue_count, 1, 2)
        grid.addWidget(QLabel("Status"), 0, 3)
        grid.addWidget(self.status, 1, 3)
        grid.setColumnStretch(3, 1)
        return group

    def _v2_sequence_control_group(self) -> QGroupBox:
        group = QGroupBox("Sequence Control")
        group.setMinimumHeight(140)
        grid = QGridLayout(group)
        start = QPushButton("Start exp")
        start.clicked.connect(self._start_experiment)
        browse = QPushButton("...")
        browse.clicked.connect(lambda: self._browse_folder(self.series_path))

        grid.addWidget(QLabel("Start Experiment series"), 0, 0)
        grid.addWidget(start, 1, 0)
        grid.addWidget(QLabel("Series path"), 2, 0)
        grid.addWidget(self._wrap_with_tooltip_icon(self.series_path), 3, 0, 1, 4)
        grid.addWidget(browse, 3, 4)
        grid.setColumnStretch(3, 1)
        return group

    def _v2_ad2_output_group(self) -> QGroupBox:
        group = QGroupBox("AD2 Output Parameters CH0 / CH1")
        group.setMinimumHeight(260)
        outer = QVBoxLayout(group)

        content = QWidget()
        grid = QGridLayout(content)
        headers = (
            "Enable", "Function", "Frequency (kHz)", "Amplitude (V)", "Offset (V)",
            "Start (s)", "Run (s)", "cRepeat", "Trigger Source",
            "Symmetry (%)", "Phase (Deg)", "Repeat Trigger",
        )
        core_column_count = 9
        # Detail cluster (Symmetry/Phase/Repeat Trigger) visually set apart from
        # the core columns with its own spanning sub-header, mirroring the
        # Carrier/Trigger/Sweep sub-grouping just added to qt_ui.py's Experiment
        # tab -- purely a visual grouping, same 12 columns/widgets as before.
        detail_label = QLabel("Detail")
        grid.addWidget(detail_label, 0, core_column_count + 1, 1, len(headers) - core_column_count)
        # No per-cell tooltip icons in this dense table (Session 41,
        # Part 2): each column's field widget is the SAME shared instance
        # the Experiment tab's own labeled rows use, and wrapping either a
        # header or a data cell here to add an icon would change what
        # grid.itemAtPosition(row, col).widget() returns -- breaking this
        # table's own pre-existing identity tests (confirming CH0/CH1 bind
        # the identical widgets, Session 24/25). The explanation is already
        # reachable via the icon on the Experiment tab's equivalent field.
        for column, header in enumerate(headers, start=1):
            grid.addWidget(QLabel(header), 1, column)

        self._add_experiment_ad2_row(grid, 2, "CH0", self.exp_ad2_channels[0])
        self._add_experiment_ad2_row(grid, 3, "CH1", self.exp_ad2_channels[1])
        self._size_ad2_output_columns(grid, headers)

        # The outer experiment area shrinks this group's content to fit the
        # window (QScrollArea.setWidgetResizable(True) in
        # _center_experiment_area), which otherwise compresses/truncates
        # these 10 columns at moderate widths. Give the table its own
        # non-resizable scroll area so it keeps its natural width and
        # scrolls horizontally instead of compressing when the window is
        # narrower than that.
        scroll = QScrollArea()
        scroll.setWidgetResizable(False)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        return group

    @staticmethod
    def _size_ad2_output_columns(grid: QGridLayout, headers: tuple[str, ...]) -> None:
        padding = 24
        for column, header in enumerate(headers, start=1):
            header_item = grid.itemAtPosition(1, column)
            data_item = grid.itemAtPosition(2, column)
            header_width = header_item.widget().fontMetrics().horizontalAdvance(header) + padding
            content_width = data_item.widget().sizeHint().width() + padding
            grid.setColumnMinimumWidth(column, max(header_width, content_width, 60))

    def _add_experiment_ad2_row(self, grid: QGridLayout, row: int, label: str, state: dict[str, object]) -> None:
        grid.addWidget(QLabel(label), row, 0)
        widgets = (
            state["enable"],
            state["function"],
            state["frequency"],
            state["amplitude"],
            state["offset"],
            state["sec_wait"],
            state["sec_run"],
            state["repeat"],
            state["trigger_source"],
            state["symmetry"],
            state["phase"],
            state["repeat_trigger"],
        )
        for column, widget in enumerate(widgets, start=1):
            grid.addWidget(widget, row, column)

    def _v2_acquisition_group(self) -> QGroupBox:
        group = QGroupBox("Acquisition Parameters")
        group.setMinimumHeight(300)
        grid = QGridLayout(group)
        acquisition_rows = (
            ("Camera FPS", self.exp_camera_fps),
            ("Camera Start (s)", self.exp_camera_start),
            ("Repeats", self.exp_repeats),
            ("Frames", self.exp_frames),
            ("Exposure time (ms)", self.exp_exposure_ms),
            ("GlobalExposure", self.global_exposure),
        )
        for row, (text, widget) in enumerate(acquisition_rows):
            grid.addWidget(QLabel(text), row, 0)
            grid.addWidget(self._wrap_with_tooltip_icon(widget), row, 1)

        camera_start = QGroupBox("Camera Start Array(s)")
        camera_start_layout = QGridLayout(camera_start)
        # Dynamic Camera Start Time moved here from the acquisition grid's own
        # column -- it's the toggle controlling whether this array is used at
        # all (see qt_ui.py's _experiment_do_clock_config()), so it belongs
        # with the array it controls rather than the other, unrelated
        # acquisition params (matching the same regroup applied in qt_ui.py's
        # own _camera_start_group()).
        camera_start_layout.addWidget(QLabel("Dynamic Camera Start Time"), 0, 0)
        camera_start_layout.addWidget(self._wrap_with_tooltip_icon(self.dynamic_camera_start), 0, 1)
        for index, widget in enumerate(self.camera_start_array):
            # No adjacent label for these (qt_ui.py's own _camera_start_group()
            # form rows are label-less too) -- wrap the field itself directly.
            camera_start_layout.addWidget(self._wrap_with_tooltip_icon(widget), index // 2 + 1, index % 2)
        grid.addWidget(camera_start, 0, 2, 6, 1)
        grid.setColumnStretch(2, 1)
        return group

    def _v2_waveform_group(self) -> QGroupBox:
        group = QGroupBox("Waveform Preview / Average FPS")
        group.setMinimumHeight(260)
        layout = QVBoxLayout(group)
        fps_row = QHBoxLayout()
        fps_row.addWidget(QLabel("Average FPS"))
        fps_row.addWidget(self.average_fps)
        fps_row.addStretch(1)
        layout.addLayout(fps_row)
        self.waveform_graph = self.waveform_graph if hasattr(self, "waveform_graph") else None
        self.waveform_graph = self.waveform_graph or self._make_waveform_graph()
        layout.addWidget(self.waveform_graph)
        return group

    def _make_waveform_graph(self):
        from .qt_ui import WaveformGraph

        return WaveformGraph()

    def _global_status_panel(self) -> QGroupBox:
        group = QGroupBox("Global Status")
        # Offscreen measurement (Session 39, Category 3) found every value
        # QLabel in this form squeezed to a fixed 34px regardless of its own
        # content (e.g. "Not connected" needing 156px, "idle, fill 0.000 ml"
        # needing 228px) -- this group's own minimumSizeHint (534x269) was
        # never checked against its 280px maximumWidth cap, unlike every
        # QGroupBox in qt_ui.py's own tabs, which the generic
        # test_no_group_box_is_squeezed_below_its_minimum_size_hint guard
        # (Session 29) already covers -- that guard only walks
        # window.tabs.currentWidget(), which qt_ui_v2.MainWindowV2 doesn't
        # have. Fixed with WrapLongRows, the same established pattern
        # already used for narrow-column truncation on the Pump&Valve tab
        # (Session 38): a row's label goes on its own line when it doesn't
        # fit alongside its field, giving the field(most of the group's
        # width on the line below instead of a fixed sliver. Confirmed
        # offscreen this alone (no width change) resolves every QLabel
        # truncation in this form.
        group.setMaximumWidth(300)
        form = QFormLayout(group)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

        self.error_status = QLabel("OK")
        self.error_code = QLineEdit("0")
        self.error_code.setReadOnly(True)
        self.error_code.setToolTip("Always '0' when status='OK', '1' on any caught exception -- not a real DCAM/AD2/Qmix error code, just a boolean flag (_handle_worker_finished()).")
        self.error_source = QLineEdit("")
        self.error_source.setReadOnly(True)
        form.addRow("Error Out status", self.error_status)
        form.addRow("Error Out code", self.error_code)
        form.addRow("Error Out source", self.error_source)

        # word-wrap: these four can display long runtime text (e.g. the
        # valve's real "Connected (unverified position response: '...')"
        # status_note passthrough, Session 2) that WrapLongRows' extra
        # row width alone would not guarantee fits on one line.
        self.ad2_connection_status = QLabel("Not connected")
        self.ad2_connection_status.setWordWrap(True)
        self.camera_connection_status = QLabel("Not connected")
        self.camera_connection_status.setWordWrap(True)
        self.pump_connection_status = QLabel("Not connected")
        self.pump_connection_status.setWordWrap(True)
        self.valve_connection_status = QLabel("Not connected")
        self.valve_connection_status.setWordWrap(True)
        form.addRow("AD2", self.ad2_connection_status)
        form.addRow("Camera", self.camera_connection_status)
        form.addRow("Pump", self.pump_connection_status)
        form.addRow("Valve", self.valve_connection_status)

        self.ad2_running_status = QLabel("No")
        self.camera_capturing_status = QLabel("No")
        self.experiment_running_status = QLabel("No")
        form.addRow("AD2 output running", self.ad2_running_status)
        form.addRow("Camera capturing", self.camera_capturing_status)
        form.addRow("Experiment running", self.experiment_running_status)

        self.valve_position_status = QLabel("Unknown")
        self.pump_state_status = QLabel("Unknown")
        form.addRow("Valve position", self.valve_position_status)
        form.addRow("Pump state / fill level", self.pump_state_status)
        self._add_tooltip_icons(form)
        return group

    def _open_initialization_dialog(self) -> None:
        dialog = self._ensure_initialization_dialog()
        dialog.show()
        dialog.raise_()

    def _ensure_initialization_dialog(self) -> InitializationDialog:
        if self._initialization_dialog is None:
            self._initialization_dialog = InitializationDialog(self, self._start_initialize)
        return self._initialization_dialog

    def _show_placeholder(self, panel_name: str) -> None:
        self._set_status(f"{self._panel_display_name(panel_name)} panel is not yet implemented in the new UI preview")

    def _open_manual_panel(self, panel_name: str) -> None:
        dialog = self._ensure_manual_panel(panel_name)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _ensure_manual_panel(self, panel_name: str) -> QDialog:
        dialog = self._manual_panels.get(panel_name)
        if dialog is None:
            builder_name = self._MANUAL_PANEL_BUILDERS[panel_name]
            content = getattr(self, builder_name)()
            dialog = QDialog(self)
            dialog.setWindowTitle(f"{self._panel_display_name(panel_name)} (Manual Test)")
            dialog.setModal(False)
            layout = QVBoxLayout(dialog)
            layout.addWidget(content)
            self._manual_panels[panel_name] = dialog
        return dialog

    def _start_initialize(self) -> None:
        self._seed_experiment_ad2_from_wfg_once()
        dialog = self._ensure_initialization_dialog()
        dialog.reset()
        dialog.show()

        config = HardwareRuntimeConfig(
            ad2_enabled=self.ad2_enabled.isChecked(),
            sim_ad2=self.sim_ad2.isChecked(),
            camera_enabled=self.camera_enabled.isChecked(),
            sim_camera=self.sim_camera.isChecked(),
            pump_enabled=self.pump_enabled.isChecked(),
            sim_pump=self.sim_pump.isChecked(),
            valve_enabled=self.valve_enabled.isChecked(),
            sim_valve=self.sim_valve.isChecked(),
            z_enabled=self.z_enabled.isChecked(),
            prior_resource=self.prior_resource.text(),
            valve_resource=self.valve_resource.text(),
            cetoni_config_path=self.cetoni_config_path.text(),
        )
        self._run_action(lambda progress: self._initialize_system(config, progress), "Initializing")

    def _initialize_system(self, config: HardwareRuntimeConfig, progress=None) -> str:
        if progress:
            progress("status", "Opening selected hardware")
        try:
            self.app.cleanup()
        except Exception as exc:
            self.app.check_loop_error(exc)

        apply_hardware_bundle(self.app, build_hardware_bundle(config))
        self.app.create_queues()
        self.app.register_events()
        self.app.fire_status_event("Initializing")

        initialized: list[tuple[str, object]] = []
        for name, instrument in (
            ("AD2", self.app.ad2),
            ("Camera", self.app.camera),
            ("Pump", self.app.pump),
            ("Valve", self.app.valve),
            ("Z-stage", self.app.z_motor),
        ):
            if progress:
                progress("init_device", (name, "In Progress"))
            try:
                instrument.initialize()
            except Exception as exc:
                if progress:
                    progress("init_device", (name, "Failed"))
                rollback_errors = self.app._cleanup_instruments(initialized)
                details = [f"{name} initialize failed: {exc}"]
                details.extend(rollback_errors)
                raise RuntimeError("; ".join(details)) from exc
            initialized.append((name, instrument))
            if progress:
                progress("init_device", (name, "Complete"))

        self.app.fire_status_event("System Initialized")
        return "System Initialized"

    def _handle_worker_progress(self, kind: str, value) -> None:
        if kind == "init_device":
            device_name, status = value
            self._ensure_initialization_dialog().set_device_status(str(device_name), str(status))
            return
        super()._handle_worker_progress(kind, value)

    def _refresh_status(self) -> None:
        super()._refresh_status()
        connected = self.app.status == "System Initialized"
        if hasattr(self, "connection_button"):
            self.connection_button.setText("* Connected" if connected else "* Not Connected")
            self.connection_button.setStyleSheet("color: green;" if connected else "color: red;")
        if not hasattr(self, "ad2_connection_status"):
            return

        self.ad2_connection_status.setText(self._connected_text(getattr(self.app.ad2, "enabled", True), getattr(self.app.ad2, "device_handle", None)))
        self.camera_connection_status.setText(self._connected_text(getattr(self.app.camera, "enabled", True), getattr(self.app.camera, "handle", None)))
        self.pump_connection_status.setText("Disabled" if not getattr(self.app.pump, "enabled", True) else ("Connected" if getattr(self.app.pump, "referenced", False) else "Not connected"))
        self.valve_connection_status.setText(self._valve_connection_text())

        wfg_config = getattr(self.app.ad2, "wfg_config", None)
        self.ad2_running_status.setText("Yes" if getattr(wfg_config, "running", False) else "No")
        self.camera_capturing_status.setText("Yes" if getattr(self.app.camera, "capturing", False) else "No")
        # Reads the "experiment_series_active" flag qt_ui.py's
        # _run_experiment_series() brackets its own execution with (see
        # qt_ui.py's _build_state()/_handle_worker_progress()) -- not a
        # status-text substring match. The prior "experiment" in
        # self.app.status.lower() heuristic went stale the instant Abort was
        # clicked: Abort's own "Aborting..." status overwrites self.app.status
        # while the series' current repeat may still genuinely be executing,
        # which would have made this indicator misleadingly report "No"
        # while hardware was still active.
        self.experiment_running_status.setText("Yes" if getattr(self, "_experiment_series_active", False) else "No")
        self.valve_position_status.setText(self._valve_position_text())
        dosing = "dosing" if getattr(self.app.pump, "dosing", False) else "idle"
        self.pump_state_status.setText(f"{dosing}, fill {getattr(self.app.pump, 'fill_level', 0.0):.3f} ml")

    @staticmethod
    def _connected_text(enabled: bool, handle: object | None) -> str:
        if not enabled:
            return "Disabled"
        return "Connected" if handle is not None else "Not connected"

    def _valve_connection_text(self) -> str:
        valve = self.app.valve
        if not getattr(valve, "enabled", True):
            return "Disabled"
        if not getattr(valve, "initialized", False):
            return "Not connected"
        status_note = getattr(valve, "status_note", "")
        if status_note and status_note != "confirmed":
            return f"Connected ({status_note})"
        return "Connected"

    def _valve_position_text(self) -> str:
        # Position 1 = Open, Position 2 = Closed (confirmed physical mapping,
        # see instruments.py's Valve class) -- surfaced explicitly here too,
        # not just on the Pump&Valve tab's own Pos1/Pos2 buttons, since this
        # is the only live readout of the valve's current position in v2.
        position = getattr(self.app.valve, "position", None)
        if position == 1:
            return "1 (Open)"
        if position == 2:
            return "2 (Closed)"
        return "Unknown"


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    install_focus_wheel_guard(app)
    window = MainWindowV2(app=Application(ad2=SimulatedAD2Sdk()))
    window.show()
    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
