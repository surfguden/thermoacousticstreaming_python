from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "hardware_tests" / "test_real_workflow_smoke.py"
HARDWARE_SDK_MODULE_NAMES = ("pylablib", "qmixsdk", "serial", "dcam", "dwf")


def load_smoke_module():
    spec = importlib.util.spec_from_file_location("test_real_workflow_smoke", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_real_camera_only_plan_is_safe_by_default():
    module = load_smoke_module()

    plan = module.real_camera_only_plan()

    assert plan.name == "real-camera-only"
    assert plan.flush_enabled is False
    assert plan.requires_confirmation is False
    assert plan.config.camera_enabled is True
    assert plan.config.sim_camera is False
    assert plan.config.ad2_enabled is True
    assert plan.config.sim_ad2 is True
    assert plan.config.pump_enabled is False
    assert plan.config.sim_pump is True
    assert plan.config.valve_enabled is False
    assert plan.config.sim_valve is True
    assert plan.config.z_enabled is False


def test_plan_only_main_does_not_call_real_camera_runner(monkeypatch, capsys, tmp_path):
    module = load_smoke_module()

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("real camera runner should not be called in plan-only mode")

    monkeypatch.setattr(module, "run_real_camera_only", fail_if_called)
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "test_real_workflow_smoke.py",
            "--plan-only",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert module.main() == 0
    output = capsys.readouterr().out
    assert "plan: real-camera-only" in output
    assert "default behavior is plan-only" in output
    assert "flush_enabled" in output


def test_labview_preset_plan_only_prints_candidates_without_running_hardware(monkeypatch, capsys, tmp_path):
    module = load_smoke_module()

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("real camera runner should not be called in plan-only mode")

    monkeypatch.setattr(module, "run_real_camera_only", fail_if_called)
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "test_real_workflow_smoke.py",
            "--plan-only",
            "--preset",
            "labview-screenshot",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert module.main() == 0
    output = capsys.readouterr().out
    assert "plan: real-camera-only" in output
    assert "LabVIEW screenshot preset candidates" in output
    assert "LabVIEW ROI candidate" in output
    assert "ROI application: disabled by default; pass --apply-roi for explicit ROI validation" in output
    assert "camera exposure_ms: 40.0" in output
    assert "LabVIEW experiment frames: 1000" in output
    assert "smoke frame override: 1 frame(s); LabVIEW experiment preset uses 1000" in output
    assert "flush candidate: not enabled in smoke path" in output
    assert "screenshot valve COM candidate: COM5" in output


def test_labview_preset_resolution_uses_camera_values_but_conservative_frames():
    module = load_smoke_module()

    settings = module.resolve_smoke_settings("labview-screenshot", frames=None, exposure_ms=None)

    assert settings.frames == 1
    assert settings.exposure_ms == 40.0
    assert settings.trigger_source == "internal"
    assert settings.roi == {
        "horizontal_offset": 0,
        "vertical_offset": 792,
        "horizontal_size": 2304,
        "vertical_size": 740,
    }
    assert settings.apply_roi is False
    assert settings.preset.experiment.frames == 1000


def test_labview_preset_apply_roi_is_explicit():
    module = load_smoke_module()

    settings = module.resolve_smoke_settings("labview-screenshot", frames=None, exposure_ms=None, apply_roi=True)

    assert settings.roi is not None
    assert settings.apply_roi is True


def test_labview_preset_allows_explicit_smoke_frame_and_exposure_override():
    module = load_smoke_module()

    settings = module.resolve_smoke_settings("labview-screenshot", frames=7, exposure_ms=12.5)

    assert settings.frames == 7
    assert settings.exposure_ms == 12.5
    assert settings.preset.camera.exposure_ms == 40.0


def test_ad2_plan_only_prints_without_running_hardware(monkeypatch, capsys, tmp_path):
    module = load_smoke_module()

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("real camera runner should not be called in AD2 plan-only mode")

    monkeypatch.setattr(module, "run_real_camera_only", fail_if_called)
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "test_real_workflow_smoke.py",
            "--ad2-plan-only",
            "--preset",
            "labview-screenshot",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert module.main() == 0
    output = capsys.readouterr().out
    assert "AD2 LabVIEW screenshot plan only" in output
    assert "real AD2 initialized: False" in output
    assert "frequency=1975000.0 Hz" in output
    assert "amplitude=2.0 V" in output
    assert "This mode is print-only" in output


def test_plan_only_can_include_ad2_candidate_plan(monkeypatch, capsys, tmp_path):
    module = load_smoke_module()

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("real hardware runner should not be called in plan-only mode")

    monkeypatch.setattr(module, "run_real_camera_only", fail_if_called)
    monkeypatch.setattr(module, "run_real_ad2_open_close", fail_if_called)
    monkeypatch.setattr(module, "run_real_ad2_low_risk_output", fail_if_called)
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "test_real_workflow_smoke.py",
            "--plan-only",
            "--preset",
            "labview-screenshot",
            "--ad2-plan",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert module.main() == 0
    output = capsys.readouterr().out
    assert "plan: real-camera-only" in output
    assert "AD2 LabVIEW screenshot plan only" in output
    assert "frequency=1975000.0 Hz" in output
    assert "amplitude=2.0 V" in output
    assert "real AD2 initialized: False" in output


def test_real_ad2_open_close_requires_confirmation(monkeypatch):
    module = load_smoke_module()

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("AD2 open-close should not run without confirmation")

    monkeypatch.setattr(module, "run_real_ad2_open_close", fail_if_called)
    monkeypatch.setattr(module.sys, "argv", ["test_real_workflow_smoke.py", "--real-ad2-open-close"])

    try:
        module.main()
    except SystemExit as exc:
        assert "CONFIRM_REAL_HARDWARE" in str(exc)
    else:
        raise AssertionError("missing confirmation should raise SystemExit")


def test_real_ad2_low_risk_output_requires_confirmation(monkeypatch):
    module = load_smoke_module()

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("AD2 output should not run without confirmation")

    monkeypatch.setattr(module, "run_real_ad2_low_risk_output", fail_if_called)
    monkeypatch.setattr(module.sys, "argv", ["test_real_workflow_smoke.py", "--real-ad2-low-risk-output"])

    try:
        module.main()
    except SystemExit as exc:
        assert "CONFIRM_REAL_HARDWARE" in str(exc)
    else:
        raise AssertionError("missing confirmation should raise SystemExit")


def test_real_ad2_open_close_runs_only_with_confirmation(monkeypatch):
    module = load_smoke_module()
    calls = []

    def fake_runner(device_index=0):
        calls.append(device_index)
        return 0

    monkeypatch.setattr(module, "run_real_ad2_open_close", fake_runner)
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "test_real_workflow_smoke.py",
            "--real-ad2-open-close",
            "--confirm",
            "CONFIRM_REAL_HARDWARE",
            "--device-index",
            "1",
        ],
    )

    assert module.main() == 0
    assert calls == [1]


