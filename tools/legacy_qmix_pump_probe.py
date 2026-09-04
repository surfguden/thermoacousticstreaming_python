"""Legacy manual Qmix diagnostic, not automated pytest coverage.

Initialization can open the real bus and enable the pump; ``--flow-ul-min``
can additionally command motion. It has no confirmation gate, so retain it
only as historical diagnostics and use gated hardware tools for new work.
"""

from __future__ import annotations

__test__ = False

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from thermo_acoustic.qmix_backend import QmixPumpBackend


CONFIRM_TEXT = "CONFIRM_REAL_CETONI_QMIX"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Open and lightly exercise a real Qmix/Cetoni pump.")
    parser.add_argument(
        "configuration_path",
        nargs="?",
        default=r"C:\Users\Public\Documents\QmixElements\Projects",
        help="Qmix device configuration path passed to LCB_Open.",
    )
    parser.add_argument("--pump-name", default=None, help="Optional Qmix pump device name.")
    parser.add_argument("--pump-index", type=int, default=0, help="Pump index when no name is supplied.")
    parser.add_argument("--flow-ul-min", type=float, default=0.0, help="Optional flow to command briefly.")
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
            "REFUSING: this quarantined legacy tool can operate REAL CETONI/QMIX hardware. "
            f"Pass --confirm {CONFIRM_TEXT} exactly to acknowledge that risk. "
            "This acknowledgement does not establish physical readiness, syringe readiness, "
            "safe direction, safe flow, safe fill state, or physical verification.",
            file=sys.stderr,
            flush=True,
        )
        return 2

    backend = QmixPumpBackend(pump_name=args.pump_name, pump_index=args.pump_index)
    result = 0
    try:
        backend.initialize(Path(args.configuration_path))
        print(f"Initialized Qmix pump index={args.pump_index} name={args.pump_name!r}")
        print(f"Max flow: {backend.max_flow_rate_ul_min} uL/min")
        print(f"Max volume: {backend.max_volume_ml} mL")
        if args.flow_ul_min:
            backend.generate_flow(args.flow_ul_min)
            print(f"Commanded flow: {args.flow_ul_min} uL/min")
            print(f"Pumping: {backend.read_status()}")
            backend.stop()
            print("Stopped pump")
    except KeyboardInterrupt:
        print("Legacy probe interrupted by operator.", file=sys.stderr, flush=True)
        result = 130
    except Exception as exc:
        print(f"Legacy probe failed: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        result = 1
    finally:
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
    return result


if __name__ == "__main__":
    raise SystemExit(main())
