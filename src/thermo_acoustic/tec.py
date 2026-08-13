from __future__ import annotations

from dataclasses import dataclass, field
import math
import time
from typing import Callable, Protocol

from .hw_logging import run_with_timeout


TEC_TARGET_MIN_C = 0.0
TEC_TARGET_MAX_C = 80.0

# This integration is configured for two TEC-Family parameter instances.
# MeCom addresses a channel through ``parameter_instance``; the official
# protocol includes an instance-1 example for parameter 2010. Compatibility
# of instances 1 and 2 with the attached controller still requires an approved
# bench record; this is not a general device-discovery constant.
TEC_CHANNELS: tuple[int, ...] = (1, 2)

# Scope rule for the current implementation:
# WRITES are strictly limited to these 2 parameters, by name, never
# *_raw -- no other parameter is ever written anywhere in this file.
# READS are not limited to a fixed parameter list -- any parameter may be
# read (by name, still never *_raw) for diagnostics (e.g. investigating a
# real-hardware channel-addressing question), since a read cannot change
# device state. This file's own production read paths (read_status())
# still only read the 4 parameters below (104/105/1000, plus the write
# echo of 2010) -- the looser read rule exists for ad hoc diagnostic
# scripts outside this class, not because this class gained new read
# behavior. No PID, current/voltage limits/thresholds, sensor calibration,
# communication/address settings, or Auto Tuning is ever written anywhere
# in this file.
_MECOM_PARAM_OUTPUT_ENABLE = "Output Enable Status"  # ID 2010, write 0=OFF/1=Static ON
_MECOM_PARAM_TARGET_TEMP = "Target Object Temperature"  # ID 3000, write, degrees C -- name
# checked against the installed pyMeCom package's own
# mecom.commands.TEC_PARAMETERS table (the earlier "Target Object Temp"
# string was wrong and would have raised UnknownParameter on every real
# write).
_MECOM_WRITABLE_PARAMETER_NAMES = frozenset({_MECOM_PARAM_OUTPUT_ENABLE, _MECOM_PARAM_TARGET_TEMP})

_MECOM_PARAM_OBJECT_TEMP = "Object Temperature"  # ID 1000, read-only, degrees C
_MECOM_PARAM_DEVICE_STATUS = "Device Status"  # ID 104, read-only
_MECOM_PARAM_ERROR_NUMBER = "Error Number"  # ID 105, read-only


