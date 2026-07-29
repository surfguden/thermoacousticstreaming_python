from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
UI_STATE_PATH = ROOT / ".thermo_acoustic_ui.json"
DEFAULT_PORTS = {
    "MX valve default": "COM5",  # real-hardware-confirmed; COM6 was a standing documentation error
    "Prior Z-stage default": "COM7",
}


def print_step(message: str) -> None:
    print(f"[serial-discovery] {message}", flush=True)


def print_value(label: str, value: object) -> None:
    print(f"  {label}: {value}", flush=True)


def import_pyserial() -> tuple[Any, Any]:
    print_step("importing pyserial")
    import serial
    from serial.tools import list_ports

    print_value("serial module", getattr(serial, "__file__", "<unknown>"))
    print_value("list_ports module", getattr(list_ports, "__file__", "<unknown>"))
    return serial, list_ports


def load_configured_ports() -> dict[str, str]:
    configured = dict(DEFAULT_PORTS)
    print_step(f"checking persisted UI state: {UI_STATE_PATH}")
    if not UI_STATE_PATH.exists():
        print_step("persisted UI state not found; using defaults only")
        return configured

    try:
        data = json.loads(UI_STATE_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        print_step(f"warning: could not read persisted UI state: {exc}")
        return configured

    for key, label in (
        ("valve_resource", "persisted valve_resource"),
        ("prior_resource", "persisted prior_resource"),
    ):
        value = data.get(key)
        if value:
            configured[label] = str(value)
    return configured


def port_to_dict(port: Any) -> dict[str, object]:
    return {
        "device": getattr(port, "device", None),
        "name": getattr(port, "name", None),
        "description": getattr(port, "description", None),
        "hwid": getattr(port, "hwid", None),
        "manufacturer": getattr(port, "manufacturer", None),
        "product": getattr(port, "product", None),
        "serial_number": getattr(port, "serial_number", None),
        "vid": getattr(port, "vid", None),
        "pid": getattr(port, "pid", None),
    }


def list_serial_ports(list_ports: Any) -> list[Any]:
    print_step("listing available serial ports")
    ports = sorted(list_ports.comports(), key=lambda item: str(getattr(item, "device", "")))
    print_value("port count", len(ports))
    for index, port in enumerate(ports):
        print_step(f"port {index}")
        for key, value in port_to_dict(port).items():
            print_value(key, value)
    return ports


def compare_configured_ports(ports: list[Any], configured: dict[str, str], selected_port: str | None) -> None:
    available = {str(getattr(port, "device", "")).upper(): port for port in ports}

    print_step("configured/default port comparison")
    for label, port_name in configured.items():
        normalized = port_name.upper()
        state = "present" if normalized in available else "not present"
        print_value(f"{label} ({port_name})", state)

    if selected_port:
        state = "present" if selected_port.upper() in available else "not present"
        print_value(f"selected --port ({selected_port})", state)


def open_close_port(serial_module: Any, port_name: str, baud_rate: int, timeout_s: float) -> Any:
    print_step(f"opening serial port {port_name}")
    print_value("baud rate", baud_rate)
    print_value("timeout seconds", timeout_s)
    print_step("no bytes will be written and no bytes will be read")
    handle = serial_module.Serial(port=port_name, baudrate=baud_rate, timeout=timeout_s)
    print_value("is open", getattr(handle, "is_open", "<unknown>"))
    print_step(f"closing serial port {port_name}")
    handle.close()
    print_value("is open after close", getattr(handle, "is_open", "<unknown>"))
    return handle


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Serial discovery-only test. Default mode lists serial ports and "
            "compares them with project default/configured COM resources. It "
            "does not read, write, move stages, switch valves, home devices, "
            "start pumps, or trigger actuators."
        )
    )
    parser.add_argument("--port", default=None, help="Port name to highlight, and required for --open-close.")
    parser.add_argument(
        "--open-close",
        action="store_true",
        help="Opt-in passive open/close test for --port. No reads or writes are performed.",
    )
    parser.add_argument("--baud-rate", type=int, default=9600, help="Baud rate for --open-close. Default: 9600.")
    parser.add_argument("--timeout-s", type=float, default=1.0, help="Timeout for --open-close. Default: 1.0.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    serial_handle = None

    print_step("starting serial port discovery test")
    print_step("default behavior only lists ports and compares configured/default resources")
    print_step("this script does not send commands, read bytes, move stages, switch valves, home devices, start pumps, or trigger actuators")

    try:
        serial_module, list_ports = import_pyserial()
        configured = load_configured_ports()
        for label, port_name in configured.items():
            print_value(label, port_name)

        ports = list_serial_ports(list_ports)
        compare_configured_ports(ports, configured, args.port)

        if args.open_close:
            if not args.port:
                raise ValueError("--open-close requires --port")
            serial_handle = open_close_port(serial_module, args.port, args.baud_rate, args.timeout_s)
        else:
            print_step("skipping open/close because --open-close was not provided")

        print_step("serial discovery test completed successfully")
        return 0
    except Exception as exc:
        print_step(f"ERROR: {exc}")
        return 1
    finally:
        print_step("entering cleanup")
        if serial_handle is not None and getattr(serial_handle, "is_open", False):
            try:
                serial_handle.close()
                print_step("cleanup ok: serial port closed")
            except Exception as exc:
                print_step(f"cleanup warning: serial close failed: {exc}")
        else:
            print_step("cleanup: no open serial handle")
        print_step("cleanup finished")


if __name__ == "__main__":
    raise SystemExit(main())
