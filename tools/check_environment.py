"""Sanity-check that the current Python environment has every real,
third-party package the production app (launch_gui.bat -> qt_ui.py) needs.

Run this after (re)creating the `exp_ctrl` conda environment, instead of
only discovering a gap the first time a real experiment tries to use it --
this is exactly how the original npTDMS gap went undetected until a real-
hardware verification run tried to write data.tdms (2026-07-31, see
docs/known_open_items.md).

Usage:
    python tools/check_environment.py

Exit code 0 if every import succeeds, 1 otherwise.
"""
from __future__ import annotations

import importlib
import sys


# name -> (module to import, why it's needed, which real file imports it)
CORE_DEPENDENCIES: dict[str, tuple[str, str]] = {
    "PySide6": ("PySide6.QtWidgets", "qt_ui.py / qt_ui_v2.py -- the whole GUI"),
    "Pillow": ("PIL", "used for image handling"),
    "pyserial": ("serial", "instruments.py -- valve serial backend"),
    "npTDMS": ("nptdms", "workflows.py -- writing data.tdms; missing until 2026-07-31"),
    "numpy": ("numpy", "workflows.py / qt_ui.py -- top-level imports, always needed"),
    "pythonnet": ("clr", "thorlabs_piezo.py -- real Z-stage/piezo motion via Kinesis .NET"),
    "mecom": ("mecom", "tec.py -- real Meerstetter TEC controller via pyMeCom (MeComSerial)"),
}

# Only needed for a standalone diagnostic script, not the real production
# path -- reported separately, does not affect the pass/fail exit code.
OPTIONAL_DEPENDENCIES: dict[str, tuple[str, str]] = {
    "pylablib": ("pylablib", "hardware_tests/test_thorlabs_apt_discovery.py only"),
}


def check_one(package_name: str, import_name: str, reason: str) -> bool:
    try:
        importlib.import_module(import_name)
    except Exception as exc:
        print(f"  [MISSING] {package_name} (import {import_name}) -- needed for: {reason}")
        print(f"            {exc!r}")
        return False
    print(f"  [OK]      {package_name} (import {import_name})")
    return True


def main() -> int:
    print(f"Checking environment: {sys.executable}")
    print(f"Python version: {sys.version}\n")

    print("Core dependencies (required for launch_gui.bat / the real production app):")
    core_ok = all(
        check_one(package_name, import_name, reason)
        for package_name, (import_name, reason) in CORE_DEPENDENCIES.items()
    )

    print("\nOptional dependencies (diagnostic scripts only, not the core app):")
    for package_name, (import_name, reason) in OPTIONAL_DEPENDENCIES.items():
        check_one(package_name, import_name, reason)

    print()
    if core_ok:
        print("All core dependencies present.")
        return 0
    print("One or more core dependencies are MISSING -- see requirements-exp_ctrl.txt.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
