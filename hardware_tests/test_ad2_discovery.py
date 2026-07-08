from __future__ import annotations

import argparse
import ctypes
from ctypes import byref, c_char, c_int, create_string_buffer
from ctypes.util import find_library
from pathlib import Path
from typing import Iterable


def print_step(message: str) -> None:
    print(f"[ad2-discovery] {message}", flush=True)


def print_value(label: str, value: object) -> None:
    print(f"  {label}: {value}", flush=True)


def candidate_libraries() -> Iterable[str | Path]:
    for name in ("dwf", "dwf.dll"):
        found = find_library(name)
        if found:
            yield found
    yield Path(r"C:\Windows\System32\dwf.dll")
    yield Path(r"C:\Windows\SysWOW64\dwf.dll")
    yield Path(r"C:\Program Files\Digilent\WaveFormsSDK\lib\x64\dwf.dll")
    yield Path(r"C:\Program Files (x86)\Digilent\WaveFormsSDK\lib\x86\dwf.dll")


def resolve_library(library_path: Path | None) -> str:
    if library_path is not None:
        if not library_path.exists():
            raise FileNotFoundError(f"WaveForms SDK DLL was not found: {library_path}")
        return str(library_path)

    for candidate in candidate_libraries():
        if isinstance(candidate, Path):
            if candidate.exists():
                return str(candidate)
        else:
            return candidate
    raise FileNotFoundError("Could not find dwf.dll. Install Digilent WaveForms or pass --library-path.")


def load_dwf(library_path: Path | None) -> ctypes.CDLL:
    resolved = resolve_library(library_path)
    print_step(f"loading WaveForms SDK DLL: {resolved}")
    loader = ctypes.WinDLL if hasattr(ctypes, "WinDLL") else ctypes.CDLL
    dwf = loader(resolved)
    bind_signatures(dwf)
    return dwf


def bind_signatures(dwf: ctypes.CDLL) -> None:
    signatures = {
        "FDwfGetLastErrorMsg": ([ctypes.POINTER(c_char)], c_int),
        "FDwfEnum": ([c_int, ctypes.POINTER(c_int)], c_int),
        "FDwfEnumDeviceName": ([c_int, ctypes.POINTER(c_char)], c_int),
        "FDwfEnumSN": ([c_int, ctypes.POINTER(c_char)], c_int),
        "FDwfEnumDeviceIsOpened": ([c_int, ctypes.POINTER(c_int)], c_int),
        "FDwfDeviceOpen": ([c_int, ctypes.POINTER(c_int)], c_int),
        "FDwfDeviceClose": ([c_int], c_int),
        "FDwfDeviceCloseAll": ([], c_int),
        "FDwfDeviceReset": ([c_int], c_int),
        "FDwfAnalogOutReset": ([c_int, c_int], c_int),
        "FDwfDigitalOutReset": ([c_int], c_int),
    }
    for name, (argtypes, restype) in signatures.items():
        try:
            function = getattr(dwf, name)
        except AttributeError:
            print_step(f"warning: {name} is not available in this WaveForms DLL")
            continue
        function.argtypes = argtypes
        function.restype = restype


def last_error(dwf: ctypes.CDLL) -> str:
    buffer = create_string_buffer(512)
    try:
        dwf.FDwfGetLastErrorMsg(buffer)
        return buffer.value.decode(errors="replace")
    except Exception as exc:
        return f"<could not read WaveForms error: {exc}>"


def check_ok(dwf: ctypes.CDLL, result: int, operation: str) -> None:
    if not result:
        raise RuntimeError(f"{operation} failed: {last_error(dwf)}")


def safe_call(dwf: ctypes.CDLL, label: str, action: object) -> None:
    try:
        result = action()
        if not result:
            print_step(f"cleanup warning: {label} failed: {last_error(dwf)}")
        else:
            print_step(f"cleanup ok: {label}")
    except AttributeError:
        print_step(f"cleanup skipped: {label} is unavailable")
    except Exception as exc:
        print_step(f"cleanup warning: {label} raised: {exc}")


def read_string(dwf: ctypes.CDLL, operation: str, index: int) -> str:
    buffer = create_string_buffer(64)
    function = getattr(dwf, operation)
    result = function(c_int(index), buffer)
    if not result:
        return f"<unavailable: {last_error(dwf)}>"
    return buffer.value.decode(errors="replace")


