from __future__ import annotations

from dataclasses import dataclass, field
import math
from pathlib import Path
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
from .waveforms import WaveFormsBackend


class Instrument(Protocol):
    def initialize(self) -> None: ...

    def cleanup(self) -> None: ...


class TextCommandBackend(Protocol):
    def write(self, command: str) -> None: ...

    def query(self, command: str) -> str: ...

    def close(self) -> None: ...


@dataclass(slots=True)
class SerialTextCommandBackend:
    baud_rate: int = 9600
    timeout_s: float = 1.0
    line_ending: str = "\r\n"
    port: object | None = None

    def _open(self, resource: str) -> None:
        if self.port is not None:
            return
        try:
            import serial
        except ImportError as exc:  # pragma: no cover - depends on optional runtime package
            raise RuntimeError("pyserial is required for real serial hardware. Install with: python -m pip install pyserial") from exc
        self.port = serial.Serial(resource, baudrate=self.baud_rate, timeout=self.timeout_s)

    def write(self, command: str) -> None:
        text = command.strip()
        if text.upper().startswith("OPEN "):
            self._open(text.split(maxsplit=1)[1])
            return
        if self.port is None:
            raise RuntimeError("Serial port is not open.")
        self.port.write((command + self.line_ending).encode("ascii"))

    def query(self, command: str) -> str:
        self.write(command)
        if self.port is None:
            raise RuntimeError("Serial port is not open.")
        return self.port.readline().decode("ascii", errors="replace")

    def close(self) -> None:
        if self.port is not None:
            self.port.close()
        self.port = None


class PumpBackend(Protocol):
    def initialize(self, configuration_path: Path) -> None: ...

    def refill(self) -> None: ...

    def empty(self) -> None: ...

    def stop(self) -> None: ...

    def generate_flow(self, flow_rate: float) -> None: ...

    def set_fill_level(self, fill_level: float) -> None: ...

    def configure_syringe(self, config: dict | None) -> None: ...

    def configure_flow_unit(self, unit: str | None) -> None: ...

    def reference_move(self) -> None: ...

    def read_status(self) -> bool: ...

    def close(self) -> None: ...


class CameraBackend(Protocol):
    def open_camera(self) -> object: ...

    def configure_exposure_time(self, exposure_ms: float) -> None: ...

    def configure_roi(self, roi: SubRegion | dict | None) -> None: ...

    def configure_snapshot(self, settings: dict | None = None) -> None: ...

    def configure_sequence(self, settings: dict | None) -> None: ...

    def start_capture(self) -> None: ...

    def stop_capture(self) -> None: ...

    def capture_snapshot(self) -> object: ...

    def image_sequence(self, frame_count: int = 0) -> list[object]: ...

    def save_sequence(self, image_data: object, folder: Path) -> None: ...

    def get_camera_buffer_size(self) -> int: ...

    def read_subregion_limits_and_value(self) -> tuple[SubRegionLimits, SubRegion | dict]: ...

    def update_roi_limits(self, limits: SubRegionLimits | None = None) -> SubRegionLimits: ...

    def read_readout_time(self) -> float: ...

    def sw_trigger(self) -> None: ...

    def close(self) -> None: ...


