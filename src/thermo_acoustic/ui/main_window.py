from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QEvent, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QButtonGroup,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..application.commands import (
    Ad2ScopeReadResult,
    CameraFrameProgress,
    CameraSequenceResult,
    CameraSnapshotResult,
    CommandEvent,
    CommandResult,
    ConfirmationRequest,
)
from ..application.event_formatting import detailed_event_text, event_summary
from ..application.experiment_runner import BATCH_ACTIVE_STATES
from ..application.simple_series import simple_series_settings_from_profile, simple_series_settings_to_profile
from ..domain.models import ConnectionState, DeviceId, DeviceStatus, OperatingMode
from .device_panels import DevicePanel, PANEL_TYPES
from .workflow_panel import WorkflowPanel
from .experiment_panel import ExperimentPanel
from .saved_frames_window import SavedFramesWindow
from .simple_series_panel import SimpleSeriesPanel
from .status_dashboard import StatusDashboard


PROFILE_SCHEMA_VERSION = 2
_TERMINAL_STATES = {"completed", "failed", "cancelled"}
_TAB_LABELS = {
    DeviceId.AD2: "AD2",
    DeviceId.PUMP: "Pump",
    DeviceId.VALVE: "Valve",
    DeviceId.CAMERA: "Camera",
    DeviceId.TEC: "TEC",
    DeviceId.Z_STAGE: "Z-stage",
}


