"""Decide whether this Python can start the UI in the requested mode.

Used by tools/launch_common.cmd to validate each candidate interpreter. It prints one line and exits
0 (usable) or 1 (not usable). It never imports a hardware driver or touches a device: the real-mode
packages are only looked for (importing pythonnet's `clr` would start the .NET runtime).

Usage:
    python tools/check_launch_python.py simulation|real

For the full dependency report use tools/check_environment.py.
"""
from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
import sys

SRC = Path(__file__).resolve().parents[1] / "src"

# (package, module): imported for real, so a broken install is caught.
UI_PACKAGES = (("PySide6", "PySide6.QtWidgets"), ("numpy", "numpy"), ("Pillow", "PIL"))
# Real mode also needs the retained driver packages; only presence is checked.
REAL_PACKAGES = (("pyserial", "serial"), ("pythonnet", "clr"), ("mecom", "mecom"))


def problems(mode: str) -> list[str]:
    found: list[str] = []
    if sys.version_info < (3, 11):
        found.append(f"Python {sys.version_info.major}.{sys.version_info.minor} is older than 3.11")
    if not (SRC / "thermo_acoustic" / "main.py").is_file():
        found.append(f"source not found at {SRC}")
    for package, module in UI_PACKAGES:
        try:
            importlib.import_module(module)
        except Exception as exc:
            found.append(f"{package} cannot be imported ({type(exc).__name__})")
    if mode == "real":
        for package, module in REAL_PACKAGES:
            if importlib.util.find_spec(module) is None:
                found.append(f"{package} is not installed (needed for real mode)")
    return found


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in {"simulation", "real"}:
        print("usage: check_launch_python.py simulation|real")
        return 2
    found = problems(argv[1])
    if found:
        print("; ".join(found))
        return 1
    print(f"Python {sys.version.split()[0]} is usable for {argv[1]} mode")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
