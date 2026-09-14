from __future__ import annotations

from dataclasses import dataclass, field
import threading

from ..application import HardwarePorts, LabApplication
from ..domain import (
    CameraCapabilities, CameraConfig, CaptureRequest, CaptureResult,
    ConnectionState, DeviceId, DeviceStatus, DigitalOutputConfig, OperatingMode,
    PumpConfig, PumpStatus, RegionOfInterest, ScopeCapture, ScopeCaptureRequest,
    TecChannelStatus, TemperatureSetpoints, ValvePosition, ValveStatus,
    WaveformConfig, ZStageCapabilities,
)


@dataclass(slots=True)
class AdapterFlags:
    connected: bool = False
    busy: bool = False
    configured: bool = False
    active: bool = False
    fault: str | None = None


class SimulatedAdapter:
    mode = OperatingMode.SIMULATION

    def __init__(self, device_id: DeviceId) -> None:
        self.device_id = device_id
        self.flags = AdapterFlags()
        self._lock = threading.RLock()

    def connect(self) -> None:
        with self._lock:
            self.flags.connected = True
            self.flags.fault = None

    def disconnect(self) -> None:
        with self._lock:
            self.flags = AdapterFlags()

    def _require_connected(self) -> None:
        if not self.flags.connected:
            raise RuntimeError(f"{self.device_id.value} is not connected")

    def read_status(self) -> DeviceStatus:
        with self._lock:
            connection = ConnectionState.CONNECTED if self.flags.connected else ConnectionState.DISCONNECTED
            if self.flags.fault:
                connection = ConnectionState.ERROR
            return DeviceStatus(
                device=self.device_id,
                connection=connection,
                busy=self.flags.busy,
                configured=self.flags.configured,
                active=self.flags.active,
                summary="Simulated and ready" if self.flags.connected else "Not connected",
                fault=self.flags.fault,
                readings=self._readings(),
            )

    def _readings(self) -> dict[str, object]:
        return {}


class SimulatedAD2Adapter(SimulatedAdapter):
    def __init__(self) -> None:
        super().__init__(DeviceId.AD2)
        self.waveform_config: WaveformConfig | None = None
        self.digital_config: DigitalOutputConfig | None = None
        self.digital_running = False

    def configure_waveform(self, config: WaveformConfig) -> WaveformConfig:
        self._require_connected()
        self.waveform_config = config
        self.flags.configured = True
        return config

    def start_waveform(self) -> None:
        self._require_connected()
        if self.waveform_config is None:
            raise RuntimeError("Configure the waveform before starting output")
        self.flags.active = True

    def stop_waveform(self) -> None:
        self.flags.active = False

    def trigger_waveform(self) -> None:
        self._require_connected()

    def configure_digital_output(self, config: DigitalOutputConfig) -> None:
        self._require_connected()
        self.digital_config = config

    def start_digital_output(self) -> None:
        self._require_connected()
        if self.digital_config is None:
            raise RuntimeError("Configure digital output before starting it")
        self.digital_running = True

    def stop_digital_output(self) -> None:
        self.digital_running = False

    def capture_scope(self, request: ScopeCaptureRequest) -> ScopeCapture:
        self._require_connected()
        samples = {channel: tuple(0.0 for _ in range(request.sample_count)) for channel in request.channels}
        return ScopeCapture(samples, request.sample_frequency_hz)

    def _readings(self) -> dict[str, object]:
        return {
            "waveform": self.waveform_config,
            "digital_output_running": self.digital_running,
        }


class SimulatedPumpAdapter(SimulatedAdapter):
    def __init__(self) -> None:
        super().__init__(DeviceId.PUMP)
        self.config: PumpConfig | None = None
        self.flow_ul_min = 0.0
        self.fill_volume_ul = 0.0
        self.maximum_volume_ul = 1_000.0
        self.referenced = False

    def configure_pump(self, config: PumpConfig) -> None:
        self._require_connected()
        self.config = config
        self.flags.configured = True

    def reference_pump(self) -> None:
        self._require_connected()
        self.referenced = True

    def set_flow(self, flow_ul_min: float) -> None:
        self._require_connected()
        self.flow_ul_min = flow_ul_min
        self.flags.active = flow_ul_min != 0

    def move_to_volume(self, volume_ul: float, flow_ul_min: float) -> None:
        self._require_connected()
        if not 0 <= volume_ul <= self.maximum_volume_ul:
            raise ValueError("Requested volume is outside the simulated syringe capacity")
        self.fill_volume_ul = volume_ul
        self.flow_ul_min = flow_ul_min
        self.flags.active = False

    def refill(self, flow_ul_min: float | None = None) -> None:
        self._require_connected()
        self.fill_volume_ul = self.maximum_volume_ul
        self.flow_ul_min = flow_ul_min or 0.0

    def empty(self, flow_ul_min: float | None = None) -> None:
        self._require_connected()
        self.fill_volume_ul = 0.0
        self.flow_ul_min = flow_ul_min or 0.0

    def stop_pump(self) -> None:
        self.flow_ul_min = 0.0
        self.flags.active = False

    def read_pump_status(self) -> PumpStatus:
        return PumpStatus(
            self.read_status(), self.fill_volume_ul, self.flow_ul_min,
            self.maximum_volume_ul, self.referenced,
        )

    def _readings(self) -> dict[str, object]:
        return {"flow_ul_min": self.flow_ul_min, "fill_volume_ul": self.fill_volume_ul, "referenced": self.referenced}