@dataclass(slots=True)
class RegloPumpControl:
    running: bool = False
    direction: str = "clockwise"
    speed: float = 0.0
    volume_ml: float | None = None


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
        handle = self.open_and_use_first_device()
        if handle is not None:
            self.get_backend().trigger_pc(handle)
        self.triggered = True

    def get_wfg_config(self) -> WfgConfig:
        if self.wfg_config is None:
            self.wfg_config = WfgConfig()
        return self.wfg_config

    def set_wfg_config(self, config: WfgConfig | dict | None) -> None:
        self.wfg_config = coerce_wfg_config(config)

    def config_wfg(self, config: WfgConfig | dict | None) -> None:
        self.set_wfg_config(config)
        handle = self.open_and_use_first_device()
        if handle is not None:
            self.get_backend().configure_wfg(handle, self.get_wfg_config())

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
        self.set_wfg_config(config)
        handle = self.open_and_use_first_device()
        if handle is not None:
            self.get_backend().configure_wfg(handle, self.get_wfg_config())

    def wfg_configure_read_back(self) -> WfgConfig:
        return self.get_wfg_config()

    def wfg_start_stop_all_ch(self, running: bool) -> None:
        self.get_wfg_config().running = running
        handle = self.open_and_use_first_device()
        if handle is not None:
            self.get_backend().configure_wfg(handle, self.get_wfg_config())

    def get_do_config(self) -> DoConfig:
        if self.do_config is None:
            self.do_config = DoConfig()
        return self.do_config

    def config_do_custom(self, config: DoConfig | dict | None) -> None:
        self.do_custom_config = coerce_do_config(config)
        self.do_config = self.do_custom_config
        handle = self.open_and_use_first_device()
        if handle is not None:
            self.get_backend().configure_do(handle, self.get_do_config())

    def config_do_clock_special(self, settings: DoConfig | dict | None) -> None:
        self.do_clock_settings = coerce_do_config(settings)
        self.do_config = self.do_clock_settings
        handle = self.open_and_use_first_device()
        if handle is not None:
            self.get_backend().configure_do(handle, self.get_do_config())

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
        self.do_config = coerce_do_config(config)
        handle = self.open_and_use_first_device()
        if handle is not None:
            self.get_backend().configure_do(handle, self.get_do_config())

    def do_reset(self) -> None:
        handle = self.open_and_use_first_device()
        if handle is not None:
            self.get_backend().reset_do(handle)
        self.do_config = DoConfig()

    def start_stop_do(self, running: bool) -> None:
        self.get_do_config().running = running
        handle = self.open_and_use_first_device()
        if handle is not None:
            self.get_backend().configure_do(handle, self.get_do_config())

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
        handle = self.open_and_use_first_device()
        if handle is None:
            return []
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
            return {}
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

    def configure_exposure_time(self, exposure_ms: float) -> None:
        if self.backend is not None:
            self.backend.configure_exposure_time(exposure_ms)
        self.exposure_ms = exposure_ms

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

    def start_capture(self) -> None:
        if self.backend is not None:
            self.backend.start_capture()
        self.capturing = True

    def stop_capture(self) -> None:
        if self.backend is not None:
            self.backend.stop_capture()
        self.capturing = False

    def image_sequence(self, frame_count: int = 0) -> list[object]:
        if self.backend is not None:
            return self.backend.image_sequence(frame_count)
        count = max(frame_count, 0)
        return [object() for _ in range(count)]

    def capture_snapshot(self) -> object:
        if self.backend is not None:
            return self.backend.capture_snapshot()
        return object()

    def center_roi(self) -> None:
        if isinstance(self.roi, SubRegion):
            self.roi = self.roi.centered(self.roi_limits)
        elif self.roi is None:
            self.roi = {"centered": True}
        else:
            self.roi["centered"] = True

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

    def read_readout_time(self) -> float:
        if self.backend is not None:
            return self.backend.read_readout_time()
        return 0.0

    def sw_trigg(self) -> None:
        if self.backend is not None:
            self.backend.sw_trigger()

    def cleanup(self) -> None:
        self.stop_capture()
        if self.backend is not None:
            self.backend.close()
        self.handle = None


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

    def initialize(self) -> None:
        if not self.enabled:
            return
        if self.backend is not None:
            self.backend.initialize(self.configuration_path)
        self.referenced = True

    def refill(self) -> None:
        if self.backend is not None:
            self.backend.refill()
        self.fill_level = 1.0

    def empty(self) -> None:
        if self.backend is not None:
            self.backend.empty()
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

    def set_fill_level(self, fill_level: float) -> None:
        if self.backend is not None:
            self.backend.set_fill_level(fill_level)
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


@dataclass(slots=True)
class Valve:
    enabled: bool = True
    simulate: bool = True
    visa_resource: str = "COM6"
    backend: TextCommandBackend | None = None
    command_position_1: str = "1"
    command_position_2: str = "2"
    position: int = 1
    initialized: bool = False

    def initialize(self) -> None:
        self.initialized = True
        if self.backend is not None:
            self.backend.write(f"OPEN {self.visa_resource}")

    def set_position(self, position: int) -> None:
        if position not in (1, 2):
            raise ValueError(f"Unsupported valve position: {position}")
        self.position = position
        if self.backend is not None:
            command = self.command_position_1 if position == 1 else self.command_position_2
            self.backend.write(command)

    def cleanup(self) -> None:
        if self.backend is not None:
            self.backend.close()
        self.initialized = False


@dataclass(slots=True)
class PriorZMotor:
    enabled: bool = False
    visa_resource: str = "COM7"
    backend: TextCommandBackend | None = None
    position: float = 0.0
    initialized: bool = False
    moving: bool = False

    def initialize(self) -> None:
        self.initialized = True
        if self.backend is not None:
            self.backend.write(f"OPEN {self.visa_resource}")

    def go_to_abs_pos(self, position: float) -> None:
        self.moving = True
        if self.backend is not None:
            self.backend.write(f"G {position}")
        self.position = position
        self.moving = False

    def read_position(self) -> float:
        if self.backend is not None:
            response = self.backend.query("P")
            try:
                self.position = float(response.strip())
            except ValueError:
                pass
        return self.position

    def read_movement(self) -> bool:
        if self.backend is not None:
            response = self.backend.query("$")
            self.moving = response.strip() not in {"0", "IDLE", "READY"}
        return self.moving

    def zero_pos(self) -> None:
        if self.backend is not None:
            self.backend.write("Z")
        self.position = 0.0

    def cleanup(self) -> None:
        if self.backend is not None:
            self.backend.close()
        self.initialized = False
