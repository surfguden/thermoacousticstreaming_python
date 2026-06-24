from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class VisaSerialConfig:
    resource_name: str
    baud_rate: int = 9600
    data_bits: int = 8
    parity: str = "none"
    stop_bits: float = 1.0
    flow_control: str = "none"
    timeout_ms: int = 10_000


def visa_configure_serial_port(
    resource_name: str,
    *,
    baud_rate: int = 9600,
    data_bits: int = 8,
    parity: str = "none",
    stop_bits: float = 1.0,
    flow_control: str = "none",
    timeout_ms: int = 10_000,
) -> VisaSerialConfig:
    return VisaSerialConfig(
        resource_name=resource_name,
        baud_rate=baud_rate,
        data_bits=data_bits,
        parity=parity,
        stop_bits=stop_bits,
        flow_control=flow_control,
        timeout_ms=timeout_ms,
    )


def visa_configure_serial_port_instr(resource_name: str, **kwargs: object) -> VisaSerialConfig:
    return visa_configure_serial_port(resource_name, **kwargs)


def visa_configure_serial_port_serial_instr(resource_name: str, **kwargs: object) -> VisaSerialConfig:
    return visa_configure_serial_port(resource_name, **kwargs)
