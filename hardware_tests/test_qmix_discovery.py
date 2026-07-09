from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SDK_PYTHON_PATH = ROOT / "qmix_sdk_for_codex" / "python"
DEFAULT_CONFIG_PATH = Path(r"C:\Users\Public\Documents\QmixElements\Projects")
QMIX_REQUIRED_DLLS = ("labbCAN_Bus_API.dll", "labbCAN_Pump_API.dll")
DLL_DIRECTORY_HANDLES: list[Any] = []


def print_step(message: str) -> None:
    print(f"[qmix-discovery] {message}", flush=True)


def print_value(label: str, value: object) -> None:
    print(f"  {label}: {value}", flush=True)


def safe_call(label: str, action: Any) -> None:
    try:
        action()
        print_step(f"cleanup ok: {label}")
    except Exception as exc:
        print_step(f"cleanup warning: {label} failed: {exc}")


def validate_path(label: str, path: Path) -> None:
    print_step(f"validating {label}: {path}")
    if not path.exists():
        raise FileNotFoundError(f"{label} does not exist: {path}")
    print_value(label, "exists")


def dedupe_paths(paths: list[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path.resolve() if path.exists() else path).lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


def likely_qmix_subdirs(qmix_root: Path) -> list[Path]:
    if not qmix_root.exists():
        return []
    markers = {"bin", "lib", "x64", "win64", "win32", "windows", "dll", "release"}
    result: list[Path] = []
    try:
        for directory in qmix_root.rglob("*"):
            if not directory.is_dir():
                continue
            parts = {part.lower() for part in directory.parts}
            if parts & markers:
                result.append(directory)
    except OSError as exc:
        print_step(f"warning: could not scan likely Qmix subdirectories: {exc}")
    return dedupe_paths(result)


def build_search_roots(sdk_python_path: Path) -> list[Path]:
    qmix_root = ROOT / "qmix_sdk_for_codex"
    roots = [ROOT, qmix_root, qmix_root / "python", sdk_python_path]
    qmixsdk_env = os.environ.get("QMIXSDK")
    if qmixsdk_env:
        roots.append(Path(qmixsdk_env))
    roots.extend(likely_qmix_subdirs(qmix_root))
    return dedupe_paths(roots)


def print_search_roots(search_roots: list[Path]) -> None:
    print_step("searched roots / candidate folders")
    for path in search_roots:
        state = "exists" if path.exists() else "missing"
        print_value(str(path), state)


def search_qmix_dlls(search_roots: list[Path]) -> dict[str, list[Path]]:
    found: dict[str, list[Path]] = {name: [] for name in QMIX_REQUIRED_DLLS}
    for root in search_roots:
        if not root.exists():
            continue
        for dll_name in QMIX_REQUIRED_DLLS:
            direct = root / dll_name
            if direct.exists():
                found[dll_name].append(direct)
            try:
                found[dll_name].extend(path for path in root.rglob(dll_name) if path.is_file())
            except OSError as exc:
                print_step(f"warning: could not search {root} for {dll_name}: {exc}")
    return {name: dedupe_paths(paths) for name, paths in found.items()}


def print_dll_search_results(found: dict[str, list[Path]]) -> None:
    print_step("Qmix DLL search results")
    for dll_name in QMIX_REQUIRED_DLLS:
        paths = found.get(dll_name, [])
        if not paths:
            print_value(dll_name, "<missing>")
            continue
        for index, path in enumerate(paths):
            print_value(f"{dll_name} [{index}]", path)


def directories_containing_qmix_dlls(found: dict[str, list[Path]]) -> list[Path]:
    directories = [path.parent for paths in found.values() for path in paths]
    return dedupe_paths(directories)


def common_complete_dll_directories(found: dict[str, list[Path]]) -> list[Path]:
    sets = [{path.parent.resolve() for path in found.get(dll_name, [])} for dll_name in QMIX_REQUIRED_DLLS]
    if not sets:
        return []
    common = set.intersection(*sets)
    return sorted(common)


def add_windows_dll_directories(directories: list[Path]) -> None:
    if os.name != "nt":
        print_step("os.add_dll_directory skipped because this is not Windows")
        return
    if not hasattr(os, "add_dll_directory"):
        print_step("os.add_dll_directory is unavailable in this Python runtime")
        return
    print_step("adding Qmix DLL directories with os.add_dll_directory")
    for directory in directories:
        try:
            handle = os.add_dll_directory(str(directory))
            DLL_DIRECTORY_HANDLES.append(handle)
            print_value("added DLL directory", directory)
        except OSError as exc:
            print_value("DLL directory add failed", f"{directory}: {exc}")


def prepare_qmix_dll_loading(sdk_python_path: Path) -> None:
    print_value("current working directory", Path.cwd())
    print_value("QMIXSDK environment variable", os.environ.get("QMIXSDK", "<not set>"))
    search_roots = build_search_roots(sdk_python_path)
    print_search_roots(search_roots)
    found = search_qmix_dlls(search_roots)
    print_dll_search_results(found)

    missing = [dll_name for dll_name, paths in found.items() if not paths]
    dll_directories = directories_containing_qmix_dlls(found)
    if dll_directories:
        print_step("directories containing one or more Qmix DLLs")
        for directory in dll_directories:
            print_value("Qmix DLL directory", directory)
        add_windows_dll_directories(dll_directories)
    else:
        print_step("no directories containing required Qmix DLLs were found")

    if missing:
        details = "; ".join(f"{name}: {found.get(name, []) or '<missing>'}" for name in QMIX_REQUIRED_DLLS)
        raise FileNotFoundError(f"Missing required Qmix DLLs: {', '.join(missing)}. Search results: {details}")

    complete_directories = common_complete_dll_directories(found)
    if not complete_directories:
        details = "; ".join(f"{name}: {[str(path) for path in found.get(name, [])]}" for name in QMIX_REQUIRED_DLLS)
        raise FileNotFoundError(
            "Found required Qmix DLLs, but no single directory contains all required DLLs. "
            "The qmixsdk loader requires one QMIXSDK directory containing both DLLs. "
            f"Search results: {details}"
        )

    selected = complete_directories[0]
    original_qmixsdk = os.environ.get("QMIXSDK")
    if original_qmixsdk:
        print_step(f"QMIXSDK was already set before import: {original_qmixsdk}")
    if not original_qmixsdk or Path(original_qmixsdk).resolve() != selected.resolve():
        os.environ["QMIXSDK"] = str(selected)
        print_step(f"QMIXSDK set by this script before import: {selected}")
    else:
        print_step("QMIXSDK already points to a directory containing the required DLLs")


def import_qmix(sdk_python_path: Path) -> tuple[Any, Any]:
    validate_path("Qmix SDK Python wrapper path", sdk_python_path)
    text_path = str(sdk_python_path)
    if text_path not in sys.path:
        print_step(f"adding Qmix SDK Python wrapper path: {sdk_python_path}")
        sys.path.insert(0, text_path)

    prepare_qmix_dll_loading(sdk_python_path)
    print_step("importing qmixsdk.qmixbus and qmixsdk.qmixpump")
    from qmixsdk import qmixbus, qmixpump

    print_value("qmixbus module", getattr(qmixbus, "__file__", "<unknown>"))
    print_value("qmixpump module", getattr(qmixpump, "__file__", "<unknown>"))
    return qmixbus, qmixpump


def read_passive(label: str, action: Any) -> None:
    try:
        print_value(label, action())
    except Exception as exc:
        print_value(label, f"<unavailable: {exc}>")


def read_pump_identity(qmixpump: Any, pump_index: int) -> None:
    print_step(f"creating passive pump handle for index {pump_index}")
    pump = qmixpump.Pump()

    print_step(f"looking up pump by device index {pump_index}")
    pump.lookup_by_device_index(pump_index)

    print_step("reading passive pump identity")
    read_passive("pump name", pump.get_pump_name)
    read_passive("device name", pump.get_device_name)
    read_passive("node id", pump.get_node_id)

    print_step("reading passive pump status/configuration")
    read_passive("is pumping", pump.is_pumping)
    read_passive("is enabled", pump.is_enabled)
    read_passive("is in fault state", pump.is_in_fault_state)
    read_passive("position sensing initialized", pump.is_position_sensing_initialized)
    read_passive("syringe parameters", pump.get_syringe_param)
    read_passive("volume max", pump.get_volume_max)
    read_passive("flow rate max", pump.get_flow_rate_max)
    read_passive("volume unit", pump.get_volume_unit)
    read_passive("flow unit", pump.get_flow_unit)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Qmix/Cetoni discovery-only test. Default mode validates the SDK "
            "wrapper and config path, opens the bus, reads passive pump "
            "identity/status if available, and closes the bus. It does not "
            "start flow, enable the pump, calibrate, reference, dose, aspirate, "
            "dispense, clear faults, or move liquid."
        )
    )
    parser.add_argument(
        "--sdk-python-path",
        type=Path,
        default=DEFAULT_SDK_PYTHON_PATH,
        help=f"Path containing the qmixsdk package. Default: {DEFAULT_SDK_PYTHON_PATH}",
    )
    parser.add_argument(
        "--config-path",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"QmixElements project/config path for Bus.open. Default: {DEFAULT_CONFIG_PATH}",
    )
    parser.add_argument("--pump-index", type=int, default=0, help="Pump index to inspect if pumps are found. Default: 0.")
    parser.add_argument(
        "--start-communication",
        action="store_true",
        help=(
            "Opt-in Bus.start() before passive pump readback. This still does "
            "not enable, move, dose, calibrate, reference, or clear faults."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    qmixbus = None
    qmixpump = None
    bus_opened = False
    communication_started = False

    print_step("starting Qmix/Cetoni discovery test")
    print_step("default behavior opens the bus without starting communication")
    print_step("this script does not enable, move, dose, aspirate, dispense, calibrate, reference, clear faults, or move liquid")
    print_step("Pump.stop_all_pumps() is intentionally not called")

    try:
        qmixbus, qmixpump = import_qmix(args.sdk_python_path)
        validate_path("Qmix config path", args.config_path)

        print_step("opening Qmix bus")
        qmixbus.Bus.open(str(args.config_path), 0)
        bus_opened = True
        print_step("Qmix bus opened")

        if args.start_communication:
            print_step("starting Qmix bus communication because --start-communication was provided")
            qmixbus.Bus.start()
            communication_started = True
            print_step("Qmix bus communication started")
        else:
            print_step("skipping Bus.start() because --start-communication was not provided")

        print_step("reading pump count")
        pump_count = qmixpump.Pump.get_no_of_pumps()
        print_value("pump count", pump_count)

        if int(pump_count) <= 0:
            print_step("no Qmix pumps found; discovery test complete")
            return 0
        if args.pump_index < 0 or args.pump_index >= int(pump_count):
            raise ValueError(f"pump index {args.pump_index} is outside available range 0..{int(pump_count) - 1}")

        read_pump_identity(qmixpump, args.pump_index)
        print_step("Qmix/Cetoni discovery test completed successfully")
        return 0
    except Exception as exc:
        print_step(f"ERROR: {exc}")
        return 1
    finally:
        print_step("entering cleanup")
        if qmixbus is not None:
            if communication_started:
                safe_call("Bus.stop", qmixbus.Bus.stop)
            else:
                print_step("cleanup: Bus.stop skipped because communication was not started")
            if bus_opened:
                safe_call("Bus.close", qmixbus.Bus.close)
            else:
                print_step("cleanup: Bus.close skipped because bus was not opened")
        else:
            print_step("cleanup: Qmix modules were not imported")
        print_step("cleanup finished")


if __name__ == "__main__":
    raise SystemExit(main())
