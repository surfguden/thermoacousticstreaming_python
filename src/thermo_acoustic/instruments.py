from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import logging
import math
from pathlib import Path
import time
from typing import Protocol

from .ad2 import (
    DoConfig,
    DoSingleChannelConfig,
    MsoConfig,
    TriggerSource,
    WfgChannelConfig,
    WfgConfig,
    coerce_do_config,
    coerce_wfg_config,
)
from .camera import SubRegion, SubRegionLimits
from .hw_logging import log_call
from .thorlabs_piezo import PiezoStage
from .waveforms import WaveFormsBackend

logger = logging.getLogger(__name__)


class Instrument(Protocol):
    def initialize(self) -> None: ...

    def cleanup(self) -> None: ...


class TextCommandBackend(Protocol):
    def write(self, command: str) -> None: ...

    def query(self, command: str) -> str: ...

    def close(self) -> None: ...


@dataclass(slots=True)
class SerialTextCommandBackend:
    baud_rate: int = 19200
    timeout_s: float = 1.0
    write_timeout_s: float = 5.0
    line_ending: str = "\r"
    port: object | None = None
    # Which device this instance's transactions get tagged as in the shared
    # hw_logging log (e.g. "valve") -- set by the caller that constructs this
    # backend, since the backend itself is generic and has no device identity
    # of its own. Left at the generic default only if a caller forgets to set it.
    device_name: str = "serial"

    def _open(self, resource: str) -> None:
        if self.port is not None:
            return
        with log_call(self.device_name, "connect", command=resource) as result:
            try:
                import serial
            except ImportError as exc:  # pragma: no cover - depends on optional runtime package
                raise RuntimeError("pyserial is required for real serial hardware. Install with: python -m pip install pyserial") from exc
            self.port = serial.Serial(
                resource,
                baudrate=self.baud_rate,
                timeout=self.timeout_s,
                write_timeout=self.write_timeout_s,
            )
            result["response"] = "connected"

    def _send(self, command: str) -> None:
        text = command.strip()
        if text.upper().startswith("OPEN "):
            self._open(text.split(maxsplit=1)[1])
            return
        if self.port is None:
            raise RuntimeError("Serial port is not open.")
        self.port.write((command + self.line_ending).encode("ascii"))

    def write(self, command: str) -> None:
        if command.strip().upper().startswith("OPEN "):
            # _send() -> _open() already logs this as its own "connect"
            # transaction -- avoid a redundant second "write" line for the
            # same pseudo-command.
            self._send(command)
            return
        with log_call(self.device_name, "write", command=command) as result:
            self._send(command)
            result["response"] = "sent"

    def query(self, command: str) -> str:
        with log_call(self.device_name, "query", command=command) as result:
            self._send(command)
            if self.port is None:
                raise RuntimeError("Serial port is not open.")
            # readline() splits on b"\n", but this backend's own devices are
            # only ever confirmed to terminate responses with line_ending
            # ("\r" by default -- see write() above). Real-hardware timing
            # characterization (Session 54) showed every query() call blocking
            # for the entire configured timeout_s before returning, regardless
            # of how quickly the device actually responded -- the signature of
            # readline() never finding the "\n" it was looking for. Reading
            # until the same terminator this backend writes with fixes that.
            terminator = self.line_ending.encode("ascii")
            response = self.port.read_until(expected=terminator).decode("ascii", errors="replace")
            result["response"] = response
        return response

    def close(self) -> None:
        with log_call(self.device_name, "close") as result:
            # M1 (instruments.py line-by-line review): self.port must be
            # reset to None even if port.close() itself raises -- otherwise
            # a future _open() sees self.port is not None and skips
            # reopening entirely, permanently reusing the broken handle,
            # and a future close() tries to close the same broken handle
            # again. The exception itself still propagates (log_call()
            # logs and re-raises), this only guarantees the reset happens
            # first.
            try:
                if self.port is not None:
                    self.port.close()
            finally:
                self.port = None
            result["response"] = "closed"


class PumpBackend(Protocol):
    def initialize(self, configuration_path: Path) -> None: ...

    def refill(self, flow_rate: float | None = None) -> None: ...

    def empty(self, flow_rate: float | None = None) -> None: ...

    def stop(self) -> None: ...

    def generate_flow(self, flow_rate: float) -> None: ...

    def set_fill_level(self, fill_level: float, flow_rate: float | None = None) -> None: ...

    def read_fill_level(self) -> float: ...

    def configure_syringe(self, config: dict | None) -> None: ...

    def configure_flow_unit(self, unit: str | None) -> None: ...

    def reference_move(self) -> None: ...

    def read_status(self) -> bool: ...

    def close(self) -> None: ...


