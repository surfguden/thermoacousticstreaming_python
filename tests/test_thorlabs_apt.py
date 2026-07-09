from __future__ import annotations

from thermo_acoustic import thorlabs_apt
from thermo_acoustic.thorlabs_apt import (
    ThorlabsAptZStageConfig,
    coerce_device_info,
    discover_kinesis_devices,
)


class FakeThorlabsModule:
    def __init__(self, devices):
        self.devices = devices
        self.calls = []

    def list_kinesis_devices(self):
        self.calls.append(("list_kinesis_devices",))
        return self.devices


def test_discover_kinesis_devices_with_fake_tuple_device():
    fake = FakeThorlabsModule([("44533854", "APT Piezo Controller")])

    result = discover_kinesis_devices(thorlabs_module=fake)

    assert result.pylablib_available
    assert result.error is None
    assert fake.calls == [("list_kinesis_devices",)]
    assert len(result.devices) == 1
    assert result.devices[0].serial_number == "44533854"
    assert result.devices[0].description == "APT Piezo Controller"


def test_discover_kinesis_devices_filters_by_serial_with_fake_module():
    fake = FakeThorlabsModule(
        [
            ("44533854", "APT Piezo Controller"),
            ("12345678", "Other Kinesis Device"),
        ]
    )

    result = discover_kinesis_devices(
        ThorlabsAptZStageConfig(serial_number="44533854"),
        thorlabs_module=fake,
    )

    assert result.error is None
    assert [device.serial_number for device in result.devices] == ["44533854"]


def test_discover_kinesis_devices_returns_passive_result_when_pylablib_missing(monkeypatch):
    monkeypatch.setattr(thorlabs_apt, "is_pylablib_available", lambda: False)

    result = discover_kinesis_devices()

    assert not result.pylablib_available
    assert result.devices == []
    assert result.error is None


def test_discover_kinesis_devices_reports_missing_required_pylablib(monkeypatch):
    monkeypatch.setattr(thorlabs_apt, "is_pylablib_available", lambda: False)

    result = discover_kinesis_devices(ThorlabsAptZStageConfig(require_pylablib=True))

    assert not result.pylablib_available
    assert result.devices == []
    assert result.error == "pylablib is not installed or importable."


def test_coerce_device_info_accepts_mapping_without_hardware_imports():
    info = coerce_device_info(
        {
            "serial_number": "44533854",
            "description": "APT Piezo Controller",
            "model": "Piezo",
        }
    )

    assert info.serial_number == "44533854"
    assert info.description == "APT Piezo Controller"
    assert info.model == "Piezo"