class SimulatedValveAdapter(SimulatedAdapter):
    def __init__(self) -> None:
        super().__init__(DeviceId.VALVE)
        self.position: ValvePosition | None = None

    def set_valve_position(self, position: ValvePosition) -> None:
        self._require_connected()
        self.position = position
        self.flags.configured = True

    def read_valve_status(self) -> ValveStatus:
        return ValveStatus(self.read_status(), self.position)

    def _readings(self) -> dict[str, object]:
        return {"position": self.position.value if self.position else None}


class SimulatedCameraAdapter(SimulatedAdapter):
    def __init__(self) -> None:
        super().__init__(DeviceId.CAMERA)
        self.config = CameraConfig()
        self.snapshots = 0
        self.roi: RegionOfInterest | None = None

    def read_camera_capabilities(self) -> CameraCapabilities:
        return CameraCapabilities(buffer_frames=100, readout_time_s=0.001, minimum_trigger_interval_s=0.002)

    def configure_camera(self, config: CameraConfig) -> CameraConfig:
        self._require_connected()
        self.config = config
        self.roi = config.roi
        self.flags.configured = True
        return config

    def configure_roi(self, roi: RegionOfInterest) -> None:
        self._require_connected()
        self.roi = roi

    def capture_snapshot(self) -> CaptureResult:
        self._require_connected()
        self.snapshots += 1
        return CaptureResult((b"simulated-frame",), (f"simulation-{self.snapshots}",))

    def capture_sequence(self, request: CaptureRequest) -> CaptureResult:
        self._require_connected()
        frames = tuple(b"simulated-frame" for _ in range(request.frame_count))
        timestamps = tuple(f"simulation-{index + 1}" for index in range(request.frame_count))
        return CaptureResult(frames, timestamps)

    def stop_camera(self) -> None:
        self.flags.active = False

    def _readings(self) -> dict[str, object]:
        return {"exposure_ms": self.config.exposure_ms, "frame_count": self.config.frame_count, "snapshots": self.snapshots}


class SimulatedTecAdapter(SimulatedAdapter):
    def __init__(self) -> None:
        super().__init__(DeviceId.TEC)
        self.channels = {1: TecChannelStatus(1, 25.0, 25.0), 2: TecChannelStatus(2, 25.0, 25.0)}

    def read_tec_channels(self) -> tuple[TecChannelStatus, ...]:
        return tuple(self.channels.values())

    def set_temperatures(self, setpoints: TemperatureSetpoints) -> tuple[TecChannelStatus, ...]:
        self._require_connected()
        for channel, target in setpoints.by_channel_c.items():
            self.channels[channel] = TecChannelStatus(channel, target, target, True, True)
        self.flags.configured = True
        self.flags.active = True
        return self.read_tec_channels()

    def disable_tec_outputs(self) -> tuple[TecChannelStatus, ...]:
        self.channels = {
            channel: TecChannelStatus(channel, status.current_temperature_c, status.target_temperature_c, False, status.ready)
            for channel, status in self.channels.items()
        }
        self.flags.active = False
        return self.read_tec_channels()

    def _readings(self) -> dict[str, object]:
        return {f"channel_{item.channel}_c": item.current_temperature_c for item in self.channels.values()}


class SimulatedZStageAdapter(SimulatedAdapter):
    def __init__(self) -> None:
        super().__init__(DeviceId.Z_STAGE)
        self.position_um = 0.0
        self.closed_loop = False
        self.capabilities = ZStageCapabilities(maximum_travel_um=450.0)

    def read_z_stage_capabilities(self) -> ZStageCapabilities:
        return ZStageCapabilities(maximum_travel_um=450.0, closed_loop=self.closed_loop)

    def read_position_um(self) -> float:
        self._require_connected()
        return self.position_um

    def enable_closed_loop(self) -> None:
        self._require_connected()
        self.closed_loop = True

    def move_to_um(self, position_um: float) -> float:
        self._require_connected()
        if not self.closed_loop:
            raise RuntimeError("Closed-loop control must be enabled before moving the Z-stage")
        if not 0 <= position_um <= 450:
            raise ValueError("Z-stage position is outside simulated travel")
        self.position_um = position_um
        return self.position_um

    def _readings(self) -> dict[str, object]:
        return {"position_um": self.position_um, "closed_loop": self.closed_loop}


def build_simulated_ports() -> HardwarePorts:
    return HardwarePorts(
        ad2=SimulatedAD2Adapter(),
        pump=SimulatedPumpAdapter(),
        valve=SimulatedValveAdapter(),
        camera=SimulatedCameraAdapter(),
        tec=SimulatedTecAdapter(),
        z_stage=SimulatedZStageAdapter(),
    )


def build_simulated_application() -> LabApplication:
    return LabApplication(build_simulated_ports(), OperatingMode.SIMULATION)
