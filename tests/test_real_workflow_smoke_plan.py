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


def test_combined_camera_ad2_low_risk_plan_keeps_other_hardware_disabled():
    module = load_smoke_module()

    plan = module.real_camera_real_ad2_low_risk_plan()

    assert plan.name == "real-camera-real-ad2-low-risk"
    assert plan.flush_enabled is False
    assert plan.requires_confirmation is True
    assert plan.config.camera_enabled is True
    assert plan.config.sim_camera is False
    assert plan.config.ad2_enabled is True
    assert plan.config.sim_ad2 is False
    assert plan.config.pump_enabled is False
    assert plan.config.sim_pump is True
    assert plan.config.valve_enabled is False
    assert plan.config.sim_valve is True
    assert plan.config.z_enabled is False


def test_combined_camera_ad2_acoustic_short_plan_keeps_other_hardware_disabled():
    module = load_smoke_module()

    plan = module.real_camera_real_ad2_acoustic_short_plan()

    assert plan.name == "real-camera-real-ad2-acoustic-short"
    assert plan.flush_enabled is False
    assert plan.requires_confirmation is True
    assert plan.config.camera_enabled is True
    assert plan.config.sim_camera is False
    assert plan.config.ad2_enabled is True
    assert plan.config.sim_ad2 is False
    assert plan.config.pump_enabled is False
    assert plan.config.sim_pump is True
    assert plan.config.valve_enabled is False
    assert plan.config.sim_valve is True
    assert plan.config.z_enabled is False


def test_led_trigger_check_plan_keeps_other_hardware_disabled():
    module = load_smoke_module()

    plan = module.real_camera_led_trigger_check_plan()

    assert plan.name == "real-camera-led-trigger-check"
    assert plan.flush_enabled is False
    assert plan.requires_confirmation is True
    assert plan.config.camera_enabled is True
    assert plan.config.sim_camera is False
    assert plan.config.ad2_enabled is True
    assert plan.config.sim_ad2 is False
    assert plan.config.pump_enabled is False
    assert plan.config.sim_pump is True
    assert plan.config.valve_enabled is False
    assert plan.config.sim_valve is True
    assert plan.config.z_enabled is False


def test_real_full_workflow_short_plan_uses_real_pump_valve_and_keeps_z_disabled():
    module = load_smoke_module()

    plan = module.real_full_workflow_short_plan("COM6", flush_enabled=True)

    assert plan.name == "real-full-workflow-short"
    assert plan.flush_enabled is True
    assert plan.requires_confirmation is True
    assert plan.config.camera_enabled is True
    assert plan.config.sim_camera is False
    assert plan.config.ad2_enabled is True
    assert plan.config.sim_ad2 is False
    assert plan.config.pump_enabled is True
    assert plan.config.sim_pump is False
    assert plan.config.valve_enabled is True
    assert plan.config.sim_valve is False
    assert plan.config.valve_resource == "COM6"
    assert plan.config.z_enabled is False
    assert "Cetoni_1pump_config_FM" in str(plan.config.cetoni_config_path)
    assert "two_pumps" not in str(plan.config.cetoni_config_path).lower()


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
    monkeypatch.setattr(module, "run_real_ad2_timing_check", fail_if_called)
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


def test_plan_only_can_include_ad2_timing_plan(monkeypatch, capsys, tmp_path):
    module = load_smoke_module()

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("real AD2 timing check should not run in plan-only mode")

    monkeypatch.setattr(module, "run_real_ad2_timing_check", fail_if_called)
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "test_real_workflow_smoke.py",
            "--plan-only",
            "--ad2-timing-plan",
            "--pre-trigger-wait-s",
            "2.5",
            "--duration-s",
            "1.0",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert module.main() == 0
    output = capsys.readouterr().out
    assert "AD2 timing verification plan" in output
    assert "open AD2" in output
    assert "configure WFG: CH0 1000 Hz sine, 0.1 V amplitude, 0 V offset, trigsrcNone, running=True" in output
    assert "wait 2.5 s before pc_trigger" in output
    assert "send pc_trigger" in output
    assert "wait output duration 1.0 s" in output
    assert "CH2/index 1: disabled" in output
    assert "DO Clock: not used" in output
    assert "DO Custom: not used" in output
    assert "if waveform appears during pre-trigger wait: trigsrcNone/config_wfg starts output immediately" in output
    assert "if waveform appears only after pc_trigger: PC trigger controls start for this configuration" in output


