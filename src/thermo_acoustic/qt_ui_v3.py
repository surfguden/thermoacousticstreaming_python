from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .application import Application
from .experiment_planning import (
    BuildResult,
    ExperimentRequest,
    blocking_build_result,
    build_result_from_existing_plan,
    run_plan_from_existing_series,
)
from .instruments import SimulatedAD2Sdk
from .piezo_zscan import ZScanCalibration
from .qt_ui import install_focus_wheel_guard
from .qt_ui_v2 import InitializationDialog, MainWindowV2
from .runtime_truth import RuntimeEvent, RuntimeEventSeverity
from .workflows import Experiment2


def _rename_unique_text_widget(
    root: QWidget,
    widget_type,
    old_text: str,
    new_text: str,
    object_name: str,
) -> None:
    """Adapt one inherited caption and fail visibly if the v2 contract drifts."""
    matches = [widget for widget in root.findChildren(widget_type) if widget.text() == old_text]
    if len(matches) != 1:
        raise RuntimeError(
            f"V3 expected exactly one {widget_type.__name__} captioned {old_text!r}; found {len(matches)}."
        )
    matches[0].setText(new_text)
    matches[0].setObjectName(object_name)


def _rename_unique_group(
    root: QWidget,
    old_title: str,
    new_title: str,
    object_name: str,
) -> None:
    """Adapt one inherited group title and assign a stable v3 identifier."""
    matches = [group for group in root.findChildren(QGroupBox) if group.title() == old_title]
    if len(matches) != 1:
        raise RuntimeError(f"V3 expected exactly one group titled {old_title!r}; found {len(matches)}.")
    matches[0].setTitle(new_title)
    matches[0].setObjectName(object_name)


def _grid_cell_containing(root: QWidget, field: QWidget) -> tuple[QGridLayout, int, int]:
    """Find the grid cell that owns *field*, including tooltip wrappers."""
    layouts = []
    root_layout = root.layout()
    if isinstance(root_layout, QGridLayout):
        layouts.append(root_layout)
    layouts.extend(root.findChildren(QGridLayout))
    matches: list[tuple[int, QGridLayout, int, int]] = []
    for layout in layouts:
        for index in range(layout.count()):
            item = layout.itemAt(index)
            widget = item.widget()
            if widget is not None and (widget is field or widget.isAncestorOf(field)):
                row, column, _row_span, _column_span = layout.getItemPosition(index)
                distance = 0
                candidate: QWidget | None = field
                while candidate is not None and candidate is not widget:
                    distance += 1
                    candidate = candidate.parentWidget()
                matches.append((distance, layout, row, column))
    if matches:
        _distance, layout, row, column = min(matches, key=lambda match: match[0])
        return layout, row, column
    raise RuntimeError(f"V3 could not locate the grid cell for {field!r}.")


def _adapt_grid_caption(
    root: QWidget,
    field: QWidget,
    new_text: str,
    object_name: str,
    *,
    label_row_offset: int = 0,
    label_column: int = 0,
) -> None:
    """Adapt a caption by its bound field and grid position, not inherited text."""
    layout, field_row, _field_column = _grid_cell_containing(root, field)
    item = layout.itemAtPosition(field_row + label_row_offset, label_column)
    label = item.widget() if item is not None else None
    if not isinstance(label, QLabel):
        raise RuntimeError(f"V3 expected a QLabel associated with {field!r}.")
    label.setText(new_text)
    label.setObjectName(object_name)


def _adapt_form_caption(
    form: QFormLayout,
    field: QWidget,
    new_text: str,
    object_name: str,
) -> None:
    """Adapt a form caption through its field, including an inherited wrapper."""
    candidate: QWidget | None = field
    while candidate is not None:
        label = form.labelForField(candidate)
        if isinstance(label, QLabel):
            label.setText(new_text)
            label.setObjectName(object_name)
            return
        candidate = candidate.parentWidget()
    raise RuntimeError(f"V3 could not locate the form caption for {field!r}.")


class InitializationDialogV3(InitializationDialog):
    """Task-grouped v3 presentation of v2's shared initialization state."""

    def __init__(self, parent: QWidget, start_callback) -> None:
        super().__init__(parent, start_callback)
        _rename_unique_text_widget(
            self,
            QPushButton,
            "Initialize",
            "Initialize selected devices",
            "v3InitializeSelectedDevicesButton",
        )

    def _hardware_details_group(self, window: QWidget) -> QGroupBox:
        group = QGroupBox("Hardware resources and references")
        layout = QVBoxLayout(group)
        sections = QTabWidget()
        sections.setObjectName("v3InitializationDetails")

        resources = QWidget()
        resources_form = QFormLayout(resources)
        resources_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        resources_form.addRow("Piezo device serial number", window.thorlabs_apt_serial)
        resources_form.addRow("Valve serial port", window.valve_resource)
        resources_form.addRow("Cetoni configuration path", window.cetoni_config_path)
        window.tec_port.setToolTip(
            "Serial resource for the real TEC adapter. Real TEC operation remains unapproved; "
            "keep TEC simulated unless a reviewed procedure explicitly authorizes real use."
        )
        resources_form.addRow("TEC serial resource", window.tec_port)
        window._add_tooltip_icons(resources_form)

        vendor_paths = QWidget()
        vendor_form = QFormLayout(vendor_paths)
        vendor_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        vendor_form.addRow("Qmix SDK Python path", self._mark_unwired_stub(window.qmix_sdk_python_path))
        vendor_form.addRow("Qmix SDK runtime path", self._mark_unwired_stub(window.qmix_qmixsdk_path))
        note = QLabel("Reference paths only; the runtime does not read these fields.")
        note.setWordWrap(True)
        vendor_form.addRow(note)
        window._add_tooltip_icons(vendor_form)

        legacy = QWidget()
        legacy_form = QFormLayout(legacy)
        legacy_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        legacy_form.addRow("Z-stage backend", self._mark_unwired_stub(window.z_backend))
        legacy_form.addRow("Prior VISA resource", self._mark_unwired_stub(window.prior_resource))
        legacy_form.addRow("Thorlabs/APT backend", self._mark_unwired_stub(window.thorlabs_apt_backend))
        legacy_form.addRow("Discovery-only mode", self._mark_unwired_stub(window.thorlabs_apt_discovery_only))
        legacy_note = QLabel("Retained for migration reference; the runtime does not use these fields.")
        legacy_note.setWordWrap(True)
        legacy_form.addRow(legacy_note)
        window._add_tooltip_icons(legacy_form)

        sections.addTab(resources, "Connections")
        sections.addTab(vendor_paths, "Reference paths")
        sections.addTab(legacy, "Retained fields")
        layout.addWidget(sections)
        return group


