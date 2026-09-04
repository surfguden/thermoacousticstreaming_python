from __future__ import annotations

import os
from pathlib import Path

import pytest

from thermo_acoustic import hardware_factory
from thermo_acoustic.hardware_config import default_hardware_config
from thermo_acoustic.hardware_factory import HardwareRuntimeConfig, build_hardware_bundle
from thermo_acoustic.instruments import AD2Sdk, SimulatedAD2Sdk, ZStage
from thermo_acoustic.tec import MeerstetterTecBackend, SimulatedTecBackend, TecController
from thermo_acoustic.thorlabs_piezo import PiezoStage


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
        "thorlabs_apt_serial": "44533854",
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
    def __init__(self, **kwargs):
        pass


def test_factory_builds_simulated_safe_defaults_without_real_backends():
    bundle = build_hardware_bundle(runtime_config())

    assert isinstance(bundle.ad2, SimulatedAD2Sdk)
    assert bundle.camera.backend is None
    assert bundle.pump.backend is None
    assert bundle.valve.backend is None
    assert isinstance(bundle.z_motor, ZStage)
    assert bundle.z_motor.enabled is False
    assert isinstance(bundle.z_motor.stage, PiezoStage)
    assert bundle.z_motor.stage.serial_number == "44533854"
    assert bundle.z_motor.stage.connected is False
    assert bundle.pump.configuration_path == Path(r"C:\configs\one-pump")
    assert isinstance(bundle.tec, TecController)
    assert bundle.tec.enabled is False
    assert isinstance(bundle.tec.backend, SimulatedTecBackend)


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
            valve_resource="COM5",
            z_enabled=True,
        )
    )

    assert isinstance(bundle.ad2, AD2Sdk)
    assert not isinstance(bundle.ad2, SimulatedAD2Sdk)
    assert isinstance(bundle.camera.backend, FakeHamamatsuBackend)
    assert isinstance(bundle.pump.backend, FakeQmixBackend)
    assert isinstance(bundle.valve.backend, FakeSerialBackend)
    # Z-stage never used SerialTextCommandBackend at all (that was the
    # retired PriorZMotor/COM7 path) -- it always connects via the real
    # thorlabs_piezo.PiezoStage, enabled/disabled by ZStage.enabled alone.
    assert isinstance(bundle.z_motor, ZStage)
    assert bundle.z_motor.enabled is True
    assert isinstance(bundle.z_motor.stage, PiezoStage)
    assert isinstance(bundle.tec.backend, SimulatedTecBackend)


def test_factory_builds_real_tec_adapter_only_when_enabled_and_not_simulated():
    bundle = build_hardware_bundle(runtime_config(tec_enabled=True, sim_tec=False, tec_port="COM9"))

    assert bundle.tec.enabled is True
    assert bundle.tec.simulate is False
    assert isinstance(bundle.tec.backend, MeerstetterTecBackend)
    assert bundle.tec.backend.port == "COM9"


def test_factory_rejects_com6_as_live_valve_without_opening_hardware():
    with pytest.raises(ValueError, match="COM6 is reserved for TEC"):
        build_hardware_bundle(runtime_config(valve_enabled=True, sim_valve=False, valve_resource="COM6"))


def test_factory_preserves_com6_for_tec_and_simulated_valve_fixture():
    bundle = build_hardware_bundle(
        runtime_config(
            valve_enabled=False,
            sim_valve=True,
            tec_enabled=True,
            sim_tec=False,
            tec_port="COM6",
        )
    )

    assert bundle.valve.backend is None
    assert bundle.tec.backend.port == "COM6"


def test_factory_keeps_z_stage_disabled_when_z_is_off(monkeypatch):
    monkeypatch.setattr(hardware_factory, "SerialTextCommandBackend", FakeSerialBackend)

    bundle = build_hardware_bundle(runtime_config(z_enabled=False, sim_valve=False, valve_resource="COM5"))

    assert isinstance(bundle.valve.backend, FakeSerialBackend)
    assert bundle.z_motor.enabled is False
    assert bundle.z_motor.stage.connected is False


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
