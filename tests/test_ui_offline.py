from __future__ import annotations

import os
import importlib.util
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PYSIDE_AVAILABLE = importlib.util.find_spec("PySide6") is not None

if PYSIDE_AVAILABLE:
    from PySide6.QtWidgets import QApplication

    from thermo_acoustic.infrastructure import build_simulated_application
    from thermo_acoustic.ui.main_window import MainWindow


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 UI extra is not installed")
class OfflineUiTests(unittest.TestCase):
    def test_window_can_render_without_connecting_devices(self) -> None:
        qt_app = QApplication.instance() or QApplication([])
        lab = build_simulated_application()
        window = MainWindow(lab)

        self.assertEqual(window.mode.text(), "SIMULATION")
        self.assertTrue(
            all(
                state.connection.value == "disconnected"
                for state in lab.snapshot().devices.values()
            )
        )

        window.close()
        qt_app.processEvents()