def test_plan_only_can_include_led_trigger_plan(monkeypatch, capsys, tmp_path):
    module = load_smoke_module()

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("real LED trigger check should not run in plan-only mode")

    monkeypatch.setattr(module, "run_real_camera_led_trigger_check", fail_if_called)
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "test_real_workflow_smoke.py",
            "--plan-only",
            "--preset",
            "labview-screenshot",
            "--apply-roi",
            "--frames",
            "20",
            "--led-trigger-plan",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert module.main() == 0
    output = capsys.readouterr().out
    assert "LED trigger verification plan" in output
    assert "LED is driven by: AD2 green wire" in output
    assert "LED trigger path: AD2 WFG CH0 via the green wire illumination trigger line" in output
    assert "AD2 output path used for LED: WFG CH0 only" in output
    assert "camera frames: 20" in output
    assert "ROI application: enabled explicitly by --apply-roi" in output
    assert "CH2/index 1: disabled" in output
    assert "pump: not used" in output
    assert "valve: not used" in output
    assert "Qmix: not used" in output
    assert "Z-stage: not used" in output
    assert "Thorlabs/APT: not used" in output
    assert "Prior COM7: not used" in output


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


def test_real_ad2_timing_check_requires_confirmation(monkeypatch):
    module = load_smoke_module()

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("AD2 timing check should not run without confirmation")

    monkeypatch.setattr(module, "run_real_ad2_timing_check", fail_if_called)
    monkeypatch.setattr(module.sys, "argv", ["test_real_workflow_smoke.py", "--real-ad2-timing-check"])

    try:
        module.main()
    except SystemExit as exc:
        assert "CONFIRM_REAL_HARDWARE" in str(exc)
    else:
        raise AssertionError("missing confirmation should raise SystemExit")


def test_real_ad2_labview_acoustic_short_requires_confirmation(monkeypatch):
    module = load_smoke_module()

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("LabVIEW acoustic short should not run without confirmation")

    monkeypatch.setattr(module, "run_real_ad2_labview_acoustic_short", fail_if_called)
    monkeypatch.setattr(module.sys, "argv", ["test_real_workflow_smoke.py", "--real-ad2-labview-acoustic-short"])

    try:
        module.main()
    except SystemExit as exc:
        assert "CONFIRM_REAL_HARDWARE" in str(exc)
    else:
        raise AssertionError("missing confirmation should raise SystemExit")


def test_real_ad2_labview_acoustic_short_requires_timing_acknowledgement(monkeypatch):
    module = load_smoke_module()

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("LabVIEW acoustic short should not run without timing acknowledgement")

    monkeypatch.setattr(module, "run_real_ad2_labview_acoustic_short", fail_if_called)
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "test_real_workflow_smoke.py",
            "--real-ad2-labview-acoustic-short",
            "--confirm",
            "CONFIRM_REAL_HARDWARE",
        ],
    )

    try:
        module.main()
    except SystemExit as exc:
        message = str(exc)
        assert "--acknowledge-timing-uncertain" in message
        assert "AD2 WFG start timing vs pc_trigger is not yet fully confirmed" in message
        assert "trigsrcNone may mean output starts at config_wfg rather than pc_trigger" in message
        assert "CH2/index 1 purpose is unknown and remains disabled" in message
        assert "AD2 CH0 only" in message
    else:
        raise AssertionError("missing timing acknowledgement should raise SystemExit")


def test_combined_camera_ad2_low_risk_requires_confirmation(monkeypatch, tmp_path):
    module = load_smoke_module()

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("combined smoke should not run without confirmation")

    monkeypatch.setattr(module, "run_real_camera_real_ad2_low_risk", fail_if_called)
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "test_real_workflow_smoke.py",
            "--real-camera-real-ad2-low-risk",
            "--preset",
            "labview-screenshot",
            "--output-dir",
            str(tmp_path),
        ],
    )

    try:
        module.main()
    except SystemExit as exc:
        assert "CONFIRM_REAL_HARDWARE" in str(exc)
    else:
        raise AssertionError("missing confirmation should raise SystemExit")


