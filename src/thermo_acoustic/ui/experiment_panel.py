"""Definition editor and queue controls; execution remains in application layer."""

from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..application.experiments import default_definition, load_definition, save_definition, validate_definition


class ExperimentPanel(QWidget):
    def __init__(self, manager, parent=None) -> None:
        super().__init__(parent)
        self.manager = manager
        root = QVBoxLayout(self)
        root.addWidget(QLabel("Experiment builder · versioned JSON · selected steps can be edited or reordered"))
        toolbar = QHBoxLayout()
        self.load_button = QPushButton("Load definition…")
        self.save_button = QPushButton("Save definition…")
        self.template_button = QPushButton("Default template")
        self.validate_button = QPushButton("Validate / preview")
        for button in (self.load_button, self.save_button, self.template_button, self.validate_button):
            toolbar.addWidget(button)
        root.addLayout(toolbar)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Ordered steps / sweep values / repeats"])
        self.step_json = QPlainTextEdit()
        self.step_json.setPlaceholderText("Selected step JSON; edit args, parameter lists or numeric ranges here")
        self.definition_json = QPlainTextEdit()
        self.definition_json.setPlaceholderText("Full portable definition JSON")
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.tree)
        editors = QWidget()
        editors_layout = QVBoxLayout(editors)
        editors_layout.addWidget(QLabel("Selected step"))
        editors_layout.addWidget(self.step_json)
        self.apply_button = QPushButton("Apply selected-step edit")
        editors_layout.addWidget(self.apply_button)
        editors_layout.addWidget(QLabel("Full definition (editable; apply by validating)"))
        editors_layout.addWidget(self.definition_json)
        splitter.addWidget(editors)
        root.addWidget(splitter, 2)
        order = QHBoxLayout()
        self.add_button = QPushButton("Add step after selected")
        self.remove_button = QPushButton("Remove selected")
        self.up_button = QPushButton("Move up")
        self.down_button = QPushButton("Move down")
        for button in (self.add_button, self.remove_button, self.up_button, self.down_button):
            order.addWidget(button)
        root.addLayout(order)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        root.addWidget(self.preview, 1)
        self.description = QLineEdit()
        self.description.setPlaceholderText("Required series descriptor")
        root.addWidget(QLabel("Series descriptor (required before queueing)"))
        root.addWidget(self.description)
        queue_row = QHBoxLayout()
        self.output_root = QLineEdit()
        self.output_root.setPlaceholderText("Choose output root before queueing")
        self.choose_output = QPushButton("Output root…")
        self.format = QComboBox()
        self.format.addItem("Individual TIFF", "frames")
        self.format.addItem("Stacked TIFF", "stacked")
        self.preflight = QCheckBox("Real-mode count preflight")
        queue_row.addWidget(self.output_root, 2)
        queue_row.addWidget(self.choose_output)
        queue_row.addWidget(self.format)
        queue_row.addWidget(self.preflight)
        root.addLayout(queue_row)
        controls = QHBoxLayout()
        self.queue_button = QPushButton("Queue series")
        self.start_button = QPushButton("Start queued batch")
        self.stop_button = QPushButton("Stop after current")
        self.abort_button = QPushButton("Abort batch")
        for button in (self.queue_button, self.start_button, self.stop_button, self.abort_button):
            controls.addWidget(button)
        root.addLayout(controls)
        self.batch_list = QTreeWidget()
        self.batch_list.setHeaderLabels(["Series descriptor", "State", "Experiments", "Preflight", "Output folder"])
        self.batch_list.setMinimumHeight(100)
        self._batch_snapshot = None
        root.addWidget(self.batch_list)
        self.state_label = QLabel("No experiment series queued")
        self.state_label.setWordWrap(True)
        root.addWidget(self.state_label)

        self.template_button.clicked.connect(self._template)
        self.definition_json.textChanged.connect(self._sync_description_from_json)
        self.load_button.clicked.connect(self._load)
        self.save_button.clicked.connect(self._save)
        self.validate_button.clicked.connect(self._validate)
        self.tree.currentItemChanged.connect(self._selected)
        self.apply_button.clicked.connect(self._apply_selected)
        self.add_button.clicked.connect(self._add)
        self.remove_button.clicked.connect(self._remove)
        self.up_button.clicked.connect(lambda: self._move(-1))
        self.down_button.clicked.connect(lambda: self._move(1))
        self.choose_output.clicked.connect(self._choose_output)
        self.queue_button.clicked.connect(self._queue)
        self.start_button.clicked.connect(self._start)
        self.stop_button.clicked.connect(manager.stop_after_current)
        self.abort_button.clicked.connect(manager.abort)
        manager.changed.connect(self._status)
        manager.notice.connect(self._notice)
        manager.controller.status_changed.connect(lambda _statuses: self._render_batch_list(manager.status()))
        self._template()
        self._status(manager.status())

    def _definition(self) -> dict:
        value = json.loads(self.definition_json.toPlainText())
        if not isinstance(value, dict):
            raise ValueError("Definition must be a JSON object")
        value["description"] = self.description.text().strip()
        return value

    def _sync_description_from_json(self) -> None:
        try:
            value = json.loads(self.definition_json.toPlainText())
        except (TypeError, ValueError):
            return
        if isinstance(value, dict) and isinstance(value.get("description"), str):
            self.description.setText(value["description"])

    def _replace(self, value: dict) -> None:
        self.definition_json.setPlainText(json.dumps(value, indent=2, ensure_ascii=False))
        self.description.setText(str(value.get("description", "")))
        self.preflight.setChecked(bool(value.get("preflight", False)))
        format_index = self.format.findData(value.get("tiff_format", "frames"))
        if format_index >= 0:
            self.format.setCurrentIndex(format_index)
        self._tree(value)

    def _tree(self, definition: dict) -> None:
        self.tree.clear()
        def children(steps: list, parent, prefix: tuple):
            for index, node in enumerate(steps):
                path = prefix + (index,)
                text = node.get("type", "invalid")
                if text == "sweep":
                    text += " · " + ", ".join(node.get("parameters", {}))
                elif text == "repeat":
                    text += f" × {node.get('count', '?')}"
                item = QTreeWidgetItem([text])
                item.setData(0, Qt.ItemDataRole.UserRole, path)
                (parent.addChild(item) if parent else self.tree.addTopLevelItem(item))
                if isinstance(node.get("steps"), list):
                    children(node["steps"], item, path + ("steps",))
                if isinstance(node.get("branches"), list):
                    for branch_index, branch in enumerate(node["branches"]):
                        branch_item = QTreeWidgetItem([f"branch {branch_index + 1}"])
                        branch_item.setData(0, Qt.ItemDataRole.UserRole, path + ("branches", branch_index))
                        item.addChild(branch_item)
                        children(branch, branch_item, path + ("branches", branch_index))
        children(definition.get("steps", []), None, ("steps",))
        self.tree.expandAll()

    def _selected(self, current, _previous) -> None:
        if current is None:
            self.step_json.clear()
            return
        path = current.data(0, Qt.ItemDataRole.UserRole)
        try:
            node = self._at(self._definition(), path)
            self.step_json.setPlainText(json.dumps(node, indent=2, ensure_ascii=False))
        except (KeyError, IndexError, TypeError, ValueError):
            self.step_json.clear()

    @staticmethod
    def _at(value, path: tuple):
        for part in path:
            value = value[part]
        return value

    def _mutate_selected(self, change) -> None:
        item = self.tree.currentItem()
        if item is None:
            raise ValueError("Select a step first")
        path = item.data(0, Qt.ItemDataRole.UserRole)
        definition = self._definition()
        parent = self._at(definition, path[:-1])
        if not isinstance(parent, list):
            raise ValueError("Select an action or block, not a branch heading")
        change(parent, path[-1])
        self._replace(definition)

    def _apply_selected(self) -> None:
        try:
            node = json.loads(self.step_json.toPlainText())
            if not isinstance(node, dict) or "type" not in node:
                raise ValueError("Selected step must be a JSON object with type")
            self._mutate_selected(lambda parent, index: parent.__setitem__(index, node))
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            self._notice(str(exc))

    def _add(self) -> None:
        try:
            self._mutate_selected(lambda parent, index: parent.insert(index + 1,
                                                        {"type": "wait", "args": {"seconds": 1}}))
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            self._notice(str(exc))

    def _remove(self) -> None:
        try:
            self._mutate_selected(lambda parent, index: parent.pop(index))
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            self._notice(str(exc))

    def _move(self, offset: int) -> None:
        def change(parent, index):
            destination = index + offset
            if not 0 <= destination < len(parent):
                raise ValueError("Step is already at the edge of its block")
            parent[index], parent[destination] = parent[destination], parent[index]
        try:
            self._mutate_selected(change)
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            self._notice(str(exc))

    def _template(self) -> None:
        self._replace(default_definition())
        self._validate()

    def _load(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load experiment definition", "", "JSON (*.json)")
        if path:
            try:
                self._replace(load_definition(path))
                self._validate()
            except Exception as exc:
                self._notice(str(exc))

    def _save(self) -> None:
        try:
            definition = self._definition()
            definition["preflight"] = self.preflight.isChecked()
            definition["tiff_format"] = self.format.currentData()
            validate_definition(definition)
            path, _ = QFileDialog.getSaveFileName(self, "Save experiment definition", "", "JSON (*.json)")
            if path:
                save_definition(path, definition)
                self._notice(f"Saved {path}")
        except Exception as exc:
            self._notice(str(exc))

    def _validate(self) -> None:
        try:
            expansion = validate_definition(self._definition())
            self._tree(expansion.definition)
            self.preview.setPlainText("\n".join(
                f"{i + 1:04d}  {item.experiment_id}  {item.relative_path}  {item.parameters}"
                for i, item in enumerate(expansion.experiments)
            ))
            self._notice(f"Valid: {len(expansion.experiments)} ordered experiments")
        except Exception as exc:
            self._notice(f"Validation failed: {exc}")

    def _choose_output(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose experiment output root")
        if path:
            self.output_root.setText(path)

    def _queue(self) -> None:
        try:
            if not self.output_root.text().strip():
                raise ValueError("Choose an output root before queueing")
            definition = self._definition()
            definition["preflight"] = self.preflight.isChecked()
            definition["tiff_format"] = self.format.currentData()
            folder = self.manager.queue(definition, self.output_root.text(), self.format.currentData())
            self._notice(f"Queued {folder}")
        except Exception as exc:
            self._notice(str(exc))

    def _start(self) -> None:
        try:
            self.manager.start()
        except Exception as exc:
            self._notice(str(exc))

    def _status(self, status: dict) -> None:
        locked = status["state"] in {"running", "stopping", "aborting"}
        self.queue_button.setEnabled(not locked)
        self.start_button.setEnabled(not locked)
        self.stop_button.setEnabled(status["state"] == "running")
        self.abort_button.setEnabled(status["state"] == "running")
        self._render_batch_list(status)
        self.state_label.setText(f"State: {status['state']} · queued series: {status['queued_series']} "
                                 f"· completed experiments: {status['completed_experiments']} "
                                 f"· current: {status['current_experiment'] or 'none'} "
                                 f"· folder: {status['current_series'] or 'none'}")

    def _render_batch_list(self, status: dict) -> None:
        snapshot = tuple((item["description"], item["state"], item["experiment_count"],
                          item["preflight_passed"], item["folder"])
                         for item in status.get("series", []))
        if snapshot == self._batch_snapshot:
            return
        self._batch_snapshot = snapshot
        self.batch_list.clear()
        for series in status.get("series", []):
            item = QTreeWidgetItem([series["description"], series["state"],
                                    str(series["experiment_count"]),
                                    "● Passed" if series["preflight_passed"] else "● Not tested",
                                    series["folder"]])
            item.setForeground(3, QColor("#2e7d32" if series["preflight_passed"] else "#b71c1c"))
            self.batch_list.addTopLevelItem(item)

    def _notice(self, message: str) -> None:
        self.state_label.setText(message)
