from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .hamamatsu_dcam import HamamatsuDcamBackend
from .hardware_config import default_hardware_config
from .instruments import AD2Sdk, CetoniPump, HamamatsuCamera, SerialTextCommandBackend, SimulatedAD2Sdk, Valve, ZStage
from .qmix_backend import QmixPumpBackend
from .tec import MeerstetterTecBackend, SimulatedTecBackend, TecController, _real_tec_client_factory
from .thorlabs_piezo import PiezoStage


@dataclass(frozen=True, slots=True)
class HardwareRuntimeConfig:
    ad2_enabled: bool
    sim_ad2: bool
    camera_enabled: bool
    sim_camera: bool
    pump_enabled: bool
    sim_pump: bool
    valve_enabled: bool
    sim_valve: bool
    z_enabled: bool
    # Real Thorlabs piezo device serial (thorlabs_piezo.PiezoStage connects
    # by serial number, not a COM port) -- replaces the legacy prior_resource
    # ('COM7', a port that never existed on this lab's hardware and was
    # never actually the real piezo; see pending_feedback.md item 4/5).
    thorlabs_apt_serial: str
    valve_resource: str
    cetoni_config_path: str | Path
    tec_enabled: bool = False
    sim_tec: bool = True
    tec_port: str = ""


@dataclass(frozen=True, slots=True)
class HardwareBundle:
    ad2: AD2Sdk
    camera: HamamatsuCamera
    pump: CetoniPump
    valve: Valve
    z_motor: ZStage
    tec: TecController


def validate_live_valve_resource(resource: str) -> None:
    """Reject the TEC's current serial resource on a live valve path."""
    if resource.strip().upper() == "COM6":
        raise ValueError("COM6 is reserved for TEC and cannot be used as the valve resource.")


def _ensure_qmixsdk_env() -> None:
    # qmix_sdk_for_codex/python/qmixsdk/_qmixloadlib.py resolves the real Qmix
    # SDK's native DLL directory from the QMIXSDK environment variable the
    # first time qmixsdk is imported (falling back to a path relative to the
    # qmixsdk package itself, which is wrong for this repo's layout). With
    # QMIXSDK unset, ctypes.windll.LoadLibrary("labbCAN_Bus_API") looks in the
    # process's CWD/PATH and fails -- confirmed on real hardware: the real
    # pump could not connect via this app's own Initialize button on a clean
    # environment, even though hardware_tests/test_real_workflow_smoke.py
    # already sets this same variable before touching the real backend.
    # setdefault() so an operator/CI environment that already points QMIXSDK
    # somewhere specific is not overridden.
    os.environ.setdefault("QMIXSDK", str(default_hardware_config().qmix.qmixsdk_path))


def build_hardware_bundle(config: HardwareRuntimeConfig) -> HardwareBundle:
    if config.valve_enabled and not config.sim_valve:
        validate_live_valve_resource(config.valve_resource)
    if not config.sim_pump:
        _ensure_qmixsdk_env()
    ad2 = SimulatedAD2Sdk(enabled=config.ad2_enabled) if config.sim_ad2 else AD2Sdk(enabled=config.ad2_enabled)
    camera = HamamatsuCamera(
        enabled=config.camera_enabled,
        simulate=config.sim_camera,
        backend=None if config.sim_camera else HamamatsuDcamBackend(),
    )
    pump = CetoniPump(
        enabled=config.pump_enabled,
        simulate=config.sim_pump,
        configuration_path=Path(config.cetoni_config_path),
        backend=None if config.sim_pump else QmixPumpBackend(),
    )
    valve = Valve(
        enabled=config.valve_enabled,
        simulate=config.sim_valve,
        visa_resource=config.valve_resource,
        backend=None if config.sim_valve else SerialTextCommandBackend(device_name="valve"),
    )
    z_motor = ZStage(
        enabled=config.z_enabled,
        stage=PiezoStage(serial_number=config.thorlabs_apt_serial),
    )
    tec = TecController(
        enabled=config.tec_enabled,
        simulate=config.sim_tec,
        backend=SimulatedTecBackend()
        if config.sim_tec
        else MeerstetterTecBackend(port=config.tec_port or None, client_factory=_real_tec_client_factory),
    )
    return HardwareBundle(ad2=ad2, camera=camera, pump=pump, valve=valve, z_motor=z_motor, tec=tec)


def apply_hardware_bundle(app: Any, bundle: HardwareBundle) -> None:
    app.set_ad2_sdk(bundle.ad2)
    app.set_hamamatsu(bundle.camera)
    app.set_cetoni_pump(bundle.pump)
    app.set_valve(bundle.valve)
    app.set_z_stage(bundle.z_motor)
    app.set_tec_controller(bundle.tec)