def test_combined_camera_ad2_acoustic_short_requires_confirmation(monkeypatch, tmp_path):
    module = load_smoke_module()

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("combined acoustic-short smoke should not run without confirmation")

    monkeypatch.setattr(module, "run_real_camera_real_ad2_acoustic_short", fail_if_called)
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "test_real_workflow_smoke.py",
            "--real-camera-real-ad2-acoustic-short",
            "--preset",
            "labview-screenshot",
            "--output-dir",
            str(tmp_path),
        ],
    )

    try:
        module.main()
    except SystemExit as exc:
        assert "CONFIRM_REAL_HARDWARE" in str(exc)
    else:
        raise AssertionError("missing confirmation should raise SystemExit")


def test_combined_camera_ad2_acoustic_short_requires_timing_acknowledgement(monkeypatch, tmp_path):
    module = load_smoke_module()

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("combined acoustic-short smoke should not run without timing acknowledgement")

    monkeypatch.setattr(module, "run_real_camera_real_ad2_acoustic_short", fail_if_called)
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "test_real_workflow_smoke.py",
            "--real-camera-real-ad2-acoustic-short",
            "--preset",
            "labview-screenshot",
            "--output-dir",
            str(tmp_path),
            "--confirm",
            "CONFIRM_REAL_HARDWARE",
        ],
    )

    try:
        module.main()
    except SystemExit as exc:
        message = str(exc)
        assert "--acknowledge-timing-uncertain" in message
        assert "AD2 WFG start timing vs pc_trigger is not yet fully confirmed" in message
        assert "CH2/index 1 purpose is unknown and remains disabled" in message
    else:
        raise AssertionError("missing timing acknowledgement should raise SystemExit")


def test_led_trigger_check_requires_confirmation(monkeypatch, tmp_path):
    module = load_smoke_module()

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("LED trigger check should not run without confirmation")

    monkeypatch.setattr(module, "run_real_camera_led_trigger_check", fail_if_called)
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "test_real_workflow_smoke.py",
            "--real-camera-led-trigger-check",
            "--preset",
            "labview-screenshot",
            "--output-dir",
            str(tmp_path),
        ],
    )

    try:
        module.main()
    except SystemExit as exc:
        assert "CONFIRM_REAL_HARDWARE" in str(exc)
    else:
        raise AssertionError("missing confirmation should raise SystemExit")


def test_led_trigger_check_requires_timing_acknowledgement(monkeypatch, tmp_path):
    module = load_smoke_module()

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("LED trigger check should not run without timing acknowledgement")

    monkeypatch.setattr(module, "run_real_camera_led_trigger_check", fail_if_called)
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "test_real_workflow_smoke.py",
            "--real-camera-led-trigger-check",
            "--preset",
            "labview-screenshot",
            "--output-dir",
            str(tmp_path),
            "--confirm",
            "CONFIRM_REAL_HARDWARE",
        ],
    )

    try:
        module.main()
    except SystemExit as exc:
        message = str(exc)
        assert "--acknowledge-timing-uncertain" in message
        assert "AD2 WFG start timing vs pc_trigger is not yet fully confirmed" in message
        assert "CH2/index 1 purpose is unknown and remains disabled" in message
    else:
        raise AssertionError("missing timing acknowledgement should raise SystemExit")


def test_real_full_workflow_short_requires_confirmation(monkeypatch, tmp_path):
    module = load_smoke_module()

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("full workflow should not run without confirmation")

    monkeypatch.setattr(module, "run_real_full_workflow_short", fail_if_called)
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "test_real_workflow_smoke.py",
            "--real-full-workflow-short",
            "--valve-port",
            "COM6",
            "--acknowledge-timing-uncertain",
            "--acknowledge-pump-valve-real",
            "--output-dir",
            str(tmp_path),
        ],
    )

    try:
        module.main()
    except SystemExit as exc:
        assert "CONFIRM_REAL_HARDWARE" in str(exc)
    else:
        raise AssertionError("missing confirmation should raise SystemExit")


