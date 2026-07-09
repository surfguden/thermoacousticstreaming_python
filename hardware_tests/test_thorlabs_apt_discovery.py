from __future__ import annotations

import argparse
import importlib.util
import platform
import sys
from pathlib import Path
from typing import Iterable


THORLABS_ROOTS = (
    Path(r"C:\Program Files\Thorlabs"),
    Path(r"C:\Program Files (x86)\Thorlabs"),
    Path(r"C:\Program Files\Thorlabs\Kinesis"),
    Path(r"C:\Program Files (x86)\Thorlabs\Kinesis"),
)

THORLABS_DLL_NAMES = (
    "Thorlabs.MotionControl.DeviceManagerCLI.dll",
    "Thorlabs.MotionControl.GenericMotorCLI.dll",
    "Thorlabs.MotionControl.KCube.DCServoCLI.dll",
    "Thorlabs.MotionControl.Benchtop.StepperMotorCLI.dll",
    "Thorlabs.MotionControl.IntegratedStepperMotorsCLI.dll",
)


def print_step(message: str) -> None:
    print(f"[thorlabs-apt-discovery] {message}", flush=True)


def print_value(label: str, value: object) -> None:
    print(f"  {label}: {value}", flush=True)


def dedupe_paths(paths: Iterable[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


def print_python_environment() -> None:
    print_step("python environment")
    print_value("executable", sys.executable)
    print_value("version", sys.version.replace("\n", " "))
    print_value("architecture", platform.architecture()[0])
    print_value("machine", platform.machine())
    print_value("platform", platform.platform())


def find_import_spec(module_name: str) -> object | None:
    try:
        return importlib.util.find_spec(module_name)
    except (ImportError, AttributeError, ValueError) as exc:
        print_step(f"warning: checking {module_name!r} failed: {exc}")
        return None


def print_package_checks() -> dict[str, bool]:
    print_step("checking optional Python package/module availability")
    checks = {
        "pythonnet": find_import_spec("pythonnet"),
        "pylablib": find_import_spec("pylablib"),
        "msl.equipment": find_import_spec("msl.equipment"),
    }

    available: dict[str, bool] = {}
    for name, spec in checks.items():
        is_available = spec is not None
        available[name] = is_available
        print_value(f"{name} importable", is_available)
        if spec is not None:
            print_value(f"{name} origin", getattr(spec, "origin", None))
    print_step("note: this script does not import clr, ctypes, or Thorlabs DLLs")
    return available


def print_thorlabs_roots() -> list[Path]:
    print_step("checking likely Thorlabs/Kinesis installation folders")
    roots = dedupe_paths(THORLABS_ROOTS)
    for root in roots:
        print_value(str(root), "exists" if root.exists() else "missing")
    return roots


def search_for_dlls(roots: Iterable[Path]) -> dict[str, list[Path]]:
    print_step("searching for Thorlabs/Kinesis DLL files")
    found: dict[str, list[Path]] = {dll_name: [] for dll_name in THORLABS_DLL_NAMES}
    existing_roots = [root for root in roots if root.exists()]

    if not existing_roots:
        print_step("no existing Thorlabs roots found; skipping DLL search")
        return found

    for root in existing_roots:
        print_step(f"search root: {root}")
        for dll_name in THORLABS_DLL_NAMES:
            try:
                matches = list(root.rglob(dll_name))
            except OSError as exc:
                print_step(f"warning: could not search {root} for {dll_name}: {exc}")
                continue
            found[dll_name].extend(matches)

    for dll_name, paths in found.items():
        print_step(f"DLL: {dll_name}")
        print_value("found", bool(paths))
        if paths:
            for path in dedupe_paths(paths):
                print_value("path", path)
        else:
            print_value("path", "<not found>")
    return found


def print_kinesis_device(device: object, index: int) -> None:
    print_step(f"pylablib Kinesis device {index}")
    if isinstance(device, tuple):
        for field_index, value in enumerate(device):
            print_value(f"field {field_index}", value)
        return

    print_value("repr", repr(device))
    for attr_name in ("serial", "serial_number", "description", "model", "name"):
        if hasattr(device, attr_name):
            try:
                print_value(attr_name, getattr(device, attr_name))
            except Exception as exc:
                print_value(attr_name, f"<read failed: {exc}>")


def try_pylablib_passive_enumeration(pylablib_available: bool) -> None:
    print_step("pylablib passive Kinesis enumeration")
    if not pylablib_available:
        print_step("pylablib is not installed/importable; skipping enumeration")
        print_step("no packages will be installed automatically")
        return

    try:
        from pylablib.devices import Thorlabs

        print_step("calling pylablib.devices.Thorlabs.list_kinesis_devices()")
        devices = Thorlabs.list_kinesis_devices()
        print_value("device count", len(devices))
        for index, device in enumerate(devices):
            print_kinesis_device(device, index)
        if not devices:
            print_step("no Kinesis/APT devices reported by pylablib")
    except Exception as exc:
        print_step(f"pylablib passive enumeration failed: {exc}")
    finally:
        print_step("cleanup: no controller was opened; nothing to close")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Discovery-only diagnostics for a Thorlabs APT/Kinesis USB device. "
            "This script does not open, enable, home, move, jog, identify, poll, "
            "or change controller settings."
        )
    )
    return parser.parse_args()


def main() -> int:
    parse_args()
    print_step("starting discovery-only Thorlabs APT/Kinesis diagnostics")
    print_step("safety: no motor/controller class will be instantiated")
    print_step("safety: no device will be opened or enabled")
    print_step("safety: no home, move, jog, identify, polling, or setting changes")

    print_python_environment()
    package_available = print_package_checks()
    thorlabs_roots = print_thorlabs_roots()
    search_for_dlls(thorlabs_roots)
    try_pylablib_passive_enumeration(package_available["pylablib"])

    print_step("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
