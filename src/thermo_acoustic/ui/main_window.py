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
    QLabel,
    QMainWindow,
    QMessageBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..application.commands import (
    Ad2ScopeReadResult,
    CameraSequenceResult,
    CameraSnapshotResult,
    CommandEvent,
    CommandResult,
    ConfirmationRequest,
)
from ..application.event_formatting import detailed_event_text, event_summary
from ..domain.models import DEVICE_LABELS, DeviceId, DeviceStatus
from .device_panels import DevicePanel, PANEL_TYPES


PROFILE_SCHEMA_VERSION = 1
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
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._requests: dict[str, tuple[DevicePanel, str]] = {}
        self.setWindowTitle("Thermo-acoustic control")
        self.setMinimumSize(960, 1080)
        self.resize(1100, 1080)
        root = QWidget()
        root_layout = QVBoxLayout(root)
        self.setCentralWidget(root)
        root_layout.addWidget(
            QLabel(f"Mode: {controller.mode.value} (simulation is the safe default)")
        )

        self.tabs = QTabWidget()
        self.tabs.setMinimumWidth(0)
        self.panels: dict[DeviceId, DevicePanel] = {}
        for device in DeviceId:
            panel = PANEL_TYPES[device]()
            panel.command_requested.connect(
                lambda action, command, source=panel: self._submit(source, action, command)
            )
            panel.notice.connect(self._ui_notice)
            self.panels[device] = panel
            self.tabs.addTab(panel, _TAB_LABELS[device])
        root_layout.addWidget(self.tabs)
        self.log_window = DetailedLogWindow(self)
        self.log = self.log_window.log
        self._create_file_menu()
        self._create_log_menu()
        self._configure_editor_controls()

        controller.command_event.connect(self._event)
        controller.command_result.connect(self._result)
        controller.status_changed.connect(self._status)
        self._status(controller.statuses())

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

    def _show_log(self) -> None:
        self.log_window.show()
        self.log_window.raise_()
        self.log_window.activateWindow()

    def _configure_editor_controls(self) -> None:
        for widget in self.findChildren(QAbstractSpinBox):
            widget.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
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

    def _submit(self, panel: DevicePanel, action: str, command) -> None:
        panel.mark_pending(action, command.request_id)
        self._requests[command.request_id] = (panel, action)
        try:
            self.controller.submit(command)
        except Exception as exc:
            self._requests.pop(command.request_id, None)
            panel.clear_pending(command.request_id)
            panel.show_notice(f"Command was not submitted: {exc}")

    def confirm_real_connection(self, device: DeviceId) -> bool:
        answer = QMessageBox.question(
            self,
            "Connect real hardware",
            f"Connect to the real {DEVICE_LABELS[device]}?",
        )
        return answer is QMessageBox.StandardButton.Yes

    def confirm_operation(self, request: ConfirmationRequest) -> bool:
        answer = QMessageBox.question(self, "Confirm hardware operation", request.prompt)
        return answer is QMessageBox.StandardButton.Yes

    def _event(self, event: CommandEvent) -> None:
        self.log.append(detailed_event_text(event))
        summary = event_summary(event)
        if summary is not None:
            self.statusBar().showMessage(summary, 7000)
        if event.state in _TERMINAL_STATES:
            pending = self._requests.pop(event.request_id, None)
            if pending is not None:
                panel, _action = pending
                panel.clear_pending(event.request_id)

    def _result(self, result: CommandResult) -> None:
        if result.ok and result.device is not None:
            self.panels[result.device].handle_result(result.value)

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
        self.log.append(f"{timestamp} · UI · {text}")
        self.statusBar().showMessage(text, 5000)

    def _status(self, statuses: dict[DeviceId, DeviceStatus]) -> None:
        for device, status in statuses.items():
            self.panels[device].set_status(status)
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
        if document.get("schema_version") != PROFILE_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported settings schema version: {document.get('schema_version')!r}"
            )
        devices = document.get("devices")
        if not isinstance(devices, dict):
            raise ValueError("Settings profile must contain a devices object")
        unknown_devices = set(devices) - {device.value for device in DeviceId}
        if unknown_devices:
            raise ValueError(f"Unknown device settings: {', '.join(sorted(unknown_devices))}")

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
