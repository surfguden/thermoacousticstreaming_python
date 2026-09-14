from __future__ import annotations

from concurrent.futures import Future
from dataclasses import replace
import threading
from typing import Any

from ..domain import (
    CaptureCameraSequence, CaptureScope, CaptureSnapshot, ConfigureCamera,
    ConfigureDigitalOutput, ConfigurePump, ConfigureWaveform, ConnectDevice,
    ConnectionState, DeviceId, DisableTecOutputs, DisconnectDevice,
    EmptyPump, EnableZStageClosedLoop, ExperimentPlan, ExperimentState, LabCommand,
    LabSnapshot, MovePumpToVolume, MoveZStage, OperatingMode, ReferencePump,
    RefillPump, SetPumpFlow, SetTemperature, SetValvePosition,
    StartDigitalOutput, StartWaveform, StopCamera, StopDigitalOutput, StopPump,
    StopWaveform, TriggerWaveform, command_device,
)
from .executor import HardwareCommandExecutor
from .experiment import ExperimentRunner
from .ports import HardwarePorts
from .safety import SafetyCoordinator


class DeviceNotConnectedError(RuntimeError):
    pass


class LabApplication:
    """Typed application façade; presentation code never calls device adapters."""

    def __init__(self, ports: HardwarePorts, mode: OperatingMode) -> None:
        if any(port.mode is not mode for port in ports.all()):
            raise ValueError("All device ports must match the application mode")
        self.ports = ports
        self.mode = mode
        self._message = "Ready — devices remain disconnected until explicitly connected"
        self._message_lock = threading.RLock()
        self._device_locks = {device: threading.RLock() for device in DeviceId}
        self._busy_lock = threading.RLock()
        self._busy_devices: set[DeviceId] = set()
        self._closing = threading.Event()
        self._shutdown_lock = threading.Lock()
        self._shutdown_result: list[str] | None = None
        self._executor = HardwareCommandExecutor()
        self.safety = SafetyCoordinator(ports, self._device_locks)
        self.experiment = ExperimentRunner(self._execute_command, self._experiment_finished)

    @property
    def message(self) -> str:
        with self._message_lock:
            return self._message

    def _set_message(self, message: str) -> None:
        with self._message_lock:
            self._message = message

    def snapshot(self) -> LabSnapshot:
        with self._busy_lock:
            busy_devices = set(self._busy_devices)
        statuses = {}
        for port in self.ports.all():
            status = port.read_status()
            if port.device_id in busy_devices:
                status = replace(status, busy=True, summary=f"{status.summary} — operation in progress")
            statuses[port.device_id] = status
        experiment = self.experiment.status()
        return LabSnapshot(
            mode=self.mode,
            devices=statuses,
            experiment=experiment,
            message=experiment.fault or self.message,
        )

    def connect(self, device: DeviceId) -> None:
        self.execute(ConnectDevice(device))

    def disconnect(self, device: DeviceId) -> None:
        self.execute(DisconnectDevice(device))

    def connect_async(self, device: DeviceId) -> Future[Any]:
        return self.execute_async(ConnectDevice(device))

    def disconnect_async(self, device: DeviceId) -> Future[Any]:
        return self.execute_async(DisconnectDevice(device))

    def execute(self, command: LabCommand) -> object:
        if self._closing.is_set():
            raise RuntimeError("Application shutdown has started")
        if self.experiment.status().state is ExperimentState.RUNNING:
            raise RuntimeError("Interactive actions are disabled while an experiment is running")
        return self._execute_command(command)

    def execute_async(self, command: LabCommand) -> Future[Any]:
        if self._closing.is_set():
            raise RuntimeError("Application shutdown has started")
        if self.experiment.status().state is ExperimentState.RUNNING:
            raise RuntimeError("Interactive actions are disabled while an experiment is running")
        return self._executor.submit(lambda: self._execute_command(command))

    def _execute_command(self, command: LabCommand) -> object:
        device = command_device(command)
        with self._device_locks[device]:
            with self._busy_lock:
                self._busy_devices.add(device)
            try:
                result = self._dispatch(command)
            except Exception as exc:
                self._set_message(f"{device.value}: {exc}")
                raise
            finally:
                with self._busy_lock:
                    self._busy_devices.discard(device)
            self._set_message(f"{device.value}: {type(command).__name__} completed")
            return result

    def _dispatch(self, command: LabCommand) -> object:
        if isinstance(command, ConnectDevice):
            return self.ports.by_id(command.device).connect()
        if isinstance(command, DisconnectDevice):
            return self.ports.by_id(command.device).disconnect()

        device = command_device(command)
        if self.ports.by_id(device).read_status().connection is not ConnectionState.CONNECTED:
            raise DeviceNotConnectedError(f"Connect {device.value} before {type(command).__name__}")

        if isinstance(command, ConfigureWaveform): return self.ports.ad2.configure_waveform(command.config)
        if isinstance(command, StartWaveform): return self.ports.ad2.start_waveform()
        if isinstance(command, StopWaveform): return self.ports.ad2.stop_waveform()
        if isinstance(command, TriggerWaveform): return self.ports.ad2.trigger_waveform()
        if isinstance(command, ConfigureDigitalOutput): return self.ports.ad2.configure_digital_output(command.config)
        if isinstance(command, StartDigitalOutput): return self.ports.ad2.start_digital_output()
        if isinstance(command, StopDigitalOutput): return self.ports.ad2.stop_digital_output()
        if isinstance(command, CaptureScope): return self.ports.ad2.capture_scope(command.request)
        if isinstance(command, ConfigurePump): return self.ports.pump.configure_pump(command.config)
        if isinstance(command, ReferencePump): return self.ports.pump.reference_pump()
        if isinstance(command, SetPumpFlow): return self.ports.pump.set_flow(command.flow_ul_min)
        if isinstance(command, StopPump): return self.ports.pump.stop_pump()
        if isinstance(command, MovePumpToVolume): return self.ports.pump.move_to_volume(command.volume_ul, command.flow_ul_min)
        if isinstance(command, RefillPump): return self.ports.pump.refill(command.flow_ul_min)
        if isinstance(command, EmptyPump): return self.ports.pump.empty(command.flow_ul_min)
        if isinstance(command, SetValvePosition): return self.ports.valve.set_valve_position(command.position)
        if isinstance(command, ConfigureCamera): return self.ports.camera.configure_camera(command.config)
        if isinstance(command, CaptureSnapshot): return self.ports.camera.capture_snapshot()
        if isinstance(command, CaptureCameraSequence): return self.ports.camera.capture_sequence(command.request)
        if isinstance(command, StopCamera): return self.ports.camera.stop_camera()
        if isinstance(command, SetTemperature): return self.ports.tec.set_temperatures(command.setpoints)
        if isinstance(command, DisableTecOutputs): return self.ports.tec.disable_tec_outputs()
        if isinstance(command, EnableZStageClosedLoop): return self.ports.z_stage.enable_closed_loop()
        if isinstance(command, MoveZStage):
            maximum = self.ports.z_stage.read_z_stage_capabilities().maximum_travel_um
            if maximum is not None and command.position_um > maximum:
                raise ValueError(f"position_um exceeds device maximum travel of {maximum:g}")
            return self.ports.z_stage.move_to_um(command.position_um)
        raise TypeError(f"Unsupported command type: {type(command).__name__}")

    def start_experiment(self, plan: ExperimentPlan) -> None:
        if self._closing.is_set():
            raise RuntimeError("Application shutdown has started")
        previous_message = self.message
        self._set_message(f"Running {plan.name}")
        try:
            self.experiment.start(plan)
        except Exception:
            self._set_message(previous_message)
            raise

    def cancel_experiment(self) -> None:
        self.experiment.cancel(wait=True)
        errors = self.safety.safe_stop()
        self._set_message("Experiment cancelled" if not errors else "; ".join(errors))

    def cancel_experiment_async(self) -> Future[Any]:
        return self._executor.submit(self.cancel_experiment)

    def _experiment_finished(self, state: ExperimentState, fault: str | None) -> None:
        if state is ExperimentState.FAILED:
            errors = self.safety.safe_stop()
            detail = fault or "unknown failure"
            if errors:
                detail += "; safe-stop errors: " + "; ".join(errors)
            self._set_message(f"Experiment failed: {detail}")
        elif state is ExperimentState.COMPLETED:
            self._set_message("Experiment completed")

    def shutdown(self) -> list[str]:
        with self._shutdown_lock:
            if self._shutdown_result is not None:
                return list(self._shutdown_result)
            self._closing.set()
            self.experiment.cancel(wait=True)
            self._executor.shutdown(wait=True)
            errors = self.safety.shutdown()
            self._set_message("Shutdown complete" if not errors else "Shutdown completed with errors")
            self._shutdown_result = list(errors)
            return errors
