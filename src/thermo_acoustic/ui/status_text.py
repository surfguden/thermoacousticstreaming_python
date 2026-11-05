"""One wording for device state, built from the typed status and readback (never from other labels).

ERROR in this application means a connected device whose last operation failed, not a lost link, so
it counts as connected here. Header, connection table, folded summaries, device pages and the run
monitor all use these functions.
"""

from __future__ import annotations

from ..domain.models import ConnectionState, DeviceStatus, PumpReadback, TecReadback, ValveReadback

GREEN, RED, GREY = "#2e7d32", "#b71c1c", "#616161"


def is_connected(status: DeviceStatus | None) -> bool:
    return status is not None and status.connection in {ConnectionState.CONNECTED, ConnectionState.ERROR}


def connection_phrase(status: DeviceStatus | None) -> str:
    if status is None or status.connection is ConnectionState.DISCONNECTED:
        return "not connected"
    if status.connection is ConnectionState.ERROR:
        return "connected · last operation failed"
    return "connected" + (" (fault)" if status.fault else "")


def connection_color(status: DeviceStatus | None) -> str:
    if status is None or status.connection is ConnectionState.DISCONNECTED:
        return GREY
    return RED if status.connection is ConnectionState.ERROR or status.fault else GREEN


def format_frequency(hz: object) -> str:
    """A frequency as Hz, kHz or MHz for reading. Display only: the value is divided by a power of ten and
    printed with enough digits (12 significant) that no entered frequency is visibly rounded."""
    if not isinstance(hz, (int, float)) or isinstance(hz, bool):
        return "unknown" if hz is None else str(hz)
    magnitude = abs(hz)
    value, unit = (hz / 1e6, "MHz") if magnitude >= 1e6 else (hz / 1e3, "kHz") if magnitude >= 1e3 else (hz, "Hz")
    return f"{value:.12g} {unit}"


def _value(value: object, unit: str = "") -> str:
    return "unknown" if value is None else f"{value:g}{unit}" if isinstance(value, (int, float)) else str(value)


def valve_summary(readback: object) -> str:
    """Requested and confirmed position are different facts; ready says whether the valve reports settled."""
    if not isinstance(readback, ValveReadback):
        return "no readback"
    requested = "—" if readback.requested_position is None else str(readback.requested_position)
    confirmed = "unknown" if readback.confirmed_position is None else str(readback.confirmed_position)
    ready = "—" if readback.ready is None else ("yes" if readback.ready else "no")
    note = f" · {readback.status_note}" if readback.status_note else ""
    return f"requested position {requested} · confirmed position {confirmed} · ready {ready}{note}"


def ad2_channels_configured(readback: object) -> str:
    """The channels as configured (enabled or disabled, setting). A configuration is not a running output."""
    channels = getattr(readback, "waveform_channels", ()) if readback is not None else ()
    return ", ".join(
        f"CH{channel.channel_index + 1} " + (f"enabled {format_frequency(channel.frequency_hz)}/{channel.amplitude_v:g} V"
                                             if channel.enabled else "disabled")
        for channel in channels) or "none configured"


def ad2_outputs_summary(readback: object) -> str:
    """What the AD2 reports about its outputs. Whether the waveform generator is running is one reported flag
    for the instrument; the channel list is the configuration, not a per-channel live state."""
    if readback is None:
        return "no readback"
    channels = getattr(readback, "waveform_channels", ())
    configured = ad2_channels_configured(readback)
    if getattr(readback, "waveform_running", False):
        wfg = f"waveform generator running (configured: {configured})"
    elif channels:
        wfg = f"waveform generator not running (configured: {configured})"
    else:
        wfg = "waveform generator idle (nothing configured)"
    digital = ("running" if getattr(readback, "digital_output_running", False)
               else "configured, not running" if getattr(readback, "digital_output_configured", False) else "idle")
    return f"{wfg} · digital output {digital}"


def pump_summary(readback: object) -> str:
    units = readback.units if isinstance(readback, PumpReadback) else ()
    return " · ".join(
        f"unit {unit.unit_index + 1}: " + ("level unknown" if unit.fill_level_ml is None else f"{unit.fill_level_ml:.3g} mL")
        + (" of " + f"{unit.max_volume_ml:g}" if unit.max_volume_ml else "")
        + (", pumping" if unit.is_pumping else "") for unit in units) or "no pump units"


def tec_summary(readback: object) -> str:
    channels = getattr(readback, "channels", ()) if isinstance(readback, TecReadback) else ()
    return " · ".join(
        f"ch{item.channel}: now " + ("unknown" if item.current_temperature_c is None else f"{item.current_temperature_c:.2f} °C")
        + " · reported target " + ("none" if item.target_temperature_c is None else f"{item.target_temperature_c:g} °C")
        + (" · output on" if item.output_enabled else " · output off") for item in channels) or "no channel readback"


# Same parameter names as the compiled plan; anything not listed is shown as key=value.
_PARAMETER_LABELS = (("frequency_hz", "frequency", " Hz"), ("amplitude_v", "amplitude", " V"),
                     ("exposure_ms", "exposure", " ms"), ("sweep_width_hz", "sweep width", " Hz"),
                     ("temperature_c", "temperature", " °C"))
_FREQUENCY_KEYS = {"frequency_hz", "sweep_width_hz"}  # shown as Hz/kHz/MHz


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def sweep_summary(parameters: dict | None, plan: dict | None = None, *, say_requested: bool = True) -> str | None:
    """The in-experiment frequency sweep of one experiment, from the parameters stored for it and, when known, the
    plan's own statement of it. A missing mode or period is said to be unknown / not recorded; nothing is
    filled in from any form. None when the parameters say nothing about a sweep."""
    parameters = parameters or {}
    width, center = parameters.get("sweep_width_hz"), parameters.get("frequency_hz")
    flag = (plan or {}).get("sweep_enabled")
    if flag is False or width == "NaN":
        return "sweep off"
    if not _is_number(width):
        return "sweep on (width not stated)" if flag else None
    band = (f" ({format_frequency(center - width / 2)} … {format_frequency(center + width / 2)})"
            if _is_number(center) else "")
    period = (plan or {}).get("sweep_period_ms")
    if flag and _is_number(period):
        timing = f"{period:g} ms triangle" + (" (requested)" if say_requested else "")
    elif flag:
        timing = "period not stated"
    else:
        timing = "period not recorded"
    return f"sweep full width {format_frequency(width)}{band}, {timing}"


def describe_condition(parameters: dict | None, plan: dict | None = None) -> str:
    """One experiment's own parameters as stored; `plan` (the running plan's facts) only adds what that plan states
    about the sweep. Nothing is derived from any form."""
    if not parameters:
        return "—"
    pieces = []
    known = set()
    for key, label, unit in _PARAMETER_LABELS:
        if key in parameters:
            known.add(key)
            if key == "sweep_width_hz":
                piece = sweep_summary(parameters, plan)
                if piece:
                    pieces.append(piece)
            elif parameters[key] != "NaN":  # the plan's marker for a disabled temperature axis
                pieces.append(f"{label} {format_frequency(parameters[key]) if key in _FREQUENCY_KEYS else _value(parameters[key], unit)}")
    pieces.extend(f"{key}={_value(value)}" for key, value in parameters.items() if key not in known)
    return " · ".join(pieces) if pieces else "—"
