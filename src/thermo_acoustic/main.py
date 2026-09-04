"""Simulation-only queue smoke entry point.

The operator GUI entry points live in :mod:`thermo_acoustic.qt_ui` and
:mod:`thermo_acoustic.qt_ui_v3`.  This small module is retained for exercising
the message-dispatch path without opening real hardware.
"""

from __future__ import annotations

from .application import Application
from .instruments import SimulatedAD2Sdk
from .messages import Message, MessageName


def main() -> None:
    app = Application(ad2=SimulatedAD2Sdk())
    try:
        app.enqueue_main(Message(MessageName.INITIALIZE))
        app.run_until_idle()
        print(app.status)
    finally:
        app.cleanup()


if __name__ == "__main__":
    main()

