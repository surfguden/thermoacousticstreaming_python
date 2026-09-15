from __future__ import annotations

from .configuration import ScopeConfig, coerce_scope_config


class SimulatedAD2:
    def __init__(self) -> None:
        self.initialized = False
        self.configured = False
        self.running = False
        self.triggered = False
        self.configuration: object | None = None
        self.scope_config: ScopeConfig | None = None
        self.scope_armed = False

    def initialize(self) -> None:
        self.initialized = True

    def cleanup(self) -> None:
        self.running = False
        self.scope_armed = False
        self.scope_config = None
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

    def scope_configure(self, configuration: ScopeConfig | dict | None) -> None:
        if self.scope_armed:
            raise RuntimeError("Cannot configure scope while it is armed")
        self.scope_config = coerce_scope_config(configuration)
        self.scope_armed = True

    def scope_read(self) -> dict[int, list[float]]:
        if not self.scope_armed or self.scope_config is None:
            raise RuntimeError("scope_read() requires an armed scope")
        try:
            return {
                channel.channel_index: [0.0] * self.scope_config.sample_count
                for channel in self.scope_config.channels
            }
        finally:
            self.scope_armed = False
