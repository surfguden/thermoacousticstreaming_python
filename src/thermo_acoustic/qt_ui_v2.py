from __future__ import annotations

import math
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
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

from .ad2 import WaveformFunction, waveform_parameter_policy
from .application import (
    Application,
    STEP_CAPTURE_FRAMES,
    STEP_CONFIGURE_CAMERA,
    STEP_CONFIGURE_WFG,
    STEP_FLUSH,
    STEP_INITIALIZE_EXPERIMENT,
    STEP_ORDER,
    STEP_SAVE_RESULTS,
    STEP_WAIT_FOR_AD2_COMPLETION,
)
from .hardware_factory import HardwareRuntimeConfig, apply_hardware_bundle, build_hardware_bundle
from .instruments import SimulatedAD2Sdk
from .qt_ui import (
    HistoryLogWidget,
    MainWindow,
    WaveformGraph,
    _hardware_reference_tabs,
    install_focus_wheel_guard,
)


def _synthesize_wfg_wave(
    function: WaveformFunction,
    frequency_hz: float,
    amplitude_v: float,
    offset_v: float,
    symmetry_percent: float,
    phase_deg: float,
    num_points: int,
    duration_s: float,
) -> list[float]:
    """Computed (not hardware-read) preview of one AD2 carrier waveform,
    reusing qt_ui.py's own _preview_points()'s per-function shapes
    (Sine/Square/Triangle/DC), extended to add Symmetry -- not present in
    _preview_points(), which only ever previews channel 0 with symmetry
    ignored. Symmetry here matches the real AD2/WaveForms SDK's own
    definition: a time-axis warp, where the first `symmetry_percent` of
    each period maps to the first half of the underlying shape and the
    remainder maps to the second half (FDwfAnalogOutNodeSymmetrySet),
    rather than a duty-cycle-only interpretation limited to Square."""
    phase = math.radians(phase_deg)
    # Clamped away from the exact 0/100 edges to avoid a zero-width half
    # (division by zero) while a field is mid-edit.
    symmetry = min(max(symmetry_percent / 100.0, 0.001), 0.999)
    points: list[float] = []
    for index in range(num_points):
        t = index / max(num_points - 1, 1) * duration_s
        cycle = math.fmod(frequency_hz * t, 1.0)
        if cycle < 0:
            cycle += 1.0
        if cycle < symmetry:
            x = cycle / symmetry * 0.5
        else:
            x = 0.5 + (cycle - symmetry) / (1.0 - symmetry) * 0.5
        angle = math.tau * x + phase
        if function == WaveformFunction.SQUARE:
            raw = 1.0 if math.sin(angle) >= 0 else -1.0
        elif function == WaveformFunction.TRIANGLE:
            tri_x = (angle / math.tau) % 1.0
            raw = 2.0 * abs(2.0 * (tri_x - math.floor(tri_x + 0.5))) - 1.0
        elif function == WaveformFunction.DC:
            raw = 0.0
        else:
            raw = math.sin(angle)
        points.append(offset_v + amplitude_v * raw)
    return points


class InitializationDialog(QDialog):
    """Preview initialization dialog with per-device progress rows."""

    DEVICE_NAMES = ("AD2", "Camera", "Pump", "Valve", "Z-stage", "TEC")

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
        # Device | Simulate | Enable (device identity first, then whether
        # it's simulated, then whether it's enabled at all -- a top-down
        # decision order for an operator reading left to right; was
        # Enable | Simulate | Device before this reorder).
        grid.addWidget(QLabel("Device"), 0, 0)
        grid.addWidget(QLabel("Simulate"), 0, 1)
        grid.addWidget(QLabel("Enable"), 0, 2)
        grid.addWidget(QLabel("Progress"), 0, 3)

        rows = (
            ("AD2", window.ad2_enabled, window.sim_ad2),
            ("Camera", window.camera_enabled, window.sim_camera),
            ("Pump", window.pump_enabled, window.sim_pump),
            ("Valve", window.valve_enabled, window.sim_valve),
            ("Z-stage", window.z_enabled, self._z_stage_simulate_placeholder()),
            ("TEC", window.tec_enabled, window.sim_tec),
        )
        for row, (name, enable, simulate) in enumerate(rows, start=1):
            label = QLabel("Waiting")
            self._status_labels[name] = label
            # Enable/Simulate checkboxes already carry their own tooltip
            # (window._build_state()) -- wrapped directly (their own "Off/On"
            # text is the row's only label) since there's no separate
            # row-label widget in this grid layout to place an icon beside.
            grid.addWidget(QLabel(name), row, 0)
            grid.addWidget(window._wrap_with_tooltip_icon(simulate), row, 1)
            grid.addWidget(window._wrap_with_tooltip_icon(enable), row, 2)
            grid.addWidget(label, row, 3)
        # Was setColumnStretch(0, 1) -- gave ALL extra horizontal space to
        # the Device column specifically, whose own content ("AD2"/
        # "Camera"/etc.) is short and never needed it, which visually
        # shoved Simulate/Enable/Progress far to the right of the device
        # names they belong to. The real driver of the surplus width isn't
        # this grid's own content -- it's the sibling "Hardware Details"
        # QFormLayout below, whose Qmix SDK path fields are
        # _widen_for_content()'d to fit real, long Windows paths (~800px)
        # and force the whole dialog wide; QVBoxLayout then stretches this
        # grid to match. Moving the stretch to the Progress column (whose
        # variable-length status text -- "Waiting"/"Complete (...)"/"Failed"
        # -- can actually use the room) keeps Device/Simulate/Enable snug
        # against each other regardless of how wide a sibling group makes
        # the dialog, instead of spreading all four columns out evenly.
        grid.setColumnStretch(3, 1)
        return group

    def _z_stage_simulate_placeholder(self) -> QCheckBox:
        checkbox = QCheckBox("N/A")
        checkbox.setEnabled(False)
        checkbox.setToolTip(
            "Z stage has no Simulate checkbox on the Initialization tab either -- when enabled, "
            "hardware_factory.build_hardware_bundle() always connects to the real Thorlabs piezo "
            "(thorlabs_piezo.PiezoStage), with no simulated variant."
        )
        return checkbox

    def _hardware_details_group(self, window: QWidget) -> QGroupBox:
        # v3 design-idea adoption, Proposal 5 (2026-08-06): was one flat
        # form mixing live-wired fields (Thorlabs/APT serial, Valve
        # resource, TEC resource, Cetoni config path) with informational-
        # only reference paths (Qmix SDK/QMIXSDK paths) and fields retained
        # purely for migration reference (Z stage backend, Prior VISA
        # resource, Thorlabs/APT backend, Thorlabs/APT discovery only) --
        # all disabled the same way regardless of which very different
        # category they were actually in. Grouped into task-oriented tabs
        # instead, same shared helper qt_ui.py's own Initialization tab
        # now also uses.
        group = QGroupBox("Hardware Details")
        layout = QVBoxLayout(group)
        layout.addWidget(_hardware_reference_tabs(window, self._mark_unwired_stub))
        return group

    @staticmethod
    def _mark_unwired_stub(widget: QWidget) -> QWidget:
        widget.setEnabled(False)
        widget.setToolTip("Not wired to a real backend")
        return widget

    def reset(self) -> None:
        for name in self.DEVICE_NAMES:
            self.set_device_status(name, "Waiting")

    def set_device_status(self, device_name: str, status: str) -> None:
        label = self._status_labels.get(device_name)
        if label is None:
            return
        label.setText(status)


