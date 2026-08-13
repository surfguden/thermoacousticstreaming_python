"""
Manual-only valve command probe (hardware_tests/test_valve_command_probe.py)

Purpose:
  Test a SINGLE candidate command string against the real Rheodyne MX valve
  on a serial port, so the user can observe whether the valve physically
  switches. This is intentionally isolated from src/ and from the main
  application code -- it does not import Valve, SerialTextCommandBackend,
  or anything from src/thermo_acoustic.

This is not an automated pytest test despite the historical ``test_`` file
name. ``pyproject.toml`` collects only ``tests/`` and ``__test__ = False``
below is a second guard if collection configuration changes. Run it only by an
explicit operator command after reading this header.

Safety:
  - Sends exactly ONE command per run, then exits.
  - Requires explicit --port and --command-name (from a fixed candidate list)
    plus a typed confirmation string, so nothing fires by accident.
  - Does not loop, does not retry, does not send multiple candidates in one run.
  - Prints exactly what bytes were sent so there is no ambiguity.

Usage:
  python hardware_tests\\test_valve_command_probe.py --list
  python hardware_tests\\test_valve_command_probe.py --port COM5 --command-name cr_1 --confirm SEND
"""

import argparse
import sys
import time


# Prevent accidental collection if a future pytest invocation names this file.
__test__ = False

try:
    import serial
except ImportError:
    serial = None


# Candidate command formats to test ONE AT A TIME.
# Format: name -> (raw_bytes_to_send, human_description)
CANDIDATES = {
    "cr_1":        (b"1\r",        "Bare '1' + CR only (most common Rheodyne-style)"),
    "cr_2":        (b"2\r",        "Bare '2' + CR only"),
    "crlf_1":      (b"1\r\n",      "Legacy bare '1' + CRLF candidate; not the current application format"),
    "lf_1":        (b"1\n",        "Bare '1' + LF only"),
    "p01_cr":      (b"P01\r",      "Current application/LabVIEW position-1 command; fluidic route unverified"),
    "p02_cr":      (b"P02\r",      "Current application/LabVIEW position-2 command; fluidic route unverified"),
    "go1_cr":      (b"GO1\r",      "'GO1' + CR (go-to-position style)"),
    "go2_cr":      (b"GO2\r",      "'GO2' + CR"),
    "cp1_cr":      (b"CP1\r",      "'CP1' + CR (change position style)"),
    "cp2_cr":      (b"CP2\r",      "'CP2' + CR"),
    "addr0_p01":   (b"/1P01\r",    "Address-prefixed '/1P01' + CR (multi-drop protocol style)"),
    "status_query": (b"S\r",       "'S' + CR (diagnostic only, no motion expected) -- status "
                                    "query used by the current application; response semantics "
                                    "require bench confirmation"),
}
# NOTE: the earlier "star_query" ('*\r') candidate was speculative. The
# application uses ``S\r`` as its status query, but this script does not treat
# its response semantics as independent vendor-documentation proof.


def main():
    parser = argparse.ArgumentParser(description="Rheodyne MX valve command probe (single-shot)")
    parser.add_argument("--port", help="Serial port, e.g. COM5")
    parser.add_argument("--baud", type=int, default=19200, help="Baud rate (default 19200, current app default)")
    parser.add_argument("--timeout", type=float, default=1.0, help="Serial timeout seconds")
    parser.add_argument("--command-name", choices=list(CANDIDATES.keys()),
                         help="Which candidate command to send (see --list)")
    parser.add_argument("--confirm", help="Must be exactly SEND to actually transmit")
    parser.add_argument("--list", action="store_true", help="List all candidate commands and exit")
    parser.add_argument("--read-response", action="store_true",
                         help="After sending, wait briefly and print any bytes the valve sends back")
    args = parser.parse_args()

    if args.list:
        print("Available candidate commands:\n")
        for name, (raw, desc) in CANDIDATES.items():
            print(f"  {name:14s} bytes={raw!r:16s} - {desc}")
        return

    if serial is None:
        print("pyserial not installed in this environment. Run: pip install pyserial")
        sys.exit(1)

    if not args.port or not args.command_name:
        print("ERROR: --port and --command-name are required (or use --list).")
        sys.exit(1)

    if args.confirm != "SEND":
        print("ERROR: refusing to send without --confirm SEND")
        print(f"About to send candidate '{args.command_name}': {CANDIDATES[args.command_name][0]!r}")
        print("Re-run with --confirm SEND to actually transmit this command.")
        sys.exit(1)

    raw_bytes, desc = CANDIDATES[args.command_name]

    print(f"[valve-probe] port: {args.port}")
    print(f"[valve-probe] baud: {args.baud}, timeout: {args.timeout}s")
    print(f"[valve-probe] candidate: {args.command_name} - {desc}")
    print(f"[valve-probe] EXACT BYTES TO SEND: {raw_bytes!r}")
    print("[valve-probe] opening port...")

    ser = serial.Serial(args.port, baudrate=args.baud, timeout=args.timeout)
    try:
        print("[valve-probe] port open. Sending in 2 seconds -- watch/listen to the valve now.")
        time.sleep(2.0)
        n = ser.write(raw_bytes)
        ser.flush()
        print(f"[valve-probe] wrote {n} bytes successfully (no exception raised).")

        if args.read_response:
            time.sleep(0.3)
            resp = ser.read(64)
            print(f"[valve-probe] response bytes read: {resp!r}")
        else:
            print("[valve-probe] not reading response (pass --read-response to check for any reply).")

    finally:
        ser.close()
        print("[valve-probe] port closed.")

    print()
    print("=" * 60)
    print("Did the valve physically move/click/switch? Record this manually.")
    print(f"Candidate tested: {args.command_name} -> {raw_bytes!r}")
    print("=" * 60)


if __name__ == "__main__":
    main()
