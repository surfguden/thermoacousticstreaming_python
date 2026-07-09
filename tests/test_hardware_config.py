from __future__ import annotations

import importlib
import sys

from thermo_acoustic.hardware_config import (
    ONE_PUMP_QMIX_CONFIG_PATH,
    DEFAULT_QMIXSDK_PATH,
    ZStageBackend,
    default_hardware_config,
)


HARDWARE_SDK_MODULE_NAMES = ("pylablib", "qmixsdk", "serial", "dcam", "dwf")


def test_default_hardware_config_matches_validated_hardware_status():
    config = default_hardware_config()

    assert config.z_stage.backend == ZStageBackend.DISABLED
    assert config.z_stage.prior_resource == "COM7"
    assert config.z_stage.thorlabs_apt_serial == "44533854"
    assert config.z_stage.thorlabs_apt_backend == "pylablib"
    assert config.z_stage.thorlabs_apt_discovery_only is True

    assert config.qmix.qmixsdk_path == DEFAULT_QMIXSDK_PATH
    assert config.qmix.config_path == ONE_PUMP_QMIX_CONFIG_PATH
    assert config.qmix.active_units == 1
    assert config.qmix.legacy_two_pump_config_allowed is False


def test_default_qmix_sdk_python_path_uses_repo_root(tmp_path):
    config = default_hardware_config(tmp_path)

    assert config.qmix.sdk_python_path == tmp_path / "qmix_sdk_for_codex" / "python"


def test_one_pump_config_is_default():
    config = default_hardware_config()

    assert config.qmix.config_path == ONE_PUMP_QMIX_CONFIG_PATH
    assert "Cetoni_1pump_config_FM" in str(config.qmix.config_path)
    assert "two_pumps" not in str(config.qmix.config_path).lower()


def test_module_does_not_import_hardware_sdks():
    before = {name for name in HARDWARE_SDK_MODULE_NAMES if name in sys.modules}

    module = importlib.import_module("thermo_acoustic.hardware_config")
    importlib.reload(module)

    after = {name for name in HARDWARE_SDK_MODULE_NAMES if name in sys.modules}
    assert after == before


def test_paths_are_constructed_not_opened(tmp_path):
    fake_root = tmp_path / "does-not-exist"

    config = default_hardware_config(fake_root)

    assert config.qmix.sdk_python_path == fake_root / "qmix_sdk_for_codex" / "python"