class MainWindowV3(MainWindowV2):
    """Tracked, opt-in layout evolution of v2 using the same application runtime."""

    _PANEL_DISPLAY_NAMES: dict[str, str] = {"PumpValve": "Pump & Valve", "ZScan": "Z-Scan"}
    _WFG_PREVIEW_CHANNEL_LABELS: tuple[str, str] = ("AD2 channel 0", "AD2 channel 1")
    _MANUAL_PANEL_INITIAL_SIZES = {
        "WFG": (900, 760),
        "MSO": (820, 680),
        "PumpValve": (820, 680),
        "Camera": (860, 700),
        "ZScan": (820, 440),
    }
    _MANUAL_PANEL_MINIMUM_SIZES = {
        "WFG": (760, 620),
        "MSO": (720, 560),
        "PumpValve": (700, 540),
        "Camera": (720, 560),
        "ZScan": (700, 360),
    }

    def __init__(self, app: Application | None = None) -> None:
        super().__init__(app=app)
        self.setWindowTitle("Thermo Acoustic Streaming - UI v3 (shared hardware runtime)")
        self.connection_button.setText("Initialize hardware")
        self.connection_button.setStyleSheet("")
        self.connection_button.setToolTip(
            "Open device selection, simulation options, and initialization progress."
        )
        self.resize(1440, 900)

    @staticmethod
    def _make_status_dot(device_label: str) -> QLabel:
        """Use a real Unicode status marker instead of v2's mojibake text."""
        dot = QLabel("\u25cf")
        dot.setFixedWidth(14)
        dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dot.setStyleSheet("color: gray;")
        dot.setToolTip(f"{device_label}: disabled")
        return dot

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

        planning = QWidget()
        planning_layout = QHBoxLayout(planning)
        planning_layout.setContentsMargins(0, 0, 0, 0)
        planning_layout.addWidget(self._v3_experiment_identity_group(), 1)
        planning_layout.addWidget(self._v3_experiment_plan_group(), 2)
        workspace_layout.addWidget(planning, 0)

        operational = QWidget()
        operational_layout = QHBoxLayout(operational)
        operational_layout.setContentsMargins(0, 0, 0, 0)
        setup = QWidget()
        setup_layout = QVBoxLayout(setup)
        setup_layout.setContentsMargins(0, 0, 0, 0)
        setup_layout.addWidget(self._v3_one_repeat_timing_plan(), 0)
        setup_layout.addWidget(self._v3_setup_tabs(), 1)
        operational_layout.addWidget(setup, 1)
        operational_layout.addWidget(runtime, 0)
        workspace_layout.addWidget(operational, 1)
        workspace_layout.addWidget(self._v3_run_control_group(), 0)

        root_layout.addWidget(workspace, 1)
        self._connect_v3_relationship_refresh()
        self._refresh_v3_relationships()

    def _build_menu_bar(self) -> None:
        super()._build_menu_bar()
        replacements = {
            "menuSaveSettingsAction": (
                "Save UI settings",
                "Save the current UI control values to the local settings file.",
            ),
            "menuLoadSettingsAction": (
                "Load UI settings",
                "Load UI control values from the local settings file.",
            ),
        }
        actions = {action.objectName(): action for action in self.menuBar().actions()}
        for object_name, (text, tooltip) in replacements.items():
            action = actions.get(object_name)
            if action is None:
                raise RuntimeError(f"V3 expected inherited menu action {object_name!r}.")
            action.setText(text)
            action.setToolTip(tooltip)
            action.setStatusTip(tooltip)

    def _ensure_initialization_dialog(self):
        created = self._initialization_dialog is None
        if created:
            self._initialization_dialog = InitializationDialogV3(self, self._start_initialize)
        dialog = self._initialization_dialog
        assert dialog is not None
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
            root_layout = dialog.layout()
            if root_layout is not None:
                root_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
            for group in dialog.findChildren(QGroupBox):
                group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
            dialog.setMinimumSize(760, 560)
            dialog.resize(900, 620)
        return dialog

    def _ensure_manual_panel(self, panel_name: str):
        created = panel_name not in self._manual_panels
        dialog = super()._ensure_manual_panel(panel_name)
        if created:
            dialog.setMinimumSize(*self._MANUAL_PANEL_MINIMUM_SIZES[panel_name])
            dialog.resize(*self._MANUAL_PANEL_INITIAL_SIZES[panel_name])
        return dialog

    def _v3_connection_strip(self) -> QGroupBox:
        group = QGroupBox("Hardware connection status")
        group.setObjectName("v3ConnectionStrip")
        layout = QHBoxLayout(group)
        self._v3_connection_values: dict[str, QLabel] = {}
        for name in ("AD2", "Camera", "Pump", "Valve", "TEC"):
            layout.addWidget(QLabel(name))
            value = QLabel("Not connected")
            value.setObjectName(f"v3ConnectionStatus{name}")
            value.setMinimumWidth(82)
            self._v3_connection_values[name] = value
            layout.addWidget(value)
        layout.addStretch(1)
        return group

    def _v3_experiment_identity_group(self) -> QGroupBox:
        group = QGroupBox("Series identity and inner repeats")
        group.setObjectName("v3ExperimentIdentity")
        grid = QGridLayout(group)
        browse = QPushButton("Browse...")
        browse.clicked.connect(lambda: self._browse_folder(self.series_path))
        repeats_host = QWidget()
        repeats_layout = QHBoxLayout(repeats_host)
        repeats_layout.setContentsMargins(0, 0, 0, 0)
        self._v3_repeats_layout = repeats_layout
        self._v3_series_relationship_summary = QLabel()
        self._v3_series_relationship_summary.setObjectName("v3SeriesRelationshipSummary")
        self._v3_series_relationship_summary.setWordWrap(True)
        grid.addWidget(QLabel("Series path"), 0, 0)
        grid.addWidget(self._wrap_with_tooltip_icon(self.series_path), 0, 1)
        grid.addWidget(browse, 0, 2)
        repeats_caption = QLabel("Series repeats")
        repeats_caption.setObjectName("v3ExperimentRepeatsCaption")
        grid.addWidget(repeats_caption, 1, 0)
        grid.addWidget(repeats_host, 1, 1)
        grid.addWidget(self._v3_series_relationship_summary, 2, 0, 1, 3)
        grid.setColumnStretch(1, 1)
        return group

    def _v3_experiment_plan_group(self) -> QGroupBox:
        group = QGroupBox("Derived experiment plan — configured state")
        group.setObjectName("v3ExperimentPlan")
        form = QFormLayout(group)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self._v3_axis_summary = QLabel()
        self._v3_axis_summary.setObjectName("v3ExperimentAxisSummary")
        self._v3_repeat_workflow = QLabel()
        self._v3_repeat_workflow.setObjectName("v3RepeatWorkflowSummary")
        self._v3_camera_request_summary = QLabel()
        self._v3_camera_request_summary.setObjectName("v3RequestedCameraSummary")
        self._v3_requirements_summary = QLabel()
        self._v3_requirements_summary.setObjectName("v3HardwareRequirementsSummary")
        self._v3_plan_warnings = QLabel()
        self._v3_plan_warnings.setObjectName("v3PreRunWarnings")
        for label in (
            self._v3_axis_summary,
            self._v3_repeat_workflow,
            self._v3_camera_request_summary,
            self._v3_requirements_summary,
            self._v3_plan_warnings,
        ):
            label.setWordWrap(True)
        form.addRow("Acquisition axes", self._v3_axis_summary)
        form.addRow("Per-repeat order", self._v3_repeat_workflow)
        form.addRow("Camera request", self._v3_camera_request_summary)
        form.addRow("Pre-run readiness", self._v3_requirements_summary)
        form.addRow("Review", self._v3_plan_warnings)
        return group

    def _v3_run_control_group(self) -> QGroupBox:
        group = QGroupBox("Review and run")
        group.setObjectName("v3PrimaryRunControl")
        layout = QHBoxLayout(group)
        start = QPushButton("Start experiment")
        start.setObjectName("v3StartExperimentButton")
        start.setMinimumHeight(44)
        start.setToolTip("Runs with the currently initialized backends after shared validation.")
        start.clicked.connect(self._v3_start_experiment_with_shared_preflight)
        stop = QPushButton("Request graceful stop")
        stop.setObjectName("v3RequestGracefulStopButton")
        stop.setMinimumHeight(44)
        stop.setStyleSheet("color: darkred; font-weight: bold;")
        stop.setToolTip(
            "Stops after the current repeat, or after the current temperature point during a TEC scan. "
            "It does not stop hardware in the middle of an operation."
        )
        stop.clicked.connect(self._abort)
        note = QLabel(
            "Start uses the plan above. Graceful stop finishes the active unit before halting; "
            "it is not an emergency hardware stop."
        )
        note.setWordWrap(True)
        note.setMaximumWidth(620)
        layout.addWidget(start)
        layout.addWidget(stop)
        layout.addWidget(note, 1)
        return group

    def _v3_setup_tabs(self) -> QTabWidget:
        tabs = QTabWidget()
        tabs.setObjectName("v3SetupTabs")

        ad2_content = QWidget()
        ad2_layout = QVBoxLayout(ad2_content)
        ad2_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        ad2_layout.addWidget(self._v3_ad2_output_group())
        tabs.addTab(self._v3_scroll_page(ad2_content, "v3Ad2SetupScroll"), "AD2 Output")

        camera_content = QWidget()
        camera_layout = QVBoxLayout(camera_content)
        camera_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        camera_layout.addWidget(self._v2_acquisition_group())
        tabs.addTab(self._v3_scroll_page(camera_content, "v3CameraSetupScroll"), "Camera")

        fluidics_content = QWidget()
        fluidics_layout = QVBoxLayout(fluidics_content)
        fluidics_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        fluidics_note = QLabel(
            "Optional post-capture sequence: valve P01 → pump dispense → valve P02 → configured wait. "
            "The commands are sequential; physical P01/P02 fluid routing remains bench-unverified. "
            "Capacity checks use the syringe selected in the manual Pump & Valve panel; applying that "
            "geometry to the pump still requires its explicit Configure syringe action."
        )
        fluidics_note.setObjectName("v3FluidicsWorkflowNote")
        fluidics_note.setWordWrap(True)
        fluidics_note.setMaximumWidth(520)
        fluidics_layout.addWidget(fluidics_note)
        flush_group = self._experiment_flush_group()
        # Preserve v2's concise, safety-relevant explanation at the control
        # itself without adding another block of inline text to v3's layout.
        flush_group.setToolTip(
            "Sequential, not concurrent: valve switches to position 1, then the pump moves, "
            "then the valve switches to position 2. The pump is idle during each valve switch."
        )
        fluidics_layout.addWidget(flush_group)
        fluidics_layout.addWidget(self._v3_flush_summary_group())
        fluidics_layout.addStretch(1)
        tabs.addTab(self._v3_scroll_page(fluidics_content, "v3FluidicsSetupScroll"), "Fluidics")

        advanced_content = QWidget()
        advanced_layout = QVBoxLayout(advanced_content)
        advanced_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        advanced_layout.addWidget(self._experiment_temperature_group())
        advanced_layout.addStretch(1)
        tabs.addTab(self._v3_scroll_page(advanced_content, "v3AdvancedSetupScroll"), "Temperature scan")
        return tabs

    def _v3_ad2_output_group(self) -> QGroupBox:
        group = QGroupBox("Experiment AD2 output")
        group.setObjectName("v3ExperimentAd2Output")
        layout = QVBoxLayout(group)
        channels = QTabWidget()
        channels.setObjectName("v3ExperimentAd2Channels")
        for index, state in enumerate(self.exp_ad2_channels):
            title = "Channel 0" if index == 0 else "Channel 1 — role unverified"
            channels.addTab(self._v3_ad2_channel_page(state, index), title)
        layout.addWidget(channels)
        return group

    def _v3_ad2_channel_page(self, state: dict[str, object], index: int) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        carrier = QGroupBox("Base carrier waveform" if index == 0 else "Carrier waveform")
        carrier_form = QFormLayout(carrier)
        state["enable"].setText("Enabled")
        carrier_form.addRow("Channel output", state["enable"])
        carrier_form.addRow("Waveform", state["function"])
        carrier_form.addRow("Frequency (kHz)", state["frequency"])
        carrier_form.addRow("Amplitude (V)", state["amplitude"])
        carrier_form.addRow("Offset (V)", state["offset"])
        self._add_tooltip_icons(carrier_form)

        timing = QGroupBox("Timing and trigger")
        timing_form = QFormLayout(timing)
        timing_form.addRow("Start delay (s)", state["sec_wait"])
        timing_form.addRow("Run duration (s)", state["sec_run"])
        timing_form.addRow("Repeat count [0 = infinite]", state["repeat"])
        timing_form.addRow("Trigger source", state["trigger_source"])
        state["repeat_trigger"].setText("Enabled")
        timing_form.addRow("Re-arm trigger after each repeat", state["repeat_trigger"])
        self._add_tooltip_icons(timing_form)

        detail = QGroupBox("Waveform shape")
        detail_form = QFormLayout(detail)
        detail_form.addRow("Symmetry (%)", state["symmetry"])
        detail_form.addRow("Phase (deg)", state["phase"])
        self._add_tooltip_icons(detail_form)

        layout.addWidget(carrier)
        layout.addWidget(timing)
        layout.addWidget(detail)
        if index == 0:
            layout.addWidget(self._v3_frequency_program_group())
        else:
            role = QLabel(
                "AD2 analog channel 1 (LabVIEW Ch2). Independent analog output; physical apparatus "
                "role unverified. Timing is intentionally not linked to channel 0 or DIO1."
            )
            role.setObjectName("v3Channel1RoleNote")
            role.setWordWrap(True)
            layout.insertWidget(0, role)
        return page

    def _v3_frequency_program_group(self) -> QGroupBox:
        group = QGroupBox("Frequency program — channel 0")
        group.setObjectName("v3FrequencyProgram")
        layout = QVBoxLayout(group)
        hierarchy = QLabel(
            "Hierarchy: base carrier → optional FM sweep within each repeat → optional frequency-scan "
            "base-carrier override for each repeat."
        )
        hierarchy.setObjectName("v3FrequencyProgramHierarchy")
        hierarchy.setWordWrap(True)
        layout.addWidget(hierarchy)
        self._v3_frequency_program_summary = QLabel()
        self._v3_frequency_program_summary.setObjectName("v3FrequencyProgramSummary")
        self._v3_frequency_program_summary.setWordWrap(True)
        layout.addWidget(self._v3_frequency_program_summary)
        self._v3_frequency_scan_preview = QLabel()
        self._v3_frequency_scan_preview.setObjectName("v3FrequencyScanListPreview")
        self._v3_frequency_scan_preview.setWordWrap(True)
        layout.addWidget(self._v3_frequency_scan_preview)

        modulation = QTabWidget()
        modulation.setObjectName("v3ModulationTabs")
        fm_page = QWidget()
        fm_layout = QVBoxLayout(fm_page)
        fm_note = QLabel(
            "Equivalent inputs: Start / Stop ↔ Center / Width. Editing either pair synchronizes the other."
        )
        fm_note.setObjectName("v3FmEquivalentInputsNote")
        fm_note.setWordWrap(True)
        fm_layout.addWidget(fm_note)
        fm_sweep = self._experiment_fm_sweep_group()
        fm_sweep.setTitle("FM sweep within a repeat")
        fm_layout.addWidget(fm_sweep)
        scan_page = QWidget()
        scan_layout = QVBoxLayout(scan_page)
        scan_note = QLabel(
            "Alternative inputs: Step Size > 0 derives Number of Frequencies; Step Size = 0 uses "
            "Number of Frequencies directly."
        )
        scan_note.setObjectName("v3ScanAlternativeInputsNote")
        scan_note.setWordWrap(True)
        scan_layout.addWidget(scan_note)
        frequency_scan = self._experiment_frequency_scan_group()
        frequency_scan.setTitle("Frequency scan across repeats")
        scan_form = frequency_scan.layout()
        if not isinstance(scan_form, QFormLayout):
            raise RuntimeError("V3 expected Frequency scan to use a form layout.")
        _adapt_form_caption(
            scan_form,
            self.exp_freq_scan_step_khz,
            "Step size (kHz) [0 = Count]",
            "v3FrequencyScanStepCaption",
        )
        self._v3_frequency_scan_input_mode = QComboBox()
        self._v3_frequency_scan_input_mode.setObjectName("v3FrequencyScanInputMode")
        self._v3_frequency_scan_input_mode.addItems(("Number of Frequencies", "Step Size"))
        self._v3_frequency_scan_input_mode.setToolTip(
            "Select which frequency-scan input drives the point count. Switching modes preserves "
            "the inactive mode's last value; Step Size remains the existing Python-only alternative."
        )
        self._v3_frequency_scan_saved_count = self.exp_freq_scan_count.value()
        self._v3_frequency_scan_saved_step_khz = self.exp_freq_scan_step_khz.value()
        self._v3_frequency_scan_input_mode.setCurrentIndex(
            1 if self.exp_freq_scan_step_khz.value() > 0 else 0
        )
        scan_form.insertRow(3, "Point-count input", self._v3_frequency_scan_input_mode)
        self._v3_frequency_scan_input_mode.currentIndexChanged.connect(
            self._switch_v3_frequency_scan_input_mode
        )
        self.exp_freq_scan_count.valueChanged.connect(self._remember_v3_frequency_scan_count)
        self.exp_freq_scan_step_khz.valueChanged.connect(self._remember_v3_frequency_scan_step)
        self._apply_v3_frequency_scan_input_mode()
        scan_layout.addWidget(frequency_scan)
        modulation.addTab(fm_page, "FM sweep")
        modulation.addTab(scan_page, "Frequency scan")
        layout.addWidget(modulation)
        return group

    def _v3_one_repeat_timing_plan(self) -> QGroupBox:
        group = QGroupBox("One-repeat AD2 timing plan (requested)")
        group.setObjectName("v3OneRepeatTimingPlan")
        grid = QGridLayout(group)
        for column, text in enumerate(("Output", "Start (s)", "Run (s)", "End (s)")):
            grid.addWidget(QLabel(text), 0, column)
        self._v3_timing_delta_header = QLabel("End delta vs CH0 (s)")
        self._v3_timing_delta_header.setObjectName("v3TimingDeltaHeader")
        grid.addWidget(self._v3_timing_delta_header, 0, 4)
        self._v3_timing_labels: dict[str, dict[str, QLabel]] = {}
        rows = (
            ("ch0", "WFG channel 0"),
            ("ch1", "WFG channel 1 (role unverified)"),
            ("dio1", "DIO1 request"),
        )
        for row, (key, title) in enumerate(rows, start=1):
            grid.addWidget(QLabel(title), row, 0)
            values: dict[str, QLabel] = {}
            for column, field in enumerate(("start", "run", "end", "delta"), start=1):
                label = QLabel("—")
                label.setObjectName(f"v3Timing{key.title()}{field.title()}")
                grid.addWidget(label, row, column)
                values[field] = label
            self._v3_timing_labels[key] = values
        self._v3_completion_budget = QLabel()
        self._v3_completion_budget.setObjectName("v3Ad2CompletionBudget")
        self._v3_completion_budget.setWordWrap(True)
        grid.addWidget(self._v3_completion_budget, 4, 0, 1, 5)
        self._v3_timing_anchor_note = QLabel()
        self._v3_timing_anchor_note.setObjectName("v3TimingAnchorNote")
        self._v3_timing_anchor_note.setWordWrap(True)
        grid.addWidget(self._v3_timing_anchor_note, 5, 0, 1, 5)
        return group

    def _derived_v3_frequency_scan_step_khz(self) -> float:
        count = max(int(self._v3_frequency_scan_saved_count), 1)
        span_khz = abs(
            float(self.exp_freq_scan_stop_khz.value()) - float(self.exp_freq_scan_start_khz.value())
        )
        if count > 1 and span_khz > 0:
            return span_khz / (count - 1)
        return max(span_khz * 2.0 + self.exp_freq_scan_step_khz.singleStep(),
                   self.exp_freq_scan_step_khz.singleStep())

    def _apply_v3_frequency_scan_input_mode(self) -> None:
        scan_enabled = self.exp_freq_scan_enable.isChecked()
        use_step_size = self._v3_frequency_scan_input_mode.currentIndex() == 1
        self.exp_freq_scan_count.setEnabled(scan_enabled and not use_step_size)
        self.exp_freq_scan_step_khz.setEnabled(scan_enabled and use_step_size)

    def _apply_v3_context_state(self, _value=None) -> None:
        """Expose which configured values participate in the selected mode."""
        fm_enabled = self.exp_sweep_enable.isChecked()
        for field in (
            self.exp_sweep_start_khz,
            self.exp_sweep_stop_khz,
            self.exp_sweep_center_khz,
            self.exp_sweep_width_khz,
            self.exp_sweep_time_ms,
            self.exp_sweep_type,
        ):
            field.setEnabled(fm_enabled)

        scan_enabled = self.exp_freq_scan_enable.isChecked()
        for field in (
            self.exp_freq_scan_start_khz,
            self.exp_freq_scan_stop_khz,
            self._v3_frequency_scan_input_mode,
        ):
            field.setEnabled(scan_enabled)
        self._apply_v3_frequency_scan_input_mode()

        flush_enabled = self.exp_flush_enabled.isChecked()
        for field in (self.exp_flush_flowrate, self.exp_flush_volume, self.exp_wait_after_flush):
            field.setEnabled(flush_enabled)

        tec_enabled = self.exp_tec_scan_enable.isChecked()
        self._v3_tec_targets_group.setEnabled(tec_enabled)
        self._v3_tec_stability_group.setEnabled(tec_enabled)
        self._v3_tec_advanced_group.setEnabled(tec_enabled)
        self.exp_tec_points_ch2.setEnabled(tec_enabled and not self.exp_tec_lock_channels.isChecked())

        external_camera_trigger = self.dcam_source.currentText() == "External"
        self.external_polarity.setEnabled(external_camera_trigger)
        self.external_delay.setEnabled(external_camera_trigger)

    def _switch_v3_frequency_scan_input_mode(self, index: int) -> None:
        use_step_size = index == 1
        if use_step_size:
            self._v3_frequency_scan_saved_count = self.exp_freq_scan_count.value()
            step_khz = float(self._v3_frequency_scan_saved_step_khz)
            if step_khz <= 0:
                step_khz = self._derived_v3_frequency_scan_step_khz()
            self.exp_freq_scan_step_khz.setValue(step_khz)
        else:
            current_step = self.exp_freq_scan_step_khz.value()
            if current_step > 0:
                self._v3_frequency_scan_saved_step_khz = current_step
            self.exp_freq_scan_step_khz.setValue(0.0)
            self.exp_freq_scan_count.setValue(self._v3_frequency_scan_saved_count)
        self._apply_v3_frequency_scan_input_mode()

    def _remember_v3_frequency_scan_count(self, value: int) -> None:
        if self._v3_frequency_scan_input_mode.currentIndex() == 0:
            self._v3_frequency_scan_saved_count = value

    def _remember_v3_frequency_scan_step(self, value: float) -> None:
        if value > 0:
            self._v3_frequency_scan_saved_step_khz = value
            if self._v3_frequency_scan_input_mode.currentIndex() == 0:
                self._v3_frequency_scan_input_mode.setCurrentIndex(1)
        elif self._v3_frequency_scan_input_mode.currentIndex() == 1:
            self._v3_frequency_scan_input_mode.setCurrentIndex(0)

    def _v3_flush_summary_group(self) -> QGroupBox:
        group = QGroupBox("Derived flush plan")
        group.setObjectName("v3FlushDerivedSummary")
        form = QFormLayout(group)
        self._v3_flush_movement = QLabel()
        self._v3_flush_timeout = QLabel()
        self._v3_flush_capacity = QLabel()
        self._v3_flush_fill_margin = QLabel()
        form.addRow("Requested pump movement", self._v3_flush_movement)
        form.addRow("Centralized movement timeout", self._v3_flush_timeout)
        form.addRow("Selected syringe capacity", self._v3_flush_capacity)
        form.addRow("Tracked fill after dispense", self._v3_flush_fill_margin)
        return group

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
        # Keep monitoring readable when the setup column asks for more room.
        # Without a minimum, Qt collapses this column to roughly 130 px and
        # silently clips the waveform/status content behind a disabled
        # horizontal scrollbar.
        area.setMinimumWidth(330)
        area.setMaximumWidth(360)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self._v2_waveform_group())
        layout.addWidget(self._global_status_panel())
        area.setWidget(content)
        return area

    def _experiment_temperature_group(self) -> QGroupBox:
        """Build v3 TEC controls, replacing v1 without calling its base method.

        Future additions to v1's method of the same name do not appear here
        automatically and require an explicit v3 review.
        """
        group = QGroupBox("TEC temperature scan")
        group.setObjectName("v3TecTemperatureScan")
        layout = QVBoxLayout(group)
        note = QLabel("Simulated by default. Real TEC operation remains unapproved.")
        note.setWordWrap(True)
        note.setMaximumWidth(520)
        layout.addWidget(note)
        layout.addWidget(self.exp_tec_scan_enable)
        self._v3_tec_axis_summary = QLabel()
        self._v3_tec_axis_summary.setObjectName("v3TecAxisSummary")
        self._v3_tec_axis_summary.setWordWrap(True)
        layout.addWidget(self._v3_tec_axis_summary)

        self._v3_tec_targets_group = QGroupBox("Temperature targets")
        self._v3_tec_targets_group.setObjectName("v3TecTargets")
        targets = QFormLayout(self._v3_tec_targets_group)
        targets.addRow("Channel 1 points (°C)", self.exp_tec_points)
        targets.addRow("Channel relationship", self.exp_tec_lock_channels)
        targets.addRow("Channel 2 points (°C)", self.exp_tec_points_ch2)
        self._add_tooltip_icons(targets)

        self._v3_tec_stability_group = QGroupBox("Stabilization criteria")
        self._v3_tec_stability_group.setObjectName("v3TecStabilityCriteria")
        stability = QFormLayout(self._v3_tec_stability_group)
        stability.addRow("Target tolerance (°C)", self.exp_tec_tolerance_c)
        stability.addRow("Minimum in-tolerance time (s)", self.exp_tec_min_settle_s)
        self._add_tooltip_icons(stability)

        self._v3_tec_advanced_group = QGroupBox("Advanced wait and polling policy")
        self._v3_tec_advanced_group.setObjectName("v3TecAdvancedPolicy")
        advanced = QFormLayout(self._v3_tec_advanced_group)
        advanced.addRow("Maximum wait per target (s)", self.exp_tec_max_wait_s)
        advanced.addRow("Status poll interval (s)", self.exp_tec_poll_interval_s)
        advanced.addRow("Post-stabilization hold (s)", self.exp_tec_post_stable_hold_s)
        self._add_tooltip_icons(advanced)

        readback = QGroupBox("Cached TEC readback")
        readback.setObjectName("v3TecCachedReadback")
        readback_form = QFormLayout(readback)
        self._v3_tec_readback_labels: dict[int, QLabel] = {}
        for channel in (1, 2):
            value = QLabel("No cached readback")
            value.setObjectName(f"v3TecChannel{channel}Readback")
            value.setWordWrap(True)
            self._v3_tec_readback_labels[channel] = value
            readback_form.addRow(f"Channel {channel}", value)
        readback_note = QLabel("Display only: refreshing the UI does not query or command the TEC.")
        readback_note.setWordWrap(True)
        readback_form.addRow(readback_note)

        layout.addWidget(self._v3_tec_targets_group)
        layout.addWidget(self._v3_tec_stability_group)
        layout.addWidget(self._v3_tec_advanced_group)
        layout.addWidget(readback)
        return group

    def _v2_status_progress_group(self) -> QGroupBox:
        group = super()._v2_status_progress_group()
        group.setTitle("Experiment status and progress")
        # Bind these inherited display captions to queue_count's stable grid,
        # not to v2's presentation text. V2 wording can evolve without
        # breaking construction of this deliberately divergent surface.
        queue_grid, _row, _column = _grid_cell_containing(group, self.queue_count)
        captions = (
            (0, "Elapsed time", "v3ElapsedTimeCaption"),
            (1, "Estimated time remaining", "v3RemainingTimeCaption"),
            (2, "Runs remaining", "v3RunsRemainingCaption"),
        )
        for column, text, object_name in captions:
            item = queue_grid.itemAtPosition(0, column)
            label = item.widget() if item is not None else None
            if not isinstance(label, QLabel):
                raise RuntimeError(f"V3 expected the inherited status caption in column {column}.")
            label.setText(text)
            label.setObjectName(object_name)
        return group

    def _v2_acquisition_group(self) -> QGroupBox:
        group = super()._v2_acquisition_group()
        group.setTitle("Experiment acquisition")
        # Use the shared field objects as the binding contract. The previous
        # exact-caption adapter broke whenever v1/v2 clarified their wording.
        captions = (
            (self.exp_camera_fps, "DIO1 pulse rate (camera FPS)", "v3CameraFrameRateCaption"),
            (self.exp_camera_start, "Fixed DIO1 pulse start delay (s)", "v3CameraStartDelayCaption"),
            (self.exp_frames, "Frames per repeat", "v3FramesPerRepeatCaption"),
            (self.global_exposure, "Request global exposure reset", "v3GlobalExposureCaption"),
            (
                self.dynamic_camera_start,
                "Use per-repeat DIO1 pulse delays",
                "v3DynamicCameraStartCaption",
            ),
        )
        for field, text, object_name in captions:
            _adapt_grid_caption(group, field, text, object_name)

        repeats_grid, repeats_row, repeats_column = _grid_cell_containing(group, self.exp_repeats)
        repeats_item = repeats_grid.itemAtPosition(repeats_row, repeats_column)
        repeats_container = repeats_item.widget() if repeats_item is not None else None
        repeats_caption_item = repeats_grid.itemAtPosition(repeats_row, 0)
        repeats_caption = repeats_caption_item.widget() if repeats_caption_item is not None else None
        if repeats_container is None or not isinstance(repeats_caption, QLabel):
            raise RuntimeError("V3 could not move the inherited Repeats field into series controls.")
        repeats_grid.removeWidget(repeats_container)
        repeats_grid.removeWidget(repeats_caption)
        self.exp_repeats.setParent(None)
        if repeats_container is not self.exp_repeats:
            repeats_container.deleteLater()
        repeats_caption.deleteLater()
        self._v3_repeats_layout.addWidget(self._wrap_with_tooltip_icon(self.exp_repeats))

        dynamic_wrapper = self.dynamic_camera_start.parentWidget()
        camera_start_group = dynamic_wrapper.parentWidget() if dynamic_wrapper is not None else None
        if not isinstance(camera_start_group, QGroupBox):
            raise RuntimeError("V3 could not locate the per-repeat camera-start group.")
        camera_start_group.setTitle("Per-repeat DIO1 pulse delays (s)")
        camera_start_group.setObjectName("v3PerRepeatCameraStartGroup")
        self.global_exposure.setToolTip(
            "On requests GLOBALRESET. Off leaves the current DCAM property unchanged because the "
            "LabVIEW false-case mapping is unresolved. It may only take effect with compatible "
            "camera trigger settings."
        )
        self.dynamic_camera_start.setToolTip(
            "When enabled, each experiment repeat uses its corresponding DIO1 pulse-train sec_wait "
            "value instead of the fixed delay. The list has 10 slots; its physical alignment with "
            "camera exposure remains bench-unverified."
        )
        summary = QGroupBox("DIO1 timing request and camera feasibility")
        summary.setObjectName("v3DioTimingSummary")
        summary_form = QFormLayout(summary)
        self._v3_dio_duration = QLabel()
        self._v3_dio_start_source = QLabel()
        self._v3_dio_slot_budget = QLabel()
        self._v3_camera_feasibility = QLabel()
        self._v3_camera_feasibility.setWordWrap(True)
        summary_form.addRow("Derived DIO1 run duration", self._v3_dio_duration)
        summary_form.addRow("Active start source", self._v3_dio_start_source)
        summary_form.addRow("Per-repeat slot budget", self._v3_dio_slot_budget)
        summary_form.addRow("Existing run-start check", self._v3_camera_feasibility)
        acquisition_grid = group.layout()
        if not isinstance(acquisition_grid, QGridLayout):
            raise RuntimeError("V3 expected Experiment acquisition to use a grid layout.")
        acquisition_grid.addWidget(summary, 6, 0, 1, 3)
        self._v3_sync_uncertainty = QLabel(
            "Synchronization uncertainty: automated camera trigger is Internal. DIO1-to-exposure timing "
            "has not been bench verified; this panel shows the requested DIO1 window, not confirmed exposure timing."
        )
        self._v3_sync_uncertainty.setObjectName("v3SyncUncertaintyBanner")
        self._v3_sync_uncertainty.setWordWrap(True)
        self._v3_sync_uncertainty.setStyleSheet("color: darkorange; font-weight: bold;")
        acquisition_grid.addWidget(self._v3_sync_uncertainty, 7, 0, 1, 3)
        return group

    def _connect_v3_relationship_refresh(self) -> None:
        value_widgets = [
            self.exp_repeats,
            self.exp_frames,
            self.exp_camera_fps,
            self.exp_camera_start,
            self.exp_exposure_ms,
            self.exp_freq_scan_count,
            self.exp_freq_scan_step_khz,
            self.exp_freq_scan_start_khz,
            self.exp_freq_scan_stop_khz,
            self.exp_flush_flowrate,
            self.exp_flush_volume,
            self.exp_wait_after_flush,
            self.custom_syringe_volume_ml,
            *self.camera_start_array,
        ]
        for state in self.exp_ad2_channels:
            value_widgets.extend((state["sec_wait"], state["sec_run"]))
        for widget in value_widgets:
            widget.valueChanged.connect(self._refresh_v3_relationships)
        for checkbox in (
            self.dynamic_camera_start,
            self.exp_freq_scan_enable,
            self.exp_sweep_enable,
            self.exp_flush_enabled,
            self.exp_tec_scan_enable,
            self.exp_tec_lock_channels,
            *(state["enable"] for state in self.exp_ad2_channels),
        ):
            checkbox.toggled.connect(self._refresh_v3_relationships)
        self.syringe.currentTextChanged.connect(self._refresh_v3_relationships)
        self.dcam_source.currentTextChanged.connect(self._refresh_v3_relationships)
        self.series_path.textChanged.connect(self._refresh_v3_relationships)
        self.exp_tec_points.textChanged.connect(self._refresh_v3_relationships)
        self.exp_tec_points_ch2.textChanged.connect(self._refresh_v3_relationships)

    @staticmethod
    def _v3_seconds(value: float) -> str:
        return f"{value:.3f}"

    @staticmethod
    def _v3_compact_values(values: list[float], *, limit: int = 7) -> str:
        rendered = [f"{value:g}" for value in values]
        if len(rendered) <= limit:
            return ", ".join(rendered)
        head = limit // 2
        tail = limit - head
        return ", ".join((*rendered[:head], "…", *rendered[-tail:]))

    def _v3_experiment_request(self) -> ExperimentRequest:
        try:
            frequencies = tuple(self._experiment_frequency_scan_list_hz())
        except (TypeError, ValueError):
            frequencies = ()
        temperature_targets: list[tuple[tuple[int, float], ...]] = []
        if self.exp_tec_scan_enable.isChecked():
            try:
                temperature_series = self._temperature_series()
                for index in range(len(temperature_series.temperature_points_c)):
                    target = temperature_series.target_at(index)
                    values = (
                        {channel: float(target) for channel in self.app.tec.channels}
                        if isinstance(target, float)
                        else target
                    )
                    temperature_targets.append(tuple(sorted(values.items())))
            except ValueError:
                temperature_targets = []
        return ExperimentRequest(
            output_path=Path(self.series_path.text()),
            repeats_per_group=self.exp_repeats.value(),
            frequency_scan_enabled=self.exp_freq_scan_enable.isChecked(),
            frequency_values_hz=frequencies,
            camera_fps=float(self.exp_camera_fps.value()),
            frames=self.exp_frames.value(),
            camera_start_s=tuple(widget.value() for widget in self.camera_start_array),
            dynamic_camera_start=self.dynamic_camera_start.isChecked(),
            fm_sweep_enabled=self.exp_sweep_enable.isChecked(),
            channel0_output_selected=self.exp_ad2_channels[0]["enable"].isChecked(),
            flush_enabled=self.exp_flush_enabled.isChecked(),
            tec_scan_enabled=self.exp_tec_scan_enable.isChecked(),
            temperature_targets_c=tuple(temperature_targets),
            device_modes=(
                ("ad2", self.app.ad2.enabled, isinstance(self.app.ad2, SimulatedAD2Sdk)),
                ("camera", self.app.camera.enabled, self.app.camera.simulate),
                ("pump", self.app.pump.enabled, self.app.pump.simulate),
                ("valve", self.app.valve.enabled, self.app.valve.simulate),
                ("tec", self.app.tec.enabled, self.app.tec.simulate),
            ),
        )

    def _v3_shadow_build_result(self) -> BuildResult:
        request = self._v3_experiment_request()
        try:
            if request.tec_scan_enabled:
                _temperature_series, groups, total_frames, _config = self._build_temperature_experiment_groups(
                    request.output_path
                )
                plan = run_plan_from_existing_series(request.output_path, groups, total_frames=total_frames)
            else:
                series, total_frames, _config = self._build_experiment_series(request.output_path)
                plan = run_plan_from_existing_series(request.output_path, series, total_frames=total_frames)
        except (IndexError, TypeError, ValueError) as exc:
            return blocking_build_result(request, exc)
        return build_result_from_existing_plan(request, plan, self.app.runtime_evidence_snapshot())

    def _v3_start_experiment_with_shared_preflight(self) -> None:
        result = self._v3_shadow_build_result()
        if result.preflight.blocking_issues:
            message = "; ".join(issue.message for issue in result.preflight.blocking_issues)
            self.app.emit_event(
                RuntimeEvent.create(
                    severity=RuntimeEventSeverity.BLOCKING_CONFIGURATION,
                    subsystem="experiment",
                    operation="preflight",
                    message=message,
                    may_continue=False,
                    operator_next_action="Correct the reported configuration before starting.",
                ),
                update_legacy_status=False,
            )
        # Shadow-only in this milestone: the inherited authoritative Start
        # path rebuilds and executes exactly as before.
        self._start_experiment()

    def _render_v3_shared_preflight(self, result: BuildResult) -> None:
        self._v3_last_build_result = result
        preflight = result.preflight
        axes = dict(preflight.experiment_axes)
        temperature_count = axes.get("temperature", 1)
        repeats = axes.get("repeat", result.request.repeats_per_group)
        total_runs = len(result.plan.experiments) if result.plan is not None else temperature_count * repeats
        scan_text = (
            f"frequency list maps {len(result.request.frequency_values_hz)} carrier value(s) one-to-one to repeat indices"
            if result.request.frequency_scan_enabled
            else "no frequency-list mapping"
        )
        outer = f"TEC temperature: {temperature_count} point(s)" if result.request.tec_scan_enabled else "No outer TEC axis"
        inner = (
            f"{repeats} repeat(s) per temperature; {total_runs} acquisition run(s) total"
            if result.request.tec_scan_enabled
            else f"{repeats} acquisition repeat(s)"
        )
        self._v3_axis_summary.setText(f"{outer}; {inner}; {scan_text}.")
        self._v3_tec_axis_summary.setText(
            f"Outer axis: {temperature_count} temperature point(s) × {repeats} repeats = {total_runs} acquisition runs."
            if result.request.tec_scan_enabled and not preflight.blocking_issues
            else (
                "Temperature target plan is blocked by shared preflight."
                if result.request.tec_scan_enabled
                else "Disabled: no outer temperature axis."
            )
        )
        self._v3_tec_axis_summary.setStyleSheet(
            "color: darkred; font-weight: bold;" if preflight.blocking_issues else ""
        )

        snapshot = self.app.runtime_evidence_snapshot()
        evidence_by_name = {
            "camera": snapshot.camera,
            "pump": snapshot.pump,
            "valve": snapshot.valve,
            "tec": snapshot.tec,
        }
        def device_state(name: str) -> str:
            if name in preflight.disabled_devices:
                return "DISABLED — current runtime skips this subsystem"
            if name in preflight.simulated_devices:
                return "SIMULATED — no physical evidence"
            return "SELECTED"

        def evidence_suffix(name: str) -> str:
            subsystem = evidence_by_name.get(name)
            if subsystem is not None:
                connection = subsystem.values.get("connected") or subsystem.values.get("initialized")
                if connection is not None:
                    return f"; {connection.source_operation}={connection.value} ({connection.freshness.value})"
            if name == "ad2":
                return "; shared AD2 snapshot intentionally deferred"
            return ""

        requirement_lines = [
            f"AD2: {device_state('ad2')}{evidence_suffix('ad2')}",
            f"Camera: {device_state('camera')}{evidence_suffix('camera')}",
        ]
        if preflight.fluidics_required:
            if "pump" in preflight.selected_devices and "valve" in preflight.selected_devices:
                requirement_lines.extend(
                    (
                        f"Pump: {device_state('pump')}{evidence_suffix('pump')}",
                        f"Valve: {device_state('valve')}{evidence_suffix('valve')}",
                    )
                )
            else:
                requirement_lines.append("Fluidics: DISABLED — selected flush will be skipped by runtime")
        else:
            requirement_lines.append("Pump/Valve: NOT REQUIRED (flush off)")
        if preflight.tec_required:
            requirement_lines.append(f"TEC: {device_state('tec')}{evidence_suffix('tec')}")
        else:
            requirement_lines.append("TEC: NOT REQUIRED (temperature scan off)")
        requirement_lines.append(
            "Output path: CONFIGURED (writeability unverified until run)"
            if preflight.output_path_state == "configured"
            else "Output path: UNSET — blank resolves to the current working directory"
        )
        self._v3_requirements_summary.setText(
            "; ".join(requirement_lines)
            + ". Software-known shared snapshot only; no hardware query and no physical-ready claim."
        )

        issues = preflight.blocking_issues + preflight.warnings
        self._v3_plan_warnings.setText(
            "; ".join(issue.message for issue in issues) + "." if issues else "No shared preflight issues."
        )
        self._v3_plan_warnings.setStyleSheet(
            "color: darkred; font-weight: bold;"
            if preflight.blocking_issues
            else "color: darkorange; font-weight: bold;"
        )

    def _refresh_v3_relationships(self, _value=None) -> None:
        if not hasattr(self, "_v3_timing_labels"):
            return
        self._apply_v3_context_state()
        try:
            wfg = self._experiment_wfg_config()
            do_config = self._experiment_do_clock_config(0)
            rows = {
                "ch0": (
                    bool(wfg.running and wfg.channels[0].carrier.enable),
                    float(wfg.channels[0].trigger.sec_wait),
                    float(wfg.channels[0].trigger.sec_run),
                ),
                "ch1": (
                    bool(wfg.running and wfg.channels[1].carrier.enable),
                    float(wfg.channels[1].trigger.sec_wait),
                    float(wfg.channels[1].trigger.sec_run),
                ),
                "dio1": (
                    bool(do_config.running and do_config.channels[0].enable),
                    float(do_config.channels[0].trigger.sec_wait),
                    float(do_config.channels[0].trigger.sec_run),
                ),
            }
            preview = Experiment2(wfg_config=wfg, do_clock_settings=do_config)
            completion = self.app._ad2_completion_wait_seconds(preview)
            ch0_enabled, ch0_start, ch0_run = rows["ch0"]
            if ch0_enabled:
                anchor_end = ch0_start + ch0_run
                self._v3_timing_delta_header.setText("End delta vs CH0 (s)")
                self._v3_timing_anchor_note.setText(
                    "CH0 is enabled, so end deltas use CH0's requested end. Deltas are neutral "
                    "comparisons, not validation or automatic linking."
                )
            else:
                anchor_end = completion
                self._v3_timing_delta_header.setText("End delta vs completion driver (s)")
                self._v3_timing_anchor_note.setText(
                    "CH0 is disabled; end deltas are anchored to the shared completion budget "
                    "(the maximum enabled analog/digital end) used by experiment execution."
                )
            for key, (enabled, start, run) in rows.items():
                end = start + run
                values = self._v3_timing_labels[key]
                values["start"].setText(self._v3_seconds(start))
                values["run"].setText(self._v3_seconds(run))
                values["end"].setText(self._v3_seconds(end))
                values["delta"].setText(self._v3_seconds(end - anchor_end))
                for label in values.values():
                    label.setEnabled(enabled)
            self._v3_completion_budget.setText(
                f"Shared AD2 completion budget: {completion:.3f} s (maximum enabled analog/digital end)."
            )
        except (IndexError, TypeError, ValueError) as exc:
            self._v3_completion_budget.setText(f"Shared AD2 completion budget unavailable: {exc}")

        repeats = self.exp_repeats.value()
        scan_enabled = self.exp_freq_scan_enable.isChecked()
        try:
            scan_values_hz = self._experiment_frequency_scan_list_hz()
            scan_error = None
        except (TypeError, ValueError) as exc:
            scan_values_hz = []
            scan_error = str(exc)
        scan_count = len(scan_values_hz)
        scan_mismatch = scan_enabled and scan_count != repeats
        if scan_mismatch:
            scan_text = (
                f"frequency scan {scan_count}/{repeats} repeats; mismatch — run will reject until counts match"
            )
        elif scan_enabled:
            scan_text = f"frequency scan {scan_count}/{repeats} repeats; counts match"
        else:
            scan_text = "frequency scan off"
        dynamic_text = (
            f"DIO1 start slots {min(repeats, len(self.camera_start_array))}/{repeats}"
            if self.dynamic_camera_start.isChecked()
            else "fixed DIO1 start"
        )
        self._v3_series_relationship_summary.setText(f"Relationship checks: {scan_text}; {dynamic_text}.")
        self._v3_series_relationship_summary.setStyleSheet(
            "color: darkorange; font-weight: bold;" if scan_mismatch else ""
        )

        temperature_count = 1
        temperature_error = None
        if self.exp_tec_scan_enable.isChecked():
            try:
                temperature_count = len(self._temperature_series().temperature_points_c)
            except ValueError as exc:
                temperature_count = 0
                temperature_error = str(exc)
        total_runs = repeats * temperature_count
        if self.exp_tec_scan_enable.isChecked():
            outer = (
                f"TEC temperature: {temperature_count} point(s)"
                if temperature_error is None
                else f"TEC temperature invalid: {temperature_error}"
            )
            inner = f"{repeats} repeat(s) per temperature; {total_runs} acquisition run(s) total"
        else:
            outer = "No outer TEC axis"
            inner = f"{repeats} acquisition repeat(s)"
        scan_axis = (
            f"frequency list maps {scan_count} carrier value(s) one-to-one to repeat indices"
            if scan_enabled
            else "no frequency-list mapping"
        )
        self._v3_axis_summary.setText(f"{outer}; {inner}; {scan_axis}.")
        self._v3_tec_axis_summary.setText(
            f"Outer axis: {temperature_count} temperature point(s) × {repeats} repeats = {total_runs} acquisition runs."
            if self.exp_tec_scan_enable.isChecked() and temperature_error is None
            else (
                f"Temperature target list invalid: {temperature_error}"
                if temperature_error is not None
                else "Disabled: no outer temperature axis."
            )
        )
        self._v3_tec_axis_summary.setStyleSheet(
            "color: darkorange; font-weight: bold;" if temperature_error is not None else ""
        )
        self._v3_repeat_workflow.setText(
            "create record → configure AD2/DIO → configure camera → capture frames → wait for AD2 "
            "completion → optional flush → save frames and metadata"
        )
        camera_fps = float(self.exp_camera_fps.value())
        if camera_fps > 0:
            frame_interval_ms = 1000.0 / camera_fps
            acquisition_s = float(self.exp_frames.value()) / camera_fps
            camera_request = (
                f"{self.exp_frames.value()} frame(s) at {camera_fps:g} fps request a "
                f"{acquisition_s:.3f} s DIO1 window; {self.exp_exposure_ms.value():.3f} ms exposure vs "
                f"{frame_interval_ms:.3f} ms frame interval. Live DCAM readout margin is checked only at run start."
            )
        else:
            camera_request = "Camera FPS must be greater than zero before a DIO1 window can be derived."
        self._v3_camera_request_summary.setText(camera_request)
        status = getattr(self, "_v3_connection_values", {})
        status_text = lambda name: status[name].text() if name in status else "status unavailable"
        selected = [
            (
                f"AD2: {status_text('AD2')}"
                if self.app.ad2.enabled
                else "AD2: DISABLED — runtime skips WFG, DIO, and PC trigger"
            ),
            (
                f"Camera: {status_text('Camera')}"
                if self.app.camera.enabled
                else "Camera: DISABLED — runtime skips capture"
            ),
        ]
        if self.exp_flush_enabled.isChecked():
            if self.app.pump.enabled and self.app.valve.enabled:
                selected.extend((f"Pump: {status_text('Pump')}", f"Valve: {status_text('Valve')}"))
            else:
                selected.append("Fluidics: DISABLED — selected flush will be skipped by runtime")
        else:
            selected.append("Pump/Valve: NOT REQUIRED (flush off)")
        if self.exp_tec_scan_enable.isChecked():
            selected.append(
                f"TEC: {status_text('TEC')}"
                if self.app.tec.enabled
                else "TEC: DISABLED — target/stability are simulated; no TEC command"
            )
        else:
            selected.append("TEC: NOT REQUIRED (temperature scan off)")
        output_path = self.series_path.text().strip()
        selected.append(
            "Output path: CONFIGURED (writeability unverified until run)"
            if output_path
            else "Output path: UNSET — blank resolves to the current working directory"
        )
        self._v3_requirements_summary.setText(
            "; ".join(selected) + ". Software-known configured/cached state only; no hardware query and no physical-ready claim."
        )

        warnings = []
        if scan_error is not None:
            warnings.append(f"frequency list invalid: {scan_error}")
        elif scan_mismatch:
            warnings.append("frequency count must match repeats")
        if self.dynamic_camera_start.isChecked() and repeats > len(self.camera_start_array):
            warnings.append("per-repeat DIO1 delay slots are insufficient")
        if camera_fps <= 0:
            warnings.append("camera FPS must be greater than zero")
        if not output_path:
            warnings.append("choose an explicit output path; blank currently resolves to the working directory")
        if not self.app.ad2.enabled:
            warnings.append("AD2 is disabled; WFG/DIO configuration and PC trigger will be skipped")
        if not self.app.camera.enabled:
            warnings.append("camera is disabled; the run will save no captured frames")
        if self.exp_sweep_enable.isChecked() and not self.exp_ad2_channels[0]["enable"].isChecked():
            warnings.append("FM sweep enables channel 0 in the shared builder even though Channel output is unchecked")
        if temperature_error is not None:
            warnings.append("TEC target list must be corrected")
        if self.exp_tec_scan_enable.isChecked() and not self.app.tec.enabled:
            warnings.append("TEC scan is selected but the controller is disabled; the shared runtime simulates target/stability")
        if self.exp_flush_enabled.isChecked():
            settings = self._flush_settings(experiment=True)
            if settings.flush_volume_ml > settings.syringe_volume_ml:
                warnings.append("flush volume exceeds selected syringe capacity")
            if settings.flush_volume_ml > float(self.app.pump.fill_level):
                warnings.append("flush volume exceeds the pump's tracked fill level")
            if not (self.app.pump.enabled and self.app.valve.enabled):
                warnings.append("flush is selected but pump or valve is disabled; the shared runtime will skip it")
            warnings.append("fluid routing is bench-unverified; selected syringe geometry must be applied manually")
        warnings.append("DIO1-to-camera exposure synchronization remains bench-unverified")
        self._v3_plan_warnings.setText("; ".join(warnings) + ".")
        self._v3_plan_warnings.setStyleSheet("color: darkorange; font-weight: bold;")
        self._render_v3_shared_preflight(self._v3_shadow_build_result())

        fm = self.exp_sweep_enable.isChecked()
        scan = self.exp_freq_scan_enable.isChecked()
        if fm and scan:
            program = "Scan selects each repeat's base carrier; FM sweep remains active within that repeat."
        elif fm:
            program = "FM sweep active within each repeat; frequency scan off."
        elif scan:
            program = "Frequency scan overrides the base carrier once per repeat; FM sweep off."
        else:
            program = "Static base carrier only."
        self._v3_frequency_program_summary.setText(f"Active program: {program}")
        if scan_enabled and scan_error is None:
            values_khz = [value / 1000.0 for value in scan_values_hz]
            self._v3_frequency_scan_preview.setText(
                f"Frequency-list preview ({len(values_khz)} point(s), kHz): "
                f"{self._v3_compact_values(values_khz)}"
            )
        elif scan_error is not None:
            self._v3_frequency_scan_preview.setText(f"Frequency-list preview unavailable: {scan_error}")
        else:
            self._v3_frequency_scan_preview.setText("Frequency-list preview: off; base carrier is unchanged across repeats.")

        dynamic = self.dynamic_camera_start.isChecked()
        self.exp_camera_start.setEnabled(not dynamic)
        for widget in self.camera_start_array:
            widget.setEnabled(dynamic)
        try:
            do_config = self._experiment_do_clock_config(0)
            trigger = do_config.channels[0].trigger
            self._v3_dio_duration.setText(
                f"{trigger.sec_run:.3f} s = {self.exp_frames.value()} frames / {self.exp_camera_fps.value():.3f} fps"
            )
            source = "per-repeat slot 1" if dynamic else "fixed DIO1 start"
            self._v3_dio_start_source.setText(f"{source}: {trigger.sec_wait:.3f} s")
        except (IndexError, ValueError) as exc:
            self._v3_dio_duration.setText(f"Unavailable: {exc}")
            self._v3_dio_start_source.setText("Unavailable")
        if dynamic:
            slots = len(self.camera_start_array)
            slot_mismatch = repeats > slots
            suffix = "available" if not slot_mismatch else "insufficient — run will reject beyond slot 10"
            self._v3_dio_slot_budget.setText(f"{min(repeats, slots)}/{repeats} repeats; {slots} slots {suffix}")
            self._v3_dio_slot_budget.setStyleSheet(
                "color: darkorange; font-weight: bold;" if slot_mismatch else ""
            )
        else:
            self._v3_dio_slot_budget.setText("Not used; fixed start applies to every repeat")
            self._v3_dio_slot_budget.setStyleSheet("")
        self._v3_camera_feasibility.setText(
            "Application._check_camera_timing_budget() validates requested FPS against applied exposure plus "
            "live DCAM readout at run start. Preview unavailable without querying hardware."
        )

        settings = self._flush_settings(experiment=True)
        movement_s = max(settings.timeout_s - 5.0, 0.0) if settings.flush_flowrate > 0 else 0.0
        self._v3_flush_movement.setText(f"{movement_s:.3f} s")
        self._v3_flush_timeout.setText(f"{settings.timeout_s:.3f} s (movement + 5.000 s margin)")
        capacity_status = "within capacity" if settings.flush_volume_ml <= settings.syringe_volume_ml else "exceeds capacity"
        self._v3_flush_capacity.setText(f"{settings.syringe_volume_ml:.3f} ml; {capacity_status}")
        tracked_fill = float(self.app.pump.fill_level)
        remaining = tracked_fill - settings.flush_volume_ml
        self._v3_flush_fill_margin.setText(
            f"{remaining:.3f} ml = tracked {tracked_fill:.3f} ml − requested {settings.flush_volume_ml:.3f} ml"
        )

    def _v2_waveform_group(self) -> QGroupBox:
        group = super()._v2_waveform_group()
        group.setTitle("Live waveform and camera rate")
        _rename_unique_text_widget(
            group,
            QLabel,
            "Average FPS",
            "Measured camera rate (fps)",
            "v3MeasuredCameraRateCaption",
        )
        return group

    def _global_status_panel(self) -> QGroupBox:
        group = super()._global_status_panel()
        form = group.layout()
        if not isinstance(form, QFormLayout):
            raise RuntimeError("V3 expected Global Status to use a form layout.")
        _adapt_form_caption(form, self.error_log, "Status and error history", "v3StatusHistoryCaption")
        return group

    def _refresh_status(self) -> None:
        super()._refresh_status()
        if hasattr(self, "connection_button"):
            # In v2 this action's text is derived from app.status being exactly
            # "System Initialized". Any later successful action changes that
            # status string and makes the button claim hardware disconnected.
            # V3 has per-device connection indicators, so keep this as a stable
            # action label and leave connection truth to those indicators.
            self.connection_button.setText("Initialize hardware")
            self.connection_button.setStyleSheet("")
            self.connection_button.setToolTip("Open device selection, simulation options, and initialization progress.")
        values = getattr(self, "_v3_connection_values", None)
        if not values or not hasattr(self, "ad2_connection_status"):
            return
        sources = {
            "AD2": self.ad2_connection_status.text(),
            "Camera": self.camera_connection_status.text(),
            "Pump": self.pump_connection_status.text(),
            "Valve": self.valve_connection_status.text(),
            "TEC": (
                "Disabled"
                if not self.app.tec.enabled
                else "Connected (simulated)"
                if self.app.tec.initialized and self.app.tec.simulate
                else "Connected"
                if self.app.tec.initialized
                else "Not connected"
            ),
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
        self._refresh_v3_tec_readback()
        self._refresh_v3_pump_local_status()
        if hasattr(self, "_v3_timing_labels"):
            self._refresh_v3_relationships()

    def _refresh_v3_tec_readback(self) -> None:
        labels = getattr(self, "_v3_tec_readback_labels", None)
        if not labels:
            return
        for channel, label in labels.items():
            status = self.app.tec.last_status.get(channel)
            if status is None:
                label.setText("No cached readback")
                continue
            current = "—" if status.current_temperature_c is None else f"{status.current_temperature_c:.3f} °C"
            target = "—" if status.target_temperature_c is None else f"{status.target_temperature_c:.3f} °C"
            readiness = "ready" if status.ready else "not ready"
            output = "output on" if status.output_stage_static_on else "output off"
            error = f"; error: {status.error_state}" if status.error_state else ""
            label.setText(f"Measured {current}; target {target}; {readiness}; {output}{error}")

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

        note = QLabel(
            "Manual AD2 waveform test. On the first hardware initialization only, this panel seeds the "
            "experiment AD2 fields; after that one-time seed, manual and experiment values are independent."
        )
        note.setObjectName("v3ManualWfgExperimentBoundary")
        note.setWordWrap(True)
        note.setMaximumWidth(700)
        layout.addWidget(note)

        header = QHBoxLayout()
        self.wfg_running.setText("Enable WFG output")
        header.addWidget(self._wrap_with_tooltip_icon(self.wfg_running))
        header.addStretch(1)
        self.wfg_sync.setEnabled(False)
        self.wfg_sync.setToolTip("Not implemented: channel synchronization is currently unavailable.")
        header.addWidget(QLabel("Synchronize channels"))
        header.addWidget(self._wrap_with_tooltip_icon(self.wfg_sync))
        layout.addLayout(header)

        layout.addWidget(self._wfg_channel_group("AD2 channel 0 (LabVIEW Ch1)", self.wfg_channels[0]))
        layout.addWidget(self._wfg_channel_group("AD2 channel 1 (LabVIEW Ch2)", self.wfg_channels[1]))

        apply = QPushButton("Apply manual WFG settings")
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

    def _wfg_channel_group(self, title: str, state: dict[str, object]) -> QGroupBox:
        group = super()._wfg_channel_group(title, state)
        inner_scroll = group.findChild(QScrollArea)
        if inner_scroll is None:
            raise RuntimeError("V3 expected the inherited WFG channel form scroll area.")
        # V1/v2 deliberately keep this dense form at its natural width and
        # expose a horizontal scrollbar. V3's longer relationship labels made
        # that scrollbar appear even in its 900 px manual dialog. Allow the
        # form to reflow here; vertical scrolling remains available for rows.
        inner_scroll.setWidgetResizable(True)
        inner_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner_scroll.setObjectName(f"v3WfgChannel{state['idx'].value()}Scroll")
        label_text_by_object_name = {
            "manualWfgCarrier_idxLabel": "Channel index",
            "manualWfgCarrier_frequencyLabel": "Carrier frequency (kHz) (overridden)",
            "manualWfgCarrier_amplitudeLabel": "Amplitude (V) (overridden)",
            "manualWfgCarrier_offsetLabel": "Offset (V) (overridden)",
            "manualWfgCarrier_symmetryLabel": "Symmetry (%) (overridden)",
            "manualWfgCarrier_phaseLabel": "Phase (deg) (overridden)",
            "manualWfgCarrier_functionLabel": "Waveform (overridden)",
            "manualWfgTrigger_sec_runLabel": "Run duration (s)   [0 = continuous] (overridden)",
            "manualWfgTrigger_sec_waitLabel": "Start delay (s) (overridden)",
            "manualWfgTrigger_repeatLabel": "Repeat count   [0 = infinite] (overridden)",
            "manualWfgTrigger_sourceLabel": "Trigger source (overridden)",
            "manualWfgFm_fm_frequencyLabel": "Frequency (kHz) (manual WFG only)",
            "manualWfgFm_fm_amplitudeLabel": "Amplitude (%) (manual WFG only)",
            "manualWfgFm_fm_offsetLabel": "Offset (V) (manual WFG only)",
            "manualWfgFm_fm_symmetryLabel": "Symmetry (%) (manual WFG only)",
            "manualWfgFm_fm_phaseLabel": "Phase (deg) (manual WFG only)",
            "manualWfgFm_fm_functionLabel": "Modulation waveform (manual WFG only)",
            "manualWfgFmSectionLabel": "FM modulation (manual WFG only)",
        }
        for object_name, text in label_text_by_object_name.items():
            label = group.findChild(QLabel, object_name)
            if label is None:
                raise RuntimeError(f"V3 expected inherited WFG label {object_name!r}.")
            label.setText(text)
            label.setWordWrap(True)
            label.setMaximumWidth(310)
        state["enable"].setText("Enable channel output (overridden)")
        state["repeat_trigger"].setText("Re-arm trigger after each repeat (overridden)")
        state["fm_enable"].setText("Enable FM modulation")
        state["sweep_enable"].setText("Enable frequency sweep")
        return group

    def _wfg_preview_group(self) -> QGroupBox:
        group = super()._wfg_preview_group()
        group.setTitle("Computed waveform preview")
        note = group.findChild(QLabel, "manualWfgPreviewDescription")
        if note is None:
            raise RuntimeError("V3 expected the inherited WFG preview description.")
        note.setText("Computed from the current manual settings; no hardware readback.")
        note.setMaximumWidth(700)
        return group

    def _mso_tab(self) -> QWidget:
        base = super()._mso_tab()
        _rename_unique_text_widget(base, QPushButton, "Capture", "Capture waveform", "v3MsoCaptureButton")
        _rename_unique_group(
            base,
            "MSO Configuration",
            "MSO acquisition settings",
            "v3MsoAcquisitionSettings",
        )
        _rename_unique_group(base, "Waveform", "Captured waveform", "v3MsoCapturedWaveform")
        _rename_unique_text_widget(base, QLabel, "Stats", "Capture summary", "v3MsoCaptureSummaryCaption")
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
        note = QLabel("Manual AD2 oscilloscope diagnostic. Independent of experiment runs.")
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

        note = QLabel(
            "Manual pump and valve controls. P01/P02 fluid routing requires bench confirmation. The syringe "
            "selection is also used by experiment-flush capacity checks, but selecting it does not configure "
            "the physical pump."
        )
        note.setWordWrap(True)
        note.setMaximumWidth(700)
        layout.addWidget(note)

        local_status = QGroupBox("Cached pump and valve state")
        local_status.setObjectName("v3PumpValveLocalStatus")
        local_form = QFormLayout(local_status)
        self._v3_pump_local_state = QLabel()
        self._v3_pump_local_state.setObjectName("v3PumpLocalState")
        self._v3_pump_local_state.setWordWrap(True)
        self._v3_valve_local_state = QLabel()
        self._v3_valve_local_state.setObjectName("v3ValveLocalState")
        self._v3_valve_local_state.setWordWrap(True)
        self._v3_syringe_local_state = QLabel()
        self._v3_syringe_local_state.setObjectName("v3SyringeLocalState")
        self._v3_syringe_local_state.setWordWrap(True)
        local_form.addRow("Pump", self._v3_pump_local_state)
        local_form.addRow("Valve", self._v3_valve_local_state)
        local_form.addRow("Syringe configuration", self._v3_syringe_local_state)
        local_note = QLabel(
            "Application cache only: refreshed after software actions/readbacks; opening this panel does not query hardware. "
            "Tracked fill and protocol position are not independent physical verification."
        )
        local_note.setObjectName("v3PumpLocalStatusEvidenceNote")
        local_note.setWordWrap(True)
        local_form.addRow(local_note)
        layout.addWidget(local_status)

        pump_group = QGroupBox("Immediate pump operations")
        pump_form = QFormLayout(pump_group)
        pump_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        refill = QPushButton("Refill syringe")
        refill.clicked.connect(lambda: self._run_action(lambda progress: self._refill(), "Refilling"))
        empty = QPushButton("Empty syringe")
        empty.clicked.connect(lambda: self._run_action(lambda progress: self._empty(), "Emptying"))
        generate = QPushButton("Start flow at selected rate")
        generate.clicked.connect(self._start_generate_flow)
        go = QPushButton("Move to target fill level")
        go.clicked.connect(self._start_go_level)
        stop = QPushButton("Stop pump")
        stop.setObjectName("v3StopPumpButton")
        stop.setMinimumHeight(50)
        stop.setStyleSheet("color: darkred; font-weight: bold;")
        stop.clicked.connect(lambda: self._run_action(lambda progress: self.app.pump.stop(), "Pump stopped"))
        pump_form.addRow("Refill / empty flow rate (uL/min)", self.fill_flow_rate)
        pump_form.addRow(refill, empty)
        pump_form.addRow("Flow rate (- = aspirate, + = dispense)", self.flow_rate)
        pump_form.addRow(generate)
        pump_form.addRow("Target level (ml)", self.level_ml)
        pump_form.addRow(go)
        pump_form.addRow(stop)
        self._add_tooltip_icons(pump_form)

        valve_group = QGroupBox("Valve position")
        valve_form = QFormLayout(valve_group)
        valve_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        pos1 = QPushButton("Set valve to position 1 (P01)")
        pos1.setToolTip("Sends P01. Physical fluidic routing remains unverified.")
        pos1.clicked.connect(
            lambda: self._run_action(
                lambda progress: self.app.valve.set_position(1), "Setting valve to position 1 (P01)"
            )
        )
        pos2 = QPushButton("Set valve to position 2 (P02)")
        pos2.setToolTip("Sends P02. Physical fluidic routing remains unverified.")
        pos2.clicked.connect(
            lambda: self._run_action(
                lambda progress: self.app.valve.set_position(2), "Setting valve to position 2 (P02)"
            )
        )
        valve_form.addRow(pos1)
        valve_form.addRow(pos2)

        flush_group = QGroupBox("Manual flush")
        flush_form = QFormLayout(flush_group)
        flush_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        flush = QPushButton("Start flush sequence")
        flush.clicked.connect(self._start_flush)
        flush_form.addRow("Flush cycles", self.flush_count)
        flush_form.addRow("Flow rate (uL/min)", self.flush_flowrate)
        flush_form.addRow("Volume (ml)", self.flush_volume)
        flush_form.addRow("Wait after flush (s)", self.wait_after_flush)
        flush_note = QLabel(
            "Sequence: valve P01 → pump dispense → valve P02 → configured wait. "
            "Physical P01/P02 routing remains bench-unverified."
        )
        flush_note.setObjectName("v3ManualFlushWorkflowNote")
        flush_note.setWordWrap(True)
        flush_form.addRow(flush_note)
        flush_form.addRow(flush)
        self._add_tooltip_icons(flush_form)

        syringe_group = QGroupBox("Shared syringe setup and calibration")
        syringe_form = QFormLayout(syringe_group)
        syringe_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        configure = QPushButton("Configure syringe")
        configure.clicked.connect(self._start_configure_syringe)
        reference = QPushButton("Run reference move")
        reference.clicked.connect(self._start_reference_move)
        syringe_form.addRow(reference)
        syringe_form.addRow("Syringe", self.syringe)
        syringe_form.addRow("Custom volume (ml)", self.custom_syringe_volume_ml)
        syringe_form.addRow("Custom inner diameter (mm)", self.custom_syringe_inner_diameter_mm)
        syringe_form.addRow("Custom max piston stroke (mm)", self.custom_syringe_stroke_mm)
        syringe_note = QLabel(
            "Experiment flush capacity calculations use this selected geometry. Configure syringe is the explicit "
            "action that applies it to the pump; automated experiment setup does not apply it for you."
        )
        syringe_note.setObjectName("v3SharedSyringeBoundary")
        syringe_note.setWordWrap(True)
        syringe_form.addRow(syringe_note)
        syringe_form.addRow(configure)
        self._add_tooltip_icons(syringe_form)

        recovery_group = QGroupBox("Connection recovery")
        recovery_group.setObjectName("v3PumpConnectionRecovery")
        recovery_layout = QVBoxLayout(recovery_group)
        recovery_note = QLabel(
            "Advanced manual recovery for a pump fault observed after initialization or for an "
            "operator-requested reconnect. It does not repair the underlying CAN cause."
        )
        recovery_note.setWordWrap(True)
        recovery_note.setMaximumWidth(620)
        clear_fault = QPushButton("Clear fault and retry connection")
        clear_fault.setObjectName("v3ClearPumpFaultButton")
        clear_fault.setStyleSheet("color: darkred; font-weight: bold;")
        clear_fault.setToolTip(
            "Uses the shared, confirmation-gated Qmix recovery path. Normal initialization already "
            "clears the vendor fault latch; use this only for explicit manual recovery."
        )
        clear_fault.clicked.connect(self._start_clear_pump_fault)
        recovery_layout.addWidget(recovery_note)
        recovery_layout.addWidget(clear_fault, alignment=Qt.AlignmentFlag.AlignLeft)
        recovery_layout.addStretch(1)

        tasks = QTabWidget()
        tasks.setObjectName("v3PumpValveTasks")

        pump_page = QWidget()
        pump_layout = QVBoxLayout(pump_page)
        pump_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        pump_layout.addWidget(pump_group)
        pump_layout.addStretch(1)

        valve_page = QWidget()
        valve_layout = QVBoxLayout(valve_page)
        valve_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        valve_layout.addWidget(valve_group)
        valve_layout.addStretch(1)

        flush_page = QWidget()
        flush_layout = QVBoxLayout(flush_page)
        flush_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        flush_layout.addWidget(flush_group)
        flush_layout.addStretch(1)

        setup_page = QWidget()
        setup_layout = QVBoxLayout(setup_page)
        setup_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        setup_layout.addWidget(syringe_group)
        setup_layout.addStretch(1)

        recovery_page = QWidget()
        recovery_page_layout = QVBoxLayout(recovery_page)
        recovery_page_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        recovery_page_layout.addWidget(recovery_group)
        recovery_page_layout.addStretch(1)

        tasks.addTab(pump_page, "Pump")
        tasks.addTab(valve_page, "Valve")
        tasks.addTab(flush_page, "Flush")
        tasks.addTab(setup_page, "Syringe setup")
        tasks.addTab(recovery_page, "Recovery")
        layout.addWidget(tasks)

        scroll.setWidget(content)
        outer.addWidget(scroll)
        self._refresh_v3_pump_local_status()
        return tab

    def _refresh_v3_pump_local_status(self) -> None:
        pump_label = getattr(self, "_v3_pump_local_state", None)
        valve_label = getattr(self, "_v3_valve_local_state", None)
        syringe_label = getattr(self, "_v3_syringe_local_state", None)
        if pump_label is None or valve_label is None or syringe_label is None:
            return
        pump = self.app.pump
        pump_connection = (
            "Disabled"
            if not pump.enabled
            else "Connected"
            if pump.initialized
            else "Not connected"
        )
        pump_label.setText(
            f"{pump_connection}; {'dosing' if pump.dosing else 'idle'}; tracked fill {pump.fill_level:.3f} ml; "
            f"reference move {'confirmed' if pump.referenced else 'not confirmed'}"
        )
        valve = self.app.valve
        valve_label.setText(
            f"{self._valve_connection_text()}; cached protocol position {self._valve_position_text()}; "
            f"status {valve.status_note or 'no protocol readback note'}"
        )
        config = pump.syringe_config
        if config is None:
            syringe_label.setText("No syringe configuration has been applied by this process")
        else:
            details = [f"name {config.get('name', 'unnamed')}"]
            if "inner_diameter_mm" in config:
                details.append(f"inner diameter {config['inner_diameter_mm']} mm")
            if "max_piston_stroke_mm" in config:
                details.append(f"stroke {config['max_piston_stroke_mm']} mm")
            syringe_label.setText("Last successfully applied by this process: " + "; ".join(details))

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

        note = QLabel(
            "Camera setup and manual operation. Automated experiments inherit the applied ROI and selected "
            "sequence defaults, then reapply experiment exposure/frame count and force Internal trigger source. "
            "Display conversion affects preview only, not saved image data."
        )
        note.setObjectName("v3CameraSharedStateSummary")
        note.setWordWrap(True)
        note.setMaximumWidth(700)
        layout.addWidget(note)
        tasks = QTabWidget()
        tasks.setObjectName("v3CameraTasks")

        capture_page = QWidget()
        capture_layout = QVBoxLayout(capture_page)
        capture_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        capture_layout.addWidget(self._v3_camera_acquisition_group())
        capture_layout.addWidget(self._v3_camera_roi_group())
        capture_layout.addWidget(self._v3_camera_saved_output_group())
        capture_layout.addStretch(1)

        sequence_page = QWidget()
        sequence_layout = QVBoxLayout(sequence_page)
        sequence_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        sequence_sections = QTabWidget()
        sequence_sections.setObjectName("v3CameraSequenceSections")
        sequence_sections.addTab(self._v3_group_page(self._v3_camera_sequence_actions_group()), "Actions")
        sequence_sections.addTab(self._v3_group_page(self._v3_camera_sequence_timing_group()), "Timing")
        sequence_sections.addTab(self._v3_group_page(self._v3_camera_trigger_group()), "Trigger")
        sequence_sections.addTab(
            self._v3_group_page(self._v3_camera_legacy_sequence_group()),
            "Retained (not used by runtime)",
        )
        sequence_layout.addWidget(sequence_sections)
        sequence_layout.addStretch(1)

        display_page = QWidget()
        display_layout = QVBoxLayout(display_page)
        display_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        display_layout.addWidget(self._v3_conversion_group())
        display_layout.addStretch(1)

        tasks.addTab(capture_page, "Capture")
        tasks.addTab(sequence_page, "Sequence")
        tasks.addTab(display_page, "Display")
        layout.addWidget(tasks)

        scroll.setWidget(content)
        outer.addWidget(scroll)
        return tab

    def _v3_camera_acquisition_group(self) -> QGroupBox:
        group = QGroupBox("Capture and preview")
        row = QHBoxLayout(group)
        image = QPushButton("Capture single image")
        image.clicked.connect(self._start_capture_camera_image)
        continuous = self._live_image_continuous_checkbox()
        continuous.toggled.connect(self._set_image_continuous)
        row.addWidget(image)
        row.addWidget(QLabel("Live preview"))
        row.addWidget(continuous)
        hint = QLabel("Apply camera settings before starting a capture.")
        hint.setWordWrap(True)
        hint.setMaximumWidth(300)
        row.addWidget(hint)
        row.addStretch(1)
        return group

    def _v3_camera_sequence_actions_group(self) -> QGroupBox:
        group = QGroupBox("Sequence actions")
        form = QFormLayout(group)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        start = QPushButton("Start camera capture session")
        start.setToolTip(
            "Starts the low-level DCAM capture session. It does not retrieve an image for "
            "Save last captured image."
        )
        start.clicked.connect(
            lambda: self._run_action(lambda progress: self.app.camera.start_capture(), "Camera capture started")
        )
        stop = QPushButton("Stop camera capture session")
        stop.setToolTip("Stops the active DCAM capture session.")
        stop.clicked.connect(
            lambda: self._run_action(lambda progress: self.app.camera.stop_capture(), "Camera capture stopped")
        )
        trigger = QPushButton("Send software trigger")
        trigger.setToolTip(
            "Sends a software trigger to the camera. It does not retrieve an image for "
            "Save last captured image."
        )
        trigger.clicked.connect(lambda: self._run_action(lambda progress: self.app.camera.sw_trigg(), "Camera triggered"))
        form.addRow(start)
        form.addRow(stop)
        form.addRow(trigger)
        return group

    def _v3_camera_saved_output_group(self) -> QGroupBox:
        group = QGroupBox("Saved-frame output")
        group.setObjectName("v3CameraSavedOutput")
        form = QFormLayout(group)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        save = QPushButton("Save last captured image")
        save.setToolTip("Saves the frame buffer populated by Capture single image; it does not retrieve a new frame.")
        save.clicked.connect(self._start_save_sequence)
        browse = QPushButton("Browse...")
        browse.clicked.connect(lambda: self._browse_folder(self.sequence_path))
        path_row = QHBoxLayout()
        path_row.addWidget(self.sequence_path, 1)
        path_row.addWidget(browse)
        form.addRow("Output folder", path_row)
        form.addRow(save)
        return group

    def _v3_camera_roi_group(self) -> QGroupBox:
        group = QGroupBox("Shared applied ROI and manual exposure")
        form = QFormLayout(group)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.addRow("Horizontal offset (px)", self.roi_h_offset)
        form.addRow("Vertical offset (px)", self.roi_v_offset)
        form.addRow("Horizontal size (px)", self.roi_h_size)
        form.addRow("Vertical size (px)", self.roi_v_size)
        form.addRow("Exposure time (ms)", self.exposure_ms)
        form.addRow("Center ROI", self.center_roi)
        configure = QPushButton("Apply camera settings")
        configure.setToolTip(
            "Applies exposure, region-of-interest, and Sequence tab settings to the camera. Automated runs "
            "reapply experiment exposure but retain the applied ROI."
        )
        configure.clicked.connect(self._start_configure_camera)
        form.addRow(configure)
        self._add_tooltip_icons(form)
        return group

    @staticmethod
    def _v3_group_page(group: QGroupBox) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(group)
        layout.addStretch(1)
        return page

    def _v3_camera_sequence_timing_group(self) -> QGroupBox:
        group = QGroupBox("Shared sequence defaults")
        form = QFormLayout(group)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        for label, widget in (
            ("Master pulse mode", self.sequence_mode),
            ("Master pulse source", self.sequence_source),
            ("Interval (s)", self.sequence_interval),
            ("Burst count", self.sequence_burst),
            ("Capture buffer size (frames)", self.sequence_frames),
        ):
            form.addRow(label, widget)
        note = QLabel(
            "Automated runs inherit mode, source, interval, and burst count, but replace the capture-buffer "
            "frame count with Frames per repeat."
        )
        note.setObjectName("v3CameraSequenceBoundary")
        note.setWordWrap(True)
        form.addRow(note)
        self._add_tooltip_icons(form)
        return group

    def _v3_camera_trigger_group(self) -> QGroupBox:
        group = QGroupBox("Trigger defaults and manual mode")
        form = QFormLayout(group)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.addRow("Camera trigger source", self.dcam_source)
        form.addRow("Trigger polarity", self.external_polarity)
        form.addRow("Trigger delay (s)", self.external_delay)
        note = QLabel(
            "Automated runs force trigger source to Internal. Polarity and delay remain inherited sequence "
            "values, but their physical relevance depends on the selected camera mode and is bench-unverified."
        )
        note.setObjectName("v3CameraTriggerBoundary")
        note.setWordWrap(True)
        form.addRow(note)
        self._add_tooltip_icons(form)
        return group

    def _v3_camera_legacy_sequence_group(self) -> QGroupBox:
        group = QGroupBox("Retained sequence fields (not used)")
        form = QFormLayout(group)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.addRow("Capture mode", self.capture_mode)
        form.addRow("Sequence exposure (ms)", self.sequence_exposure_ms)
        note = QLabel("Retained for migration reference; the current runtime does not use these fields.")
        note.setWordWrap(True)
        form.addRow(note)
        self._add_tooltip_icons(form)
        return group

    def _v3_conversion_group(self) -> QGroupBox:
        group = QGroupBox("Display conversion (advanced)")
        form = QFormLayout(group)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.addRow("Conversion method", self.conversion_method)
        form.addRow("Display minimum", self.conversion_min)
        form.addRow("Display maximum", self.conversion_max)
        form.addRow("Right shift (bits)", self.conversion_shifts)
        adjust = QPushButton("Reprocess preview")
        adjust.setToolTip(
            "Reprocesses the most recently captured image with these display settings. "
            "It does not capture a new image or modify saved data."
        )
        adjust.clicked.connect(self._adjust_camera_preview)
        self.conversion_method.currentTextChanged.connect(lambda _value: self._update_conversion_controls())
        form.addRow(adjust)
        self._add_tooltip_icons(form)
        self._update_conversion_controls()
        return group

    def _zscan_control_group(self) -> QGroupBox:
        """Build v3 Z-scan controls, replacing v1 without calling its base method.

        Future additions to v1's method of the same name do not appear here
        automatically and require an explicit v3 review.
        """
        group = QGroupBox("Z-Scan actions")
        layout = QVBoxLayout(group)
        query_range = QPushButton("Read piezo travel range")
        query_range.clicked.connect(self._query_zscan_range)
        start = QPushButton("Start Z-Scan")
        start.clicked.connect(self._start_zscan)
        abort = QPushButton("Abort Z-Scan")
        abort.clicked.connect(self._abort_zscan)
        layout.addWidget(query_range)
        layout.addWidget(start)
        layout.addWidget(abort)
        hint = QLabel(
            "Uses the existing camera connection and the Z-scan exposure setting. "
            "Apply camera settings before starting; motion requires explicit confirmation."
        )
        hint.setWordWrap(True)
        hint.setMaximumWidth(280)
        layout.addWidget(hint)
        layout.addStretch(1)
        return group

    def _apply_zscan_range(self, max_travel_um: float | None) -> None:
        super()._apply_zscan_range(max_travel_um)
        if hasattr(self, "_v3_zscan_derived_summary"):
            self._refresh_v3_zscan_summary()

    def _zscan_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        note = QLabel(
            "Manual calibration workflow only. It reuses the existing camera connection; "
            "the Z-scan exposure is independent of the experiment-camera exposure. Motion requires explicit confirmation."
        )
        note.setWordWrap(True)
        note.setMaximumWidth(620)
        layout.addWidget(note)

        self._v3_zscan_derived_summary = QLabel()
        self._v3_zscan_derived_summary.setObjectName("v3ZScanDerivedSummary")
        self._v3_zscan_derived_summary.setWordWrap(True)
        layout.addWidget(self._v3_zscan_derived_summary)
        for widget in (self.zscan_z_start_um, self.zscan_z_end_um, self.zscan_step_size_um):
            widget.valueChanged.connect(self._refresh_v3_zscan_summary)
        self._refresh_v3_zscan_summary()

        body = QHBoxLayout()
        parameters = self._zscan_parameters_group()
        controls = self._zscan_control_group()
        parameters.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        controls.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        body.addWidget(parameters, 1, Qt.AlignmentFlag.AlignTop)
        body.addWidget(controls, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(body)
        layout.addStretch(1)
        return tab

    def _refresh_v3_zscan_summary(self, _value=None) -> None:
        start_um = float(self.zscan_z_start_um.value())
        end_um = float(self.zscan_z_end_um.value())
        step_um = float(self.zscan_step_size_um.value())
        if end_um < start_um:
            text = "Requested range is invalid: Z end must be greater than or equal to Z start."
            warning = True
        else:
            targets = ZScanCalibration._build_targets(start_um, end_um, step_um)
            text = (
                f"Derived scan: {len(targets)} position(s) / image(s), {start_um:.3f}–{end_um:.3f} µm "
                f"with {step_um:.3f} µm requested spacing. {self.zscan_range_status.text()}"
            )
            warning = not self.zscan_z_start_um.isEnabled()
        self._v3_zscan_derived_summary.setText(text)
        self._v3_zscan_derived_summary.setStyleSheet(
            "color: darkorange; font-weight: bold;" if warning else ""
        )


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    install_focus_wheel_guard(app)
    window = MainWindowV3(app=Application(ad2=SimulatedAD2Sdk()))
    window.show()
    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
