"""Input and progress view for application-owned workflows."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QLabel, QPushButton,
    QVBoxLayout, QWidget,
)

from ..application.commands import (
    FlushArgs, WaitArgs, WorkflowCommand, WorkflowOperation, WorkflowProgress,
)
from ..domain.models import PumpReadback


class WorkflowPanel(QWidget):
    command_requested = Signal(str, object)
    abort_requested = Signal()
    notice = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._pending: dict[str, str] = {}
        self._experiment_locked = False
        layout = QVBoxLayout(self)

        flush = QGroupBox("Flush")
        form = QFormLayout(flush)
        self.unit = QComboBox()
        self.unit.addItem("Select connected pump unit", None)
        self.volume = self._number(0.1, 0, 1000, 6)
        self.flow = self._number(100, 0, 1_000_000, 3)
        self.wait_after = self._number(0, 0, 100, 3)
        form.addRow("Pump unit", self.unit)
        form.addRow("Flush volume (mL)", self.volume)
        form.addRow("Flow (µL/min)", self.flow)
        form.addRow("Wait after flush (s)", self.wait_after)
        self.flush_button = QPushButton("Start flush")
        self.flush_button.clicked.connect(self._request_flush)
        form.addRow(self.flush_button)
        layout.addWidget(flush)

        wait = QGroupBox("Wait in command queue")
        wait_form = QFormLayout(wait)
        self.wait_seconds = self._number(1, 0, 86_400, 3)
        self.wait_button = QPushButton("Queue wait")
        self.wait_button.clicked.connect(self._request_wait)
        wait_form.addRow("Seconds", self.wait_seconds)
        wait_form.addRow(self.wait_button)
        layout.addWidget(wait)

        self.abort_button = QPushButton("Abort active workflow")
        self.abort_button.clicked.connect(self.abort_requested.emit)
        layout.addWidget(self.abort_button)
        self.progress_label = QLabel("No workflow running")
        self.progress_label.setWordWrap(True)
        layout.addWidget(self.progress_label)
        self.feedback_label = QLabel("")
        self.feedback_label.setWordWrap(True)
        layout.addWidget(self.feedback_label)
        layout.addStretch(1)

    @staticmethod
    def _number(value: float, minimum: float, maximum: float, decimals: int) -> QDoubleSpinBox:
        widget = QDoubleSpinBox()
        widget.setDecimals(decimals)
        widget.setRange(minimum, maximum)
        widget.setValue(value)
        return widget

    def update_pumps(self, readback: object) -> None:
        selected = self.unit.currentData()
        units = readback.units if isinstance(readback, PumpReadback) else ()
        wanted = tuple(
            (unit.unit_index, unit.syringe_name or "configured syringe")
            for unit in units
        )
        existing = tuple(
            (self.unit.itemData(index), self.unit.itemText(index))
            for index in range(1, self.unit.count())
        )
        labels = tuple((index, f"Pump {index + 1} · {name}") for index, name in wanted)
        if existing == labels:
            return
        self.unit.clear()
        self.unit.addItem("Select connected pump unit", None)
        for index, label in labels:
            self.unit.addItem(label, index)
        if selected is not None:
            index = self.unit.findData(selected)
            if index >= 0:
                self.unit.setCurrentIndex(index)

    def _request_flush(self) -> None:
        try:
            index = self.unit.currentData()
            if index is None:
                raise ValueError("Select a connected pump unit before flushing")
            command = WorkflowCommand(
                WorkflowOperation.FLUSH,
                FlushArgs(index, self.volume.value(), self.flow.value(), self.wait_after.value()),
            )
        except (TypeError, ValueError) as exc:
            self.show_notice(str(exc))
            return
        self.command_requested.emit("flush", command)

    def _request_wait(self) -> None:
        try:
            command = WorkflowCommand(WorkflowOperation.WAIT, WaitArgs(self.wait_seconds.value()))
        except (TypeError, ValueError) as exc:
            self.show_notice(str(exc))
            return
        self.command_requested.emit("wait", command)

    def mark_pending(self, action: str, request_id: str) -> None:
        self._pending[action] = request_id
        (self.flush_button if action == "flush" else self.wait_button).setEnabled(False)

    def clear_pending(self, request_id: str) -> None:
        for action, pending in tuple(self._pending.items()):
            if pending == request_id:
                del self._pending[action]
                (self.flush_button if action == "flush" else self.wait_button).setEnabled(
                    not self._experiment_locked)

    def set_experiment_locked(self, locked: bool) -> None:
        self._experiment_locked = locked
        self.flush_button.setEnabled(not locked and "flush" not in self._pending)
        self.wait_button.setEnabled(not locked and "wait" not in self._pending)
        self.abort_button.setEnabled(not locked)

    def show_notice(self, message: str) -> None:
        self.set_feedback(message, success=False)
        self.notice.emit(f"workflow: {message}")

    def set_feedback(self, message: str, *, success: bool) -> None:
        self.feedback_label.setStyleSheet(
            f"color: {'#2e7d32' if success else '#a65a00'}; font-weight: 600;"
        )
        self.feedback_label.setText(message)
        self.progress_label.setText(message)

    def handle_progress(self, value: object) -> None:
        if isinstance(value, WorkflowProgress):
            self.progress_label.setText(value.detail or value.state)
