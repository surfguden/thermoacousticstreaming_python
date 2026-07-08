from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SDK_PYTHON_PATH = ROOT / "dcamsdk4" / "samples" / "python"


def print_step(message: str) -> None:
    print(f"[hamamatsu-discovery] {message}", flush=True)


def print_value(label: str, value: object) -> None:
    print(f"  {label}: {value}", flush=True)


def safe_call(label: str, action: Any) -> None:
    try:
        result = action()
        if result is False:
            print_step(f"cleanup warning: {label} returned False")
        else:
            print_step(f"cleanup ok: {label}")
    except Exception as exc:
        print_step(f"cleanup warning: {label} failed: {exc}")


def require_capture_confirmation() -> None:
    print()
    print_step("--capture-one-frame was requested.")
    print_step("This will acquire exactly one camera frame. No trigger mode or light source will be configured.")
    print_step("Type CAPTURE to continue, or anything else to abort acquisition.")
    response = input("Confirm one-frame acquisition [CAPTURE]: ").strip()
    if response != "CAPTURE":
        raise RuntimeError("One-frame acquisition was not confirmed by the operator.")


def import_dcam(sdk_python_path: Path) -> Any:
    print_step(f"adding DCAM Python wrapper path: {sdk_python_path}")
    if not sdk_python_path.exists():
        raise FileNotFoundError(f"DCAM Python wrapper path does not exist: {sdk_python_path}")
    text_path = str(sdk_python_path)
    if text_path not in sys.path:
        sys.path.insert(0, text_path)

    print_step("importing dcam wrapper")
    import dcam as dcam_module

    print_value("dcam module", getattr(dcam_module, "__file__", "<unknown>"))
    return dcam_module


def error_text(owner: Any) -> str:
    try:
        return str(owner.lasterr())
    except Exception as exc:
        return f"<could not read last error: {exc}>"


def check_ok(ok: object, operation: str, owner: Any) -> None:
    if ok is False:
        raise RuntimeError(f"{operation} failed: {error_text(owner)}")


def read_device_strings(dcam_module: Any, camera: Any) -> None:
    print_step("reading safe camera identity strings")
    for name in ("BUS", "CAMERAID", "VENDOR", "MODEL", "CAMERAVERSION", "DRIVERVERSION", "MODULEVERSION"):
        idstr = getattr(dcam_module.DCAM_IDSTR, name, None)
        if idstr is None:
            continue
        value = camera.dev_getstring(idstr)
        if value is False:
            print_value(name, f"<unavailable: {error_text(camera)}>")
        else:
            print_value(name, value)


def read_property(dcam_module: Any, camera: Any, name: str) -> None:
    idprop = getattr(dcam_module.DCAM_IDPROP, name, None)
    if idprop is None:
        return
    value = camera.prop_getvalue(idprop)
    if value is False:
        print_value(name, f"<unavailable: {error_text(camera)}>")
        return

    text = None
    try:
        text = camera.prop_getvaluetext(idprop, value)
    except Exception:
        text = None
    if text:
        print_value(name, f"{value} ({text})")
    else:
        print_value(name, value)


def read_safe_properties(dcam_module: Any, camera: Any) -> None:
    print_step("reading safe camera properties")
    for name in (
        "IMAGE_WIDTH",
        "IMAGE_HEIGHT",
        "IMAGE_ROWBYTES",
        "IMAGE_PIXELTYPE",
        "EXPOSURETIME",
        "TIMING_READOUTTIME",
        "TRIGGERSOURCE",
        "SUBARRAYMODE",
        "SUBARRAYHPOS",
        "SUBARRAYVPOS",
        "SUBARRAYHSIZE",
        "SUBARRAYVSIZE",
        "SENSORTEMPERATURE",
        "SENSORCOOLERSTATUS",
    ):
        read_property(dcam_module, camera, name)


