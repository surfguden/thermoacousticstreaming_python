"""Manually verify Qmix Python wrappers and native DLLs without bus access."""

from __future__ import annotations

import argparse
import os
from pathlib import Path


CONFIRMATION = "LOAD_QMIX_DLLS_ONLY"
REQUIRED_DLLS = ("labbCAN_Bus_API.dll", "labbCAN_Pump_API.dll", "labbCAN_Valve_API.dll")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dll-dir", required=True, type=Path, help="Folder containing the Qmix SDK DLLs.")
    parser.add_argument("--confirm", required=True, help=f"Pass {CONFIRMATION} to load the DLLs.")
    args = parser.parse_args()
    if args.confirm != CONFIRMATION:
        parser.error(f"--confirm must be {CONFIRMATION}")

    dll_dir = args.dll_dir.resolve()
    missing = [name for name in REQUIRED_DLLS if not (dll_dir / name).is_file()]
    if missing:
        parser.error(f"{dll_dir} is missing required SDK DLLs: {', '.join(missing)}")
    os.environ["QMIXSDK"] = str(dll_dir)

    from thermo_acoustic.drivers.pump import CetoniPump

    pump = CetoniPump()
    pump._load_sdk()
    print(f"Qmix SDK DLLs loaded from {dll_dir}")
    print(f"Qmix bus wrapper: {pump.qmixbus.__file__}")
    print(f"Qmix pump wrapper: {pump.qmixpump.__file__}")
    print("No bus was opened and no pump commands were sent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
