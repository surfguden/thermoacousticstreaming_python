from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


ONE_PUMP_QMIX_CONFIG_PATH = Path(
    r"C:\Users\Lab user\Desktop\Franzi\video paper 2\Paper 2 slow flow\Configurations\Cetoni_1pump_config_FM"
)
DEFAULT_QMIXSDK_PATH = Path(r"C:\Users\Lab user\AppData\Local\CETONI_SDK")


class ZStageBackend(StrEnum):
    DISABLED = "disabled"
    SIMULATED = "simulated"
    PRIOR_SERIAL = "prior_serial"
    THORLABS_APT = "thorlabs_apt"


@dataclass(frozen=True, slots=True)
class ZStageConfig:
    backend: ZStageBackend = ZStageBackend.DISABLED
    prior_resource: str = "COM7"
    thorlabs_apt_serial: str = "44533854"
    thorlabs_apt_backend: str = "pylablib"
    thorlabs_apt_discovery_only: bool = True


@dataclass(frozen=True, slots=True)
class QmixConfig:
    sdk_python_path: Path = field(default_factory=lambda: default_qmix_sdk_python_path())
    qmixsdk_path: Path = DEFAULT_QMIXSDK_PATH
    config_path: Path = ONE_PUMP_QMIX_CONFIG_PATH
    active_units: int = 1
    legacy_two_pump_config_allowed: bool = False


@dataclass(frozen=True, slots=True)
class HardwareConfig:
    z_stage: ZStageConfig = field(default_factory=ZStageConfig)
    qmix: QmixConfig = field(default_factory=lambda: default_qmix_config())


def default_repo_root() -> Path:
    return Path(__file__).parents[2]


def default_qmix_sdk_python_path(repo_root: Path | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else default_repo_root()
    return root / "qmix_sdk_for_codex" / "python"


def default_qmix_config(repo_root: Path | None = None) -> QmixConfig:
    return QmixConfig(sdk_python_path=default_qmix_sdk_python_path(repo_root))


def default_hardware_config(repo_root: Path | None = None) -> HardwareConfig:
    return HardwareConfig(qmix=default_qmix_config(repo_root))