def capture_one_frame(camera: Any, timeout_ms: int) -> bool:
    print_step("allocating one-frame buffer")
    check_ok(camera.buf_alloc(1), "Dcam.buf_alloc", camera)
    buffer_allocated = True

    print_step("starting one-frame snapshot acquisition")
    check_ok(camera.cap_snapshot(), "Dcam.cap_snapshot", camera)
    capture_started = True

    print_step(f"waiting for frame-ready event, timeout {timeout_ms} ms")
    check_ok(camera.wait_capevent_frameready(timeout_ms), "Dcam.wait_capevent_frameready", camera)

    print_step("reading last frame metadata")
    frame = camera.buf_getlastframedata()
    check_ok(frame, "Dcam.buf_getlastframedata", camera)
    print_value("frame type", type(frame).__name__)
    print_value("frame shape", getattr(frame, "shape", "<unknown>"))
    print_value("frame dtype", getattr(frame, "dtype", "<unknown>"))
    return buffer_allocated and capture_started


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Hamamatsu DCAM discovery-only test. By default this imports DCAM, "
            "initializes the SDK, counts cameras, opens one camera, reads safe "
            "identity/properties, closes it, and uninitializes DCAM."
        )
    )
    parser.add_argument("--device-index", type=int, default=0, help="Camera device index to open. Default: 0.")
    parser.add_argument(
        "--sdk-python-path",
        type=Path,
        default=DEFAULT_SDK_PYTHON_PATH,
        help=f"Path containing dcam.py. Default: {DEFAULT_SDK_PYTHON_PATH}",
    )
    parser.add_argument(
        "--capture-one-frame",
        action="store_true",
        help="Opt-in one-frame acquisition. Requires typed confirmation before capture.",
    )
    parser.add_argument("--timeout-ms", type=int, default=1000, help="Frame wait timeout for opt-in capture. Default: 1000.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dcam_module = None
    dcamapi = None
    camera = None
    api_initialized = False
    camera_opened = False
    capture_requested = bool(args.capture_one_frame)

    print_step("starting Hamamatsu DCAM discovery test")
    print_step("default behavior is discovery-only; no acquisition is performed unless --capture-one-frame is confirmed")
    print_step("this script does not configure external trigger, laser, LED, stage, pump, valve, AD2 output, or acoustic drive")

    try:
        dcam_module = import_dcam(args.sdk_python_path)
        dcamapi = dcam_module.Dcamapi

        print_step("initializing DCAM API")
        check_ok(dcamapi.init(), "Dcamapi.init", dcamapi)
        api_initialized = True

        print_step("reading camera count")
        camera_count = dcamapi.get_devicecount()
        if camera_count is False:
            raise RuntimeError(f"Dcamapi.get_devicecount failed: {error_text(dcamapi)}")
        print_value("camera count", camera_count)
        if int(camera_count) <= 0:
            print_step("no cameras found; discovery test complete")
            return 0
        if args.device_index < 0 or args.device_index >= int(camera_count):
            raise ValueError(f"device index {args.device_index} is outside available range 0..{int(camera_count) - 1}")

        print_step(f"creating camera object for device index {args.device_index}")
        camera = dcam_module.Dcam(args.device_index)

        print_step("opening camera")
        check_ok(camera.dev_open(), "Dcam.dev_open", camera)
        camera_opened = True
        print_value("is opened", camera.is_opened())

        read_device_strings(dcam_module, camera)
        read_safe_properties(dcam_module, camera)

        if capture_requested:
            require_capture_confirmation()
            capture_one_frame(camera, max(int(args.timeout_ms), 1))
        else:
            print_step("skipping acquisition because --capture-one-frame was not provided")

        print_step("discovery test completed successfully")
        return 0
    except Exception as exc:
        print_step(f"ERROR: {exc}")
        return 1
    finally:
        print_step("entering cleanup")
        if camera is not None and camera_opened:
            if capture_requested:
                safe_call("stop capture", camera.cap_stop)
                safe_call("release camera buffer", camera.buf_release)
            safe_call("close camera", camera.dev_close)
        elif camera is not None:
            print_step("cleanup: camera object existed but was not opened")
        if dcamapi is not None and api_initialized:
            safe_call("uninitialize DCAM API", dcamapi.uninit)
        else:
            print_step("cleanup: DCAM API was not initialized")
        print_step("cleanup finished")


if __name__ == "__main__":
    raise SystemExit(main())
