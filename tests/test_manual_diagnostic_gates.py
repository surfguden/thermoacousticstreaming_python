"""Offline checks for relocated camera and device-release confirmation gates."""

import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
CASES = (
    ("manual_hamamatsu_camera_probe", "thermo_acoustic.hamamatsu_dcam", "HamamatsuDcamBackend"),
    ("manual_release_ad2", "thermo_acoustic.waveforms", "WaveFormsBackend"),
)


def load_diagnostic(monkeypatch, name, dependency, backend):
    def tripwire():
        raise AssertionError("Real backend construction is forbidden in offline checks")

    fake_dependency = ModuleType(dependency)
    setattr(fake_dependency, backend, tripwire)
    monkeypatch.setitem(sys.modules, dependency, fake_dependency)
    spec = importlib.util.spec_from_file_location(name, ROOT / "hardware_tests" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("name,dependency,backend", CASES)
def test_import_help_and_unconfirmed_calls_never_construct_backend(monkeypatch, name, dependency, backend):
    module = load_diagnostic(monkeypatch, name, dependency, backend)
    with pytest.raises(SystemExit) as result:
        module.main(["--help"])
    assert result.value.code == 0
    assert module.main([]) == 2
    for token in ("wrong", module.CONFIRM_TEXT.lower(), module.CONFIRM_TEXT + " "):
        assert module.main(["--confirm", token]) == 2


def test_confirmed_camera_failure_still_closes_fake_backend(monkeypatch):
    module = load_diagnostic(monkeypatch, *CASES[0])
    events = []

    def fail_capture():
        events.append("capture")
        raise RuntimeError("fake capture failure")

    fake = SimpleNamespace(
        open_camera=lambda: events.append("open"),
        configure_exposure_time=lambda value: events.append(("exposure", value)),
        capture_snapshot=fail_capture,
        close=lambda: events.append("close"),
    )
    monkeypatch.setattr(module, "HamamatsuDcamBackend", lambda: fake)
    with pytest.raises(RuntimeError, match="fake capture failure"):
        module.main(["--confirm", module.CONFIRM_TEXT])
    assert events == ["open", ("exposure", 50.0), "capture", "close"]


def test_confirmed_release_preserves_enumerate_release_enumerate_order(monkeypatch):
    module = load_diagnostic(monkeypatch, *CASES[1])
    events = []

    def enumerate_devices():
        events.append("enumerate")
        return 0

    fake = SimpleNamespace(
        enum_devices=enumerate_devices,
        close_all=lambda: events.append("release"),
    )
    monkeypatch.setattr(module, "WaveFormsBackend", lambda: fake)
    assert module.main(["--confirm", module.CONFIRM_TEXT]) == 0
    assert events == ["enumerate", "release", "enumerate"]
