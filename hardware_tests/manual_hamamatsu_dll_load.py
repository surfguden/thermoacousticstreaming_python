"""Manually verify that the bundled DCAM wrapper can load dcamapi.dll.

This intentionally does not initialize DCAM, discover/open a device, or acquire.
"""

from __future__ import annotations

import argparse
import sys


CONFIRMATION = "LOAD_DCAM_DLL_ONLY"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm", required=True, help=f"Pass {CONFIRMATION} to load the DCAM DLL.")
    args = parser.parse_args()
    if args.confirm != CONFIRMATION:
        parser.error(f"--confirm must be {CONFIRMATION}")

    from thermo_acoustic.drivers.camera import HamamatsuDcamDriver

    driver = HamamatsuDcamDriver()
    if not (driver.sdk_python_path / "dcam.py").is_file():
        raise FileNotFoundError(f"DCAM wrapper not found: {driver.sdk_python_path / 'dcam.py'}")

    # Importing dcam imports dcamapi4, whose module initialization loads
    # dcamapi.dll. No DCAM API function is called here.
    driver._load_sdk()
    print(f"DCAM wrapper loaded: {driver.dcam_module.__file__}")
    print(f"DCAM DLL loader module: {sys.modules['dcamapi4'].__file__}")
    print("dcamapi.dll loaded; no camera commands were sent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
