from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..application import HardwarePorts, LabApplication
from ..domain import (
    CameraCapabilities, CameraConfig, CaptureRequest, CaptureResult,
    ConnectionState, DeviceId, DeviceStatus, DigitalOutputConfig, OperatingMode,
    PumpConfig, PumpStatus, RegionOfInterest, ScopeCapture, ScopeCaptureRequest,
    TecChannelStatus, TemperatureSetpoints, ValvePosition, ValveStatus,
    WaveformConfig, ZStageCapabilities,
)


@dataclass(slots=True)
class _Flags:
    connected: bool = False
    busy: bool = False
    configured: bool = False
    active: bool = False
    fault: str | None = None


class AD2Adapter:
    device_id = DeviceId.AD2
    mode = OperatingMode.REAL

    def __init__(self, driver: Any) -> None:
        self.driver = driver
        self.flags = _Flags()
        self.waveform_config: WaveformConfig | None = None
        self.digital_running = False

    def connect(self) -> None:
        if self.flags.connected:
            return
        try:
            self.driver.initialize()
            self.flags.connected = self.driver.get_phdwf() is not None
            if not self.flags.connected:
                raise RuntimeError("AD2 driver did not return a device handle")
            self.flags.fault = None
        except Exception as exc:
            self.flags.fault = str(exc)
            raise

    def disconnect(self) -> None:
        if not self.flags.connected:
            return
        try:
            self.driver.cleanup()
        except Exception as exc:
            self.flags.fault = str(exc)
            raise
        self.flags = _Flags()

    def read_status(self) -> DeviceStatus:
        return _device_status(self.device_id, self.flags, {"waveform": self.waveform_config, "digital_output_running": self.digital_running})

    def configure_waveform(self, config: WaveformConfig) -> WaveformConfig:
        from ..ad2 import CarrierSettings, WaveformFunction, WfgChannelConfig, WfgConfig

        functions = {
            "sine": WaveformFunction.SINE, "square": WaveformFunction.SQUARE,
            "triangle": WaveformFunction.TRIANGLE, "ramp_up": WaveformFunction.RAMP_UP,
            "ramp_down": WaveformFunction.RAMP_DOWN, "dc": WaveformFunction.DC,
        }
        try:
            function = functions[config.function.lower()]
        except KeyError as exc:
            raise ValueError(f"Unsupported waveform function: {config.function}") from exc
        channel = WfgChannelConfig(
            channel_index=config.channel,
            carrier=CarrierSettings(
                frequency_hz=config.frequency_hz,
                amplitude_v=config.amplitude_v,
                offset_v=config.offset_v,
                phase_deg=config.phase_deg,
                function=function,
            ),
        )
        self.driver.wfg_configure(WfgConfig(channels=[channel]))
        effective = self.driver.wfg_configure_read_back()
        effective_channel = effective.channels[0].effective_carrier or effective.channels[0].carrier
        canonical_function = {value: name for name, value in functions.items()}[effective_channel.function]
        self.waveform_config = WaveformConfig(
            channel=config.channel,
            frequency_hz=effective_channel.frequency_hz,
            amplitude_v=effective_channel.amplitude_v,
            offset_v=effective_channel.offset_v,
            phase_deg=effective_channel.phase_deg,
            function=canonical_function,
        )
        self.flags.configured = True
        return self.waveform_config

    def start_waveform(self) -> None:
        if not self.flags.configured:
            raise RuntimeError("Configure the waveform before starting output")
        self.driver.wfg_start_stop_all_ch(True)
        self.flags.active = True

    def stop_waveform(self) -> None:
        if self.flags.connected:
            self.driver.wfg_start_stop_all_ch(False)
        self.flags.active = False

    def trigger_waveform(self) -> None:
        self.driver.pc_trigger()

    def configure_digital_output(self, config: DigitalOutputConfig) -> None:
        from ..ad2 import DigitalOutType, DoConfig, DoSingleChannelConfig

        types = {"pulse": DigitalOutType.PULSE, "custom": DigitalOutType.CUSTOM, "random": DigitalOutType.RANDOM}
        channel = DoSingleChannelConfig(
            channel_index=config.channel,
            enable=True,
            clock_divider=config.clock_divider,
            output_type=types[config.output_type.lower()],
            counter_high_bits=config.high_bits,
            counter_low_bits=config.low_bits,
        )
        self.driver.do_configure(DoConfig(channels=[channel]))

    def start_digital_output(self) -> None:
        self.driver.start_stop_do(True)
        self.digital_running = True

    def stop_digital_output(self) -> None:
        if self.flags.connected:
            self.driver.start_stop_do(False)
        self.digital_running = False

    def capture_scope(self, request: ScopeCaptureRequest) -> ScopeCapture:
        data = self.driver.capture_scope_channels(
            channel_indices=list(request.channels),
            sample_frequency_hz=request.sample_frequency_hz,
            sample_count=request.sample_count,
            range_v=request.range_v,
            offset_v=request.offset_v,
            trigger_source=request.trigger_source,
        )
        return ScopeCapture({channel: tuple(samples) for channel, samples in data.items()}, request.sample_frequency_hz)


