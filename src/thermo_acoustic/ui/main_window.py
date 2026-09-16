from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..application.commands import (
    CommandEvent,
    ConfirmationRequest,
    DeviceCommand,
    DeviceOperation,
    PumpSetFlowArgs,
    TecApplySetpointsArgs,
    ValveSetPositionArgs,
    ZStageSetPositionArgs,
)
from ..domain.models import DeviceId


class MainWindow(QMainWindow):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle("Thermo-acoustic control")
        self.resize(760, 520)
        root = QWidget()
        layout = QVBoxLayout(root)
        self.setCentralWidget(root)
        layout.addWidget(QLabel(f"Mode: {controller.mode.value} (simulation is safe default)"))
        self.device = QComboBox()
        self.device.addItems([device.value for device in DeviceId])
        layout.addWidget(self.device)
        self.value = QDoubleSpinBox()
        self.value.setRange(-10000, 10000)
        self.value.setValue(100)
        layout.addWidget(self.value)
        actions = (
            ("Connect", DeviceOperation.CONNECT),
            ("Disconnect", DeviceOperation.DISCONNECT),
            ("Pump set flow", DeviceOperation.PUMP_FLOW_SET),
            ("Valve position 1", DeviceOperation.VALVE_POSITION_SET),
            ("Camera snapshot", DeviceOperation.CAMERA_SNAPSHOT_CAPTURE),
            ("TEC set temperature", DeviceOperation.TEC_SETPOINTS_APPLY),
            ("Z-stage check closed loop", DeviceOperation.Z_STAGE_CLOSED_LOOP_REQUIREMENT_READ),
            ("Z-stage enable closed loop", DeviceOperation.Z_STAGE_CLOSED_LOOP_ENABLE),
            ("Z-stage move", DeviceOperation.Z_STAGE_POSITION_SET),
        )
        for label, operation in actions:
            button = QPushButton(label)
            button.clicked.connect(
                lambda checked=False, selected=operation: self._submit(selected)
            )
            layout.addWidget(button)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log)
        controller.command_event.connect(self._event)
        controller.status_changed.connect(self._status)

    def _submit(self, operation: DeviceOperation) -> None:
        device = DeviceId(self.device.currentText())
        arguments = None
        if operation is DeviceOperation.PUMP_FLOW_SET:
            device = DeviceId.PUMP
            arguments = PumpSetFlowArgs(self.value.value())
        elif operation is DeviceOperation.VALVE_POSITION_SET:
            device = DeviceId.VALVE
            arguments = ValveSetPositionArgs(1)
        elif operation is DeviceOperation.TEC_SETPOINTS_APPLY:
            device = DeviceId.TEC
            arguments = TecApplySetpointsArgs(self.value.value())
        elif operation in (
            DeviceOperation.Z_STAGE_CLOSED_LOOP_REQUIREMENT_READ,
            DeviceOperation.Z_STAGE_CLOSED_LOOP_ENABLE,
        ):
            device = DeviceId.Z_STAGE
        elif operation is DeviceOperation.Z_STAGE_POSITION_SET:
            device = DeviceId.Z_STAGE
            arguments = ZStageSetPositionArgs(self.value.value())
        command = (
            DeviceCommand(device, operation)
            if arguments is None
            else DeviceCommand(device, operation, arguments)
        )
        self.controller.submit(command)

    def confirm_real_connection(self, device: DeviceId) -> bool:
        answer = QMessageBox.question(
            self,
            "Connect real hardware",
            f"Connect to the real {device.value} device?",
        )
        return answer is QMessageBox.StandardButton.Yes

    def confirm_operation(self, request: ConfirmationRequest) -> bool:
        answer = QMessageBox.question(self, "Confirm hardware operation", request.prompt)
        return answer is QMessageBox.StandardButton.Yes

    def _event(self, event: CommandEvent) -> None:
        device = event.device.value if event.device else ""
        self.log.append(
            f"[{event.request_id}] {event.source} {event.state} "
            f"{device} {event.operation.value} {event.message}"
        )

    def _status(self, statuses) -> None:
        self.statusBar().showMessage(
            " | ".join(
                f"{device.value}: {status.connection.value}"
                for device, status in statuses.items()
            )
        )

    def closeEvent(self, event) -> None:
        self.controller.shutdown()
        event.accept()


def configure_palette(application):
    return None
