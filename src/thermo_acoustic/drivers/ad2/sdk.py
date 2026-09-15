from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass, field
import logging
import math
import time
from .models import DoConfig, DoSingleChannelConfig, MsoConfig, TriggerSource, WfgChannelConfig, WfgConfig, coerce_do_config, coerce_wfg_config
from ..common.logging import log_call
from .waveforms import WaveFormsBackend

logger = logging.getLogger(__name__)

class AD2SdkError(RuntimeError):
    pass


@dataclass(slots=True)
class AD2Sdk:
    enabled: bool = True
    backend: WaveFormsBackend | None = None
    library_path: str | Path | None = None
    wfg_config: WfgConfig | None = None
    do_config: DoConfig | None = None
    do_custom_config: DoConfig | None = None
    do_clock_settings: DoConfig | None = None
    mso_config: MsoConfig | None = None
    device_handle: int | None = None
    triggered: bool = False

    def get_backend(self) -> WaveFormsBackend:
        if self.backend is None:
            self.backend = WaveFormsBackend(self.library_path)
        return self.backend

    def initialize(self) -> None:
        if self.enabled:
            # LabVIEW AD2_SDK_Init/OpenAndUseFirstDevice maps here.
            self.open_and_use_first_device()

    def cleanup(self) -> None:
        handle = self.device_handle
        errors: list[str] = []
        try:
            if handle is None:
                return
            backend = self.get_backend()
            for channel_index in (0, 1):
                for operation, action in (
                    ("stop", lambda channel_index=channel_index: backend.analog_out_configure(handle, channel_index, False)),
                    ("reset", lambda channel_index=channel_index: backend.analog_out_reset(handle, channel_index)),
                ):
                    try:
                        action()
                    except Exception as exc:
                        errors.append(
                            f"AnalogOut channel {channel_index} {operation} failed: {exc}"
                        )
            # DigitalOut is now part of the canonical production trigger path.
            # Keep its shutdown independent from AnalogOut and device-close so
            # one failed cleanup command cannot skip the remaining safeguards.
            for operation, action in (
                ("stop", lambda: backend.digital_out_configure(handle, False)),
                ("reset", lambda: backend.reset_do(handle)),
            ):
                try:
                    action()
                except Exception as exc:
                    errors.append(f"DigitalOut {operation} failed: {exc}")
            try:
                backend.close(handle)
            except Exception as exc:
                errors.append(f"device close failed: {exc}")
        finally:
            self.device_handle = None
            self.triggered = False
        if errors:
            raise AD2SdkError("; ".join(errors))

    def open_and_use_first_device(self) -> int | None:
        if not self.enabled:
            self.device_handle = None
        elif self.device_handle is None:
            self.device_handle = self.get_backend().open_first_device()
        return self.device_handle

    def get_phdwf(self) -> int | None:
        return self.device_handle

    def pc_trigger(self) -> None:
        # Was: silently no-op'd and still set self.triggered = True when
        # handle was None (AD2 disabled) -- a real experiment run with AD2
        # disabled would report a successful trigger that never reached
        # hardware, with nothing in the UI/log/experiment record to reveal
        # it. Same reasoning as config_wfg()/config_do_clock_special()
        # above: the real automated path now checks ad2.enabled and skips
        # this call entirely when disabled, so reaching here with a None
        # handle is a caller bug.
        handle = self.open_and_use_first_device()
        if handle is None:
            raise AD2SdkError("pc_trigger() called while AD2 is disabled -- caller must check ad2.enabled first.")
        self.get_backend().trigger_pc(handle)
        self.triggered = True

    def get_wfg_config(self) -> WfgConfig:
        if self.wfg_config is None:
            self.wfg_config = WfgConfig()
        return self.wfg_config

    def set_wfg_config(self, config: WfgConfig | dict | None) -> None:
        self.wfg_config = coerce_wfg_config(config)

    def config_wfg(self, config: WfgConfig | dict | None) -> None:
        # Finding 2 (waveforms.py review, Session 66): self.wfg_config is
        # only committed after the real backend call succeeds -- previously
        # assigned up front (via set_wfg_config()), so a failure partway
        # through a multi-channel configure_wfg() call (each channel issues
        # several independent _check()-guarded DWF calls) left self.wfg_config
        # reflecting the requested-but-never-(fully)-applied configuration,
        # not the last confirmed one. Same shape as hamamatsu_dcam.py's
        # configure_sequence() fix earlier today.
        new_config = coerce_wfg_config(config)
        handle = self.open_and_use_first_device()
        if handle is None:
            # open_and_use_first_device() only returns None when self.enabled
            # is False (a real device failure raises instead, never returns a
            # falsy handle -- see WaveFormsBackend.open_device()). Callers on
            # the real automated path (Application.run_experiment2()) are
            # expected to check ad2.enabled themselves and skip this call
            # entirely when disabled -- reaching here with a disabled device
            # is a caller bug, not a legitimate "disabled" outcome to
            # silently absorb (previously this method silently no-op'd,
            # which let a disabled AD2 report a successful WFG configuration
            # that never actually reached hardware).
            raise AD2SdkError("config_wfg() called while AD2 is disabled -- caller must check ad2.enabled first.")
        self.get_backend().configure_wfg(handle, new_config)
        self.wfg_config = new_config

    def wfg_check_config_valid(self) -> bool:
        return self.get_wfg_config().check_valid()

    def wfg_configure_carrier_single_ch(self, channel_index: int, channel: WfgChannelConfig) -> None:
        config = self.get_wfg_config()
        config.channels[channel_index] = channel

    def wfg_configure_trigger_single_ch(self, channel_index: int, channel: WfgChannelConfig) -> None:
        self.wfg_configure_carrier_single_ch(channel_index, channel)

    def wfg_configure_fm_mod_single_ch(self, channel_index: int, channel: WfgChannelConfig) -> None:
        self.wfg_configure_carrier_single_ch(channel_index, channel)

    def wfg_dynamic_config_ch(self, channel_index: int, channel: WfgChannelConfig) -> None:
        self.wfg_configure_carrier_single_ch(channel_index, channel)

    def wfg_configure_single_ch(self, channel_index: int, channel: WfgChannelConfig) -> None:
        self.wfg_configure_carrier_single_ch(channel_index, channel)

    def wfg_configure(self, config: WfgConfig | dict | None) -> None:
        # AD2 SDK review: same fix as config_wfg()
        # above -- raise instead of silently no-op'ing when AD2 is disabled.
        # Finding 2 (waveforms.py review, Session 66): same commit-after-
        # confirmation reordering as config_wfg() above.
        new_config = coerce_wfg_config(config)
        handle = self.open_and_use_first_device()
        if handle is None:
            raise AD2SdkError("wfg_configure() called while AD2 is disabled -- caller must check ad2.enabled first.")
        self.get_backend().configure_wfg(handle, new_config)
        self.wfg_config = new_config

    def wfg_configure_read_back(self) -> WfgConfig:
        return self.get_wfg_config()

    def wfg_start_stop_all_ch(self, running: bool) -> None:
        # Configure a copy first: the existing cached config is the last
        # confirmed hardware state and must survive a failed start/stop call.
        new_config = deepcopy(self.get_wfg_config())
        new_config.running = running
        handle = self.open_and_use_first_device()
        if handle is None:
            raise AD2SdkError(
                "wfg_start_stop_all_ch() called while AD2 is disabled -- caller must check ad2.enabled first."
            )
        self.get_backend().configure_wfg(handle, new_config)
        self.wfg_config = new_config

    def get_do_config(self) -> DoConfig:
        if self.do_config is None:
            self.do_config = DoConfig()
        return self.do_config

    def config_do_custom(self, config: DoConfig | dict | None) -> None:
        # Finding 2 (waveforms.py review, Session 66): commit do_custom_config/
        # do_config only after the real backend call succeeds -- same
        # reasoning as config_wfg() above.
        new_config = coerce_do_config(config)
        handle = self.open_and_use_first_device()
        if handle is None:
            raise AD2SdkError(
                "config_do_custom() called while AD2 is disabled -- caller must check ad2.enabled first."
            )
        self.get_backend().configure_do(handle, new_config)
        self.do_custom_config = new_config
        self.do_config = new_config

    def config_do_clock_special(self, settings: DoConfig | dict | None) -> None:
        # Finding 2 (waveforms.py review, Session 66): same reordering as
        # config_wfg()/config_do_custom() above.
        new_config = coerce_do_config(settings)
        handle = self.open_and_use_first_device()
        if handle is None:
            # Same reasoning as config_wfg() above -- the real automated
            # path is expected to check ad2.enabled and skip this call
            # entirely when disabled.
            raise AD2SdkError(
                "config_do_clock_special() called while AD2 is disabled -- caller must check ad2.enabled first."
            )
        self.get_backend().configure_do(handle, new_config)
        self.do_clock_settings = new_config
        self.do_config = new_config

    def do_config_trigger(self, trigger_source: str) -> None:
        for channel in self.get_do_config().channels:
            channel.trigger.source = trigger_source

    def do_configure_idle(self, channel_index: int, channel: DoSingleChannelConfig) -> None:
        self.get_do_config().channel(channel_index).idle_state = channel.idle_state

    def do_divider_config(self, channel_index: int, clock_divider: int) -> None:
        self.get_do_config().channel(channel_index).clock_divider = clock_divider

    def do_type_config(self, channel_index: int, channel: DoSingleChannelConfig) -> None:
        target = self.get_do_config().channel(channel_index)
        target.output_type = channel.output_type
        target.output_mode = channel.output_mode

    def do_enable_set(self, channel_index: int, enabled: bool) -> None:
        self.get_do_config().channel(channel_index).enable = enabled

    def do_custom_pattern_build_array(self, high_bits: int, low_bits: int) -> list[int]:
        return [1] * max(high_bits, 0) + [0] * max(low_bits, 0)

    def do_configure_custom_pattern(self, channel_index: int, bits: list[int]) -> None:
        channel = self.get_do_config().channel(channel_index)
        channel.custom_data.bits = bits
        channel.custom_data.count_of_bits = len(bits)

    def do_configure(self, config: DoConfig | dict | None) -> None:
        # Keep the cached value as the last confirmed hardware config until
        # the backend accepts this requested replacement.
        new_config = coerce_do_config(config)
        handle = self.open_and_use_first_device()
        if handle is None:
            raise AD2SdkError("do_configure() called while AD2 is disabled -- caller must check ad2.enabled first.")
        self.get_backend().configure_do(handle, new_config)
        self.do_config = new_config

    def do_reset(self) -> None:
        handle = self.open_and_use_first_device()
        if handle is None:
            raise AD2SdkError("do_reset() called while AD2 is disabled -- caller must check ad2.enabled first.")
        self.get_backend().reset_do(handle)
        self.do_config = DoConfig()

    def start_stop_do(self, running: bool) -> None:
        # Keep the cached value as the last confirmed hardware configuration
        # until the backend accepts the requested start/stop transition.
        new_config = deepcopy(self.get_do_config())
        new_config.running = running
        handle = self.open_and_use_first_device()
        if handle is None:
            raise AD2SdkError(
                "start_stop_do() called while AD2 is disabled -- caller must check ad2.enabled first."
            )
        self.get_backend().configure_do(handle, new_config)
        self.do_config = new_config

    def mso_init(self, phdwf: object | int | None = None) -> None:
        if phdwf is None:
            phdwf = self.open_and_use_first_device()
        self.mso_config = MsoConfig(device_handle=phdwf)

    def capture_scope(
        self,
        *,
        channel_index: int = 0,
        sample_frequency_hz: float = 10_000.0,
        sample_count: int = 4096,
        range_v: float = 1.0,
        offset_v: float = 0.0,
    ) -> list[float]:
        # AD2 SDK review: this previously returned []
        # silently when AD2 was disabled -- indistinguishable from a real
        # capture that genuinely returned zero samples. The real UI caller
        # (qt_ui.py's MSO tab, via capture_scope_channels()) already runs
        # through _run_action()/ActionWorker, which surfaces this cleanly as
        # a status message, not a crash (confirmed against the identical
        # pattern used by config_wfg()/pc_trigger() earlier).
        handle = self.open_and_use_first_device()
        if handle is None:
            raise AD2SdkError("capture_scope() called while AD2 is disabled -- caller must check ad2.enabled first.")
        self.mso_config = MsoConfig(
            device_handle=handle,
            range_ch1=range_v if channel_index == 0 else None,
            range_ch2=range_v if channel_index == 1 else None,
            sample_frequency_hz=sample_frequency_hz,
            sample_count=sample_count,
        )
        return self.get_backend().capture_analog_in(
            handle,
            channel_index=channel_index,
            sample_frequency_hz=sample_frequency_hz,
            sample_count=sample_count,
            range_v=range_v,
            offset_v=offset_v,
        )

    def capture_scope_channels(
        self,
        *,
        channel_indices: list[int],
        sample_frequency_hz: float = 10_000.0,
        sample_count: int = 4096,
        range_v: float = 1.0,
        offset_v: float = 0.0,
        trigger_source: TriggerSource | str = TriggerSource.NONE,
    ) -> dict[int, list[float]]:
        handle = self.open_and_use_first_device()
        if handle is None:
            raise AD2SdkError(
                "capture_scope_channels() called while AD2 is disabled -- caller must check ad2.enabled first."
            )
        self.mso_config = MsoConfig(
            device_handle=handle,
            range_ch1=range_v if 0 in channel_indices else None,
            range_ch2=range_v if 1 in channel_indices else None,
            sample_frequency_hz=sample_frequency_hz,
            sample_count=sample_count,
            trigger_source=trigger_source,
        )
        return self.get_backend().capture_analog_in_channels(
            handle,
            channel_indices=channel_indices,
            sample_frequency_hz=sample_frequency_hz,
            sample_count=sample_count,
            range_v=range_v,
            offset_v=offset_v,
            trigger_source=trigger_source,
        )

    def get_mso_config(self) -> MsoConfig:
        if self.mso_config is None:
            self.mso_init()
        assert self.mso_config is not None
        return self.mso_config


