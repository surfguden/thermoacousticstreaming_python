"""Manual camera diagnostic, not automated pytest coverage.

Running this file opens/configures the real camera, captures a frame, and
writes an ignored TIFF artifact. Requires explicit operator confirmation.
"""

from __future__ import annotations

__test__ = False

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from thermo_acoustic.drivers.camera import HamamatsuDcamDriver


CONFIRM_TEXT = "CONFIRM_REAL_CAMERA_CAPTURE"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm", help=f"Required exact acknowledgement: {CONFIRM_TEXT}")
    args = parser.parse_args(argv)
    if args.confirm != CONFIRM_TEXT:
        print(f"REFUSING real camera capture. Pass --confirm {CONFIRM_TEXT} after verifying bench readiness.", file=sys.stderr)
        return 2

    driver = HamamatsuDcamDriver()
    try:
        camera = driver.open_camera()
        print(f"Opened Hamamatsu camera: {camera}")
        driver.configure_exposure_time(50.0)
        frame = driver.capture_snapshot()
        shape = getattr(frame, "shape", None)
        dtype = getattr(frame, "dtype", None)
        print(f"Captured snapshot shape={shape} dtype={dtype}")
        out = ROOT / "hamamatsu_snapshot.tiff"
        try:
            from PIL import Image

            Image.fromarray(frame).save(out, format="TIFF")
            print(f"Saved {out}")
        except Exception as exc:
            print(f"Could not save snapshot: {exc}")
    finally:
        driver.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