class CetoniPumpAdapter:
    device_id = DeviceId.PUMP
    mode = OperatingMode.REAL

    def __init__(self, driver: Any) -> None:
        self.driver = driver
        self.flags = _Flags()
        self.flow_ul_min = 0.0

    def connect(self) -> None:
        if not self.flags.connected:
            self.driver.initialize()
            self.flags.connected = bool(self.driver.initialized)

    def disconnect(self) -> None:
        if self.flags.connected:
            self.driver.cleanup()
        self.flags = _Flags()

    def read_status(self) -> DeviceStatus:
        return _device_status(self.device_id, self.flags, {"fill_volume_ul": float(self.driver.fill_level) * 1000, "flow_ul_min": self.flow_ul_min, "referenced": bool(self.driver.referenced)})

    def configure_pump(self, config: PumpConfig) -> None:
        self.driver.configure_flow_unit(config.flow_unit)
        self.driver.configure_syringe({"inner_diameter_mm": config.inner_diameter_mm, "max_piston_stroke_mm": config.piston_stroke_mm})
        self.flags.configured = True

    def reference_pump(self) -> None:
        self.driver.reference_move()

    def set_flow(self, flow_ul_min: float) -> None:
        self.driver.generate_flow(flow_ul_min)
        self.flow_ul_min = flow_ul_min
        self.flags.active = flow_ul_min != 0

    def move_to_volume(self, volume_ul: float, flow_ul_min: float) -> None:
        self.driver.set_fill_level(volume_ul / 1000.0, flow_ul_min)

    def refill(self, flow_ul_min: float | None = None) -> None:
        self.driver.refill(flow_ul_min)

    def empty(self, flow_ul_min: float | None = None) -> None:
        self.driver.empty(flow_ul_min)

    def stop_pump(self) -> None:
        if self.flags.connected:
            self.driver.stop()
        self.flow_ul_min = 0.0
        self.flags.active = False

    def read_pump_status(self) -> PumpStatus:
        if self.flags.connected:
            self.driver.sync_fill_level()
            self.flags.active = bool(self.driver.read_status())
        maximum = self.driver.known_capacity_ml or self.driver.max_volume_ml
        return PumpStatus(self.read_status(), self.driver.fill_level * 1000, self.flow_ul_min, maximum * 1000, self.driver.referenced)


class NemesysPumpAdapter(CetoniPumpAdapter):
    """Alternative adapter for the standalone, explicitly-unitized neMESYS driver."""

    def connect(self) -> None:
        if not self.flags.connected:
            self.driver.connect()
            self.flags.connected = bool(self.driver.is_connected)

    def disconnect(self) -> None:
        if self.flags.connected:
            self.driver.close()
        self.flags = _Flags()

    def configure_pump(self, config: PumpConfig) -> None:
        self.driver.configure_syringe(config.inner_diameter_mm, config.piston_stroke_mm)
        self.flags.configured = True

    def reference_pump(self) -> None:
        self.driver.reference_move()

    def set_flow(self, flow_ul_min: float) -> None:
        self.driver.set_flow(flow_ul_min)
        self.flow_ul_min = flow_ul_min
        self.flags.active = self.driver.is_pumping

    def move_to_volume(self, volume_ul: float, flow_ul_min: float) -> None:
        self.driver.move_to_volume(volume_ul, flow_ul_min)

    def refill(self, flow_ul_min: float | None = None) -> None:
        if flow_ul_min is None:
            raise ValueError("The standalone neMESYS adapter requires flow_ul_min for refill")
        self.driver.refill(flow_ul_min)

    def empty(self, flow_ul_min: float | None = None) -> None:
        if flow_ul_min is None:
            raise ValueError("The standalone neMESYS adapter requires flow_ul_min for empty")
        self.driver.empty(flow_ul_min)

    def read_status(self) -> DeviceStatus:
        return _device_status(self.device_id, self.flags, {"fill_volume_ul": self.driver.current_volume_ul if self.flags.connected else None, "flow_ul_min": self.flow_ul_min})

    def read_pump_status(self) -> PumpStatus:
        return PumpStatus(self.read_status(), self.driver.current_volume_ul, self.driver.current_flow_ul_min, self.driver.maximum_volume_ul, False)


