from __future__ import annotations

import os
from pathlib import Path

from thermo_acoustic import hardware_factory
from thermo_acoustic.hardware_config import default_hardware_config
from thermo_acoustic.hardware_factory import HardwareRuntimeConfig, build_hardware_bundle
from thermo_acoustic.instruments import AD2Sdk, PriorZMotor, SimulatedAD2Sdk


def runtime_config(**overrides) -> HardwareRuntimeConfig:
    values = {
        "ad2_enabled": True,
        "sim_ad2": True,
        "camera_enabled": True,
        "sim_camera": True,
        "pump_enabled": True,
        "sim_pump": True,
        "valve_enabled": True,
        "sim_valve": True,
        "z_enabled": False,
        "prior_resource": "COM7",
        "valve_resource": "COM6",
        "cetoni_config_path": r"C:\configs\one-pump",
    }
    values.update(overrides)
    return HardwareRuntimeConfig(**values)


class FakeHamamatsuBackend:
    pass


class FakeQmixBackend:
    pass


class FakeSerialBackend:
    pass


def test_factory_builds_simulated_safe_defaults_without_real_backends():
    bundle = build_hardware_bundle(runtime_config())

    assert isinstance(bundle.ad2, SimulatedAD2Sdk)
    assert bundle.camera.backend is None
    assert bundle.pump.backend is None
    assert bundle.valve.backend is None
    assert isinstance(bundle.z_motor, PriorZMotor)
    assert bundle.z_motor.backend is None
    assert bundle.z_motor.visa_resource == "COM7"
    assert bundle.pump.configuration_path == Path(r"C:\configs\one-pump")


def test_factory_selects_real_backend_classes_when_simulation_is_disabled(monkeypatch):
    monkeypatch.setattr(hardware_factory, "HamamatsuDcamBackend", FakeHamamatsuBackend)
    monkeypatch.setattr(hardware_factory, "QmixPumpBackend", FakeQmixBackend)
    monkeypatch.setattr(hardware_factory, "SerialTextCommandBackend", FakeSerialBackend)

    bundle = build_hardware_bundle(
        runtime_config(
            sim_ad2=False,
            sim_camera=False,
            sim_pump=False,
            sim_valve=False,
            z_enabled=True,
        )
    )

    assert isinstance(bundle.ad2, AD2Sdk)
    assert not isinstance(bundle.ad2, SimulatedAD2Sdk)
    assert isinstance(bundle.camera.backend, FakeHamamatsuBackend)
    assert isinstance(bundle.pump.backend, FakeQmixBackend)
    assert isinstance(bundle.valve.backend, FakeSerialBackend)
    assert isinstance(bundle.z_motor.backend, FakeSerialBackend)


def test_factory_keeps_prior_z_serial_backend_disabled_when_z_is_off(monkeypatch):
    monkeypatch.setattr(hardware_factory, "SerialTextCommandBackend", FakeSerialBackend)

    bundle = build_hardware_bundle(runtime_config(z_enabled=False, sim_valve=False))

    assert isinstance(bundle.valve.backend, FakeSerialBackend)
    assert bundle.z_motor.backend is None


def test_build_hardware_bundle_sets_qmixsdk_env_for_real_pump(monkeypatch):
    monkeypatch.delenv("QMIXSDK", raising=False)

    build_hardware_bundle(runtime_config(sim_pump=False))

    assert os.environ["QMIXSDK"] == str(default_hardware_config().qmix.qmixsdk_path)


def test_build_hardware_bundle_does_not_override_existing_qmixsdk_env(monkeypatch):
    monkeypatch.setenv("QMIXSDK", r"C:\already\set\by\operator")

    build_hardware_bundle(runtime_config(sim_pump=False))

    assert os.environ["QMIXSDK"] == r"C:\already\set\by\operator"


def test_build_hardware_bundle_leaves_qmixsdk_env_unset_for_simulated_pump(monkeypatch):
    monkeypatch.delenv("QMIXSDK", raising=False)

    build_hardware_bundle(runtime_config(sim_pump=True))

    assert "QMIXSDK" not in os.environ
