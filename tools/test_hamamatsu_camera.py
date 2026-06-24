from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from thermo_acoustic.hamamatsu_dcam import HamamatsuDcamBackend


def main() -> None:
    backend = HamamatsuDcamBackend()
    try:
        camera = backend.open_camera()
        print(f"Opened Hamamatsu camera: {camera}")
        backend.configure_exposure_time(50.0)
        frame = backend.capture_snapshot()
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
        backend.close()


if __name__ == "__main__":
    main()