def test_real_full_workflow_short_requires_timing_acknowledgement(monkeypatch, tmp_path):
    module = load_smoke_module()

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("full workflow should not run without timing acknowledgement")

    monkeypatch.setattr(module, "run_real_full_workflow_short", fail_if_called)
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "test_real_workflow_smoke.py",
            "--real-full-workflow-short",
            "--valve-port",
            "COM6",
            "--confirm",
            "CONFIRM_REAL_HARDWARE",
            "--acknowledge-pump-valve-real",
            "--output-dir",
            str(tmp_path),
        ],
    )

    try:
        module.main()
    except SystemExit as exc:
        assert "--acknowledge-timing-uncertain" in str(exc)
    else:
        raise AssertionError("missing timing acknowledgement should raise SystemExit")


def test_real_full_workflow_short_requires_pump_valve_acknowledgement_when_flush_enabled(monkeypatch, tmp_path):
    module = load_smoke_module()

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("full workflow should not run without pump/valve acknowledgement")

    monkeypatch.setattr(module, "run_real_full_workflow_short", fail_if_called)
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "test_real_workflow_smoke.py",
            "--real-full-workflow-short",
            "--flush-enabled",
            "--valve-port",
            "COM6",
            "--confirm",
            "CONFIRM_REAL_HARDWARE",
            "--acknowledge-timing-uncertain",
            "--output-dir",
            str(tmp_path),
        ],
    )

    try:
        module.main()
    except SystemExit as exc:
        assert "--acknowledge-pump-valve-real" in str(exc)
    else:
        raise AssertionError("missing pump/valve acknowledgement should raise SystemExit")


def test_real_full_workflow_short_requires_explicit_valve_port(monkeypatch, tmp_path):
    module = load_smoke_module()

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("full workflow should not run without explicit valve port")

    monkeypatch.setattr(module, "run_real_full_workflow_short", fail_if_called)
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "test_real_workflow_smoke.py",
            "--real-full-workflow-short",
            "--confirm",
            "CONFIRM_REAL_HARDWARE",
            "--acknowledge-timing-uncertain",
            "--acknowledge-pump-valve-real",
            "--output-dir",
            str(tmp_path),
        ],
    )

    try:
        module.main()
    except SystemExit as exc:
        assert "--valve-port COM5 or COM6" in str(exc)
    else:
        raise AssertionError("missing explicit valve port should raise SystemExit")


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


def test_real_ad2_timing_check_runs_only_with_confirmation(monkeypatch):
    module = load_smoke_module()
    calls = []

    def fake_runner(device_index=0, pre_trigger_wait_s=2.0, duration_s=None):
        calls.append((device_index, pre_trigger_wait_s, duration_s))
        return 0

    monkeypatch.setattr(module, "run_real_ad2_timing_check", fake_runner)
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "test_real_workflow_smoke.py",
            "--real-ad2-timing-check",
            "--pre-trigger-wait-s",
            "2.5",
            "--duration-s",
            "1.0",
            "--confirm",
            "CONFIRM_REAL_HARDWARE",
            "--device-index",
            "1",
        ],
    )

    assert module.main() == 0
    assert calls == [(1, 2.5, 1.0)]


def test_real_ad2_labview_acoustic_short_runs_only_with_confirmation_and_timing_acknowledgement(monkeypatch):
    module = load_smoke_module()
    calls = []

    def fake_runner(device_index=0, duration_s=None):
        calls.append((device_index, duration_s))
        return 0

    monkeypatch.setattr(module, "run_real_ad2_labview_acoustic_short", fake_runner)
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "test_real_workflow_smoke.py",
            "--real-ad2-labview-acoustic-short",
            "--duration-s",
            "1.0",
            "--confirm",
            "CONFIRM_REAL_HARDWARE",
            "--acknowledge-timing-uncertain",
            "--device-index",
            "1",
        ],
    )

    assert module.main() == 0
    assert calls == [(1, 1.0)]


