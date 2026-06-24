from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from thermo_acoustic.waveforms import WaveFormsBackend


def main() -> None:
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


if __name__ == "__main__":
    main()
