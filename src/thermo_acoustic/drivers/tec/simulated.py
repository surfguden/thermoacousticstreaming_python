from __future__ import annotations

from .controller import TEC_CHANNELS, TecStatus, validate_tec_target_temperature


class SimulatedTec:
    def __init__(self, channels: tuple[int, ...] = TEC_CHANNELS) -> None:
        self.initialized = False
        self.outputs_enabled = False
        self.targets_c: dict[int, float] = {}
        self.channels = channels

    def initialize(self) -> None:
        self.initialized = True

    def cleanup(self) -> None:
        self.set_output_stage_static_off()
        self.initialized = False

    def apply_static_setpoint(
        self, temperature_c: float | dict[int, float], channels: tuple[int, ...] | None = None
    ) -> dict[int, TecStatus]:
        resolved_channels = self.channels if channels is None else channels
        if isinstance(temperature_c, dict):
            targets = {
                channel: validate_tec_target_temperature(value)
                for channel, value in temperature_c.items()
            }
            if set(targets) != set(resolved_channels):
                raise ValueError(
                    f"Per-channel temperature dict keys {sorted(targets)} must exactly match "
                    f"channels {sorted(resolved_channels)}."
                )
        else:
            target = validate_tec_target_temperature(temperature_c)
            targets = {channel: target for channel in resolved_channels}
        self.targets_c = {channel: targets[channel] for channel in resolved_channels}
        self.outputs_enabled = True

        return self.read_status(resolved_channels)

    def read_status(self, channels: tuple[int, ...] | None = None) -> dict[int, TecStatus]:
        resolved_channels = self.channels if channels is None else channels
        return {
            channel: TecStatus(
                channel=channel,
                current_temperature_c=self.targets_c.get(channel),
                target_temperature_c=self.targets_c.get(channel),
                output_stage_static_on=self.outputs_enabled,
                ready=self.outputs_enabled,
            )
            for channel in resolved_channels
        }

    def set_output_stage_static_off(self, channels: tuple[int, ...] | None = None) -> dict[int, TecStatus]:
        self.outputs_enabled = False
        return self.read_status(channels)
