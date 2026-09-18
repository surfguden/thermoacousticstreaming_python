"""Exercise the real AD2 Connect path through the controller and Qt UI."""

from __future__ import annotations

__test__ = False

import argparse
import sys
from pathlib import Path

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from thermo_acoustic.application import ApplicationController
from thermo_acoustic.application.commands import DeviceOperation
from thermo_acoustic.domain.models import ConnectionState, DeviceId, OperatingMode
from thermo_acoustic.hal.registry import DeviceRegistry
from thermo_acoustic.ui.main_window import MainWindow


CONFIRM_TEXT = "CONFIRM_REAL_AD2_UI_CONNECT"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm", help=f"Required exact acknowledgement: {CONFIRM_TEXT}")
    args = parser.parse_args(argv)
    if args.confirm != CONFIRM_TEXT:
        print(
            f"REFUSING real device access. Pass --confirm {CONFIRM_TEXT} "
            "after checking that the AD2 is safe to open.",
            file=sys.stderr,
        )
        return 2

    app = QApplication.instance() or QApplication(["manual-ad2-ui-connect"])
    controller = ApplicationController(DeviceRegistry(OperatingMode.REAL), mode=OperatingMode.REAL)
    window = MainWindow(controller)
    controller.confirm_real_connection = lambda device: device is DeviceId.AD2
    terminal_events = []
    loop = QEventLoop()

    def capture(event) -> None:
        if (
            event.device is DeviceId.AD2
            and event.operation is DeviceOperation.CONNECT
            and event.state in {"completed", "failed", "cancelled"}
        ):
            terminal_events.append(event)
            loop.quit()

    controller.command_event.connect(capture)
    controller.start()
    try:
        window.panels[DeviceId.AD2]._buttons["connect"].click()
        timeout = QTimer()
        timeout.setSingleShot(True)
        timeout.timeout.connect(loop.quit)
        timeout.start(15_000)
        if not terminal_events:
            loop.exec()
        if not terminal_events:
            raise TimeoutError("AD2 UI Connect did not finish within 15 seconds")
        event = terminal_events[-1]
        if event.state != "completed":
            raise RuntimeError(event.message or f"AD2 UI Connect ended as {event.state}")

        status = controller.statuses()[DeviceId.AD2]
        if status.connection is not ConnectionState.CONNECTED:
            raise RuntimeError(f"Unexpected AD2 connection state: {status.connection.value}")
        capabilities = status.readback.capabilities
        if capabilities is None:
            raise RuntimeError("AD2 connected without capability readback")
        scope = window.panels[DeviceId.AD2].scope_controls
        ui_ranges = tuple(
            scope.channel_range[0].itemData(index)
            for index in range(scope.channel_range[0].count())
        )
        if ui_ranges != capabilities.scope.input_ranges_v:
            raise RuntimeError(
                f"UI input ranges {ui_ranges} do not match SDK {capabilities.scope.input_ranges_v}"
            )
        if scope.sample_rate.value() != capabilities.scope.sample_frequency_hz.maximum:
            raise RuntimeError("UI scope rate did not adopt the SDK maximum")
        print(
            "AD2 UI Connect completed: "
            f"scope={capabilities.scope.sample_frequency_hz.minimum:g}.."
            f"{capabilities.scope.sample_frequency_hz.maximum:g} Hz, "
            f"buffer={capabilities.scope.sample_count.minimum}.."
            f"{capabilities.scope.sample_count.maximum}, ranges={ui_ranges}"
        )
        return 0
    except Exception as exc:
        print(f"AD2 UI Connect failed: {exc}", file=sys.stderr)
        return 1
    finally:
        window.close()
        app.processEvents()


if __name__ == "__main__":
    raise SystemExit(main())
