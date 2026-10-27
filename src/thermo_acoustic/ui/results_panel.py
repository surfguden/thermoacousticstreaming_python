"""Results workspace: find a finished run's output and look at its saved frames.

It hosts the existing read-only saved-frames viewer (same display and measurement controls as the
live image viewer, frames read from disk on demand) inside the window instead of a separate one.
Nothing here touches a device or the running batch.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from .saved_frames_window import SavedFramesWindow


class ResultsPanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.latest_label = QLabel("Latest output: nothing has run in this session. Open any series or "
                                   "experiment folder below.")
        self.latest_label.setWordWrap(True)
        self.open_latest_button = QPushButton("Show latest in viewer")
        self.open_latest_button.clicked.connect(lambda: self.open_folder(self._latest))
        self.open_in_os_button = QPushButton("Open folder in file manager")
        self.open_in_os_button.clicked.connect(self._open_in_file_manager)
        row.addWidget(self.latest_label, 1)
        row.addWidget(self.open_latest_button)
        row.addWidget(self.open_in_os_button)
        layout.addLayout(row)
        self._latest = ""
        self.viewer = SavedFramesWindow()
        self.viewer.setWindowFlags(Qt.WindowType.Widget)  # shown inside this page, not as a window
        # In a scroll area so the viewer's own minimum size never sets the window's minimum size.
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.Shape.NoFrame)
        area.setWidget(self.viewer)
        layout.addWidget(area, 1)
        self.viewer.show()
        self.set_latest("")

    def set_latest(self, folder: str) -> None:
        """Remember the newest output folder (from the run monitor); it is only a shortcut."""
        self._latest = folder or ""
        has = bool(self._latest) and Path(self._latest).is_dir()
        if has:
            self.latest_label.setText(f"Latest output: {self._latest}")
        self.open_latest_button.setEnabled(has)
        self.open_in_os_button.setEnabled(has)

    def open_folder(self, folder: str) -> None:
        if folder and Path(folder).is_dir():
            self.viewer.open_or_report(folder)
        else:
            self.viewer.choose_folder(self._latest)

    def _open_in_file_manager(self) -> None:
        if self._latest and Path(self._latest).is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._latest))
