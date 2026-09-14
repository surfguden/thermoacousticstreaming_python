from __future__ import annotations

from functools import partial
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..application import LabApplication
from ..domain import (
    ConnectionState,
    DEVICE_LABELS,
    DeviceId,
    ExperimentPlan,
    ExperimentState,
    ExperimentStep,
    LabSnapshot,
)


NAV_ITEMS = (
    ("Overview", "System status and explicit device connections"),
    ("Waveform", "AD2 signal configuration and output"),
    ("Pump & valve", "Flow and fluid-path controls"),
    ("Camera", "Acquisition settings and snapshots"),
    ("Temperature & Z", "Thermal setpoint and focus position"),
    ("Experiment", "Review and run application-owned sequences"),
)


STYLE = """
QWidget { color: #e8edf3; font-family: Segoe UI; font-size: 10pt; }
QMainWindow, QWidget#root { background: #11161d; }
QFrame#sidebar { background: #171e27; border-right: 1px solid #293342; }
QFrame#card { background: #19212b; border: 1px solid #2b3746; border-radius: 8px; }
QLabel#title { font-size: 23pt; font-weight: 600; }
QLabel#subtitle, QLabel#muted { color: #93a2b5; }
QLabel#mode { color: #7ee2b8; background: #17382f; border-radius: 10px; padding: 5px 10px; }
QLabel#statusbar { background: #171e27; color: #b7c2cf; padding: 9px 14px; border-top: 1px solid #293342; }
QPushButton { background: #253142; border: 1px solid #35465c; border-radius: 5px; padding: 7px 12px; }
QPushButton:hover { background: #304058; }
QPushButton:checked, QPushButton#primary { background: #176b87; border-color: #2aa5c9; }
QPushButton#danger { background: #63323a; border-color: #914552; }
QDoubleSpinBox, QSpinBox, QComboBox { background: #111820; border: 1px solid #344255; border-radius: 4px; padding: 5px; }
QTableWidget { background: #151c25; alternate-background-color: #18212b; border: 1px solid #2b3746; gridline-color: #2b3746; }
QHeaderView::section { background: #202a37; color: #cbd4df; border: 0; padding: 7px; }
"""


class DeviceCard(QFrame):
    def __init__(self, device: DeviceId, app: LabApplication) -> None:
        super().__init__()
        self.device = device
        self.app = app
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        name = QLabel(DEVICE_LABELS[device])
        name.setStyleSheet("font-size: 12pt; font-weight: 600")
        self.badge = QLabel("Disconnected")
        top.addWidget(name)
        top.addStretch()
        top.addWidget(self.badge)
        layout.addLayout(top)
        self.detail = QLabel("Not connected")
        self.detail.setObjectName("muted")
        layout.addWidget(self.detail)
        buttons = QHBoxLayout()
        self.connect_button = QPushButton("Connect")
        self.disconnect_button = QPushButton("Disconnect")
        self.connect_button.clicked.connect(lambda: self._call(app.connect))
        self.disconnect_button.clicked.connect(lambda: self._call(app.disconnect))
        buttons.addWidget(self.connect_button)
        buttons.addWidget(self.disconnect_button)
        layout.addLayout(buttons)

    def _call(self, action: Any) -> None:
        try:
            action(self.device)
        except Exception as exc:
            QMessageBox.critical(self, "Device action failed", str(exc))

    def update_state(self, snapshot: LabSnapshot) -> None:
        state = snapshot.devices[self.device]
        connected = state.connection is ConnectionState.CONNECTED
        self.badge.setText(state.connection.value.title())
        self.badge.setStyleSheet(f"color: {'#7ee2b8' if connected else '#93a2b5'}")
        self.detail.setText(state.summary)
        self.connect_button.setEnabled(not connected)
        self.disconnect_button.setEnabled(connected)


