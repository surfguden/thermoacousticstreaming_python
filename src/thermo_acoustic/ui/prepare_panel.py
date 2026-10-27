"""Prepare devices: choose the devices this session needs and connect them in one action.

Display and input collection only. "Connect selected devices" builds each device's own CONNECT
command from that device page's inputs and hands the set to the application-level
DeviceConnector. Nothing here connects at start-up, and a selected device is neither connected
nor "ready for the experiment" until its own state says so.

The everyday controls below the connection table are not copies: each device panel builds them
(`DevicePanel.daily_container()`), and this page only takes them over with `release_daily()`, so
a control has one owner, one set of values and one enable/lock rule. To change what a daily
control does or shows, edit that device panel in `device_panels.py` (PumpPanel._build_tiles,
CameraPanel snapshot/ROI groups, ZStagePanel, TecPanel); to change where it appears, edit the
sections built in `PreparePanel.__init__`.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from ..application.device_connect import ConnectOutcome, DeviceConnector
from ..domain.models import ConnectionState, DeviceId, DeviceStatus, OperatingMode, PumpReadback
from .status_dashboard import camera_summary, z_stage_summary
from .widgets import CollapsibleSection

DEVICE_NAMES = {DeviceId.AD2: "AD2", DeviceId.PUMP: "Pump", DeviceId.VALVE: "Valve",
                DeviceId.CAMERA: "Camera", DeviceId.TEC: "TEC", DeviceId.Z_STAGE: "Z-stage"}
_STATE_STYLE = {ConnectionState.CONNECTED: "color:#2e7d32", ConnectionState.ERROR: "color:#b71c1c;font-weight:700",
                ConnectionState.DISCONNECTED: "color:#616161"}
_RESULT_TEXT = {"waiting": "waiting", "connecting": "connecting…", "connected": "connected",
                "already_connected": "skipped, already connected", "already_connecting": "skipped, already connecting",
                "failed": "failed", "not_started": "not started", "cancelled": "cancelled"}
_RESULT_STYLE = {"connected": "color:#2e7d32", "failed": "color:#b71c1c;font-weight:600",
                 "not_started": "color:#a65a00", "cancelled": "color:#a65a00"}


class PreparePanel(QWidget):
    def __init__(self, controller, panels: dict, connector: DeviceConnector,
                 open_device_page: Callable[[DeviceId], None],
                 open_configure: Callable[[], None] = lambda: None, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.panels = panels
        self.connector = connector
        self._open_device_page = open_device_page
        self._start_error = ""
        root = QVBoxLayout(self)
        mode = "REAL hardware" if controller.mode is OperatingMode.REAL else "Simulation"
        self.mode_label = QLabel(f"Mode: {mode}. Nothing connects until you press Connect selected devices "
                                 "or a device page's own Connect.")
        self.mode_label.setWordWrap(True)
        root.addWidget(self.mode_label)

        self.connect_section = CollapsibleSection("Connect devices")
        group = QGroupBox("Devices for this session")
        grid = QGridLayout(group)
        for column, title in enumerate(("Use", "Device", "State", "Connect uses", "Last connect result", "")):
            heading = QLabel(title)
            heading.setStyleSheet("font-weight: 600")
            grid.addWidget(heading, 0, column)
        self.checkboxes: dict[DeviceId, QCheckBox] = {}
        self.state_labels: dict[DeviceId, QLabel] = {}
        self.input_labels: dict[DeviceId, QLabel] = {}
        self.result_labels: dict[DeviceId, QLabel] = {}
        self.page_buttons: dict[DeviceId, QPushButton] = {}
        for row, device in enumerate(DeviceId, start=1):
            box = QCheckBox()
            box.setToolTip("Choosing a device only includes it in Connect selected devices")
            box.toggled.connect(self._selection_changed)
            state = QLabel()
            inputs = QLabel()
            inputs.setWordWrap(True)
            result = QLabel("—")
            result.setWordWrap(True)
            page = QPushButton("Open page")
            page.setToolTip("Go to this device's own page to change its inputs, retry or disconnect")
            page.clicked.connect(lambda _checked=False, d=device: self._open_device_page(d))
            for column, widget in enumerate((box, QLabel(DEVICE_NAMES[device]), state, inputs, result, page)):
                grid.addWidget(widget, row, column)
            self.checkboxes[device], self.state_labels[device] = box, state
            self.input_labels[device], self.result_labels[device], self.page_buttons[device] = inputs, result, page
        grid.setColumnStretch(3, 1)
        grid.setColumnStretch(4, 1)
        connect_body = QWidget()
        connect_layout = QVBoxLayout(connect_body)
        connect_layout.setContentsMargins(0, 0, 0, 0)
        connect_layout.addWidget(group)
        self.connect_button = QPushButton("Connect selected devices")
        self.connect_button.clicked.connect(self._connect_selected)
        self.hint_label = QLabel()
        self.hint_label.setWordWrap(True)
        connect_layout.addWidget(self.connect_button, 0, Qt.AlignmentFlag.AlignLeft)
        connect_layout.addWidget(self.hint_label)
        self.connect_section.set_content(connect_body)
        self.connect_section.set_expanded(True)
        root.addWidget(self.connect_section)

        # Everyday controls, taken over from the device panels (one owner each; see module docstring).
        # Folding a section only hides it: nothing is sent and nothing is disabled.
        self.pump_section = self._section(
            root, "Pump and flow path", [panels[DeviceId.PUMP].release_daily("Everyday pump controls")])
        imaging = QWidget()
        imaging_layout = QHBoxLayout(imaging)
        imaging_layout.setContentsMargins(0, 0, 0, 0)
        imaging_layout.addWidget(panels[DeviceId.CAMERA].release_daily("Everyday camera controls"), 3,
                                 Qt.AlignmentFlag.AlignTop)
        imaging_layout.addWidget(panels[DeviceId.Z_STAGE].release_daily("Everyday focus controls"), 2,
                                 Qt.AlignmentFlag.AlignTop)
        self.imaging_section = self._section(root, "Imaging and focus", [imaging])
        self.temperature_section = self._section(
            root, "Fixed temperature", [panels[DeviceId.TEC].release_daily("Everyday temperature controls")])

        next_row = QHBoxLayout()
        self.configure_button = QPushButton("Go to Configure")
        self.configure_button.setToolTip("Opens the experiment form. Nothing on this page changes the "
                                         "experiment parameters; Import there copies the camera's ROI and exposure.")
        self.configure_button.clicked.connect(lambda: open_configure())
        next_row.addWidget(self.configure_button)
        next_row.addWidget(QLabel("Preparing devices does not fill in or overwrite experiment parameters, and no "
                                  "order or complete preparation is required."), 1)
        root.addLayout(next_row)
        root.addStretch(1)

        connector.changed.connect(self._outcomes_changed)
        controller.status_changed.connect(self._refresh)
        controller.panic_changed.connect(self._refresh)
        controller.experiments.changed.connect(self._refresh)
        self._refresh()

    @staticmethod
    def _section(root: QVBoxLayout, title: str, widgets: list) -> CollapsibleSection:
        section = CollapsibleSection(title)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(12, 0, 0, 0)
        for widget in widgets:
            layout.addWidget(widget)
        section.set_content(body)
        root.addWidget(section)
        return section

    def _section_summaries(self, statuses: dict[DeviceId, DeviceStatus]) -> None:
        pump = statuses[DeviceId.PUMP]
        units = pump.readback.units if isinstance(pump.readback, PumpReadback) else ()
        if pump.connection is not ConnectionState.CONNECTED:
            self.pump_section.set_summary("pump not connected")
        else:
            self.pump_section.set_summary(" · ".join(
                f"Pump {unit.unit_index + 1}: "
                + ("unknown level" if unit.fill_level_ml is None else f"{unit.fill_level_ml:.3g} mL")
                + (", pumping" if unit.is_pumping else "") for unit in units) or "no pump units")
        camera, stage = statuses[DeviceId.CAMERA], statuses[DeviceId.Z_STAGE]
        self.imaging_section.set_summary(" | ".join((
            "camera: " + (camera_summary(camera.readback) if camera.connection is ConnectionState.CONNECTED
                          else "not connected"),
            "Z: " + (z_stage_summary(stage.readback) if stage.connection is ConnectionState.CONNECTED
                     and stage.readback is not None else "not connected"))))
        tec = statuses[DeviceId.TEC]
        channels = getattr(tec.readback, "channels", ()) if tec.connection is ConnectionState.CONNECTED else ()
        self.temperature_section.set_summary(
            "TEC not connected" if tec.connection is not ConnectionState.CONNECTED else " · ".join(
                f"ch{item.channel}: "
                + ("unknown" if item.current_temperature_c is None else f"{item.current_temperature_c:.2f} °C")
                for item in channels) or "TEC connected")

    def _selection_changed(self, *_args) -> None:
        self._start_error = ""
        self._refresh()

    def selected_devices(self) -> list[DeviceId]:
        return [device for device in DeviceId if self.checkboxes[device].isChecked()]

    def _connect_selected(self) -> None:
        selected = self.selected_devices()
        self._start_error = ""
        if not selected:
            self._start_error = "Select at least one device to connect."
            self._refresh()
            return
        requests = {}
        for device in selected:
            try:
                requests[device] = self.panels[device].build_connect_command()
            except (TypeError, ValueError) as exc:
                requests[device] = str(exc)  # reported on this device; the others still connect
        try:
            self.connector.connect(requests)
        except (RuntimeError, ValueError) as exc:
            self._start_error = f"Nothing was started: {exc}"
            self._refresh()

    def _outcomes_changed(self, outcomes: dict[DeviceId, ConnectOutcome]) -> None:
        for device, outcome in outcomes.items():
            text = _RESULT_TEXT[outcome.state]
            if outcome.detail and outcome.state not in {"connected", "connecting", "waiting"}:
                text += f": {outcome.detail}"
            self.result_labels[device].setText(text)
            self.result_labels[device].setStyleSheet(_RESULT_STYLE.get(outcome.state, ""))
        self._refresh()

    def _refresh(self, *_args) -> None:
        statuses: dict[DeviceId, DeviceStatus] = self.controller.statuses()
        for device in DeviceId:
            status = statuses[device]
            self.state_labels[device].setText(status.connection.value + (" (fault)" if status.fault else ""))
            self.state_labels[device].setToolTip(status.fault or "")
            self.state_labels[device].setStyleSheet(_STATE_STYLE[status.connection])
            self.input_labels[device].setText(self.panels[device].connect_inputs_text())
        self._section_summaries(statuses)
        blocked = self.connector.blocked_reason()
        self.connect_button.setEnabled(blocked is None and not self.connector.active)
        if self._start_error and not self.connector.active:
            self.hint_label.setText(self._start_error)
        elif self.connector.active:
            self.hint_label.setText("Connecting the selected devices one after another; a failure does not "
                                    "stop the others.")
        elif blocked:
            self.hint_label.setText(f"Connect selected devices is unavailable: {blocked}.")
        elif not self.selected_devices():
            self.hint_label.setText("Choose the devices this session needs, then Connect selected devices. "
                                    "A chosen device is not connected, or ready for the experiment, until "
                                    "its state says connected. Each device page keeps its own Connect, "
                                    "Disconnect and retry.")
        else:
            self.hint_label.setText("Already connected devices are skipped. Failed devices are not retried "
                                    "automatically; fix inputs on the device page and connect again.")