def test_combined_camera_ad2_low_risk_runs_only_with_confirmation(monkeypatch, tmp_path):
    module = load_smoke_module()
    calls = []

    def fake_runner(output_dir, frames, exposure_ms, preset_name=None, apply_roi=False, device_index=0):
        calls.append((output_dir, frames, exposure_ms, preset_name, apply_roi, device_index))
        return output_dir / "fake-run"

    monkeypatch.setattr(module, "run_real_camera_real_ad2_low_risk", fake_runner)
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "test_real_workflow_smoke.py",
            "--real-camera-real-ad2-low-risk",
            "--preset",
            "labview-screenshot",
            "--apply-roi",
            "--frames",
            "20",
            "--output-dir",
            str(tmp_path),
            "--confirm",
            "CONFIRM_REAL_HARDWARE",
            "--device-index",
            "1",
        ],
    )

    assert module.main() == 0
    assert calls == [(tmp_path, 20, None, "labview-screenshot", True, 1)]


def test_combined_camera_ad2_acoustic_short_runs_only_with_confirmation_and_acknowledgement(monkeypatch, tmp_path):
    module = load_smoke_module()
    calls = []

    def fake_runner(output_dir, frames, exposure_ms, preset_name=None, apply_roi=False, device_index=0, duration_s=None):
        calls.append((output_dir, frames, exposure_ms, preset_name, apply_roi, device_index, duration_s))
        return output_dir / "fake-run"

    monkeypatch.setattr(module, "run_real_camera_real_ad2_acoustic_short", fake_runner)
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "test_real_workflow_smoke.py",
            "--real-camera-real-ad2-acoustic-short",
            "--preset",
            "labview-screenshot",
            "--apply-roi",
            "--frames",
            "20",
            "--duration-s",
            "0.5",
            "--output-dir",
            str(tmp_path),
            "--confirm",
            "CONFIRM_REAL_HARDWARE",
            "--acknowledge-timing-uncertain",
            "--device-index",
            "1",
        ],
    )

    assert module.main() == 0
    assert calls == [(tmp_path, 20, None, "labview-screenshot", True, 1, 0.5)]


def test_led_trigger_check_runs_only_with_confirmation_and_acknowledgement(monkeypatch, tmp_path):
    module = load_smoke_module()
    calls = []

    def fake_runner(output_dir, frames, exposure_ms, preset_name=None, apply_roi=False, device_index=0, duration_s=None):
        calls.append((output_dir, frames, exposure_ms, preset_name, apply_roi, device_index, duration_s))
        return output_dir / "fake-run"

    monkeypatch.setattr(module, "run_real_camera_led_trigger_check", fake_runner)
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "test_real_workflow_smoke.py",
            "--real-camera-led-trigger-check",
            "--preset",
            "labview-screenshot",
            "--apply-roi",
            "--frames",
            "20",
            "--duration-s",
            "0.5",
            "--output-dir",
            str(tmp_path),
            "--confirm",
            "CONFIRM_REAL_HARDWARE",
            "--acknowledge-timing-uncertain",
            "--device-index",
            "1",
        ],
    )

    assert module.main() == 0
    assert calls == [(tmp_path, 20, None, "labview-screenshot", True, 1, 0.5)]


def test_real_full_workflow_short_runs_only_with_all_confirmations(monkeypatch, tmp_path):
    module = load_smoke_module()
    calls = []

    def fake_runner(
        output_dir,
        frames,
        exposure_ms,
        preset_name,
        apply_roi,
        valve_port,
        flush_enabled,
        device_index=0,
        duration_s=None,
        include_ad2_laser=False,
    ):
        calls.append(
            (
                output_dir,
                frames,
                exposure_ms,
                preset_name,
                apply_roi,
                valve_port,
                flush_enabled,
                device_index,
                duration_s,
                include_ad2_laser,
            )
        )
        return output_dir / "fake-run"

    monkeypatch.setattr(module, "run_real_full_workflow_short", fake_runner)
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "test_real_workflow_smoke.py",
            "--real-full-workflow-short",
            "--preset",
            "labview-screenshot",
            "--apply-roi",
            "--frames",
            "20",
            "--duration-s",
            "0.5",
            "--flush-enabled",
            "--valve-port",
            "COM6",
            "--output-dir",
            str(tmp_path),
            "--confirm",
            "CONFIRM_REAL_HARDWARE",
            "--acknowledge-timing-uncertain",
            "--acknowledge-pump-valve-real",
            "--device-index",
            "1",
        ],
    )

    assert module.main() == 0
    assert calls == [(tmp_path, 20, None, "labview-screenshot", True, "COM6", True, 1, 0.5, False)]


