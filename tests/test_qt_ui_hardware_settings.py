from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from thermo_acoustic import qt_ui
from thermo_acoustic.hardware_config import ZStageBackend, default_hardware_config


def make_window(monkeypatch, tmp_path, settings: dict | None = None) -> qt_ui.MainWindow:
    settings_path = tmp_path / "settings.json"
    if settings is not None:
        settings_path.write_text(json.dumps(settings), encoding="utf-8")
    monkeypatch.setattr(qt_ui, "SETTINGS_PATH", settings_path)
    QApplication.instance() or QApplication([])
    return qt_ui.MainWindow()


def test_qt_ui_uses_passive_hardware_config_defaults(monkeypatch, tmp_path):
    defaults = default_hardware_config()

    window = make_window(monkeypatch, tmp_path)

    assert window.z_backend.currentText() == ZStageBackend.DISABLED.value
    assert window.prior_resource.text() == defaults.z_stage.prior_resource
    assert window.thorlabs_apt_serial.text() == defaults.z_stage.thorlabs_apt_serial
    assert window.thorlabs_apt_backend.text() == defaults.z_stage.thorlabs_apt_backend
    assert window.thorlabs_apt_discovery_only.isChecked() is True
    assert window.cetoni_config_path.text() == str(defaults.qmix.config_path)
    assert window.qmix_sdk_python_path.text() == str(defaults.qmix.sdk_python_path)
    assert window.qmix_qmixsdk_path.text() == str(defaults.qmix.qmixsdk_path)


def test_qt_ui_settings_dict_includes_passive_hardware_fields(monkeypatch, tmp_path):
    window = make_window(monkeypatch, tmp_path)

    settings = window._settings_dict()

    assert settings["z_backend"] == ZStageBackend.DISABLED.value
    assert settings["prior_resource"] == "COM7"
    assert settings["thorlabs_apt_serial"] == "44533854"
    assert settings["thorlabs_apt_backend"] == "pylablib"
    assert settings["thorlabs_apt_discovery_only"] is True
    assert settings["qmix_sdk_python_path"].endswith(r"qmix_sdk_for_codex\python")
    assert settings["qmix_qmixsdk_path"] == r"C:\Users\Lab user\AppData\Local\CETONI_SDK"
    assert "Cetoni_1pump_config_FM" in settings["cetoni_config_path"]


def test_qt_ui_load_settings_is_backward_compatible(monkeypatch, tmp_path):
    old_settings = {
        "z_enabled": False,
        "prior_resource": "COM7",
        "valve_resource": "COM6",
        "cetoni_config_path": r"C:\Users\Public\Documents\QmixElements\Projects",
    }

    window = make_window(monkeypatch, tmp_path, old_settings)

    assert window.z_backend.currentText() == ZStageBackend.DISABLED.value
    assert window.thorlabs_apt_serial.text() == "44533854"
    assert window.thorlabs_apt_backend.text() == "pylablib"
    assert window.thorlabs_apt_discovery_only.isChecked() is True
    assert window.qmix_sdk_python_path.text().endswith(r"qmix_sdk_for_codex\python")
    assert window.qmix_qmixsdk_path.text() == r"C:\Users\Lab user\AppData\Local\CETONI_SDK"
    assert window.cetoni_config_path.text() == old_settings["cetoni_config_path"]


def test_qt_ui_save_and_restore_passive_hardware_fields(monkeypatch, tmp_path):
    first_window = make_window(monkeypatch, tmp_path)
    first_window.z_backend.setCurrentText(ZStageBackend.THORLABS_APT.value)
    first_window.thorlabs_apt_serial.setText("44533854")
    first_window.thorlabs_apt_backend.setText("pylablib")
    first_window.thorlabs_apt_discovery_only.setChecked(False)
    first_window.qmix_sdk_python_path.setText(r"C:\sdk\python")
    first_window.qmix_qmixsdk_path.setText(r"C:\sdk\dll")
    first_window.cetoni_config_path.setText(r"C:\configs\one-pump")

    first_window._save_settings()
    saved = json.loads(qt_ui.SETTINGS_PATH.read_text(encoding="utf-8"))

    assert saved["z_backend"] == ZStageBackend.THORLABS_APT.value
    assert saved["thorlabs_apt_discovery_only"] is False
    assert saved["qmix_sdk_python_path"] == r"C:\sdk\python"

    second_window = qt_ui.MainWindow()

    assert second_window.z_backend.currentText() == ZStageBackend.THORLABS_APT.value
    assert second_window.thorlabs_apt_serial.text() == "44533854"
    assert second_window.thorlabs_apt_backend.text() == "pylablib"
    assert second_window.thorlabs_apt_discovery_only.isChecked() is False
    assert second_window.qmix_sdk_python_path.text() == r"C:\sdk\python"
    assert second_window.qmix_qmixsdk_path.text() == r"C:\sdk\dll"
    assert second_window.cetoni_config_path.text() == r"C:\configs\one-pump"