class ValveAdapter:
    device_id = DeviceId.VALVE
    mode = OperatingMode.REAL

    def __init__(self, driver: Any) -> None:
        self.driver = driver
        self.flags = _Flags()

    def connect(self) -> None:
        if not self.flags.connected:
            self.driver.initialize()
            self.flags.connected = bool(self.driver.initialized)

    def disconnect(self) -> None:
        if self.flags.connected:
            self.driver.cleanup()
        self.flags = _Flags()

    def set_valve_position(self, position: ValvePosition) -> None:
        self.driver.set_position(position.value)
        self.flags.configured = True

    def read_status(self) -> DeviceStatus:
        return _device_status(self.device_id, self.flags, {"position": self.driver.position})

    def read_valve_status(self) -> ValveStatus:
        position = ValvePosition(self.driver.position) if self.flags.connected else None
        return ValveStatus(self.read_status(), position)


class CameraAdapter:
    device_id = DeviceId.CAMERA
    mode = OperatingMode.REAL

    def __init__(self, driver: Any) -> None:
        self.driver = driver
        self.flags = _Flags()
        self.config = CameraConfig()

    def connect(self) -> None:
        if not self.flags.connected:
            self.driver.initialize()
            self.flags.connected = self.driver.get_handle_out() is not None

    def disconnect(self) -> None:
        if self.flags.connected:
            self.driver.cleanup()
        self.flags = _Flags()

    def read_status(self) -> DeviceStatus:
        return _device_status(self.device_id, self.flags, {"exposure_ms": self.driver.exposure_ms, "frame_count": self.config.frame_count})

    def read_camera_capabilities(self) -> CameraCapabilities:
        return CameraCapabilities(self.driver.get_camera_buffer_size(), self.driver.read_readout_time(), self.driver.read_min_trigger_interval())

    def configure_camera(self, config: CameraConfig) -> CameraConfig:
        applied = self.driver.configure_exposure_time(config.exposure_ms)
        if config.roi is not None:
            self.configure_roi(config.roi)
        self.driver.configure_sequence({"frame_count": config.frame_count})
        self.driver.configure_trigger_global_exposure(config.global_exposure_trigger)
        self.config = CameraConfig(applied, config.frame_count, config.roi, config.global_exposure_trigger)
        self.flags.configured = True
        return self.config

    def configure_roi(self, roi: RegionOfInterest) -> None:
        from ..camera import SubRegion
        self.driver.configure_roi(SubRegion(roi.horizontal_offset, roi.vertical_offset, roi.horizontal_size, roi.vertical_size))

    def capture_snapshot(self) -> CaptureResult:
        return CaptureResult((self.driver.capture_snapshot(),), tuple(self.driver.read_frame_timestamps()))

    def capture_sequence(self, request: CaptureRequest) -> CaptureResult:
        frames = self.driver.image_sequence(request.frame_count, request.partial_capture_folder)
        return CaptureResult(tuple(frames), tuple(self.driver.read_frame_timestamps()))

    def stop_camera(self) -> None:
        if self.flags.connected:
            self.driver.stop_capture()
        self.flags.active = False


