"""V3-owned compatibility support retained while the V2 shell remains available.

This module deliberately contains only the behavior V3 still needs from the
former V2 base: initialization, lazy manual panels, progress/status presenters,
and the computed manual-WFG preview.  It must not import ``qt_ui_v2``.
"""

from __future__ import annotations

import math

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
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

from .ad2 import WaveformFunction
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
from .qt_ui import HistoryLogWidget, MainWindow, WaveformGraph, _hardware_reference_tabs


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
    """Return the same computed (not hardware-read) manual WFG preview."""
    phase = math.radians(phase_deg)
    symmetry = min(max(symmetry_percent / 100.0, 0.001), 0.999)
    points: list[float] = []
    for index in range(num_points):
        t = index / max(num_points - 1, 1) * duration_s
        cycle = math.fmod(frequency_hz * t, 1.0)
        if cycle < 0:
            cycle += 1.0
        x = cycle / symmetry * 0.5 if cycle < symmetry else 0.5 + (cycle - symmetry) / (1.0 - symmetry) * 0.5
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
    """Shared initialization dialog, kept V3-owned during V2 retirement."""

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
        for column, text in enumerate(("Device", "Simulate", "Enable", "Progress")):
            grid.addWidget(QLabel(text), 0, column)
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
            grid.addWidget(QLabel(name), row, 0)
            grid.addWidget(window._wrap_with_tooltip_icon(simulate), row, 1)
            grid.addWidget(window._wrap_with_tooltip_icon(enable), row, 2)
            grid.addWidget(label, row, 3)
        grid.setColumnStretch(3, 1)
        return group

    @staticmethod
    def _z_stage_simulate_placeholder() -> QCheckBox:
        checkbox = QCheckBox("N/A")
        checkbox.setEnabled(False)
        checkbox.setToolTip(
            "Z stage has no Simulate checkbox on the Initialization tab either -- when enabled, "
            "hardware_factory.build_hardware_bundle() always connects to the real Thorlabs piezo "
            "(thorlabs_piezo.PiezoStage), with no simulated variant."
        )
        return checkbox

    def _hardware_details_group(self, window: QWidget) -> QGroupBox:
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
        if label is not None:
            label.setText(status)


_STEP_BREADCRUMB_TITLES = {
    STEP_INITIALIZE_EXPERIMENT: "Initialize Experiment",
    STEP_CONFIGURE_WFG: "Configure WFG",
    STEP_CONFIGURE_CAMERA: "Configure Camera",
    STEP_CAPTURE_FRAMES: "Capture Frames",
    STEP_WAIT_FOR_AD2_COMPLETION: "Wait For AD2 Completion",
    STEP_FLUSH: "Flush",
    STEP_SAVE_RESULTS: "Save Results",
}


