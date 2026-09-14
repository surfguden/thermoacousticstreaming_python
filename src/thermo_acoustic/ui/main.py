from __future__ import annotations

import argparse
import sys

from PySide6.QtWidgets import QApplication

from ..infrastructure import build_simulated_application
from .main_window import MainWindow, configure_palette


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Thermo-acoustic control UI")
    parser.add_argument(
        "--mode",
        choices=("simulation",),
        default="simulation",
        help="Only offline simulation is available until real adapters are commissioned.",
    )
    parser.parse_args(argv)
    qt_app = QApplication(sys.argv[:1])
    configure_palette(qt_app)
    window = MainWindow(build_simulated_application())
    window.show()
    return qt_app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
