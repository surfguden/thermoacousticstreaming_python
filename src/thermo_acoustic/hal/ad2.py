from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from ..application.commands import (
    Ad2ConfigureDigitalOutputArgs,
    Ad2ConfigureScopeArgs,
    Ad2ConfigureWaveformArgs,
    Ad2AnalogOutputIdle,
    Ad2WaveformAppliedResult,
    Ad2WaveformChannelArgs,
    Ad2WaveformFunction,
    Ad2TriggerSettingsArgs,
    Ad2TriggerSource,
    Ad2ScopeReadResult,
    DeviceOperation,
    NoArguments,
)
from ..domain.models import Ad2Readback, Ad2WaveformChannelReadback, DeviceId
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

    def configure_waveform(
        self, args: Ad2ConfigureWaveformArgs
    ) -> Ad2WaveformAppliedResult:
        channels = args.resolved_channels()
        if any(not 0 <= channel.amplitude_v <= 5 for channel in channels):
            raise ValueError("waveform amplitude_v must be within 0..5")
        self.device.wfg_configure(
            {
                "channels": [self._waveform_channel_settings(channel) for channel in channels]
            }
        )
        self.state.configured = True
        self.state.readback = replace(
            self.state.readback,
            waveform_frequency_hz=channels[0].frequency_hz,
            waveform_amplitude_v=channels[0].amplitude_v,
        )
        try:
            applied = self._waveform_result(self.device.wfg_readback())
        except Exception as exc:
            raise RuntimeError(
                f"waveform configuration was applied, but SDK readback failed: {exc}"
            ) from exc
        channel_readbacks = tuple(self._waveform_readback(item) for item in applied.channels)
        first = applied.channels[0]
        self.state.readback = replace(
            self.state.readback,
            waveform_frequency_hz=first.frequency_hz,
            waveform_amplitude_v=first.amplitude_v,
            waveform_channels=channel_readbacks,
        )
        return applied

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

    @classmethod
    def _waveform_channel_settings(
        cls, args: Ad2WaveformChannelArgs
    ) -> dict[str, object]:
        return {
            "channel_index": args.channel_index,
            "carrier": {
                "enable": args.enabled,
                "function": args.function.value,
                "frequency_hz": args.frequency_hz,
                "amplitude_v": args.amplitude_v,
                "offset_v": args.offset_v,
                "symmetry_percent": args.symmetry_percent,
                "phase_deg": args.phase_deg,
            },
            "fm_mod": {
                "enable": args.fm_enabled,
                "function": args.fm_function.value,
                "frequency_hz": args.fm_frequency_hz,
                "amplitude_v": args.fm_modulation_index_percent,
                "offset_v": args.fm_offset_percent,
                "symmetry_percent": args.fm_symmetry_percent,
                "phase_deg": args.fm_phase_deg,
            },
            "idle_state": args.idle_state.value,
            "trigger": cls._trigger_settings(args.trigger),
        }

    @staticmethod
    def _waveform_result(config: object) -> Ad2WaveformAppliedResult:
        channels = []
        for channel in sorted(config.channels, key=lambda item: item.channel_index):
            carrier = channel.carrier
            fm = channel.fm_mod
            trigger = channel.trigger
            channels.append(
                Ad2WaveformChannelArgs(
                    channel_index=channel.channel_index,
                    enabled=carrier.enable,
                    function=Ad2WaveformFunction(carrier.function.value),
                    frequency_hz=carrier.frequency_hz,
                    amplitude_v=carrier.amplitude_v,
                    offset_v=carrier.offset_v,
                    symmetry_percent=carrier.symmetry_percent,
                    phase_deg=carrier.phase_deg,
                    fm_enabled=fm.enable,
                    fm_function=Ad2WaveformFunction(fm.function.value),
                    fm_frequency_hz=fm.frequency_hz,
                    fm_modulation_index_percent=fm.amplitude_v,
                    fm_offset_percent=fm.offset_v,
                    fm_symmetry_percent=fm.symmetry_percent,
                    fm_phase_deg=fm.phase_deg,
                    idle_state=Ad2AnalogOutputIdle(channel.idle_state.value),
                    trigger=Ad2TriggerSettingsArgs(
                        source=Ad2TriggerSource(trigger.source.value),
                        wait_s=trigger.sec_wait,
                        run_s=trigger.sec_run,
                        repeat_count=trigger.repeat_count,
                        repeat_trigger=trigger.repeat_trigger,
                    ),
                )
            )
        return Ad2WaveformAppliedResult(tuple(channels), bool(config.running))

    @staticmethod
    def _waveform_readback(
        channel: Ad2WaveformChannelArgs,
    ) -> Ad2WaveformChannelReadback:
        return Ad2WaveformChannelReadback(
            channel_index=channel.channel_index,
            enabled=channel.enabled,
            function=channel.function.value,
            frequency_hz=channel.frequency_hz,
            amplitude_v=channel.amplitude_v,
            offset_v=channel.offset_v,
            symmetry_percent=channel.symmetry_percent,
            phase_deg=channel.phase_deg,
            fm_enabled=channel.fm_enabled,
            fm_function=channel.fm_function.value,
            fm_frequency_hz=channel.fm_frequency_hz,
            fm_modulation_index_percent=channel.fm_modulation_index_percent,
            fm_offset_percent=channel.fm_offset_percent,
            fm_symmetry_percent=channel.fm_symmetry_percent,
            fm_phase_deg=channel.fm_phase_deg,
            idle_state=channel.idle_state.value,
            trigger_source=channel.trigger.source.value,
            trigger_wait_s=channel.trigger.wait_s,
            trigger_run_s=channel.trigger.run_s,
            trigger_repeat_count=channel.trigger.repeat_count,
            trigger_repeat=channel.trigger.repeat_trigger,
        )
