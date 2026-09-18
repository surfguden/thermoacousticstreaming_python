from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
import time

from ..application.commands import (
    Ad2ConfigureDigitalOutputArgs,
    Ad2ConfigureScopeArgs,
    Ad2ScopeAppliedResult,
    Ad2ScopeChannelArgs,
    Ad2ScopeTriggerArgs,
    Ad2ScopeTriggerCondition,
    Ad2ScopeTriggerFilter,
    Ad2ScopeTriggerLengthCondition,
    Ad2ScopeTriggerType,
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
from ..domain.models import (
    Ad2Capabilities,
    Ad2DigitalOutputCapabilities,
    Ad2Readback,
    Ad2ScopeCapabilities,
    Ad2WaveformChannelCapabilities,
    Ad2WaveformChannelReadback,
    Ad2WaveformNodeCapabilities,
    DeviceId,
    FloatRange,
    IntegerRange,
)
from .base import DeferredProgress, DeviceWorker


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
        self._capabilities: Ad2Capabilities | None = None

    def connect_device(self) -> None:
        super().connect_device()
        read_capabilities = getattr(self.device, "capabilities", None)
        if callable(read_capabilities):
            self._capabilities = self._convert_capabilities(read_capabilities())
            self.state.readback = replace(
                self.state.readback, capabilities=self._capabilities
            )
            self._emit_status()

    def disconnect_device(self) -> None:
        try:
            super().disconnect_device()
        finally:
            self._capabilities = None

    def configure_waveform(
        self, args: Ad2ConfigureWaveformArgs
    ) -> Ad2WaveformAppliedResult:
        channels = args.resolved_channels()
        self._validate_waveform(channels)
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
            self.device.scope_abort()
        self.state.active = False
        self.state.readback = replace(
            self.state.readback,
            waveform_running=False,
            digital_output_running=False,
            scope_state="idle",
        )

    def software_trigger(self, _args: NoArguments) -> None:
        self.device.pc_trigger()

    def configure_scope(self, args: Ad2ConfigureScopeArgs) -> Ad2ScopeAppliedResult:
        self._validate_scope(args)
        trigger = args.trigger
        self.device.scope_configure(
            {
                "sample_count": args.sample_count,
                "sample_frequency_hz": args.sample_frequency_hz,
                "pretrigger_samples": args.pretrigger_samples,
                "timeout_s": args.timeout_s,
                "poll_interval_s": args.poll_interval_s,
                "channels": [
                    {
                        "channel_index": channel.channel_index,
                        "range_v": channel.range_v,
                        "offset_v": channel.offset_v,
                    }
                    for channel in args.channels
                ],
                "trigger": {
                    "source": trigger.source.value,
                    "channel_index": trigger.channel_index,
                    "trigger_type": trigger.trigger_type.value,
                    "condition": trigger.condition.value,
                    "filter": trigger.filter.value,
                    "level_v": trigger.level_v,
                    "hysteresis_v": trigger.hysteresis_v,
                    "length_condition": trigger.length_condition.value,
                    "length_s": trigger.length_s,
                    "holdoff_s": trigger.holdoff_s,
                    "auto_timeout_s": trigger.auto_timeout_s,
                },
            }
        )
        self.state.configured = True
        self.state.active = True
        self.state.readback = replace(self.state.readback, scope_state="armed")
        applied = self.device.scope_readback()
        return Ad2ScopeAppliedResult(
            sample_count=applied.sample_count,
            sample_frequency_hz=applied.sample_frequency_hz,
            pretrigger_samples=applied.pretrigger_samples,
            channels=tuple(
                Ad2ScopeChannelArgs(channel.channel_index, channel.range_v, channel.offset_v)
                for channel in applied.channels
            ),
            trigger=Ad2ScopeTriggerArgs(
                source=Ad2TriggerSource(applied.trigger.source),
                channel_index=applied.trigger.channel_index,
                trigger_type=Ad2ScopeTriggerType(applied.trigger.trigger_type),
                condition=Ad2ScopeTriggerCondition(applied.trigger.condition),
                filter=Ad2ScopeTriggerFilter(applied.trigger.filter),
                level_v=applied.trigger.level_v,
                hysteresis_v=applied.trigger.hysteresis_v,
                length_condition=Ad2ScopeTriggerLengthCondition(applied.trigger.length_condition),
                length_s=applied.trigger.length_s,
                holdoff_s=applied.trigger.holdoff_s,
                auto_timeout_s=applied.trigger.auto_timeout_s,
            ),
        )

    def read_scope(self, _args: NoArguments):
        if self.state.readback.scope_state != "armed":
            raise RuntimeError("Configure the scope before reading")
        config = self.device.scope_config
        deadline = time.monotonic() + config.timeout_s

        def finish() -> None:
            self.state.active = self.state.readback.waveform_running
            self.state.readback = replace(self.state.readback, scope_state="idle")

        def step() -> DeferredProgress:
            samples = self.device.scope_poll()
            if samples is not None:
                finish()
                return DeferredProgress(True, Ad2ScopeReadResult(samples))
            if time.monotonic() >= deadline:
                raise TimeoutError("AnalogIn capture timed out before acquisition completed")
            return DeferredProgress(False)

        def cancel() -> None:
            try:
                self.device.scope_abort()
            finally:
                finish()

        return self.defer_operation(
            step, cancel=cancel, poll_interval_s=config.poll_interval_s
        )

    def configure_digital_output(self, args: Ad2ConfigureDigitalOutputArgs) -> None:
        self._validate_digital_output(args)
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

    @staticmethod
    def _float_range(values: tuple[float, ...]) -> FloatRange:
        return FloatRange(
            float(values[0]),
            float(values[1]),
            float(values[2]) if len(values) > 2 else None,
        )

    @staticmethod
    def _integer_range(values: tuple[int, int]) -> IntegerRange:
        return IntegerRange(int(values[0]), int(values[1]))

    @classmethod
    def _node_capabilities(cls, values: dict[str, object]) -> Ad2WaveformNodeCapabilities:
        return Ad2WaveformNodeCapabilities(
            frequency_hz=cls._float_range(values["frequency_hz"]),
            amplitude=cls._float_range(values["amplitude"]),
            offset=cls._float_range(values["offset"]),
            symmetry_percent=cls._float_range(values["symmetry_percent"]),
            phase_deg=cls._float_range(values["phase_deg"]),
        )

    @classmethod
    def _convert_capabilities(cls, values: dict[str, object]) -> Ad2Capabilities:
        waveform_channels = tuple(
            Ad2WaveformChannelCapabilities(
                channel_index=int(channel["channel_index"]),
                carrier=cls._node_capabilities(channel["carrier"]),
                fm=cls._node_capabilities(channel["fm"]),
                wait_s=cls._float_range(channel["wait_s"]),
                run_s=cls._float_range(channel["run_s"]),
                repeat_count=cls._integer_range(channel["repeat_count"]),
            )
            for channel in values["waveform_channels"]
        )
        scope = values["scope"]
        digital = values["digital_output"]
        return Ad2Capabilities(
            waveform_channels=waveform_channels,
            scope=Ad2ScopeCapabilities(
                sample_frequency_hz=cls._float_range(scope["sample_frequency_hz"]),
                sample_count=cls._integer_range(scope["sample_count"]),
                input_ranges_v=tuple(float(value) for value in scope["input_ranges_v"]),
                input_offset_v=cls._float_range(scope["input_offset_v"]),
                trigger_channel=cls._integer_range(scope["trigger_channel"]),
                trigger_level_v=cls._float_range(scope["trigger_level_v"]),
                trigger_hysteresis_v=cls._float_range(scope["trigger_hysteresis_v"]),
                trigger_holdoff_s=cls._float_range(scope["trigger_holdoff_s"]),
                trigger_auto_timeout_s=cls._float_range(scope["trigger_auto_timeout_s"]),
            ),
            digital_output=Ad2DigitalOutputCapabilities(
                channel_count=int(digital["channel_count"]),
                clock_frequency_hz=cls._float_range(digital["clock_frequency_hz"]),
                counter_bits=cls._integer_range(digital["counter_bits"]),
                custom_data_bits_max=int(digital["custom_data_bits_max"]),
                wait_s=cls._float_range(digital["wait_s"]),
                run_s=cls._float_range(digital["run_s"]),
                repeat_count=cls._integer_range(digital["repeat_count"]),
            ),
        )

    @staticmethod
    def _require_float_range(name: str, value: float, limits: FloatRange) -> None:
        if not limits.minimum <= value <= limits.maximum:
            raise ValueError(
                f"{name} must be within {limits.minimum:g}..{limits.maximum:g}; "
                f"received {value:g}"
            )

    @staticmethod
    def _require_integer_range(name: str, value: int, limits: IntegerRange) -> None:
        if not limits.minimum <= value <= limits.maximum:
            raise ValueError(
                f"{name} must be within {limits.minimum}..{limits.maximum}; "
                f"received {value}"
            )

    def _validate_waveform(self, channels: tuple[Ad2WaveformChannelArgs, ...]) -> None:
        if self._capabilities is None:
            if any(not 0 <= channel.amplitude_v <= 5 for channel in channels):
                raise ValueError("waveform amplitude_v must be within 0..5")
            return
        by_channel = {
            item.channel_index: item for item in self._capabilities.waveform_channels
        }
        for channel in channels:
            capability = by_channel[channel.channel_index]
            for prefix, node, values in (
                ("carrier", capability.carrier, channel),
                ("fm", capability.fm, channel),
            ):
                if prefix == "carrier":
                    fields = (
                        ("frequency_hz", values.frequency_hz, node.frequency_hz),
                        ("amplitude", values.amplitude_v, node.amplitude),
                        ("offset", values.offset_v, node.offset),
                        ("symmetry_percent", values.symmetry_percent, node.symmetry_percent),
                        ("phase_deg", values.phase_deg, node.phase_deg),
                    )
                else:
                    fields = (
                        ("frequency_hz", values.fm_frequency_hz, node.frequency_hz),
                        ("amplitude", values.fm_modulation_index_percent, node.amplitude),
                        ("offset", values.fm_offset_percent, node.offset),
                        ("symmetry_percent", values.fm_symmetry_percent, node.symmetry_percent),
                        ("phase_deg", values.fm_phase_deg, node.phase_deg),
                    )
                for name, value, limits in fields:
                    self._require_float_range(
                        f"waveform CH{channel.channel_index + 1} {prefix} {name}",
                        value,
                        limits,
                    )
            self._require_float_range("waveform trigger wait_s", channel.trigger.wait_s, capability.wait_s)
            self._require_float_range("waveform trigger run_s", channel.trigger.run_s, capability.run_s)
            self._require_integer_range(
                "waveform trigger repeat_count",
                channel.trigger.repeat_count,
                capability.repeat_count,
            )

    def _validate_scope(self, args: Ad2ConfigureScopeArgs) -> None:
        if self._capabilities is None:
            return
        limits = self._capabilities.scope
        self._require_integer_range("scope sample_count", args.sample_count, limits.sample_count)
        self._require_float_range(
            "scope sample_frequency_hz", args.sample_frequency_hz, limits.sample_frequency_hz
        )
        for channel in args.channels:
            if not any(abs(channel.range_v - value) <= 1e-12 for value in limits.input_ranges_v):
                allowed = ", ".join(f"{value:g}" for value in limits.input_ranges_v)
                raise ValueError(
                    f"scope CH{channel.channel_index + 1} range_v must be one of {allowed}; "
                    f"received {channel.range_v:g}"
                )
            self._require_float_range(
                f"scope CH{channel.channel_index + 1} offset_v",
                channel.offset_v,
                limits.input_offset_v,
            )
        trigger = args.trigger
        self._require_integer_range("scope trigger channel", trigger.channel_index, limits.trigger_channel)
        self._require_float_range("scope trigger level_v", trigger.level_v, limits.trigger_level_v)
        self._require_float_range(
            "scope trigger hysteresis_v", trigger.hysteresis_v, limits.trigger_hysteresis_v
        )
        self._require_float_range(
            "scope trigger holdoff_s", trigger.holdoff_s, limits.trigger_holdoff_s
        )
        self._require_float_range(
            "scope trigger auto_timeout_s",
            trigger.auto_timeout_s,
            limits.trigger_auto_timeout_s,
        )

    def _validate_digital_output(self, args: Ad2ConfigureDigitalOutputArgs) -> None:
        if self._capabilities is None:
            return
        limits = self._capabilities.digital_output
        if not 0 <= args.channel_index < limits.channel_count:
            raise ValueError(
                f"digital output channel_index must be within 0..{limits.channel_count - 1}; "
                f"received {args.channel_index}"
            )
        if args.clock_frequency_hz is not None:
            self._require_float_range(
                "digital output clock_frequency_hz",
                args.clock_frequency_hz,
                limits.clock_frequency_hz,
            )
        for name, value in (
            ("counter_high_bits", args.counter_high_bits),
            ("counter_low_bits", args.counter_low_bits),
        ):
            self._require_integer_range(f"digital output {name}", value, limits.counter_bits)
        if len(args.bits) > limits.custom_data_bits_max:
            raise ValueError(
                f"digital output custom data must contain at most "
                f"{limits.custom_data_bits_max} bits; received {len(args.bits)}"
            )
        self._require_float_range("digital trigger wait_s", args.trigger.wait_s, limits.wait_s)
        self._require_float_range("digital trigger run_s", args.trigger.run_s, limits.run_s)
        self._require_integer_range(
            "digital trigger repeat_count", args.trigger.repeat_count, limits.repeat_count
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
