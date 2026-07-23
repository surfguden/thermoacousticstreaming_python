from __future__ import annotations

import argparse
import math
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from thermo_acoustic.hamamatsu_dcam import HamamatsuDcamBackend


CONFIRM_TEXT = "READONLY_PROBE"


def print_step(message: str) -> None:
    print(f"[dcam-property-discovery] {message}", flush=True)


def print_value(label: str, value: object) -> None:
    print(f"  {label}: {value}", flush=True)


def error_text(camera: Any) -> str:
    try:
        return str(camera.lasterr())
    except Exception as exc:
        return f"<could not read last error: {exc}>"


def enum_name(value: object) -> str:
    return getattr(value, "name", str(value))


def enum_int(value: object) -> int:
    return int(value)


def value_text(camera: Any, idprop: object, value: float | int) -> str:
    try:
        text = camera.prop_getvaluetext(idprop, float(value))
    except Exception as exc:
        return f"<value text unavailable: {exc}>"
    if text is False:
        return f"<value text unavailable: {error_text(camera)}>"
    return str(text)


def property_name(camera: Any, idprop: object) -> str:
    try:
        name = camera.prop_getname(idprop)
    except Exception as exc:
        return f"<property name unavailable: {exc}>"
    if name is False:
        return f"<property name unavailable: {error_text(camera)}>"
    return str(name)


def read_device_strings(backend: HamamatsuDcamBackend) -> None:
    dcam_module = backend.dcam_module
    camera = backend.dcam
    if dcam_module is None or camera is None:
        return
    print_step("reading camera identity strings")
    for name in ("BUS", "CAMERAID", "VENDOR", "MODEL", "CAMERAVERSION", "DRIVERVERSION", "MODULEVERSION"):
        idstr = getattr(dcam_module.DCAM_IDSTR, name, None)
        if idstr is None:
            continue
        value = camera.dev_getstring(idstr)
        if value is False:
            print_value(name, f"<unavailable: {error_text(camera)}>")
        else:
            print_value(name, value)


def collect_property_candidates(dcam_module: Any) -> list[tuple[str, object]]:
    idprops = dcam_module.DCAM_IDPROP
    requested_names = [
        "TRIGGER_GLOBALEXPOSURE",
        "SENSORMODE",
        "READOUTSPEED",
        "SHUTTER_MODE",
    ]
    candidates: dict[str, object] = {}
    for name in requested_names:
        value = getattr(idprops, name, None)
        if value is not None:
            candidates[name] = value
    for prop in idprops:
        name = enum_name(prop)
        if "GLOBAL" in name.upper():
            candidates.setdefault(name, prop)
    return sorted(candidates.items(), key=lambda item: enum_int(item[1]))


def related_dcamprop_enums(dcam_module: Any, property_name_hint: str) -> list[tuple[str, list[tuple[str, int]]]]:
    dcamprop = dcam_module.DCAMPROP
    normalized_hint = property_name_hint.upper()
    related: list[tuple[str, list[tuple[str, int]]]] = []
    for class_name in dir(dcamprop):
        if class_name.startswith("_"):
            continue
        enum_class = getattr(dcamprop, class_name)
        if not hasattr(enum_class, "__iter__"):
            continue
        members: list[tuple[str, int]] = []
        try:
            iterable = list(enum_class)
        except TypeError:
            continue
        for member in iterable:
            member_name = enum_name(member)
            if "GLOBAL" in class_name.upper() or "GLOBAL" in member_name.upper() or class_name.upper() in normalized_hint:
                members.append((member_name, enum_int(member)))
        if members:
            related.append((class_name, members))
    return related


def print_related_enums(dcam_module: Any, property_name_hint: str) -> None:
    related = related_dcamprop_enums(dcam_module, property_name_hint)
    if not related:
        print_value("related DCAMPROP enum values", "<none found in Python bindings>")
        return
    print_value("related DCAMPROP enum values", "")
    for class_name, members in related:
        print(f"    {class_name}:", flush=True)
        for member_name, member_value in members:
            print(f"      {member_name} = {member_value}", flush=True)


def is_nearly_integer(value: float) -> bool:
    return math.isfinite(value) and abs(value - round(value)) < 1e-9


def attr_values(attr: Any) -> list[float]:
    try:
        min_value = float(attr.valuemin)
        max_value = float(attr.valuemax)
        step = float(attr.valuestep)
    except Exception:
        return []
    if not all(math.isfinite(value) for value in (min_value, max_value, step)):
        return []
    if step <= 0 or max_value < min_value:
        return []
    count = int(round((max_value - min_value) / step)) + 1
    if count <= 0 or count > 128:
        return []
    values = [min_value + index * step for index in range(count)]
    if all(is_nearly_integer(value) for value in values):
        return [float(int(round(value))) for value in values]
    return values


