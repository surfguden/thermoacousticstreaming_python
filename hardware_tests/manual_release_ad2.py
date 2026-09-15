"""Manual WaveForms enumeration and device-handle release utility."""

from __future__ import annotations

__test__ = False

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from thermo_acoustic.drivers.ad2.waveforms import WaveFormsBackend


CONFIRM_TEXT = "CONFIRM_REAL_AD2_RELEASE"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm", help=f"Required exact acknowledgement: {CONFIRM_TEXT}")
    args = parser.parse_args(argv)
    if args.confirm != CONFIRM_TEXT:
        print(f"REFUSING real device access. Pass --confirm {CONFIRM_TEXT} after checking active device use.", file=sys.stderr)
        return 2

    backend = WaveFormsBackend()
    try:
        count = backend.enum_devices()
        print(f"WaveForms sees {count} device(s).")
        for index in range(count):
            name = backend.enum_device_name(index)
            serial = backend.enum_device_serial_number(index)
            opened = backend.enum_device_is_opened(index)
            print(f"  [{index}] {name} SN={serial} opened={opened}")
    except Exception as exc:
        print(f"Device enumeration failed before release: {exc}")
    backend.close_all()
    print("Released all Digilent WaveForms device handles.")
    try:
        count = backend.enum_devices()
        for index in range(count):
            opened = backend.enum_device_is_opened(index)
            print(f"  [{index}] opened={opened}")
    except Exception as exc:
        print(f"Device enumeration failed after release: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
