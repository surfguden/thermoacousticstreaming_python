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
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .application import Application
from .instruments import SimulatedAD2Sdk
from .qt_ui import install_focus_wheel_guard
from .qt_ui_v2 import InitializationDialog, MainWindowV2
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

        workspace_layout.addWidget(self._v3_run_control_group(), 0)

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
        for name in ("AD2", "Camera", "Pump", "Valve"):
            layout.addWidget(QLabel(name))
            value = QLabel("Not connected")
            value.setMinimumWidth(82)
            self._v3_connection_values[name] = value
            layout.addWidget(value)
        layout.addStretch(1)
        return group

    def _v3_run_control_group(self) -> QGroupBox:
        group = QGroupBox("Experiment run")
        group.setObjectName("v3PrimaryRunControl")
        grid = QGridLayout(group)
        start = QPushButton("Start experiment")
        start.setObjectName("v3StartExperimentButton")
        start.setMinimumHeight(44)
        start.setToolTip(
            "Runs with the currently initialized backends."
        )
        start.clicked.connect(self._start_experiment)
        stop = QPushButton("Request graceful stop")
        stop.setObjectName("v3RequestGracefulStopButton")
        stop.setMinimumHeight(44)
        stop.setStyleSheet("color: darkred; font-weight: bold;")
        stop.setToolTip(
            "Stops after the current repeat, or after the current temperature point during a TEC scan. "
            "It does not stop hardware in the middle of an operation."
        )
        stop.clicked.connect(self._abort)
        browse = QPushButton("Browse...")
        browse.clicked.connect(lambda: self._browse_folder(self.series_path))
        note = QLabel(
            "Start uses the configured series. Graceful stop finishes the active unit before halting; "
            "it is not an emergency hardware stop."
        )
        note.setWordWrap(True)
        note.setMaximumWidth(520)
        repeats_host = QWidget()
        repeats_layout = QHBoxLayout(repeats_host)
        repeats_layout.setContentsMargins(0, 0, 0, 0)
        self._v3_repeats_layout = repeats_layout
        self._v3_series_relationship_summary = QLabel()
        self._v3_series_relationship_summary.setObjectName("v3SeriesRelationshipSummary")
        self._v3_series_relationship_summary.setWordWrap(True)
        grid.addWidget(start, 0, 0, 2, 1)
        grid.addWidget(stop, 0, 1, 2, 1)
        grid.addWidget(QLabel("Series path"), 0, 2)
        grid.addWidget(self._wrap_with_tooltip_icon(self.series_path), 1, 2)
        grid.addWidget(browse, 1, 3)
        grid.addWidget(note, 0, 4, 2, 1)
        repeats_caption = QLabel("Series repeats")
        repeats_caption.setObjectName("v3ExperimentRepeatsCaption")
        grid.addWidget(repeats_caption, 2, 0)
        grid.addWidget(repeats_host, 2, 1)
        grid.addWidget(self._v3_series_relationship_summary, 2, 2, 1, 3)
        grid.setColumnStretch(2, 1)
        grid.setColumnStretch(4, 1)
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
        fluidics_note = QLabel("Optional post-capture pump and valve sequence. Disabled by default.")
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
        scan_layout.addWidget(frequency_scan)
        modulation.addTab(fm_page, "FM sweep")
        modulation.addTab(scan_page, "Frequency scan")
        layout.addWidget(modulation)
        return group

    def _v3_one_repeat_timing_plan(self) -> QGroupBox:
        group = QGroupBox("One-repeat AD2 timing plan (requested)")
        group.setObjectName("v3OneRepeatTimingPlan")
        grid = QGridLayout(group)
        for column, text in enumerate(("Output", "Start (s)", "Run (s)", "End (s)", "End delta vs CH0 (s)")):
            grid.addWidget(QLabel(text), 0, column)
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
        note = QLabel(
            "End deltas are neutral comparisons, not validation or automatic linking. The completion budget "
            "uses the same shared finite-window calculation as experiment execution."
        )
        note.setWordWrap(True)
        grid.addWidget(note, 5, 0, 1, 5)
        return group

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
        group.setTitle("TEC temperature scan")
        note = QLabel("Simulated by default. Real TEC operation remains unapproved.")
        note.setWordWrap(True)
        note.setMaximumWidth(520)
        layout = group.layout()
        if isinstance(layout, QFormLayout):
            layout.insertRow(0, note)
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
            *(state["enable"] for state in self.exp_ad2_channels),
        ):
            checkbox.toggled.connect(self._refresh_v3_relationships)
        self.syringe.currentTextChanged.connect(self._refresh_v3_relationships)

    @staticmethod
    def _v3_seconds(value: float) -> str:
        return f"{value:.3f}"

    def _refresh_v3_relationships(self, _value=None) -> None:
        if not hasattr(self, "_v3_timing_labels"):
            return
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
            ch0_end = rows["ch0"][1] + rows["ch0"][2]
            for key, (enabled, start, run) in rows.items():
                end = start + run
                values = self._v3_timing_labels[key]
                values["start"].setText(self._v3_seconds(start))
                values["run"].setText(self._v3_seconds(run))
                values["end"].setText(self._v3_seconds(end))
                values["delta"].setText(self._v3_seconds(end - ch0_end))
                for label in values.values():
                    label.setEnabled(enabled)
            preview = Experiment2(wfg_config=wfg, do_clock_settings=do_config)
            completion = self.app._ad2_completion_wait_seconds(preview)
            self._v3_completion_budget.setText(
                f"Shared AD2 completion budget: {completion:.3f} s (maximum enabled analog/digital end)."
            )
        except (IndexError, TypeError, ValueError) as exc:
            self._v3_completion_budget.setText(f"Shared AD2 completion budget unavailable: {exc}")

        repeats = self.exp_repeats.value()
        scan_count = len(self._experiment_frequency_scan_list_hz())
        scan_text = (
            f"frequency scan {scan_count}/{repeats} repeats"
            if self.exp_freq_scan_enable.isChecked()
            else "frequency scan off"
        )
        dynamic_text = (
            f"DIO1 start slots {min(repeats, len(self.camera_start_array))}/{repeats}"
            if self.dynamic_camera_start.isChecked()
            else "fixed DIO1 start"
        )
        self._v3_series_relationship_summary.setText(f"Relationship checks: {scan_text}; {dynamic_text}.")

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
            suffix = "available" if repeats <= slots else "insufficient — run will reject beyond slot 10"
            self._v3_dio_slot_budget.setText(f"{min(repeats, slots)}/{repeats} repeats; {slots} slots {suffix}")
        else:
            self._v3_dio_slot_budget.setText("Not used; fixed start applies to every repeat")
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
        if hasattr(self, "_v3_timing_labels"):
            self._refresh_v3_relationships()
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

        note = QLabel("Manual AD2 waveform test. These settings do not affect experiment runs.")
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

        note = QLabel("Manual pump and valve controls. P01/P02 fluid routing requires bench confirmation.")
        note.setWordWrap(True)
        note.setMaximumWidth(700)
        layout.addWidget(note)

        pump_group = QGroupBox("Pump operations")
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
        stop.setMinimumHeight(50)
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
        flush_form.addRow(flush)
        self._add_tooltip_icons(flush_form)

        syringe_group = QGroupBox("Syringe setup and calibration")
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

        note = QLabel(
            "Manual camera controls. Settings used by an experiment are marked; fields unused by the "
            "current runtime are retained separately."
        )
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
        save = QPushButton("Save last captured image")
        save.setToolTip("Saves the frame buffer populated by the Camera panel's Capture single image action.")
        save.clicked.connect(self._start_save_sequence)
        browse = QPushButton("Browse...")
        browse.clicked.connect(lambda: self._browse_folder(self.sequence_path))
        path_row = QHBoxLayout()
        path_row.addWidget(self.sequence_path, 1)
        path_row.addWidget(browse)
        form.addRow(start)
        form.addRow(stop)
        form.addRow(trigger)
        form.addRow("Output folder", path_row)
        form.addRow(save)
        return group

    def _v3_camera_roi_group(self) -> QGroupBox:
        group = QGroupBox("Camera region of interest (ROI)")
        form = QFormLayout(group)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.addRow("Horizontal offset", self.roi_h_offset)
        form.addRow("Vertical offset", self.roi_v_offset)
        form.addRow("Horizontal size", self.roi_h_size)
        form.addRow("Vertical size", self.roi_v_size)
        form.addRow("Exposure time (ms)", self.exposure_ms)
        form.addRow("Center ROI", self.center_roi)
        configure = QPushButton("Apply camera settings")
        configure.setToolTip("Applies exposure, region-of-interest, and Sequence tab settings to the camera.")
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
        group = QGroupBox("Sequence timing")
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
        self._add_tooltip_icons(form)
        return group

    def _v3_camera_trigger_group(self) -> QGroupBox:
        group = QGroupBox("Camera trigger")
        form = QFormLayout(group)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.addRow("Camera trigger source", self.dcam_source)
        form.addRow("Trigger polarity", self.external_polarity)
        form.addRow("Trigger delay (s)", self.external_delay)
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
        hint = QLabel("Apply camera settings before starting. Motion requires explicit confirmation.")
        hint.setWordWrap(True)
        hint.setMaximumWidth(280)
        layout.addWidget(hint)
        layout.addStretch(1)
        return group

    def _zscan_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        note = QLabel("Manual calibration workflow only. Motion requires explicit confirmation.")
        note.setWordWrap(True)
        note.setMaximumWidth(620)
        layout.addWidget(note)

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


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    install_focus_wheel_guard(app)
    window = MainWindowV3(app=Application(ad2=SimulatedAD2Sdk()))
    window.show()
    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