@dataclass(slots=True)
class SimulatedAD2Sdk(AD2Sdk):
    device_handle: object | None = None

    def get_backend(self) -> WaveFormsBackend:
        raise RuntimeError("SimulatedAD2Sdk does not use the WaveForms hardware backend.")

    def cleanup(self) -> None:
        self.device_handle = None
        self.triggered = False

    def open_and_use_first_device(self) -> object | None:
        if not self.enabled:
            self.device_handle = None
        elif self.device_handle is None:
            self.device_handle = object()
        return self.device_handle

    def pc_trigger(self) -> None:
        self.triggered = True

    def config_wfg(self, config: WfgConfig | dict | None) -> None:
        self._set_effective_wfg_config(config)

    def _set_effective_wfg_config(self, config: WfgConfig | dict | None) -> None:
        self.set_wfg_config(config)
        for channel in self.get_wfg_config().channels:
            channel.effective_carrier = deepcopy(channel.carrier)
            channel.effective_fm_mod = deepcopy(channel.fm_mod) if channel.fm_mod.enable else None

    def wfg_configure(self, config: WfgConfig | dict | None) -> None:
        self._set_effective_wfg_config(config)

    def wfg_start_stop_all_ch(self, running: bool) -> None:
        self.get_wfg_config().running = running

    def config_do_custom(self, config: DoConfig | dict | None) -> None:
        self.do_custom_config = coerce_do_config(config)
        self.do_config = self.do_custom_config

    def config_do_clock_special(self, settings: DoConfig | dict | None) -> None:
        self.do_clock_settings = coerce_do_config(settings)
        self.do_config = self.do_clock_settings

    def do_configure(self, config: DoConfig | dict | None) -> None:
        self.do_config = coerce_do_config(config)

    def do_reset(self) -> None:
        self.do_config = DoConfig()

    def start_stop_do(self, running: bool) -> None:
        self.get_do_config().running = running

    def capture_scope(
        self,
        *,
        channel_index: int = 0,
        sample_frequency_hz: float = 10_000.0,
        sample_count: int = 4096,
        range_v: float = 1.0,
        offset_v: float = 0.0,
    ) -> list[float]:
        _ = channel_index
        _ = sample_frequency_hz
        _ = sample_count
        _ = range_v
        _ = offset_v
        count = max(int(sample_count), 1)
        frequency_hz = 100.0 if channel_index == 0 else 250.0
        amplitude = min(max(range_v / 4.0, 0.05), range_v)
        return [
            offset_v + amplitude * math.sin(2.0 * math.pi * frequency_hz * index / sample_frequency_hz)
            for index in range(count)
        ]

    def capture_scope_channels(
        self,
        *,
        channel_indices: list[int],
        sample_frequency_hz: float = 10_000.0,
        sample_count: int = 4096,
        range_v: float = 1.0,
        offset_v: float = 0.0,
        trigger_source: TriggerSource | str = TriggerSource.NONE,
    ) -> dict[int, list[float]]:
        _ = trigger_source
        return {
            index: self.capture_scope(
                channel_index=index,
                sample_frequency_hz=sample_frequency_hz,
                sample_count=sample_count,
                range_v=range_v,
                offset_v=offset_v,
            )
            for index in channel_indices
        }
