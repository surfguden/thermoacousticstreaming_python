from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


class PumpDriver(Protocol):
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

@dataclass(slots=True)
class CetoniPump:
    driver: PumpDriver
    enabled: bool = True
    configuration_path: Path = Path(r"C:\Users\Public\Documents\QmixElements\Projects")
    fill_level: float = 0.0
    dosing: bool = False
    syringe_config: dict | None = None
    flow_unit: str | None = None
    referenced: bool = False
    # Set True once initialize() completes (mirrors Valve/QmixPumpDriver's
    # own "initialized" flags) -- distinct from `referenced`, which now only
    # means "a physical reference move was confirmed". The retired transitional
    # UI pump connection-status row used this, not `referenced`, matching the same
    # pattern the Valve row already uses (`valve.initialized`).
    initialized: bool = False
    # Unknown until configure_syringe() obtains the driver's fresh maximum-volume readback.
    known_capacity_ml: float | None = None

    def sync_fill_level(self) -> None:
        self.fill_level = self.driver.read_fill_level()

    def initialize(self) -> None:
        if not self.enabled:
            return
        driver_initialized = False
        try:
            self.driver.initialize(self.configuration_path)
            driver_initialized = True
            self.sync_fill_level()
        except Exception as exc:
            self.initialized = False
            if not driver_initialized:
                raise
            try:
                self.driver.close()
            except Exception as cleanup_exc:
                raise RuntimeError(
                    f"Pump initialize failed after driver open: {exc}; "
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
        # does, via QmixPumpDriver.reference_move()'s poll-until-confirmed
        # or raise).

    def clear_fault_and_reinitialize(self) -> None:
        # Normal initialization now performs the owner-approved automatic
        # fault clear. This explicit operator-only path remains for a fault
        # observed after initialization or an operator-requested fresh
        # reconnect. It mirrors initialize()'s driver-open/rollback shape so
        # its traceable manual-recovery semantics remain separate.
        if not self.enabled:
            return
        clear_fault_and_reinitialize = getattr(self.driver, "clear_fault_and_reinitialize", None)
        if not callable(clear_fault_and_reinitialize):
            raise RuntimeError("This pump driver does not support an explicit fault-clear action.")
        driver_initialized = False
        try:
            clear_fault_and_reinitialize(self.configuration_path)
            driver_initialized = True
            self.sync_fill_level()
        except Exception as exc:
            self.initialized = False
            if not driver_initialized:
                # QmixPumpDriver.clear_fault_and_reinitialize() owns rollback
                # of failures raised inside its own open/start/clear/enable
                # sequence.
                raise
            try:
                self.driver.close()
            except Exception as cleanup_exc:
                raise RuntimeError(
                    f"Pump clear_fault_and_reinitialize failed after driver open: {exc}; "
                    f"cleanup after failed clear_fault_and_reinitialize also failed: {cleanup_exc}"
                ) from exc
            raise
        self.initialized = True

    def refill(self, flow_rate: float | None = None) -> None:
        self.driver.refill(flow_rate)
        self.sync_fill_level()

    def empty(self, flow_rate: float | None = None) -> None:
        self.driver.empty(flow_rate)
        self.fill_level = 0.0

    def stop(self) -> None:
        self.driver.stop()
        self.dosing = False

    def generate_flow(self, flow_rate: float) -> None:
        self.driver.generate_flow(flow_rate)
        self.dosing = True

    def set_fill_level(self, fill_level: float, flow_rate: float | None = None) -> None:
        self.driver.set_fill_level(fill_level, flow_rate)
        self.fill_level = fill_level

    def configure_syringe(self, config: dict | None) -> None:
        self.driver.configure_syringe(config)
        driver_max_volume_ml = getattr(self.driver, "max_volume_ml", None)
        if driver_max_volume_ml is not None:
            self.known_capacity_ml = float(driver_max_volume_ml)
        self.syringe_config = config

    def configure_syringe_bd(self, config: dict | None) -> None:
        self.configure_syringe(config)

    def configure_flow_unit(self, unit: str | None) -> None:
        self.driver.configure_flow_unit(unit)
        self.flow_unit = unit

    def reference_move(self) -> None:
        self.driver.reference_move()
        self.referenced = True

    def read_status(self) -> bool:
        self.dosing = self.driver.read_status()
        return self.dosing

    def cleanup(self) -> None:
        # Checkpoint-S-closure review finding (2026-09-07): previously
        # `self.stop()` was not guarded, so a raising stop() (e.g. a real
        # Qmix fault surfacing on close, or the concurrent-Stop race tracked
        # as UI-PUMP-STOP-THREAD-SAFETY-001) skipped `self.driver.close()`
        # entirely -- the serial/CAN connection was never released -- and
        # also skipped `self.initialized = False` below it, leaving the pump
        # falsely presented as still connected. Matches the established
        # best-effort multi-step cleanup pattern this project already uses
        # for TEC (`TecController.cleanup()`) and AD2 (`AD2Sdk.cleanup()`):
        # each step is attempted independently, a failure in one does not
        # skip the next, and both errors are collected and reported
        # together rather than one silently winning. `initialized` is left
        # unchanged (not forced to False) when cleanup could not be fully
        # confirmed clean -- same invariant TecController.cleanup() already
        # documents: a stuck/failed stop-or-close leaves the connection
        # state genuinely unknown, so this must not claim "uninitialized"
        # for a pump that may still be live.
        errors: list[str] = []
        try:
            self.stop()
        except Exception as exc:
            errors.append(f"Pump stop before cleanup failed: {exc}")
        try:
            self.driver.close()
        except Exception as exc:
            errors.append(f"Pump driver close failed: {exc}")
        if errors:
            raise RuntimeError("; ".join(errors))
        # Pump-driver review: this flag previously never reset,
        # so the pump connection-status UI (wired to this flag) would keep
        # showing "Connected" after a real cleanup/disconnect -- matches the
        # pattern Valve.cleanup() already gets right.
        self.initialized = False
