from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from ..application.commands import (
    Ad2ConfigureDigitalOutputArgs,
    Ad2ConfigureScopeArgs,
    Ad2ConfigureWaveformArgs,
    Ad2TriggerSettingsArgs,
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
        self.register(
            DeviceOperation.AD2_DIGITAL_OUTPUT_CONFIGURE,
            self.configure_digital_output,
        )
        self.register(DeviceOperation.AD2_DIGITAL_OUTPUT_START, self.start_digital_output)
        self.register(DeviceOperation.AD2_DIGITAL_OUTPUT_STOP, self.stop_digital_output)
        self.register(DeviceOperation.AD2_DIGITAL_OUTPUT_RESET, self.reset_digital_output)

    def configure_waveform(self, args: Ad2ConfigureWaveformArgs) -> None:
        if args.frequency_hz <= 0 or not 0 <= args.amplitude_v <= 5:
            raise ValueError("frequency_hz must be positive and amplitude_v must be 0..5")
        self.device.wfg_configure(
            {
                "frequency_hz": args.frequency_hz,
                "amplitude_v": args.amplitude_v,
                "trigger": self._trigger_settings(args.trigger),
            }
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
            self.device.start_stop_do(False)
        self.state.active = False
        self.state.readback = replace(
            self.state.readback,
            waveform_running=False,
            digital_output_running=False,
        )

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

    def configure_digital_output(self, args: Ad2ConfigureDigitalOutputArgs) -> None:
        if args.channel_index < 0:
            raise ValueError("channel_index must be non-negative")
        if args.clock_frequency_hz is not None and args.clock_frequency_hz <= 0:
            raise ValueError("clock_frequency_hz must be positive")
        if any(bit not in (0, 1) for bit in args.bits):
            raise ValueError("digital output bits must contain only 0 or 1")
        if args.output_type.value == "Custom" and not args.bits:
            raise ValueError("custom digital output requires a non-empty bit pattern")
        if args.counter_high_bits < 0 or args.counter_low_bits < 0:
            raise ValueError("digital output counter lengths must be non-negative")
        self.device.do_configure(
            {
                "channel_index": args.channel_index,
                "enabled": args.enabled,
                "output_type": args.output_type.value,
                "clock_frequency_hz": args.clock_frequency_hz,
                "counter_high_bits": args.counter_high_bits,
                "counter_low_bits": args.counter_low_bits,
                "start_high": args.start_high,
                "bits": list(args.bits),
                "frame_count": args.frame_count,
                "trigger": self._trigger_settings(args.trigger),
            }
        )
        self.state.readback = replace(
            self.state.readback,
            digital_output_configured=True,
            digital_output_running=False,
            digital_output_channel=args.channel_index,
            digital_output_clock_frequency_hz=args.clock_frequency_hz,
        )

    def start_digital_output(self, _args: NoArguments) -> None:
        if not self.state.readback.digital_output_configured:
            raise RuntimeError("Configure digital output before starting")
        self.device.start_stop_do(True)
        self.state.active = True
        self.state.readback = replace(self.state.readback, digital_output_running=True)

    def stop_digital_output(self, _args: NoArguments) -> None:
        self.device.start_stop_do(False)
        self.state.readback = replace(self.state.readback, digital_output_running=False)
        self.state.active = (
            self.state.readback.waveform_running or self.state.readback.scope_state == "armed"
        )

    def reset_digital_output(self, _args: NoArguments) -> None:
        self.device.do_reset()
        self.state.readback = replace(
            self.state.readback,
            digital_output_configured=False,
            digital_output_running=False,
            digital_output_channel=None,
            digital_output_clock_frequency_hz=None,
        )
        self.state.active = (
            self.state.readback.waveform_running or self.state.readback.scope_state == "armed"
        )

    @staticmethod
    def _trigger_settings(args: Ad2TriggerSettingsArgs) -> dict[str, object]:
        return {
            "source": args.source.value,
            "sec_wait": args.wait_s,
            "sec_run": args.run_s,
            "repeat_count": args.repeat_count,
            "repeat_trigger": args.repeat_trigger,
        }