def read_opened_state(dwf: ctypes.CDLL, index: int) -> str:
    opened = c_int()
    result = dwf.FDwfEnumDeviceIsOpened(c_int(index), byref(opened))
    if not result:
        return f"<unavailable: {last_error(dwf)}>"
    return str(bool(opened.value))


def enumerate_devices(dwf: ctypes.CDLL) -> int:
    print_step("enumerating WaveForms devices")
    count = c_int()
    check_ok(dwf, dwf.FDwfEnum(c_int(0), byref(count)), "FDwfEnum")
    print_value("device count", count.value)

    for index in range(count.value):
        print_step(f"reading device {index}")
        print_value("index", index)
        print_value("name", read_string(dwf, "FDwfEnumDeviceName", index))
        print_value("serial", read_string(dwf, "FDwfEnumSN", index))
        print_value("opened", read_opened_state(dwf, index))
    return count.value


def open_close_device(dwf: ctypes.CDLL, device_index: int) -> int:
    print_step(f"opening device index {device_index}")
    handle = c_int()
    check_ok(dwf, dwf.FDwfDeviceOpen(c_int(device_index), byref(handle)), "FDwfDeviceOpen")
    if handle.value == 0:
        raise RuntimeError("FDwfDeviceOpen returned an empty device handle.")
    print_value("handle", handle.value)
    print_step("device opened; no configure/start/trigger/output calls will be made")
    return handle.value


def reset_and_close_handle(dwf: ctypes.CDLL, handle: int) -> None:
    print_step("performing safe reset/disable cleanup for opened device")
    for channel_index in (0, 1):
        safe_call(
            dwf,
            f"FDwfAnalogOutReset channel {channel_index}",
            lambda channel_index=channel_index: dwf.FDwfAnalogOutReset(c_int(handle), c_int(channel_index)),
        )
    safe_call(dwf, "FDwfDigitalOutReset", lambda: dwf.FDwfDigitalOutReset(c_int(handle)))
    safe_call(dwf, "FDwfDeviceReset", lambda: dwf.FDwfDeviceReset(c_int(handle)))
    safe_call(dwf, "FDwfDeviceClose", lambda: dwf.FDwfDeviceClose(c_int(handle)))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Digilent WaveForms discovery-only test. Default mode loads dwf.dll, "
            "enumerates devices, prints name/serial/opened state, and closes all "
            "WaveForms handles in cleanup without opening any device."
        )
    )
    parser.add_argument("--library-path", type=Path, default=None, help="Explicit path to dwf.dll.")
    parser.add_argument("--device-index", type=int, default=0, help="Device index for --open-close. Default: 0.")
    parser.add_argument(
        "--open-close",
        action="store_true",
        help="Opt-in safe open/close test. No configure, start, trigger, or output calls are made.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dwf = None
    opened_handle: int | None = None

    print_step("starting Digilent AD2/AD3 WaveForms discovery test")
    print_step("default behavior is enumeration-only; no device is opened unless --open-close is passed")
    print_step("this script does not enable wavegen, analog output, digital output, trigger output, PC trigger, or acoustic drive")

    try:
        dwf = load_dwf(args.library_path)
        device_count = enumerate_devices(dwf)

        if args.open_close:
            if device_count <= 0:
                raise RuntimeError("Cannot open device because WaveForms enumerated zero devices.")
            if args.device_index < 0 or args.device_index >= device_count:
                raise ValueError(f"device index {args.device_index} is outside available range 0..{device_count - 1}")
            opened_handle = open_close_device(dwf, args.device_index)
        else:
            print_step("skipping open/close because --open-close was not provided")

        print_step("AD2/AD3 discovery test completed successfully")
        return 0
    except Exception as exc:
        print_step(f"ERROR: {exc}")
        return 1
    finally:
        print_step("entering cleanup")
        if dwf is not None:
            if opened_handle is not None:
                reset_and_close_handle(dwf, opened_handle)
                opened_handle = None
            safe_call(dwf, "FDwfDeviceCloseAll", lambda: dwf.FDwfDeviceCloseAll())
        else:
            print_step("cleanup: WaveForms DLL was not loaded")
        print_step("cleanup finished")


if __name__ == "__main__":
    raise SystemExit(main())
