from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from ..application.commands import (
    Ad2ConfigureScopeArgs,
    Ad2ConfigureWaveformArgs,
    Ad2ScopeReadResult,
    DeviceOperation,
    NoArguments,
)
from ..domain.models import Ad2Readback, DeviceId
from .base import DeviceWorker


class AD2Worker(DeviceWorker):
    def __init__(self, device_factory: Callable[[], object], parent=None) -> None:
        super().__init__(DeviceId.AD2, device_factory, readback_factory=Ad2Readback, parent=parent)
        self.register(DeviceOperation.AD2_WAVEFORM_CONFIGURE, self.configure_waveform)
        self.register(DeviceOperation.AD2_WAVEFORM_START, self.start_waveform)
        self.register(DeviceOperation.AD2_WAVEFORM_STOP, self.stop_waveform)
        self.register(DeviceOperation.AD2_SOFTWARE_TRIGGER, self.software_trigger)
        self.register(DeviceOperation.AD2_SCOPE_CONFIGURE, self.configure_scope)
        self.register(DeviceOperation.AD2_SCOPE_READ, self.read_scope)

    def configure_waveform(self, args: Ad2ConfigureWaveformArgs) -> None:
        if args.frequency_hz <= 0 or not 0 <= args.amplitude_v <= 5:
            raise ValueError("frequency_hz must be positive and amplitude_v must be 0..5")
        self.device.wfg_configure(
            {"frequency_hz": args.frequency_hz, "amplitude_v": args.amplitude_v}
        )
        self.state.configured = True
        self.state.readback = replace(
            self.state.readback,
            waveform_frequency_hz=args.frequency_hz,
            waveform_amplitude_v=args.amplitude_v,
        )

    def start_waveform(self, _args: NoArguments) -> None:
        if not self.state.configured:
            raise RuntimeError("Configure AD2 before starting")
        self.device.wfg_start_stop_all_ch(True)
        self.state.active = True
        self.state.readback = replace(self.state.readback, waveform_running=True)

    def stop_waveform(self, _args: NoArguments) -> None:
        self.device.wfg_start_stop_all_ch(False)
        self.state.active = self.state.readback.scope_state == "armed"
        self.state.readback = replace(self.state.readback, waveform_running=False)

    def safe_stop(self) -> None:
        if self.device_constructed and self.state.connected:
            self.device.wfg_start_stop_all_ch(False)
        self.state.active = False
        self.state.readback = replace(self.state.readback, waveform_running=False)

    def software_trigger(self, _args: NoArguments) -> None:
        self.device.pc_trigger()

    def configure_scope(self, args: Ad2ConfigureScopeArgs) -> None:
        self.device.scope_configure(
            {
                "sample_count": args.sample_count,
                "channels": list(args.channels),
                "trigger_source": args.trigger_source.value,
            }
        )
        self.state.active = True
        self.state.readback = replace(self.state.readback, scope_state="armed")

    def read_scope(self, _args: NoArguments) -> Ad2ScopeReadResult:
        try:
            return Ad2ScopeReadResult(self.device.scope_read())
        finally:
            self.state.active = self.state.readback.waveform_running
            self.state.readback = replace(self.state.readback, scope_state="idle")
