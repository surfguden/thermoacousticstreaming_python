"""
Manual-only valve command probe v2 (hardware_tests/test_valve_command_probe_v2.py)

Adds explicit DTR/RTS control on top of v1, to test whether the valve
requires these handshake lines asserted before it will respond to commands.

This is not an automated pytest test despite the historical ``test_`` file
name. ``pyproject.toml`` collects only ``tests/`` and ``__test__ = False``
below is a second guard if collection configuration changes. Run it only by an
explicit operator command after reading this header.

Usage:
  python hardware_tests\\test_valve_command_probe_v2.py --list
  python hardware_tests\\test_valve_command_probe_v2.py --port COM5 --baud 19200 --command-name p01_cr --confirm SEND --dtr true --rts true
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


CANDIDATES = {
    "cr_1":        (b"1\r",        "Bare '1' + CR only"),
    "cr_2":        (b"2\r",        "Bare '2' + CR only"),
    "crlf_1":      (b"1\r\n",      "Bare '1' + CRLF"),
    "p01_cr":      (b"P01\r",      "'P01' + CR (confirmed LabVIEW format for position 1)"),
    "p02_cr":      (b"P02\r",      "'P02' + CR (candidate for position 2)"),
    "status_query": (b"S\r",       "'S' + CR -- status/position query used by the current "
                                    "application. Record the raw response; its exact device "
                                    "semantics require bench confirmation. Use --read-response "
                                    "to see it."),
}
# NOTE: the earlier "star_query" ('*\r') candidate was speculative. The
# application uses ``S\r`` as its status query, but this script does not treat
# its response semantics as independent vendor-documentation proof.


def parse_tristate(value):
    if value is None:
        return None
    v = value.strip().lower()
    if v == "true":
        return True
    if v == "false":
        return False
    raise argparse.ArgumentTypeError("must be 'true' or 'false'")


def main():
    parser = argparse.ArgumentParser(description="Rheodyne MX valve command probe v2 (DTR/RTS aware)")
    parser.add_argument("--port", help="Serial port, e.g. COM5")
    parser.add_argument("--baud", type=int, default=19200, help="Baud rate (default 19200, confirmed from LabVIEW)")
    parser.add_argument("--timeout", type=float, default=1.0, help="Serial timeout seconds")
    parser.add_argument("--command-name", choices=list(CANDIDATES.keys()))
    parser.add_argument("--confirm", help="Must be exactly SEND to actually transmit")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--read-response", action="store_true")
    parser.add_argument("--dtr", type=parse_tristate, default=None,
                         help="'true' or 'false' to explicitly set DTR after opening; omit to leave OS/pyserial default")
    parser.add_argument("--rts", type=parse_tristate, default=None,
                         help="'true' or 'false' to explicitly set RTS after opening; omit to leave OS/pyserial default")
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
        sys.exit(1)

    raw_bytes, desc = CANDIDATES[args.command_name]

    print(f"[valve-probe-v2] port: {args.port}")
    print(f"[valve-probe-v2] baud: {args.baud}, timeout: {args.timeout}s")
    print(f"[valve-probe-v2] candidate: {args.command_name} - {desc}")
    print(f"[valve-probe-v2] EXACT BYTES TO SEND: {raw_bytes!r}")
    print(f"[valve-probe-v2] requested DTR override: {args.dtr}")
    print(f"[valve-probe-v2] requested RTS override: {args.rts}")
    print("[valve-probe-v2] opening port...")

    ser = serial.Serial(args.port, baudrate=args.baud, timeout=args.timeout)
    try:
        print(f"[valve-probe-v2] port open. Initial line state: DTR={ser.dtr} RTS={ser.rts} CTS={ser.cts} DSR={ser.dsr}")

        if args.dtr is not None:
            ser.dtr = args.dtr
            print(f"[valve-probe-v2] DTR explicitly set to {args.dtr}")
        if args.rts is not None:
            ser.rts = args.rts
            print(f"[valve-probe-v2] RTS explicitly set to {args.rts}")

        print(f"[valve-probe-v2] line state after override: DTR={ser.dtr} RTS={ser.rts} CTS={ser.cts} DSR={ser.dsr}")

        print("[valve-probe-v2] sending in 2 seconds -- watch/listen to the valve now.")
        time.sleep(2.0)
        n = ser.write(raw_bytes)
        ser.flush()
        print(f"[valve-probe-v2] wrote {n} bytes successfully (no exception raised).")

        if args.read_response:
            time.sleep(0.3)
            resp = ser.read(64)
            print(f"[valve-probe-v2] response bytes read: {resp!r}")
        else:
            print("[valve-probe-v2] not reading response (pass --read-response to check).")

        print(f"[valve-probe-v2] line state at end: CTS={ser.cts} DSR={ser.dsr}")

    finally:
        ser.close()
        print("[valve-probe-v2] port closed.")

    print()
    print("=" * 60)
    print("Did the valve physically move/click/switch? Record this manually.")
    print(f"Candidate tested: {args.command_name} -> {raw_bytes!r}  DTR={args.dtr} RTS={args.rts}")
    print("=" * 60)


if __name__ == "__main__":
    main()
