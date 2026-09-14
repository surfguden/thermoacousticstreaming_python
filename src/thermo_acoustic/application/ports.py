from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..domain import (
    CameraCapabilities,
    CameraConfig,
    CaptureRequest,
    CaptureResult,
    DeviceId,
    DeviceStatus,
    DigitalOutputConfig,
    OperatingMode,
    PumpConfig,
    PumpStatus,
    RegionOfInterest,
    ScopeCapture,
    ScopeCaptureRequest,
    TecChannelStatus,
    TemperatureSetpoints,
    ValvePosition,
    ValveStatus,
    WaveformConfig,
    ZStageCapabilities,
)


class DevicePort(Protocol):
    device_id: DeviceId
    mode: OperatingMode

    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def read_status(self) -> DeviceStatus: ...


class WaveformPort(Protocol):
    def configure_waveform(self, config: WaveformConfig) -> WaveformConfig: ...
    def start_waveform(self) -> None: ...
    def stop_waveform(self) -> None: ...
    def trigger_waveform(self) -> None: ...


class DigitalOutputPort(Protocol):
    def configure_digital_output(self, config: DigitalOutputConfig) -> None: ...
    def start_digital_output(self) -> None: ...
    def stop_digital_output(self) -> None: ...


class OscilloscopePort(Protocol):
    def capture_scope(self, request: ScopeCaptureRequest) -> ScopeCapture: ...


class AD2Port(DevicePort, WaveformPort, DigitalOutputPort, OscilloscopePort, Protocol):
    pass


class PumpPort(DevicePort, Protocol):
    def configure_pump(self, config: PumpConfig) -> None: ...
    def reference_pump(self) -> None: ...
    def set_flow(self, flow_ul_min: float) -> None: ...
    def move_to_volume(self, volume_ul: float, flow_ul_min: float) -> None: ...
    def refill(self, flow_ul_min: float | None = None) -> None: ...
    def empty(self, flow_ul_min: float | None = None) -> None: ...
    def stop_pump(self) -> None: ...
    def read_pump_status(self) -> PumpStatus: ...


class ValvePort(DevicePort, Protocol):
    def set_valve_position(self, position: ValvePosition) -> None: ...
    def read_valve_status(self) -> ValveStatus: ...


class CameraPort(DevicePort, Protocol):
    def read_camera_capabilities(self) -> CameraCapabilities: ...
    def configure_camera(self, config: CameraConfig) -> CameraConfig: ...
    def capture_snapshot(self) -> CaptureResult: ...
    def capture_sequence(self, request: CaptureRequest) -> CaptureResult: ...
    def stop_camera(self) -> None: ...
    def configure_roi(self, roi: RegionOfInterest) -> None: ...


class TecPort(DevicePort, Protocol):
    def read_tec_channels(self) -> tuple[TecChannelStatus, ...]: ...
    def set_temperatures(self, setpoints: TemperatureSetpoints) -> tuple[TecChannelStatus, ...]: ...
    def disable_tec_outputs(self) -> tuple[TecChannelStatus, ...]: ...


class ZStagePort(DevicePort, Protocol):
    def read_z_stage_capabilities(self) -> ZStageCapabilities: ...
    def read_position_um(self) -> float: ...
    def enable_closed_loop(self) -> None: ...
    def move_to_um(self, position_um: float) -> float: ...


@dataclass(frozen=True, slots=True)
class HardwarePorts:
    ad2: AD2Port
    pump: PumpPort
    valve: ValvePort
    camera: CameraPort
    tec: TecPort
    z_stage: ZStagePort

    def by_id(self, device: DeviceId) -> DevicePort:
        return {
            DeviceId.AD2: self.ad2,
            DeviceId.PUMP: self.pump,
            DeviceId.VALVE: self.valve,
            DeviceId.CAMERA: self.camera,
            DeviceId.TEC: self.tec,
            DeviceId.Z_STAGE: self.z_stage,
        }[device]

    def all(self) -> tuple[DevicePort, ...]:
        return (self.ad2, self.pump, self.valve, self.camera, self.tec, self.z_stage)