class CameraBackend(Protocol):
    def open_camera(self) -> object: ...

    def configure_exposure_time(self, exposure_ms: float) -> float: ...

    def configure_roi(self, roi: SubRegion | dict | None) -> None: ...

    def configure_snapshot(self, settings: dict | None = None) -> None: ...

    def configure_sequence(self, settings: dict | None) -> None: ...

    def configure_trigger_global_exposure(self, enabled: bool) -> None: ...

    def start_capture(self) -> None: ...

    def stop_capture(self) -> None: ...

    def capture_snapshot(self) -> object: ...

    def image_sequence(self, frame_count: int = 0, partial_capture_folder: Path | None = None) -> list[object]: ...

    def read_frame_timestamps(self) -> list[str]: ...

    def save_sequence(self, image_data: object, folder: Path) -> None: ...

    def get_camera_buffer_size(self) -> int: ...

    def read_subregion_limits_and_value(self) -> tuple[SubRegionLimits, SubRegion | dict]: ...

    def update_roi_limits(self, limits: SubRegionLimits | None = None) -> SubRegionLimits: ...

    def read_readout_time(self) -> float | None: ...

    def sw_trigger(self) -> None: ...

    def close(self) -> None: ...


@dataclass(slots=True)
class RegloPumpControl:
    running: bool = False
    direction: str = "clockwise"
    speed: float = 0.0
    volume_ml: float | None = None


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
        if self.device_handle is not None:
            self.get_backend().close(self.device_handle)
        self.device_handle = None
        self.triggered = False

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
        # M3 (instruments.py line-by-line review): same fix as config_wfg()
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
        # M3 (instruments.py line-by-line review): previously returned []
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
        self.set_wfg_config(config)

    def wfg_configure(self, config: WfgConfig | dict | None) -> None:
        self.set_wfg_config(config)

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


