from __future__ import annotations
import argparse, sys
from PySide6.QtWidgets import QApplication
from .application import ApplicationController, AuditLogger
from .console.reader import ConsoleCommandReader
from .hal.registry import DeviceRegistry
from .domain.models import OperatingMode
from .ui.main_window import MainWindow, configure_palette

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--mode", choices=["simulation", "real"], default="simulation"); parser.add_argument("--audit-log", default=None); args = parser.parse_args(argv)
    qt_app = QApplication(sys.argv[:1]); configure_palette(qt_app); mode = OperatingMode(args.mode); controller = ApplicationController(DeviceRegistry(mode), mode=mode, audit=AuditLogger(args.audit_log), confirm_real_connection=lambda d: False); window = MainWindow(controller); reader = ConsoleCommandReader()
    def handle(item):
        if item == "help": print("status | devices | connect DEVICE | disconnect DEVICE | pump set-flow UL_MIN | pump stop | valve set-position 1|2 | camera snapshot | tec set-temperature C | z-stage enable-closed-loop | z-stage move UM | quit", flush=True)
        elif item in ("status", "devices"): print(controller.statuses(), flush=True)
        elif item == "quit": qt_app.quit()
        elif item is not None:
            try: controller.submit(item)
            except Exception as exc: print(f"validation error: {exc}", flush=True)
    reader.command.connect(handle); reader.output.connect(lambda text: print(text, flush=True)); controller.command_event.connect(lambda e: print(f"[{e.request_id}] {e.state} {e.message}", flush=True)); controller.start(); reader.start(); window.show(); return qt_app.exec()

if __name__ == "__main__": raise SystemExit(main())
