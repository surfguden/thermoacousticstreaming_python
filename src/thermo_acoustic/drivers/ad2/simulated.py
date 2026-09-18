from __future__ import annotations

from copy import deepcopy

from .configuration import (
    DoConfig,
    ScopeConfig,
    WfgConfig,
    coerce_do_config,
    coerce_scope_config,
    coerce_wfg_config,
)


class SimulatedAD2:
    def __init__(self) -> None:
        self.initialized = False
        self.configured = False
        self.running = False
        self.triggered = False
        self.configuration: WfgConfig | None = None
        self.scope_config: ScopeConfig | None = None
        self.scope_armed = False
        self.do_config: DoConfig | None = None
        self.digital_output_running = False

    def initialize(self) -> None:
        self.initialized = True

    def capabilities(self) -> dict[str, object]:
        node = {
            "frequency_hz": (0.001, 100_000_000.0),
            "amplitude": (0.0, 5.0),
            "offset": (-5.0, 5.0),
            "symmetry_percent": (0.0, 100.0),
            "phase_deg": (-360.0, 360.0),
        }
        waveform_channels = tuple(
            {
                "channel_index": index,
                "carrier": dict(node),
                "fm": dict(node),
                "wait_s": (0.0, 1_000_000.0),
                "run_s": (0.0, 1_000_000.0),
                "repeat_count": (0, 1_000_000),
            }
            for index in (0, 1)
        )
        return {
            "waveform_channels": waveform_channels,
            "scope": {
                "sample_frequency_hz": (0.001, 100_000_000.0),
                "sample_count": (1, 16_384),
                "input_ranges_v": (0.5, 1.0, 2.0, 5.0, 10.0, 25.0, 50.0),
                "input_offset_v": (-50.0, 50.0, 0.001),
                "trigger_channel": (0, 1),
                "trigger_level_v": (-50.0, 50.0, 0.001),
                "trigger_hysteresis_v": (0.0, 50.0, 0.001),
                "trigger_holdoff_s": (0.0, 3600.0, 0.000001),
                "trigger_auto_timeout_s": (0.0, 3600.0, 0.001),
            },
            "digital_output": {
                "channel_count": 16,
                "clock_frequency_hz": (0.001, 50_000_000.0),
                "counter_bits": (1, 65_535),
                "custom_data_bits_max": 16_384,
                "wait_s": (0.0, 1_000_000.0),
                "run_s": (0.0, 1_000_000.0),
                "repeat_count": (0, 1_000_000),
            },
        }

    def cleanup(self) -> None:
        self.running = False
        self.scope_armed = False
        self.scope_config = None
        self.digital_output_running = False
        self.do_config = None
        self.initialized = False

    def wfg_configure(self, configuration: object) -> None:
        self.configuration = coerce_wfg_config(configuration)
        for channel in self.configuration.channels:
            channel.effective_carrier = deepcopy(channel.carrier)
            channel.effective_fm_mod = (
                deepcopy(channel.fm_mod) if channel.fm_mod.enable else None
            )
        self.configured = True

    def wfg_readback(self) -> WfgConfig:
        if self.configuration is None:
            raise RuntimeError("Configure AD2 before reading waveform settings")
        return deepcopy(self.configuration)

    def wfg_start_stop_all_ch(self, running: bool) -> None:
        if running and not self.configured:
            raise RuntimeError("Configure AD2 before starting")
        self.running = running
        if self.configuration is not None:
            self.configuration.running = running

    def pc_trigger(self) -> None:
        self.triggered = True

    def do_configure(self, configuration: DoConfig | dict | None) -> None:
        self.do_config = coerce_do_config(configuration)
        self.digital_output_running = False

    def start_stop_do(self, running: bool) -> None:
        if running and self.do_config is None:
            raise RuntimeError("Configure digital output before starting")
        self.digital_output_running = running
        if self.do_config is not None:
            self.do_config.running = running

    def do_reset(self) -> None:
        self.digital_output_running = False
        self.do_config = DoConfig()

    def scope_configure(self, configuration: ScopeConfig | dict | None) -> None:
        if self.scope_armed:
            raise RuntimeError("Cannot configure scope while it is armed")
        self.scope_config = coerce_scope_config(configuration)
        self.scope_armed = True

    def scope_readback(self) -> ScopeConfig:
        if self.scope_config is None:
            raise RuntimeError("Configure scope before reading its settings")
        return deepcopy(self.scope_config)

    def scope_poll(self) -> dict[int, list[float]] | None:
        return self.scope_read()

    def scope_abort(self) -> None:
        self.scope_armed = False

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
