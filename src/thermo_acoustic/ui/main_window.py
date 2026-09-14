from __future__ import annotations
from PySide6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QLabel, QPushButton, QComboBox, QDoubleSpinBox, QTextEdit
from ..application.commands import CommandEvent, DeviceCommand
from ..domain.models import DeviceId

class MainWindow(QMainWindow):
    def __init__(self, controller, parent=None):
        super().__init__(parent); self.controller = controller; self.setWindowTitle("Thermo-acoustic control"); self.resize(760, 520)
        root = QWidget(); layout = QVBoxLayout(root); self.setCentralWidget(root); layout.addWidget(QLabel(f"Mode: {controller.mode.value} (simulation is safe default)"))
        self.device = QComboBox(); self.device.addItems([d.value for d in DeviceId]); layout.addWidget(self.device); self.value = QDoubleSpinBox(); self.value.setRange(-10000, 10000); self.value.setValue(100); layout.addWidget(self.value)
        for label, operation in (("Connect", "connect"), ("Disconnect", "disconnect"), ("Pump set flow", "set-flow"), ("Valve position 1", "set-position"), ("Camera snapshot", "snapshot"), ("TEC set temperature", "set-temperature"), ("Z-stage enable closed loop", "enable-closed-loop"), ("Z-stage move", "move")):
            button = QPushButton(label); button.clicked.connect(lambda checked=False, op=operation: self._submit(op)); layout.addWidget(button)
        self.log = QTextEdit(); self.log.setReadOnly(True); layout.addWidget(self.log); controller.command_event.connect(self._event); controller.status_changed.connect(self._status)
    def _submit(self, operation):
        device = DeviceId(self.device.currentText()); args = ()
        if operation == "set-flow": device, args = DeviceId.PUMP, (self.value.value(),)
        elif operation == "set-position": device, args = DeviceId.VALVE, (1,)
        elif operation == "set-temperature": device, args = DeviceId.TEC, (self.value.value(),)
        elif operation == "move": device, args = DeviceId.Z_STAGE, (self.value.value(),)
        self.controller.submit(DeviceCommand(device, operation, args))
    def _event(self, event: CommandEvent): self.log.append(f"[{event.request_id}] {event.source} {event.state} {event.device.value if event.device else ''} {event.operation} {event.message}")
    def _status(self, statuses): self.statusBar().showMessage(" | ".join(f"{d.value}: {s.connection.value}" for d, s in statuses.items()))
    def closeEvent(self, event): self.controller.shutdown(); event.accept()

def configure_palette(application): return None