class MainWindow(QMainWindow):
    def __init__(self, controller, parent=None, *, ui_log_writer=None):
        super().__init__(parent)
        self.controller = controller
        self._ui_log_writer = ui_log_writer
        self._requests: dict[str, tuple[DevicePanel | WorkflowPanel, str]] = {}
        self._scroll_pages: dict[QWidget, QScrollArea] = {}
        self.setWindowTitle("Thermo-acoustic control — Simulation mode" if
                            controller.mode is OperatingMode.SIMULATION else "Thermo-acoustic control")
        # Content scrolls inside the panels, so the window may be small; the initial size
        # follows the screen it opens on instead of a fixed height.
        self.setMinimumSize(900, 560)
        available = self.screen().availableGeometry() if self.screen() is not None else None
        self.resize(min(1280, int(available.width() * 0.95)) if available else 1280,
                    min(860, int(available.height() * 0.92)) if available else 860)
        root = QWidget()
        root_layout = QVBoxLayout(root)
        self.setCentralWidget(root)
        self._last_action = "Ready"
        self._experiment_status = controller.experiments.status()
        self._panic_status = controller.panic_status()
        header = QHBoxLayout()
        text = QHBoxLayout()
        self.activity_title = QLabel("Idle")
        self.activity_title.setStyleSheet("font-weight: 600")
        self.activity_detail = QLabel("Ready")
        self.activity_detail.setWordWrap(True)
        text.addWidget(self.activity_title)
        text.addWidget(self.activity_detail, 1)
        header.addLayout(text, 1)
        # Three different stops, always visible, in increasing severity.
        self.stop_after_button = QPushButton("Stop after current")
        self.stop_after_button.setToolTip(
            "Let the running experiment finish, then end the batch before the next one. "
            "Nothing is interrupted.")
        self.abort_button = QPushButton("Abort batch")
        self.abort_button.setToolTip(
            "End the batch now: cancel the running experiment and stop the AD2, camera, pump and "
            "valve activity of the batch. An incomplete acquisition is discarded; completed "
            "experiments are kept.")
        self.abort_button.setStyleSheet("QPushButton:enabled { background: #ffe0b2; }")
        self.panic_button = QPushButton("PANIC · Safe stop")
        self.panic_button.setToolTip("Confirm, then urgently stop connected outputs and abort the batch")
        self.panic_button.setStyleSheet(
            "QPushButton:enabled { background: #b71c1c; color: white; font-weight: 700; }")
        self.stop_after_button.setEnabled(False)
        self.abort_button.setEnabled(False)
        self.stop_after_button.clicked.connect(lambda: controller.experiments.stop_after_current())
        self.abort_button.clicked.connect(lambda: controller.experiments.abort())
        self.panic_button.clicked.connect(self._panic)
        for button in (self.stop_after_button, self.abort_button, self.panic_button):
            button.setMinimumHeight(32)
            header.addWidget(button)
        root_layout.addLayout(header)
        root_layout.addLayout(self._navigation_row())

        self.tabs = QTabWidget()
        self.tabs.setMinimumWidth(0)
        self.panels: dict[DeviceId, DevicePanel] = {}
        for device in DeviceId:
            panel = PANEL_TYPES[device]()
            if device is DeviceId.VALVE:
                panel.require_port = controller.mode is OperatingMode.REAL
            panel.command_requested.connect(
                lambda action, command, source=panel: self._submit(source, action, command)
            )
            panel.notice.connect(self._ui_notice)
            self.panels[device] = panel
            self.tabs.addTab(panel, _TAB_LABELS[device])
        self.workflow_panel = WorkflowPanel()
        self.workflow_panel.command_requested.connect(
            lambda action, command: self._submit(self.workflow_panel, action, command)
        )
        self.workflow_panel.abort_requested.connect(controller.cancel_active_workflow)
        self.workflow_panel.notice.connect(self._ui_notice)
        self.tabs.addTab(self._scrolling(self.workflow_panel), "Workflows")
        from .z_stack_panel import ZStackPanel
        self.z_stack_panel = ZStackPanel(controller.z_stack, self.panels[DeviceId.CAMERA])
        self.tabs.addTab(self._scrolling(self.z_stack_panel), "Z stack")
        self.experiment_panel = SimpleSeriesPanel(controller)
        self.tabs.addTab(self.experiment_panel, "Experiments")
        self.dashboard = StatusDashboard()
        self.tabs.addTab(self._scrolling(self.dashboard), "Run monitor")
        self.dashboard.image_window_requested.connect(self._show_camera_image_window)
        self.dashboard.review_requested.connect(self._review_saved_frames)
        self.saved_frames_window: SavedFramesWindow | None = None
        self.builder_window = ExperimentBuilderWindow(controller.experiments, self)
        controller.experiments.confirm_batch = self.confirm_experiment_batch
        controller.experiments.confirm_unchecked = self.confirm_unchecked_preflight
        root_layout.addWidget(self.tabs)
        self.log_window = DetailedLogWindow(self)
        self.log = self.log_window.log
        self._create_file_menu()
        self._create_log_menu()
        self._create_builder_menu()
        self._configure_editor_controls()

        controller.command_event.connect(self._event)
        controller.command_result.connect(self._result)
        controller.command_progress.connect(self._progress)
        controller.status_changed.connect(self._status)
        controller.message.connect(self._ui_notice)
        controller.temperature_monitor.sample.connect(self.panels[DeviceId.TEC].add_temperature_sample)
        controller.temperature_monitor.sample.connect(self.dashboard.add_temperature_sample)
        controller.experiments.changed.connect(self._experiment_changed)
        self._close_after_stop = False
        self._acknowledged_close_errors: tuple[str, ...] = ()
        controller.experiments.changed.connect(self._close_when_batch_stopped)
        controller.z_stack.changed.connect(lambda _status: self._experiment_changed(self._experiment_status))
        controller.panic_changed.connect(self._panic_changed)
        self._status(controller.statuses())
        self._experiment_changed(self._experiment_status)
        self.tabs.currentChanged.connect(self._sync_navigation)
        self.experiment_panel.pages.currentChanged.connect(self._sync_navigation)
        self._sync_navigation()

    def _scrolling(self, widget: QWidget) -> QScrollArea:
        """Tabs without their own scrolling get one, so a short window never squeezes their content."""
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.Shape.NoFrame)
        area.setWidget(widget)
        self._scroll_pages[widget] = area
        return area

    def _navigation_row(self) -> QHBoxLayout:
        """Shortcuts to existing tabs. Navigation only: no command is issued and no step is required."""
        row = QHBoxLayout()
        row.addWidget(QLabel("Task:"))
        self._nav_group = QButtonGroup(self)
        self._nav_buttons: dict[str, QPushButton] = {}
        for key, label, tip in (
            ("prepare", "1 Prepare devices", "Connect and set up instruments in the device tabs"),
            ("configure", "2 Configure", "Experiments tab, Configure page"),
            ("review", "3 Review and start", "Experiments tab, Review and start page"),
            ("monitor", "4 Monitor run", "Run monitor tab"),
        ):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setFlat(True)
            button.setToolTip(tip + ". Any tab can be opened at any time.")
            self._nav_group.addButton(button)
            self._nav_buttons[key] = button
            row.addWidget(button)
            button.clicked.connect(lambda _checked=False, name=key: self._navigate(name))
        row.addStretch(1)
        self._last_device_tab = 0
        return row

    def _navigate(self, name: str) -> None:
        if name == "prepare":
            self.tabs.setCurrentIndex(self._last_device_tab)
        elif name in {"configure", "review"}:
            self.tabs.setCurrentWidget(self.experiment_panel)
            self.experiment_panel.pages.setCurrentIndex(0 if name == "configure" else 1)
        elif name == "monitor":
            self.tabs.setCurrentWidget(self._scroll_pages[self.dashboard])

    def _sync_navigation(self, *_args) -> None:
        current = self.tabs.currentWidget()
        if current in self.panels.values() or current in (self._scroll_pages[self.workflow_panel],
                                                          self._scroll_pages[self.z_stack_panel]):
            self._last_device_tab = self.tabs.currentIndex()
            key = "prepare"
        elif current is self.experiment_panel:
            key = "configure" if self.experiment_panel.pages.currentIndex() == 0 else "review"
        elif current is self._scroll_pages[self.dashboard]:
            key = "monitor"
        else:
            key = None
        self._nav_group.setExclusive(False)
        for name, button in self._nav_buttons.items():
            button.setChecked(name == key)
        self._nav_group.setExclusive(True)

    def _review_saved_frames(self, folder: str = "") -> None:
        """Open the saved-frames viewer on ``folder`` (a series or experiment folder) or ask for one.

        The viewer only reads files; it never touches a device or the running batch."""
        if self.saved_frames_window is None:
            self.saved_frames_window = SavedFramesWindow(self)
        window = self.saved_frames_window
        window.show()
        window.raise_()
        window.activateWindow()
        if folder and Path(folder).is_dir():
            window.open_or_report(folder)
        else:
            window.choose_folder(self.dashboard.output_folder or "")

    def _show_camera_image_window(self) -> None:
        window = self.panels[DeviceId.CAMERA].image_window
        window.show()
        window.raise_()
        window.activateWindow()

    def _panic(self) -> None:
        if self.controller.shutdown_started:
            # Closing already issued every stop; Panic can only report what is left,
            # so there is nothing to confirm.
            self.controller.panic_stop()
            return
        answer = QMessageBox.warning(
            self, "Confirm Panic safe stop",
            "Stop connected AD2, pump, camera and TEC outputs and abort the experiment batch? "
            "The valve and Z-stage will hold their current positions.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.controller.panic_stop()
        except Exception as exc:
            QMessageBox.critical(self, "Panic stop failed", str(exc))

    def _panic_changed(self, status: dict) -> None:
        self._panic_status = status
        self.panic_button.setEnabled(status["state"] != "stopping")
        self._experiment_changed(self._experiment_status)
        if status["state"] == "stopping":
            self.experiment_panel.preflight_button.setEnabled(False)
            self.experiment_panel.queue_button.setEnabled(False)
            self.experiment_panel.start_button.setEnabled(False)
            self.builder_window.panel.queue_button.setEnabled(False)
            self.builder_window.panel.start_button.setEnabled(False)
        else:
            current = self.controller.experiments.status()
            self.experiment_panel._status(current)
            self.builder_window.panel._status(current)

    def _experiment_changed(self, status: dict) -> None:
        self._experiment_status = status
        locked = (status["state"] in BATCH_ACTIVE_STATES
                  or self.controller.z_stack.state == "running"
                  or self._panic_status["state"] == "stopping")
        for panel in self.panels.values():
            panel.set_experiment_locked(locked)
        self.workflow_panel.set_experiment_locked(locked)
        self.dashboard.update_experiment(status)
        running = status["state"] == "running" and self._panic_status["state"] != "stopping"
        stop_requested = bool(status.get("stop_after_current"))
        self.stop_after_button.setEnabled(running and not stop_requested)
        self.stop_after_button.setText("Stop requested" if running and stop_requested
                                       else "Stop after current")
        self.abort_button.setEnabled(running)
        self._render_activity()

    def _render_activity(self) -> None:
        panic = self._panic_status
        experiment = self._experiment_status
        state = experiment["state"]
        if panic["state"] == "stopping":
            title, detail = "Safe stop!", f"Waiting for {panic['pending']} instrument stop results…"
        elif panic["state"] == "failed":
            title, detail = "Safe stop incomplete", "; ".join(panic["errors"])
        elif panic["state"] == "completed":
            title, detail = "Idle", "Panic safe stop completed; valve and Z-stage held position"
        elif state == "running":
            number = experiment.get("current_experiment_number")
            count = experiment.get("planned_experiments", 0)
            title = f"Running experiment {number}/{count}…" if number else "Preparing experiment batch…"
            detail = experiment.get("phase", "Running")
        elif state in {"stopping", "aborting"}:
            title, detail = "Safe stop!", experiment.get("phase", "Stopping experiment batch")
        elif state in {"failed", "aborted"}:
            title, detail = "Idle", experiment.get("phase", "Experiment series failed")
        elif state == "completed":
            title, detail = "Idle", "Experiment series completed!"
        elif state == "stopped":
            title, detail = "Idle", "Experiment batch stopped after current experiment"
        else:
            title, detail = "Idle", self._last_action
        self.activity_title.setText(title)
        self.activity_detail.setText(detail)

    def _create_file_menu(self) -> None:
        menu = self.menuBar().addMenu("&File")
        save_action = QAction("Save settings…", self)
        load_action = QAction("Load settings…", self)
        save_action.triggered.connect(self._choose_save_profile)
        load_action.triggered.connect(self._choose_load_profile)
        menu.addAction(save_action)
        menu.addAction(load_action)
        menu.addSeparator()
        review_action = QAction("Review saved frames…", self)
        review_action.triggered.connect(lambda: self._review_saved_frames())
        menu.addAction(review_action)

    def _create_log_menu(self) -> None:
        menu = self.menuBar().addMenu("&Log")
        show_action = QAction("Show detailed log…", self)
        show_action.triggered.connect(self._show_log)
        menu.addAction(show_action)

    def _create_builder_menu(self) -> None:
        menu = self.menuBar().addMenu("Experiment &builder")
        show_action = QAction("Show experiment builder…", self)
        show_action.triggered.connect(self._show_builder)
        menu.addAction(show_action)

    def _show_builder(self) -> None:
        self.builder_window.show()
        self.builder_window.raise_()
        self.builder_window.activateWindow()

    def _show_log(self) -> None:
        self.log_window.show()
        self.log_window.raise_()
        self.log_window.activateWindow()

    def _configure_editor_controls(self) -> None:
        for widget in self.findChildren(QAbstractSpinBox):
            widget.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            widget.setKeyboardTracking(False)
            widget.installEventFilter(self)
        for widget in self.findChildren(QComboBox):
            widget.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        if event.type() is QEvent.Type.Wheel and isinstance(
            watched, (QAbstractSpinBox, QComboBox)
        ):
            event.ignore()
            return True
        return super().eventFilter(watched, event)

    def _submit(self, panel: DevicePanel | WorkflowPanel, action: str, command) -> None:
        panel.mark_pending(action, command.request_id)
        self._requests[command.request_id] = (panel, action)
        try:
            self.controller.submit(command)
        except Exception as exc:
            self._requests.pop(command.request_id, None)
            panel.clear_pending(command.request_id)
            panel.show_notice(f"Command was not submitted: {exc}")

    def confirm_operation(self, request: ConfirmationRequest) -> bool:
        answer = QMessageBox.question(
            self, "Confirm hardware operation", request.prompt,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Yes

    def confirm_experiment_batch(self, summary: str) -> bool:
        answer = QMessageBox.warning(
            self, "Confirm real-hardware experiment batch", summary,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Yes

    def confirm_unchecked_preflight(self, summary: str) -> bool:
        answer = QMessageBox.warning(
            self, "Count preflight not current", summary,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _event(self, event: CommandEvent) -> None:
        line = detailed_event_text(event)
        self.log.append(line)
        if self._ui_log_writer is not None:
            self._ui_log_writer.write(line)
        summary = event_summary(event)
        if summary is not None:
            self.statusBar().showMessage(summary)
            if event.source in {"ui", "console"}:
                self._last_action = summary
                if self._experiment_status["state"] in {"completed", "failed", "aborted", "stopped"}:
                    self._experiment_status = {**self._experiment_status, "state": "idle"}
                if self._panic_status["state"] in {"completed", "failed"}:
                    self._panic_status = {"state": "idle", "pending": 0, "errors": ()}
                self._render_activity()
        if event.state in _TERMINAL_STATES:
            target = (
                self.panels[event.device] if event.device is not None
                else self.workflow_panel
            )
            if summary is not None:
                target.set_feedback(
                    summary, success=event.state == "completed"
                )
            pending = self._requests.pop(event.request_id, None)
            if pending is not None:
                panel, _action = pending
                panel.clear_pending(event.request_id)
            if event.device is not None:
                self.panels[event.device].handle_terminal_event(event)

    def _result(self, result: CommandResult) -> None:
        if result.ok and result.device is not None:
            panel = self.panels[result.device]
            panel.apply_successful_command(result.command)
            panel.handle_result(result.value)

    def _progress(self, request_id: str, value: object) -> None:
        pending = self._requests.get(request_id)
        if pending is None:
            if not isinstance(value, CameraFrameProgress):
                return
            panel = self.panels[DeviceId.CAMERA]
        else:
            panel, _action = pending
        handler = getattr(panel, "handle_progress", None)
        if callable(handler):
            handler(value)

    @staticmethod
    def _result_summary(value: object) -> str:
        if isinstance(value, CameraSnapshotResult):
            shape = getattr(value.frame, "shape", None)
            return f"snapshot captured{f' · shape={shape}' if shape is not None else ''}"
        if isinstance(value, CameraSequenceResult):
            return f"{len(value.frames)} frames · {len(value.timestamps)} timestamps"
        if isinstance(value, Ad2ScopeReadResult):
            counts = ", ".join(
                f"ch{channel}={len(samples)}"
                for channel, samples in sorted(value.samples_by_channel.items())
            )
            return f"scope samples · {counts}"
        text = repr(value)
        return text if len(text) <= 240 else text[:237] + "…"

    def _ui_notice(self, text: str) -> None:
        timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        line = f"{timestamp} · UI · {text}"
        self.log.append(line)
        if self._ui_log_writer is not None:
            self._ui_log_writer.write(line)
        self.statusBar().showMessage(text)

    def _status(self, statuses: dict[DeviceId, DeviceStatus]) -> None:
        for device, status in statuses.items():
            self.panels[device].set_status(status)
        pump = statuses.get(DeviceId.PUMP)
        self.workflow_panel.update_pumps(
            pump.readback if pump is not None and pump.connection is ConnectionState.CONNECTED else None
        )
        self.dashboard.update_statuses(statuses)
        if not self.statusBar().currentMessage():
            self.statusBar().showMessage(
                " | ".join(
                    f"{device.value}: {status.connection.value}"
                    for device, status in statuses.items()
                )
            )

    def profile_document(self) -> dict[str, object]:
        return {
            "schema_version": PROFILE_SCHEMA_VERSION,
            "devices": {
                device.value: panel.profile_values()
                for device, panel in self.panels.items()
            },
            # require_pump_unit=False: saving the form must not require a
            # pump to be connected, unlike actually running an experiment.
            "experiment": simple_series_settings_to_profile(
                self.experiment_panel._settings(require_pump_unit=False)
            ),
        }

    def save_profile(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(self.profile_document(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def load_profile(self, path: str | Path) -> None:
        def reject_constant(value: str) -> None:
            raise ValueError(f"Non-finite JSON number is not allowed: {value}")

        document = json.loads(
            Path(path).read_text(encoding="utf-8"), parse_constant=reject_constant
        )
        if not isinstance(document, dict):
            raise ValueError("Settings profile must be a JSON object")
        schema_version = document.get("schema_version")
        if schema_version not in (1, PROFILE_SCHEMA_VERSION):
            raise ValueError(
                f"Unsupported settings schema version: {document.get('schema_version')!r}"
            )
        devices = document.get("devices")
        if not isinstance(devices, dict):
            raise ValueError("Settings profile must contain a devices object")
        unknown_devices = set(devices) - {device.value for device in DeviceId}
        if unknown_devices:
            raise ValueError(f"Unknown device settings: {', '.join(sorted(unknown_devices))}")
        if schema_version == 1 and isinstance(devices.get("camera"), dict):
            devices = dict(devices)
            camera = dict(devices["camera"])
            for obsolete in (
                "snapshot_exposure_enabled",
                "sequence_exposure_enabled",
                "trigger_enabled",
                "global_exposure_enabled",
            ):
                camera.pop(obsolete, None)
            devices["camera"] = camera
        if isinstance(devices.get("ad2"), dict):
            devices = dict(devices)
            ad2 = dict(devices["ad2"])
            for channel in (1, 2):
                prefix = f"wave_ch{channel}"
                start = ad2.pop(f"{prefix}_sweep_start_hz", None)
                stop = ad2.pop(f"{prefix}_sweep_stop_hz", None)
                if start is not None and stop is not None:
                    ad2[f"{prefix}_sweep_center_hz"] = (start + stop) / 2
                    ad2[f"{prefix}_sweep_width_hz"] = stop - start
            devices["ad2"] = ad2

        validated: dict[DeviceId, dict[str, object]] = {}
        for device, panel in self.panels.items():
            if device.value in devices:
                validated[device] = panel.validate_profile(devices[device.value])
        # Validate everything (including the experiment tab, if present)
        # before applying anything -- a malformed "experiment" object must
        # not leave the device panels half-applied, and vice versa.
        experiment_settings = None
        if "experiment" in document:
            experiment_settings = simple_series_settings_from_profile(document["experiment"])
            # simple_series_settings_from_profile() only checks field
            # *types* -- it has no widget to check against. A type-valid
            # value can still be outside what the real QSpinBox/
            # QDoubleSpinBox can represent (an integer far beyond its
            # range, for instance), which setValue() does not always
            # reject gracefully; checked here, against this panel's own
            # live widgets, before anything is applied.
            self.experiment_panel._validate_settings_ranges(experiment_settings)
        for device, values in validated.items():
            self.panels[device].apply_profile(values)
        if experiment_settings is not None:
            # Pure input restoration: _apply_settings() only calls
            # setValue()/setChecked()/setCurrentIndex() on widgets -- no
            # device command, no queue, no start.
            self.experiment_panel._apply_settings(experiment_settings)

    def _choose_save_profile(self) -> None:
        path, _selected_filter = QFileDialog.getSaveFileName(
            self, "Save device settings", "device-settings.json", "JSON files (*.json)"
        )
        if not path:
            return
        try:
            self.save_profile(path)
            self._ui_notice(f"Saved device settings to {path}")
        except (OSError, TypeError, ValueError) as exc:
            QMessageBox.critical(self, "Could not save settings", str(exc))

    def _choose_load_profile(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self, "Load device settings", "", "JSON files (*.json)"
        )
        if not path:
            return
        try:
            self.load_profile(path)
            self._ui_notice(f"Loaded device settings from {path}; no commands were submitted")
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            QMessageBox.critical(self, "Could not load settings", str(exc))

    def closeEvent(self, event) -> None:
        """Close only when nothing is still running.

        A running batch is stopped through the normal Abort (and its save/flush
        drain) and the window closes by itself afterwards. If a device has not
        finished shutting down, or reported an error, the window stays open and
        says so; closing again retries. No device thread is forced to end.
        """
        controller = self.controller
        experiments = controller.experiments
        if experiments.batch_active:
            controller.begin_close()
            self._close_after_stop = True
            if experiments.status()["state"] == "running":
                experiments.abort("Application window closed during the run")
            self.statusBar().showMessage("Closing: stopping the experiment batch first…")
            event.ignore()
            return
        self._close_after_stop = False
        errors = controller.shutdown()
        pending = controller.shutdown_pending_devices()
        if pending or (errors and tuple(errors) != self._acknowledged_close_errors):
            self._acknowledged_close_errors = () if pending else tuple(errors)
            if pending:
                message = ("Close incomplete: still shutting down: " + ", ".join(pending)
                           + ". The application stays open; close again to retry.")
            else:
                message = ("Close finished with errors: " + "; ".join(errors)
                           + ". Close again to leave anyway.")
            self.statusBar().showMessage(message)
            self.log.append(message)
            # Commands are refused once shutdown has started, so the device tabs cannot
            # do anything; Panic stays and only reports (it cannot interrupt a blocked call).
            self.tabs.setEnabled(False)
            self.panic_button.setToolTip(
                "Closing: stop requests were already issued. Panic now only reports the remaining "
                "devices and cannot interrupt a blocked SDK call.")
            event.ignore()
            return
        self.panels[DeviceId.CAMERA].image_window.close()
        if self.saved_frames_window is not None:
            self.saved_frames_window.close()
        self.builder_window.close()
        event.accept()

    def _close_when_batch_stopped(self, _status: dict) -> None:
        if self._close_after_stop and not self.controller.experiments.batch_active:
            QTimer.singleShot(0, self.close)


def configure_palette(application: QApplication) -> None:
    del application


class DetailedLogWindow(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Detailed command log")
        self.resize(960, 540)
        layout = QVBoxLayout(self)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Detailed command activity will appear here")
        layout.addWidget(self.log)


class ExperimentBuilderWindow(QDialog):
    def __init__(self, manager, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Experiment builder")
        self.resize(1250, 850)
        layout = QVBoxLayout(self)
        self.panel = ExperimentPanel(manager)
        layout.addWidget(self.panel)
