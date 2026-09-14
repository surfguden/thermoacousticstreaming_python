from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from ..domain import (
    ConnectionState,
    DeviceId,
    ExperimentPlan,
    LabSnapshot,
    OperatingMode,
)
from .experiment import ExperimentRunner
from .ports import DevicePort
from .validation import ActionValidationError, validate_action


class LabApplication:
    """Owns lifecycle and validated actions; UI code never calls drivers."""

    def __init__(self, devices: Mapping[DeviceId, DevicePort], mode: OperatingMode) -> None:
        expected = set(DeviceId)
        if set(devices) != expected:
            missing = ", ".join(sorted(item.value for item in expected - set(devices)))
            raise ValueError(f"Device set is incomplete: {missing}")
        if any(port.mode is not mode for port in devices.values()):
            raise ValueError("All device ports must match the application mode")
        self._devices = dict(devices)
        self.mode = mode
        self.message = "Ready — no hardware is accessed until an explicit real-mode connection"
        self._listeners: list[Callable[[LabSnapshot], None]] = []
        self.experiment = ExperimentRunner(self.execute)

    def subscribe(self, listener: Callable[[LabSnapshot], None]) -> Callable[[], None]:
        self._listeners.append(listener)
        listener(self.snapshot())

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    def _publish(self) -> None:
        snapshot = self.snapshot()
        for listener in tuple(self._listeners):
            listener(snapshot)

    def snapshot(self) -> LabSnapshot:
        plan = self.experiment.plan
        return LabSnapshot(
            mode=self.mode,
            devices={device: port.state() for device, port in self._devices.items()},
            experiment_state=self.experiment.state,
            experiment_step=self.experiment.step_index,
            experiment_total=len(plan.steps) if plan else 0,
            message=self.experiment.error or self.message,
        )

    def connect(self, device: DeviceId) -> None:
        port = self._devices[device]
        try:
            port.connect()
            self.message = f"{device.value} connected in {self.mode.value} mode"
        except Exception as exc:
            self.message = str(exc)
            raise
        finally:
            self._publish()

    def disconnect(self, device: DeviceId) -> None:
        try:
            self._devices[device].disconnect()
            self.message = f"{device.value} disconnected"
        finally:
            self._publish()

    def execute(
        self,
        device: DeviceId,
        command: str,
        parameters: Mapping[str, Any] | None = None,
    ) -> None:
        values = dict(parameters or {})
        validate_action(device, command, values)
        port = self._devices[device]
        if port.state().connection is not ConnectionState.CONNECTED:
            raise ActionValidationError(f"Connect {device.value} before running {command}")
        port.execute(command, values)
        self.message = f"{device.value}: {command.replace('_', ' ')} completed"
        self._publish()

    def start_experiment(self, plan: ExperimentPlan) -> None:
        self.experiment.start(plan)
        self.message = f"Running {plan.name}"
        self._publish()

    def cancel_experiment(self) -> None:
        self.experiment.cancel()
        self.message = "Experiment cancelled"
        self._publish()

    def tick(self) -> None:
        if self.experiment.tick():
            if self.experiment.state.value != "running":
                self.message = f"Experiment {self.experiment.state.value}"
            self._publish()

    def shutdown(self) -> list[str]:
        self.experiment.cancel()
        errors: list[str] = []
        for device, port in reversed(tuple(self._devices.items())):
            try:
                port.disconnect()
            except Exception as exc:
                errors.append(f"{device.value}: {exc}")
        self.message = "Shutdown complete" if not errors else "Shutdown completed with errors"
        self._publish()
        return errors
