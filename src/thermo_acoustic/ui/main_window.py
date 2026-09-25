from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QEvent
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
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
from ..domain.models import ConnectionState, DeviceId, DeviceStatus, OperatingMode
from .device_panels import DevicePanel, PANEL_TYPES
from .workflow_panel import WorkflowPanel
from .experiment_panel import ExperimentPanel
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
        self.setWindowTitle("Thermo-acoustic control — Simulation mode" if
                            controller.mode is OperatingMode.SIMULATION else "Thermo-acoustic control")
        self.setMinimumSize(960, 1080)
        self.resize(1100, 1080)
        root = QWidget()
        root_layout = QVBoxLayout(root)
        self.setCentralWidget(root)
        self._last_action = "Ready"
        self._experiment_status = controller.experiments.status()
        self._panic_status = controller.panic_status()
        header = QHBoxLayout()
        text = QVBoxLayout()
        self.activity_title = QLabel("Idle")
        self.activity_detail = QLabel("Ready")
        self.activity_detail.setWordWrap(True)
        text.addWidget(self.activity_title)
        text.addWidget(self.activity_detail)
        header.addLayout(text, 1)
        self.panic_button = QPushButton("PANIC · Safe stop")
        self.panic_button.setToolTip("Confirm, then urgently stop connected outputs and abort the batch")
        self.panic_button.clicked.connect(self._panic)
        header.addWidget(self.panic_button)
        root_layout.addLayout(header)

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
        self.tabs.addTab(self.workflow_panel, "Workflows")
        self.experiment_panel = SimpleSeriesPanel(controller)
        self.tabs.addTab(self.experiment_panel, "Experiments")
        self.dashboard = StatusDashboard()
        self.tabs.addTab(self.dashboard, "Status")
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
        controller.panic_changed.connect(self._panic_changed)
        self._status(controller.statuses())
        self._experiment_changed(self._experiment_status)

    def _panic(self) -> None:
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
        locked = (status["state"] in {"running", "stopping", "aborting"}
                  or self._panic_status["state"] == "stopping")
        for panel in self.panels.values():
            panel.set_experiment_locked(locked)
        self.workflow_panel.set_experiment_locked(locked)
        self.dashboard.update_experiment(status)
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
        for device, values in validated.items():
            self.panels[device].apply_profile(values)

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
        self.panels[DeviceId.CAMERA].image_window.close()
        self.builder_window.close()
        self.controller.shutdown()
        event.accept()


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