@dataclass(slots=True)
class HamamatsuCamera:
    enabled: bool = True
    simulate: bool = True
    backend: CameraBackend | None = None
    exposure_ms: float = 1.0
    capturing: bool = False
    sequence_config: dict | None = None
    roi: SubRegion | dict | None = None
    roi_limits: SubRegionLimits = field(default_factory=SubRegionLimits)
    handle: object | None = None

    def initialize(self) -> None:
        if self.enabled:
            self.open_camera()

    def open_camera(self) -> object | None:
        if not self.enabled:
            self.handle = None
        elif self.backend is not None:
            self.handle = self.backend.open_camera()
        elif self.handle is None:
            self.handle = object()
        return self.handle

    def get_handle_out(self) -> object | None:
        return self.handle

    def configure(self, exposure_ms: float | None = None) -> None:
        if exposure_ms is not None:
            self.exposure_ms = exposure_ms

    def configure_exposure_time(self, exposure_ms: float) -> float:
        # Finding E: when a real backend is attached, self.exposure_ms now
        # tracks what the device actually applied (which can differ slightly
        # from the request due to DCAM's own exposure quantization), not the
        # raw request -- _check_camera_timing_budget() (application.py)
        # already reads this attribute, so it benefits from the more accurate
        # value with no changes needed there. Simulated/no-backend case has no
        # real device to read back from, so the requested value is used as-is,
        # same as before.
        if self.backend is not None:
            self.exposure_ms = self.backend.configure_exposure_time(exposure_ms)
        else:
            self.exposure_ms = exposure_ms
        return self.exposure_ms

    def configure_roi(self, roi: SubRegion | dict | None) -> None:
        if self.backend is not None:
            self.backend.configure_roi(roi)
        self.roi = roi

    def configure_snapshot(self, settings: dict | None = None) -> None:
        if self.backend is not None:
            self.backend.configure_snapshot(settings)

    def configure_sequence(self, settings: dict | None) -> None:
        if self.backend is not None:
            self.backend.configure_sequence(settings)
        self.sequence_config = settings

    def configure_trigger_global_exposure(self, enabled: bool) -> None:
        if self.backend is not None:
            self.backend.configure_trigger_global_exposure(enabled)

    def start_capture(self) -> None:
        if self.backend is not None:
            self.backend.start_capture()
        self.capturing = True

    def stop_capture(self) -> None:
        if self.backend is not None:
            self.backend.stop_capture()
        self.capturing = False

    def image_sequence(self, frame_count: int = 0, partial_capture_folder: Path | None = None) -> list[object]:
        if self.backend is not None:
            return self.backend.image_sequence(frame_count, partial_capture_folder)
        count = max(frame_count, 0)
        return [object() for _ in range(count)]

    def read_frame_timestamps(self) -> list[str]:
        if self.backend is not None:
            return self.backend.read_frame_timestamps()
        return []

    def capture_snapshot(self) -> object:
        if self.backend is not None:
            return self.backend.capture_snapshot()
        return object()

    def center_roi(self) -> None:
        if isinstance(self.roi, SubRegion):
            centered: SubRegion | dict = self.roi.centered(self.roi_limits)
        elif self.roi is None:
            centered = {"centered": True}
        else:
            centered = dict(self.roi)
            centered["centered"] = True
        self.configure_roi(centered)

    def save_sequence(self, image_data: object, folder: Path) -> None:
        if self.backend is not None:
            self.backend.save_sequence(image_data, folder)
            return
        folder.mkdir(parents=True, exist_ok=True)

    def get_camera_buffer_size(self) -> int:
        if self.backend is not None:
            return self.backend.get_camera_buffer_size()
        return 0

    def get_sub_region(self) -> SubRegion | dict:
        return self.roi or {}

    def read_subregion_limits_and_value(self) -> tuple[SubRegionLimits, SubRegion | dict]:
        if self.backend is not None:
            limits, roi = self.backend.read_subregion_limits_and_value()
            self.roi_limits = limits
            self.roi = roi
            return limits, roi
        return self.roi_limits, self.get_sub_region()

    def update_roi_limits(self, limits: SubRegionLimits | None = None) -> SubRegionLimits:
        if self.backend is not None:
            self.roi_limits = self.backend.update_roi_limits(limits)
            return self.roi_limits
        if limits is not None:
            self.roi_limits = limits
        return self.roi_limits

    def read_readout_time(self) -> float | None:
        if self.backend is not None:
            return self.backend.read_readout_time()
        return 0.0

    def sw_trigg(self) -> None:
        if self.backend is not None:
            self.backend.sw_trigger()

    def cleanup(self) -> None:
        errors: list[str] = []
        try:
            self.stop_capture()
        except Exception as exc:
            errors.append(f"stop capture failed: {exc}")

        backend_closed = self.backend is None
        if self.backend is not None:
            try:
                self.backend.close()
                backend_closed = True
            except Exception as exc:
                errors.append(f"close failed: {exc}")

        if backend_closed:
            self.handle = None
            self.capturing = False
        if errors:
            raise RuntimeError("Hamamatsu camera cleanup failed: " + "; ".join(errors))


