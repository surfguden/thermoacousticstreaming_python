"""LabVIEW-migration-parity reference material -- not part of the
production runtime path.

Each function/class here maps to a specific original LabVIEW VISA
serial-configuration VI (see `labview_ports.py`'s `python_name=`
entries, e.g. `visa_configure_serial_port_instr`). This module exists
to prove migration completeness/traceability -- evidence that no
original LabVIEW capability was silently dropped during the port --
even though the actual production serial path
(`SerialTextCommandBackend` in `instruments.py`) hardcodes its own
baud/timeout parameters directly instead of building a `VisaSerialConfig`
through this layer.

Confirmed (code-health audit, Session 57) to have zero cross-references
from any other file in `src/thermo_acoustic/` or from `tools/`; only
referenced by its own unit tests in `tests/test_application.py`. This
is intentional, not dead code awaiting cleanup -- do not remove or
flag this module without an explicit decision to do so. See
`docs/known_open_items.md`'s "LabVIEW-migration-parity scaffolding"
note for the cross-reference.
"""

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
