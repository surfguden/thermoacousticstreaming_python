"""Results workspace: find a finished run's output and look at its saved frames.

It hosts the existing read-only saved-frames viewer (same display and measurement controls as the
live image viewer, frames read from disk on demand) inside the window instead of a separate one.
Two different folders are kept apart: the one **being viewed** (what the viewer loaded successfully,
however it was opened) and the **latest output of this session** (a shortcut from the run monitor).
Nothing here touches a device or the running batch.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QCheckBox, QGridLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from .saved_frames_window import SavedFramesWindow


class ResultsPanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        grid = QGridLayout()
        self.viewing_label = QLabel()
        self.viewing_label.setWordWrap(True)
        self.viewing_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.open_viewed_button = QPushButton("Open viewed folder in file manager")
        self.open_viewed_button.clicked.connect(lambda: self._open_in_file_manager(self.viewer.loaded_folder()))
        self.latest_label = QLabel()
        self.latest_label.setWordWrap(True)
        self.latest_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.open_latest_button = QPushButton("Show latest output in viewer")
        self.open_latest_button.clicked.connect(lambda: self.open_folder(self._latest))
        grid.addWidget(self.viewing_label, 0, 0)
        grid.addWidget(self.open_viewed_button, 0, 1)
        grid.addWidget(self.latest_label, 1, 0)
        self.measure_toggle = QCheckBox("Display and measurement")
        self.measure_toggle.setToolTip("Display range, histogram, analysis ROI and intensity profile (display only)")
        grid.addWidget(self.open_latest_button, 1, 1)
        grid.addWidget(self.measure_toggle, 2, 0, alignment=Qt.AlignmentFlag.AlignLeft)
        grid.setColumnStretch(0, 1)
        layout.addLayout(grid)
        self._latest = ""
        self.viewer = SavedFramesWindow()
        self.viewer.setWindowFlags(Qt.WindowType.Widget)  # shown inside this page, not as a window
        # In a scroll area so the viewer's own minimum size never sets the window's minimum size.
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.Shape.NoFrame)
        area.setWidget(self.viewer)
        layout.addWidget(area, 1)
        self.viewer.set_measurement_visible(False)  # same default as the docked viewer: the image first
        self.measure_toggle.toggled.connect(self.viewer.set_measurement_visible)
        self.viewer.show()
        self.viewer.source_changed.connect(self._viewer_changed)
        self.set_latest("")
        self._viewer_changed()

    def ensure_visible(self) -> None:
        """The embedded viewer is part of this page; make sure it is shown whenever the page is."""
        if not self.viewer.isVisibleTo(self):
            self.viewer.show()

    def set_latest(self, folder: str) -> None:
        """Remember the newest output folder of this session (from the run monitor); only a shortcut."""
        self._latest = folder or ""
        has = bool(self._latest) and Path(self._latest).is_dir()
        self.latest_label.setText(f"Latest output of this session: {self._latest}" if has
                                  else "Latest output of this session: nothing has run yet")
        self.open_latest_button.setEnabled(has)

    def open_folder(self, folder: str) -> None:
        self.ensure_visible()
        if folder and Path(folder).is_dir():
            self.viewer.open_or_report(folder)
        else:
            self.viewer.choose_folder(self._latest)

    def _viewer_changed(self) -> None:
        loaded = self.viewer.loaded_folder()
        if loaded is None:
            self.viewing_label.setText("Viewing: nothing loaded. Use Open series or experiment folder below.")
        else:
            self.viewing_label.setText(f"Viewing: {loaded} · experiment {self.viewer.loaded_experiment_id()}")
        self.open_viewed_button.setEnabled(loaded is not None)

    @staticmethod
    def _open_in_file_manager(folder: str | None) -> None:
        if folder and Path(folder).is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
