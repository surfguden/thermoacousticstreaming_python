from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .hamamatsu_dcam import HamamatsuDcamBackend
from .instruments import AD2Sdk, CetoniPump, HamamatsuCamera, PriorZMotor, SerialTextCommandBackend, SimulatedAD2Sdk, Valve
from .qmix_backend import QmixPumpBackend


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
    prior_resource: str
    valve_resource: str
    cetoni_config_path: str | Path


@dataclass(frozen=True, slots=True)
class HardwareBundle:
    ad2: AD2Sdk
    camera: HamamatsuCamera
    pump: CetoniPump
    valve: Valve
    z_motor: PriorZMotor


def build_hardware_bundle(config: HardwareRuntimeConfig) -> HardwareBundle:
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
        backend=None if config.sim_valve else SerialTextCommandBackend(),
    )
    z_motor = PriorZMotor(
        enabled=config.z_enabled,
        visa_resource=config.prior_resource,
        backend=None if not config.z_enabled else SerialTextCommandBackend(),
    )
    return HardwareBundle(ad2=ad2, camera=camera, pump=pump, valve=valve, z_motor=z_motor)


def apply_hardware_bundle(app: Any, bundle: HardwareBundle) -> None:
    app.set_ad2_sdk(bundle.ad2)
    app.set_hamamatsu(bundle.camera)
    app.set_cetoni_pump(bundle.pump)
    app.set_valve(bundle.valve)
    app.set_prior_zmotor(bundle.z_motor)