@dataclass(slots=True)
class CetoniPump:
    enabled: bool = True
    simulate: bool = True
    backend: PumpBackend | None = None
    configuration_path: Path = Path(r"C:\Users\Public\Documents\QmixElements\Projects")
    fill_level: float = 0.0
    dosing: bool = False
    syringe_config: dict | None = None
    flow_unit: str | None = None
    referenced: bool = False
    # Set True once initialize() completes (mirrors Valve/QmixPumpBackend's
    # own "initialized" flags) -- distinct from `referenced`, which now only
    # means "a physical reference move was confirmed". qt_ui_v2.py's pump
    # connection-status row uses this, not `referenced`, matching the same
    # pattern the Valve row already uses (`valve.initialized`).
    initialized: bool = False
    # Used by refill() when simulating (backend=None) to fill to the
    # syringe's actual configured capacity instead of an arbitrary
    # hardcoded value. Defaults to 1.0 for backward compatibility with
    # existing simulated-mode callers that never set this explicitly --
    # not a claim that 1.0 mL is a realistic syringe capacity.
    max_volume_ml: float = 1.0

    def sync_fill_level(self) -> None:
        # Re-read the real fill level from hardware and update self.fill_level
        # to match -- the single canonical place this project's own repeated
        # "self.fill_level = self.backend.read_fill_level()" pattern (Session
        # 56/57, and Session 63's flush-timeout fix below) should live, so it
        # can't drift between call sites. No-op when simulated (backend is
        # None) -- there is no real device to read back from; the simulated/
        # bookkeeping value is already authoritative in that case.
        if self.backend is not None:
            self.fill_level = self.backend.read_fill_level()

    def initialize(self) -> None:
        if not self.enabled:
            return
        backend_initialized = False
        if self.backend is not None:
            try:
                self.backend.initialize(self.configuration_path)
                backend_initialized = True
                # A successful backend open is not a complete pump initialize
                # until the real fill-level readback also succeeds.
                self.sync_fill_level()
            except Exception as exc:
                self.initialized = False
                if not backend_initialized:
                    # QmixPumpBackend.initialize() owns rollback of failures
                    # raised inside its own open/start/enable sequence.
                    raise
                try:
                    self.backend.close()
                except Exception as cleanup_exc:
                    raise RuntimeError(
                        f"Pump initialize failed after backend open: {exc}; "
                        f"cleanup after failed initialize also failed: {cleanup_exc}"
                    ) from exc
                raise
        self.initialized = True
        # Deliberately not setting self.referenced here -- initialize() never
        # calls calibrate()/reference_move(), so it has no basis to claim a
        # physical reference move happened. Real pumps with an incremental
        # encoder (e.g. this project's Nemesys Low Pressure Pump) report
        # is_position_sensing_initialized()=False until reference_move()
        # actually runs and completes; only reference_move() itself should
        # set referenced=True, and only after confirming success (it already
        # does, via QmixPumpBackend.reference_move()'s poll-until-confirmed
        # or raise).

    def clear_fault_and_reinitialize(self) -> None:
        # Normal initialization now performs the owner-approved automatic
        # fault clear. This explicit operator-only path remains for a fault
        # observed after initialization or an operator-requested fresh
        # reconnect. It mirrors initialize()'s backend-open/rollback shape so
        # its traceable manual-recovery semantics remain separate.
        if not self.enabled:
            return
        if self.backend is None:
            # Simulated pump: there is no real fault state to clear, so this
            # is equivalent to a normal (re)initialize.
            self.initialize()
            return
        clear_fault_and_reinitialize = getattr(self.backend, "clear_fault_and_reinitialize", None)
        if not callable(clear_fault_and_reinitialize):
            raise RuntimeError("This pump backend does not support an explicit fault-clear action.")
        backend_initialized = False
        try:
            clear_fault_and_reinitialize(self.configuration_path)
            backend_initialized = True
            self.sync_fill_level()
        except Exception as exc:
            self.initialized = False
            if not backend_initialized:
                # QmixPumpBackend.clear_fault_and_reinitialize() owns rollback
                # of failures raised inside its own open/start/clear/enable
                # sequence.
                raise
            try:
                self.backend.close()
            except Exception as cleanup_exc:
                raise RuntimeError(
                    f"Pump clear_fault_and_reinitialize failed after backend open: {exc}; "
                    f"cleanup after failed clear_fault_and_reinitialize also failed: {cleanup_exc}"
                ) from exc
            raise
        self.initialized = True

    def refill(self, flow_rate: float | None = None) -> None:
        if self.backend is not None:
            self.backend.refill(flow_rate)
            # Same fix as initialize() above, same reason: the real
            # backend's own refill() fills the physical syringe to its
            # true max_volume_ml (see QmixPumpBackend.refill()), which is
            # essentially never exactly 1.0 mL -- the old hardcoded
            # self.fill_level = 1.0 here desynced the Python-side value
            # from real hardware state immediately after every refill(),
            # for any syringe other than a 1 mL one (audit finding 5a).
            self.sync_fill_level()
        else:
            self.fill_level = self.max_volume_ml

    def empty(self, flow_rate: float | None = None) -> None:
        if self.backend is not None:
            self.backend.empty(flow_rate)
        self.fill_level = 0.0

    def stop(self) -> None:
        if self.backend is not None:
            self.backend.stop()
        self.dosing = False

    def generate_flow(self, flow_rate: float) -> None:
        if self.backend is not None:
            self.backend.generate_flow(flow_rate)
        self.dosing = True
        if self.simulate:
            self.dosing = False

    def set_fill_level(self, fill_level: float, flow_rate: float | None = None) -> None:
        if self.backend is not None:
            self.backend.set_fill_level(fill_level, flow_rate)
        self.fill_level = fill_level

    def configure_syringe(self, config: dict | None) -> None:
        if self.backend is not None:
            self.backend.configure_syringe(config)
        self.syringe_config = config

    def configure_syringe_bd(self, config: dict | None) -> None:
        self.configure_syringe(config)

    def configure_flow_unit(self, unit: str | None) -> None:
        if self.backend is not None:
            self.backend.configure_flow_unit(unit)
        self.flow_unit = unit

    def reference_move(self) -> None:
        if self.backend is not None:
            self.backend.reference_move()
        self.referenced = True

    def read_status(self) -> bool:
        if self.backend is not None:
            self.dosing = self.backend.read_status()
        return self.dosing

    def cleanup(self) -> None:
        self.stop()
        if self.backend is not None:
            self.backend.close()
        # H2 (instruments.py line-by-line review): previously never reset,
        # so the pump connection-status UI (wired to this flag) would keep
        # showing "Connected" after a real cleanup/disconnect -- matches the
        # pattern Valve.cleanup() already gets right.
        self.initialized = False