def validate_tec_target_temperature(temperature_c: float) -> float:
    """Validate the local application safety envelope for TEC setpoints.

    This is not a Meerstetter device-limit claim. The real vendor protocol
    document's only universal bound on parameter 3000 (Target Object Temp)
    is RNG_TEMP = -273..1000 C, a wire-format acceptance range, not a real
    per-device safety limit -- the device's actual safe range lives in
    Upper/Lower Error Threshold parameters (4010/4011), which are out of
    this integration's scope to read (2026-08-03 investigation). This
    conservative Python-side bound is kept instead.
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
    channel: int = 1
    current_temperature_c: float | None = None
    target_temperature_c: float | None = None
    output_stage_static_on: bool = False
    ready: bool = False
    error_state: str | None = None


class TecBackend(Protocol):
    def connect(self) -> None: ...

    def close(self) -> None: ...

    def read_status(self, channels: tuple[int, ...]) -> dict[int, TecStatus]: ...

    def set_output_stage_static_on(self, channel: int) -> None: ...

    def set_target_temperature(self, channel: int, temperature_c: float) -> None: ...

    def write_config(self) -> None: ...


class TecError(RuntimeError):
    pass


class TecAbortedError(TecError):
    pass


@dataclass(slots=True)
class SimulatedTecBackend:
    channels: tuple[int, ...] = TEC_CHANNELS
    connected: bool = False
    written: bool = False
    _current_temperature_c: dict[int, float] = field(default_factory=dict)
    _target_temperature_c: dict[int, float] = field(default_factory=dict)
    _output_stage_static_on: dict[int, bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for channel in self.channels:
            self._current_temperature_c.setdefault(channel, 25.0)
            self._target_temperature_c.setdefault(channel, 25.0)
            self._output_stage_static_on.setdefault(channel, False)

    def connect(self) -> None:
        self.connected = True

    def close(self) -> None:
        self.connected = False

    def read_status(self, channels: tuple[int, ...]) -> dict[int, TecStatus]:
        return {
            channel: TecStatus(
                channel=channel,
                current_temperature_c=self._current_temperature_c[channel],
                target_temperature_c=self._target_temperature_c[channel],
                output_stage_static_on=self._output_stage_static_on[channel],
                ready=self.connected and self._output_stage_static_on[channel],
                error_state=None,
            )
            for channel in channels
        }

    def set_output_stage_static_on(self, channel: int) -> None:
        self._output_stage_static_on[channel] = True

    def set_target_temperature(self, channel: int, temperature_c: float) -> None:
        self._target_temperature_c[channel] = float(temperature_c)

    def write_config(self) -> None:
        self.written = True
        # Simulated backend settles immediately after an explicit write.
        for channel in self.channels:
            self._current_temperature_c[channel] = self._target_temperature_c[channel]


@dataclass(slots=True)
class MeerstetterTecBackend:
    """Thin adapter for a Meerstetter/MeCom client supplied by integration code.

    The client (built by ``client_factory``, e.g. ``_real_tec_client_factory``
    below) is expected to expose the same channel-aware high-level methods
    as ``TecBackend`` -- this adapter forwards to it without inventing any
    hardware command of its own.
    """

    port: str | None = None
    client_factory: Callable[[str | None], object] | None = None
    client: object | None = None

    def connect(self) -> None:
        if self.client is None:
            if self.client_factory is None:
                raise TecError(
                    "No Meerstetter TEC client is configured; no device connection was attempted. "
                    "Confirm the controller model/firmware, MeCom Python package/API, and register map "
                    "before adding a reviewed real integration."
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

    def read_status(self, channels: tuple[int, ...]) -> dict[int, TecStatus]:
        client = self._client()
        read_status = getattr(client, "read_status", None)
        if not callable(read_status):
            raise TecError("Configured Meerstetter TEC client has no read_status() method.")
        result = read_status(channels)
        if not isinstance(result, dict):
            raise TecError(f"Unsupported TEC status response: {result!r}")
        normalized: dict[int, TecStatus] = {}
        for channel in channels:
            status = result.get(channel)
            if isinstance(status, TecStatus):
                normalized[channel] = status
            elif isinstance(status, dict):
                normalized[channel] = TecStatus(
                    channel=channel,
                    current_temperature_c=status.get("current_temperature_c"),
                    target_temperature_c=status.get("target_temperature_c"),
                    output_stage_static_on=bool(status.get("output_stage_static_on", False)),
                    ready=bool(status.get("ready", False)),
                    error_state=status.get("error_state"),
                )
            else:
                raise TecError(f"Unsupported TEC status response for channel {channel}: {status!r}")
        return normalized

    def set_output_stage_static_on(self, channel: int) -> None:
        action = getattr(self._client(), "set_output_stage_static_on", None)
        if not callable(action):
            raise TecError("Configured Meerstetter TEC client has no set_output_stage_static_on() method.")
        action(channel)

    def set_target_temperature(self, channel: int, temperature_c: float) -> None:
        action = getattr(self._client(), "set_target_temperature", None)
        if not callable(action):
            raise TecError("Configured Meerstetter TEC client has no set_target_temperature() method.")
        action(channel, float(temperature_c))

    def write_config(self) -> None:
        action = getattr(self._client(), "write_config", None)
        if not callable(action):
            raise TecError("Configured Meerstetter TEC client has no write_config() method.")
        action()

    def _client(self) -> object:
        if self.client is None:
            raise TecError("Meerstetter TEC backend is not connected.")
        return self.client


class _PyMeComTecClient:
    """Real MeCom client, backed by pyMeCom's MeComSerial
    (github.com/meerstetter/pyMeCom, MIT license, pinned to tag v1.1 in
    pyproject.toml/requirements-exp_ctrl.txt).

    Scope, enforced by construction (updated 2026-08-04): this class's own
    read_status()/set_output_stage_static_on()/set_target_temperature()
    call ONLY get_parameter()/set_parameter() by name, for exactly the 4
    parameter names this class currently reads -- 2010 Output Enable
    Status, 1000 Object Temperature, 104 Device Status, 105 Error Number
    -- and WRITES are strictly limited to exactly 2 parameter names, by
    name, never via get_parameter_raw()/set_parameter_raw() (pyMeCom's
    own bypass of its built-in parameter allow-list) -- 2010 Output
    Enable Status and 3000 Target Object Temperature
    (_MECOM_WRITABLE_PARAMETER_NAMES above). Reads are not restricted to
    this class's own 4 parameters at the project level -- any parameter
    may be read elsewhere (e.g. an ad hoc diagnostic script) for
    real-hardware investigation, since a read cannot change device state;
    this class itself just doesn't happen to read anything beyond what it
    needs. No PID, current/voltage limits/thresholds, sensor calibration,
    communication/address settings, or Auto Tuning is ever WRITTEN
    anywhere in this file.

    read_status() takes all configured channels and returns
    dict[channel, TecStatus]. Device Status/Error Number are read once at
    instance 1 because the official protocol classifies them as Common Product
    Parameters; temperature and output parameters are read per configured
    channel. Compatibility with the attached model/firmware remains a bench
    approval item.

    `mecom` is imported lazily inside connect(), not at module import time
    -- matching this project's own established convention for vendor SDKs
    used only on the real-hardware path (qmix_backend.py's _load_sdk(),
    thorlabs_piezo.py's lazy `import clr`), so a machine without pyMeCom
    installed can still run this app in simulated mode.
    """

    def __init__(self, port: str | None, baudrate: int = 57600, timeout_s: float = 1.0) -> None:
        self._port = port
        self._baudrate = baudrate
        self._timeout_s = timeout_s
        self._mc: object | None = None

    def connect(self) -> None:
        from mecom import MeComSerial

        if not self._port:
            raise TecError("MeerstetterTecBackend has no port configured; cannot connect a real TEC client.")
        self._mc = MeComSerial(
            serialport=self._port,
            timeout=self._timeout_s,
            baudrate=self._baudrate,
            metype="TEC",
        )

    def close(self) -> None:
        if self._mc is None:
            return
        stop = getattr(self._mc, "stop", None)
        if callable(stop):
            stop()
        self._mc = None

    def read_status(self, channels: tuple[int, ...]) -> dict[int, TecStatus]:
        mc = self._require_client()
        # Device Status (104) and Error Number (105) are Common Product
        # Parameters in the official protocol, separate from the per-instance
        # Temperature Controller parameters. Read them once at instance 1 and
        # apply the result to every requested channel. The attached controller's
        # model/firmware compatibility is still a bench approval item.
        device_status_id = int(mc.get_parameter(parameter_name=_MECOM_PARAM_DEVICE_STATUS, parameter_instance=1))
        # Matches pyMeCom's own status() decode and the real protocol
        # document's Device Status table exactly (0 Init / 1 Ready / 2 Run /
        # 3 Error / 4 Bootloader / 5 Device will Reset within next 200ms).
        error_state: str | None = None
        if device_status_id == 3:
            error_number = mc.get_parameter(parameter_name=_MECOM_PARAM_ERROR_NUMBER, parameter_instance=1)
            error_state = f"Device Status=Error, Error Number={error_number}"

        result: dict[int, TecStatus] = {}
        for channel in channels:
            current_temperature_c = float(mc.get_parameter(parameter_name=_MECOM_PARAM_OBJECT_TEMP, parameter_instance=channel))
            output_enabled = bool(mc.get_parameter(parameter_name=_MECOM_PARAM_OUTPUT_ENABLE, parameter_instance=channel))
            result[channel] = TecStatus(
                channel=channel,
                current_temperature_c=current_temperature_c,
                target_temperature_c=None,  # not re-read from the device; the caller already knows what it set
                output_stage_static_on=output_enabled,
                ready=device_status_id in (1, 2) and output_enabled,
                error_state=error_state,
            )
        return result

    def set_output_stage_static_on(self, channel: int) -> None:
        mc = self._require_client()
        mc.set_parameter(value=1, parameter_name=_MECOM_PARAM_OUTPUT_ENABLE, parameter_instance=channel)

    def set_target_temperature(self, channel: int, temperature_c: float) -> None:
        mc = self._require_client()
        mc.set_parameter(value=float(temperature_c), parameter_name=_MECOM_PARAM_TARGET_TEMP, parameter_instance=channel)

    def write_config(self) -> None:
        # Deliberate RAM-only no-op, not the vendor's flash-persistence
        # "Write Config" operation. MeCom VS (parameter set) commands apply
        # the requested values in RAM; this integration re-applies its target
        # each session and intentionally does not issue a flash save. Whether
        # persistent configuration should ever be supported is a separate
        # reviewed policy decision, not behavior implied by this method name.
        # A separate unresolved discrepancy remains between pyMeCom's static
        # parameter list (which still includes ID 108 "Save Data to
        # Flash") and the specific protocol document revision fetched
        # during the 2026-08-03 investigation (which did not document ID
        # 108 at all) -- deliberately not resolved by guessing, since this
        # no-op sidesteps needing to.
        return

    def _require_client(self):
        if self._mc is None:
            raise TecError("_PyMeComTecClient is not connected.")
        return self._mc


def _real_tec_client_factory(port: str | None) -> _PyMeComTecClient:
    return _PyMeComTecClient(port)


@dataclass(slots=True)
class TecController:
    enabled: bool = False
    simulate: bool = True
    backend: TecBackend | None = None
    initialized: bool = False
    # Real device is a 2-channel unit (TEC_CHANNELS). Every public method
    # below defaults to operating on all of these channels when called
    # without an explicit `channels` argument -- matching this project's
    # current behavior (both channels get the same target temperature) --
    # while still accepting an explicit, narrower `channels` tuple so a
    # future caller can drive channels independently (e.g.
    # apply_static_setpoint(t1, channels=(1,)) then
    # apply_static_setpoint(t2, channels=(2,))) without any further changes
    # to this class. Existing callers (Application.run_temperature_series())
    # already call these methods with no channel argument and are
    # unaffected by this change.
    channels: tuple[int, ...] = TEC_CHANNELS
    initialized_via_real_port: bool = False
    last_status: dict[int, TecStatus] = field(default_factory=dict)
    cleanup_timeout_s: float = 5.0

    def _backend(self) -> TecBackend:
        if self.backend is None:
            self.backend = SimulatedTecBackend(channels=self.channels) if self.simulate else MeerstetterTecBackend()
        return self.backend

    def _channels_or_default(self, channels: tuple[int, ...] | None) -> tuple[int, ...]:
        return channels if channels is not None else self.channels

    def initialize(self) -> None:
        if not self.enabled:
            return
        backend = self._backend()
        try:
            backend.connect()
            status = backend.read_status(self.channels)
        except Exception as exc:
            self.initialized = False
            cleanup_error = run_with_timeout(backend.close, "TEC failed-initialize cleanup", self.cleanup_timeout_s)
            if cleanup_error is not None:
                raise TecError(
                    f"TEC initialize failed: {exc}; cleanup after the failed initialize also failed: "
                    f"{cleanup_error}"
                ) from exc
            raise
        self.initialized = True
        self.last_status = status

    def cleanup(self) -> None:
        if self.backend is not None:
            cleanup_error = run_with_timeout(self.backend.close, "TEC cleanup", self.cleanup_timeout_s)
            if cleanup_error is not None:
                raise TecError(cleanup_error)
        self.initialized = False

    def read_status(self, channels: tuple[int, ...] | None = None) -> dict[int, TecStatus]:
        channels = self._channels_or_default(channels)
        if not self.enabled:
            self.last_status = {channel: TecStatus(channel=channel) for channel in channels}
            return self.last_status
        backend = self._backend()
        self.last_status = backend.read_status(channels)
        return self.last_status

    def apply_static_setpoint(
        self, temperature_c: float | dict[int, float], channels: tuple[int, ...] | None = None
    ) -> dict[int, TecStatus]:
        # A plain float broadcasts the same target to every channel in
        # `channels` (today's only usage, e.g. application.py's single
        # "Temperature points (C)" field). A dict[int, float] gives each
        # channel its own independent target in one call -- added
        # (2026-08-04) for unlocked dual-channel temperature scans, where
        # both channels must move to their own target together, not one
        # after the other.
        targets = self._resolve_targets(temperature_c, channels)
        channels = tuple(targets)
        if not self.enabled:
            result = {
                channel: TecStatus(channel=channel, target_temperature_c=target, ready=True)
                for channel, target in targets.items()
            }
            self.last_status = result
            return result
        backend = self._backend()
        for channel in channels:
            backend.set_output_stage_static_on(channel)
            backend.set_target_temperature(channel, targets[channel])
        backend.write_config()
        result = backend.read_status(channels)
        self.last_status = result
        for channel, status in result.items():
            if status.error_state:
                raise TecError(
                    f"TEC channel {channel} reported error after setting {targets[channel]:.3f} C: {status.error_state}"
                )
        return result

    def _resolve_targets(
        self, temperature_c: float | dict[int, float], channels: tuple[int, ...] | None
    ) -> dict[int, float]:
        if isinstance(temperature_c, dict):
            targets = {channel: validate_tec_target_temperature(value) for channel, value in temperature_c.items()}
            resolved_channels = self._channels_or_default(channels)
            if set(targets) != set(resolved_channels):
                raise ValueError(
                    f"Per-channel temperature dict keys {sorted(targets)} must exactly match "
                    f"channels {sorted(resolved_channels)}."
                )
            # Preserve resolved_channels' order, not the dict's insertion order.
            return {channel: targets[channel] for channel in resolved_channels}
        single_target = validate_tec_target_temperature(temperature_c)
        resolved_channels = self._channels_or_default(channels)
        return {channel: single_target for channel in resolved_channels}

    def wait_until_stable(
        self,
        target_temperature_c: float | dict[int, float],
        *,
        tolerance_c: float,
        min_settle_s: float,
        max_wait_s: float,
        poll_interval_s: float = 1.0,
        channels: tuple[int, ...] | None = None,
        should_abort: Callable[[], bool] | None = None,
    ) -> dict[int, TecStatus]:
        # See apply_static_setpoint()'s docstring note: a plain float
        # broadcasts one target to every channel (today's only usage); a
        # dict[int, float] lets each channel poll toward its own target in
        # one call, genuinely simultaneously -- not one channel's full
        # wait followed by the other's.
        targets = self._resolve_targets(target_temperature_c, channels)
        channels = tuple(targets)
        targets_label = ", ".join(f"ch{channel}={value:.3f}C" for channel, value in targets.items())
        if not self.enabled:
            return {
                channel: TecStatus(
                    channel=channel,
                    current_temperature_c=target,
                    target_temperature_c=target,
                    output_stage_static_on=False,
                    ready=True,
                )
                for channel, target in targets.items()
            }
        deadline = time.monotonic() + max(max_wait_s, 0.0)
        stable_since: float | None = None
        last_status = self.read_status(channels)
        while True:
            if should_abort is not None and should_abort():
                raise TecAbortedError(f"TEC stabilization aborted while waiting for {targets_label}.")
            for channel, status in last_status.items():
                if status.error_state:
                    raise TecError(f"TEC channel {channel} reported error while waiting for stability: {status.error_state}")
            all_within_tolerance = all(
                status.current_temperature_c is not None
                and abs(float(status.current_temperature_c) - targets[channel]) <= tolerance_c
                and status.ready
                for channel, status in last_status.items()
            )
            if all_within_tolerance:
                if stable_since is None:
                    stable_since = time.monotonic()
                if time.monotonic() - stable_since >= max(min_settle_s, 0.0):
                    return last_status
            else:
                stable_since = None
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"TEC did not stabilize at {targets_label} within {max_wait_s:.1f}s "
                    f"(last status: {last_status})."
                )
            self._sleep_with_abort(max(poll_interval_s, 0.0), should_abort)
            last_status = self.read_status(channels)

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
