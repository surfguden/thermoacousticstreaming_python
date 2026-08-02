from __future__ import annotations

from dataclasses import dataclass, field
import math
import time
from typing import Callable, Protocol


TEC_TARGET_MIN_C = 0.0
TEC_TARGET_MAX_C = 80.0


def validate_tec_target_temperature(temperature_c: float) -> float:
    """Validate the local application safety envelope for TEC setpoints.

    This is not a Meerstetter device-limit claim. The real MeCom register
    mapping remains unresolved in this repository, so keep a conservative
    Python-side bound here before any future reviewed real backend receives a
    target.
    """

    value = float(temperature_c)
    if not math.isfinite(value):
        raise ValueError(f"TEC target temperature must be finite, got {temperature_c!r}.")
    if not (TEC_TARGET_MIN_C <= value <= TEC_TARGET_MAX_C):
        raise ValueError(
            f"TEC target temperature {value:.3f} C is outside the local safety range "
            f"[{TEC_TARGET_MIN_C:.1f}, {TEC_TARGET_MAX_C:.1f}] C."
        )
    return value


@dataclass(frozen=True, slots=True)
class TecStatus:
    current_temperature_c: float | None = None
    target_temperature_c: float | None = None
    output_stage_static_on: bool = False
    ready: bool = False
    error_state: str | None = None


class TecBackend(Protocol):
    def connect(self) -> None: ...

    def close(self) -> None: ...

    def read_status(self) -> TecStatus: ...

    def set_output_stage_static_on(self) -> None: ...

    def set_target_temperature(self, temperature_c: float) -> None: ...

    def write_config(self) -> None: ...


class TecError(RuntimeError):
    pass


class TecAbortedError(TecError):
    pass


@dataclass(slots=True)
class SimulatedTecBackend:
    current_temperature_c: float = 25.0
    target_temperature_c: float = 25.0
    connected: bool = False
    output_stage_static_on: bool = False
    written: bool = False

    def connect(self) -> None:
        self.connected = True

    def close(self) -> None:
        self.connected = False

    def read_status(self) -> TecStatus:
        return TecStatus(
            current_temperature_c=self.current_temperature_c,
            target_temperature_c=self.target_temperature_c,
            output_stage_static_on=self.output_stage_static_on,
            ready=self.connected and self.output_stage_static_on,
            error_state=None,
        )

    def set_output_stage_static_on(self) -> None:
        self.output_stage_static_on = True

    def set_target_temperature(self, temperature_c: float) -> None:
        self.target_temperature_c = float(temperature_c)

    def write_config(self) -> None:
        self.written = True
        # Simulated backend settles immediately after an explicit write.
        self.current_temperature_c = self.target_temperature_c


@dataclass(slots=True)
class MeerstetterTecBackend:
    """Thin adapter for a Meerstetter/MeCom client supplied by integration code.

    The repository does not currently contain a Meerstetter SDK wrapper or a
    confirmed register map. To avoid inventing hardware commands, this adapter
    accepts a client object/factory that already exposes the high-level methods
    below. A future real-hardware integration can bind those methods to the
    exact MeCom registers verified for this controller.

    The shipped UI/factory intentionally does not supply ``client_factory``.
    Selecting real TEC there therefore fails before any connection attempt;
    that is an unresolved-safety boundary, not a usable real integration path.
    """

    port: str | None = None
    client_factory: Callable[[str | None], object] | None = None
    client: object | None = None

    def connect(self) -> None:
        if self.client is None:
            if self.client_factory is None:
                raise TecError(
                    "No Meerstetter TEC client is configured. The shipped UI/factory cannot supply one, "
                    "so real TEC is unavailable and no device connection was attempted. Confirm the "
                    "controller model/firmware, MeCom Python package/API, and register map before "
                    "adding a reviewed real integration."
                )
            self.client = self.client_factory(self.port)
        connect = getattr(self.client, "connect", None)
        if callable(connect):
            connect()

    def close(self) -> None:
        if self.client is None:
            return
        close = getattr(self.client, "close", None)
        if callable(close):
            close()
        self.client = None

    def read_status(self) -> TecStatus:
        client = self._client()
        read_status = getattr(client, "read_status", None)
        if not callable(read_status):
            raise TecError("Configured Meerstetter TEC client has no read_status() method.")
        status = read_status()
        if isinstance(status, TecStatus):
            return status
        if isinstance(status, dict):
            return TecStatus(
                current_temperature_c=status.get("current_temperature_c"),
                target_temperature_c=status.get("target_temperature_c"),
                output_stage_static_on=bool(status.get("output_stage_static_on", False)),
                ready=bool(status.get("ready", False)),
                error_state=status.get("error_state"),
            )
        raise TecError(f"Unsupported TEC status response: {status!r}")

    def set_output_stage_static_on(self) -> None:
        action = getattr(self._client(), "set_output_stage_static_on", None)
        if not callable(action):
            raise TecError("Configured Meerstetter TEC client has no set_output_stage_static_on() method.")
        action()

    def set_target_temperature(self, temperature_c: float) -> None:
        action = getattr(self._client(), "set_target_temperature", None)
        if not callable(action):
            raise TecError("Configured Meerstetter TEC client has no set_target_temperature() method.")
        action(float(temperature_c))

    def write_config(self) -> None:
        action = getattr(self._client(), "write_config", None)
        if not callable(action):
            raise TecError("Configured Meerstetter TEC client has no write_config() method.")
        action()

    def _client(self) -> object:
        if self.client is None:
            raise TecError("Meerstetter TEC backend is not connected.")
        return self.client


