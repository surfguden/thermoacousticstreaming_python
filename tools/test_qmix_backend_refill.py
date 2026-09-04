"""Reference and refill a CETONI pump through QmixPumpBackend.

This is an operator-run hardware test. It performs real pump movement.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from thermo_acoustic.qmix_backend import QmixPumpBackend  # noqa: E402


DEFAULT_CONFIGURATION_PATH = Path(
    r"C:\Users\Public\Documents\QmixElements\Projects\default_project\Configurations\single"
)
DEFAULT_QMIXSDK_PATH = Path(r"C:\Users\Ola\AppData\Local\CETONI_SDK")
CONFIRM_TEXT = "CONFIRM_REAL_CETONI_QMIX"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Connect through QmixPumpBackend, reference the pump, then refill "
            "at its live maximum flow while printing fill-level readback."
        )
    )
    parser.add_argument(
        "--configuration",
        type=Path,
        default=DEFAULT_CONFIGURATION_PATH,
        help="Qmix configuration directory (default: %(default)s)",
    )
    parser.add_argument(
        "--qmixsdk",
        type=Path,
        default=DEFAULT_QMIXSDK_PATH,
        help="CETONI SDK runtime directory (default: %(default)s)",
    )
    parser.add_argument(
        "--pump-index",
        type=int,
        default=0,
        help="Zero-based pump index (default: %(default)s)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=0.25,
        help="Seconds between fill-level readings (default: %(default)s)",
    )
    parser.add_argument(
        "--refill-timeout",
        type=float,
        default=120.0,
        help="Maximum refill time in seconds (default: %(default)s)",
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


def require_positive(value: float, name: str) -> float:
    value = float(value)
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    poll_interval_s = require_positive(args.poll_interval, "--poll-interval")
    refill_timeout_s = require_positive(args.refill_timeout, "--refill-timeout")
    if args.pump_index < 0:
        raise ValueError("--pump-index must be zero or greater")

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

    os.environ["QMIXSDK"] = str(args.qmixsdk)
    backend = QmixPumpBackend(pump_index=args.pump_index)
    result = 0

    print("QmixPumpBackend reference-and-refill test", flush=True)
    print(f"Configuration: {args.configuration}", flush=True)
    print(f"Qmix SDK runtime: {args.qmixsdk}", flush=True)
    print(f"Pump selection: index {args.pump_index}", flush=True)

    try:
        print("Connecting to pump...", flush=True)
        backend.initialize(args.configuration)
        print("Pump connected.", flush=True)

        maximum_flow_ul_min = backend.max_flow_rate_ul_min
        maximum_volume_ml = backend.max_volume_ml
        if maximum_flow_ul_min is None or maximum_volume_ml is None:
            raise RuntimeError("Pump did not report its live flow and volume limits")

        print(f"Maximum flow: {maximum_flow_ul_min:g} uL/min", flush=True)
        print(
            f"Maximum volume: {maximum_volume_ml:g} mL "
            f"({maximum_volume_ml * 1000.0:g} uL)",
            flush=True,
        )

        print("Starting reference move...", flush=True)
        backend.reference_move()
        print("Reference move completed.", flush=True)

        print(
            f"Starting refill at {maximum_flow_ul_min:g} uL/min...",
            flush=True,
        )
        refill_started = time.monotonic()
        backend.refill(maximum_flow_ul_min)

        while True:
            elapsed_s = time.monotonic() - refill_started
            fill_level_ml = backend.read_fill_level()
            pumping = backend.read_status()
            print(
                f"{elapsed_s:7.2f} s | fill level: {fill_level_ml:.6f} mL "
                f"({fill_level_ml * 1000.0:.3f} uL) | "
                f"{'refilling' if pumping else 'stopped'}",
                flush=True,
            )

            if not pumping:
                break
            if elapsed_s >= refill_timeout_s:
                backend.stop()
                raise TimeoutError(
                    f"Refill exceeded {refill_timeout_s:g} seconds and was stopped"
                )
            time.sleep(poll_interval_s)

        final_level_ml = backend.read_fill_level()
        print(
            f"Refill completed at {final_level_ml:.6f} mL "
            f"({final_level_ml * 1000.0:.3f} uL).",
            flush=True,
        )
    except KeyboardInterrupt:
        print("Interrupted by operator; stopping pump...", file=sys.stderr, flush=True)
        try:
            backend.stop()
        except Exception as stop_exc:
            print(f"Warning: stop failed: {stop_exc}", file=sys.stderr, flush=True)
        result = 130
    except Exception as exc:
        print(f"Test failed: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        try:
            backend.stop()
        except Exception as stop_exc:
            print(f"Warning: stop failed: {stop_exc}", file=sys.stderr, flush=True)
        result = 1
    finally:
        print("Closing pump connection...", flush=True)
        try:
            backend.close()
        except Exception as close_exc:
            print(
                f"Warning: connection cleanup failed: {type(close_exc).__name__}: {close_exc}",
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