class ActionPage(QWidget):
    def __init__(self, app: LabApplication, title: str, subtitle: str) -> None:
        super().__init__()
        self.app = app
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(30, 28, 30, 28)
        title_label = QLabel(title)
        title_label.setObjectName("title")
        self.layout.addWidget(title_label)
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("subtitle")
        self.layout.addWidget(subtitle_label)

    def action_button(
        self,
        text: str,
        device: DeviceId,
        command: str,
        parameters: Any = None,
        *,
        confirmation: str | None = None,
    ) -> QPushButton:
        button = QPushButton(text)

        def invoke() -> None:
            if confirmation and QMessageBox.question(self, "Confirm action", confirmation) != QMessageBox.Yes:
                return
            try:
                values = parameters() if callable(parameters) else (parameters or {})
                self.app.execute(device, command, values)
            except Exception as exc:
                QMessageBox.warning(self, "Action not completed", str(exc))

        button.clicked.connect(invoke)
        return button


class WaveformPage(ActionPage):
    def __init__(self, app: LabApplication) -> None:
        super().__init__(app, "Waveform", "Configure the requested signal before enabling output.")
        card = QFrame(objectName="card")
        form = QFormLayout(card)
        self.frequency = QDoubleSpinBox()
        self.frequency.setRange(0.001, 100_000_000)
        self.frequency.setDecimals(3)
        self.frequency.setValue(1_000_000)
        self.amplitude = QDoubleSpinBox()
        self.amplitude.setRange(0, 5)
        self.amplitude.setDecimals(3)
        self.amplitude.setValue(1)
        form.addRow("Frequency (Hz)", self.frequency)
        form.addRow("Amplitude (V)", self.amplitude)
        row = QHBoxLayout()
        row.addWidget(self.action_button("Apply configuration", DeviceId.AD2, "configure_waveform", self.values))
        start = self.action_button(
            "Start output",
            DeviceId.AD2,
            "start",
            confirmation="Enable waveform output with the current applied configuration?",
        )
        start.setObjectName("primary")
        row.addWidget(start)
        stop = self.action_button("Stop output", DeviceId.AD2, "stop")
        stop.setObjectName("danger")
        row.addWidget(stop)
        form.addRow(row)
        self.layout.addWidget(card)
        self.layout.addStretch()

    def values(self) -> dict[str, float]:
        return {"frequency_hz": self.frequency.value(), "amplitude_v": self.amplitude.value()}


class PumpValvePage(ActionPage):
    def __init__(self, app: LabApplication) -> None:
        super().__init__(app, "Pump & valve", "Fluid movement requires an explicit connected device and confirmation.")
        pump = QFrame(objectName="card")
        pump_form = QFormLayout(pump)
        self.flow = QDoubleSpinBox()
        self.flow.setRange(-10_000, 10_000)
        self.flow.setValue(100)
        pump_form.addRow("Flow (µL/min)", self.flow)
        row = QHBoxLayout()
        row.addWidget(self.action_button("Set flow", DeviceId.PUMP, "set_flow", lambda: {"flow_ul_min": self.flow.value()}, confirmation="Start pump flow at the entered rate?"))
        stop = self.action_button("Stop pump", DeviceId.PUMP, "stop")
        stop.setObjectName("danger")
        row.addWidget(stop)
        pump_form.addRow(row)
        self.layout.addWidget(pump)
        valve = QFrame(objectName="card")
        valve_layout = QHBoxLayout(valve)
        valve_layout.addWidget(QLabel("Valve position"))
        for position in (1, 2):
            valve_layout.addWidget(self.action_button(f"Move to {position}", DeviceId.VALVE, "set_position", {"position": position}, confirmation=f"Move the valve to numeric position {position}? Fluid routing must be verified at the bench."))
        self.layout.addWidget(valve)
        self.layout.addStretch()


