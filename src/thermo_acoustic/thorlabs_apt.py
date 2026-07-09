from __future__ import annotations

from dataclasses import dataclass
import importlib.util
from typing import Any


@dataclass(frozen=True, slots=True)
class ThorlabsAptZStageConfig:
    serial_number: str | None = None
    require_pylablib: bool = False


@dataclass(frozen=True, slots=True)
class ThorlabsAptDeviceInfo:
    serial_number: str
    description: str | None = None
    model: str | None = None
    raw: object | None = None


@dataclass(frozen=True, slots=True)
class ThorlabsAptDiscoveryResult:
    pylablib_available: bool
    devices: list[ThorlabsAptDeviceInfo]
    error: str | None = None


def is_pylablib_available() -> bool:
    try:
        return importlib.util.find_spec("pylablib") is not None
    except (ImportError, AttributeError, ValueError):
        return False


def _text_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _attribute_text(device: object, names: tuple[str, ...]) -> str | None:
    for name in names:
        if not hasattr(device, name):
            continue
        try:
            value = getattr(device, name)
        except Exception:
            continue
        text = _text_or_none(value)
        if text is not None:
            return text
    return None


def _device_info_from_mapping(device: dict[str, Any]) -> ThorlabsAptDeviceInfo:
    serial_number = (
        _text_or_none(device.get("serial_number"))
        or _text_or_none(device.get("serial"))
        or _text_or_none(device.get("id"))
        or _text_or_none(device.get("device_id"))
        or repr(device)
    )
    description = (
        _text_or_none(device.get("description"))
        or _text_or_none(device.get("name"))
        or _text_or_none(device.get("type"))
    )
    model = _text_or_none(device.get("model")) or _text_or_none(device.get("device_type"))
    return ThorlabsAptDeviceInfo(
        serial_number=serial_number,
        description=description,
        model=model,
        raw=device,
    )


def _device_info_from_sequence(device: tuple[object, ...] | list[object]) -> ThorlabsAptDeviceInfo:
    serial_number = _text_or_none(device[0]) if device else None
    description = _text_or_none(device[1]) if len(device) > 1 else None
    model = _text_or_none(device[2]) if len(device) > 2 else None
    return ThorlabsAptDeviceInfo(
        serial_number=serial_number or repr(device),
        description=description,
        model=model,
        raw=device,
    )


def coerce_device_info(device: object) -> ThorlabsAptDeviceInfo:
    if isinstance(device, dict):
        return _device_info_from_mapping(device)
    if isinstance(device, (tuple, list)):
        return _device_info_from_sequence(device)

    serial_number = (
        _attribute_text(device, ("serial_number", "serial", "id", "device_id"))
        or _text_or_none(device)
        or repr(device)
    )
    description = _attribute_text(device, ("description", "name", "type"))
    model = _attribute_text(device, ("model", "device_type"))
    return ThorlabsAptDeviceInfo(
        serial_number=serial_number,
        description=description,
        model=model,
        raw=device,
    )


def discover_kinesis_devices(
    config: ThorlabsAptZStageConfig | None = None,
    *,
    thorlabs_module: object | None = None,
) -> ThorlabsAptDiscoveryResult:
    config = config or ThorlabsAptZStageConfig()
    pylablib_available = thorlabs_module is not None or is_pylablib_available()
    if not pylablib_available:
        error = "pylablib is not installed or importable." if config.require_pylablib else None
        return ThorlabsAptDiscoveryResult(pylablib_available=False, devices=[], error=error)

    try:
        if thorlabs_module is None:
            from pylablib.devices import Thorlabs

            thorlabs_module = Thorlabs
        devices = [
            coerce_device_info(device)
            for device in thorlabs_module.list_kinesis_devices()
        ]
    except Exception as exc:
        return ThorlabsAptDiscoveryResult(
            pylablib_available=pylablib_available,
            devices=[],
            error=str(exc),
        )

    if config.serial_number is not None:
        requested_serial = str(config.serial_number)
        devices = [device for device in devices if device.serial_number == requested_serial]
    return ThorlabsAptDiscoveryResult(
        pylablib_available=pylablib_available,
        devices=devices,
        error=None,
    )
