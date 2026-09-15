from __future__ import annotations


class SimulatedAD2:
    def __init__(self) -> None:
        self.initialized = False
        self.configured = False
        self.running = False
        self.triggered = False
        self.configuration: object | None = None

    def initialize(self) -> None:
        self.initialized = True

    def cleanup(self) -> None:
        self.running = False
        self.initialized = False

    def wfg_configure(self, configuration: object) -> None:
        self.configuration = configuration
        self.configured = True

    def wfg_start_stop_all_ch(self, running: bool) -> None:
        if running and not self.configured:
            raise RuntimeError("Configure AD2 before starting")
        self.running = running

    def pc_trigger(self) -> None:
        self.triggered = True