class _StepBreadcrumb(QWidget):
    _STATE_STYLE = {
        "pending": ("○", "gray"), "active": ("●", "dodgerblue"),
        "completed": ("●", "green"), "failed": ("●", "red"),
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self._markers: dict[str, QLabel] = {}
        self._states: dict[str, str] = {}
        for step in STEP_ORDER:
            marker = QLabel()
            marker.setToolTip(_STEP_BREADCRUMB_TITLES[step])
            self._markers[step] = marker
            layout.addWidget(marker)
        layout.addStretch(1)
        self.set_states(dict.fromkeys(STEP_ORDER, "pending"))

    def set_states(self, states: dict[str, str]) -> None:
        for index, (step, marker) in enumerate(self._markers.items(), start=1):
            state = states.get(step, "pending")
            self._states[step] = state
            symbol, color = self._STATE_STYLE[state]
            marker.setText(f"{symbol}{index}")
            marker.setStyleSheet(f"color: {color}; font-weight: bold;")

    def state_of(self, step_name: str) -> str:
        return self._states.get(step_name, "pending")


class MainWindowV3Compatibility(MainWindow):
    """The V3 compatibility layer; no V2 import or inheritance is allowed."""

    _MANUAL_PANEL_BUILDERS = {
        "WFG": "_wfg_manual_panel_content", "MSO": "_mso_tab", "PumpValve": "_pump_tab",
        "Camera": "_camera_tab", "ZScan": "_zscan_tab",
    }
    _PANEL_DISPLAY_NAMES = {"PumpValve": "Pump&Valve", "ZScan": "Z-Scan"}
    _WFG_PREVIEW_CHANNEL_LABELS = ("Ch1", "Ch2")

    @classmethod
    def _panel_display_name(cls, panel_name: str) -> str:
        return cls._PANEL_DISPLAY_NAMES.get(panel_name, panel_name)

    def __init__(self, app: Application | None = None) -> None:
        self._initialization_dialog: InitializationDialog | None = None
        self._manual_panels: dict[str, QDialog] = {}
        super().__init__(app=app)
        self._seed_experiment_ad2_from_wfg_once()
        self._refresh_status()

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

    def _v2_status_progress_group(self) -> QGroupBox:
        group = QGroupBox("Status / Progress")
        group.setMinimumHeight(187)
        outer = QVBoxLayout(group)
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
        self.queue_count = QLabel("0")
        top_row = QGridLayout()
        for column, (caption, value) in enumerate((("Elapsed Time", self._elapsed_time_label()), ("Estimated time remaining", self._time_left_label()), ("# elements in queue", self.queue_count))):
            top_row.addWidget(QLabel(caption), 0, column)
            top_row.addWidget(self._wrap_with_tooltip_icon(value), 1, column)
        outer.addLayout(top_row)
        outer.addWidget(QLabel("Status"))
        wrapper = self._wrap_with_tooltip_icon(self.status)
        wrapper.setMaximumHeight(90)
        outer.addWidget(wrapper)
        return group

    def _v2_acquisition_group(self) -> QGroupBox:
        group = QGroupBox("Acquisition Parameters")
        group.setMinimumHeight(300)
        grid = QGridLayout(group)
        for row, (text, widget) in enumerate((("Camera FPS (Internal trigger)", self.exp_camera_fps), ("Camera Start request (s; metadata only)", self.exp_camera_start), ("Repeats", self.exp_repeats), ("Frames", self.exp_frames), ("Exposure time (ms)", self.exp_exposure_ms), ("GlobalExposure", self.global_exposure))):
            grid.addWidget(QLabel(text), row, 0)
            grid.addWidget(self._wrap_with_tooltip_icon(widget), row, 1)
        camera_start = QGroupBox("Camera Start Array(s) (per-repeat metadata)")
        camera_start_layout = QGridLayout(camera_start)
        camera_start_layout.addWidget(QLabel("Dynamic Camera Start Time (per-repeat metadata)"), 0, 0)
        camera_start_layout.addWidget(self._wrap_with_tooltip_icon(self.dynamic_camera_start), 0, 1)
        for index, widget in enumerate(self.camera_start_array):
            camera_start_layout.addWidget(self._wrap_with_tooltip_icon(widget), index // 2 + 1, index % 2)
        grid.addWidget(camera_start, 0, 2, 6, 1)
        grid.setColumnStretch(2, 1)
        return group

    def _v2_waveform_group(self) -> QGroupBox:
        group = QGroupBox("Waveform Preview / Average FPS")
        group.setMinimumHeight(260)
        layout = QVBoxLayout(group)
        row = QHBoxLayout()
        row.addWidget(QLabel("Average FPS"))
        row.addWidget(self.average_fps)
        row.addStretch(1)
        layout.addLayout(row)
        self.waveform_graph = getattr(self, "waveform_graph", None) or WaveformGraph()
        layout.addWidget(self.waveform_graph)
        return group

    def _wfg_manual_panel_content(self) -> QWidget:
        content = QWidget()
        layout = QHBoxLayout(content)
        layout.addWidget(self._wfg_tab(), 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self._wfg_preview_group(), 1, Qt.AlignmentFlag.AlignTop)
        self._update_wfg_preview()
        return content

    def _wfg_preview_group(self) -> QGroupBox:
        group = QGroupBox("Waveform Preview (computed)")
        layout = QVBoxLayout(group)
        note = QLabel("Synthesized from current manual settings; no hardware readback.")
        note.setObjectName("manualWfgPreviewDescription")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.wfg_preview_graph = WaveformGraph()
        layout.addWidget(self.wfg_preview_graph)
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
        enabled = [(label, state) for label, state in zip(self._WFG_PREVIEW_CHANNEL_LABELS, self.wfg_channels, strict=True) if state["enable"].isChecked()]
        if not enabled:
            self.wfg_preview_graph.set_series({}, 1.0)
            return
        frequencies = [state["frequency"].value() * 1000.0 for _, state in enabled]
        positive = [frequency for frequency in frequencies if frequency > 0]
        duration_s = 3.0 / (min(positive) if positive else 1.0)
        num_points = 400
        series = {
            label: _synthesize_wfg_wave(WaveformFunction(state["function"].currentText()), state["frequency"].value() * 1000.0, state["amplitude"].value(), state["offset"].value(), state["symmetry"].value(), state["phase"].value(), num_points, duration_s)
            for label, state in enabled
        }
        self.wfg_preview_graph.set_series(series, num_points / duration_s)

    def _global_status_panel(self) -> QGroupBox:
        group = QGroupBox("Global Status")
        group.setMaximumWidth(300)
        form = QFormLayout(group)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.error_log = HistoryLogWidget()
        self.error_log.setMaximumHeight(90)
        self.error_log.setToolTip(
            "Full session history of every status/code/source event, newest at the "
            "bottom -- not just the most recent one. code is always '0' when "
            "status='OK', '1' on any caught exception -- not a real DCAM/AD2/Qmix "
            "error code, just a boolean flag (_handle_worker_finished())."
        )
        form.addRow("Status and error history", self.error_log)
        for attribute, caption in (("ad2_connection_status", "AD2"), ("camera_connection_status", "Camera"), ("pump_connection_status", "Pump"), ("valve_connection_status", "Valve")):
            label = QLabel("Not connected")
            label.setWordWrap(True)
            setattr(self, attribute, label)
            form.addRow(caption, label)
        self.ad2_running_status = QLabel("No")
        self.camera_capturing_status = QLabel("No")
        self.experiment_running_status = QLabel("No")
        self.valve_position_status = QLabel("Unknown")
        self.pump_state_status = QLabel("Unknown")
        form.addRow("AD2 output running", self.ad2_running_status)
        form.addRow("Camera capturing", self.camera_capturing_status)
        form.addRow("Experiment running", self.experiment_running_status)
        form.addRow("Valve position", self.valve_position_status)
        form.addRow("Pump state / fill level", self.pump_state_status)
        self._add_tooltip_icons(form)
        self.error_log.parentWidget().setMaximumHeight(90)
        return group

    def _open_initialization_dialog(self) -> None:
        dialog = self._ensure_initialization_dialog()
        dialog.show(); dialog.raise_()

    def _ensure_initialization_dialog(self) -> InitializationDialog:
        if self._initialization_dialog is None:
            self._initialization_dialog = InitializationDialog(self, self._start_initialize)
        return self._initialization_dialog

    def _open_manual_panel(self, panel_name: str) -> None:
        dialog = self._ensure_manual_panel(panel_name)
        dialog.show(); dialog.raise_(); dialog.activateWindow()

    def _ensure_manual_panel(self, panel_name: str) -> QDialog:
        dialog = self._manual_panels.get(panel_name)
        if dialog is None:
            content = getattr(self, self._MANUAL_PANEL_BUILDERS[panel_name])()
            dialog = QDialog(self)
            dialog.setWindowTitle(f"{self._panel_display_name(panel_name)} (Manual Test)")
            dialog.setModal(False)
            QVBoxLayout(dialog).addWidget(content)
            self._manual_panels[panel_name] = dialog
        return dialog

    def _start_initialize(self) -> None:
        self._seed_experiment_ad2_from_wfg_once()
        dialog = self._ensure_initialization_dialog(); dialog.reset(); dialog.show()
        config = HardwareRuntimeConfig(ad2_enabled=self.ad2_enabled.isChecked(), sim_ad2=self.sim_ad2.isChecked(), camera_enabled=self.camera_enabled.isChecked(), sim_camera=self.sim_camera.isChecked(), pump_enabled=self.pump_enabled.isChecked(), sim_pump=self.sim_pump.isChecked(), valve_enabled=self.valve_enabled.isChecked(), sim_valve=self.sim_valve.isChecked(), z_enabled=self.z_enabled.isChecked(), thorlabs_apt_serial=self.thorlabs_apt_serial.text(), valve_resource=self.valve_resource.text(), cetoni_config_path=self.cetoni_config_path.text(), tec_enabled=self.tec_enabled.isChecked(), sim_tec=self.sim_tec.isChecked(), tec_port=self.tec_port.text())
        self._run_action(lambda progress: self._initialize_system(config, progress), "Initializing")

    def _initialize_system(self, config: HardwareRuntimeConfig, progress=None) -> str:
        if progress:
            progress("status", "Opening selected hardware")
        try:
            self.app.cleanup()
        except Exception as exc:
            self.app.check_loop_error(exc)
            raise RuntimeError("Existing hardware cleanup failed; refusing to initialize a replacement hardware bundle.") from exc
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
        if hasattr(self, "step_breadcrumb"):
            self.step_breadcrumb.set_states(self._step_states)

    def _refresh_status(self) -> None:
        super()._refresh_status()
        if not hasattr(self, "ad2_connection_status"):
            return
        self.ad2_connection_status.setText(self._connected_text(getattr(self.app.ad2, "enabled", True), getattr(self.app.ad2, "device_handle", None)))
        self.camera_connection_status.setText(self._connected_text(getattr(self.app.camera, "enabled", True), getattr(self.app.camera, "handle", None)))
        self.pump_connection_status.setText("Disabled" if not getattr(self.app.pump, "enabled", True) else ("Connected" if getattr(self.app.pump, "initialized", False) else "Not connected"))
        self.valve_connection_status.setText(self._valve_connection_text())
        wfg_config = getattr(self.app.ad2, "wfg_config", None)
        self.ad2_running_status.setText("Yes" if getattr(wfg_config, "running", False) else "No")
        self.camera_capturing_status.setText("Yes" if getattr(self.app.camera, "capturing", False) else "No")
        self.experiment_running_status.setText("Yes" if getattr(self, "_experiment_series_active", False) else "No")
        self.valve_position_status.setText(self._valve_position_text())
        dosing = "dosing" if getattr(self.app.pump, "dosing", False) else "idle"
        self.pump_state_status.setText(f"{dosing}, fill {getattr(self.app.pump, 'fill_level', 0.0):.3f} ml")

        def _fix_wrapped_label_heights() -> None:
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
        return "Disabled" if not enabled else ("Connected" if handle is not None else "Not connected")

    def _valve_connection_text(self) -> str:
        valve = self.app.valve
        if not getattr(valve, "enabled", True): return "Disabled"
        if not getattr(valve, "initialized", False): return "Not connected"
        status_note = getattr(valve, "status_note", "")
        return f"Connected ({status_note})" if status_note and status_note != "confirmed" else "Connected"

    def _valve_position_text(self) -> str:
        return {1: "1 (P01)", 2: "2 (P02)"}.get(getattr(self.app.valve, "position", None), "Unknown")