# Short tooltip labels for _StepBreadcrumb's markers -- same run_experiment2()
# step order application.py's STEP_ORDER defines, without the "N. " prefix
# (the marker's own position already encodes the number). Previously matched
# ExperimentSequenceView's own numbered card titles; that card-per-step view
# was retired when v2's configuration column adopted task-oriented setup tabs
# (v3 design-idea adoption, Proposal B, 2026-08-05) -- this dict is now the
# only place these step titles are spelled out for v2.
_STEP_BREADCRUMB_TITLES: dict[str, str] = {
    STEP_INITIALIZE_EXPERIMENT: "Initialize Experiment",
    STEP_CONFIGURE_WFG: "Configure WFG",
    STEP_CONFIGURE_CAMERA: "Configure Camera",
    STEP_CAPTURE_FRAMES: "Capture Frames",
    STEP_WAIT_FOR_AD2_COMPLETION: "Wait For AD2 Completion",
    STEP_FLUSH: "Flush",
    STEP_SAVE_RESULTS: "Save Results",
}


class _StepBreadcrumb(QWidget):
    """Phase 3 (2026-08-04): a horizontal at-a-glance marker row for
    run_experiment2()'s 7-step sequence, driven by the exact same
    progress("step_started"/"step_completed"/"step_failed"/"step_reset",
    ...) events _report_step() and the explicit reset calls in
    application.py already fire (see MainWindow._step_states/
    _handle_worker_progress() in qt_ui.py -- this widget is a renderer for
    that shared state, not a second independent listener). Previously
    described as the live counterpart to ExperimentSequenceView's static
    Configuration Mode cards; that view was retired (v3 design-idea
    adoption, Proposal B, 2026-08-05) in favor of task-oriented setup tabs
    -- this widget is unaffected, since it never depended on that view.

    TEC-scan design decision (recorded alongside application.py's STEP_*
    constants): SetTecTarget/WaitTecStable wrap this same 7-step sequence
    from outside, once per temperature point -- deliberately not markers
    here. The current temperature point/target is a separate indicator,
    out of scope for this widget (flagged as a follow-up candidate, not
    built here -- see the Phase 3 investigation notes).

    Deliberately does NOT show a distinct "stopping" visual during a
    graceful-stop (Session 78/80's "Stopping after this repeat/temperature
    point..." indicator, shown elsewhere): the in-flight unit still runs to
    real completion during a graceful stop, so this breadcrumb keeps
    reporting that real in-progress state unchanged -- inventing a second,
    competing "stopping" visual here would duplicate a message that already
    has one home.
    """

    _STATE_STYLE: dict[str, tuple[str, str]] = {
        # (symbol, color). Colors match already-established conventions
        # elsewhere in this window: gray = not yet reached (matches
        # _make_status_dot's "disabled"/"not connected" gray), dodgerblue =
        # actively running (matches _set_status_dot's "running" blue, the
        # only existing "in progress" color in this codebase), green =
        # completed/calm-confirmation (matches connection_button's/
        # _set_status_dot's "connected" green), red = failed (matches
        # connection_button's "* Not Connected" abnormal-state red -- this
        # codebase has no separate step-level failure color to reuse, so
        # this is the established abnormal-state color generally).
        "pending": ("○", "gray"),
        "active": ("●", "dodgerblue"),
        "completed": ("●", "green"),
        "failed": ("●", "red"),
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self._markers: dict[str, QLabel] = {}
        self._states: dict[str, str] = {}
        for step_name in STEP_ORDER:
            marker = QLabel()
            marker.setToolTip(_STEP_BREADCRUMB_TITLES[step_name])
            layout.addWidget(marker)
            self._markers[step_name] = marker
        layout.addStretch(1)
        self.set_states(dict.fromkeys(STEP_ORDER, "pending"))

    def set_states(self, states: dict[str, str]) -> None:
        for index, (step_name, marker) in enumerate(self._markers.items(), start=1):
            state = states.get(step_name, "pending")
            self._states[step_name] = state
            symbol, color = self._STATE_STYLE[state]
            marker.setText(f"{symbol}{index}")
            marker.setStyleSheet(f"color: {color}; font-weight: bold;")

    def state_of(self, step_name: str) -> str:
        return self._states.get(step_name, "pending")


class MainWindowV2(MainWindow):
    """Opt-in transitional UI that reuses the existing shared hardware runtime."""

    _MANUAL_PANEL_BUILDERS: dict[str, str] = {
        # WFG maps to a v2-only wrapper (_wfg_manual_panel_content), not
        # directly to qt_ui.py's own _wfg_tab() -- Phase 2 Part A adds a
        # live computed-waveform preview beside the WFG (Manual Test)
        # window specifically (matching Digilent WaveForms' own config +
        # live-preview convention), without touching qt_ui.py: the wrapper
        # re-parents _wfg_tab()'s existing, unmodified content whole and
        # places the new preview panel beside it, the same
        # reuse-not-rebuild approach already used throughout this class.
        "WFG": "_wfg_manual_panel_content",
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
    # Subclasses can improve presentation terminology without changing the
    # manual WFG controls or synthesis path they inherit.
    _WFG_PREVIEW_CHANNEL_LABELS: tuple[str, str] = ("Ch1", "Ch2")

    @classmethod
    def _panel_display_name(cls, panel_name: str) -> str:
        return cls._PANEL_DISPLAY_NAMES.get(panel_name, panel_name)

    def __init__(self, app: Application | None = None) -> None:
        self._initialization_dialog: InitializationDialog | None = None
        self._manual_panels: dict[str, QDialog] = {}
        super().__init__(app=app)
        self.setWindowTitle("Thermo Acoustic Streaming - Transitional UI (shared hardware runtime)")
        self.resize(1440, 860)
        self._seed_experiment_ad2_from_wfg_once()
        self._refresh_status()

    def _build_layout(self) -> None:
        self._build_menu_bar()

        root = QWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)

        layout.addWidget(self._left_navigation(), 0)
        layout.addWidget(self._configuration_column(), 1)
        layout.addWidget(self._live_monitoring_column(), 0)

    def _build_menu_bar(self) -> None:
        menu = self.menuBar()
        exit_action = menu.addAction("Exit", self._exit_app)
        exit_action.setObjectName("menuExitAction")
        stop_action = menu.addAction("Abort", self._abort)
        stop_action.setObjectName("menuAbortAction")
        stop_action.setToolTip(
            "Stops after the current repeat, or after the current temperature point during a TEC scan. "
            "It does not stop hardware in the middle of an operation."
        )
        stop_action.setStatusTip(stop_action.toolTip())
        save_action = menu.addAction("Save Settings", self._save_settings)
        save_action.setObjectName("menuSaveSettingsAction")
        load_action = menu.addAction("Load Settings", self._load_settings)
        load_action.setObjectName("menuLoadSettingsAction")

    def _left_navigation(self) -> QWidget:
        panel = QWidget()
        panel.setMaximumWidth(170)
        layout = QVBoxLayout(panel)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.connection_button = QPushButton("* Not Connected")
        self.connection_button.clicked.connect(self._open_initialization_dialog)
        layout.addWidget(self.connection_button)

        # Phase 2 Part B: sidebar connection/status dots, reusing Global
        # Status's own underlying state (updated alongside it in
        # _refresh_status(), not independently). WFG/MSO both reflect the
        # same physical AD2 device; PumpValve gets two independent dots
        # since Pump and Valve are two separate devices that can genuinely
        # differ (confirmed, not assumed). ZScan gets none: its camera
        # usage shares self.app.camera (same state Camera's own dot
        # already shows), but its piezo operations use a fresh,
        # disconnect-after-use PiezoStage instance per call, never
        # self.app.z_motor -- there is no persistent state anywhere that
        # actually reflects Z-Scan's own operational readiness, and a dot
        # showing only half the picture (camera only) would misleadingly
        # imply more than it means. Left unindicated rather than
        # fabricated; see the Phase 2 Part B investigation notes.
        self._sidebar_status_dots: dict[str, QLabel] = {}
        for name in ("WFG", "MSO", "PumpValve", "Camera", "ZScan"):
            button = QPushButton(self._panel_display_name(name))
            button.clicked.connect(lambda checked=False, panel_name=name: self._open_manual_panel(panel_name))
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(4)
            row.addWidget(button, 1)
            if name == "PumpValve":
                pump_dot = self._make_status_dot("Pump")
                valve_dot = self._make_status_dot("Valve")
                self._sidebar_status_dots["Pump"] = pump_dot
                self._sidebar_status_dots["Valve"] = valve_dot
                row.addWidget(pump_dot)
                row.addWidget(valve_dot)
            elif name in ("WFG", "MSO", "Camera"):
                dot = self._make_status_dot({"WFG": "AD2", "MSO": "AD2", "Camera": "Camera"}[name])
                self._sidebar_status_dots[name] = dot
                row.addWidget(dot)
            layout.addLayout(row)

        layout.addStretch(1)
        return panel

    @staticmethod
    def _make_status_dot(device_label: str) -> QLabel:
        dot = QLabel("●")
        dot.setFixedWidth(14)
        dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dot.setStyleSheet("color: gray;")
        dot.setToolTip(f"{device_label}: disabled")
        return dot

    @staticmethod
    def _set_status_dot(dot: QLabel, device_label: str, *, enabled: bool, connected: bool, running: bool) -> None:
        # Same three-state convention as elsewhere in this window: green
        # matches connection_button's own existing "connected" color
        # (_refresh_status()); grey covers both "disabled" and "not yet
        # connected" (Global Status's own text rows already collapse
        # those two into a single "Not connected"/"Disabled" read, so a
        # dot distinguishing them further would say more than the rest of
        # the window does); blue is new -- there was no existing
        # "actively running" color to reuse anywhere in this app.
        if not enabled:
            color, state_text = "gray", "disabled"
        elif running:
            color, state_text = "dodgerblue", "running"
        elif connected:
            color, state_text = "green", "connected"
        else:
            color, state_text = "gray", "not connected"
        dot.setStyleSheet(f"color: {color};")
        dot.setToolTip(f"{device_label}: {state_text}")

    def _configuration_column(self) -> QScrollArea:
        # Restructure (2026-08-03, proposal 2): configuration content (set
        # before a run) separated from live-monitoring content (watched
        # during/after a run) -- matching Digilent WaveForms' own
        # config-panel + live-preview convention and the SCADA principle
        # that live status stays visible without scrolling past
        # configuration. This column keeps its own independent scroll --
        # it's still long on its own (the WFG step alone is ~535px) -- and
        # no longer shares one scroll with the live-monitoring column
        # (_live_monitoring_column()), so growing configuration content
        # can't push live status out of view, and the AD2 Output
        # Parameters table's own inner horizontal scroll no longer forces
        # this column (or the live one) to also scroll horizontally with
        # it (v2 audit finding 1d, 2026-08-02).
        area = QScrollArea()
        area.setWidgetResizable(True)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # v3 design-idea adoption, Proposal A (2026-08-05): the primary run
        # control goes first, inside this column -- not stacked above the
        # config/live-monitoring split (see
        # _experiment_primary_run_control_group()'s own comment for why
        # that placement was deliberately avoided).
        layout.addWidget(self._experiment_primary_run_control_group())

        # v3 design-idea adoption, Proposal B (2026-08-05): task-oriented
        # setup tabs replace the former per-step card sequence -- see
        # _v2_experiment_setup_tabs()'s own comment for why this is safe
        # (no live functionality lived in the retired card view). TEC now
        # lives inside the "Advanced" tab rather than as its own section
        # rendered outside the step list -- that "wraps from outside"
        # relationship was specific to the per-repeat card sequence, which
        # no longer exists here.
        layout.addWidget(self._v2_experiment_setup_tabs())

        area.setWidget(content)
        return area

    def _live_monitoring_column(self) -> QScrollArea:
        # Persistent live-monitoring panel (restructure proposal 2): status/
        # progress, waveform preview, and connection/error state together in
        # one column, separate from configuration, so they stay visible
        # without needing to scroll past configuration content -- at the
        # 1440x860 reference size this column fits well within the window's
        # own height. Deliberately NOT wrapped in a QScrollArea (unlike the
        # configuration column): "Global Status" uses QFormLayout's
        # WrapLongRows with dynamically-changing wordWrap()'d labels (e.g.
        # the valve's status_note passthrough). The root cause of that
        # symptom (confirmed by direct experiment, 2026-08-03) was NOT the
        # scroll area itself -- it was error_log's/self.status's own
        # vertical QSizePolicy having been set to Maximum (an earlier,
        # since-reverted attempt at fixing HistoryLogWidget's row-growth
        # risk; see _v2_status_progress_group()/_global_status_panel()),
        # which broke QFormLayout's heightForWidth recompute for its OTHER
        # WrapLongRows rows once inside a setWidgetResizable(True) scroll
        # area. With that reverted in favor of capping each tooltip-icon
        # wrapper's height instead, wrapping this column in its own scroll
        # area is safe again and restores a safety net for smaller windows
        # (matching every other panel in this codebase) instead of letting
        # "Global Status" get squeezed below its own minimumSizeHint, as it
        # did at 980x680 without one.
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setMaximumWidth(320)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        layout.addWidget(self._v2_status_progress_group())
        layout.addWidget(self._v2_waveform_group())
        layout.addWidget(self._global_status_panel())

        area.setWidget(content)
        return area

    def _v2_experiment_setup_tabs(self) -> QTabWidget:
        # v3 design-idea adoption, Proposal B (2026-08-05): replaces the
        # former ExperimentSequenceView numbered-card-per-step display
        # (Phase 2, Configuration Mode) with task-oriented tabs -- grouping
        # by what an operator is actually configuring, not by
        # run_experiment2()'s internal step order. Safe to retire: that
        # card view was confirmed static (its own docstring: "Phase 2...
        # no live wiring"), and the live step-progress feedback Phase 3 was
        # meant to add there instead went into the fully separate
        # _StepBreadcrumb widget in the Status/Progress group -- unaffected
        # by this change. CaptureFrames/WaitForAd2Completion/SaveResults
        # had no Experiment-tab-specific configuration of their own before
        # (they got add_step_card()'s honest placeholder), so nothing here
        # replaces them -- their real behavior is still entirely derived
        # from the other steps' settings, now organized under the tabs
        # below. Each existing group-box builder is re-parented whole into
        # the tab it most directly matches, not split field-by-field, same
        # discipline the old card mapping used.
        tabs = QTabWidget()

        ad2_content = QWidget()
        ad2_layout = QVBoxLayout(ad2_content)
        ad2_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        ad2_layout.addWidget(self._v2_ad2_output_group())
        # Category 7 (Session 39): FM Sweep and Frequency Scanning are both
        # real, fully-wired Experiment-tab features in qt_ui.py -- both bind
        # the exact same self.exp_sweep_*/self.exp_freq_scan_* widgets
        # qt_ui.py's Experiment tab uses.
        fm_freq_row = QHBoxLayout()
        fm_freq_row.addWidget(self._experiment_fm_sweep_group())
        fm_freq_row.addWidget(self._experiment_frequency_scan_group())
        ad2_layout.addLayout(fm_freq_row)
        tabs.addTab(self._v2_setup_scroll_page(ad2_content), "AD2 Output")

        camera_content = QWidget()
        camera_layout = QVBoxLayout(camera_content)
        camera_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        camera_layout.addWidget(self._v2_acquisition_group())
        tabs.addTab(self._v2_setup_scroll_page(camera_content), "Camera")

        fluidics_content = QWidget()
        fluidics_layout = QVBoxLayout(fluidics_content)
        fluidics_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        fluidics_note = QLabel("Optional post-capture pump/valve workflow. Disabled by default.")
        fluidics_note.setWordWrap(True)
        fluidics_note.setMaximumWidth(520)
        fluidics_layout.addWidget(fluidics_note)
        flush_group = self._experiment_flush_group()
        # Sequential, not concurrent (confirmed against the real LabVIEW
        # source and the current Python implementation): valve switches to
        # position 1, THEN the pump moves, THEN the valve switches to
        # position 2 -- the pump is idle during each switch, not flowing
        # through it. Previously the retired step-card's own tooltip;
        # moved onto the group box directly so hovering it still surfaces
        # the same safety-relevant explanation.
        flush_group.setToolTip(
            "Sequential, not concurrent (confirmed against the real LabVIEW source and the "
            "current Python implementation): valve switches to position 1, THEN the pump "
            "moves, THEN the valve switches to position 2 -- the pump is idle during each "
            "switch, not flowing through it."
        )
        fluidics_layout.addWidget(flush_group)
        fluidics_layout.addStretch(1)
        tabs.addTab(self._v2_setup_scroll_page(fluidics_content), "Fluidics")

        advanced_content = QWidget()
        advanced_layout = QVBoxLayout(advanced_content)
        advanced_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        advanced_note = QLabel("Simulated by default. Real TEC operation remains unapproved.")
        advanced_note.setWordWrap(True)
        advanced_note.setMaximumWidth(520)
        advanced_layout.addWidget(advanced_note)
        advanced_layout.addWidget(self._experiment_temperature_group())
        advanced_layout.addStretch(1)
        tabs.addTab(self._v2_setup_scroll_page(advanced_content), "Advanced")

        return tabs

    @staticmethod
    def _v2_setup_scroll_page(content: QWidget) -> QScrollArea:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.setWidget(content)
        return area

    def _v2_status_progress_group(self) -> QGroupBox:
        group = QGroupBox("Status / Progress")
        # 187, not the old 175 -- Phase 3 step-progress breadcrumb
        # (2026-08-04) added its own row above Elapsed Time/Time Left/# queue,
        # which added another row's worth of height this group's own
        # minimumSizeHint now requires
        # (test_v2_no_group_box_is_squeezed_below_its_minimum_size_hint
        # caught this: needed >=187 at 1440x860, measured empirically -- same
        # pattern as the 140->175 bump restructure proposal 2 needed).
        group.setMinimumHeight(187)
        outer = QVBoxLayout(group)

        # Phase 3 step-progress breadcrumb (2026-08-04): placed first, above
        # Elapsed Time/Time Left/queue count, since "which step is running
        # right now" is the most immediately relevant at-a-glance answer this
        # group gives -- and this group is the one built to stay visible
        # without scrolling (see _live_monitoring_column()).
        self.step_breadcrumb = _StepBreadcrumb()
        self.step_breadcrumb.setToolTip(
            "Live progress through the current repeat's 7-step sequence "
            "(hover a marker for its step name). During a TEC temperature "
            "scan, this same sequence is reused/reset once per temperature "
            "point -- SetTecTarget/WaitTecStable/the post-stable hold run "
            "before it, not shown here."
        )
        outer.addWidget(self.step_breadcrumb)

        self.status = HistoryLogWidget()
        self.status.setMaximumHeight(90)
        self.status.setToolTip(
            "Full session history of every status change, newest at the bottom -- "
            "not just the most recent one. Scroll up to review; scroll back to the "
            "bottom (or wait for the next update while already at the bottom) to "
            "resume auto-scrolling."
        )
        self.queue_count = QLabel("0")

        # Elapsed Time / Time Left / queue count sit in their own narrow
        # top row; Status gets a full-width row below (restructure
        # proposal 2, 2026-08-03) -- previously all four were side-by-side
        # grid columns, sized for the old wide center column. Squeezed into
        # the new ~320px-wide live-monitoring side column, that 4-column
        # layout's own natural width (measured: 870px, driven mostly by
        # self.status's old setMinimumWidth(320) competing for space
        # alongside 3 sibling columns) forced this one group into its own
        # horizontal scroll. Stacking Status on its own row removes that
        # competition entirely -- it can use the group's full width instead
        # of a quarter of it.
        top_row = QGridLayout()
        # Live values and progress handling are inherited from qt_ui.MainWindow;
        # this surface only supplies its own compact presentation captions.
        top_row.addWidget(QLabel("Elapsed Time"), 0, 0)
        top_row.addWidget(self._wrap_with_tooltip_icon(self._elapsed_time_label()), 1, 0)
        top_row.addWidget(QLabel("Estimated time remaining"), 0, 1)
        top_row.addWidget(self._wrap_with_tooltip_icon(self._time_left_label()), 1, 1)
        top_row.addWidget(QLabel("# elements in queue"), 0, 2)
        top_row.addWidget(self.queue_count, 1, 2)
        outer.addLayout(top_row)

        outer.addWidget(QLabel("Status"))
        # v2 audit Step 1f fix (2026-08-03): was a bare grid.addWidget(self.status,
        # ...) -- unlike its own sibling widgets above (Elapsed Time/Time
        # Left, both wrapped), a widget placed directly in a QGridLayout
        # never passes through _add_tooltip_icons() (QFormLayout-only), so
        # this one's long tooltip was left un-HTML-wrapped and without its
        # own click-triggered "i" icon -- same gap qt_ui.py's own
        # self.status had.
        status_wrapper = self._wrap_with_tooltip_icon(self.status)
        # Cap the WRAPPER's height too, not just self.status's own
        # maximumHeight(90) above -- _TooltipIconWrapper is a bare QWidget
        # whose own maximumHeight defaults to unbounded, and self.status's
        # inherited Expanding vertical QSizePolicy can still pull the
        # wrapper (and this row) taller than intended. Deliberately NOT
        # changing self.status's own QSizePolicy to do this (tried first):
        # confirmed by direct experiment that setting a HistoryLogWidget's
        # own vertical policy to Maximum, when it shares a QFormLayout with
        # OTHER WrapLongRows rows (see _global_status_panel()'s error_log
        # below), breaks THOSE OTHER rows' heightForWidth recompute on a
        # later text change -- capping the wrapper's height instead avoids
        # that side effect entirely while still fixing the same growth risk.
        status_wrapper.setMaximumHeight(90)
        outer.addWidget(status_wrapper)
        return group

    def _v2_ad2_output_group(self) -> QGroupBox:
        group = QGroupBox("AD2 Output Parameters CH0 / CH1")
        group.setMinimumHeight(260)
        outer = QVBoxLayout(group)

        content = QWidget()
        grid = QGridLayout(content)
        headers = (
            "Enable", "Function", "Frequency (kHz)", "Amplitude (V)", "Offset / DC Level (V)",
            "Start (s)", "Run (s)", "cRepeat", "Trigger Source",
            "Symmetry / Duty (%)", "Phase (Deg)", "Repeat Trigger",
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
        self._bind_dc_incompatible_experiment_features(self.exp_ch1_function)
        self._size_ad2_output_columns(grid, headers)

        # The outer configuration column shrinks this group's content to fit
        # the window (QScrollArea.setWidgetResizable(True) in
        # _configuration_column), which otherwise compresses/truncates
        # these 10 columns at moderate widths. Give the table its own
        # non-resizable scroll area so it keeps its natural width and
        # scrolls horizontally instead of compressing when the window is
        # narrower than that -- and, since restructure proposal 2
        # (2026-08-03) split configuration from live-monitoring into
        # separate columns, this horizontal scroll now stays local to this
        # table/column instead of also forcing the live-monitoring column
        # to scroll horizontally with it.
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
        base_tooltips = {key: state[key].toolTip() for key in ("frequency", "amplitude", "offset", "symmetry", "phase")}
        def refresh(function_text: str) -> None:
            policy = waveform_parameter_policy(function_text)
            help_text = dict(policy.help_text)
            for key, enabled in (
                ("frequency", policy.frequency_applicable),
                ("amplitude", policy.amplitude_applicable),
                ("offset", policy.offset_applicable),
                ("symmetry", policy.symmetry_applicable),
                ("phase", policy.phase_applicable),
            ):
                state[key].setEnabled(policy.visible and enabled)
                base_tooltip = base_tooltips[key]
                state[key].setToolTip(
                    f"{base_tooltip}\n{help_text[key]}" if base_tooltip else help_text[key]
                )
        state["function"].currentTextChanged.connect(refresh)
        refresh(state["function"].currentText())

    def _v2_acquisition_group(self) -> QGroupBox:
        group = QGroupBox("Acquisition Parameters")
        group.setMinimumHeight(300)
        grid = QGridLayout(group)
        # v3 design-idea adoption, Proposal 4 (2026-08-06): names the real
        # DIO1 relationship these fields' own tooltips already explain --
        # matching qt_ui.py's own equivalent captions.
        acquisition_rows = (
            ("Camera FPS (drives DIO1 LED clock)", self.exp_camera_fps),
            ("Camera Start (s) (DIO1 pulse delay)", self.exp_camera_start),
            ("Repeats", self.exp_repeats),
            ("Frames", self.exp_frames),
            ("Exposure time (ms)", self.exp_exposure_ms),
            ("GlobalExposure", self.global_exposure),
        )
        for row, (text, widget) in enumerate(acquisition_rows):
            grid.addWidget(QLabel(text), row, 0)
            grid.addWidget(self._wrap_with_tooltip_icon(widget), row, 1)

        camera_start = QGroupBox("Camera Start Array(s) (per-repeat DIO1 delays)")
        camera_start_layout = QGridLayout(camera_start)
        # Dynamic Camera Start Time moved here from the acquisition grid's own
        # column -- it's the toggle controlling whether this array is used at
        # all (see qt_ui.py's _experiment_do_clock_config()), so it belongs
        # with the array it controls rather than the other, unrelated
        # acquisition params (matching the same regroup applied in qt_ui.py's
        # own _camera_start_group()).
        camera_start_layout.addWidget(QLabel("Dynamic Camera Start Time (per-repeat DIO1 delays)"), 0, 0)
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

    # --- Phase 2 Part A: WFG (Manual Test) live computed waveform preview ---

    def _wfg_manual_panel_content(self) -> QWidget:
        # Wraps qt_ui.py's own _wfg_tab() unchanged (config left) with a
        # new, v2-only computed preview panel (right) -- matches Digilent
        # WaveForms' own config-panel + live-preview convention, and the
        # same layout MSO's tab already uses within qt_ui.py itself
        # (_mso_tab()'s "MSO Configuration" + "Waveform" groups side by
        # side). Unlike MSO's preview (real captured samples, refreshed on
        # a Capture button click), this one is a SYNTHESIZED waveform
        # computed from the current Ch1/Ch2 field values -- there is no
        # real hardware read involved, and it updates live as fields
        # change, not on a button click.
        content = QWidget()
        layout = QHBoxLayout(content)
        layout.addWidget(self._wfg_tab(), 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self._wfg_preview_group(), 1, Qt.AlignmentFlag.AlignTop)
        self._update_wfg_preview()
        return content

    def _wfg_preview_group(self) -> QGroupBox:
        group = QGroupBox("Waveform Preview (computed)")
        layout = QVBoxLayout(group)
        note = QLabel(
            "Synthesized from the current Ch1/Ch2 field values, not read from "
            "hardware -- recalculates as you edit Function/Frequency/Amplitude/"
            "Offset/Symmetry/Phase/Enable below. Disabled channels are omitted."
        )
        note.setObjectName("manualWfgPreviewDescription")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.wfg_preview_graph = WaveformGraph()
        layout.addWidget(self.wfg_preview_graph)

        # Debounced live recompute (Part A Step 1 finding: no per-keystroke
        # live-recompute precedent exists elsewhere in this app to reuse --
        # MSO's own graph only updates on its Capture button click -- so a
        # short singleShot debounce, restarted on every relevant field
        # change, is used here instead of recomputing synchronously on
        # every keystroke).
        self._wfg_preview_timer = QTimer(self)
        self._wfg_preview_timer.setSingleShot(True)
        self._wfg_preview_timer.setInterval(150)
        self._wfg_preview_timer.timeout.connect(self._update_wfg_preview)
        for state in self.wfg_channels:
            state["function"].currentTextChanged.connect(self._schedule_wfg_preview_update)
            state["enable"].stateChanged.connect(self._schedule_wfg_preview_update)
            for key in ("frequency", "amplitude", "offset", "symmetry", "phase"):
                state[key].valueChanged.connect(self._schedule_wfg_preview_update)

        return group

    def _schedule_wfg_preview_update(self) -> None:
        self._wfg_preview_timer.start()

    def _update_wfg_preview(self) -> None:
        enabled_channels = [
            (label, state)
            for label, state in zip(
                self._WFG_PREVIEW_CHANNEL_LABELS,
                self.wfg_channels,
                strict=True,
            )
            if state["enable"].isChecked()
        ]
        if not enabled_channels:
            self.wfg_preview_graph.set_series({}, 1.0)
            return

        # Show enough of the time axis to see multiple periods of the
        # slowest enabled channel -- a channel with 0 Hz (an edge case
        # while a field is mid-edit) is skipped from the duration
        # calculation, not treated as "very slow."
        frequencies_hz = [state["frequency"].value() * 1000.0 for _, state in enabled_channels]
        positive_frequencies_hz = [f for f in frequencies_hz if f > 0]
        slowest_hz = min(positive_frequencies_hz) if positive_frequencies_hz else 1.0
        duration_s = 3.0 / slowest_hz
        num_points = 400

        series = {}
        for label, state in enabled_channels:
            frequency_hz = state["frequency"].value() * 1000.0
            series[label] = _synthesize_wfg_wave(
                function=WaveformFunction(state["function"].currentText()),
                frequency_hz=frequency_hz,
                amplitude_v=state["amplitude"].value(),
                offset_v=state["offset"].value(),
                symmetry_percent=state["symmetry"].value(),
                phase_deg=state["phase"].value(),
                num_points=num_points,
                duration_s=duration_s,
            )
        self.wfg_preview_graph.set_series(series, num_points / duration_s)

    def _make_waveform_graph(self) -> WaveformGraph:
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

        self.error_log = HistoryLogWidget()
        self.error_log.setMaximumHeight(90)
        # Real-platform rendering bug (2026-08-03): HistoryLogWidget inherits
        # QListWidget's default Expanding vertical QSizePolicy. Combined with
        # this form's WrapLongRows, the row's wrap-vs-side-by-side decision
        # is width-timing-sensitive on the real platform (offscreen always
        # wrapped cleanly; the real platform sometimes didn't) -- when it
        # doesn't wrap, QFormLayout gives this row's field CELL a height
        # driven by the Expanding policy (measured: 575px, vs. the widget's
        # own 90px maximumHeight-capped size), then vertically CENTERS the
        # small widget inside that oversized cell. The widget itself still
        # renders correctly -- the ~485px of empty cell above/below it is
        # what a screenshot reads as "a solid black rectangle" swallowing
        # the actual log content. Fixed below (after _add_tooltip_icons()
        # wraps this row) by capping the WRAPPER's own height -- NOT by
        # changing self.error_log's own vertical QSizePolicy, which was
        # tried first and reverted: this form has multiple WrapLongRows
        # rows (AD2/Camera/Pump/Valve below all use wordWrap() for runtime
        # text like the valve's status_note passthrough), and setting
        # error_log's own policy to Maximum was confirmed by direct
        # experiment to break THOSE OTHER rows' heightForWidth recompute on
        # a later text change (e.g. valve_connection_status getting stuck
        # at an 8px single-line height instead of re-wrapping to its real
        # ~40px). Capping the wrapper's height instead fixes the same
        # growth risk without that side effect.
        self.error_log.setToolTip(
            "Full session history of every status/code/source event, newest at the "
            "bottom -- not just the most recent one. code is always '0' when "
            "status='OK', '1' on any caught exception -- not a real DCAM/AD2/Qmix "
            "error code, just a boolean flag (_handle_worker_finished())."
        )
        # v3 design-idea adoption, Proposal 2 (2026-08-06): "Error Out" was
        # literal LabVIEW-era jargon describing a display mode this widget
        # no longer has -- shared caption fix with qt_ui.py's own
        # _error_panel().
        form.addRow("Status and error history", self.error_log)

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
        # See the comment above self.error_log.setToolTip() -- cap the
        # tooltip-icon wrapper's own height (unbounded by default) instead
        # of error_log's vertical QSizePolicy, which has already been
        # created by _add_tooltip_icons() above at this point.
        self.error_log.parentWidget().setMaximumHeight(90)
        return group

    def _open_initialization_dialog(self) -> None:
        dialog = self._ensure_initialization_dialog()
        dialog.show()
        dialog.raise_()

    def _ensure_initialization_dialog(self) -> InitializationDialog:
        if self._initialization_dialog is None:
            self._initialization_dialog = InitializationDialog(self, self._start_initialize)
        return self._initialization_dialog

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
            thorlabs_apt_serial=self.thorlabs_apt_serial.text(),
            valve_resource=self.valve_resource.text(),
            cetoni_config_path=self.cetoni_config_path.text(),
            tec_enabled=self.tec_enabled.isChecked(),
            sim_tec=self.sim_tec.isChecked(),
            tec_port=self.tec_port.text(),
        )
        self._run_action(lambda progress: self._initialize_system(config, progress), "Initializing")

    def _initialize_system(self, config: HardwareRuntimeConfig, progress=None) -> str:
        if progress:
            progress("status", "Opening selected hardware")
        try:
            self.app.cleanup()
        except Exception as exc:
            self.app.check_loop_error(exc)
            raise RuntimeError(
                "Existing hardware cleanup failed; refusing to initialize a replacement hardware bundle."
            ) from exc

        apply_hardware_bundle(self.app, build_hardware_bundle(config))
        self.app.initialize(progress=progress)
        return "System Initialized"

    def _handle_worker_progress(self, kind: str, value) -> None:
        if kind == "init_device":
            device_name, status = value
            self._ensure_initialization_dialog().set_device_status(str(device_name), str(status))
            return
        super()._handle_worker_progress(kind, value)

    def _refresh_step_breadcrumb(self) -> None:
        # Overrides the base (v1) no-op: base MainWindow._step_states is the
        # shared source of truth (updated by _handle_worker_progress() just
        # before this is called); this only renders it. hasattr-guarded the
        # same way _refresh_status() below guards its own v2-only widgets,
        # since step_breadcrumb only exists once _v2_status_progress_group()
        # has actually built it, not for every MainWindow subclass.
        if hasattr(self, "step_breadcrumb"):
            self.step_breadcrumb.set_states(self._step_states)

    def _refresh_status(self) -> None:
        super()._refresh_status()
        if not hasattr(self, "ad2_connection_status"):
            return

        self.ad2_connection_status.setText(self._connected_text(getattr(self.app.ad2, "enabled", True), getattr(self.app.ad2, "device_handle", None)))
        self.camera_connection_status.setText(self._connected_text(getattr(self.app.camera, "enabled", True), getattr(self.app.camera, "handle", None)))
        # Uses `initialized` (did initialize() succeed), not `referenced`
        # (did a physical reference move complete) -- matches the Valve
        # row's own `initialized`-based pattern just below. `referenced`
        # tracks a real hardware calibration prerequisite for absolute-
        # position dosing commands (set_fill_level() etc.), a separate
        # concept from basic connectivity.
        self.pump_connection_status.setText("Disabled" if not getattr(self.app.pump, "enabled", True) else ("Connected" if getattr(self.app.pump, "initialized", False) else "Not connected"))
        self.valve_connection_status.setText(self._valve_connection_text())

        if hasattr(self, "connection_button"):
            # Bug fix (found during v3 design evaluation, verified against
            # this project's own real hardware-status logic before
            # adopting): previously `connected = self.app.status ==
            # "System Initialized"` -- app.status is a general status
            # string overwritten by every later action (a flush, a
            # refill, an experiment run...), so the button flipped to red
            # "* Not Connected" after the first successful action following
            # initialization, even though hardware was still fully
            # connected. Now derived from the same per-device connection
            # labels just computed above (each already "Disabled"/"Not
            # connected"/"Connected"/"Connected (...)" per their own
            # _connected_text()/_valve_connection_text() logic) instead of
            # the transient status string -- a device that is deliberately
            # disabled does not count against the overall "connected"
            # claim, but no enabled device may be "Not connected", and at
            # least one device must be enabled (an all-disabled session is
            # not "connected").
            device_texts = (
                self.ad2_connection_status.text(),
                self.camera_connection_status.text(),
                self.pump_connection_status.text(),
                self.valve_connection_status.text(),
            )
            enabled_texts = [text for text in device_texts if text != "Disabled"]
            connected = bool(enabled_texts) and all(
                text == "Connected" or text.startswith("Connected") for text in enabled_texts
            )
            self.connection_button.setText("* Connected" if connected else "* Not Connected")
            self.connection_button.setStyleSheet("color: green;" if connected else "color: red;")

        wfg_config = getattr(self.app.ad2, "wfg_config", None)
        self.ad2_running_status.setText("Yes" if getattr(wfg_config, "running", False) else "No")
        self.camera_capturing_status.setText("Yes" if getattr(self.app.camera, "capturing", False) else "No")
        # Reads the "experiment_series_active" flag qt_ui.py's
        # _run_experiment_series() brackets its own execution with (see
        # qt_ui.py's _build_state()/_handle_worker_progress()) -- not a
        # status-text substring match. The prior "experiment" in
        # self.app.status.lower() heuristic went stale the instant Abort was
        # clicked: Abort's own "Stopping after {unit}..." status overwrites
        # self.app.status while the series' current repeat may still
        # genuinely be executing,
        # which would have made this indicator misleadingly report "No"
        # while hardware was still active.
        self.experiment_running_status.setText("Yes" if getattr(self, "_experiment_series_active", False) else "No")
        self.valve_position_status.setText(self._valve_position_text())
        dosing = "dosing" if getattr(self.app.pump, "dosing", False) else "idle"
        self.pump_state_status.setText(f"{dosing}, fill {getattr(self.app.pump, 'fill_level', 0.0):.3f} ml")

        # Phase 2 Part B: sidebar dots reuse the exact same state reads as
        # Global Status's own rows just above, so the two never disagree.
        if hasattr(self, "_sidebar_status_dots"):
            ad2_enabled = getattr(self.app.ad2, "enabled", True)
            ad2_connected = getattr(self.app.ad2, "device_handle", None) is not None
            ad2_running = getattr(wfg_config, "running", False)
            for dot_name in ("WFG", "MSO"):
                dot = self._sidebar_status_dots.get(dot_name)
                if dot is not None:
                    self._set_status_dot(dot, "AD2", enabled=ad2_enabled, connected=ad2_connected, running=ad2_running)

            camera_dot = self._sidebar_status_dots.get("Camera")
            if camera_dot is not None:
                self._set_status_dot(
                    camera_dot,
                    "Camera",
                    enabled=getattr(self.app.camera, "enabled", True),
                    connected=getattr(self.app.camera, "handle", None) is not None,
                    running=getattr(self.app.camera, "capturing", False),
                )

            pump_dot = self._sidebar_status_dots.get("Pump")
            if pump_dot is not None:
                self._set_status_dot(
                    pump_dot,
                    "Pump",
                    enabled=getattr(self.app.pump, "enabled", True),
                    connected=getattr(self.app.pump, "initialized", False),
                    running=getattr(self.app.pump, "dosing", False),
                )

            valve_dot = self._sidebar_status_dots.get("Valve")
            if valve_dot is not None:
                self._set_status_dot(
                    valve_dot,
                    "Valve",
                    enabled=getattr(self.app.valve, "enabled", True),
                    connected=getattr(self.app.valve, "initialized", False),
                    running=False,
                )

        # Force an explicit height correction on the wrapped connection-
        # status labels (restructure proposal 2, 2026-08-03): QFormLayout's
        # WrapLongRows heightForWidth recompute on a later setText() was
        # confirmed unreliable now that "Global Status" lives inside the
        # live-monitoring column's setWidgetResizable(True) scroll area --
        # heightForWidth() itself always reports the correct height, but
        # the row's actual allocated geometry doesn't reliably pick it up
        # automatically (order/timing-sensitive on sibling widget
        # construction elsewhere in the same scroll content, not just this
        # group's own state -- confirmed layout().invalidate()+activate()
        # on both the group's own QFormLayout and the scroll area's content
        # layout do NOT reliably fix it either). A same-call resize() also
        # doesn't help: label.width() itself hasn't settled to its final
        # value yet at this exact point in the call stack (still reads the
        # pre-refresh width), so heightForWidth(label.width()) computes
        # against a stale width and produces another wrong answer.
        # Deferring one event-loop turn via QTimer.singleShot(0, ...) lets
        # Qt's own pending layout pass settle each label's width first,
        # THEN corrects its height against that now-final width -- a
        # workaround for what appears to be a real PySide6 layout quirk in
        # this specific nesting, not a proper long-term pattern, but
        # confirmed to reproduce correctly and consistently where every
        # synchronous alternative did not.
        def _fix_wrapped_label_heights() -> None:
            # Guards against the window (and these labels) having been
            # deleted before this deferred callback fires -- a real
            # scenario, not defensive-for-its-own-sake: the test suite's
            # own cleanup fixture closes and deleteLater()s every window
            # between tests, and a still-pending 0ms timer from THIS
            # refresh can outlive that if a later test's processEvents()
            # call is what finally lets it fire (confirmed: raised
            # "Internal C++ object already deleted" during conftest.py's
            # own cleanup fixture without this guard).
            try:
                for label in (
                    self.ad2_connection_status,
                    self.camera_connection_status,
                    self.pump_connection_status,
                    self.valve_connection_status,
                ):
                    label.resize(label.width(), label.heightForWidth(label.width()))
            except RuntimeError:
                pass

        QTimer.singleShot(0, _fix_wrapped_label_heights)

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
        # The status response confirms a numeric protocol position, not the
        # physical routing. Keep v2's only live readout aligned with the v1
        # Pump&Valve controls by showing P01/P02 rather than Open/Closed.
        position = getattr(self.app.valve, "position", None)
        if position == 1:
            return "1 (P01)"
        if position == 2:
            return "2 (P02)"
        return "Unknown"


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    install_focus_wheel_guard(app)
    window = MainWindowV2(app=Application(ad2=SimulatedAD2Sdk()))
    window.show()
    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