def test_real_full_workflow_short_can_explicitly_include_ad2_laser(monkeypatch, tmp_path):
    module = load_smoke_module()
    calls = []

    def fake_runner(
        output_dir,
        frames,
        exposure_ms,
        preset_name,
        apply_roi,
        valve_port,
        flush_enabled,
        device_index=0,
        duration_s=None,
        include_ad2_laser=False,
    ):
        calls.append((output_dir, frames, exposure_ms, preset_name, apply_roi, valve_port, flush_enabled, device_index, duration_s, include_ad2_laser))
        return output_dir / "fake-run"

    monkeypatch.setattr(module, "run_real_full_workflow_short", fake_runner)
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "test_real_workflow_smoke.py",
            "--real-full-workflow-short",
            "--preset",
            "labview-screenshot",
            "--apply-roi",
            "--frames",
            "100",
            "--duration-s",
            "2.0",
            "--flush-enabled",
            "--valve-port",
            "COM6",
            "--include-ad2-laser",
            "--output-dir",
            str(tmp_path),
            "--confirm",
            "CONFIRM_REAL_HARDWARE",
            "--acknowledge-timing-uncertain",
            "--acknowledge-pump-valve-real",
        ],
    )

    assert module.main() == 0
    assert calls == [(tmp_path, 100, None, "labview-screenshot", True, "COM6", True, 0, 2.0, True)]


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


def test_ad2_timing_check_uses_low_risk_ch0_only_parameters():
    module = load_smoke_module()

    parameters = module.ad2_timing_check_parameters()

    assert parameters.name == "timing-check"
    assert parameters.channel == 0
    assert parameters.frequency_hz == 1000.0
    assert parameters.amplitude_v == 0.1
    assert parameters.offset_v == 0.0
    assert parameters.duration_s == 0.5
    assert parameters.frequency_hz != 1.975e6
    assert parameters.amplitude_v < 2.0

    config = module.ad2_timing_check_wfg_config()
    assert config.running is True
    assert len(config.channels) == 1
    channel = config.channels[0]
    assert channel.channel_index == 0
    assert [configured_channel.channel_index for configured_channel in config.channels] == [0]
    assert str(channel.trigger.source) in {"TriggerSource.NONE", "trigsrcNone"}
    assert channel.trigger.sec_run == 0.5


def test_ad2_timing_check_refuses_long_duration_and_negative_wait():
    module = load_smoke_module()

    try:
        module.ad2_timing_check_parameters(60.0)
    except SystemExit as exc:
        assert "Refusing to use a long duration" in str(exc)
    else:
        raise AssertionError("long timing-check duration should be refused")

    try:
        module.print_ad2_timing_check_plan(-0.1)
    except SystemExit as exc:
        assert "--pre-trigger-wait-s" in str(exc)
    else:
        raise AssertionError("negative pre-trigger wait should be refused")


def test_led_trigger_check_uses_ch0_only_low_risk_parameters():
    module = load_smoke_module()

    parameters = module.led_trigger_check_parameters()

    assert parameters.name == "led-trigger-check"
    assert parameters.channel == 0
    assert parameters.frequency_hz == 1000.0
    assert parameters.amplitude_v == 0.1
    assert parameters.offset_v == 0.0
    assert parameters.duration_s == 0.5
    assert parameters.frequency_hz != 1.975e6
    assert parameters.amplitude_v < 2.0

    config = module.led_trigger_check_wfg_config()
    assert config.running is True
    assert len(config.channels) == 1
    channel = config.channels[0]
    assert channel.channel_index == 0
    assert [configured_channel.channel_index for configured_channel in config.channels] == [0]
    assert channel.carrier.frequency_hz == 1000.0
    assert channel.carrier.amplitude_v == 0.1
    assert channel.trigger.sec_run == 0.5