class CameraPage(ActionPage):
    def __init__(self, app: LabApplication) -> None:
        super().__init__(app, "Camera", "Configure acquisition without coupling capture to the view.")
        card = QFrame(objectName="card")
        form = QFormLayout(card)
        self.exposure = QDoubleSpinBox()
        self.exposure.setRange(0.001, 60_000)
        self.exposure.setValue(1)
        self.frames = QSpinBox()
        self.frames.setRange(1, 100_000)
        self.frames.setValue(1)
        form.addRow("Exposure (ms)", self.exposure)
        form.addRow("Frame count", self.frames)
        row = QHBoxLayout()
        row.addWidget(self.action_button("Apply settings", DeviceId.CAMERA, "configure", lambda: {"exposure_ms": self.exposure.value(), "frame_count": self.frames.value()}))
        row.addWidget(self.action_button("Take snapshot", DeviceId.CAMERA, "snapshot"))
        form.addRow(row)
        self.layout.addWidget(card)
        preview = QLabel("Image preview will appear here after a capture adapter is commissioned.")
        preview.setAlignment(Qt.AlignCenter)
        preview.setMinimumHeight(260)
        preview.setStyleSheet("background: #0b1016; border: 1px dashed #344255; color: #637389")
        self.layout.addWidget(preview)


class TemperaturePage(ActionPage):
    def __init__(self, app: LabApplication) -> None:
        super().__init__(app, "Temperature & Z", "Independent controls; limits are enforced by application actions.")
        temp = QFrame(objectName="card")
        temp_form = QFormLayout(temp)
        self.temperature = QDoubleSpinBox()
        self.temperature.setRange(-20, 120)
        self.temperature.setValue(25)
        temp_form.addRow("Target (°C)", self.temperature)
        temp_form.addRow(self.action_button("Apply setpoint", DeviceId.TEC, "set_temperature", lambda: {"temperature_c": self.temperature.value()}, confirmation="Apply this temperature to the configured TEC channels?"), self.action_button("Outputs off", DeviceId.TEC, "outputs_off"))
        self.layout.addWidget(temp)
        stage = QFrame(objectName="card")
        stage_form = QFormLayout(stage)
        self.position = QDoubleSpinBox()
        self.position.setRange(0, 450)
        self.position.setDecimals(2)
        stage_form.addRow("Position (µm)", self.position)
        stage_form.addRow(self.action_button("Move Z-stage", DeviceId.Z_STAGE, "move_um", lambda: {"position_um": self.position.value()}, confirmation="Move the piezo Z-stage to this absolute position?"))
        self.layout.addWidget(stage)
        self.layout.addStretch()


class ExperimentPage(ActionPage):
    def __init__(self, app: LabApplication) -> None:
        super().__init__(app, "Experiment", "The sequence is validated and executed by the application layer.")
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(("Device", "Action", "Parameters", "Delay after"))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.layout.addWidget(self.table)
        buttons = QHBoxLayout()
        load = QPushButton("Load safe demo plan")
        load.clicked.connect(self.load_demo)
        buttons.addWidget(load)
        run = QPushButton("Run plan")
        run.setObjectName("primary")
        run.clicked.connect(self.run_plan)
        buttons.addWidget(run)
        cancel = QPushButton("Cancel")
        cancel.setObjectName("danger")
        cancel.clicked.connect(app.cancel_experiment)
        buttons.addWidget(cancel)
        self.layout.addLayout(buttons)
        self.plan: ExperimentPlan | None = None

    def load_demo(self) -> None:
        self.plan = ExperimentPlan(
            "Simulation demonstration",
            (
                ExperimentStep(DeviceId.AD2, "configure_waveform", {"frequency_hz": 1_000_000, "amplitude_v": 1.0}, 0.2, "Configure waveform"),
                ExperimentStep(DeviceId.CAMERA, "configure", {"exposure_ms": 1.0, "frame_count": 1}, 0.2, "Configure camera"),
                ExperimentStep(DeviceId.CAMERA, "snapshot", {}, 0, "Take snapshot"),
            ),
        )
        self.table.setRowCount(len(self.plan.steps))
        for row, step in enumerate(self.plan.steps):
            values = (DEVICE_LABELS[step.device], step.label or step.command, str(step.parameters), f"{step.delay_after_s:g} s")
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))

    def run_plan(self) -> None:
        if self.plan is None:
            QMessageBox.information(self, "No plan", "Load or create a plan before running it.")
            return
        try:
            self.app.start_experiment(self.plan)
        except Exception as exc:
            QMessageBox.warning(self, "Experiment not started", str(exc))


