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


def ad2_outputs_summary(readback: object) -> str:
    """What the AD2 reports its waveform and digital outputs are doing (a report, not the experiment's plan)."""
    if readback is None:
        return "no readback"
    channels = getattr(readback, "waveform_channels", ())
    channel_text = ", ".join(
        f"CH{channel.channel_index + 1} {'on' if channel.enabled else 'off'} "
        f"{channel.frequency_hz:g} Hz/{channel.amplitude_v:g} V" for channel in channels) or "not configured"
    wfg = "running" if getattr(readback, "waveform_running", False) else "configured" if channels else "idle"
    digital = ("running" if getattr(readback, "digital_output_running", False)
               else "configured" if getattr(readback, "digital_output_configured", False) else "idle")
    return f"WFG {wfg} ({channel_text}) · digital output {digital}"


def pump_summary(readback: object) -> str:
    units = readback.units if isinstance(readback, PumpReadback) else ()
    return " · ".join(
        f"pump {unit.unit_index + 1}: " + ("level unknown" if unit.fill_level_ml is None else f"{unit.fill_level_ml:.3g} mL")
        + (" of " + f"{unit.max_volume_ml:g}" if unit.max_volume_ml else "")
        + (", pumping" if unit.is_pumping else "") for unit in units) or "no pump units"


def tec_summary(readback: object) -> str:
    channels = getattr(readback, "channels", ()) if isinstance(readback, TecReadback) else ()
    return " · ".join(
        f"ch{item.channel}: now " + ("unknown" if item.current_temperature_c is None else f"{item.current_temperature_c:.2f} °C")
        + " · reported target " + ("none" if item.target_temperature_c is None else f"{item.target_temperature_c:g} °C")
        + (" · output on" if item.output_enabled else " · output off") for item in channels) or "no channel readback"