def test_led_trigger_check_refuses_long_duration():
    module = load_smoke_module()

    try:
        module.led_trigger_check_parameters(60.0)
    except SystemExit as exc:
        assert "Refusing to use a long duration" in str(exc)
    else:
        raise AssertionError("long LED trigger duration should be refused")


def test_labview_acoustic_short_parameters_are_short_candidate():
    module = load_smoke_module()

    parameters = module.labview_acoustic_short_parameters()

    assert parameters.name == "labview-acoustic-short"
    assert parameters.channel == 0
    assert parameters.frequency_hz == 1.975e6
    assert parameters.amplitude_v == 2.0
    assert parameters.offset_v == 0.0
    assert parameters.duration_s == 0.5
    assert parameters.repeat_count == 1
    assert parameters.duration_s != 60.0

    config = module.ad2_output_wfg_config(parameters)
    assert config.running is True
    assert len(config.channels) == 1
    channel = config.channels[0]
    assert channel.channel_index == 0
    assert [configured_channel.channel_index for configured_channel in config.channels] == [0]
    assert channel.carrier.frequency_hz == 1.975e6
    assert channel.carrier.amplitude_v == 2.0
    assert channel.trigger.sec_run == 0.5
    assert channel.trigger.repeat_count == 1


def test_ad2_laser_path_reuses_existing_ch0_acoustic_workflow_path(capsys):
    module = load_smoke_module()
    parameters = module.labview_acoustic_short_parameters(2.0)

    module.print_ad2_laser_summary(True, parameters)

    output = capsys.readouterr().out
    assert module.LASER_AD2_CHANNEL == 0
    assert module.LASER_AD2_CHANNEL == parameters.channel
    assert "AD2-controlled laser path enabled" in output
    assert "separate laser backend: not used" in output
    assert "laser AD2 channel/line: CH0: existing AD2 WFG CH0 path in Application.run_experiment2" in output
    assert "laser follows AD2 output: CH0 1975000.0 Hz sine for 2.0 s" in output

    config = module.ad2_output_wfg_config(parameters)
    assert len(config.channels) == 1
    assert [configured_channel.channel_index for configured_channel in config.channels] == [0]


def test_labview_acoustic_short_refuses_full_labview_duration():
    module = load_smoke_module()

    for duration in (60.0, 61.0):
        try:
            module.labview_acoustic_short_parameters(duration)
        except SystemExit as exc:
            assert "Refusing to run the full LabVIEW acoustic duration" in str(exc)
        else:
            raise AssertionError("full LabVIEW duration should be refused")


def test_real_full_workflow_short_refuses_full_labview_duration_before_hardware(tmp_path):
    module = load_smoke_module()

    try:
        module.run_real_full_workflow_short(
            tmp_path,
            frames=20,
            exposure_ms=None,
            preset_name="labview-screenshot",
            apply_roi=True,
            valve_port="COM6",
            flush_enabled=True,
            duration_s=60.0,
        )
    except SystemExit as exc:
        assert "Refusing to run the full LabVIEW acoustic duration" in str(exc)
    else:
        raise AssertionError("full workflow should refuse 60 s before hardware construction")


def test_labview_acoustic_short_prints_warning_and_excludes_other_hardware(capsys):
    module = load_smoke_module()
    parameters = module.labview_acoustic_short_parameters()

    module.print_labview_acoustic_short_output_parameters(parameters)

    output = capsys.readouterr().out
    assert "WARNING: LabVIEW acoustic candidate frequency/amplitude" in output
    assert "frequency_hz: 1975000.0" in output
    assert "amplitude_v: 2.0" in output
    assert "duration_s: 0.5" in output
    assert "original LabVIEW experiment run_s: 60.0" in output
    assert "camera: not used" in output
    assert "pump: not used" in output
    assert "valve: not used" in output
    assert "Qmix: not used" in output
    assert "Z-stage: not used" in output
    assert "Thorlabs/APT: not used" in output
    assert "Prior COM7: not used" in output


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
