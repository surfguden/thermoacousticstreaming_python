"""Connect to a CETONI neMESYS pump and perform a reference move."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from thermo_acoustic.nemesys_pump import (  # noqa: E402
    DEFAULT_CONFIGURATION_PATH,
    NemesysPump,
)


CONFIRM_TEXT = "CONFIRM_REAL_CETONI_QMIX"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Connect to one CETONI neMESYS pump, reference its axis, and disconnect."
    )
    parser.add_argument(
        "--configuration",
        type=Path,
        default=DEFAULT_CONFIGURATION_PATH,
        help="Qmix configuration directory (default: %(default)s)",
    )
    parser.add_argument(
        "--pump-index",
        type=int,
        default=0,
        help="Zero-based pump index (default: %(default)s)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="Reference-move timeout in seconds (default: %(default)s)",
    )
    parser.add_argument(
        "--confirm",
        default=None,
        help=(
            "Required exact acknowledgement before operating REAL CETONI/QMIX hardware: "
            f"{CONFIRM_TEXT}"
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.confirm != CONFIRM_TEXT:
        print(
            "REFUSING: this tool can operate REAL CETONI/QMIX hardware. "
            f"Pass --confirm {CONFIRM_TEXT} exactly to acknowledge that risk. "
            "This acknowledgement does not establish physical readiness, syringe readiness, "
            "safe direction, safe flow, safe fill state, or physical verification.",
            file=sys.stderr,
            flush=True,
        )
        return 2

    pump = NemesysPump(
        configuration_path=args.configuration,
        pump_index=args.pump_index,
    )

    print("CETONI neMESYS reference-move test", flush=True)
    print(f"Configuration: {args.configuration}", flush=True)
    print(f"Pump selection: index {args.pump_index}", flush=True)

    result = 0
    try:
        print("Connecting to pump...", flush=True)
        pump.connect()
        print(f"Connected to: {pump.device_name}", flush=True)

        diameter_mm, stroke_mm = pump.syringe_parameters
        print(
            f"Syringe: {diameter_mm:g} mm inner diameter, {stroke_mm:g} mm piston stroke",
            flush=True,
        )
        print(f"Maximum volume: {pump.maximum_volume_ul:g} uL", flush=True)
        print(f"Maximum flow: {pump.maximum_flow_ul_min:g} uL/min", flush=True)

        print(
            f"Starting reference move (timeout: {args.timeout:g} seconds)...",
            flush=True,
        )
        pump.reference_move(timeout_s=args.timeout)
        print("Reference move completed successfully.", flush=True)
    except KeyboardInterrupt:
        print("Test interrupted by operator.", file=sys.stderr, flush=True)
        result = 130
    except Exception as exc:
        print(f"Test failed: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        result = 1
    finally:
        print("Closing pump connection...", flush=True)
        try:
            pump.close()
        except Exception as exc:
            print(
                f"Warning: connection cleanup failed: {type(exc).__name__}: {exc}",
                file=sys.stderr,
                flush=True,
            )
            if result == 0:
                result = 1
        else:
            print("Pump connection closed.", flush=True)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