@dataclass(slots=True)
class TecController:
    enabled: bool = False
    simulate: bool = True
    backend: TecBackend | None = None
    initialized: bool = False
    last_status: TecStatus = field(default_factory=TecStatus)

    def _backend(self) -> TecBackend:
        if self.backend is None:
            self.backend = SimulatedTecBackend() if self.simulate else MeerstetterTecBackend()
        return self.backend

    def initialize(self) -> None:
        if not self.enabled:
            return
        backend = self._backend()
        try:
            backend.connect()
            status = backend.read_status()
        except Exception as exc:
            self.initialized = False
            try:
                backend.close()
            except Exception as cleanup_exc:
                raise TecError(
                    f"TEC initialize failed, and cleanup after the failed initialize also failed: {cleanup_exc}"
                ) from exc
            raise
        self.initialized = True
        self.last_status = status

    def cleanup(self) -> None:
        if self.backend is not None:
            self.backend.close()
        self.initialized = False

    def read_status(self) -> TecStatus:
        if not self.enabled:
            self.last_status = TecStatus()
            return self.last_status
        self.last_status = self._backend().read_status()
        return self.last_status

    def apply_static_setpoint(self, temperature_c: float) -> TecStatus:
        temperature_c = validate_tec_target_temperature(temperature_c)
        if not self.enabled:
            return TecStatus(target_temperature_c=temperature_c, ready=True)
        backend = self._backend()
        backend.set_output_stage_static_on()
        backend.set_target_temperature(temperature_c)
        backend.write_config()
        self.last_status = backend.read_status()
        if self.last_status.error_state:
            raise TecError(f"TEC reported error after setting {temperature_c:.3f} C: {self.last_status.error_state}")
        return self.last_status

    def wait_until_stable(
        self,
        target_temperature_c: float,
        *,
        tolerance_c: float,
        min_settle_s: float,
        max_wait_s: float,
        poll_interval_s: float = 1.0,
        should_abort: Callable[[], bool] | None = None,
    ) -> TecStatus:
        target_temperature_c = validate_tec_target_temperature(target_temperature_c)
        if not self.enabled:
            return TecStatus(
                current_temperature_c=target_temperature_c,
                target_temperature_c=target_temperature_c,
                output_stage_static_on=False,
                ready=True,
            )
        deadline = time.monotonic() + max(max_wait_s, 0.0)
        stable_since: float | None = None
        last_status = self.read_status()
        while True:
            if should_abort is not None and should_abort():
                raise TecAbortedError(f"TEC stabilization aborted while waiting for {target_temperature_c:.3f} C.")
            if last_status.error_state:
                raise TecError(f"TEC reported error while waiting for stability: {last_status.error_state}")
            current = last_status.current_temperature_c
            within_tolerance = current is not None and abs(float(current) - float(target_temperature_c)) <= tolerance_c
            if within_tolerance and last_status.ready:
                if stable_since is None:
                    stable_since = time.monotonic()
                if time.monotonic() - stable_since >= max(min_settle_s, 0.0):
                    return last_status
            else:
                stable_since = None
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"TEC did not stabilize at {target_temperature_c:.3f} C within {max_wait_s:.1f}s "
                    f"(last status: {last_status})."
                )
            self._sleep_with_abort(max(poll_interval_s, 0.0), should_abort)
            last_status = self.read_status()

    @staticmethod
    def _sleep_with_abort(duration_s: float, should_abort: Callable[[], bool] | None) -> None:
        deadline = time.monotonic() + duration_s
        while True:
            if should_abort is not None and should_abort():
                raise TecAbortedError("TEC stabilization aborted during wait.")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(remaining, 0.1))