class ValveError(RuntimeError):
    pass


@dataclass(slots=True)
class Valve:
    enabled: bool = True
    simulate: bool = True
    # Real-hardware-confirmed default (a real-hardware verification session,
    # re-confirmed by a prior session too, not a one-off): the valve responds
    # correctly to the documented "S" status-query protocol on COM5, not the
    # previously-documented COM6 -- COM6 was a standing documentation error,
    # not a transient port reassignment. LabVIEW screenshot evidence
    # (docs/labview_migration_completeness_audit.md) already hinted COM5 was
    # the real candidate; this was never independently verified until now.
    visa_resource: str = "COM5"
    backend: TextCommandBackend | None = None
    # Protocol-confirmed numeric positions. The physical fluidic routing of
    # P01/P02 remains a bench-confirmation item; do not infer Open/Closed
    # semantics from the serial position token alone.
    command_position_1: str = "P01"
    command_position_2: str = "P02"
    status_query_command: str = "S"
    position: int = 1
    initialized: bool = False
    status_note: str = ""

    def initialize(self) -> None:
        self.status_note = ""
        if self.backend is not None:
            try:
                self.backend.write(f"OPEN {self.visa_resource}")
                raw_response = self.backend.query(self.status_query_command)
                if not self._apply_status_response(raw_response):
                    raise ValveError(
                        f"Valve returned unrecognized status on {self.visa_resource}: {self.status_note}"
                    )
            except Exception as exc:
                self.initialized = False
                try:
                    self.backend.close()
                except Exception as cleanup_exc:
                    raise ValveError(
                        f"Valve initialize failed on {self.visa_resource}: {exc}; "
                        f"cleanup after failed initialize also failed: {cleanup_exc}"
                    ) from exc
                raise
        self.initialized = True

    def _apply_status_response(self, raw_response: str) -> bool:
        # Protocol confirmed against IDEX MX Series II driver docs (via the
        # linnarsson-lab/MXII-valve reference driver): "S\r" queries status.
        # Zero bytes back within the read timeout means nothing is on the
        # other end of the port -- that is the real disconnect signal, so it
        # must be checked before any stripping collapses it into a lone "\r".
        if raw_response == "":
            raise ValveError(f"Valve did not respond on {self.visa_resource}")
        text = raw_response.strip()
        if text in ("*", "**"):
            self.status_note = "busy"
            return True
        # The MX status reply is an explicit position token, not arbitrary
        # chatter containing a digit. In particular, do not treat strings
        # such as ``device=1`` or ``foo2bar`` as a confirmed valve position.
        # ``01``/``02`` are the observed protocol replies; the other exact
        # forms keep compatibility with existing simulated/echo responses.
        position_responses = {
            "1": 1,
            "01": 1,
            "P01": 1,
            "2": 2,
            "02": 2,
            "P02": 2,
        }
        if text in position_responses:
            self.position = position_responses[text]
            self.status_note = "confirmed"
            return True
        self.status_note = f"unverified position response: {text!r}"
        return False

    def _ensure_connected(self) -> None:
        # Lazy reconnect (2026-08-13 architecture fix), matching the pattern
        # already proven for AD2Sdk.open_and_use_first_device()/
        # HamamatsuDcamBackend.open_camera(): a manual Pump&Valve-tab action
        # must not require a prior, successful, whole-system
        # Application.initialize() -- e.g. this Valve was skipped because an
        # earlier device in the reporting order failed under the old
        # cross-device-abort design (see docs/hardware_repair_plan.md), or
        # was simply never initialized this session for any other reason.
        # Deliberately calls initialize() itself rather than a shortcut
        # "just open the port" duplicate: unlike AD2/Camera's lazy-open,
        # Valve.initialize() is not just a handle open, it also runs the
        # real "S" status handshake/validation (_apply_status_response()) --
        # skipping that here would silently accept an unconfirmed connection
        # on the fluid-routing-critical path. No-op when already initialized
        # or simulated (backend is None).
        if self.backend is not None and not self.initialized:
            self.initialize()

    def set_position(self, position: int) -> None:
        # Position numbers map directly to the protocol tokens P01/P02. Their
        # physical routing is intentionally not inferred here.
        if position not in (1, 2):
            raise ValueError(f"Unsupported valve position: {position}")
        self._ensure_connected()
        # M2 (instruments.py line-by-line review): self.position is now only
        # assigned after backend.write() returns without raising -- assigning
        # it first (the old order) meant a raised exception from write() left
        # self.position claiming a move that was never actually sent.
        if self.backend is not None:
            command = self.command_position_1 if position == 1 else self.command_position_2
            self.backend.write(command)
        self.position = position
        if self.backend is not None:
            # A successful serial write confirms only that the command was
            # accepted by the host serial API. Do not carry a previous
            # position's "confirmed" status across this new request; the next
            # S-query/readback must confirm the requested protocol position.
            command = self.command_position_1 if position == 1 else self.command_position_2
            self.status_note = f"requested {command}; confirmation pending"

    def wait_until_ready(self, timeout_s: float = 1.0, poll_interval_s: float = 0.05) -> bool:
        # Bounded poll of the same "S\r" handshake used at initialize() time,
        # so a real mechanical-transition confirmation replaces a fixed sleep
        # after set_position(). A real disconnect (empty response) still
        # raises ValveError immediately via _apply_status_response -- only a
        # "still busy" result is tolerated up to the timeout, at which point
        # this returns False. Hardware workflows must treat that as an
        # unconfirmed position and stop their next actuator command.
        if self.backend is None:
            return True
        deadline = time.monotonic() + max(timeout_s, 0.0)
        while True:
            raw_response = self.backend.query(self.status_query_command)
            self._apply_status_response(raw_response)
            if self.status_note in ("ready", "confirmed"):
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(max(poll_interval_s, 0.0))

    def cleanup(self) -> None:
        if self.backend is not None:
            self.backend.close()
        self.initialized = False
        self.status_note = ""


