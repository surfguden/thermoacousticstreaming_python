from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from thermo_acoustic.qmix_backend import QmixPumpBackend


def main() -> None:
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
    args = parser.parse_args()

    backend = QmixPumpBackend(pump_name=args.pump_name, pump_index=args.pump_index)
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
    finally:
        backend.close()


if __name__ == "__main__":
    main()
