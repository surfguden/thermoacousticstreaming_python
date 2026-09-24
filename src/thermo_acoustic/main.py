from __future__ import annotations
import argparse, sys
from PySide6.QtWidgets import QApplication
from .application import ApplicationController, AuditLogger
from .console.reader import ConsoleCommandReader
from .hal.registry import DeviceRegistry
from .domain.models import OperatingMode
from .ui.main_window import MainWindow, configure_palette
from .console.parser import help_text
from .console.parser import ExperimentConsoleCommand
from .application.experiments import load_definition, validate_definition
from .application.event_formatting import detailed_event_text

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--mode", choices=["simulation", "real"], default="simulation"); parser.add_argument("--audit-log", default=None); args = parser.parse_args(argv)
    qt_app = QApplication(sys.argv[:1]); configure_palette(qt_app); mode = OperatingMode(args.mode); controller = ApplicationController(DeviceRegistry(mode), mode=mode, audit=AuditLogger(args.audit_log)); window = MainWindow(controller); controller.confirm_operation = window.confirm_operation; reader = ConsoleCommandReader()
    def handle(item):
        if item == "help": print(help_text(), flush=True)
        elif item in ("status", "devices"): print(controller.statuses(), flush=True)
        elif item == "quit": qt_app.quit()
        elif isinstance(item, ExperimentConsoleCommand):
            try:
                manager = controller.experiments
                if item.operation == "validate":
                    expansion = validate_definition(load_definition(item.path))
                    print(f"Valid: {len(expansion.experiments)} experiments", flush=True)
                    for entry in expansion.experiments:
                        print(f"{entry.experiment_id}: {entry.relative_path} {entry.parameters}", flush=True)
                elif item.operation == "queue":
                    folder = manager.queue(load_definition(item.path), item.output_root, item.image_format)
                    print(f"Queued experiment series: {folder}", flush=True)
                elif item.operation == "start":
                    print("Batch started" if manager.start() else "Batch not approved", flush=True)
                elif item.operation == "status":
                    print(manager.status(), flush=True)
                elif item.operation == "stop-after-current":
                    manager.stop_after_current()
                    print(manager.status(), flush=True)
                elif item.operation == "abort":
                    manager.abort()
                    print(manager.status(), flush=True)
            except Exception as exc:
                print(f"experiment error: {exc}", flush=True)
        elif item is not None:
            try: controller.submit(item)
            except Exception as exc: print(f"validation error: {exc}", flush=True)
    reader.command.connect(handle); reader.output.connect(lambda text: print(text, flush=True)); controller.command_event.connect(lambda event: print(detailed_event_text(event), flush=True)); controller.start(); reader.start(); window.showMaximized(); return qt_app.exec()

if __name__ == "__main__": raise SystemExit(main())