@dataclass(slots=True)
class ZStage:
    """Initialize-dialog-facing wrapper around the real Thorlabs piezo
    Z-stage (thorlabs_piezo.PiezoStage), matching the same enabled/
    initialize()/cleanup() shape every other HardwareBundle member already
    uses (HamamatsuCamera/CetoniPump/Valve each wrap a real SDK backend the
    same way) -- so the Initialize dialog's uniform per-instrument loop can
    treat the Z-stage like every other device. Reuses PiezoStage's own real
    connect()/disconnect() untouched; does not create a second, divergent
    connection path.

    Replaces the legacy PriorZMotor/COM7 path (pending_feedback.md item 4):
    PriorZMotor pointed the Initialize dialog's "Z-stage" checkbox at a
    serial port ('COM7') that never existed on this lab's hardware and was
    never actually the real piezo -- confirmed via real-hardware
    investigation, not assumed. z_stack()/go_to_abs_pos() (the only other
    PriorZMotor-specific API) had zero real callers anywhere in the live
    UI/experiment path (confirmed via a repo-wide search), so nothing else
    depended on that class either.
    """

    enabled: bool = False
    stage: PiezoStage = field(default_factory=PiezoStage)
    status_note: str = ""

    def initialize(self) -> None:
        self.status_note = ""
        if not self.enabled:
            return
        self.stage.connect()
        self.status_note = (
            f"serial={self.stage.serial_number}, max_travel_um={self.stage.max_travel_um}, "
            f"mode={self.stage.position_control_mode}"
        )

    def cleanup(self) -> None:
        if self.stage.connected:
            self.stage.disconnect()
        self.status_note = ""
