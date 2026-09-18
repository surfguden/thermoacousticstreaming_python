"""Open one real Analog Discovery and print read-only WaveForms capabilities."""

from __future__ import annotations

__test__ = False

import argparse
from pprint import pprint
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from thermo_acoustic.drivers.ad2 import AnalogDiscovery2


CONFIRM_TEXT = "CONFIRM_REAL_AD2_CAPABILITIES"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm", help=f"Required exact acknowledgement: {CONFIRM_TEXT}")
    args = parser.parse_args(argv)
    if args.confirm != CONFIRM_TEXT:
        print(
            f"REFUSING real device access. Pass --confirm {CONFIRM_TEXT} "
            "after checking that the AD2 is safe to open.",
            file=sys.stderr,
        )
        return 2

    driver = AnalogDiscovery2()
    try:
        driver.initialize()
        print(f"Opened Analog Discovery handle {driver.device_handle}.")
        pprint(driver.capabilities(), sort_dicts=True)
        return 0
    except Exception as exc:
        print(f"Capability read failed: {exc}", file=sys.stderr)
        return 1
    finally:
        try:
            driver.cleanup()
            print("Analog Discovery closed safely.")
        except Exception as exc:
            print(f"Cleanup failed: {exc}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