def test_real_ad2_low_risk_output_runs_only_with_confirmation(monkeypatch):
    module = load_smoke_module()
    calls = []

    def fake_runner(device_index=0):
        calls.append(device_index)
        return 0

    monkeypatch.setattr(module, "run_real_ad2_low_risk_output", fake_runner)
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "test_real_workflow_smoke.py",
            "--real-ad2-low-risk-output",
            "--confirm",
            "CONFIRM_REAL_HARDWARE",
        ],
    )

    assert module.main() == 0
    assert calls == [0]


def test_low_risk_ad2_output_parameters_are_not_labview_acoustic_candidate():
    module = load_smoke_module()

    assert module.AD2_LOW_RISK_CHANNEL == 0
    assert module.AD2_LOW_RISK_FREQUENCY_HZ == 1000.0
    assert module.AD2_LOW_RISK_AMPLITUDE_V == 0.1
    assert module.AD2_LOW_RISK_OFFSET_V == 0.0
    assert module.AD2_LOW_RISK_DURATION_S == 0.5
    assert module.AD2_LOW_RISK_FREQUENCY_HZ != 1.975e6
    assert module.AD2_LOW_RISK_AMPLITUDE_V < 2.0

    config = module.low_risk_wfg_config()
    assert config.running is True
    assert len(config.channels) == 1
    channel = config.channels[0]
    assert channel.carrier.frequency_hz == 1000.0
    assert channel.carrier.amplitude_v == 0.1
    assert channel.trigger.sec_run == 0.5
    assert channel.trigger.repeat_count == 1


def test_real_camera_only_main_uses_safe_plan_and_runner(monkeypatch, tmp_path):
    module = load_smoke_module()
    calls = []

    def fake_runner(output_dir, frames, exposure_ms, preset_name=None, apply_roi=False):
        calls.append((output_dir, frames, exposure_ms, preset_name, apply_roi))
        return output_dir / "fake-run"

    monkeypatch.setattr(module, "run_real_camera_only", fake_runner)
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "test_real_workflow_smoke.py",
            "--real-camera-only",
            "--output-dir",
            str(tmp_path),
            "--frames",
            "2",
            "--exposure-ms",
            "5",
        ],
    )

    assert module.main() == 0
    assert calls == [(tmp_path, 2, 5.0, None, False)]


def test_real_camera_only_main_passes_labview_preset_to_runner(monkeypatch, tmp_path):
    module = load_smoke_module()
    calls = []

    def fake_runner(output_dir, frames, exposure_ms, preset_name=None, apply_roi=False):
        calls.append((output_dir, frames, exposure_ms, preset_name, apply_roi))
        return output_dir / "fake-run"

    monkeypatch.setattr(module, "run_real_camera_only", fake_runner)
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "test_real_workflow_smoke.py",
            "--real-camera-only",
            "--preset",
            "labview-screenshot",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert module.main() == 0
    assert calls == [(tmp_path, None, None, "labview-screenshot", False)]


def test_real_camera_only_main_passes_apply_roi_only_when_requested(monkeypatch, tmp_path):
    module = load_smoke_module()
    calls = []

    def fake_runner(output_dir, frames, exposure_ms, preset_name=None, apply_roi=False):
        calls.append((output_dir, frames, exposure_ms, preset_name, apply_roi))
        return output_dir / "fake-run"

    monkeypatch.setattr(module, "run_real_camera_only", fake_runner)
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "test_real_workflow_smoke.py",
            "--real-camera-only",
            "--preset",
            "labview-screenshot",
            "--apply-roi",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert module.main() == 0
    assert calls == [(tmp_path, None, None, "labview-screenshot", True)]


def test_smoke_plan_tests_do_not_import_real_hardware_sdks():
    before = {name for name in HARDWARE_SDK_MODULE_NAMES if name in sys.modules}

    load_smoke_module()

    after = {name for name in HARDWARE_SDK_MODULE_NAMES if name in sys.modules}
    assert after == before
