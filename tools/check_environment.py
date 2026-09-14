"""Check Python dependencies for the retained hardware drivers.

Run this after creating or updating the `exp_ctrl` conda environment to
catch missing packages before authorized hardware use. This does not validate
vendor SDK installations or physical device behavior.

Usage:
    python tools/check_environment.py

Exit code 0 if every import succeeds, 1 otherwise.
"""
from __future__ import annotations

import importlib
import sys


# name -> (module to import, why it's needed, which real file imports it)
CORE_DEPENDENCIES: dict[str, tuple[str, str]] = {
    "Pillow": ("PIL", "used for image handling"),
    "pyserial": ("serial", "instruments.py -- valve serial backend"),
    "numpy": ("numpy", "DCAM vendor wrapper -- camera frame arrays"),
    "pythonnet": ("clr", "thorlabs_piezo.py -- real Z-stage/piezo motion via Kinesis .NET"),
    "mecom": ("mecom", "tec.py -- real Meerstetter TEC controller via pyMeCom (MeComSerial)"),
}

# Only needed for standalone diagnostic scripts, not the core driver
# path -- reported separately, does not affect the pass/fail exit code.
OPTIONAL_DEPENDENCIES: dict[str, tuple[str, str]] = {
    "pylablib": ("pylablib", "hardware_tests/test_thorlabs_apt_discovery.py only"),
    "matplotlib": ("matplotlib", "hardware_tests/manual_capture_ad2_wavegen_scope_matplotlib.py only"),
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

    print("Core hardware-driver dependencies:")
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