def query_neighbor_values(camera: Any, dcam_module: Any, idprop: object, start_value: float) -> list[float]:
    option = dcam_module.DCAMPROP_OPTION
    values = {float(start_value)}
    for direction in (option.PRIOR, option.NEXT):
        value = float(start_value)
        for _ in range(64):
            try:
                queried = camera.prop_queryvalue(idprop, value, direction)
            except Exception:
                break
            if queried is False:
                break
            queried = float(queried)
            if queried in values:
                break
            values.add(queried)
            value = queried
    return sorted(values)


def print_value_list(camera: Any, idprop: object, values: list[float]) -> None:
    if not values:
        print_value("valid values", "<could not enumerate discrete values; see min/max/step above>")
        return
    print_value("valid/queryable values", "")
    for value in values:
        text = value_text(camera, idprop, value)
        if is_nearly_integer(value):
            display_value = int(round(value))
        else:
            display_value = value
        print(f"    {display_value}: {text}", flush=True)


def inspect_property(backend: HamamatsuDcamBackend, enum_name_hint: str, idprop: object) -> None:
    dcam_module = backend.dcam_module
    camera = backend.dcam
    if dcam_module is None or camera is None:
        raise RuntimeError("DCAM backend was not opened.")

    prop_id = enum_int(idprop)
    print()
    print_step(f"property {enum_name_hint}")
    print_value("property ID", f"{prop_id} / 0x{prop_id:08X}")

    attr = camera.prop_getattr(idprop)
    if attr is False:
        print_value("support", f"not supported on this camera ({error_text(camera)})")
        print_related_enums(dcam_module, enum_name_hint)
        return

    print_value("support", "supported")
    print_value("camera property name", property_name(camera, idprop))
    for method_name in ("is_readable", "is_writable", "is_effective"):
        try:
            print_value(method_name.removeprefix("is_"), getattr(attr, method_name)())
        except Exception:
            pass
    print_value("min", getattr(attr, "valuemin", "<unknown>"))
    print_value("max", getattr(attr, "valuemax", "<unknown>"))
    print_value("step", getattr(attr, "valuestep", "<unknown>"))
    print_value("default", getattr(attr, "valuedefault", "<unknown>"))

    current = camera.prop_getvalue(idprop)
    if current is False:
        print_value("current value", f"<unavailable: {error_text(camera)}>")
        current_values: list[float] = []
    else:
        print_value("current value", current)
        print_value("current value text", value_text(camera, idprop, float(current)))
        current_values = query_neighbor_values(camera, dcam_module, idprop, float(current))

    values = attr_values(attr)
    if current_values:
        values = sorted(set(values) | set(current_values))
    print_value_list(camera, idprop, values)
    print_related_enums(dcam_module, enum_name_hint)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only Hamamatsu DCAM property discovery for global-exposure/global-reset/global-shutter "
            "related camera properties. This opens the camera, queries properties, and closes it."
        )
    )
    parser.add_argument("--confirm", default="", help=f"Required confirmation token: {CONFIRM_TEXT}")
    parser.add_argument("--device-index", type=int, default=0, help="Camera device index. Default: 0.")
    parser.add_argument(
        "--sdk-python-path",
        type=Path,
        default=None,
        help="Optional path containing dcam.py. Defaults to the repository's dcamsdk4 samples path.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print_step(
        "This script only reads camera properties. It does not change camera state, does not trigger "
        "acquisition, and does not move any other hardware."
    )
    if args.confirm != CONFIRM_TEXT:
        print_step(f"refusing to run without --confirm {CONFIRM_TEXT}")
        return 2

    backend = HamamatsuDcamBackend(device_index=args.device_index)
    if args.sdk_python_path is not None:
        backend.sdk_python_path = args.sdk_python_path

    try:
        print_step("opening Hamamatsu camera through HamamatsuDcamBackend")
        backend.open_camera()
        read_device_strings(backend)

        dcam_module = backend.dcam_module
        if dcam_module is None:
            raise RuntimeError("DCAM module was not loaded.")
        candidates = collect_property_candidates(dcam_module)
        print()
        print_step("candidate properties to query")
        for name, idprop in candidates:
            prop_id = enum_int(idprop)
            print(f"  {name}: {prop_id} / 0x{prop_id:08X}", flush=True)

        for name, idprop in candidates:
            inspect_property(backend, name, idprop)

        print()
        print_step("read-only DCAM property discovery completed")
        return 0
    except Exception as exc:
        print_step(f"ERROR: {exc}")
        return 1
    finally:
        print_step("entering cleanup")
        try:
            backend.close()
            print_step("cleanup ok: backend.close() stopped capture if needed, released buffers, closed camera, and uninitialized DCAM")
        except Exception as exc:
            print_step(f"cleanup warning: backend.close() failed: {exc}")
        print_step("cleanup finished")


if __name__ == "__main__":
    raise SystemExit(main())