class TecAdapter:
    device_id = DeviceId.TEC
    mode = OperatingMode.REAL

    def __init__(self, driver: Any) -> None:
        self.driver = driver
        self.flags = _Flags()
        self._channels: tuple[TecChannelStatus, ...] = ()

    def connect(self) -> None:
        if not self.flags.connected:
            self.driver.initialize()
            self.flags.connected = bool(self.driver.initialized)
            self._channels = _tec_statuses(getattr(self.driver, "last_status", {}))

    def disconnect(self) -> None:
        if self.flags.connected:
            self.driver.cleanup()
        self.flags = _Flags()
        self._channels = ()

    def read_status(self) -> DeviceStatus:
        readings = {f"channel_{item.channel}_c": item.current_temperature_c for item in self._channels}
        return _device_status(self.device_id, self.flags, readings)

    def read_tec_channels(self) -> tuple[TecChannelStatus, ...]:
        return self._channels

    def set_temperatures(self, setpoints: TemperatureSetpoints) -> tuple[TecChannelStatus, ...]:
        result = self.driver.apply_static_setpoint(setpoints.by_channel_c, channels=tuple(setpoints.by_channel_c))
        self.flags.configured = True
        self.flags.active = True
        self._channels = _tec_statuses(result)
        return self._channels

    def disable_tec_outputs(self) -> tuple[TecChannelStatus, ...]:
        if not self.flags.connected:
            return ()
        result = self.driver.set_output_stage_static_off()
        self.flags.active = False
        self._channels = _tec_statuses(result)
        return self._channels


class PiezoZStageAdapter:
    device_id = DeviceId.Z_STAGE
    mode = OperatingMode.REAL

    def __init__(self, driver: Any) -> None:
        self.driver = driver
        self.flags = _Flags()
        self._position_um: float | None = None
        self._closed_loop = False

    def connect(self) -> None:
        if not self.flags.connected:
            self.driver.connect()
            self.flags.connected = bool(self.driver.connected)
            self._closed_loop = not self.driver.needs_closed_loop_confirmation()

    def disconnect(self) -> None:
        if self.flags.connected:
            self.driver.disconnect()
        self.flags = _Flags()
        self._position_um = None
        self._closed_loop = False

    def read_status(self) -> DeviceStatus:
        readings = {"position_um": self._position_um, "closed_loop": self._closed_loop} if self.flags.connected else {}
        return _device_status(self.device_id, self.flags, readings)

    def read_z_stage_capabilities(self) -> ZStageCapabilities:
        return ZStageCapabilities(
            self.driver.max_travel_um, self.driver.min_output_voltage_v,
            self.driver.max_output_voltage_v,
            self.flags.connected and self._closed_loop,
        )

    def read_position_um(self) -> float:
        if self._position_um is None:
            raise RuntimeError("No cached Z-stage position is available")
        return self._position_um

    def enable_closed_loop(self) -> None:
        self.driver.switch_to_closed_loop()
        self._closed_loop = True

    def move_to_um(self, position_um: float) -> float:
        self._position_um = self.driver.set_position(position_um)
        return self._position_um


def _device_status(device: DeviceId, flags: _Flags, readings: dict[str, object]) -> DeviceStatus:
    connection = ConnectionState.ERROR if flags.fault else (ConnectionState.CONNECTED if flags.connected else ConnectionState.DISCONNECTED)
    return DeviceStatus(device, connection, flags.busy, flags.configured, flags.active, "Connected" if flags.connected else "Not connected", readings, flags.fault)


def _tec_statuses(statuses: dict[int, Any]) -> tuple[TecChannelStatus, ...]:
    return tuple(
        TecChannelStatus(item.channel, item.current_temperature_c, item.target_temperature_c, item.output_stage_static_on, item.ready, item.error_state)
        for _, item in sorted(statuses.items())
    )


def build_real_ports() -> HardwarePorts:
    """Construct adapters without connecting to or probing any hardware."""
    from ..hamamatsu_dcam import HamamatsuDcamBackend
    from ..instruments import AD2Sdk, CetoniPump, HamamatsuCamera, SerialTextCommandBackend, Valve
    from ..qmix_backend import QmixPumpBackend
    from ..tec import TecController
    from ..thorlabs_piezo import PiezoStage

    return HardwarePorts(
        ad2=AD2Adapter(AD2Sdk()),
        pump=CetoniPumpAdapter(CetoniPump(simulate=False, backend=QmixPumpBackend())),
        valve=ValveAdapter(Valve(simulate=False, backend=SerialTextCommandBackend(device_name="valve"))),
        camera=CameraAdapter(HamamatsuCamera(simulate=False, backend=HamamatsuDcamBackend())),
        tec=TecAdapter(TecController(enabled=True, simulate=False)),
        z_stage=PiezoZStageAdapter(PiezoStage()),
    )


def build_real_application() -> LabApplication:
    return LabApplication(build_real_ports(), OperatingMode.REAL)
