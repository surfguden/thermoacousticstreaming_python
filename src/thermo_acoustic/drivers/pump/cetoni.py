from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

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

@dataclass(slots=True)
class RegloPumpControl:
    running: bool = False
    direction: str = "clockwise"
    speed: float = 0.0
    volume_ml: float | None = None

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
    # means "a physical reference move was confirmed". The retired transitional
    # UI pump connection-status row used this, not `referenced`, matching the same
    # pattern the Valve row already uses (`valve.initialized`).
    initialized: bool = False
    # Used by refill() when simulating (backend=None) to fill to the
    # syringe's actual configured capacity instead of an arbitrary
    # hardcoded value. Defaults to 1.0 for backward compatibility with
    # existing simulated-mode callers that never set this explicitly --
    # not a claim that 1.0 mL is a realistic syringe capacity.
    max_volume_ml: float = 1.0
    # UNKNOWN (None) until a real configure_syringe() call establishes it --
    # deliberately separate from max_volume_ml above, which many existing
    # callers/tests set directly as an arbitrary simulated-mode bookkeeping
    # value with no real capacity meaning. Real-shakedown finding
    # (2026-09-06): this is the field Application.flush()'s stale-fill-level
    # guard checks, so a test or a simulated pump that never configured a
    # real syringe is never second-guessed by it -- only an ACTUAL
    # QmixPumpBackend.configure_syringe() success sets this, from the
    # backend's own fresh get_volume_max() readback.
    known_capacity_ml: float | None = None

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
            # Real-shakedown finding (2026-09-06): QmixPumpBackend.
            # configure_syringe() already re-queries get_volume_max() into
            # ITS OWN self.max_volume_ml after a successful geometry change;
            # nothing previously copied that fresh ceiling up to this
            # canonical (UNKNOWN-until-established) field, so
            # Application.flush()'s stale-fill-level guard had no capacity
            # to check fill_level against. Same "single canonical place"
            # reasoning as sync_fill_level() above.
            backend_max_volume_ml = getattr(self.backend, "max_volume_ml", None)
            if backend_max_volume_ml is not None:
                self.known_capacity_ml = float(backend_max_volume_ml)
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
        # Checkpoint-S-closure review finding (2026-09-07): previously
        # `self.stop()` was not guarded, so a raising stop() (e.g. a real
        # Qmix fault surfacing on close, or the concurrent-Stop race tracked
        # as UI-PUMP-STOP-THREAD-SAFETY-001) skipped `self.backend.close()`
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
        if self.backend is not None:
            try:
                self.backend.close()
            except Exception as exc:
                errors.append(f"Pump backend close failed: {exc}")
        if errors:
            raise RuntimeError("; ".join(errors))
        # Pump-driver review: this flag previously never reset,
        # so the pump connection-status UI (wired to this flag) would keep
        # showing "Connected" after a real cleanup/disconnect -- matches the
        # pattern Valve.cleanup() already gets right.
        self.initialized = False