class MainWindow(QMainWindow):
    def __init__(self, app: LabApplication) -> None:
        super().__init__()
        self.app = app
        self.setWindowTitle("Thermo-acoustic control")
        self.resize(1180, 760)
        root = QWidget(objectName="root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        sidebar = QFrame(objectName="sidebar")
        sidebar.setFixedWidth(230)
        nav = QVBoxLayout(sidebar)
        brand = QLabel("THERMO\nACOUSTIC")
        brand.setStyleSheet("font-size: 15pt; font-weight: 700; color: #5fc6e8; padding: 16px 8px")
        nav.addWidget(brand)
        self.nav_buttons: list[QPushButton] = []
        for index, (name, _) in enumerate(NAV_ITEMS):
            button = QPushButton(name)
            button.setCheckable(True)
            button.clicked.connect(partial(self.show_page, index))
            nav.addWidget(button)
            self.nav_buttons.append(button)
        nav.addStretch()
        self.mode = QLabel("SIMULATION")
        self.mode.setObjectName("mode")
        self.mode.setAlignment(Qt.AlignCenter)
        nav.addWidget(self.mode)
        body.addWidget(sidebar)
        self.pages = QStackedWidget()
        body.addWidget(self.pages, 1)
        outer.addLayout(body, 1)
        self.status = QLabel("Ready")
        self.status.setObjectName("statusbar")
        outer.addWidget(self.status)
        self.cards: dict[DeviceId, DeviceCard] = {}
        self._build_pages()
        self.show_page(0)
        self.unsubscribe = app.subscribe(self.render)
        self.timer = QTimer(self)
        self.timer.timeout.connect(app.tick)
        self.timer.start(50)

    def _build_pages(self) -> None:
        overview = ActionPage(self.app, "Overview", "Device connections are explicit and independent.")
        grid = QVBoxLayout()
        for device in DeviceId:
            card = DeviceCard(device, self.app)
            self.cards[device] = card
            grid.addWidget(card)
        overview.layout.addLayout(grid)
        overview.layout.addStretch()
        self.pages.addWidget(overview)
        self.pages.addWidget(WaveformPage(self.app))
        self.pages.addWidget(PumpValvePage(self.app))
        self.pages.addWidget(CameraPage(self.app))
        self.pages.addWidget(TemperaturePage(self.app))
        self.pages.addWidget(ExperimentPage(self.app))

    def show_page(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        for button_index, button in enumerate(self.nav_buttons):
            button.setChecked(button_index == index)

    def render(self, snapshot: LabSnapshot) -> None:
        self.mode.setText(snapshot.mode.value.upper())
        experiment = snapshot.experiment_state
        suffix = ""
        if experiment is ExperimentState.RUNNING:
            suffix = f" · experiment step {snapshot.experiment_step + 1}/{snapshot.experiment_total}"
        self.status.setText(snapshot.message + suffix)
        for card in self.cards.values():
            card.update_state(snapshot)

    def closeEvent(self, event: Any) -> None:
        errors = self.app.shutdown()
        if errors:
            QMessageBox.warning(self, "Shutdown warning", "\n".join(errors))
        self.unsubscribe()
        event.accept()


def configure_palette(application: QApplication) -> None:
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor("#11161d"))
    palette.setColor(QPalette.WindowText, QColor("#e8edf3"))
    palette.setColor(QPalette.Base, QColor("#151c25"))
    palette.setColor(QPalette.Text, QColor("#e8edf3"))
    palette.setColor(QPalette.Button, QColor("#253142"))
    palette.setColor(QPalette.ButtonText, QColor("#e8edf3"))
    application.setPalette(palette)
    application.setStyleSheet(STYLE)
